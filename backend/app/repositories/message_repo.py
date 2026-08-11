"""Message repository — tenant-scoped."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message, MessageRole


async def create_user_message(
    session: AsyncSession,
    tenant_id: str,
    *,
    conversation_id: uuid.UUID,
    content: str,
) -> Message:
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=content,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return message


async def create_assistant_message(
    session: AsyncSession,
    tenant_id: str,
    *,
    conversation_id: uuid.UUID,
    content: str,
    citations: list[Any],
    latency_ms: int | None = None,
) -> Message:
    """Persist an assistant turn.

    ``citations`` is a list of objects with ``document_id``, ``chunk_id``,
    ``section``, and ``quote`` attributes (e.g. generation Citation dataclasses).
    """
    citations_json = (
        json.dumps(
            [
                {
                    "document_id": str(c.document_id),
                    "chunk_id": str(c.chunk_id),
                    "section": c.section,
                    "quote": c.quote,
                }
                for c in citations
            ]
        )
        if citations
        else None
    )
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content=content,
        citations=citations_json,
        latency_ms=latency_ms,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return message
