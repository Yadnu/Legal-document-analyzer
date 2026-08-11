"""Conversation repository — tenant-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.conversation import Conversation


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
