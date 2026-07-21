"""
Postgres Row-Level Security helpers.

The app uses a per-connection session variable `app.current_tenant_id` as the
RLS predicate. Setting it with SET LOCAL ensures it is automatically cleared
when the connection is returned to the pool (SET LOCAL scopes to the current
transaction; asyncpg begins an implicit transaction on first statement).

Usage in dependencies:
    await set_tenant_context(session, tenant_id)

Usage in tests (direct SQL):
    await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set the RLS session variable for the current transaction."""
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tid"),
        {"tid": tenant_id},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """
    Reset the session variable.

    Not needed in normal request flow (SET LOCAL auto-resets at transaction end),
    but useful in tests that reuse the same session across multiple tenants.
    """
    await session.execute(text("SET LOCAL app.current_tenant_id = ''"))
