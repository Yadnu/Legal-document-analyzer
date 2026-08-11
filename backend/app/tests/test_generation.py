"""Phase 5 generation unit tests — no DB, no network."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import AwsError
from app.models.chunk import Chunk
from app.services.generation_service import (
    NOT_FOUND_ANSWER,
    generate_answer,
)


def _chunk(content: str, *, section: str = "2") -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        tenant_id="org_gen_test",
        document_id=uuid.uuid4(),
        section_number=section,
        heading=f"Section {section}",
        page=1,
        content=content,
        token_count=len(content.split()),
        embedding_model="voyage-law-2",
        embedding_model_version="1",
    )


@pytest.mark.asyncio
async def test_generate_empty_chunks_is_not_found() -> None:
    result = await generate_answer("What is the term?", [])
    assert result.not_found is True
    assert result.answer == NOT_FOUND_ANSWER
    assert result.citations == []


@pytest.mark.asyncio
async def test_generate_parses_bedrock_json() -> None:
    chunk = _chunk("Payment is due within thirty days.")
    payload = (
        '{"answer":"Payment is due within thirty days.",'
        f'"citations":[{{"chunk_id":"{chunk.id}","quote":"within thirty days"}}]}}'
    )
    with patch(
        "app.services.generation_service.bedrock.converse_text",
        new=AsyncMock(return_value=payload),
    ):
        result = await generate_answer("When is payment due?", [chunk])
    assert result.not_found is False
    assert "thirty days" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == chunk.id


@pytest.mark.asyncio
async def test_generate_drops_fabricated_chunk_ids() -> None:
    chunk = _chunk("Governing law is Delaware.")
    fake_id = uuid.uuid4()
    payload = (
        '{"answer":"Governing law is Delaware.",'
        f'"citations":[{{"chunk_id":"{fake_id}","quote":"Delaware"}}]}}'
    )
    with patch(
        "app.services.generation_service.bedrock.converse_text",
        new=AsyncMock(return_value=payload),
    ):
        result = await generate_answer("What is governing law?", [chunk])
    assert result.not_found is True
    assert result.answer == NOT_FOUND_ANSWER


@pytest.mark.asyncio
async def test_generate_local_stub_on_bedrock_failure() -> None:
    chunk = _chunk("Invoices shall be payable within thirty days of receipt.")
    with patch(
        "app.services.generation_service.bedrock.converse_text",
        new=AsyncMock(side_effect=AwsError("down")),
    ):
        result = await generate_answer(
            "What are the payment thirty days terms?", [chunk]
        )
    assert result.not_found is False
    assert result.citations
    assert result.citations[0].chunk_id == chunk.id
