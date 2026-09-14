"""Audit event repository.

The audit_events table is append-only (the DB-level RLS policy allows only
SELECT and INSERT; UPDATE and DELETE are denied by Postgres).  This repository
honours that contract: there is no update or delete function.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.audit_event import AuditEvent


async def append(
    session: AsyncSession,
    tenant_id: str,
    *,
    user_id: str,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    """Insert one immutable audit row and flush (does not commit).

    The caller owns the transaction; call ``session.commit()`` after any
    additional writes that should be atomic with this event.
    """
    event = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    session.add(event)
    await session.flush()
    return event


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: str,
    *,
    action_filter: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    """Return paginated audit events newest-first for a tenant.

    Returns (items, total_count).
    """
    base = select(AuditEvent).where(col(AuditEvent.tenant_id) == tenant_id)

    if action_filter:
        base = base.where(col(AuditEvent.action) == action_filter)
    if since:
        base = base.where(col(AuditEvent.created_at) >= since)

    count_result = await session.execute(
        select(func.count()).select_from(base.subquery())
    )
    total: int = count_result.scalar_one()

    items_result = await session.execute(
        base.order_by(col(AuditEvent.created_at).desc()).offset(offset).limit(limit)
    )
    return list(items_result.scalars().all()), total
