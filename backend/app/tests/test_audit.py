"""Audit log tests — Phase 10C.

A comment write produces an audit row. Admins can read it; another tenant
cannot.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import col

from app.core.config import settings
from app.core.deps import (
    OrgRole,
    get_current_role,
    get_current_tenant,
    get_current_user,
)
from app.db.rls import set_tenant_context
from app.db.session import get_rls_db
from app.ingestion.chunker import ChunkData
from app.ingestion.embedder import embed_texts
from app.main import create_app
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.repositories import chunk_repo, document_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext

AUTHOR = UserContext(user_id="user_audit_author")
TENANT = TenantContext(
    tenant_id=f"org_aud_{uuid.uuid4().hex[:8]}",
    slug="audit-test",
)
OTHER_TENANT = TenantContext(
    tenant_id=f"org_aud_b_{uuid.uuid4().hex[:8]}",
    slug="audit-other",
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


def _client(
    session: AsyncSession,
    *,
    role: OrgRole,
    tenant: TenantContext = TENANT,
) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: AUTHOR
    app.dependency_overrides[get_current_tenant] = lambda t=tenant: t
    app.dependency_overrides[get_current_role] = lambda r=role: r

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_rls_db] = override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_chunk(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    await set_tenant_context(session, TENANT.tenant_id)
    doc = await document_repo.create(
        session,
        TENANT.tenant_id,
        DocumentCreateData(
            title="Audit Test",
            original_filename="audit.pdf",
            content_type="application/pdf",
            size_bytes=512,
            s3_key=f"{TENANT.tenant_id}/{uuid.uuid4()}/audit.pdf",
            idempotency_key=f"aud_{uuid.uuid4().hex}",
            uploaded_by=AUTHOR.user_id,
        ),
    )
    await document_repo.set_status(
        session, TENANT.tenant_id, doc.id, DocumentStatus.READY
    )
    text = "Either party may terminate with thirty days notice."
    embeddings = await embed_texts([text])
    await chunk_repo.upsert_chunks(
        session,
        TENANT.tenant_id,
        doc.id,
        [
            ChunkData(
                content=text,
                section_number="4",
                heading="Termination",
                page=1,
                cross_refs=[],
                token_count=8,
            )
        ],
        embeddings,
        settings.embedding_model,
        settings.embedding_model_version,
    )
    await session.commit()
    result = await session.execute(
        select(Chunk).where(col(Chunk.document_id) == doc.id)
    )
    return doc.id, result.scalars().one().id


async def test_comment_creates_audit_event(tenant_session: AsyncSession) -> None:
    doc_id, chunk_id = await _seed_chunk(tenant_session)
    async with _client(tenant_session, role=OrgRole.EDITOR) as editor:
        created = await editor.post(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments",
            json={"body": "Flag this termination clause."},
        )
    assert created.status_code == 201, created.text

    async with _client(tenant_session, role=OrgRole.ADMIN) as admin:
        log = await admin.get("/api/v1/audit-log", params={"action": "comment.created"})
    assert log.status_code == 200, log.text
    body = log.json()
    assert body["total"] >= 1
    assert any(item["action"] == "comment.created" for item in body["items"])
    assert all(item["user_id"] == AUTHOR.user_id for item in body["items"])


async def test_audit_log_tenant_isolation(
    tenant_session: AsyncSession,
    db_engine,
) -> None:
    doc_id, chunk_id = await _seed_chunk(tenant_session)
    async with _client(tenant_session, role=OrgRole.EDITOR) as editor:
        created = await editor.post(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments",
            json={"body": "Tenant A only."},
        )
    assert created.status_code == 201, created.text

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as other_session:
        await set_tenant_context(other_session, OTHER_TENANT.tenant_id)
        async with _client(
            other_session, role=OrgRole.ADMIN, tenant=OTHER_TENANT
        ) as outsider:
            log = await outsider.get("/api/v1/audit-log")
    assert log.status_code == 200, log.text
    actions = [item["action"] for item in log.json()["items"]]
    assert "comment.created" not in actions
