"""Workspace invite repository."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.workspace_invite import WorkspaceInvite


async def expire_overdue(
    session: AsyncSession,
    tenant_id: str,
    now: datetime,
) -> None:
    """Mark pending invites past ``expires_at`` as expired. Does not commit."""
    await session.execute(
        update(WorkspaceInvite)
        .where(
            col(WorkspaceInvite.tenant_id) == tenant_id,
            col(WorkspaceInvite.status) == "pending",
            col(WorkspaceInvite.expires_at) < now,
        )
        .values(status="expired")
    )


async def get(
    session: AsyncSession,
    tenant_id: str,
    invite_id: uuid.UUID,
) -> WorkspaceInvite | None:
    result = await session.execute(
        select(WorkspaceInvite).where(
            col(WorkspaceInvite.tenant_id) == tenant_id,
            col(WorkspaceInvite.id) == invite_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_token_hash(
    session: AsyncSession,
    token_hash: str,
) -> WorkspaceInvite | None:
    """Return the invite for this hash.

    Caller must have set the invite-token RLS variable first. The SQL filter
    is a second check so a bypassed policy still cannot return another row.
    """
    result = await session.execute(
        select(WorkspaceInvite).where(col(WorkspaceInvite.token_hash) == token_hash)
    )
    return result.scalar_one_or_none()


async def get_pending_for_email(
    session: AsyncSession,
    tenant_id: str,
    email: str,
) -> WorkspaceInvite | None:
    result = await session.execute(
        select(WorkspaceInvite).where(
            col(WorkspaceInvite.tenant_id) == tenant_id,
            col(WorkspaceInvite.email) == email,
            col(WorkspaceInvite.status) == "pending",
        )
    )
    return result.scalar_one_or_none()


async def list_pending(
    session: AsyncSession,
    tenant_id: str,
) -> list[WorkspaceInvite]:
    result = await session.execute(
        select(WorkspaceInvite)
        .where(
            col(WorkspaceInvite.tenant_id) == tenant_id,
            col(WorkspaceInvite.status) == "pending",
        )
        .order_by(col(WorkspaceInvite.created_at).desc())
    )
    return list(result.scalars().all())


async def count_pending(session: AsyncSession, tenant_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(WorkspaceInvite)
        .where(
            col(WorkspaceInvite.tenant_id) == tenant_id,
            col(WorkspaceInvite.status) == "pending",
        )
    )
    return int(result.scalar_one())


async def create(
    session: AsyncSession,
    tenant_id: str,
    *,
    email: str,
    role: str,
    token_hash: str,
    invited_by: str,
    expires_at: datetime,
) -> WorkspaceInvite:
    invite = WorkspaceInvite(
        tenant_id=tenant_id,
        email=email,
        role=role,
        token_hash=token_hash,
        status="pending",
        invited_by=invited_by,
        expires_at=expires_at,
    )
    session.add(invite)
    await session.flush()
    return invite
