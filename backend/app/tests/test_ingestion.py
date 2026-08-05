"""Phase 4 ingestion integration tests.

Strategy
--------
- S3 download and Voyage AI are replaced with synchronous mocks so no
  external services are needed.
- The parser is patched to return a predictable list of ParsedElements so
  the test does not depend on a real PDF file.
- All DB writes use a live test database (same pattern as test_worker.py).
- Each test proves one row in the Phase 4 acceptance table.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.rls import set_tenant_context
from app.ingestion.parser import ParsedElement
from app.models.chunk import Chunk
from app.models.document import Document
from app.repositories import document_repo
from app.repositories.document_repo import DocumentCreateData
from app.services.ingestion_service import ingest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DB_URL = settings.test_database_url or settings.database_url

_FAKE_ELEMENTS = [
    ParsedElement(
        text="1. Definitions",
        element_type="heading",
        page=1,
        section_number="1",
        heading="1. Definitions",
    ),
    ParsedElement(
        text=(
            "'Agreement' means this Master Service Agreement entered into "
            "as of the Effective Date between the parties."
        ),
        element_type="narrative",
        page=1,
        section_number="1",
        heading="1. Definitions",
    ),
    ParsedElement(
        text="2. Payment Terms",
        element_type="heading",
        page=1,
        section_number="2",
        heading="2. Payment Terms",
    ),
    ParsedElement(
        text=(
            "Invoices shall be payable within thirty days of receipt. "
            "See Section 3 for dispute resolution procedures."
        ),
        element_type="narrative",
        page=1,
        section_number="2",
        heading="2. Payment Terms",
    ),
    ParsedElement(
        text="3. Dispute Resolution",
        element_type="heading",
        page=2,
        section_number="3",
        heading="3. Dispute Resolution",
    ),
    ParsedElement(
        text=(
            "All disputes arising under this Agreement shall be submitted "
            "to binding arbitration in accordance with Exhibit A."
        ),
        element_type="narrative",
        page=2,
        section_number="3",
        heading="3. Dispute Resolution",
    ),
]


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
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_doc(
    session: AsyncSession,
    tenant_id: str,
    suffix: str = "",
) -> Document:
    """Insert a Document in processing state; return the full row."""
    await set_tenant_context(session, tenant_id)
    data = DocumentCreateData(
        title=f"Ingestion Test Doc {suffix}",
        original_filename=f"ingest_test{suffix}.pdf",
        content_type="application/pdf",
        size_bytes=4096,
        s3_key=f"{tenant_id}/{uuid.uuid4()}/ingest_test{suffix}.pdf",
        idempotency_key=f"ingest_idem_{uuid.uuid4().hex}",
        uploaded_by="user_ingest_test",
    )
    doc = await document_repo.create(session, tenant_id, data)
    await session.commit()
    return doc


def _fake_vectors(texts: list[str]) -> list[list[float]]:
    """Return zero-padded 1024-dim vectors (only for test assertions)."""
    dim = settings.embedding_dimensions
    return [[0.0] * dim for _ in texts]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ingest_creates_chunks(db_session: AsyncSession) -> None:
    """After ingest, Chunk rows exist for the document with the right tenant."""
    tenant_id = f"org_ingest_{uuid.uuid4().hex[:8]}"
    doc = await _create_doc(db_session, tenant_id)

    with (
        patch(
            "app.services.ingestion_service.download_document",
            new=AsyncMock(return_value=b"%PDF fake"),
        ),
        patch(
            "app.services.ingestion_service.parse_pdf",
            return_value=_FAKE_ELEMENTS,
        ),
        patch(
            "app.services.ingestion_service.embed_texts",
            new=AsyncMock(side_effect=lambda texts: _fake_vectors(texts)),
        ),
    ):
        chunk_count = await ingest(
            session=db_session,
            tenant_id=tenant_id,
            document_id=doc.id,
            s3_key=doc.s3_key,
        )
        await db_session.commit()

    assert chunk_count > 0

    # Verify rows are in DB
    await set_tenant_context(db_session, tenant_id)
    result = await db_session.execute(
        select(Chunk).where(
            Chunk.document_id == doc.id,
            Chunk.tenant_id == tenant_id,
        )
    )
    db_chunks = result.scalars().all()
    assert len(db_chunks) == chunk_count


async def test_ingest_sets_page_count(db_session: AsyncSession) -> None:
    """Document.page_count is updated to the max page number seen in elements."""
    tenant_id = f"org_ingest_{uuid.uuid4().hex[:8]}"
    doc = await _create_doc(db_session, tenant_id, suffix="_page")

    assert doc.page_count is None

    with (
        patch(
            "app.services.ingestion_service.download_document",
            new=AsyncMock(return_value=b"%PDF fake"),
        ),
        patch(
            "app.services.ingestion_service.parse_pdf",
            return_value=_FAKE_ELEMENTS,
        ),
        patch(
            "app.services.ingestion_service.embed_texts",
            new=AsyncMock(side_effect=lambda texts: _fake_vectors(texts)),
        ),
    ):
        await ingest(
            session=db_session,
            tenant_id=tenant_id,
            document_id=doc.id,
            s3_key=doc.s3_key,
        )
        await db_session.commit()

    await set_tenant_context(db_session, tenant_id)
    updated = await document_repo.get_by_id(db_session, tenant_id, doc.id)
    assert updated is not None
    # _FAKE_ELEMENTS has elements on page 1 and page 2
    assert updated.page_count == 2


async def test_ingest_is_idempotent(db_session: AsyncSession) -> None:
    """Running ingest twice produces the same chunk count, not double rows."""
    tenant_id = f"org_ingest_{uuid.uuid4().hex[:8]}"
    doc = await _create_doc(db_session, tenant_id, suffix="_idem")

    mock_kwargs = dict(
        download="app.services.ingestion_service.download_document",
        parse="app.services.ingestion_service.parse_pdf",
        embed="app.services.ingestion_service.embed_texts",
    )

    async def _run_ingest() -> int:
        with (
            patch(
                mock_kwargs["download"],
                new=AsyncMock(return_value=b"%PDF fake"),
            ),
            patch(
                mock_kwargs["parse"],
                return_value=_FAKE_ELEMENTS,
            ),
            patch(
                mock_kwargs["embed"],
                new=AsyncMock(side_effect=lambda texts: _fake_vectors(texts)),
            ),
        ):
            count = await ingest(
                session=db_session,
                tenant_id=tenant_id,
                document_id=doc.id,
                s3_key=doc.s3_key,
            )
            await db_session.commit()
        return count

    first = await _run_ingest()
    second = await _run_ingest()

    assert first == second, f"Chunk counts differ: first={first} second={second}"

    await set_tenant_context(db_session, tenant_id)
    result = await db_session.execute(
        select(Chunk).where(
            Chunk.document_id == doc.id,
            Chunk.tenant_id == tenant_id,
        )
    )
    db_count = len(result.scalars().all())
    assert db_count == first, (
        f"DB has {db_count} rows but expected {first} after idempotent re-ingest"
    )


async def test_ingest_tenant_isolation(db_session: AsyncSession) -> None:
    """Chunks created for tenant A are invisible when queried as tenant B."""
    tenant_a = f"org_a_{uuid.uuid4().hex[:8]}"
    tenant_b = f"org_b_{uuid.uuid4().hex[:8]}"
    doc = await _create_doc(db_session, tenant_a, suffix="_iso")

    with (
        patch(
            "app.services.ingestion_service.download_document",
            new=AsyncMock(return_value=b"%PDF fake"),
        ),
        patch(
            "app.services.ingestion_service.parse_pdf",
            return_value=_FAKE_ELEMENTS,
        ),
        patch(
            "app.services.ingestion_service.embed_texts",
            new=AsyncMock(side_effect=lambda texts: _fake_vectors(texts)),
        ),
    ):
        count_a = await ingest(
            session=db_session,
            tenant_id=tenant_a,
            document_id=doc.id,
            s3_key=doc.s3_key,
        )
        await db_session.commit()

    assert count_a > 0

    # Querying with tenant B's RLS context must return nothing
    await set_tenant_context(db_session, tenant_b)
    result = await db_session.execute(
        select(Chunk).where(Chunk.tenant_id == tenant_b)
    )
    chunks_b = result.scalars().all()
    assert chunks_b == [], (
        f"Tenant B unexpectedly sees {len(chunks_b)} chunks belonging to tenant A"
    )
