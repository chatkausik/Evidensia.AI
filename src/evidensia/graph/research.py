from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from evidensia.agents import EvidenceExtractor, ResearchPlanner, SufficiencyEvaluator, SynthesisEngine
from evidensia.models import AgentEvent, ResearchState, SubQuestion
from evidensia.retrieval import HybridSearcher, LocalKnowledgeIndex


class GraphState(TypedDict, total=False):
    run_id: str
    question: str
    depth: Literal["quick", "standard", "deep"]
    namespace: str
    metadata_filters: dict[str, str | int | list[str]]
    provider_manifest: dict[str, str]
    research_plan: dict[str, Any] | None
    sub_questions: list[dict[str, Any]]
    search_queries: list[str]
    retrieved_evidence: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    citation_verifications: list[dict[str, Any]]
    assessment: dict[str, Any] | None
    missing_evidence: list[str]
    iterations: int
    max_iterations: int
    confidence: float
    final_report: dict[str, Any] | None
    status: str
    error: str | None


class ResearchOrchestrator:
    """LangGraph corrective-retrieval workflow with validated node boundaries."""

    def __init__(
        self,
        index: LocalKnowledgeIndex,
        searcher: HybridSearcher | None = None,
        synthesis: SynthesisEngine | None = None,
        provider_manifest: dict[str, str] | None = None,
    ) -> None:
        self.index = index
        self.searcher = searcher or HybridSearcher(index)
        self.planner = ResearchPlanner()
        self.extractor = EvidenceExtractor()
        self.sufficiency = SufficiencyEvaluator()
        self.synthesis = synthesis or SynthesisEngine()
        self.provider_manifest = provider_manifest or {}
        self.graph = self._build_graph()

    def initial_state(
        self,
        run_id: str,
        question: str,
        depth: str,
        *,
        namespace: str = "open-research",
        metadata_filters: dict[str, str | int | list[str]] | None = None,
    ) -> ResearchState:
        max_iterations = {"quick": 1, "standard": 3, "deep": 4}[depth]
        return ResearchState(
            run_id=run_id,
            question=question,
            depth=depth,
            namespace=namespace,
            metadata_filters=metadata_filters or {},
            provider_manifest=self.provider_manifest,
            max_iterations=max_iterations,
        )

    def run(
        self,
        initial: ResearchState,
        on_event: Callable[[AgentEvent, ResearchState], None] | None = None,
    ) -> ResearchState:
        current = initial.model_dump(mode="python")
        self._emit(initial.run_id, "research.started", "Research run started", {}, initial, on_event)
        try:
            for update_batch in self.graph.stream(current, stream_mode="updates"):
                for node, update in update_batch.items():
                    if isinstance(update, dict):
                        current.update(update)
                    validated = ResearchState.model_validate(current)
                    event_type, message = self._event_for_node(node, validated)
                    self._emit(validated.run_id, event_type, message, self._event_data(node, validated), validated, on_event)
            return ResearchState.model_validate(current)
        except Exception as exc:
            failed = ResearchState.model_validate({**current, "status": "failed", "error": str(exc)})
            self._emit(failed.run_id, "research.failed", str(exc), {}, failed, on_event)
            return failed

    def _build_graph(self):
        builder = StateGraph(GraphState)
        builder.add_node("plan", self._plan)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("assess", self._assess)
        builder.add_node("rewrite", self._rewrite)
        builder.add_node("synthesize", self._synthesize)
        builder.add_node("verify", self._verify)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "retrieve")
        builder.add_edge("retrieve", "assess")
        builder.add_conditional_edges("assess", self._route_after_assessment)
        builder.add_edge("rewrite", "retrieve")
        builder.add_edge("synthesize", "verify")
        builder.add_edge("verify", END)
        return builder.compile()

    def _plan(self, state: GraphState) -> dict[str, Any]:
        validated = ResearchState.model_validate(state)
        plan = self.planner.create_plan(validated.question, validated.depth)
        return {
            "research_plan": plan.model_dump(mode="python"),
            "sub_questions": [item.model_dump(mode="python") for item in plan.sub_questions],
            "search_queries": [item.question for item in plan.sub_questions],
            "status": "retrieving",
        }

    def _retrieve(self, state: GraphState) -> dict[str, Any]:
        validated = ResearchState.model_validate(state)
        evidence = list(validated.retrieved_evidence)
        existing = {item.evidence_id for item in evidence}
        covered = {item.sub_question_id for item in evidence}
        open_questions = [item for item in validated.sub_questions if item.id not in covered]
        for index, query in enumerate(validated.search_queries):
            target = next((item for item in validated.sub_questions if item.question == query), None)
            if target is None:
                target = open_questions[index % len(open_questions)] if open_questions else validated.sub_questions[min(index, len(validated.sub_questions) - 1)]
            debug = self.searcher.search(query, limit=5, metadata_filters=validated.metadata_filters)
            for item in self.extractor.extract(target, debug.reranked, limit=3):
                if item.evidence_id not in existing:
                    evidence.append(item)
                    existing.add(item.evidence_id)
        completed_ids = {item.sub_question_id for item in evidence}
        questions = [item.model_copy(update={"completed": item.id in completed_ids}) for item in validated.sub_questions]
        return {
            "retrieved_evidence": [item.model_dump(mode="python") for item in evidence],
            "sub_questions": [item.model_dump(mode="python") for item in questions],
            "iterations": validated.iterations + 1,
            "status": "evaluating",
        }

    def _assess(self, state: GraphState) -> dict[str, Any]:
        validated = ResearchState.model_validate(state)
        assessment = self.sufficiency.assess(validated.sub_questions, validated.retrieved_evidence, validated.depth)
        confidence = 0.5 * assessment.coverage_score + 0.3 * assessment.diversity_score + 0.2 * assessment.contradiction_coverage
        return {
            "assessment": assessment.model_dump(mode="python"),
            "missing_evidence": assessment.missing_information,
            "confidence": confidence,
        }

    @staticmethod
    def _route_after_assessment(state: GraphState) -> Literal["rewrite", "synthesize"]:
        validated = ResearchState.model_validate(state)
        if validated.assessment and validated.assessment.sufficient:
            return "synthesize"
        if validated.iterations >= validated.max_iterations:
            return "synthesize"
        return "rewrite"

    def _rewrite(self, state: GraphState) -> dict[str, Any]:
        validated = ResearchState.model_validate(state)
        suggestions = validated.assessment.suggested_queries if validated.assessment else []
        if not suggestions:
            suggestions = [f"{validated.question} empirical results limitations counter evidence"]
        expanded = [f"{query} independent study benchmark" for query in suggestions]
        return {"search_queries": expanded[:5], "status": "retrieving"}

    def _synthesize(self, state: GraphState) -> dict[str, Any]:
        validated = ResearchState.model_validate(state)
        claims = self.synthesis.build_claims(validated.retrieved_evidence)
        return {"claims": [item.model_dump(mode="python") for item in claims], "status": "verifying"}

    def _verify(self, state: GraphState) -> dict[str, Any]:
        validated = ResearchState.model_validate(state)
        verifications = self.synthesis.verify(validated.claims, validated.retrieved_evidence, self.index)
        report = self.synthesis.report(
            validated.question,
            validated.claims,
            validated.retrieved_evidence,
            verifications,
            validated.missing_evidence,
        )
        return {
            "citation_verifications": [item.model_dump(mode="python") for item in verifications],
            "final_report": report.model_dump(mode="python"),
            "confidence": report.confidence_score,
            "status": "completed",
        }

    @staticmethod
    def _emit(
        run_id: str,
        event_type: str,
        message: str,
        data: dict[str, Any],
        state: ResearchState,
        callback: Callable[[AgentEvent, ResearchState], None] | None,
    ) -> None:
        if callback:
            callback(
                AgentEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:16]}",
                    run_id=run_id,
                    type=event_type,
                    message=message,
                    data=data,
                ),
                state,
            )

    @staticmethod
    def _event_for_node(node: str, state: ResearchState) -> tuple[str, str]:
        mapping = {
            "plan": ("plan.created", f"Created {len(state.sub_questions)} research tasks"),
            "retrieve": ("retrieval.completed", f"Retrieved {len(state.retrieved_evidence)} evidence spans in cycle {state.iterations}"),
            "assess": ("evidence.assessed", "Assessed coverage, source diversity, and counter-evidence"),
            "rewrite": ("retrieval.retry", "Rewrote queries for missing evidence"),
            "synthesize": ("synthesis.started", f"Synthesized {len(state.claims)} candidate claims"),
            "verify": ("research.completed", "Verified citations and completed the research report"),
        }
        return mapping.get(node, (f"research.{node}", node.replace("_", " ").title()))

    @staticmethod
    def _event_data(node: str, state: ResearchState) -> dict[str, Any]:
        if node == "assess" and state.assessment:
            return state.assessment.model_dump(mode="json")
        if node == "retrieve":
            return {"evidence_count": len(state.retrieved_evidence), "iteration": state.iterations}
        if node == "plan":
            return {"sub_questions": [item.model_dump(mode="json") for item in state.sub_questions]}
        if node == "verify":
            return {"confidence": state.confidence, "claim_count": len(state.claims)}
        return {}
