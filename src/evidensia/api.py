from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Annotated

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from evidensia import __version__
from evidensia.api_models import (
    EvaluationRequest,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    PaperDiscoveryRequest,
    PaperImportRequest,
    SearchRequest,
)
from evidensia.evals import EvaluationRunner
from evidensia.models import (
    AgentEvent,
    DocumentRecord,
    ExperimentResult,
    PaperDiscoveryResponse,
    PaperImportResponse,
    ResearchRequest,
    ResearchState,
)
from evidensia.retrieval import HybridSearcher
from evidensia.services.knowledge import KnowledgeService
from evidensia.services.paper_discovery import PaperDiscoveryService
from evidensia.services.research import ResearchRunService


class ApplicationContainer:
    def __init__(self, seed_demo: bool = True, data_dir: str | None = None) -> None:
        self.knowledge = KnowledgeService(storage_dir=data_dir)
        self.discovery = PaperDiscoveryService(self.knowledge)
        self.searcher = HybridSearcher(self.knowledge.index)
        self.research = ResearchRunService(self.knowledge.index)
        self.evaluator = EvaluationRunner(self.knowledge.index, self.searcher)
        self.experiments: list[ExperimentResult] = []
        self.feedback: dict[str, list[FeedbackRequest]] = {}
        if seed_demo:
            self._seed_demo_sources()

    def _seed_demo_sources(self) -> None:
        sources = {
            "agentic-rag-benchmark-2025.md": """# Agentic Retrieval for Multi-Hop Question Answering
Authors: Mira Chen, Samuel Ortiz
2025

## Abstract
We compare a standard retrieval-augmented generation baseline with an agentic retrieval loop on HotpotQA and MuSiQue. Agentic retrieval decomposes questions and performs targeted follow-up search.

## Results
On HotpotQA, the agentic system improved answer exact match from 61.2 to 69.8 and Recall@10 from 78.4 to 89.1. Gains were concentrated in questions that required evidence from three or more passages. Single-hop questions improved by less than one point.

## Costs and limitations
The agentic system required 2.7 times more model calls and median latency increased from 1.8 seconds to 5.1 seconds. Results come from two public benchmarks and may not transfer to enterprise corpora with access controls or rapidly changing documents.
""",
            "negative-results-2025.md": """# When Iterative Retrieval Does Not Help
Authors: Priya Raman and Elias Ford
2025

## Evaluation
We evaluated iterative agentic RAG against a tuned hybrid RAG baseline on FEVER and an internal technical-support corpus. The difference on FEVER was not statistically significant after controlling for reranking quality. On the support corpus, repeated retrieval introduced irrelevant passages and answer accuracy declined by 1.4 points.

## Discussion
However, multi-hop cases with a failed initial retrieval did benefit. The main limitation was query drift: later searches amplified an incorrect early hypothesis. Strong stopping rules and explicit counter-evidence search reduced but did not eliminate this failure mode.
""",
            "hybrid-retrieval-methods.md": """# Reliable Hybrid Retrieval Systems
Authors: Noor Patel
2024

## Methodology
Dense retrieval captures paraphrases while BM25 preserves exact identifiers and benchmark names. Reciprocal rank fusion combines both rankings without requiring comparable raw scores. A cross-encoder then reranks the fused candidate set for precision.

## Experiments
Across a 300-question enterprise evaluation set, dense retrieval reached 0.79 Recall@10, BM25 reached 0.71, and hybrid RRF reached 0.88. Cross-encoder reranking improved NDCG@10 from 0.81 to 0.90 but did not change candidate recall.

## Limitations
Reranking cannot recover a relevant document that neither first-stage retriever returns. Evaluation labels also become stale when the underlying knowledge base changes.
""",
        }
        for filename, content in sources.items():
            self.knowledge.ingest(filename, content.encode(), "text/markdown", f"demo://{filename}")


