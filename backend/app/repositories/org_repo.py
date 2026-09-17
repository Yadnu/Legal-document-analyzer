"""Organization repository.

Provides read and write access to the organizations table.
Note: the tenant_id on the Organization row equals its own clerk_org_id —
this is intentional (self-referential RLS consistent with every other table).
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.organization import Organization


async def get_for_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> Organization | None:
    """Return the Organization row for this tenant, or None."""
    result = await session.execute(
        select(Organization).where(
            col(Organization.tenant_id) == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def increment_qa_used(
    session: AsyncSession,
    tenant_id: str,
) -> None:
    """Atomically increment monthly_qa_used by 1 for this tenant.

    Does not commit — the caller's transaction covers it.
    """
    await session.execute(
        update(Organization)
        .where(col(Organization.tenant_id) == tenant_id)
        .values(monthly_qa_used=Organization.monthly_qa_used + 1)
    )


async def reset_monthly_qa_used(session: AsyncSession) -> int:
    """Set monthly_qa_used = 0 for every organization.

    Called by the scheduler on the 1st of every month.
    Returns the number of rows updated.
    """
    result = await session.execute(update(Organization).values(monthly_qa_used=0))
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
