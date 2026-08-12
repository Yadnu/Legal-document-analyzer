"""Phase 5 grounded Q&A tests.

Strategy

--------

- HTTP layer: auth deps stubbed; DB session wired like test_upload.py.

- Retrieval uses real Postgres dense/sparse indexes with local embedder vectors.

- Bedrock is forced to fail so generation uses the deterministic local stub.

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
from app.repositories import chunk_repo, document_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.auth import TenantContext, UserContext
from app.services.generation_service import NOT_FOUND_ANSWER

FAKE_USER = UserContext(user_id="user_query_test")

FAKE_TENANT = TenantContext(
    tenant_id=f"org_query_{uuid.uuid4().hex[:8]}",
    slug="query-test",
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


async def _seed_ready_document_with_chunks(
    session: AsyncSession,
    tenant_id: str,
    *,
    payment_text: str = (
        "Invoices shall be payable within thirty days of receipt "
        "under the payment terms of this Agreement."
    ),
) -> tuple[uuid.UUID, list[uuid.UUID]]:

    await set_tenant_context(session, tenant_id)

    doc = await document_repo.create(
        session,
        tenant_id,
        DocumentCreateData(
            title="MSA",
            original_filename="msa.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            s3_key=f"{tenant_id}/{uuid.uuid4()}/msa.pdf",
            idempotency_key=f"query_idem_{uuid.uuid4().hex}",
            uploaded_by=FAKE_USER.user_id,
        ),
    )

    await document_repo.set_status(session, tenant_id, doc.id, DocumentStatus.READY)

    chunks = [
        ChunkData(
            content="1. Definitions",
            section_number="1",
            heading="1. Definitions",
            page=1,
            cross_refs=[],
            token_count=2,
        ),
        ChunkData(
            content=payment_text,
            section_number="2",
            heading="2. Payment Terms",
            page=1,
            cross_refs=[],
            token_count=len(payment_text.split()),
        ),
    ]

    embeddings = await embed_texts([c.content for c in chunks])

    await chunk_repo.upsert_chunks(
        session,
        tenant_id,
        doc.id,
        chunks,
        embeddings,
        settings.embedding_model,
        settings.embedding_model_version,
    )

    await session.commit()

    ranked = await chunk_repo.dense_search(
        session,
        tenant_id,
        embeddings[0],
        top_k=10,
        embedding_model=settings.embedding_model,
        embedding_model_version=settings.embedding_model_version,
        document_id=doc.id,
    )

    return doc.id, [item.chunk.id for item in ranked]


async def test_query_returns_grounded_citation(
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
) -> None:

    doc_id, chunk_ids = await _seed_ready_document_with_chunks(
        tenant_session, FAKE_TENANT.tenant_id
    )

    with patch(
        "app.services.generation_service.bedrock.converse_text",
        new=AsyncMock(side_effect=AwsError("forced")),
    ):

        response = await authed_client.post(
            "/api/v1/query",
            json={
                "question": "What are the payment terms and thirty days deadline?",
                "document_id": str(doc_id),
            },
        )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["not_found"] is False

    assert body["citations"]

    cited_ids = {c["chunk_id"] for c in body["citations"]}

    assert cited_ids.issubset({str(cid) for cid in chunk_ids})

    assert all(c["document_id"] == str(doc_id) for c in body["citations"])


async def test_query_not_found(
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
) -> None:

    doc_id, _ = await _seed_ready_document_with_chunks(
        tenant_session, FAKE_TENANT.tenant_id
    )

    with (
        patch(
            "app.services.retrieval_service.retrieve",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.generation_service.bedrock.converse_text",
            new=AsyncMock(side_effect=AwsError("forced")),
        ),
    ):

        response = await authed_client.post(
            "/api/v1/query",
            json={
                "question": "What is the spaceship warranty period?",
                "document_id": str(doc_id),
            },
        )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["not_found"] is True

    assert body["answer"] == NOT_FOUND_ANSWER

    assert body["citations"] == []


async def test_query_requires_auth(unauthed_client: AsyncClient) -> None:

    response = await unauthed_client.post(
        "/api/v1/query",
        json={"question": "What is the term?"},
    )

    assert response.status_code == 401


async def test_query_tenant_isolation(
    authed_client: AsyncClient,
    tenant_session: AsyncSession,
    db_engine,
) -> None:

    other_tenant = f"org_other_{uuid.uuid4().hex[:8]}"

    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with factory() as other_session:

        other_doc_id, other_chunk_ids = await _seed_ready_document_with_chunks(
            other_session, other_tenant
        )

    with patch(
        "app.services.generation_service.bedrock.converse_text",
        new=AsyncMock(side_effect=AwsError("forced")),
    ):

        response = await authed_client.post(
            "/api/v1/query",
            json={"question": "What are the payment terms and thirty days?"},
        )

    assert response.status_code == 200, response.text

    body = response.json()

    cited = {c["chunk_id"] for c in body["citations"]}

    foreign = {str(cid) for cid in other_chunk_ids}

    assert cited.isdisjoint(foreign)

    assert all(c["document_id"] != str(other_doc_id) for c in body["citations"])
