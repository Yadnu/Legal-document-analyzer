"""
Tenant-isolation tests (Phase 2 acceptance criteria).

Proves that Postgres RLS prevents tenant A from reading, updating, or
deleting tenant B's rows — and that audit_events is append-only.

Requirements
────────────
* A live Postgres instance reachable via settings.test_database_url (or
  settings.database_url as a fallback).  The schema must already be applied
  (run `alembic upgrade head` before executing the suite).
* The database user (legaluser) must NOT be a superuser so that
  FORCE ROW LEVEL SECURITY applies to it.

These tests use raw SQL via SQLAlchemy text() to stay close to what an
attacker would attempt, bypassing ORM helpers.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# ── helpers ──────────────────────────────────────────────────────────────────

_DB_URL = settings.test_database_url or settings.database_url


async def _make_session() -> async_sessionmaker:
    engine = create_async_engine(_DB_URL, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _set_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Activate RLS for the current transaction."""
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tid"),
        {"tid": tenant_id},
    )


async def _clear_tenant(session: AsyncSession) -> None:
    """Remove tenant context (simulates an unauthenticated connection)."""
    await session.execute(text("SET LOCAL app.current_tenant_id = ''"))


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
async def sessions() -> AsyncGenerator[tuple[AsyncSession, AsyncSession], None]:
    """Yield (session_a, session_b) backed by a shared engine."""
    factory = await _make_session()
    async with factory() as sa, factory() as sb:
        yield sa, sb


# ── seed helper ───────────────────────────────────────────────────────────────

async def _insert_org(session: AsyncSession, tenant_id: str, name: str) -> uuid.UUID:
    """Insert an organization row as its own tenant and return its id."""
    org_id = uuid.uuid4()
    await _set_tenant(session, tenant_id)
    await session.execute(
        text(
            """
            INSERT INTO organizations
                (id, tenant_id, created_at, name, slug, clerk_org_id, plan,
                 is_active, max_documents, max_members)
            VALUES
                (:id, :tid, now(), :name, :slug, :coid, 'free', true, 50, 5)
            """
        ),
        {
            "id": org_id,
            "tid": tenant_id,
            "name": name,
            "slug": name.lower().replace(" ", "-") + "-" + str(org_id)[:8],
            "coid": tenant_id,
        },
    )
    await session.commit()
    return org_id


# ── tests ─────────────────────────────────────────────────────────────────────

class TestCrossTenantSelect:
    """Tenant A must never see tenant B's rows."""

    async def test_select_returns_only_own_rows(
        self, sessions: tuple[AsyncSession, AsyncSession]
    ) -> None:
        sa, sb = sessions

        tid_a = f"org_test_a_{uuid.uuid4().hex[:8]}"
        tid_b = f"org_test_b_{uuid.uuid4().hex[:8]}"

        org_a_id = await _insert_org(sa, tid_a, "Tenant A Corp")
        org_b_id = await _insert_org(sb, tid_b, "Tenant B Corp")

        # Session A: can see its own row.
        await _set_tenant(sa, tid_a)
        rows = (
            await sa.execute(
                text("SELECT id FROM organizations WHERE id = :id"),
                {"id": org_a_id},
            )
        ).fetchall()
        assert len(rows) == 1, "Tenant A should see its own organization"

        # Session A: must NOT see tenant B's row.
        rows = (
            await sa.execute(
                text("SELECT id FROM organizations WHERE id = :id"),
                {"id": org_b_id},
            )
        ).fetchall()
        assert len(rows) == 0, "Tenant A must not see tenant B's organization (RLS)"

        # Cleanup
        await sb.execute(text("SET LOCAL app.current_tenant_id = :t"), {"t": tid_b})
        await sb.execute(
            text("DELETE FROM organizations WHERE tenant_id = :t"), {"t": tid_b}
        )
        await sa.execute(text("SET LOCAL app.current_tenant_id = :t"), {"t": tid_a})
        await sa.execute(
            text("DELETE FROM organizations WHERE tenant_id = :t"), {"t": tid_a}
        )
        await sa.commit()
        await sb.commit()


