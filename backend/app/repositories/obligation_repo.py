"""Obligation repository.

All functions accept session + tenant_id so every query is scoped at the
application layer; RLS is a second line of defence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.obligation import Obligation
from app.schemas.obligation import ObligationCreate, ObligationPatch

# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

async def get(
    session: AsyncSession,
    tenant_id: str,
    obligation_id: uuid.UUID,
) -> Obligation | None:
    """Return a single obligation by ID, or None if it doesn't belong to tenant."""
    result = await session.execute(
        select(Obligation).where(
            col(Obligation.tenant_id) == tenant_id,
            col(Obligation.id) == obligation_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_document(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    *,
    include_resolved: bool = True,
) -> list[Obligation]:
    """Return all obligations for a single document."""
    stmt = select(Obligation).where(
        col(Obligation.tenant_id) == tenant_id,
        col(Obligation.document_id) == document_id,
    )
    if not include_resolved:
        stmt = stmt.where(col(Obligation.is_resolved).is_(False))
    stmt = stmt.order_by(col(Obligation.deadline).asc().nulls_last())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: str,
    *,
    include_resolved: bool = False,
    obligation_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Obligation], int]:
    """Return paginated obligations across all documents for a tenant.

    Returns a (items, total_count) tuple.
    """
    base = select(Obligation).where(col(Obligation.tenant_id) == tenant_id)

    if not include_resolved:
        base = base.where(col(Obligation.is_resolved).is_(False))
    if obligation_type is not None:
        base = base.where(col(Obligation.obligation_type) == obligation_type)

    count_result = await session.execute(
        select(func.count()).select_from(base.subquery())
    )
    total: int = count_result.scalar_one()

    items_result = await session.execute(
        base.order_by(col(Obligation.deadline).asc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    return list(items_result.scalars().all()), total


async def list_due_for_reminder(
    session: AsyncSession,
    tenant_id: str,
) -> list[Obligation]:
    """Return obligations whose reminders are due but not yet sent.

    An obligation is due when:
      - deadline is set
      - deadline - reminder_days_before <= now  (reminder window has opened)
      - deadline > now                          (not yet past the deadline)
      - reminder_sent_at is NULL                (not already sent)
      - is_resolved is false
    """
    now = datetime.now(UTC)
    result = await session.execute(
        select(Obligation).where(
            col(Obligation.tenant_id) == tenant_id,
            col(Obligation.deadline).is_not(None),
            col(Obligation.deadline) > now,
            col(Obligation.reminder_sent_at).is_(None),
            col(Obligation.is_resolved).is_(False),
        )
    )
    # Filter reminder window in Python (avoids SQL column arithmetic with timedelta)
    obligations = list(result.scalars().all())
    return [
        o
        for o in obligations
        if o.deadline is not None
        and o.deadline - timedelta(days=o.reminder_days_before) <= now
    ]


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

async def create(
    session: AsyncSession,
    tenant_id: str,
    data: ObligationCreate,
) -> Obligation:
    """Insert and flush a new obligation row."""
    obligation = Obligation(
        tenant_id=tenant_id,
        **data.model_dump(),
    )
    session.add(obligation)
    await session.flush()
    return obligation


async def create_batch(
    session: AsyncSession,
    tenant_id: str,
    items: list[ObligationCreate],
) -> list[Obligation]:
    """Insert multiple obligations in one flush."""
    obligations = [
        Obligation(tenant_id=tenant_id, **item.model_dump()) for item in items
    ]
    for o in obligations:
        session.add(o)
    await session.flush()
    return obligations


async def patch(
    session: AsyncSession,
    tenant_id: str,
    obligation_id: uuid.UUID,
    data: ObligationPatch,
) -> Obligation | None:
    """Apply a partial update. Returns the updated row, or None if not found."""
    obligation = await get(session, tenant_id, obligation_id)
    if obligation is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obligation, field, value)
    session.add(obligation)
    await session.flush()
    return obligation


async def mark_resolved(
    session: AsyncSession,
    tenant_id: str,
    obligation_id: uuid.UUID,
) -> Obligation | None:
    """Set is_resolved=True. Returns None if obligation not found."""
    obligation = await get(session, tenant_id, obligation_id)
    if obligation is None:
        return None
    obligation.is_resolved = True
    session.add(obligation)
    await session.flush()
    return obligation


async def stamp_reminder_sent(
    session: AsyncSession,
    obligation: Obligation,
) -> None:
    """Set reminder_sent_at to now (called by the reminder worker after sending)."""
    obligation.reminder_sent_at = datetime.now(UTC)
    session.add(obligation)
    await session.flush()
