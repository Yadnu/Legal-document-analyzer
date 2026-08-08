"""Document repository.

All public functions accept an ``AsyncSession`` and a ``tenant_id`` so that
every query is filtered by tenant at the application layer in addition to the
Postgres RLS policies (defence in depth).

The repository returns ``Document`` SQLModel objects internally.  Callers at
the service layer are responsible for converting to API DTOs before crossing
the HTTP boundary.

Transaction ownership sits with the caller (the service or the worker).  The
repo uses ``session.flush()`` after inserts so the generated ``id`` and
``created_at`` are populated, but never calls ``session.commit()`` itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.document import Document, DocumentStatus

# ---------------------------------------------------------------------------
# Input data object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentCreateData:
    """Validated fields needed to insert a new Document row.

    Kept as a plain dataclass so the service layer can construct it without
    importing any SQLModel or Pydantic machinery from this module.
    """

    title: str
    original_filename: str
    content_type: str
    size_bytes: int
    s3_key: str
    idempotency_key: str
    uploaded_by: str  # Clerk user_id


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------


async def create(
    session: AsyncSession,
    tenant_id: str,
    data: DocumentCreateData,
) -> Document:
    """Insert a new Document row with status ``processing``.

    Flushes the session so the generated ``id`` and ``created_at`` are
    populated before returning.  The caller is responsible for committing.
    """
    doc = Document(
        tenant_id=tenant_id,
        status=DocumentStatus.PROCESSING,
        title=data.title,
        original_filename=data.original_filename,
        content_type=data.content_type,
        size_bytes=data.size_bytes,
        s3_key=data.s3_key,
        idempotency_key=data.idempotency_key,
        uploaded_by=data.uploaded_by,
    )
    session.add(doc)
    await session.flush()
    await session.refresh(doc)
    return doc


async def get_by_id(
    session: AsyncSession,
    tenant_id: str,
    doc_id: uuid.UUID,
) -> Document | None:
    """Return the Document matching ``doc_id`` and ``tenant_id``, or ``None``.

    Filters by ``tenant_id`` explicitly even though the session already has
    an RLS context set via ``set_tenant_context``.
    """
    result = await session.execute(
        select(Document).where(
            col(Document.id) == doc_id,
            col(Document.tenant_id) == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_idempotency_key(
    session: AsyncSession,
    tenant_id: str,
    key: str,
) -> Document | None:
    """Return the Document with the given idempotency key, or ``None``.

    Used by the upload service to detect duplicate upload requests before
    creating a new row.
    """
    result = await session.execute(
        select(Document).where(
            col(Document.idempotency_key) == key,
            col(Document.tenant_id) == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> list[Document]:
    """Return all documents for the given tenant, ordered newest-first."""
    result = await session.execute(
        select(Document)
        .where(col(Document.tenant_id) == tenant_id)
        .order_by(col(Document.created_at).desc())
    )
    return list(result.scalars().all())


async def set_status(
    session: AsyncSession,
    tenant_id: str,
    doc_id: uuid.UUID,
    status: str,
    error_reason: str | None = None,
) -> None:
    """Update only the ``status`` (and optionally ``error_reason``) of a document.

    Filters by both ``doc_id`` and ``tenant_id`` so a mis-scoped call is a
    silent no-op rather than a data-corruption bug.  The caller must commit.
    """
    await session.execute(
        update(Document)
        .where(
            col(Document.id) == doc_id,
            col(Document.tenant_id) == tenant_id,
        )
        .values(status=status, error_reason=error_reason)
    )
