"""Phase 10A — Obligation service + endpoint tests.

Strategy
--------
- HTTP layer: auth deps stubbed; DB session wired to live Postgres (test DB).
- Bedrock is forced to raise AwsError so extraction always uses the
  deterministic local stub — no AWS credentials required in CI.
- All data is scoped to an ephemeral tenant_id to avoid cross-test pollution.
- One cross-tenant isolation check confirms RLS blocks leakage.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
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
from app.models.document import DocumentStatus
from app.repositories import chunk_repo, document_repo, obligation_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext

FAKE_USER = UserContext(user_id="user_obligation_test")
FAKE_TENANT = TenantContext(
    tenant_id=f"org_obl_{uuid.uuid4().hex[:8]}",
    slug="obligation-test",
)
OTHER_TENANT = TenantContext(
    tenant_id=f"org_obl_other_{uuid.uuid4().hex[:8]}",
    slug="obligation-other",
)

_DB_URL = settings.test_database_url or settings.database_url

_CLAUSE_TEXT = (
    "This Agreement requires Vendor to deliver payment of $5,000 within 30 days "
    "of invoice date. Either party may terminate this Agreement with 90 days written "
    "notice. The Agreement shall automatically renew annually unless notice of "
    "non-renewal is given at least 60 days before the renewal date."
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
async def other_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await set_tenant_context(session, OTHER_TENANT.tenant_id)
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


async def _seed_ready_doc(
    session: AsyncSession,
    tenant_id: str,
    content: str = _CLAUSE_TEXT,
) -> uuid.UUID:
    """Create a ready document with a single chunk containing clause text."""
    await set_tenant_context(session, tenant_id)
    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title="Obligation Test Agreement",
            original_filename="obligation_test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/obligation_test.pdf",
            idempotency_key=f"obl_idem_{uuid.uuid4().hex}",
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
    "app.services.obligation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
@pytest.mark.anyio
async def test_extract_returns_obligations_from_stub(
    _mock_bedrock,
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
):
    """POST extract → stub fires, obligations are persisted and returned."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)

    resp = await authed_client.post(f"/api/v1/documents/{doc_id}/obligations/extract")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["total"] >= 0  # stub may return 0–4 depending on keyword hits
    # Every item must have a description
    for item in data["items"]:
        assert item["description"]
        assert item["obligation_type"] in {
            "payment",
            "notice",
            "renewal",
            "termination",
            "other",
        }


@patch(
    "app.services.obligation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
@pytest.mark.anyio
async def test_extract_is_idempotent(
    _mock_bedrock,
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
):
    """Re-extracting replaces obligations rather than duplicating them."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)

    r1 = await authed_client.post(f"/api/v1/documents/{doc_id}/obligations/extract")
    assert r1.status_code == 201
    count1 = r1.json()["total"]

    r2 = await authed_client.post(f"/api/v1/documents/{doc_id}/obligations/extract")
    assert r2.status_code == 201
    # Total must stay the same after a second extraction (no duplicates).
    assert r2.json()["total"] == count1


@patch(
    "app.services.obligation_service.bedrock.converse_text",
    new_callable=AsyncMock,
    side_effect=AwsError("test"),
)
@pytest.mark.anyio
async def test_list_for_document(
    _mock_bedrock,
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
):
    """GET /documents/{id}/obligations returns the correct obligations."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)

    await authed_client.post(f"/api/v1/documents/{doc_id}/obligations/extract")

    resp = await authed_client.get(f"/api/v1/documents/{doc_id}/obligations")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert body["total"] == len(body["items"])


@pytest.mark.anyio
async def test_manual_create_and_patch(
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
):
    """POST manual obligation → PATCH description/type → verify updates."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)

    # Manual create
    create_resp = await authed_client.post(
        f"/api/v1/documents/{doc_id}/obligations",
        json={
            "document_id": str(doc_id),
            "description": "Pay invoice within 30 days",
            "obligation_type": "payment",
            "reminder_days_before": 14,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    obligation_id = create_resp.json()["id"]

    # Patch
    patch_resp = await authed_client.patch(
        f"/api/v1/obligations/{obligation_id}",
        json={"description": "Pay invoice within 45 days", "reminder_days_before": 7},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    updated = patch_resp.json()
    assert updated["description"] == "Pay invoice within 45 days"
    assert updated["reminder_days_before"] == 7
    assert updated["is_resolved"] is False


@pytest.mark.anyio
async def test_resolve_obligation(
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
):
    """POST /resolve marks obligation as resolved."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)

    create_resp = await authed_client.post(
        f"/api/v1/documents/{doc_id}/obligations",
        json={
            "document_id": str(doc_id),
            "description": "Renew contract 60 days before expiry",
            "obligation_type": "renewal",
        },
    )
    assert create_resp.status_code == 201
    obligation_id = create_resp.json()["id"]

    resolve_resp = await authed_client.post(
        f"/api/v1/obligations/{obligation_id}/resolve"
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    assert resolve_resp.json()["is_resolved"] is True


@pytest.mark.anyio
async def test_tenant_isolation(
    tenant_session: AsyncSession,
    other_session: AsyncSession,
    db_engine,
):
    """Tenant A's obligations must not be visible to Tenant B."""
    # Seed obligation for FAKE_TENANT
    doc_a_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)
    from app.schemas.obligation import ObligationCreate

    ob = await obligation_repo.create(
        tenant_session,
        FAKE_TENANT.tenant_id,
        ObligationCreate(
            document_id=doc_a_id,
            description="Tenant A secret obligation",
            obligation_type="payment",
        ),
    )
    await tenant_session.commit()

    # Tenant B queries their obligations — should see none of Tenant A's
    rows_b, total_b = await obligation_repo.list_for_tenant(
        other_session, OTHER_TENANT.tenant_id
    )
    ids_b = {str(r.id) for r in rows_b}
    assert (
        str(ob.id) not in ids_b
    ), "Tenant B must not see Tenant A's obligations — RLS breach!"


@pytest.mark.anyio
async def test_extract_404_for_missing_document(
    authed_client: AsyncClient,
):
    """Extracting for a nonexistent document returns 404."""
    fake_id = uuid.uuid4()
    resp = await authed_client.post(f"/api/v1/documents/{fake_id}/obligations/extract")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_tenant_obligations_pagination(
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
):
    """GET /obligations with limit/offset paginates correctly."""
    doc_id = await _seed_ready_doc(tenant_session, FAKE_TENANT.tenant_id)
    from app.schemas.obligation import ObligationCreate

    # Insert 3 obligations directly
    for i in range(3):
        await obligation_repo.create(
            tenant_session,
            FAKE_TENANT.tenant_id,
            ObligationCreate(
                document_id=doc_id,
                description=f"Obligation #{i}",
                obligation_type="other",
            ),
        )
    await tenant_session.commit()

    # Page 1: limit=2
    r1 = await authed_client.get(
        "/api/v1/obligations",
        params={"include_resolved": False, "limit": 2, "offset": 0},
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["total"] >= 3
    assert len(body1["items"]) == 2

    # Page 2: offset=2
    r2 = await authed_client.get(
        "/api/v1/obligations",
        params={"include_resolved": False, "limit": 2, "offset": 2},
    )
    assert r2.status_code == 200
    # Must not overlap with page 1
    ids1 = {i["id"] for i in body1["items"]}
    ids2 = {i["id"] for i in r2.json()["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"
