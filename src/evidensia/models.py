from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentMetadata(StrictModel):
    document_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    topics: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    document_type: str
    extraction_confidence: float = Field(default=0.5, ge=0, le=1)


class DocumentRecord(StrictModel):
    document_id: str
    filename: str
    content_type: str
    source_uri: str | None = None
    status: DocumentStatus = DocumentStatus.QUEUED
    metadata: DocumentMetadata | None = None
    chunk_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    error: str | None = None


PaperProvider = Literal["arxiv", "openalex"]


class PaperDiscoveryRequest(StrictModel):
    query: str = Field(min_length=2, max_length=500)
    date_from: date = Field(default=date(2025, 1, 1))
    date_to: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())
    providers: list[PaperProvider] = Field(default_factory=lambda: ["arxiv", "openalex"], min_length=1)
    categories: list[str] = Field(default_factory=list, max_length=20)
    open_access_only: bool = True
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def valid_discovery_range(self) -> PaperDiscoveryRequest:
        if self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        self.providers = list(dict.fromkeys(self.providers))
        self.categories = list(dict.fromkeys(self.categories))
        invalid_categories = [
            category for category in self.categories
            if not re.fullmatch(r"[a-z-]+(?:\.[A-Za-z0-9-]+)?", category)
        ]
        if invalid_categories:
            raise ValueError(f"invalid arXiv categories: {', '.join(invalid_categories)}")
        return self


class DiscoveredPaper(StrictModel):
    paper_id: str
    providers: list[PaperProvider]
    external_ids: dict[str, str] = Field(default_factory=dict)
    title: str
    abstract: str
    authors: list[str] = Field(default_factory=list)
    published_at: date
    updated_at: date | None = None
    venue: str | None = None
    doi: str | None = None
    categories: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    landing_url: str
    pdf_url: str | None = None
    open_access: bool = False
    license: str | None = None
    publication_type: str = "unknown"
    is_preprint: bool = False
    version: str | None = None
    citation_count: int | None = Field(default=None, ge=0)


class PaperDiscoveryResponse(StrictModel):
    query: str
    providers: list[PaperProvider]
    papers: list[DiscoveredPaper]
    warnings: list[str] = Field(default_factory=list)


class PaperImportResponse(StrictModel):
    imported: list[DocumentRecord] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    abstract_fallbacks: list[str] = Field(default_factory=list)


class ChunkRecord(StrictModel):
    chunk_id: str
    document_id: str
    parent_chunk_id: str | None = None
    title: str
    section: str
    subsection: str | None = None
    chunk_type: Literal["parent", "retrieval", "evidence_span"]
    publication_year: int | None = None
    authors: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    text: str
    token_count: int = Field(ge=1)
    source_uri: str | None = None
    page_number: int | None = None
    chunk_index: int = Field(ge=0)


class QueryIntent(StrictModel):
    intent: Literal[
        "definition",
        "comparison",
        "benchmark",
        "methodology",
        "evidence",
        "multi_hop",
        "exploratory",
    ]
    keyword_specificity: float = Field(ge=0, le=1)
    semantic_complexity: float = Field(ge=0, le=1)
    requires_multi_hop: bool
    preferred_sections: list[str] = Field(default_factory=list)
    metadata_filters: dict[str, str | int | list[str]] = Field(default_factory=dict)


class RankedEvidence(StrictModel):
    chunk: ChunkRecord
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rrf_score: float = Field(default=0, ge=0)
    rerank_score: float = Field(default=0, ge=0, le=1)
    final_score: float = Field(default=0, ge=0)
    final_rank: int = Field(ge=1)


class SearchDebug(StrictModel):
    query: str
    intent: QueryIntent
    dense: list[RankedEvidence]
    sparse: list[RankedEvidence]
    fused: list[RankedEvidence]
    reranked: list[RankedEvidence]
    duration_ms: float = Field(ge=0)


