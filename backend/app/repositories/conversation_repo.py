"""Conversation repository — tenant-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.conversation import Conversation
from app.models.message import Message


async def create(
    session: AsyncSession,
    tenant_id: str,
    *,
    user_id: str,
    document_id: uuid.UUID | None = None,
    title: str | None = None,
) -> Conversation:

    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        document_id=document_id,
        title=title,
    )

    session.add(conversation)

    await session.flush()

    await session.refresh(conversation)

    return conversation


async def list_workspace_conversations(
    session: AsyncSession,
    tenant_id: str,
    *,
    limit: int = 20,
) -> list[tuple[Conversation, int]]:
    """Return workspace conversations (document_id IS NULL) newest-first.

    Returns a list of (Conversation, message_count) tuples.
    """
    msg_count = (
        select(func.count(Message.id))
        .where(
            col(Message.conversation_id) == Conversation.id,
            col(Message.tenant_id) == tenant_id,
        )
        .correlate(Conversation)
        .scalar_subquery()
    )
    result = await session.execute(
        select(Conversation, msg_count.label("message_count"))
        .where(
            col(Conversation.tenant_id) == tenant_id,
            col(Conversation.document_id).is_(None),
        )
        .order_by(col(Conversation.created_at).desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_by_id(
    session: AsyncSession,
    tenant_id: str,
    conversation_id: uuid.UUID,
) -> Conversation | None:

    result = await session.execute(
        select(Conversation).where(
            col(Conversation.id) == conversation_id,
            col(Conversation.tenant_id) == tenant_id,
        )
    )

    return result.scalar_one_or_none()