def create_app(*, seed_demo: bool = True, data_dir: str | None = None) -> FastAPI:
    application = FastAPI(
        title="Evidensia API",
        description="Autonomous research and evidence intelligence",
        version=__version__,
    )
    application.state.container = ApplicationContainer(seed_demo=seed_demo, data_dir=data_dir)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def container() -> ApplicationContainer:
        return application.state.container

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @application.get("/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        current = container()
        return HealthResponse(
            status="ready",
            version=__version__,
            details={
                "documents": len(current.knowledge.documents),
                "chunks": len(current.knowledge.index.all()),
                "persistent_library": current.knowledge.storage_dir is not None,
            },
        )

    @application.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        current = container()
        completed = sum(run.status == "completed" for run in current.research.runs.values())
        return (
            "# TYPE evidensia_documents gauge\n"
            f"evidensia_documents {len(current.knowledge.documents)}\n"
            "# TYPE evidensia_research_runs gauge\n"
            f"evidensia_research_runs {len(current.research.runs)}\n"
            "# TYPE evidensia_research_completed gauge\n"
            f"evidensia_research_completed {completed}\n"
        )

    @application.post("/v1/documents", response_model=DocumentRecord, status_code=201)
    async def upload_document(
        file: Annotated[UploadFile, File(description="PDF, Markdown, HTML, or text document")],
        source_uri: Annotated[str | None, Form()] = None,
    ) -> DocumentRecord:
        content = await file.read()
        if not content:
            raise HTTPException(400, "The uploaded document is empty")
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(413, "Documents are limited to 25 MB in the local build")
        record = container().knowledge.ingest(
            file.filename or "document.txt",
            content,
            file.content_type or "application/octet-stream",
            source_uri,
        )
        if record.status == "failed":
            raise HTTPException(422, record.error or "Document parsing failed")
        return record

    @application.get("/v1/documents", response_model=list[DocumentRecord])
    def list_documents() -> list[DocumentRecord]:
        return container().knowledge.list_documents()

    @application.get("/v1/documents/{document_id}", response_model=DocumentRecord)
    def get_document(document_id: str) -> DocumentRecord:
        record = container().knowledge.documents.get(document_id)
        if not record:
            raise HTTPException(404, "Document not found")
        return record

    @application.delete("/v1/documents/{document_id}", status_code=204)
    def delete_document(document_id: str) -> None:
        if not container().knowledge.delete(document_id):
            raise HTTPException(404, "Document not found")

    @application.post("/v1/documents/{document_id}/reindex", response_model=DocumentRecord)
    def reindex_document(document_id: str) -> DocumentRecord:
        record = container().knowledge.reindex(document_id)
        if not record:
            raise HTTPException(404, "Document not found")
        return record

    @application.post("/v1/search", response_model=list)
    def search(request: SearchRequest) -> list:
        return container().searcher.search(
            request.query,
            limit=request.limit,
            metadata_filters=request.metadata_filters,
        ).reranked

    @application.post("/v1/search/debug")
    def search_debug(request: SearchRequest):
        return container().searcher.search(
            request.query,
            limit=request.limit,
            metadata_filters=request.metadata_filters,
        )

    @application.post("/v1/sources/discover", response_model=PaperDiscoveryResponse)
    def discover_sources(request: PaperDiscoveryRequest) -> PaperDiscoveryResponse:
        return container().discovery.discover(request)

    @application.post("/v1/sources/import", response_model=PaperImportResponse, status_code=201)
    def import_sources(request: PaperImportRequest) -> PaperImportResponse:
        return container().discovery.import_papers(request.paper_ids, full_text=request.full_text)

    @application.post("/v1/research", response_model=ResearchState, status_code=202)
    def create_research(request: ResearchRequest, background_tasks: BackgroundTasks) -> ResearchState:
        service = container().research
        state = service.create(request)
        if request.run_synchronously:
            return service.execute(state.run_id)
        background_tasks.add_task(service.execute, state.run_id)
        return state

    @application.get("/v1/research/{run_id}", response_model=ResearchState)
    def get_research(run_id: str) -> ResearchState:
        state = container().research.get(run_id)
        if not state:
            raise HTTPException(404, "Research run not found")
        return state

    @application.get("/v1/research/{run_id}/evidence")
    def get_evidence(run_id: str):
        state = container().research.get(run_id)
        if not state:
            raise HTTPException(404, "Research run not found")
        return state.retrieved_evidence

    @application.get("/v1/research/{run_id}/events")
    async def get_events(
        run_id: str,
        stream: Annotated[bool, Query()] = False,
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        service = container().research
        if not service.get(run_id):
            raise HTTPException(404, "Research run not found")
        offset = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0
        if not stream:
            return service.get_events(run_id, offset)

        async def event_stream() -> AsyncIterator[str]:
            cursor = offset
            while True:
                events = service.get_events(run_id, cursor)
                for event in events:
                    payload = event.model_dump(mode="json")
                    yield f"id: {cursor}\nevent: {event.type}\ndata: {json.dumps(payload)}\n\n"
                    cursor += 1
                state = service.get(run_id)
                if state and state.status in {"completed", "failed"} and not service.get_events(run_id, cursor):
                    break
                await asyncio.sleep(0.15)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @application.post("/v1/research/{run_id}/feedback", response_model=FeedbackResponse)
    def submit_feedback(run_id: str, request: FeedbackRequest) -> FeedbackResponse:
        if not container().research.get(run_id):
            raise HTTPException(404, "Research run not found")
        container().feedback.setdefault(run_id, []).append(request)
        return FeedbackResponse()

    @application.post("/v1/evals/run")
    def run_evaluation(request: EvaluationRequest):
        current = container()
        if request.run_ablation:
            results = current.evaluator.ablation(request.cases, request.k)
            current.experiments.extend(results)
            return results
        result = current.evaluator.run(request.cases, request.pipeline, request.k)
        current.experiments.append(result)
        return result

    @application.get("/v1/evals/experiments", response_model=list[ExperimentResult])
    def list_experiments() -> list[ExperimentResult]:
        return container().experiments

    return application


app = create_app(seed_demo=False, data_dir=os.getenv("EVIDENSIA_DATA_DIR", ".evidensia_data"))


def run() -> None:
    uvicorn.run("evidensia.api:app", host="127.0.0.1", port=8001, reload=True)
