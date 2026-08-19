"""Phase 7 — Structured clause extraction tests.

Strategy
--------
- HTTP layer: auth deps stubbed; DB session wired to live Postgres (test DB).
- Retrieval uses real HNSW + GIN indexes with local embedder vectors.
- Bedrock is forced to raise AwsError so extraction always uses the
  deterministic local stub (no AWS credentials required in CI).
- Cache behaviour verified by inspecting extracted_at timestamps.
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
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.repositories import chunk_repo, document_repo, summary_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext

FAKE_USER = UserContext(user_id="user_extraction_test")
FAKE_TENANT = TenantContext(
    tenant_id=f"org_extract_{uuid.uuid4().hex[:8]}",
    slug="extraction-test",
)
OTHER_TENANT = TenantContext(
    tenant_id=f"org_other_{uuid.uuid4().hex[:8]}",
    slug="other-tenant",
)

_DB_URL = settings.test_database_url or settings.database_url

_CLAUSE_TEXT = (
    "This Agreement is entered into as of January 1, 2025, between Acme Corp "
    "(the 'Company') and Globex Inc (the 'Vendor'). The initial term is two years. "
    "Payment is due within 30 days of invoice. Either party may terminate with "
    "90 days written notice. Liability is capped at the fees paid in the prior "
    "12 months. This Agreement is governed by the laws of the State of Delaware."
)


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


async def _seed_ready_doc(
    session: AsyncSession,
    tenant_id: str,
    content: str = _CLAUSE_TEXT,
) -> uuid.UUID:
    """Create a ready document with a single chunk containing all clause text."""
    await set_tenant_context(session, tenant_id)
    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title="Test Agreement",
            original_filename="agreement.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/agreement.pdf",
            idempotency_key=f"extract_idem_{uuid.uuid4().hex}",
            uploaded_by=FAKE_USER.user_id,
        ),
    )
    await document_repo.set_status(session, tenant_id, doc.id, DocumentStatus.READY)

    chunk = ChunkData(
        content=content,
        section_number="1",
        heading="Agreement Terms",
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
        embedding_model=settings.embedding_model,
        embedding_model_version=settings.embedding_model_version,
    )
    await session.commit()
    return doc.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch(
    "app.services.extraction_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_extraction_returns_all_fields(
    _mock_bedrock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """All 7 fields are present in the response (local stub fills them)."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)
    resp = await authed_client.get(f"/api/v1/documents/{doc_id}/summary")
    assert resp.status_code == 200
    body = resp.json()
    for field in (
        "parties",
        "effective_date",
        "term_length",
        "payment_terms",
        "termination_rights",
        "liability_caps",
        "governing_law",
    ):
        assert field in body, f"Missing field: {field}"
        # Local stub sets value = "See document" for every field
        assert body[field]["value"] is not None


@patch(
    "app.services.extraction_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_extraction_citations_are_valid(
    _mock_bedrock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """Every chunk_id in the card belongs to the document's own chunks."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)
    resp = await authed_client.get(f"/api/v1/documents/{doc_id}/summary")
    assert resp.status_code == 200
    body = resp.json()

    # Collect all chunk IDs for the document from the DB
    result = await tenant_session.execute(
        select(Chunk.id).where(
            Chunk.tenant_id == FAKE_TENANT.tenant_id,
            Chunk.document_id == doc_id,
        )
    )
    valid_chunk_ids = {str(row[0]) for row in result}

    for field in ("parties", "effective_date", "term_length"):
        entry = body.get(field) or {}
        cid = entry.get("chunk_id")
        if cid:
            assert cid in valid_chunk_ids, f"Fabricated chunk_id in {field}: {cid}"


@patch(
    "app.services.extraction_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_extraction_cached(
    _mock_bedrock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """Second call within TTL returns the same extracted_at (no re-extraction)."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)
    r1 = await authed_client.get(f"/api/v1/documents/{doc_id}/summary")
    r2 = await authed_client.get(f"/api/v1/documents/{doc_id}/summary")
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["extracted_at"] == r2.json()["extracted_at"]


@patch(
    "app.services.extraction_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_extraction_requires_ready_document(
    _mock_bedrock, authed_client: AsyncClient, tenant_session: AsyncSession
):
    """Returns 422 when the document is still processing."""
    await set_tenant_context(tenant_session, FAKE_TENANT.tenant_id)
    doc = await document_repo.create(
        tenant_session,
        FAKE_TENANT.tenant_id,
        DocumentCreateData(
            title="Processing Doc",
            original_filename="proc.pdf",
            content_type="application/pdf",
            size_bytes=512,
            s3_key=f"{FAKE_TENANT.tenant_id}/{uuid.uuid4()}/proc.pdf",
            idempotency_key=f"proc_idem_{uuid.uuid4().hex}",
            uploaded_by=FAKE_USER.user_id,
        ),
    )
    await tenant_session.commit()
    resp = await authed_client.get(f"/api/v1/documents/{doc.id}/summary")
    assert resp.status_code == 422


async def test_extraction_requires_auth(
    unauthed_client: AsyncClient,
):
    """Unauthenticated request returns 401."""
    resp = await unauthed_client.get(f"/api/v1/documents/{uuid.uuid4()}/summary")
    assert resp.status_code == 401


@patch(
    "app.services.extraction_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
async def test_extraction_tenant_isolation(
    _mock_bedrock, tenant_session: AsyncSession, db_engine
):
    """Tenant A cannot read Tenant B's summary card."""
    # Seed a doc+summary under FAKE_TENANT
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)

    # Trigger extraction for FAKE_TENANT to populate the cache
    from app.services.extraction_service import get_or_extract
    card = await get_or_extract(tenant_session, FAKE_TENANT.tenant_id, doc_id)
    assert card is not None

    # Now try to read it as OTHER_TENANT via the repo (bypassing HTTP auth)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as other_session:
        await set_tenant_context(other_session, OTHER_TENANT.tenant_id)
        other_card = await summary_repo.get_for_document(
            other_session, OTHER_TENANT.tenant_id, doc_id
        )
        assert other_card is None, "Tenant B should not see Tenant A's summary"
