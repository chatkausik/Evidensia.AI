import pytest

from evidensia.evals.metrics import hit_rate, mean_reciprocal_rank, ndcg_at_k, precision_at_k, recall_at_k


def test_retrieval_metrics() -> None:
    ranking = ["noise", "gold_a", "gold_b"]
    gold = {"gold_a", "gold_b"}
    assert recall_at_k(ranking, gold, 2) == 0.5
    assert precision_at_k(ranking, gold, 2) == 0.5
    assert hit_rate(ranking, gold, 1) == 0
    assert mean_reciprocal_rank([ranking], [gold]) == 0.5
    assert ndcg_at_k(ranking, gold, 3) == pytest.approx(0.6934, rel=1e-3)

