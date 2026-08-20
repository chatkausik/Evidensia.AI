from evidensia.api import ApplicationContainer
from evidensia.models import ResearchRequest


def test_corrective_research_produces_verified_report() -> None:
    container = ApplicationContainer(seed_demo=True)
    request = ResearchRequest(
        question="Does agentic RAG outperform traditional RAG for multi-hop question answering, and what are the trade-offs?",
        depth="standard",
        run_synchronously=True,
    )
    state = container.research.create(request)
    result = container.research.execute(state.run_id)

    assert result.status == "completed", result.error
    assert result.research_plan is not None
    assert len(result.sub_questions) >= 4
    assert result.iterations >= 1
    assert result.retrieved_evidence
    assert result.claims
    assert result.final_report is not None
    assert result.final_report.sources
    assert all(check.valid_source for check in result.citation_verifications)
    assert any(event.type == "research.completed" for event in container.research.events[state.run_id])

