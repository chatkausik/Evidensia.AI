from __future__ import annotations

from evidensia.models import ChunkRecord, QueryIntent
from evidensia.retrieval.text import tokenize


class LocalReranker:
    """Transparent relevance scorer implementing the hosted-reranker contract locally."""

    def score(self, query: str, chunk: ChunkRecord, intent: QueryIntent) -> float:
        query_terms = tokenize(query)
        document_terms = tokenize(f"{chunk.title} {chunk.section} {chunk.text}")
        query_set = set(query_terms)
        document_set = set(document_terms)
        coverage = len(query_set & document_set) / max(1, len(query_set))
        query_bigrams = set(zip(query_terms, query_terms[1:]))
        document_bigrams = set(zip(document_terms, document_terms[1:]))
        phrase = len(query_bigrams & document_bigrams) / max(1, len(query_bigrams))
        section = 1.0 if chunk.section.lower() in {value.lower() for value in intent.preferred_sections} else 0.0
        title = len(query_set & set(tokenize(chunk.title))) / max(1, len(query_set))
        return min(1.0, 0.62 * coverage + 0.18 * phrase + 0.12 * section + 0.08 * title)

