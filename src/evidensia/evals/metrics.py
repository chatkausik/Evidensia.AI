from __future__ import annotations

import math
from collections.abc import Sequence, Set


def recall_at_k(ranked_ids: Sequence[str], relevant_ids: Set[str], k: int) -> float:
    if not relevant_ids:
        return 1.0
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def precision_at_k(ranked_ids: Sequence[str], relevant_ids: Set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(ranked_ids[:k]) & relevant_ids) / k


def reciprocal_rank(ranked_ids: Sequence[str], relevant_ids: Set[str]) -> float:
    for index, item_id in enumerate(ranked_ids, start=1):
        if item_id in relevant_ids:
            return 1 / index
    return 0.0


def mean_reciprocal_rank(rankings: Sequence[Sequence[str]], relevant: Sequence[Set[str]]) -> float:
    if not rankings:
        return 0.0
    return sum(reciprocal_rank(ranking, gold) for ranking, gold in zip(rankings, relevant, strict=True)) / len(rankings)


def ndcg_at_k(ranked_ids: Sequence[str], relevant_ids: Set[str], k: int) -> float:
    gains = [1.0 if item_id in relevant_ids else 0.0 for item_id in ranked_ids[:k]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal_count = min(k, len(relevant_ids))
    ideal = sum(1 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / ideal if ideal else 1.0


def hit_rate(ranked_ids: Sequence[str], relevant_ids: Set[str], k: int) -> float:
    return float(bool(set(ranked_ids[:k]) & relevant_ids))

