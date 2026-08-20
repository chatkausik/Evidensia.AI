from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from evidensia.evals.metrics import hit_rate, mean_reciprocal_rank, ndcg_at_k, precision_at_k, recall_at_k
from evidensia.models import EvaluationCase, ExperimentResult, MetricSet
from evidensia.retrieval import HybridSearcher, LocalKnowledgeIndex


class EvaluationRunner:
    def __init__(self, index: LocalKnowledgeIndex, searcher: HybridSearcher) -> None:
        self.index = index
        self.searcher = searcher

    def run(self, cases: list[EvaluationCase], pipeline: str = "reranked", k: int = 10) -> ExperimentResult:
        pipelines: dict[str, Callable[[str], list[str]]] = {
            "dense": lambda query: [chunk.chunk_id for chunk, _ in self.index.dense_search(query, k)],
            "sparse": lambda query: [chunk.chunk_id for chunk, _ in self.index.sparse_search(query, k)],
            "hybrid": lambda query: [item.chunk.chunk_id for item in self.searcher.search(query, limit=k).fused[:k]],
            "reranked": lambda query: [item.chunk.chunk_id for item in self.searcher.search(query, limit=k).reranked[:k]],
        }
        if pipeline not in pipelines:
            raise ValueError(f"Unknown pipeline: {pipeline}")
        started = perf_counter()
        rankings = [pipelines[pipeline](case.question) for case in cases]
        relevant = [set(case.gold_chunks) for case in cases]
        if cases:
            recall = sum(recall_at_k(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            precision = sum(precision_at_k(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            ndcg = sum(ndcg_at_k(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            hits = sum(hit_rate(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            mrr = mean_reciprocal_rank(rankings, relevant)
        else:
            recall = precision = ndcg = hits = mrr = 0.0
        return ExperimentResult(
            name=pipeline,
            cases=len(cases),
            k=k,
            metrics=MetricSet(
                recall_at_k=recall,
                precision_at_k=precision,
                mrr=mrr,
                ndcg_at_k=ndcg,
                hit_rate=hits,
            ),
            duration_ms=(perf_counter() - started) * 1000,
            metadata={"target_metric": "recall_at_k", "target": 0.85},
        )

    def ablation(self, cases: list[EvaluationCase], k: int = 10) -> list[ExperimentResult]:
        return [self.run(cases, pipeline, k) for pipeline in ("dense", "sparse", "hybrid", "reranked")]
