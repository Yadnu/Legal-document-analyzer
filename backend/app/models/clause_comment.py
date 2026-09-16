"""ClauseComment — annotation on a specific chunk inside a document."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import TenantModel


class ClauseComment(TenantModel, table=True):
    """
    A user-authored comment anchored to a specific chunk (clause).

    Any org member can create a comment; only the author or an admin can
    edit or delete it. Resolved comments remain in the table for audit
    purposes (is_resolved=True) but are rendered greyed-out in the UI.
    """

    __tablename__ = "clause_comments"  # type: ignore[assignment]

    document_id: uuid.UUID = Field(
        nullable=False, index=True, foreign_key="documents.id"
    )
    chunk_id: uuid.UUID = Field(nullable=False, index=True, foreign_key="chunks.id")
    user_id: str = Field(
        nullable=False,
        index=True,
        description="Clerk user_id of the comment author",
    )
    body: str = Field(sa_column=Column(Text, nullable=False))
    is_resolved: bool = Field(default=False, nullable=False)
    # Set on every edit so the UI can show "edited" status
    updated_at: datetime | None = Field(default=None)
