from __future__ import annotations

import re

from evidensia.models import QueryIntent
from evidensia.retrieval.text import tokenize


def classify_query(query: str) -> QueryIntent:
    lowered = query.lower()
    if any(word in lowered for word in ("compare", "versus", " vs ", "differ", "outperform")):
        intent = "comparison"
    elif any(word in lowered for word in ("benchmark", "recall@", "ndcg", "accuracy", "hotpotqa")):
        intent = "benchmark"
    elif any(word in lowered for word in ("define", "what is", "meaning")):
        intent = "definition"
    elif any(word in lowered for word in ("method", "architecture", "implemented", "pipeline")):
        intent = "methodology"
    elif any(word in lowered for word in ("evidence", "study", "prove", "support")):
        intent = "evidence"
    elif any(word in lowered for word in ("multi-hop", "multiple sources", "synthesize", "relationship")):
        intent = "multi_hop"
    else:
        intent = "exploratory"

    quoted = len(re.findall(r'"[^\"]+"', query))
    technical = len(re.findall(r"\b[A-Z][A-Za-z0-9@._-]{2,}\b|\b\w+@\d+\b", query))
    specificity = min(1.0, 0.18 + quoted * 0.25 + technical * 0.1 + (0.15 if re.search(r"\b20\d{2}\b", query) else 0))
    semantic_complexity = min(1.0, 0.2 + len(tokenize(query)) / 24 + (0.25 if intent in {"comparison", "multi_hop"} else 0))

    preferred: list[str] = []
    if intent == "benchmark":
        preferred = ["results", "experiments", "evaluation"]
    elif intent == "methodology":
        preferred = ["methodology", "methods", "architecture"]
    elif intent == "definition":
        preferred = ["abstract", "introduction", "background"]

    filters: dict[str, str | int | list[str]] = {}
    year = re.search(r"\b(19\d{2}|20\d{2})\b", query)
    if year:
        filters["publication_year"] = int(year.group(1))
    datasets = [name for name in ("HotpotQA", "MuSiQue", "FEVER", "2WikiMultihopQA") if name.lower() in lowered]
    if datasets:
        filters["datasets"] = datasets

    return QueryIntent(
        intent=intent,
        keyword_specificity=specificity,
        semantic_complexity=semantic_complexity,
        requires_multi_hop=intent in {"comparison", "multi_hop"} or semantic_complexity >= 0.7,
        preferred_sections=preferred,
        metadata_filters=filters,
    )

