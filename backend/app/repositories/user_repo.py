"""User repository — membership rows inside one tenant."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.user import User


async def list_active(session: AsyncSession, tenant_id: str) -> list[User]:
    """Return active members, admins first, then by email."""
    result = await session.execute(
        select(User)
        .where(
            col(User.tenant_id) == tenant_id,
            col(User.is_active).is_(True),
        )
        .order_by(col(User.role).asc(), col(User.email).asc())
    )
    return list(result.scalars().all())


async def get_by_clerk_id(
    session: AsyncSession,
    tenant_id: str,
    clerk_user_id: str,
) -> User | None:
    result = await session.execute(
        select(User).where(
            col(User.tenant_id) == tenant_id,
            col(User.clerk_user_id) == clerk_user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_email(
    session: AsyncSession,
    tenant_id: str,
    email: str,
) -> User | None:
    result = await session.execute(
        select(User)
        .where(
            col(User.tenant_id) == tenant_id,
            col(User.email) == email,
        )
        .limit(1)
    )
    return result.scalars().first()


async def count_active(session: AsyncSession, tenant_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(User)
        .where(
            col(User.tenant_id) == tenant_id,
            col(User.is_active).is_(True),
        )
    )
    return int(result.scalar_one())


async def count_active_admins(session: AsyncSession, tenant_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(User)
        .where(
            col(User.tenant_id) == tenant_id,
            col(User.is_active).is_(True),
            col(User.role) == "admin",
        )
    )
    return int(result.scalar_one())


async def ensure_member(
    session: AsyncSession,
    tenant_id: str,
    *,
    clerk_user_id: str,
    email: str,
    full_name: str | None,
    role: str,
) -> User:
    """Insert the caller if they have no membership row yet.

    Does not overwrite an existing role. A later GET must not undo an
    admin's role change before the caller's JWT refreshes.
    """
    existing = await get_by_clerk_id(session, tenant_id, clerk_user_id)
    if existing is not None:
        return existing

    stmt = (
        insert(User)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_at=datetime.now(UTC),
            clerk_user_id=clerk_user_id,
            email=email,
            full_name=full_name,
            role=role,
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "clerk_user_id"])
    )
    await session.execute(stmt)
    stored = await get_by_clerk_id(session, tenant_id, clerk_user_id)
    if stored is None:
        raise RuntimeError("Membership insert did not persist.")
    return stored
