from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from fastapi import Depends

from app.core.config import settings
from app.core.deps import get_current_tenant
from app.db.rls import set_tenant_context
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
    SET LOCAL scopes the variable to the current transaction — it resets
    automatically when the session is returned to the pool.
    """
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant.tenant_id)
        yield session
