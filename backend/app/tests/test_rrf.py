"""Phase 5 RRF unit tests — no DB, no network."""

from __future__ import annotations

import uuid

from app.retrieval.rrf import reciprocal_rank_fusion


def test_rrf_promotes_overlap() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([[a, b], [a, c]], k=60)
    ids = [chunk_id for chunk_id, _ in fused]
    assert ids[0] == a
    assert set(ids) == {a, b, c}


def test_rrf_stable_order() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    first = reciprocal_rank_fusion([[a, b], [b, a]], k=60)
    second = reciprocal_rank_fusion([[a, b], [b, a]], k=60)
    assert first == second


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
