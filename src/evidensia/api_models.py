from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from evidensia.models import EvaluationCase, PaperDiscoveryRequest, PaperProvider, StrictModel


class SearchRequest(StrictModel):
    query: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=8, ge=1, le=50)
    metadata_filters: dict[str, str | int | list[str]] = Field(default_factory=dict)


class EvaluationRequest(StrictModel):
    cases: list[EvaluationCase] = Field(default_factory=list)
    pipeline: Literal["dense", "sparse", "hybrid", "reranked"] = "reranked"
    k: int = Field(default=10, ge=1, le=100)
    run_ablation: bool = False
    dataset_name: str = Field(default="ad-hoc", min_length=1, max_length=120)


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


class PaperCompareRequest(StrictModel):
    paper_ids: list[str] = Field(min_length=2, max_length=12)


class SavedSearchRequest(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    query: str = Field(min_length=2, max_length=500)
    date_from: date
    date_to: date
    providers: list[PaperProvider] = Field(min_length=1)
    categories: list[str] = Field(default_factory=list, max_length=20)
    open_access_only: bool = True

    @model_validator(mode="after")
    def valid_date_range(self) -> SavedSearchRequest:
        if self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        self.providers = list(dict.fromkeys(self.providers))
        self.categories = list(dict.fromkeys(self.categories))
        return self


class CollectionRequest(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    document_ids: list[str] = Field(default_factory=list, max_length=1000)


__all__ = [
    "EvaluationRequest",
    "FeedbackRequest",
    "FeedbackResponse",
    "HealthResponse",
    "PaperDiscoveryRequest",
    "PaperImportRequest",
    "PaperCompareRequest",
    "SavedSearchRequest",
    "CollectionRequest",
    "SearchRequest",
]
