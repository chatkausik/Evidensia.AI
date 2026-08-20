from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from evidensia.models import ChunkRecord
from evidensia.providers import EmbeddingProvider, HashedEmbeddingProvider
from evidensia.retrieval.text import cosine, term_frequencies, tokenize


class LocalKnowledgeIndex:
    """Auditable in-process dense + BM25 index for development and evaluation."""

    def __init__(self, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.embedding_provider = embedding_provider or HashedEmbeddingProvider()
        self._chunks: dict[str, ChunkRecord] = {}
        self._vectors: dict[str, dict[int, float]] = {}
        self._terms: dict[str, Counter[str]] = {}
        self._document_frequency: Counter[str] = Counter()
        self._average_length = 1.0

    def upsert(self, chunks: Iterable[ChunkRecord]) -> None:
        for chunk in chunks:
            if chunk.chunk_type != "retrieval":
                continue
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = self.embedding_provider.embed(self._searchable_text(chunk))
            self._terms[chunk.chunk_id] = term_frequencies(self._searchable_text(chunk))
        self._refresh_statistics()

    def delete_document(self, document_id: str) -> int:
        ids = [chunk_id for chunk_id, chunk in self._chunks.items() if chunk.document_id == document_id]
        for chunk_id in ids:
            self._chunks.pop(chunk_id, None)
            self._vectors.pop(chunk_id, None)
            self._terms.pop(chunk_id, None)
        self._refresh_statistics()
        return len(ids)

    def get(self, chunk_id: str) -> ChunkRecord | None:
        return self._chunks.get(chunk_id)

    def all(self) -> list[ChunkRecord]:
        return list(self._chunks.values())

    def dense_search(
        self,
        query: str,
        limit: int = 30,
        filters: dict[str, str | int | list[str]] | None = None,
    ) -> list[tuple[ChunkRecord, float]]:
        vector = self.embedding_provider.embed(query)
        scored = [
            (chunk, cosine(vector, self._vectors[chunk_id]))
            for chunk_id, chunk in self._chunks.items()
            if self._matches(chunk, filters)
        ]
        return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))[:limit]

    def sparse_search(
        self,
        query: str,
        limit: int = 30,
        filters: dict[str, str | int | list[str]] | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> list[tuple[ChunkRecord, float]]:
        query_terms = tokenize(query)
        document_count = max(1, len(self._chunks))
        scored: list[tuple[ChunkRecord, float]] = []
        for chunk_id, chunk in self._chunks.items():
            if not self._matches(chunk, filters):
                continue
            frequencies = self._terms[chunk_id]
            length = max(1, sum(frequencies.values()))
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                doc_frequency = self._document_frequency.get(term, 0)
                inverse_frequency = math.log(1 + (document_count - doc_frequency + 0.5) / (doc_frequency + 0.5))
                denominator = frequency + k1 * (1 - b + b * length / self._average_length)
                score += inverse_frequency * frequency * (k1 + 1) / denominator
            scored.append((chunk, score))
        return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))[:limit]

    def _refresh_statistics(self) -> None:
        self._document_frequency = Counter()
        total_length = 0
        for terms in self._terms.values():
            total_length += sum(terms.values())
            self._document_frequency.update(terms.keys())
        self._average_length = total_length / len(self._terms) if self._terms else 1.0

    @staticmethod
    def _searchable_text(chunk: ChunkRecord) -> str:
        metadata = " ".join([chunk.title, chunk.section, *chunk.topics, *chunk.methods, *chunk.datasets])
        return f"{metadata}\n{chunk.text}"

    @staticmethod
    def _matches(chunk: ChunkRecord, filters: dict[str, str | int | list[str]] | None) -> bool:
        if not filters:
            return True
        for key, expected in filters.items():
            if key == "document_ids":
                if chunk.document_id not in set(map(str, expected if isinstance(expected, list) else [expected])):
                    return False
                continue
            if key == "publication_year_gte":
                if chunk.publication_year is None or chunk.publication_year < int(expected):
                    return False
                continue
            if key == "publication_year_lte":
                if chunk.publication_year is None or chunk.publication_year > int(expected):
                    return False
                continue
            if key == "allowed_sources":
                allowed = list(map(str, expected if isinstance(expected, list) else [expected]))
                if not chunk.source_uri or not any(chunk.source_uri.startswith(value) for value in allowed):
                    return False
                continue
            actual = getattr(chunk, key, None)
            if isinstance(expected, list):
                actual_values = actual if isinstance(actual, list) else [actual]
                if not set(map(str.lower, map(str, expected))).intersection(map(str.lower, map(str, actual_values))):
                    return False
            elif isinstance(actual, list):
                if str(expected).lower() not in {str(value).lower() for value in actual}:
                    return False
            elif actual != expected:
                return False
        return True
