from __future__ import annotations

import threading
import uuid

from evidensia.agents import ResearchPlanner, SynthesisEngine
from evidensia.graph import ResearchOrchestrator
from evidensia.models import AgentEvent, ResearchRequest, ResearchState
from evidensia.persistence import LocalStateStore
from evidensia.retrieval import HybridSearcher, LocalKnowledgeIndex


class ResearchRunService:
    def __init__(
        self,
        index: LocalKnowledgeIndex,
        *,
        searcher: HybridSearcher | None = None,
        planner: ResearchPlanner | None = None,
        synthesis: SynthesisEngine | None = None,
        store: LocalStateStore | None = None,
        provider_manifest: dict[str, str] | None = None,
    ) -> None:
        self.store = store or LocalStateStore()
        self.orchestrator = ResearchOrchestrator(
            index,
            searcher=searcher,
            planner=planner,
            synthesis=synthesis,
            provider_manifest=provider_manifest,
        )
        self.runs: dict[str, ResearchState] = {}
        self.events: dict[str, list[AgentEvent]] = {}
        self._lock = threading.RLock()
        for payload in self.store.list_runs():
            state = ResearchState.model_validate(payload)
            self.runs[state.run_id] = state
            self.events[state.run_id] = [
                AgentEvent.model_validate(event) for event in self.store.list_events(state.run_id)
            ]

    def create(self, request: ResearchRequest) -> ResearchState:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        filters: dict[str, str | int | list[str]] = {}
        if request.date_from:
            filters["publication_year_gte"] = request.date_from.year
        if request.date_to:
            filters["publication_year_lte"] = request.date_to.year
        if request.allowed_sources:
            filters["allowed_sources"] = request.allowed_sources
        if request.namespace != "open-research":
            collection = self.store.get_named("collections", "collection_id", request.namespace)
            if collection:
                filters["document_ids"] = collection.get("document_ids", [])
        state = self.orchestrator.initial_state(
            run_id,
            request.question,
            request.depth,
            namespace=request.namespace,
            metadata_filters=filters,
        )
        with self._lock:
            self.runs[run_id] = state
            self.events[run_id] = []
            self.store.save_run(run_id, state)
        return state

    def execute(self, run_id: str) -> ResearchState:
        with self._lock:
            state = self.runs[run_id]

        def capture(event: AgentEvent, snapshot: ResearchState) -> None:
            with self._lock:
                self.events[run_id].append(event)
                self.runs[run_id] = snapshot
                self.store.save_event(run_id, len(self.events[run_id]) - 1, event)
                self.store.save_run(run_id, snapshot)

        final = self.orchestrator.run(state, capture)
        with self._lock:
            self.runs[run_id] = final
            self.store.save_run(run_id, final)
        return final

    def get(self, run_id: str) -> ResearchState | None:
        with self._lock:
            return self.runs.get(run_id)

    def get_events(self, run_id: str, after: int = 0) -> list[AgentEvent]:
        with self._lock:
            return list(self.events.get(run_id, [])[after:])
