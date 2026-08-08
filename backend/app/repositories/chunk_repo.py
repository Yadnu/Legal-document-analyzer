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

import structlog
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.ingestion.chunker import ChunkData, cross_refs_to_json
from app.models.chunk import Chunk

log = structlog.get_logger(__name__)


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
