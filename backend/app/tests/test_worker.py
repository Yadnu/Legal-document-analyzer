"""Phase 3/4 worker tests.

Tests exercise ``worker.main.process_message`` directly (not via the SQS
polling loop) so they're fast and don't require a running SQS endpoint.

A live test database is required — the same pattern as test_rls.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.rls import set_tenant_context
from app.models.document import DocumentStatus
from app.repositories import document_repo
from app.repositories.document_repo import DocumentCreateData
from worker.main import process_message

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DB_URL = settings.test_database_url or settings.database_url


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def db_engine():
    engine = create_async_engine(_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_doc(
    session: AsyncSession, tenant_id: str, *, suffix: str = ""
) -> uuid.UUID:
    """Insert a minimal Document row in ``processing`` state; return its id."""
    await set_tenant_context(session, tenant_id)
    data = DocumentCreateData(
        title=f"Worker Test Doc {suffix}",
        original_filename=f"worker_test{suffix}.pdf",
        content_type="application/pdf",
        size_bytes=2048,
        s3_key=f"{tenant_id}/{uuid.uuid4()}/worker_test{suffix}.pdf",
        idempotency_key=f"worker_idem_{uuid.uuid4().hex}",
        uploaded_by="user_worker_test",
    )
    doc = await document_repo.create(session, tenant_id, data)
    await session.commit()
    return doc.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_worker_sets_status_ready(db_session: AsyncSession) -> None:
    """Worker processes a valid message → status transitions to ready."""
    tenant_id = f"org_worker_{uuid.uuid4().hex[:8]}"
    doc_id = await _create_doc(db_session, tenant_id, suffix="_ready")

    msg = {
        "document_id": str(doc_id),
        "tenant_id": tenant_id,
        "s3_key": f"{tenant_id}/{doc_id}/worker_test.pdf",
        "idempotency_key": "any_key",
    }

    with patch(
        "app.services.ingestion_service.ingest",
        new=AsyncMock(return_value=3),
    ):
        await process_message(msg, db_session)

    # Re-fetch to check status
    await set_tenant_context(db_session, tenant_id)
    doc = await document_repo.get_by_id(db_session, tenant_id, doc_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY


async def test_worker_sets_status_failed_on_error(db_session: AsyncSession) -> None:
    """Injecting an error inside process_message → status transitions to failed."""
    tenant_id = f"org_worker_{uuid.uuid4().hex[:8]}"
    doc_id = await _create_doc(db_session, tenant_id, suffix="_fail")

    msg = {
        "document_id": str(doc_id),
        "tenant_id": tenant_id,
        "s3_key": f"{tenant_id}/{doc_id}/fail.pdf",
        "idempotency_key": "fail_key",
    }

    async def _boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("simulated ingestion failure")

    with (
        patch(
            "app.services.ingestion_service.ingest",
            new=AsyncMock(side_effect=_boom),
        ),
        pytest.raises(RuntimeError, match="simulated ingestion failure"),
    ):
        await process_message(msg, db_session)

    # status must be failed
    await set_tenant_context(db_session, tenant_id)
    doc = await document_repo.get_by_id(db_session, tenant_id, doc_id)
    assert doc is not None
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_reason is not None
    assert "simulated ingestion failure" in doc.error_reason


async def test_worker_is_idempotent(db_session: AsyncSession) -> None:
    """Delivering the same message twice → status stays ready, no exception."""
    tenant_id = f"org_worker_{uuid.uuid4().hex[:8]}"
    doc_id = await _create_doc(db_session, tenant_id, suffix="_idem")

    msg = {
        "document_id": str(doc_id),
        "tenant_id": tenant_id,
        "s3_key": f"{tenant_id}/{doc_id}/idem.pdf",
        "idempotency_key": "idem_key_2",
    }

    with patch(
        "app.services.ingestion_service.ingest",
        new=AsyncMock(return_value=2),
    ):
        # First delivery — should set status to ready.
        await process_message(msg, db_session)

    await set_tenant_context(db_session, tenant_id)
    doc = await document_repo.get_by_id(db_session, tenant_id, doc_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY

    # Second delivery of the same message — must be a no-op, no exception.
    await process_message(msg, db_session)

    await set_tenant_context(db_session, tenant_id)
    doc = await document_repo.get_by_id(db_session, tenant_id, doc_id)
    assert doc is not None
    assert doc.status == DocumentStatus.READY
