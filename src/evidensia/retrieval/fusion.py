from __future__ import annotations

from collections.abc import Sequence

from evidensia.models import ChunkRecord


def reciprocal_rank_fusion(
    result_sets: Sequence[Sequence[tuple[ChunkRecord, float]]],
    *,
    k: int = 60,
) -> list[tuple[ChunkRecord, float, list[int | None]]]:
    chunks: dict[str, ChunkRecord] = {}
    scores: dict[str, float] = {}
    ranks: dict[str, list[int | None]] = {}
    for set_index, results in enumerate(result_sets):
        for rank, (chunk, _) in enumerate(results, start=1):
            chunks[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1 / (k + rank)
            ranks.setdefault(chunk.chunk_id, [None] * len(result_sets))[set_index] = rank
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return [(chunks[chunk_id], scores[chunk_id], ranks[chunk_id]) for chunk_id in ordered]

