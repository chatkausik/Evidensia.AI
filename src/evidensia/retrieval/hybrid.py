from __future__ import annotations

from time import perf_counter

from evidensia.models import RankedEvidence, SearchDebug
from evidensia.retrieval.fusion import reciprocal_rank_fusion
from evidensia.retrieval.index import LocalKnowledgeIndex
from evidensia.retrieval.query import classify_query
from evidensia.retrieval.reranker import LocalReranker


class HybridSearcher:
    def __init__(self, index: LocalKnowledgeIndex, reranker: LocalReranker | None = None) -> None:
        self.index = index
        self.reranker = reranker or LocalReranker()

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        candidate_limit: int = 30,
        metadata_filters: dict[str, str | int | list[str]] | None = None,
    ) -> SearchDebug:
        started = perf_counter()
        intent = classify_query(query)
        filters = {**intent.metadata_filters, **(metadata_filters or {})}
        dense = self.index.dense_search(query, candidate_limit, filters)
        sparse = self.index.sparse_search(query, candidate_limit, filters)
        # Inferred metadata is a precision hint, not a reason to return no evidence.
        # Explicit caller filters remain strict.
        if not dense and not sparse and intent.metadata_filters and not metadata_filters:
            dense = self.index.dense_search(query, candidate_limit)
            sparse = self.index.sparse_search(query, candidate_limit)
        fused = reciprocal_rank_fusion([dense, sparse])[:candidate_limit]

        dense_ranks = {chunk.chunk_id: rank for rank, (chunk, _) in enumerate(dense, start=1)}
        sparse_ranks = {chunk.chunk_id: rank for rank, (chunk, _) in enumerate(sparse, start=1)}
        dense_scores = {chunk.chunk_id: score for chunk, score in dense}
        sparse_scores = {chunk.chunk_id: score for chunk, score in sparse}

        def provisional(source: list[tuple]) -> list[RankedEvidence]:
            output: list[RankedEvidence] = []
            for rank, item in enumerate(source, start=1):
                chunk = item[0]
                score = item[1]
                output.append(
                    RankedEvidence(
                        chunk=chunk,
                        dense_rank=dense_ranks.get(chunk.chunk_id),
                        sparse_rank=sparse_ranks.get(chunk.chunk_id),
                        rrf_score=score if len(item) == 3 else 0,
                        final_score=max(0, score),
                        final_rank=rank,
                    )
                )
            return output

        reranked_payload: list[tuple] = []
        for chunk, rrf_score, ranks in fused:
            rerank_score = self.reranker.score(query, chunk, intent)
            # RRF is small by definition; normalize it against the best possible two-list score.
            normalized_rrf = min(1.0, rrf_score / (2 / 61))
            lexical_signal = sparse_scores.get(chunk.chunk_id, 0.0)
            dense_signal = dense_scores.get(chunk.chunk_id, 0.0)
            final = 0.62 * rerank_score + 0.25 * normalized_rrf + 0.08 * min(1.0, dense_signal) + 0.05 * min(1.0, lexical_signal / 8)
            reranked_payload.append((chunk, rrf_score, ranks, rerank_score, final))
        reranked_payload.sort(key=lambda item: (-item[4], item[0].chunk_id))

        reranked = [
            RankedEvidence(
                chunk=chunk,
                dense_rank=ranks[0],
                sparse_rank=ranks[1],
                rrf_score=rrf_score,
                rerank_score=rerank_score,
                final_score=final,
                final_rank=rank,
            )
            for rank, (chunk, rrf_score, ranks, rerank_score, final) in enumerate(reranked_payload[:limit], start=1)
        ]
        fused_models = [
            RankedEvidence(
                chunk=chunk,
                dense_rank=ranks[0],
                sparse_rank=ranks[1],
                rrf_score=rrf_score,
                final_score=rrf_score,
                final_rank=rank,
            )
            for rank, (chunk, rrf_score, ranks) in enumerate(fused, start=1)
        ]
        return SearchDebug(
            query=query,
            intent=intent,
            dense=provisional(dense),
            sparse=provisional(sparse),
            fused=fused_models,
            reranked=reranked,
            duration_ms=(perf_counter() - started) * 1000,
        )