class Citation(StrictModel):
    citation_id: str
    document_id: str
    chunk_id: str
    title: str
    page: int | None = None
    section: str
    source_uri: str | None = None
    quoted_text: str | None = None


class Evidence(StrictModel):
    evidence_id: str
    sub_question_id: str
    claim: str
    supporting_text: str
    evidence_type: Literal["supporting", "contradicting", "neutral"]
    relevance: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    citation: Citation


class SubQuestion(StrictModel):
    id: str
    question: str
    purpose: str
    priority: Literal["critical", "high", "medium", "low"]
    evidence_types: list[str] = Field(default_factory=list)
    completed: bool = False


class ResearchPlan(StrictModel):
    main_question: str
    interpretation: str
    hypotheses: list[str] = Field(default_factory=list)
    sub_questions: list[SubQuestion]
    expected_evidence: list[str] = Field(default_factory=list)
    search_strategy: str


class EvidenceAssessment(StrictModel):
    sufficient: bool
    coverage_score: float = Field(ge=0, le=1)
    diversity_score: float = Field(ge=0, le=1)
    contradiction_coverage: float = Field(ge=0, le=1)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)


class ResearchClaim(StrictModel):
    claim_id: str
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    opposing_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    status: Literal["supported", "mixed", "weak", "unsupported"]


class CitationVerification(StrictModel):
    claim_id: str
    citation_id: str
    valid_source: bool
    entails_claim: bool
    citation_quality: float = Field(ge=0, le=1)
    issue: str | None = None


class ResearchReport(StrictModel):
    research_question: str
    executive_summary: str
    conclusion: str
    key_findings: list[str]
    claims: list[ResearchClaim]
    limitations: list[str]
    unresolved_questions: list[str]
    confidence_score: float = Field(ge=0, le=1)
    sources: list[Citation]


class AgentEvent(StrictModel):
    event_id: str
    run_id: str
    type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ResearchState(StrictModel):
    run_id: str
    question: str
    depth: Literal["quick", "standard", "deep"] = "standard"
    research_plan: ResearchPlan | None = None
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    retrieved_evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)
    citation_verifications: list[CitationVerification] = Field(default_factory=list)
    assessment: EvidenceAssessment | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    iterations: int = Field(default=0, ge=0)
    max_iterations: int = Field(default=2, ge=1, le=8)
    confidence: float = Field(default=0, ge=0, le=1)
    final_report: ResearchReport | None = None
    status: Literal[
        "planning",
        "retrieving",
        "evaluating",
        "synthesizing",
        "verifying",
        "completed",
        "failed",
    ] = "planning"
    error: str | None = None


class ResearchRequest(StrictModel):
    question: str = Field(min_length=8, max_length=2000)
    namespace: str = Field(default="open-research", min_length=1, max_length=100)
    depth: Literal["quick", "standard", "deep"] = "standard"
    date_from: date | None = None
    date_to: date | None = None
    allowed_sources: list[str] | None = None
    run_synchronously: bool = False

    @model_validator(mode="after")
    def valid_date_range(self) -> ResearchRequest:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class EvaluationCase(StrictModel):
    id: str
    question: str
    gold_answer: str = ""
    gold_documents: list[str] = Field(default_factory=list)
    gold_chunks: list[str] = Field(default_factory=list)
    required_claims: list[str] = Field(default_factory=list)


class MetricSet(StrictModel):
    recall_at_k: float = Field(ge=0, le=1)
    precision_at_k: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)
    hit_rate: float = Field(ge=0, le=1)


class ExperimentResult(StrictModel):
    name: str
    cases: int = Field(ge=0)
    k: int = Field(ge=1)
    metrics: MetricSet
    duration_ms: float = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerEvaluation(StrictModel):
    accuracy: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    faithfulness: float = Field(ge=0, le=1)
    citation_quality: float = Field(ge=0, le=1)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    explanation: str
