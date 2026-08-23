"""DTOs for cross-reference resolution — Phase 8."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ResolvedRefOut(BaseModel):
    """A single cross-reference with its resolved target (or null if unresolvable)."""

    raw: str
    normalised: str
    target_chunk_id: UUID | None = None
    target_section: str | None = None
    target_heading: str | None = None
    target_page: int | None = None
    target_content: str | None = None


class ChunkRefsResponse(BaseModel):
    """Response for GET /documents/{id}/chunks/{chunk_id}/refs."""

    chunk_id: UUID
    document_id: UUID
    refs: list[ResolvedRefOut]
