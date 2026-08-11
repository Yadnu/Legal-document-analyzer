"""Chunk repository.
All writes are tenant-scoped and idempotent:
- ``upsert_chunks`` deletes all existing chunks for the document, then inserts
  the new set in one batch.  Calling it twice with the same data leaves the
  database in the same state.
- ``search_vector`` is computed inside the INSERT using Postgres
  ``to_tsvector('english', :content)`` so no separate trigger is needed.
Transaction ownership stays with the caller (ingestion service).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.ingestion.chunker import ChunkData, cross_refs_to_json
from app.models.chunk import Chunk

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RankedChunk:
    """A chunk paired with a provider-native relevance score."""

    chunk: Chunk
    score: float


async def upsert_chunks(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
    embedding_model: str,
    embedding_model_version: str,
) -> int:
    """Replace all chunks for ``document_id`` with the new set.
    Parameters
    ----------
    session:
        Active async session (tenant RLS context must already be set).
    tenant_id:
        Used in every query as a defence-in-depth filter alongside RLS.
    document_id:
        All existing chunks for this document are deleted before insert.
    chunks:
        Ordered list from the chunker.
    embeddings:
        Parallel list of embedding vectors; ``len(embeddings) == len(chunks)``.
    embedding_model / embedding_model_version:
        Stored on every row to enforce model consistency at retrieval time.
    Returns
    -------
    int
        Number of rows inserted.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) "
            "must have the same length"
        )
    # ── 1. Delete existing chunks ────────────────────────────────────────────
    await session.execute(
        delete(Chunk).where(
            col(Chunk.document_id) == document_id,
            col(Chunk.tenant_id) == tenant_id,
        )
    )
    if not chunks:
        return 0
    # ── 2. Batch-insert new chunks with tsvector populated inline ────────────
    # We use raw SQL for the tsvector expression; SQLModel/SQLAlchemy does not
    # natively support function-based column defaults in bulk inserts.
    rows = []
    for chunk, vector in zip(chunks, embeddings, strict=True):
        rows.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "document_id": str(document_id),
                "section_number": chunk.section_number,
                "heading": chunk.heading,
                "page": chunk.page,
                "cross_refs": cross_refs_to_json(chunk.cross_refs),
                "content": chunk.content,
                "token_count": chunk.token_count,
                "embedding_model": embedding_model,
                "embedding_model_version": embedding_model_version,
                "embedding": str(vector),  # pgvector accepts '[0.1, 0.2, ...]'
            }
        )
    await session.execute(
        text("""
            INSERT INTO chunks (
                id, tenant_id, document_id,
                section_number, heading, page,
                cross_refs, content, token_count,
                embedding_model, embedding_model_version,
                embedding, search_vector,
                created_at
            ) VALUES (
                CAST(:id AS uuid), :tenant_id, CAST(:document_id AS uuid),
                :section_number, :heading, :page,
                :cross_refs, :content, :token_count,
                :embedding_model, :embedding_model_version,
                CAST(:embedding AS vector), to_tsvector('english', :content),
                now()
            )
            """),
        rows,
    )
    log.info(
        "chunk_repo_upsert_ok",
        tenant_id=tenant_id,
        document_id=str(document_id),
        chunk_count=len(chunks),
    )
    return len(chunks)


async def dense_search(
    session: AsyncSession,
    tenant_id: str,
    query_embedding: list[float],
    *,
    top_k: int,
    embedding_model: str,
    embedding_model_version: str,
    document_id: uuid.UUID | None = None,
) -> list[RankedChunk]:
    """Cosine nearest-neighbour search via pgvector ``<=>``.
    Only returns chunks whose embedding_model(+version) matches the query
    embedding provenance so vectors are never mixed.
    Score is cosine distance (lower is better).
    """
    if top_k <= 0 or not query_embedding:
        return []
    params: dict = {
        "tenant_id": tenant_id,
        "embedding": str(query_embedding),
        "embedding_model": embedding_model,
        "embedding_model_version": embedding_model_version,
        "top_k": top_k,
    }
    doc_filter = ""
    if document_id is not None:
        doc_filter = "AND document_id = CAST(:document_id AS uuid)"
        params["document_id"] = str(document_id)
    result = await session.execute(
        text(f"""
            SELECT
                id, tenant_id, document_id,
                section_number, heading, page,
                cross_refs, content, token_count,
                embedding_model, embedding_model_version,
                created_at,
                (embedding <=> CAST(:embedding AS vector)) AS distance
            FROM chunks
            WHERE tenant_id = :tenant_id
              AND embedding IS NOT NULL
              AND embedding_model = :embedding_model
              AND embedding_model_version = :embedding_model_version
              {doc_filter}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """),
        params,
    )
    rows = result.mappings().all()
    return [_row_to_ranked(row, score=float(row["distance"])) for row in rows]


async def sparse_search(
    session: AsyncSession,
    tenant_id: str,
    query_text: str,
    *,
    top_k: int,
    document_id: uuid.UUID | None = None,
) -> list[RankedChunk]:
    """BM25-style full-text search via ``plainto_tsquery`` + ``ts_rank_cd``.
    Score is ts_rank_cd (higher is better).
    """
    if top_k <= 0 or not query_text.strip():
        return []
    params: dict = {
        "tenant_id": tenant_id,
        "query": query_text,
        "top_k": top_k,
    }
    doc_filter = ""
    if document_id is not None:
        doc_filter = "AND document_id = CAST(:document_id AS uuid)"
        params["document_id"] = str(document_id)
    result = await session.execute(
        text(f"""
            SELECT
                id, tenant_id, document_id,
                section_number, heading, page,
                cross_refs, content, token_count,
                embedding_model, embedding_model_version,
                created_at,
                ts_rank_cd(search_vector, plainto_tsquery('english', :query))
                    AS rank
            FROM chunks
            WHERE tenant_id = :tenant_id
              AND search_vector @@ plainto_tsquery('english', :query)
              {doc_filter}
            ORDER BY rank DESC
            LIMIT :top_k
            """),
        params,
    )
    rows = result.mappings().all()
    return [_row_to_ranked(row, score=float(row["rank"])) for row in rows]


async def get_by_ids(
    session: AsyncSession,
    tenant_id: str,
    chunk_ids: list[uuid.UUID],
) -> list[Chunk]:
    """Fetch chunks by id, always filtered by tenant."""
    if not chunk_ids:
        return []
    result = await session.execute(
        select(Chunk).where(
            col(Chunk.tenant_id) == tenant_id,
            col(Chunk.id).in_(chunk_ids),
        )
    )
    return list(result.scalars().all())


def _row_to_ranked(row, *, score: float) -> RankedChunk:
    chunk = Chunk(
        id=row["id"],
        tenant_id=row["tenant_id"],
        document_id=row["document_id"],
        section_number=row["section_number"],
        heading=row["heading"],
        page=row["page"],
        cross_refs=row["cross_refs"],
        content=row["content"],
        token_count=row["token_count"],
        embedding_model=row["embedding_model"],
        embedding_model_version=row["embedding_model_version"],
        created_at=row["created_at"],
    )
    return RankedChunk(chunk=chunk, score=score)
