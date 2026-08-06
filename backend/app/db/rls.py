"""
Postgres Row-Level Security helpers.

The app uses a per-connection session variable ``app.current_tenant_id`` as the
RLS predicate. We set it via ``set_config`` (not ``SET LOCAL ... = $1``) because
asyncpg cannot bind parameters into SET.

Tenant id is also stored on ``session.info`` and re-applied on every
``after_begin`` so it survives commit/rollback (which may check out a fresh
connection from the pool, including NullPool).
"""

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_TENANT_KEY = "tenant_id"


def _apply_tenant_on_connection(connection, tenant_id: str) -> None:
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, false)"),
        {"tid": tenant_id},
    )


@event.listens_for(Session, "after_begin")
def _reapply_tenant_after_begin(
    session: Session, transaction, connection
) -> None:  # noqa: ANN001
    tenant_id = session.info.get(_TENANT_KEY)
    if tenant_id is not None:
        _apply_tenant_on_connection(connection, tenant_id)


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set the RLS session variable and remember it for future transactions."""
    session.info[_TENANT_KEY] = tenant_id
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, false)"),
        {"tid": tenant_id},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """Reset the session variable before the connection returns to the pool."""
    session.info.pop(_TENANT_KEY, None)
    await session.execute(text("SELECT set_config('app.current_tenant_id', '', false)"))
