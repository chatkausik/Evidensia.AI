from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from evidensia.models import EvaluationCase, PaperDiscoveryRequest, StrictModel


class SearchRequest(StrictModel):
    query: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=8, ge=1, le=50)
    metadata_filters: dict[str, str | int | list[str]] = Field(default_factory=dict)


class EvaluationRequest(StrictModel):
    cases: list[EvaluationCase]
    pipeline: Literal["dense", "sparse", "hybrid", "reranked"] = "reranked"
    k: int = Field(default=10, ge=1, le=100)
    run_ablation: bool = False


class FeedbackRequest(StrictModel):
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=4000)


class FeedbackResponse(StrictModel):
    accepted: bool = True


class HealthResponse(StrictModel):
    status: str
    version: str
    details: dict[str, Any] = Field(default_factory=dict)


class PaperImportRequest(StrictModel):
    paper_ids: list[str] = Field(min_length=1, max_length=100)
    full_text: bool = True


__all__ = [
    "EvaluationRequest",
    "FeedbackRequest",
    "FeedbackResponse",
    "HealthResponse",
    "PaperDiscoveryRequest",
    "PaperImportRequest",
    "SearchRequest",
]
