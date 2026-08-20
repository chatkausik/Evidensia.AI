from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from evidensia.evals.metrics import hit_rate, mean_reciprocal_rank, ndcg_at_k, precision_at_k, recall_at_k
from evidensia.models import EvaluationCase, ExperimentResult, MetricSet
from evidensia.retrieval import HybridSearcher, LocalKnowledgeIndex
from evidensia.retrieval.text import tokenize


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
        relevant = [
            set(case.gold_chunks) | {
                chunk.chunk_id for chunk in self.index.all() if chunk.document_id in set(case.gold_documents)
            }
            for case in cases
        ]
        ranked_documents = [
            [self.index.get(chunk_id).document_id for chunk_id in ranking if self.index.get(chunk_id)]
            for ranking in rankings
        ]
        if cases:
            recall = sum(recall_at_k(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            precision = sum(precision_at_k(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            ndcg = sum(ndcg_at_k(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            hits = sum(hit_rate(ranking, gold, k) for ranking, gold in zip(rankings, relevant, strict=True)) / len(cases)
            mrr = mean_reciprocal_rank(rankings, relevant)
            document_recall = sum(
                len(set(ranking[:k]) & set(case.gold_documents)) / max(1, len(set(case.gold_documents)))
                for ranking, case in zip(ranked_documents, cases, strict=True)
            ) / len(cases)
            answer_coverage = sum(
                self._coverage(case.gold_answer, ranking) for case, ranking in zip(cases, rankings, strict=True)
            ) / len(cases)
            claim_coverage = sum(
                sum(self._coverage(claim, ranking) for claim in case.required_claims) / max(1, len(case.required_claims))
                for case, ranking in zip(cases, rankings, strict=True)
            ) / len(cases)
        else:
            recall = precision = ndcg = hits = mrr = document_recall = answer_coverage = claim_coverage = 0.0
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
                document_recall_at_k=document_recall,
                answer_coverage=answer_coverage,
                claim_coverage=claim_coverage,
            ),
            duration_ms=(perf_counter() - started) * 1000,
            metadata={"target_metric": "recall_at_k", "target": 0.85, "labeled_cases": sum(bool(item) for item in relevant)},
        )

    def ablation(self, cases: list[EvaluationCase], k: int = 10) -> list[ExperimentResult]:
        return [self.run(cases, pipeline, k) for pipeline in ("dense", "sparse", "hybrid", "reranked")]

    def _coverage(self, expected: str, ranking: list[str]) -> float:
        terms = set(tokenize(expected))
        if not terms:
            return 0.0
        retrieved = set()
        for chunk_id in ranking:
            if chunk := self.index.get(chunk_id):
                retrieved.update(tokenize(chunk.text))
        return len(terms & retrieved) / len(terms)
