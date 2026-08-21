from __future__ import annotations

from evidensia.models import ResearchReport, ResearchState
from evidensia.services.memory import DisabledLongTermMemory, Mem0LongTermMemory, memory_from_environment


class FakeMem0Client:
    def __init__(self) -> None:
        self.search_kwargs: dict = {}
        self.add_messages: list[dict[str, str]] = []
        self.add_kwargs: dict = {}

    def search(self, query: str, **kwargs):
        self.search_kwargs = {"query": query, **kwargs}
        return {
            "results": [
                {"id": "memory-1", "memory": "Prefers enterprise benchmark evidence", "score": 0.87},
                {"id": "memory-2", "text": "Interested in latency trade-offs", "score": "0.72"},
            ]
        }

    def add(self, messages, **kwargs):
        self.add_messages = messages
        self.add_kwargs = kwargs
        return {"status": "PENDING"}


def test_mem0_recall_uses_v3_user_filter_and_normalizes_results() -> None:
    client = FakeMem0Client()
    memory = Mem0LongTermMemory(client, top_k=4, threshold=0.3, timeout=1)

    results = memory.recall("agentic retrieval", "researcher-123")

    assert [item.text for item in results] == [
        "Prefers enterprise benchmark evidence",
        "Interested in latency trade-offs",
    ]
    assert client.search_kwargs == {
        "query": "agentic retrieval",
        "filters": {"user_id": "researcher-123"},
        "top_k": 4,
        "threshold": 0.3,
        "rerank": False,
    }


def test_memory_is_disabled_without_mem0_api_key(monkeypatch) -> None:
    monkeypatch.delenv("MEM0_API_KEY", raising=False)

    memory = memory_from_environment()

    assert isinstance(memory, DisabledLongTermMemory)
    assert memory.enabled is False


def test_mem0_write_back_contains_only_verified_report_summary() -> None:
    client = FakeMem0Client()
    memory = Mem0LongTermMemory(client, timeout=1)
    state = ResearchState(
        run_id="run_123",
        question="What does the evidence say about agentic retrieval?",
        depth="quick",
        status="completed",
        final_report=ResearchReport(
            research_question="What does the evidence say about agentic retrieval?",
            executive_summary="Verified evidence reports improved multi-hop retrieval.",
            conclusion="The improvement has a latency trade-off.",
            key_findings=["Recall improved in the indexed benchmark."],
            claims=[],
            limitations=["The indexed corpus is small."],
            unresolved_questions=[],
            confidence_score=0.82,
            sources=[],
        ),
    )

    assert memory.remember_research(state, "researcher-123") is True
    assert client.add_messages[0] == {"role": "user", "content": state.question}
    assert client.add_messages[1]["role"] == "assistant"
    assert "Verified research summary" in client.add_messages[1]["content"]
    assert client.add_kwargs == {
        "user_id": "researcher-123",
        "agent_id": "evidensia-research",
        "run_id": "run_123",
        "metadata": {
            "source": "evidensia",
            "category": "verified_research",
            "depth": "quick",
            "namespace": "open-research",
        },
    }
