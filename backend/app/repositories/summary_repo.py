"""Summary card repository.

All functions accept a session and tenant_id so every query is scoped
to the calling tenant at the application layer (RLS is defence-in-depth).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summary import DocumentSummaryCard

_FIELDS = (
    "parties",
    "effective_date",
    "term_length",
    "payment_terms",
    "termination_rights",
    "liability_caps",
    "governing_law",
)


async def get_for_document(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
) -> DocumentSummaryCard | None:
    """Return the most recent summary card for a document, or None."""
    result = await session.execute(
        select(DocumentSummaryCard)
        .where(
            DocumentSummaryCard.tenant_id == tenant_id,
            DocumentSummaryCard.document_id == document_id,
        )
        .order_by(DocumentSummaryCard.extracted_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def upsert(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    fields: dict,
) -> DocumentSummaryCard:
    """Insert a new summary card row (or replace the existing one).

    Rather than a true SQL UPSERT (which would need a unique constraint),
    we delete any existing row for this document and insert a fresh one.
    This keeps the migration simple and the cache invalidation trivial.
    """
    existing = await get_for_document(session, tenant_id, document_id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    card = DocumentSummaryCard(
        tenant_id=tenant_id,
        document_id=document_id,
        extracted_at=datetime.now(UTC),
        **{f: fields.get(f) for f in _FIELDS},
    )
    session.add(card)
    await session.flush()
    return card
