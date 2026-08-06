from collections.abc import AsyncGenerator
from contextlib import suppress

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.deps import get_current_tenant
from app.db.rls import clear_tenant_context, set_tenant_context
from app.schemas.auth import TenantContext

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Unauthenticated DB session — use only for health checks and public routes."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_rls_db(
    tenant: TenantContext = Depends(get_current_tenant),
) -> AsyncGenerator[AsyncSession, None]:
    """
    Tenant-scoped DB session for all protected routes.

    Sets the Postgres session variable `app.current_tenant_id` so that RLS
    policies automatically filter every query to the current tenant's rows.
    Cleared in ``finally`` so a pooled connection never leaks tenant context.
    """
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant.tenant_id)
        try:
            yield session
        finally:
            with suppress(Exception):
                await clear_tenant_context(session)
