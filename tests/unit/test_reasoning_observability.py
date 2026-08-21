"""A failing reasoning provider must be visible, not silent.

The deterministic fallback is the right behaviour — a broken model provider
should not take down a research run. The hazard is that it is *indistinguishable*
from success: the run completes, the report renders, `provider_manifest` still
names the configured model, and the only trace is a log line that previously
printed the exception class name and discarded the reason.

That is how a live-API failure hides behind a green test suite.
"""

from __future__ import annotations

import logging

import pytest

from evidensia.agents.openai_reasoning import ResearchModelError
from evidensia.agents.synthesis import SynthesisEngine
from evidensia.models import ChunkRecord, Citation, Evidence, ResearchClaim
from evidensia.retrieval.index import LocalKnowledgeIndex


class _BrokenReasoning:
    """A provider that fails the way a rejected request or bad key fails."""

    name = "openai:broken"

    def __init__(self, message: str = "OpenAI returned HTTP 400") -> None:
        self.message = message

    def plan(self, *args, **kwargs):
        raise ResearchModelError(self.message)

    def synthesize_claims(self, *args, **kwargs):
        raise ResearchModelError(self.message)

    def verify_claims(self, *args, **kwargs):
        raise ResearchModelError(self.message)

    def compose_report(self, *args, **kwargs):
        raise ResearchModelError(self.message)


def _chunk() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="chk_1",
        document_id="doc_1",
        chunk_type="retrieval",
        title="A Study",
        section="Results",
        text="Hybrid reciprocal rank fusion reached 0.88 recall on the evaluation set.",
        token_count=12,
        chunk_index=0,
    )


def _evidence() -> Evidence:
    text = _chunk().text
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
            title="A Study",
            section="Results",
            quoted_text=text,
        ),
    )


def test_synthesis_falls_back_but_records_why() -> None:
    engine = SynthesisEngine(reasoning=_BrokenReasoning())
    diagnostics: list[str] = []

    claims = engine.build_claims([_evidence()], "Does RRF help?", diagnostics)

    # The run still produces an answer — the fallback is intentional.
    assert claims
    # ...but it is no longer silent about how that answer was produced.
    assert len(diagnostics) == 1
    assert diagnostics[0].startswith("synthesis:")
    assert "HTTP 400" in diagnostics[0], "the cause must survive, not just the exception type"


def test_verification_fallback_is_recorded() -> None:
    index = LocalKnowledgeIndex()
    index.upsert([_chunk()])
    engine = SynthesisEngine(reasoning=_BrokenReasoning("OpenAI could not return a valid response"))
    claim = ResearchClaim(
        claim_id="claim_1",
        statement=_chunk().text,
        evidence_ids=["ev_1"],
        confidence=0.8,
        status="supported",
    )
    diagnostics: list[str] = []

    engine.verify([claim], [_evidence()], index, diagnostics)

    assert any(entry.startswith("verification:") for entry in diagnostics)
    assert "could not return a valid response" in diagnostics[0]


def test_healthy_provider_records_nothing() -> None:
    """No fallback means an empty list, so `model_backed` is a real signal."""
    engine = SynthesisEngine()  # no reasoning provider configured at all
    diagnostics: list[str] = []
    engine.build_claims([_evidence()], "Does RRF help?", diagnostics)
    assert diagnostics == []


def test_failure_reason_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    engine = SynthesisEngine(reasoning=_BrokenReasoning("OpenAI returned HTTP 401"))
    with caplog.at_level(logging.WARNING, logger="evidensia.agents.synthesis"):
        engine.build_claims([_evidence()], "Does RRF help?")

    message = caplog.text
    assert "HTTP 401" in message, (
        "logging type(exc).__name__ made a 401, a 400 and a timeout indistinguishable"
    )
