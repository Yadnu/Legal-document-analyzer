"""Clause comment tests — Phase 10D.

Auth deps are stubbed. A live Postgres session is wired in like the upload
tests. Each case covers one rule: create/list, author-or-admin delete, and
tenant isolation.
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

AUTHOR = UserContext(user_id="user_comment_author")
OTHER_USER = UserContext(user_id="user_comment_other")
TENANT = TenantContext(
    tenant_id=f"org_cmt_{uuid.uuid4().hex[:8]}",
    slug="comment-test",
)
OTHER_TENANT = TenantContext(
    tenant_id=f"org_cmt_b_{uuid.uuid4().hex[:8]}",
    slug="comment-other",
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
    user: UserContext,
    role: OrgRole,
    tenant: TenantContext = TENANT,
) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda u=user: u
    app.dependency_overrides[get_current_tenant] = lambda t=tenant: t
    app.dependency_overrides[get_current_role] = lambda r=role: r

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_rls_db] = override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_chunk(
    session: AsyncSession, tenant_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    await set_tenant_context(session, tenant_id)
    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title="Comment Test",
            original_filename="comment.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/comment.pdf",
            idempotency_key=f"cmt_{uuid.uuid4().hex}",
            uploaded_by=AUTHOR.user_id,
        ),
    )
    await document_repo.set_status(session, tenant_id, doc.id, DocumentStatus.READY)
    text = "Payment is due within thirty days of invoice."
    chunk = ChunkData(
        content=text,
        section_number="2",
        heading="Payment",
        page=1,
        cross_refs=[],
        token_count=len(text.split()),
    )
    embeddings = await embed_texts([text])
    await chunk_repo.upsert_chunks(
        session,
        tenant_id,
        doc.id,
        [chunk],
        embeddings,
        settings.embedding_model,
        settings.embedding_model_version,
    )
    await session.commit()
    result = await session.execute(
        select(Chunk).where(col(Chunk.document_id) == doc.id)
    )
    stored = result.scalars().one()
    return doc.id, stored.id


async def test_create_and_list_comment(tenant_session: AsyncSession) -> None:
    doc_id, chunk_id = await _seed_chunk(tenant_session, TENANT.tenant_id)
    async with _client(tenant_session, user=AUTHOR, role=OrgRole.EDITOR) as client:
        created = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments",
            json={"body": "Check the payment window."},
        )
        assert created.status_code == 201, created.text
        listed = await client.get(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments"
        )
    assert listed.status_code == 200, listed.text
    bodies = [item["body"] for item in listed.json()["items"]]
    assert "Check the payment window." in bodies


async def test_non_author_cannot_delete(tenant_session: AsyncSession) -> None:
    doc_id, chunk_id = await _seed_chunk(tenant_session, TENANT.tenant_id)
    async with _client(tenant_session, user=AUTHOR, role=OrgRole.EDITOR) as author:
        created = await author.post(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments",
            json={"body": "Author note."},
        )
    comment_id = created.json()["id"]
    async with _client(tenant_session, user=OTHER_USER, role=OrgRole.EDITOR) as other:
        denied = await other.delete(f"/api/v1/comments/{comment_id}")
    assert denied.status_code == 403, denied.text


async def test_admin_can_delete(tenant_session: AsyncSession) -> None:
    doc_id, chunk_id = await _seed_chunk(tenant_session, TENANT.tenant_id)
    async with _client(tenant_session, user=AUTHOR, role=OrgRole.EDITOR) as author:
        created = await author.post(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments",
            json={"body": "Remove me."},
        )
    comment_id = created.json()["id"]
    async with _client(tenant_session, user=OTHER_USER, role=OrgRole.ADMIN) as admin:
        deleted = await admin.delete(f"/api/v1/comments/{comment_id}")
    assert deleted.status_code == 204, deleted.text


async def test_tenant_cannot_read_other_tenant_comments(
    tenant_session: AsyncSession,
    db_engine,
) -> None:
    doc_id, chunk_id = await _seed_chunk(tenant_session, TENANT.tenant_id)
    async with _client(tenant_session, user=AUTHOR, role=OrgRole.EDITOR) as author:
        created = await author.post(
            f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments",
            json={"body": "Private note."},
        )
    assert created.status_code == 201, created.text

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as other_session:
        await set_tenant_context(other_session, OTHER_TENANT.tenant_id)
        async with _client(
            other_session,
            user=OTHER_USER,
            role=OrgRole.ADMIN,
            tenant=OTHER_TENANT,
        ) as outsider:
            resp = await outsider.get(
                f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/comments"
            )
    assert resp.status_code == 404, resp.text
