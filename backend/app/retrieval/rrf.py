"""Reciprocal Rank Fusion (RRF).
Pure function — no I/O.  Combines multiple ranked lists of chunk IDs into a
single score so dense and sparse retrieval can be fused without calibrating
their native score scales.
"""

from __future__ import annotations

import uuid


def reciprocal_rank_fusion(
    ranked_lists: list[list[uuid.UUID]],
    *,
    k: int = 60,
) -> list[tuple[uuid.UUID, float]]:
    """Fuse ranked ID lists with Reciprocal Rank Fusion.
    For each list, the item at rank ``r`` (0-based) contributes ``1 / (k + r + 1)``.
    Scores are summed across lists.  Returns ``(chunk_id, score)`` pairs sorted
    by score descending.  Ties keep first-seen insertion order for stability.
    """
    if k < 0:
        raise ValueError("k must be >= 0")
    scores: dict[uuid.UUID, float] = {}
    order: list[uuid.UUID] = []
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            if chunk_id not in scores:
                scores[chunk_id] = 0.0
                order.append(chunk_id)
            scores[chunk_id] += 1.0 / (k + rank + 1)
    return sorted(
        ((chunk_id, scores[chunk_id]) for chunk_id in order),
        key=lambda item: item[1],
        reverse=True,
    )
