"""Clause comment repository.

All functions accept session + tenant_id so every query is scoped at the
application layer; RLS is a second line of defence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.clause_comment import ClauseComment


async def get(
    session: AsyncSession,
    tenant_id: str,
    comment_id: uuid.UUID,
) -> ClauseComment | None:
    """Return a single comment by ID, or None if it doesn't belong to tenant."""
    result = await session.execute(
        select(ClauseComment).where(
            col(ClauseComment.tenant_id) == tenant_id,
            col(ClauseComment.id) == comment_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_chunk(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
) -> list[ClauseComment]:
    """Return all comments for a chunk, oldest first.

    Both document_id and chunk_id are checked so a leaked chunk_id from
    another document cannot fetch comments belonging to a different document.
    """
    result = await session.execute(
        select(ClauseComment)
        .where(
            col(ClauseComment.tenant_id) == tenant_id,
            col(ClauseComment.document_id) == document_id,
            col(ClauseComment.chunk_id) == chunk_id,
        )
        .order_by(col(ClauseComment.created_at).asc())
    )
    return list(result.scalars().all())


async def create(
    session: AsyncSession,
    tenant_id: str,
    *,
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    user_id: str,
    body: str,
) -> ClauseComment:
    """Insert and flush a new comment."""
    comment = ClauseComment(
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_id=chunk_id,
        user_id=user_id,
        body=body,
    )
    session.add(comment)
    await session.flush()
    return comment


async def update_body(
    session: AsyncSession,
    tenant_id: str,
    comment_id: uuid.UUID,
    new_body: str,
) -> ClauseComment | None:
    """Edit the body of a comment. Returns None if not found."""
    comment = await get(session, tenant_id, comment_id)
    if comment is None:
        return None
    comment.body = new_body
    comment.updated_at = datetime.now(UTC)
    session.add(comment)
    await session.flush()
    return comment


async def set_resolved(
    session: AsyncSession,
    tenant_id: str,
    comment_id: uuid.UUID,
    *,
    resolved: bool,
) -> ClauseComment | None:
    """Toggle the resolved state of a comment."""
    comment = await get(session, tenant_id, comment_id)
    if comment is None:
        return None
    comment.is_resolved = resolved
    comment.updated_at = datetime.now(UTC)
    session.add(comment)
    await session.flush()
    return comment


async def delete(
    session: AsyncSession,
    tenant_id: str,
    comment_id: uuid.UUID,
) -> bool:
    """Hard-delete a comment. Returns True if deleted, False if not found."""
    comment = await get(session, tenant_id, comment_id)
    if comment is None:
        return False
    await session.delete(comment)
    await session.flush()
    return True
