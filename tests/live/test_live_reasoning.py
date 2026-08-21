"""Opt-in test that the reasoning provider actually works against the real API.

Every other test in this suite stubs `transport`, so the request that OpenAI
sees is never exercised. That is a real blind spot: a schema the API rejects, a
retired model id, or a bad key all surface as a 400/401 at runtime, get caught by
the deterministic fallback, and produce a run that looks entirely healthy.

Skipped unless EVIDENSIA_LIVE_TESTS=1, so CI stays hermetic and free. Run it
after changing a schema, a model id, or the request shape:

    EVIDENSIA_LIVE_TESTS=1 pytest tests/live -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("EVIDENSIA_LIVE_TESTS") != "1",
    reason="Set EVIDENSIA_LIVE_TESTS=1 to run tests that call the provider API.",
)


def _provider():
    from evidensia.agents.openai_reasoning import OpenAIResearchProvider

    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        pytest.skip("OPENAI_API_KEY is not set")
    return OpenAIResearchProvider(key, model=os.getenv("EVIDENSIA_LLM_MODEL", "gpt-5.4-mini"))


def _evidence():
    from evidensia.models import Citation, Evidence

    text = (
        "We evaluated iterative agentic RAG against a tuned hybrid baseline on FEVER. "
        "The difference on FEVER was not statistically significant after controlling "
        "for reranking quality."
    )
    return Evidence(
        evidence_id="ev_1",
        sub_question_id="sq_1",
        claim=text,
        supporting_text=text,
        evidence_type="supporting",
        relevance=0.9,
        source_quality=0.8,
        confidence=0.85,
        citation=Citation(
            citation_id="cit_1",
            document_id="doc_1",
            chunk_id="chk_1",
            title="When Iterative Retrieval Does Not Help",
            section="Evaluation",
            quoted_text=text,
        ),
    )


def test_plan_schema_is_accepted_by_the_live_api() -> None:
    """Catches a schema the provider rejects, a retired model id, or a bad key."""
    from evidensia.models import ResearchPlan, SubQuestion

    fallback = ResearchPlan(
        main_question="Does agentic RAG improve multi-hop QA?",
        interpretation="baseline",
        hypotheses=["baseline"],
        sub_questions=[
            SubQuestion(id="sq_01", question="What is agentic RAG?", purpose="scope", priority="critical")
        ],
        expected_evidence=["benchmarks"],
        search_strategy="hybrid",
    )
    plan = _provider().plan("Does agentic RAG improve multi-hop QA?", "quick", fallback)

    assert plan.sub_questions, "the live call returned no sub-questions"
    # A generated plan should differ from the deterministic baseline it was given.
    assert plan.interpretation != "baseline"


def test_verification_can_reject_a_claim_the_passage_contradicts() -> None:
    """The substantive check: real inference, not lexical overlap.

    The passage reports no significant difference; the claim asserts a
    significant improvement. A lexical scorer cannot tell these apart because
    they share most of their vocabulary.
    """
    from evidensia.models import ResearchClaim

    evidence = _evidence()
    claim = ResearchClaim(
        claim_id="claim_1",
        statement="Iterative agentic RAG significantly improves accuracy on FEVER.",
        evidence_ids=["ev_1"],
        confidence=0.8,
        status="supported",
    )
    passages = {("claim_1", "ev_1"): evidence.supporting_text}

    result = _provider().verify_claims([claim], [evidence], passages)

    assert ("claim_1", "ev_1") in result, "the live call returned no verdict for the pair"
    grounded, score, _issue = result[("claim_1", "ev_1")]
    assert grounded is False, "a passage reporting no significant difference must not ground the opposite claim"
    assert 0.0 <= score <= 1.0


def test_a_healthy_run_reports_served_by_model() -> None:
    """End to end: the diagnostics endpoint must not say 'degraded' when it works."""
    from fastapi.testclient import TestClient

    from evidensia.api import create_app

    client = TestClient(create_app(seed_demo=True, data_dir=None))
    created = client.post(
        "/v1/research",
        json={"question": "Does agentic RAG improve multi-hop QA?", "depth": "quick", "run_synchronously": True},
    )
    assert created.status_code == 202, created.text
    diagnostics = client.get(f"/v1/research/{created.json()['run_id']}/diagnostics").json()

    if diagnostics["reasoning_configured"] == "deterministic-fallback":
        pytest.skip("No reasoning provider configured in this environment")
    assert diagnostics["served_by"] == "model", (
        f"model path degraded: {diagnostics['reasoning_fallbacks']}"
    )