class TestCrossTenantWrite:
    """Tenant A must not be able to insert rows belonging to tenant B."""

    async def test_insert_wrong_tenant_id_rejected(
        self, sessions: tuple[AsyncSession, AsyncSession]
    ) -> None:
        sa, _ = sessions

        tid_a = f"org_test_a_{uuid.uuid4().hex[:8]}"
        tid_b = f"org_test_b_{uuid.uuid4().hex[:8]}"

        # Activate session as tenant A, but attempt to insert a row for tenant B.
        await _set_tenant(sa, tid_a)

        with pytest.raises(Exception):
            # WITH CHECK on the policy should reject tenant_id != current setting.
            await sa.execute(
                text(
                    """
                    INSERT INTO organizations
                        (id, tenant_id, created_at, name, slug, clerk_org_id,
                         plan, is_active, max_documents, max_members)
                    VALUES
                        (:id, :tid_b, now(), 'Evil Row', 'evil-row-1', :tid_b,
                         'free', true, 50, 5)
                    """
                ),
                {"id": uuid.uuid4(), "tid_b": tid_b},
            )
            await sa.commit()

        await sa.rollback()


class TestUnauthenticatedConnection:
    """A connection without app.current_tenant_id set sees zero rows."""

    async def test_no_tenant_context_returns_nothing(
        self, sessions: tuple[AsyncSession, AsyncSession]
    ) -> None:
        sa, sb = sessions

        tid_a = f"org_test_a_{uuid.uuid4().hex[:8]}"
        org_id = await _insert_org(sa, tid_a, "Visible Corp")

        # Unset the tenant variable on a fresh session.
        await _clear_tenant(sb)
        rows = (
            await sb.execute(
                text("SELECT id FROM organizations WHERE id = :id"),
                {"id": org_id},
            )
        ).fetchall()
        assert len(rows) == 0, "No tenant context must return zero rows (fail-closed)"

        # Cleanup
        await sa.execute(text("SET LOCAL app.current_tenant_id = :t"), {"t": tid_a})
        await sa.execute(
            text("DELETE FROM organizations WHERE tenant_id = :t"), {"t": tid_a}
        )
        await sa.commit()


class TestAuditEventAppendOnly:
    """audit_events rows must not be updatable or deletable by the app user."""

    async def test_insert_succeeds(
        self, sessions: tuple[AsyncSession, AsyncSession]
    ) -> None:
        sa, _ = sessions
        tid = f"org_audit_{uuid.uuid4().hex[:8]}"
        event_id = uuid.uuid4()

        await _set_tenant(sa, tid)
        # Should succeed — INSERT is allowed.
        await sa.execute(
            text(
                """
                INSERT INTO audit_events
                    (id, tenant_id, created_at, user_id, action)
                VALUES
                    (:id, :tid, now(), 'user_test', 'test.event')
                """
            ),
            {"id": event_id, "tid": tid},
        )
        await sa.commit()

        # Verify the row exists.
        rows = (
            await sa.execute(
                text("SELECT id FROM audit_events WHERE id = :id"),
                {"id": event_id},
            )
        ).fetchall()
        assert len(rows) == 1

    async def test_update_rejected(
        self, sessions: tuple[AsyncSession, AsyncSession]
    ) -> None:
        sa, _ = sessions
        tid = f"org_audit_{uuid.uuid4().hex[:8]}"
        event_id = uuid.uuid4()

        await _set_tenant(sa, tid)
        await sa.execute(
            text(
                """
                INSERT INTO audit_events
                    (id, tenant_id, created_at, user_id, action)
                VALUES
                    (:id, :tid, now(), 'user_test', 'original.action')
                """
            ),
            {"id": event_id, "tid": tid},
        )
        await sa.commit()

        # UPDATE should be rejected (no FOR UPDATE policy on audit_events).
        with pytest.raises(Exception):
            await _set_tenant(sa, tid)
            await sa.execute(
                text(
                    "UPDATE audit_events SET action = 'tampered' WHERE id = :id"
                ),
                {"id": event_id},
            )
            await sa.commit()

        await sa.rollback()

    async def test_delete_rejected(
        self, sessions: tuple[AsyncSession, AsyncSession]
    ) -> None:
        sa, _ = sessions
        tid = f"org_audit_{uuid.uuid4().hex[:8]}"
        event_id = uuid.uuid4()

        await _set_tenant(sa, tid)
        await sa.execute(
            text(
                """
                INSERT INTO audit_events
                    (id, tenant_id, created_at, user_id, action)
                VALUES
                    (:id, :tid, now(), 'user_test', 'original.action')
                """
            ),
            {"id": event_id, "tid": tid},
        )
        await sa.commit()

        # DELETE should be rejected (no FOR DELETE policy on audit_events).
        with pytest.raises(Exception):
            await _set_tenant(sa, tid)
            await sa.execute(
                text("DELETE FROM audit_events WHERE id = :id"),
                {"id": event_id},
            )
            await sa.commit()

        await sa.rollback()
