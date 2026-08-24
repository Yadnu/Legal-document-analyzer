"""Phase 8 — Cross-reference resolution tests.

Strategy
--------
- Auth deps stubbed; live Postgres (test DB).
- No Bedrock calls needed — resolution is pure metadata matching.
- Seeds documents with chunks that have known section_number / heading
  values and cross_refs JSON, then verifies resolution results.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import col

from app.core.config import settings
from app.core.deps import get_current_tenant, get_current_user
from app.core.exceptions import NotFoundError
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
from app.services.cross_ref_service import get_resolved_refs

FAKE_USER = UserContext(user_id="user_xref_test")
FAKE_TENANT = TenantContext(
    tenant_id=f"org_xref_{uuid.uuid4().hex[:8]}",
    slug="xref-test",
)
OTHER_TENANT = TenantContext(
    tenant_id=f"org_xref_other_{uuid.uuid4().hex[:8]}",
    slug="xref-other",
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


async def _seed_doc_with_chunks(
    session: AsyncSession,
    tenant_id: str,
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """Seed a ready document with four chunks; return doc_id + {label: chunk_id}."""
    await set_tenant_context(session, tenant_id)
    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title="Cross-Ref Test Contract",
            original_filename="contract.pdf",
            content_type="application/pdf",
            size_bytes=2048,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/contract.pdf",
            idempotency_key=f"xref_idem_{uuid.uuid4().hex}",
            uploaded_by=FAKE_USER.user_id,
        ),
    )
    await document_repo.set_status(session, tenant_id, doc.id, DocumentStatus.READY)

    chunks_data = [
        ChunkData(
            content=(
                "Section 2.1 — Definitions. "
                '"Agreement" has the meaning set forth herein.'
            ),
            section_number="2.1",
            heading="2.1 Definitions",
            page=1,
            cross_refs=[],
            token_count=12,
        ),
        ChunkData(
            content=(
                "Section 3 — Payment Terms. "
                "Invoices are due within 30 days per Section 2.1."
            ),
            section_number="3",
            heading="3 Payment Terms",
            page=2,
            cross_refs=["Section 2.1"],
            token_count=14,
        ),
        ChunkData(
            content=(
                "Exhibit B — Scope of Work. "
                "The vendor shall deliver the items listed herein."
            ),
            section_number=None,
            heading="Exhibit B",
            page=5,
            cross_refs=[],
            token_count=12,
        ),
        ChunkData(
            content="Termination rights are subject to Exhibit B and Section 2.1.",
            section_number="4",
            heading="4 Termination",
            page=3,
            cross_refs=["Exhibit B", "Section 2.1"],
            token_count=10,
        ),
    ]

    embeddings = await embed_texts([c.content for c in chunks_data])
    await chunk_repo.upsert_chunks(
        session,
        tenant_id,
        doc.id,
        chunks_data,
        embeddings,
        embedding_model=settings.embedding_model,
        embedding_model_version=settings.embedding_model_version,
    )
    await session.commit()

    # Retrieve inserted chunks to get their IDs
    result = await session.execute(
        select(Chunk).where(
            col(Chunk.tenant_id) == tenant_id,
            col(Chunk.document_id) == doc.id,
        )
    )
    db_chunks = result.scalars().all()
    chunk_ids: dict[str, uuid.UUID] = {}
    for c in db_chunks:
        if c.section_number == "3":
            chunk_ids["payment"] = c.id
        elif c.section_number == "4":
            chunk_ids["termination"] = c.id
        elif c.section_number == "2.1":
            chunk_ids["definitions"] = c.id
        elif c.heading == "Exhibit B":
            chunk_ids["exhibit_b"] = c.id

    return doc.id, chunk_ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_resolve_exact_section(
    authed_client: AsyncClient, tenant_session: AsyncSession
):
    """'Section 2.1' resolves to the chunk with section_number='2.1'."""
    doc_id, ids = await _seed_doc_with_chunks(tenant_session, FAKE_TENANT.tenant_id)
    chunk_id = ids["payment"]  # has cross_refs=["Section 2.1"]

    resp = await authed_client.get(f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/refs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunk_id"] == str(chunk_id)
    assert len(body["refs"]) == 1
    ref = body["refs"][0]
    assert ref["raw"] == "Section 2.1"
    assert ref["normalised"] == "2.1"
    assert ref["target_chunk_id"] == str(ids["definitions"])
    assert ref["target_section"] == "2.1"
    assert ref["target_content"] is not None


async def test_resolve_exhibit(
    authed_client: AsyncClient, tenant_session: AsyncSession
):
    """'Exhibit B' resolves to the chunk whose heading is 'Exhibit B'."""
    doc_id, ids = await _seed_doc_with_chunks(tenant_session, FAKE_TENANT.tenant_id)
    chunk_id = ids["termination"]  # has cross_refs=["Exhibit B", "Section 2.1"]

    resp = await authed_client.get(f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/refs")
    assert resp.status_code == 200
    body = resp.json()
    ref_raws = [r["raw"] for r in body["refs"]]
    assert "Exhibit B" in ref_raws

    exhibit_ref = next(r for r in body["refs"] if r["raw"] == "Exhibit B")
    assert exhibit_ref["target_chunk_id"] == str(ids["exhibit_b"])
    assert exhibit_ref["target_heading"] == "Exhibit B"


async def test_resolve_unresolvable(
    authed_client: AsyncClient, tenant_session: AsyncSession
):
    """'Section 99' returns an entry with target_chunk_id=null (not an error)."""
    doc_id, ids = await _seed_doc_with_chunks(tenant_session, FAKE_TENANT.tenant_id)

    # Manually insert a chunk with an unresolvable ref
    from sqlalchemy import text as sqla_text

    await set_tenant_context(tenant_session, FAKE_TENANT.tenant_id)
    bad_chunk_id = uuid.uuid4()
    # section_number="5" so it won't match "Section 99" in its own cross_ref
    embeddings = await embed_texts(["This clause references Section 99."])
    await tenant_session.execute(
        sqla_text("""
            INSERT INTO chunks (
                id, tenant_id, document_id, section_number, heading, page,
                cross_refs, content, token_count,
                embedding_model, embedding_model_version,
                embedding, search_vector, created_at
            ) VALUES (
                CAST(:id AS uuid), :tenant_id, CAST(:doc_id AS uuid),
                '5', NULL, 9,
                :cross_refs, :content, 6,
                :model, :version,
                CAST(:embedding AS vector),
                to_tsvector('english', :content),
                now()
            )
        """),
        {
            "id": str(bad_chunk_id),
            "tenant_id": FAKE_TENANT.tenant_id,
            "doc_id": str(doc_id),
            "cross_refs": json.dumps(["Section 99"]),
            "content": "This clause references Section 99.",
            "model": settings.embedding_model,
            "version": settings.embedding_model_version,
            "embedding": str(embeddings[0]),
        },
    )
    await tenant_session.commit()

    resp = await authed_client.get(
        f"/api/v1/documents/{doc_id}/chunks/{bad_chunk_id}/refs"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["refs"]) == 1
    assert body["refs"][0]["raw"] == "Section 99"
    assert body["refs"][0]["target_chunk_id"] is None


async def test_resolve_empty_refs(
    authed_client: AsyncClient, tenant_session: AsyncSession
):
    """Chunk with no cross-refs returns refs=[]."""
    doc_id, ids = await _seed_doc_with_chunks(tenant_session, FAKE_TENANT.tenant_id)
    chunk_id = ids["definitions"]  # cross_refs=[]

    resp = await authed_client.get(f"/api/v1/documents/{doc_id}/chunks/{chunk_id}/refs")
    assert resp.status_code == 200
    assert resp.json()["refs"] == []


async def test_resolve_requires_auth(unauthed_client: AsyncClient):
    """Unauthenticated request returns 401."""
    resp = await unauthed_client.get(
        f"/api/v1/documents/{uuid.uuid4()}/chunks/{uuid.uuid4()}/refs"
    )
    assert resp.status_code == 401


async def test_resolve_tenant_isolation(tenant_session: AsyncSession, db_engine):
    """Tenant B cannot resolve refs from Tenant A's document."""
    doc_id, ids = await _seed_doc_with_chunks(tenant_session, FAKE_TENANT.tenant_id)
    chunk_id = ids["payment"]

    # Try resolving as OTHER_TENANT via the service directly
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as other_session:
        await set_tenant_context(other_session, OTHER_TENANT.tenant_id)
        with pytest.raises(NotFoundError):
            await get_resolved_refs(
                other_session, OTHER_TENANT.tenant_id, doc_id, chunk_id
            )
