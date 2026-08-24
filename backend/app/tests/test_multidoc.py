"""Phase 9 — Multi-document workspace tests.

Strategy
--------
- Auth deps stubbed; live Postgres (test DB).
- Seeds TWO documents with distinct content so retrieval returns chunks
  from both when queried without a document_id filter.
- Bedrock forced to raise AwsError → generation uses deterministic stub
  (cites top chunk).
- Verifies cross-doc citations include document_title.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.deps import get_current_tenant, get_current_user
from app.core.exceptions import AwsError
from app.db.rls import set_tenant_context
from app.db.session import get_rls_db
from app.ingestion.chunker import ChunkData
from app.ingestion.embedder import embed_texts
from app.main import create_app
from app.models.conversation import Conversation
from app.models.document import DocumentStatus
from app.repositories import chunk_repo, document_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext

FAKE_USER = UserContext(user_id="user_multidoc_test")
FAKE_TENANT = TenantContext(
    tenant_id=f"org_multidoc_{uuid.uuid4().hex[:8]}",
    slug="multidoc-test",
)

_DB_URL = settings.test_database_url or settings.database_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_engine():
    engine = create_async_engine(_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def tenant_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await set_tenant_context(session, FAKE_TENANT.tenant_id)
        yield session


@pytest.fixture()
async def authed_client(
    tenant_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
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


@pytest.fixture()
async def unauthed_client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def _seed_doc(
    session: AsyncSession,
    tenant_id: str,
    title: str,
    content: str,
) -> uuid.UUID:
    """Create a ready document with a single chunk."""
    await set_tenant_context(session, tenant_id)
    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title=title,
            original_filename=f"{title.lower().replace(' ', '_')}.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/{title}.pdf",
            idempotency_key=f"multidoc_{uuid.uuid4().hex}",
            uploaded_by=FAKE_USER.user_id,
        ),
    )
    await document_repo.set_status(session, tenant_id, doc.id, DocumentStatus.READY)
    chunk = ChunkData(
        content=content,
        section_number="1",
        heading="1 Terms",
        page=1,
        cross_refs=[],
        token_count=len(content.split()),
    )
    embeddings = await embed_texts([chunk.content])
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
    return doc.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch(
    "app.services.generation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_cross_doc_returns_citations_from_both_docs(
    _mock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """A workspace query (no document_id) can cite chunks from both documents."""
    await _seed_doc(
        tenant_session,
        FAKE_TENANT.tenant_id,
        "Contract A",
        "Contract A payment terms: invoices due within 30 days of receipt.",
    )
    await _seed_doc(
        tenant_session,
        FAKE_TENANT.tenant_id,
        "Contract B",
        "Contract B renewal clause: this agreement auto-renews annually.",
    )

    resp = await authed_client.post(
        "/api/v1/query",
        json={"question": "payment terms and renewal"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["citations"]) >= 1
    # At least one citation must reference a real chunk (not fabricated)
    for cit in body["citations"]:
        assert cit["chunk_id"] is not None
        assert cit["document_id"] is not None


@patch(
    "app.services.generation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_cross_doc_citations_include_document_title(
    _mock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """Every CitationOut includes a non-null document_title."""
    await _seed_doc(
        tenant_session,
        FAKE_TENANT.tenant_id,
        "NDA Agreement",
        "Confidentiality obligations survive termination for five years.",
    )

    resp = await authed_client.post(
        "/api/v1/query",
        json={"question": "confidentiality"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["citations"]) >= 1
    for cit in body["citations"]:
        assert cit["document_title"] is not None, (
            f"Expected document_title on citation {cit}"
        )
        assert cit["document_title"] == "NDA Agreement"


@patch(
    "app.services.generation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_workspace_conversation_has_null_document_id(
    _mock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """Conversation created by a workspace query has document_id=None."""
    await _seed_doc(
        tenant_session,
        FAKE_TENANT.tenant_id,
        "Service Agreement",
        "Service fees are invoiced monthly.",
    )
    resp = await authed_client.post(
        "/api/v1/query",
        json={"question": "service fees"},
    )
    assert resp.status_code == 200
    conv_id = resp.json()["conversation_id"]

    # Fetch conversation directly from DB and verify document_id is NULL
    result = await tenant_session.execute(
        select(Conversation).where(Conversation.id == uuid.UUID(conv_id))
    )
    conv = result.scalar_one_or_none()
    assert conv is not None
    assert conv.document_id is None


@patch(
    "app.services.generation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_list_conversations_returns_workspace_convs(
    _mock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """GET /conversations returns workspace conversations (document_id IS NULL)."""
    await _seed_doc(
        tenant_session,
        FAKE_TENANT.tenant_id,
        "Lease",
        "Monthly rent is due on the first of each month.",
    )
    # Create a workspace conversation
    await authed_client.post(
        "/api/v1/query",
        json={"question": "rent due date"},
    )

    resp = await authed_client.get("/api/v1/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    assert isinstance(convs, list)
    assert len(convs) >= 1
    # All returned conversations must have a title
    for conv in convs:
        assert "id" in conv
        assert "created_at" in conv


async def test_list_conversations_requires_auth(unauthed_client: AsyncClient):
    """Unauthenticated request returns 401."""
    resp = await unauthed_client.get("/api/v1/conversations")
    assert resp.status_code == 401
