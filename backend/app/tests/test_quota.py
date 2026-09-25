"""Quota enforcement tests — Phase 10E.

An organization row at its limit makes upload and Q&A return 429. The quota
check runs before S3 and retrieval, so those paths stay mocked out.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.deps import (
    OrgRole,
    get_current_role,
    get_current_tenant,
    get_current_user,
)
from app.db.rls import set_tenant_context
from app.db.session import get_rls_db
from app.main import create_app
from app.models.document import DocumentStatus
from app.models.organization import Organization
from app.repositories import document_repo, org_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext

USER = UserContext(user_id="user_quota_test")
TENANT = TenantContext(
    tenant_id=f"org_qta_{uuid.uuid4().hex[:8]}",
    slug="quota-test",
)

_DB_URL = settings.test_database_url or settings.database_url


@pytest.fixture()
async def db_engine():
    engine = create_async_engine(_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def tenant_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await set_tenant_context(session, TENANT.tenant_id)
        yield session


@pytest.fixture()
async def client(tenant_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    app.dependency_overrides[get_current_role] = lambda: OrgRole.EDITOR

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield tenant_session

    app.dependency_overrides[get_rls_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def _org(
    session: AsyncSession,
    *,
    max_documents: int,
    monthly_qa_quota: int,
    monthly_qa_used: int,
) -> None:
    existing = await org_repo.get_for_tenant(session, TENANT.tenant_id)
    if existing is None:
        session.add(
            Organization(
                tenant_id=TENANT.tenant_id,
                name="Quota Org",
                slug=f"quota-{uuid.uuid4().hex[:8]}",
                clerk_org_id=TENANT.tenant_id,
                max_documents=max_documents,
                monthly_qa_quota=monthly_qa_quota,
                monthly_qa_used=monthly_qa_used,
            )
        )
    else:
        existing.max_documents = max_documents
        existing.monthly_qa_quota = monthly_qa_quota
        existing.monthly_qa_used = monthly_qa_used
        session.add(existing)
    await session.commit()


async def test_upload_rejected_when_doc_quota_reached(
    client: AsyncClient,
    tenant_session: AsyncSession,
) -> None:
    await _org(
        tenant_session,
        max_documents=1,
        monthly_qa_quota=10,
        monthly_qa_used=0,
    )
    doc = await document_repo.create(
        tenant_session,
        TENANT.tenant_id,
        DocumentCreateData(
            title="Existing",
            original_filename="existing.pdf",
            content_type="application/pdf",
            size_bytes=100,
            s3_key=f"{TENANT.tenant_id}/{uuid.uuid4()}/existing.pdf",
            idempotency_key=f"qta_{uuid.uuid4().hex}",
            uploaded_by=USER.user_id,
        ),
    )
    await document_repo.set_status(
        tenant_session, TENANT.tenant_id, doc.id, DocumentStatus.READY
    )
    await tenant_session.commit()

    resp = await client.post(
        "/api/v1/documents/upload-url",
        json={
            "filename": "another.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
    )
    assert resp.status_code == 429, resp.text
    assert resp.json()["error"] == "Too Many Requests"


async def test_query_rejected_when_qa_quota_reached(
    client: AsyncClient,
    tenant_session: AsyncSession,
) -> None:
    await _org(
        tenant_session,
        max_documents=50,
        monthly_qa_quota=2,
        monthly_qa_used=2,
    )
    resp = await client.post(
        "/api/v1/query",
        json={"question": "What is the payment term?"},
    )
    assert resp.status_code == 429, resp.text
    assert resp.json()["error"] == "Too Many Requests"
