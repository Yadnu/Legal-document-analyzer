"""Ingestion service.

Orchestrates the full document ingestion pipeline:

  download (S3) → parse (PDF) → chunk → embed (Voyage/fallback) → store (DB)

This is the single entry-point called by the worker.  All heavy work happens
here; the worker only handles SQS mechanics and status transitions.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.config import settings
from app.infra.storage import download_document
from app.ingestion.chunker import chunk_elements, chunks_to_texts
from app.ingestion.embedder import embed_texts
from app.ingestion.parser import ParseError, parse_pdf
from app.models.document import Document
from app.repositories import chunk_repo, document_repo

log = structlog.get_logger(__name__)


async def ingest(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    s3_key: str,
) -> int:
    """Run the full ingestion pipeline for one document.

    Parameters
    ----------
    session:
        Active async session with RLS tenant context already set.
    tenant_id, document_id, s3_key:
        From the SQS message body.

    Returns
    -------
    int
        Number of chunks created.

    Raises
    ------
    Any exception propagates to the worker which marks the document ``failed``
    and re-raises so SQS can retry → DLQ.
    """
    bound_log = log.bind(
        document_id=str(document_id),
        tenant_id=tenant_id,
    )

    # ── 1. Fetch document record (content_type needed for parser dispatch) ──
    doc = await document_repo.get_by_id(session, tenant_id, document_id)
    if doc is None:
        raise RuntimeError(f"Document {document_id} not found for tenant {tenant_id}")

    bound_log.info("ingestion_start", content_type=doc.content_type)

    # ── 2. Download raw bytes from S3 ────────────────────────────────────────
    data = await download_document(s3_key)
    bound_log.info("ingestion_downloaded", size_bytes=len(data))

    # ── 3. Parse ─────────────────────────────────────────────────────────────
    try:
        elements = parse_pdf(data)
    except ParseError as exc:
        raise RuntimeError(f"Parse failed: {exc}") from exc

    page_count = max((e.page for e in elements), default=0)
    bound_log.info(
        "ingestion_parsed",
        element_count=len(elements),
        page_count=page_count,
    )

    # ── 4. Chunk ─────────────────────────────────────────────────────────────
    chunks = chunk_elements(
        elements,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    bound_log.info("ingestion_chunked", chunk_count=len(chunks))

    # ── 5. Embed ─────────────────────────────────────────────────────────────
    texts = chunks_to_texts(chunks)
    embeddings = await embed_texts(texts)
    bound_log.info("ingestion_embedded", vector_count=len(embeddings))

    # ── 6. Upsert chunks (idempotent) ────────────────────────────────────────
    inserted = await chunk_repo.upsert_chunks(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        chunks=chunks,
        embeddings=embeddings,
        embedding_model=settings.embedding_model,
        embedding_model_version=settings.embedding_model_version,
    )

    # ── 7. Update Document.page_count ────────────────────────────────────────
    if page_count:
        await session.execute(
            update(Document)
            .where(
                col(Document.id) == document_id,
                col(Document.tenant_id) == tenant_id,
            )
            .values(page_count=page_count)
        )

    bound_log.info(
        "ingestion_complete",
        chunk_count=inserted,
        page_count=page_count,
    )
    return inserted
