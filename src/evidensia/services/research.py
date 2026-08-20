from __future__ import annotations

import threading
import uuid

from evidensia.graph import ResearchOrchestrator
from evidensia.models import AgentEvent, ResearchRequest, ResearchState
from evidensia.retrieval import LocalKnowledgeIndex


class ResearchRunService:
    def __init__(self, index: LocalKnowledgeIndex) -> None:
        self.orchestrator = ResearchOrchestrator(index)
        self.runs: dict[str, ResearchState] = {}
        self.events: dict[str, list[AgentEvent]] = {}
        self._lock = threading.RLock()

    def create(self, request: ResearchRequest) -> ResearchState:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        state = self.orchestrator.initial_state(run_id, request.question, request.depth)
        with self._lock:
            self.runs[run_id] = state
            self.events[run_id] = []
        return state

    def execute(self, run_id: str) -> ResearchState:
        with self._lock:
            state = self.runs[run_id]

        def capture(event: AgentEvent, snapshot: ResearchState) -> None:
            with self._lock:
                self.events[run_id].append(event)
                self.runs[run_id] = snapshot

        final = self.orchestrator.run(state, capture)
        with self._lock:
            self.runs[run_id] = final
        return final

    def get(self, run_id: str) -> ResearchState | None:
        with self._lock:
            return self.runs.get(run_id)

    def get_events(self, run_id: str, after: int = 0) -> list[AgentEvent]:
        with self._lock:
            return list(self.events.get(run_id, [])[after:])
