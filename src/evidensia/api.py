from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from evidensia import __version__
from evidensia.api_models import (
    EvaluationRequest,
    CollectionRequest,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    PaperDiscoveryRequest,
    PaperImportRequest,
    PaperCompareRequest,
    SavedSearchRequest,
    SearchRequest,
)
from evidensia.evals import EvaluationRunner
from evidensia.agents import SynthesisEngine
from evidensia.models import (
    AgentEvent,
    CitationGraph,
    DocumentRecord,
    ExperimentResult,
    PaperDiscoveryResponse,
    PaperComparison,
    PaperImportResponse,
    ResearchCollection,
    ResearchRequest,
    ResearchState,
    SavedSearch,
)
from evidensia.persistence import LocalStateStore
from evidensia.providers import providers_from_environment
from evidensia.retrieval import HybridSearcher, LocalKnowledgeIndex
from evidensia.services.knowledge import KnowledgeService
from evidensia.services.paper_discovery import PaperDiscoveryService
from evidensia.services.research import ResearchRunService
from evidensia.services.exports import export_research
from evidensia.connectors.http import PaperSourceError


class ApplicationContainer:
    def __init__(self, seed_demo: bool = True, data_dir: str | None = None) -> None:
        self.providers = providers_from_environment()
        index = LocalKnowledgeIndex(self.providers.embedding)
        self.knowledge = KnowledgeService(index=index, storage_dir=data_dir)
        state_path = Path(data_dir) / "evidensia-state.sqlite3" if data_dir else None
        self.state_store = LocalStateStore(state_path)
        self.discovery = PaperDiscoveryService(self.knowledge)
        self.searcher = HybridSearcher(self.knowledge.index, self.providers.reranker)
        self.research = ResearchRunService(
            self.knowledge.index,
            searcher=self.searcher,
            synthesis=SynthesisEngine(self.providers.entailment),
            store=self.state_store,
            provider_manifest=self.providers.manifest,
        )
        self.evaluator = EvaluationRunner(self.knowledge.index, self.searcher)
        self.experiments: list[ExperimentResult] = [
            ExperimentResult.model_validate(payload) for payload in self.state_store.list_experiments()
        ]
        self.feedback: dict[str, list[FeedbackRequest]] = {}
        if seed_demo or data_dir:
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
        ids = {
            "agentic-rag-benchmark-2025.md": "demo-agentic",
            "negative-results-2025.md": "demo-negative",
            "hybrid-retrieval-methods.md": "demo-hybrid",
        }
        for filename, content in sources.items():
            self.knowledge.ingest(filename, content.encode(), "text/markdown", f"demo://{filename}", document_id=ids[filename])


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
                "providers": current.providers.manifest,
            },
        )

    @application.get("/v1/providers")
    def list_providers() -> dict[str, str]:
        return container().providers.manifest

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

    @application.post("/v1/sources/compare", response_model=list[PaperComparison])
    def compare_sources(request: PaperCompareRequest) -> list[PaperComparison]:
        return container().discovery.compare(request.paper_ids)

    @application.get("/v1/sources/{paper_id:path}/citation-graph", response_model=CitationGraph)
    def source_citation_graph(paper_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 15) -> CitationGraph:
        try:
            return container().discovery.citation_graph(paper_id, limit)
        except PaperSourceError as exc:
            raise HTTPException(502, str(exc)) from exc

    @application.get("/v1/saved-searches", response_model=list[SavedSearch])
    def list_saved_searches() -> list[SavedSearch]:
        return [SavedSearch.model_validate(payload) for payload in container().state_store.list_named("saved_searches")]

    @application.post("/v1/saved-searches", response_model=SavedSearch, status_code=201)
    def create_saved_search(request: SavedSearchRequest) -> SavedSearch:
        saved = SavedSearch(search_id=f"search_{uuid.uuid4().hex[:14]}", **request.model_dump())
        container().state_store.save_named("saved_searches", "search_id", saved.search_id, saved)
        return saved

    @application.post("/v1/saved-searches/{search_id}/run", response_model=PaperDiscoveryResponse)
    def run_saved_search(search_id: str) -> PaperDiscoveryResponse:
        payload = container().state_store.get_named("saved_searches", "search_id", search_id)
        if not payload:
            raise HTTPException(404, "Saved search not found")
        saved = SavedSearch.model_validate(payload)
        response = container().discovery.discover(PaperDiscoveryRequest(
            query=saved.query,
            date_from=saved.date_from,
            date_to=saved.date_to,
            providers=saved.providers,
            categories=saved.categories,
            open_access_only=saved.open_access_only,
        ))
        saved = saved.model_copy(update={"last_run_at": datetime.now(timezone.utc)})
        container().state_store.save_named("saved_searches", "search_id", saved.search_id, saved)
        return response

    @application.delete("/v1/saved-searches/{search_id}", status_code=204)
    def delete_saved_search(search_id: str) -> None:
        if not container().state_store.delete_named("saved_searches", "search_id", search_id):
            raise HTTPException(404, "Saved search not found")

    @application.get("/v1/collections", response_model=list[ResearchCollection])
    def list_collections() -> list[ResearchCollection]:
        return [ResearchCollection.model_validate(payload) for payload in container().state_store.list_named("collections")]

    @application.post("/v1/collections", response_model=ResearchCollection, status_code=201)
    def create_collection(request: CollectionRequest) -> ResearchCollection:
        missing = [document_id for document_id in request.document_ids if document_id not in container().knowledge.documents]
        if missing:
            raise HTTPException(422, f"Unknown documents: {', '.join(missing[:5])}")
        collection = ResearchCollection(collection_id=f"collection_{uuid.uuid4().hex[:14]}", **request.model_dump())
        container().state_store.save_named("collections", "collection_id", collection.collection_id, collection)
        return collection

    @application.delete("/v1/collections/{collection_id}", status_code=204)
    def delete_collection(collection_id: str) -> None:
        if not container().state_store.delete_named("collections", "collection_id", collection_id):
            raise HTTPException(404, "Collection not found")

    @application.post("/v1/research", response_model=ResearchState, status_code=202)
    def create_research(request: ResearchRequest, background_tasks: BackgroundTasks) -> ResearchState:
        service = container().research
        state = service.create(request)
        if request.run_synchronously:
            return service.execute(state.run_id)
        background_tasks.add_task(service.execute, state.run_id)
        return state

    @application.get("/v1/research", response_model=list[ResearchState])
    def list_research() -> list[ResearchState]:
        return list(container().research.runs.values())

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
        container().state_store.add_feedback(run_id, request)
        return FeedbackResponse()

    @application.get("/v1/research/{run_id}/export")
    def export_research_report(
        run_id: str,
        format: Annotated[Literal["markdown", "json", "bibtex", "ris"], Query()] = "markdown",
    ) -> Response:
        state = container().research.get(run_id)
        if not state:
            raise HTTPException(404, "Research run not found")
        content, media_type, filename = export_research(state, format)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @application.post("/v1/evals/run")
    def run_evaluation(request: EvaluationRequest):
        current = container()
        cases = request.cases or _load_gold_cases()
        if request.run_ablation:
            results = [
                result.model_copy(update={
                    "metadata": {**result.metadata, "dataset_name": request.dataset_name},
                })
                for result in current.evaluator.ablation(cases, request.k)
            ]
            current.experiments.extend(results)
            for result in results:
                current.state_store.add_experiment(result)
            return results
        evaluated = current.evaluator.run(cases, request.pipeline, request.k)
        result = evaluated.model_copy(update={
            "metadata": {**evaluated.metadata, "dataset_name": request.dataset_name},
        })
        current.experiments.append(result)
        current.state_store.add_experiment(result)
        return result

    @application.get("/v1/evals/experiments", response_model=list[ExperimentResult])
    def list_experiments() -> list[ExperimentResult]:
        return container().experiments

    @application.get("/v1/evals/gold")
    def get_gold_cases():
        return _load_gold_cases()

    return application


def _load_gold_cases():
    from evidensia.models import EvaluationCase

    path = Path(__file__).resolve().parents[2] / "datasets" / "gold" / "sample.jsonl"
    if not path.is_file():
        return []
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvaluationCase.model_validate_json(line))
    return cases


app = create_app(seed_demo=False, data_dir=os.getenv("EVIDENSIA_DATA_DIR", ".evidensia_data"))


def run() -> None:
    uvicorn.run("evidensia.api:app", host="127.0.0.1", port=8001, reload=True)
