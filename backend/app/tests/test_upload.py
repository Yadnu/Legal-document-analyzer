"""Phase 3 upload pipeline tests.

Strategy
--------
- HTTP layer:  tests go through the FastAPI app with auth dependencies stubbed
  (same pattern as test_me.py) and AWS clients patched with unittest.mock so
  no real S3/SQS is needed.
- Repository layer:  tests use a live test database (same pattern as
  test_rls.py) so SQL correctness is verified without fake objects.

Each test proves exactly one row in the T9 acceptance table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.deps import get_current_tenant, get_current_user
from app.db.rls import set_tenant_context
from app.db.session import get_rls_db
from app.main import create_app
from app.models.document import DocumentStatus
from app.repositories import document_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_USER = UserContext(user_id="user_upload_test")
FAKE_TENANT = TenantContext(
    tenant_id=f"org_upload_{uuid.uuid4().hex[:8]}",
    slug="upload-test",
)
FAKE_PRESIGNED_URL = "https://s3.example.com/presigned-put-url"

_DB_URL = settings.test_database_url or settings.database_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def db_engine():
    engine = create_async_engine(_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def tenant_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Tenant-scoped session for the fake tenant used by upload tests."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await set_tenant_context(session, FAKE_TENANT.tenant_id)
        yield session


@pytest.fixture()
def _patch_aws():
    """Patch get_s3_client and get_sqs_client so no real AWS calls are made."""
    # S3: generate_presigned_url returns FAKE_PRESIGNED_URL
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_url = AsyncMock(return_value=FAKE_PRESIGNED_URL)
    s3_ctx = MagicMock()
    s3_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
    s3_ctx.__aexit__ = AsyncMock(return_value=False)

    # SQS: send_message returns a stub response
    mock_sqs = AsyncMock()
    mock_sqs.send_message = AsyncMock(return_value={"MessageId": "fake-msg-id"})
    sqs_ctx = MagicMock()
    sqs_ctx.__aenter__ = AsyncMock(return_value=mock_sqs)
    sqs_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.infra.aws.get_s3_client", return_value=s3_ctx),
        patch("app.infra.aws.get_sqs_client", return_value=sqs_ctx),
        patch("app.services.upload_service.get_s3_client", return_value=s3_ctx),
        patch("app.services.upload_service.get_sqs_client", return_value=sqs_ctx),
    ):
        yield mock_s3, mock_sqs


@pytest.fixture()
async def authed_client(
    tenant_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Client with auth stubbed and DB session wired to the test transaction."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_current_tenant] = lambda: FAKE_TENANT

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield tenant_session

    app.dependency_overrides[get_rls_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _upload_body(
    filename: str = "contract.pdf",
    content_type: str = "application/pdf",
    size_bytes: int = 1024,
) -> dict[str, Any]:
    return {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
    }


# ---------------------------------------------------------------------------
# T9 tests
# ---------------------------------------------------------------------------


async def test_request_upload_returns_presigned_url(
    authed_client: AsyncClient,
    _patch_aws: Any,
) -> None:
    """Valid request → 201, presigned URL present, document created processing."""
    resp = await authed_client.post(
        "/api/v1/documents/upload-url", json=_upload_body()
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["upload_url"] == FAKE_PRESIGNED_URL
    assert "document_id" in data
    assert "s3_key" in data
    assert data["expires_in"] > 0


async def test_upload_rejects_invalid_content_type(
    authed_client: AsyncClient,
    _patch_aws: Any,
) -> None:
    """PDF-only policy enforced → 422."""
    resp = await authed_client.post(
        "/api/v1/documents/upload-url",
        json=_upload_body(content_type="image/jpeg"),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "Unprocessable Entity"


async def test_upload_rejects_oversized_file(
    authed_client: AsyncClient,
    _patch_aws: Any,
) -> None:
    """Size limit enforced → 422 when size_bytes > upload_max_size_bytes."""
    oversized = settings.upload_max_size_bytes + 1
    resp = await authed_client.post(
        "/api/v1/documents/upload-url",
        json=_upload_body(size_bytes=oversized),
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "Unprocessable Entity"


async def test_confirm_enqueues_sqs_message(
    authed_client: AsyncClient,
    _patch_aws: Any,
    tenant_session: AsyncSession,
) -> None:
    """After confirm, SQS send_message was called with the correct document_id."""
    _, mock_sqs = _patch_aws

    # First create a document via upload-url
    resp = await authed_client.post(
        "/api/v1/documents/upload-url",
        json=_upload_body(filename="confirm_test.pdf"),
    )
    assert resp.status_code == 201
    doc_id = resp.json()["document_id"]

    # Now confirm
    resp = await authed_client.post(f"/api/v1/documents/{doc_id}/confirm")
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id

    # SQS send_message must have been called with the right document_id
    mock_sqs.send_message.assert_called_once()
    call_kwargs = mock_sqs.send_message.call_args.kwargs
    body = json.loads(call_kwargs["MessageBody"])
    assert body["document_id"] == doc_id
    assert body["tenant_id"] == FAKE_TENANT.tenant_id


async def test_upload_is_idempotent(
    authed_client: AsyncClient,
    _patch_aws: Any,
    tenant_session: AsyncSession,
) -> None:
    """Same (tenant, filename, size) → same document_id, no duplicate rows."""
    body = _upload_body(filename="idempotent.pdf", size_bytes=2048)

    resp1 = await authed_client.post("/api/v1/documents/upload-url", json=body)
    assert resp1.status_code == 201
    doc_id_1 = resp1.json()["document_id"]

    resp2 = await authed_client.post("/api/v1/documents/upload-url", json=body)
    assert resp2.status_code == 201
    doc_id_2 = resp2.json()["document_id"]

    assert doc_id_1 == doc_id_2, (
        "Second upload with same params must return the same document_id"
    )


async def test_get_document_returns_status(
    authed_client: AsyncClient,
    _patch_aws: Any,
) -> None:
    """Polling endpoint returns current status."""
    resp = await authed_client.post(
        "/api/v1/documents/upload-url",
        json=_upload_body(filename="poll_test.pdf"),
    )
    assert resp.status_code == 201
    doc_id = resp.json()["document_id"]

    resp = await authed_client.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == doc_id
    assert data["status"] == DocumentStatus.PROCESSING


async def test_tenant_cannot_read_other_tenant_document(
    _patch_aws: Any,
    db_engine,
) -> None:
    """Tenant B cannot GET tenant A's document → 404."""
    tenant_a = TenantContext(
        tenant_id=f"org_a_{uuid.uuid4().hex[:8]}", slug="a"
    )
    tenant_b = TenantContext(
        tenant_id=f"org_b_{uuid.uuid4().hex[:8]}", slug="b"
    )
    fake_user = UserContext(user_id="user_isolation")

    # Insert a document as tenant A directly via repo
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session_a:
        await set_tenant_context(session_a, tenant_a.tenant_id)
        data = DocumentCreateData(
            title="Secret Contract",
            original_filename="secret.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            s3_key=(
                f"{tenant_a.tenant_id}/{uuid.uuid4()}/secret.pdf"
            ),
            idempotency_key=f"isolation_key_{uuid.uuid4().hex}",
            uploaded_by=fake_user.user_id,
        )
        doc = await document_repo.create(session_a, tenant_a.tenant_id, data)
        await session_a.commit()
        doc_id = doc.id

    # Now try to GET it as tenant B via the HTTP layer
    async with factory() as session_b:
        await set_tenant_context(session_b, tenant_b.tenant_id)

        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_current_tenant] = lambda: tenant_b

        async def override_db_b() -> AsyncGenerator[AsyncSession, None]:
            yield session_b

        app.dependency_overrides[get_rls_db] = override_db_b

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client_b:
            resp = await client_b.get(f"/api/v1/documents/{doc_id}")

        assert resp.status_code == 404, (
            "RLS FAILURE: tenant B read tenant A's document. "
            f"Response: {resp.text}"
        )
