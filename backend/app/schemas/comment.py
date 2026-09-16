"""Pydantic schemas for the ClauseComment resource."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class CommentOut(BaseModel):
    """Public representation of one clause comment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    user_id: str
    body: str
    is_resolved: bool
    created_at: datetime
    updated_at: datetime | None


class CommentListResponse(BaseModel):
    items: list[CommentOut]


class CommentCreate(BaseModel):
    """Body required to post a new comment."""

    body: str

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment body must not be empty.")
        if len(v) > 4000:
            raise ValueError("Comment body must not exceed 4000 characters.")
        return v


class CommentPatch(BaseModel):
    """Editable fields on an existing comment."""

    body: str | None = None
    is_resolved: bool | None = None

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Comment body must not be empty.")
            if len(v) > 4000:
                raise ValueError("Comment body must not exceed 4000 characters.")
        return v
