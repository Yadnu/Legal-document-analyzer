"""Q&A orchestration: retrieve → generate → persist conversation turns."""

from __future__ import annotations

import time
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.document import DocumentStatus
from app.repositories import conversation_repo, document_repo, message_repo
from app.schemas.query import CitationOut, QueryResponse
from app.services import generation_service, retrieval_service

log = structlog.get_logger(__name__)


async def ask(
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    question: str,
    *,
    document_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> QueryResponse:
    """Answer ``question`` with grounded citations (or not-found)."""

    question = question.strip()

    if not question:

        raise ValidationError("question must not be empty.")

    if document_id is not None:

        doc = await document_repo.get_by_id(session, tenant_id, document_id)

        if doc is None:

            raise NotFoundError(f"Document {document_id} not found.")

        if doc.status != DocumentStatus.READY:

            raise ValidationError(
                f"Document is not ready for Q&A (status={doc.status})."
            )

    conversation = await _resolve_conversation(
        session,
        tenant_id,
        user_id,
        question=question,
        document_id=document_id,
        conversation_id=conversation_id,
    )

    await message_repo.create_user_message(
        session,
        tenant_id,
        conversation_id=conversation.id,
        content=question,
    )

    started = time.perf_counter()

    chunks = await retrieval_service.retrieve(
        session,
        tenant_id,
        question,
        document_id=document_id or conversation.document_id,
    )

    result = await generation_service.generate_answer(question, chunks)

    latency_ms = int((time.perf_counter() - started) * 1000)

    assistant = await message_repo.create_assistant_message(
        session,
        tenant_id,
        conversation_id=conversation.id,
        content=result.answer,
        citations=result.citations,
        latency_ms=latency_ms,
    )

    await session.commit()

    log.info(
        "qa_ask_ok",
        tenant_id=tenant_id,
        conversation_id=str(conversation.id),
        not_found=result.not_found,
        citation_count=len(result.citations),
        latency_ms=latency_ms,
    )

    return QueryResponse(
        conversation_id=conversation.id,
        message_id=assistant.id,
        answer=result.answer,
        not_found=result.not_found,
        citations=[
            CitationOut(
                document_id=c.document_id,
                chunk_id=c.chunk_id,
                section=c.section,
                quote=c.quote,
            )
            for c in result.citations
        ],
    )


async def _resolve_conversation(
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    *,
    question: str,
    document_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
):

    if conversation_id is not None:

        existing = await conversation_repo.get_by_id(
            session, tenant_id, conversation_id
        )

        if existing is None:

            raise NotFoundError(f"Conversation {conversation_id} not found.")

        return existing

    title = question[:80] if question else None

    return await conversation_repo.create(
        session,
        tenant_id,
        user_id=user_id,
        document_id=document_id,
        title=title,
    )
