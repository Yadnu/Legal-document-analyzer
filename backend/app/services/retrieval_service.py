"""Hybrid retrieval: dense + sparse → RRF → rerank."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.embedder import embed_query
from app.models.chunk import Chunk
from app.repositories import chunk_repo
from app.retrieval.rerank import rerank
from app.retrieval.rrf import reciprocal_rank_fusion

log = structlog.get_logger(__name__)


async def retrieve(
    session: AsyncSession,
    tenant_id: str,
    question: str,
    *,
    document_id: uuid.UUID | None = None,
) -> list[Chunk]:
    """Return tenant-scoped, reranked chunks relevant to ``question``."""

    query_embedding = await embed_query(question)

    dense = await chunk_repo.dense_search(
        session,
        tenant_id,
        query_embedding,
        top_k=settings.retrieval_dense_top_k,
        embedding_model=settings.embedding_model,
        embedding_model_version=settings.embedding_model_version,
        document_id=document_id,
    )

    sparse = await chunk_repo.sparse_search(
        session,
        tenant_id,
        question,
        top_k=settings.retrieval_sparse_top_k,
        document_id=document_id,
    )

    fused = reciprocal_rank_fusion(
        [
            [item.chunk.id for item in dense],
            [item.chunk.id for item in sparse],
        ],
        k=settings.retrieval_rrf_k,
    )

    by_id: dict[uuid.UUID, Chunk] = {item.chunk.id: item.chunk for item in dense}

    for item in sparse:

        by_id.setdefault(item.chunk.id, item.chunk)

    # Cap candidates before rerank to avoid huge Cohere payloads.

    fused_ids = [chunk_id for chunk_id, _ in fused][
        : max(settings.retrieval_dense_top_k, settings.retrieval_sparse_top_k)
    ]

    candidates = [by_id[cid] for cid in fused_ids if cid in by_id]

    # If fusion produced nothing (e.g. empty indexes), fall back to dense order.

    if not candidates and dense:

        candidates = [item.chunk for item in dense]

    reranked = await rerank(
        question,
        candidates,
        top_n=settings.retrieval_rerank_top_n,
    )

    log.info(
        "retrieval_ok",
        tenant_id=tenant_id,
        dense_count=len(dense),
        sparse_count=len(sparse),
        fused_count=len(fused),
        returned=len(reranked),
        document_scoped=document_id is not None,
    )

    return reranked
