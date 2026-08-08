"""
Tenant isolation test — Phase 2 acceptance criteria.

Proves that Postgres Row-Level Security prevents tenant A from reading
tenant B's rows, even when both sessions connect with the same DB user.

Strategy
--------
1. Apply the migration to a disposable test database (handled by the
   test_db fixture in conftest.py — see note below if it doesn't exist yet).
2. Open two sessions, each with a different tenant context set via SET LOCAL.
3. Insert an Organization row as tenant A.
4. Query that row as tenant B — must return nothing.
5. Query that row as tenant A — must return exactly one row.

The test does NOT go through the FastAPI app or HTTP layer; it exercises
the DB session and RLS policies directly so failures are unambiguous.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.rls import set_tenant_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def rls_engine():
    """Async engine pointed at the test database."""
    url = settings.test_database_url or settings.database_url
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def tenant_ids() -> tuple[str, str]:
    """Fresh tenant pair per test so unique constraints never collide."""
    return (
        f"org_tenant_aaa_{uuid.uuid4().hex[:8]}",
        f"org_tenant_bbb_{uuid.uuid4().hex[:8]}",
    )


@pytest.fixture()
async def tenant_a_session(
    rls_engine, tenant_ids: tuple[str, str]
) -> AsyncGenerator[AsyncSession, None]:
    """Session with tenant A context active."""
    tenant_a, _ = tenant_ids
    async_session = async_sessionmaker(rls_engine, expire_on_commit=False)
    async with async_session() as session:
        await set_tenant_context(session, tenant_a)
        yield session


@pytest.fixture()
async def tenant_b_session(
    rls_engine, tenant_ids: tuple[str, str]
) -> AsyncGenerator[AsyncSession, None]:
    """Session with tenant B context active."""
    _, tenant_b = tenant_ids
    async_session = async_sessionmaker(rls_engine, expire_on_commit=False)
    async with async_session() as session:
        await set_tenant_context(session, tenant_b)
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_org(session: AsyncSession, tenant_id: str) -> uuid.UUID:
    """Insert a minimal organization row and return its id."""
    org_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO organizations
                (id, tenant_id, created_at, name, slug, clerk_org_id, plan,
                 is_active, max_documents, max_members)
            VALUES
                (:id, :tenant_id, now(), :name, :slug, :clerk_org_id,
                 'free', true, 50, 5)
            """),
        {
            "id": org_id,
            "tenant_id": tenant_id,
            "name": f"Org {tenant_id}",
            "slug": f"org-{tenant_id}",
            "clerk_org_id": tenant_id,
        },
    )
    await session.commit()
    return org_id


async def _count_orgs(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Count organization rows visible to the current tenant context."""
    result = await session.execute(
        text("SELECT COUNT(*) FROM organizations WHERE id = :id"),
        {"id": org_id},
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_rls_blocks_cross_tenant_read(
    tenant_a_session: AsyncSession,
    tenant_b_session: AsyncSession,
    tenant_ids: tuple[str, str],
) -> None:
    """Tenant B must not see tenant A's organization row."""
    tenant_a, _ = tenant_ids
    org_id = await _insert_org(tenant_a_session, tenant_a)

    count_as_b = await _count_orgs(tenant_b_session, org_id)
    assert count_as_b == 0, (
        f"RLS FAILURE: tenant B read {count_as_b} row(s) belonging to tenant A. "
        "Check that RLS is enabled and FORCE ROW LEVEL SECURITY is set."
    )


async def test_rls_allows_same_tenant_read(
    tenant_a_session: AsyncSession,
    tenant_ids: tuple[str, str],
) -> None:
    """Tenant A must see its own organization row."""
    tenant_a, _ = tenant_ids
    org_id = await _insert_org(tenant_a_session, tenant_a)

    count_as_a = await _count_orgs(tenant_a_session, org_id)
    assert count_as_a == 1, (
        f"Expected tenant A to read its own row, got {count_as_a}. "
        "Check that the RLS policy USING clause is correct."
    )


async def test_rls_blocks_cross_tenant_read_documents(
    tenant_a_session: AsyncSession,
    tenant_b_session: AsyncSession,
    tenant_ids: tuple[str, str],
) -> None:
    """
    RLS applies to every tenant table.
    Spot-check documents — a second table beyond organizations.
    """
    tenant_a, _ = tenant_ids
    doc_id = uuid.uuid4()
    await tenant_a_session.execute(
        text("""
            INSERT INTO documents
                (id, tenant_id, created_at, title, original_filename,
                 content_type, size_bytes, s3_key, idempotency_key,
                 status, uploaded_by)
            VALUES
                (:id, :tenant_id, now(), 'Secret Contract', 'secret.pdf',
                 'application/pdf', 12345, :s3_key, :idem_key,
                 'processing', 'user_aaa')
            """),
        {
            "id": doc_id,
            "tenant_id": tenant_a,
            "s3_key": f"tenant-a/{doc_id}/secret.pdf",
            "idem_key": str(doc_id),
        },
    )
    await tenant_a_session.commit()

    result = await tenant_b_session.execute(
        text("SELECT COUNT(*) FROM documents WHERE id = :id"),
        {"id": doc_id},
    )
    count = result.scalar_one()
    assert (
        count == 0
    ), f"RLS FAILURE on documents: tenant B read {count} row(s) belonging to tenant A."


async def test_no_tenant_context_reads_nothing() -> None:
    """
    A session with no tenant context set must see zero rows from any table.

    current_setting('app.current_tenant_id', true) returns NULL when the
    variable is not set, so tenant_id = NULL is always false — RLS blocks all rows.
    """
    url = settings.test_database_url or settings.database_url
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # Deliberately do NOT call set_tenant_context
        result = await session.execute(text("SELECT COUNT(*) FROM organizations"))
        count = result.scalar_one()

    await engine.dispose()

    assert count == 0, (
        f"RLS FAILURE: a session with no tenant context read "
        f"{count} organization row(s). "
        "Ensure FORCE ROW LEVEL SECURITY is set and the policy uses the 'true' "
        "missing-ok flag on current_setting."
    )
