from __future__ import annotations

import json

from evidensia.agents import OpenAIResearchProvider, ResearchPlanner, SynthesisEngine
from evidensia.api import create_app
from evidensia.models import Citation, CitationVerification, Evidence, ResearchReport
from evidensia.providers import providers_from_environment


def _evidence() -> Evidence:
    citation = Citation(
        citation_id="citation_1",
        document_id="doc_1",
        chunk_id="chunk_1",
        title="Agentic Retrieval Benchmark",
        section="Results",
        source_uri="https://example.org/paper",
        quoted_text="Agentic retrieval improved Recall@10 from 78.4 to 89.1.",
    )
    return Evidence(
        evidence_id="evidence_1",
        sub_question_id="sq_01",
        claim="Agentic retrieval improved Recall@10 from 78.4 to 89.1.",
        supporting_text="Agentic retrieval improved Recall@10 from 78.4 to 89.1.",
        evidence_type="supporting",
        relevance=0.95,
        source_quality=0.9,
        confidence=0.92,
        citation=citation,
    )


def test_openai_provider_uses_structured_evidence_bounded_workflow() -> None:
    captured: list[dict] = []

    def transport(payload: dict) -> dict:
        captured.append(payload)
        schema = payload["text"]["format"]["name"]
        responses = {
            "research_plan": {
                "interpretation": "A benchmark comparison requiring direct and counter-evidence.",
                "hypotheses": ["Measured gains may involve latency trade-offs."],
                "sub_questions": [
                    {"question": "What direct benchmark results were reported?", "purpose": "Measure outcomes", "priority": "critical", "evidence_types": ["results"]},
                    {"question": "Which costs or negative results qualify the finding?", "purpose": "Find counter-evidence", "priority": "high", "evidence_types": ["limitations"]},
                ],
                "expected_evidence": ["benchmark measurements", "limitations"],
                "search_strategy": "Retrieve direct comparisons and disconfirming studies.",
            },
            "evidence_claims": {
                "claims": [{
                    "statement": "Agentic retrieval improved Recall@10 in the supplied benchmark.",
                    "evidence_ids": ["evidence_1", "hallucinated_id"],
                    "opposing_evidence_ids": [],
                    "confidence": 0.9,
                    "status": "supported",
                }],
            },
            "claim_verification": {
                "verifications": [{
                    "claim_id": "placeholder",
                    "evidence_id": "evidence_1",
                    "grounded": True,
                    "score": 0.94,
                    "issue": None,
                }],
            },
            "research_report": {
                "executive_summary": "The supplied benchmark reports a material retrieval gain.",
                "conclusion": "The result is promising but remains bounded to the indexed evidence.",
                "key_findings": ["Recall@10 increased in the supplied benchmark."],
                "limitations": ["The evidence base is small."],
                "unresolved_questions": ["Does the result generalize?"],
                "confidence_score": 0.88,
            },
        }
        body = responses[schema]
        if schema == "claim_verification":
            body["verifications"][0]["claim_id"] = json.loads(payload["input"])["pairs"][0]["claim_id"]
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(body)}]}]}

    provider = OpenAIResearchProvider("test-key", model="gpt-5.4-mini", transport=transport)
    baseline = ResearchPlanner().create_plan("Does agentic retrieval improve multi-hop retrieval?", "quick")
    plan = provider.plan(
        baseline.main_question,
        "quick",
        baseline,
        ["The researcher prioritizes enterprise benchmarks."],
    )
    evidence = _evidence()
    claims = provider.synthesize_claims(baseline.main_question, [evidence])
    decisions = provider.verify_claims(
        claims,
        [evidence],
        {(claims[0].claim_id, evidence.evidence_id): evidence.supporting_text},
    )
    verification = CitationVerification(
        claim_id=claims[0].claim_id,
        citation_id=evidence.citation.citation_id,
        valid_source=True,
        entails_claim=True,
        citation_quality=0.93,
    )
    fallback = ResearchReport(
        research_question=baseline.main_question,
        executive_summary="Fallback summary.",
        conclusion="Fallback conclusion.",
        key_findings=[claims[0].statement],
        claims=claims,
        limitations=["Indexed corpus only."],
        unresolved_questions=[],
        confidence_score=0.8,
        sources=[evidence.citation],
    )
    report = provider.compose_report(
        baseline.main_question,
        claims,
        [evidence],
        [verification],
        [],
        [evidence.citation],
        fallback,
    )

    assert len(plan.sub_questions) == 2
    assert claims[0].evidence_ids == ["evidence_1"]
    assert decisions[(claims[0].claim_id, "evidence_1")][0] is True
    assert report.sources == [evidence.citation]
    assert report.confidence_score == 0.88
    assert {item["text"]["format"]["name"] for item in captured} == {
        "research_plan", "evidence_claims", "claim_verification", "research_report",
    }
    assert all(item["store"] is False and item["text"]["format"]["strict"] is True for item in captured)
    plan_input = json.loads(next(item for item in captured if item["text"]["format"]["name"] == "research_plan")["input"])
    assert plan_input["prior_memory_context"] == ["The researcher prioritizes enterprise benchmarks."]


def test_reasoning_failures_use_deterministic_fallbacks() -> None:
    class BrokenReasoning:
        name = "broken"

        def plan(self, *args, **kwargs):
            raise TimeoutError

        def synthesize_claims(self, *args, **kwargs):
            raise TimeoutError

        def verify_claims(self, *args, **kwargs):
            raise TimeoutError

        def compose_report(self, *args, **kwargs):
            raise TimeoutError

    question = "Does agentic retrieval improve multi-hop retrieval?"
    plan = ResearchPlanner(BrokenReasoning()).create_plan(question, "quick")
    claims = SynthesisEngine(reasoning=BrokenReasoning()).build_claims([_evidence()], question)

    assert plan.main_question == question
    assert len(plan.sub_questions) >= 2
    assert claims[0].evidence_ids == ["evidence_1"]


def test_openai_provider_is_enabled_only_when_key_is_configured(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert providers_from_environment().manifest["research"] == "deterministic-fallback"

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EVIDENSIA_OPENAI_MODEL", "gpt-5.4-mini")
    assert providers_from_environment().manifest["research"] == "openai:gpt-5.4-mini"
    application = create_app(seed_demo=False)
    orchestrator = application.state.container.research.orchestrator
    assert orchestrator.planner.reasoning is orchestrator.synthesis.reasoning
    assert orchestrator.provider_manifest["research"] == "openai:gpt-5.4-mini"
