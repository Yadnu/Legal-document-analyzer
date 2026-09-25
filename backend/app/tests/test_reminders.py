"""Deadline reminder tests — Phase 10B.

SES stays in its default log-only mode. The tests prove a due obligation is
stamped once, an obligation outside the window is skipped, and another
tenant's rows are untouched.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.rls import set_tenant_context
from app.models.document import DocumentStatus
from app.models.user import User
from app.repositories import document_repo, obligation_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.obligation import ObligationCreate
from app.services.reminder_service import send_due_reminders

TENANT = f"org_rem_{uuid.uuid4().hex[:8]}"
OTHER = f"org_rem_b_{uuid.uuid4().hex[:8]}"
ASSIGNEE = "user_reminder_assignee"

_DB_URL = settings.test_database_url or settings.database_url


@pytest.fixture()
async def db_engine():
    engine = create_async_engine(_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        await set_tenant_context(db, TENANT)
        yield db


async def _document(session: AsyncSession, tenant_id: str) -> uuid.UUID:
    await set_tenant_context(session, tenant_id)
    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title="Reminder Agreement",
            original_filename="reminder.pdf",
            content_type="application/pdf",
            size_bytes=256,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/reminder.pdf",
            idempotency_key=f"rem_{uuid.uuid4().hex}",
            uploaded_by=ASSIGNEE,
        ),
    )
    await document_repo.set_status(session, tenant_id, doc.id, DocumentStatus.READY)
    return doc.id


async def _assignee(session: AsyncSession, tenant_id: str) -> None:
    await set_tenant_context(session, tenant_id)
    session.add(
        User(
            tenant_id=tenant_id,
            clerk_user_id=ASSIGNEE,
            email="assignee@example.com",
            role="member",
        )
    )
    await session.flush()


async def _obligation(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    *,
    days_until_deadline: int,
    reminder_days_before: int,
) -> uuid.UUID:
    await set_tenant_context(session, tenant_id)
    row = await obligation_repo.create(
        session,
        tenant_id,
        ObligationCreate(
            document_id=document_id,
            description="Pay the invoice.",
            obligation_type="payment",
            deadline=datetime.now(UTC) + timedelta(days=days_until_deadline),
            reminder_days_before=reminder_days_before,
            assigned_to=ASSIGNEE,
        ),
    )
    await session.commit()
    return row.id


async def test_sends_once_and_stamps(session: AsyncSession) -> None:
    doc_id = await _document(session, TENANT)
    await _assignee(session, TENANT)
    obligation_id = await _obligation(
        session,
        TENANT,
        doc_id,
        days_until_deadline=3,
        reminder_days_before=7,
    )

    sent = await send_due_reminders(session, TENANT)
    assert sent == 1

    stored = await obligation_repo.get(session, TENANT, obligation_id)
    assert stored is not None
    assert stored.reminder_sent_at is not None

    again = await send_due_reminders(session, TENANT)
    assert again == 0


async def test_skips_obligation_outside_window(session: AsyncSession) -> None:
    doc_id = await _document(session, TENANT)
    await _assignee(session, TENANT)
    await _obligation(
        session,
        TENANT,
        doc_id,
        days_until_deadline=60,
        reminder_days_before=7,
    )
    assert await send_due_reminders(session, TENANT) == 0


async def test_does_not_touch_other_tenant(session: AsyncSession, db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as other:
        doc_id = await _document(other, OTHER)
        await _assignee(other, OTHER)
        foreign_id = await _obligation(
            other,
            OTHER,
            doc_id,
            days_until_deadline=2,
            reminder_days_before=7,
        )

    await set_tenant_context(session, TENANT)
    assert await send_due_reminders(session, TENANT) == 0

    async with factory() as other:
        await set_tenant_context(other, OTHER)
        stored = await obligation_repo.get(other, OTHER, foreign_id)
    assert stored is not None
    assert stored.reminder_sent_at is None
