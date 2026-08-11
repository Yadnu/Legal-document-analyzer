"""Pydantic DTOs for the grounded Q&A endpoint."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    """Request body for ``POST /query``."""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    document_id: UUID | None = None
    conversation_id: UUID | None = None


class CitationOut(BaseModel):
    document_id: UUID
    chunk_id: UUID
    section: str | None = None
    quote: str


class QueryResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    not_found: bool
    citations: list[CitationOut]
