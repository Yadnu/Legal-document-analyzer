"""DocumentSummaryCard — structured extraction result for a document.

One row per document, upserted by the extraction service.
Each of the seven fields is stored as a JSONB object:
    {"value": str | null, "chunk_id": str | null,
     "section": str | null, "quote": str | null}

This keeps the citation data co-located with the value so the API
can return a fully self-contained card without extra joins.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import TenantModel


class DocumentSummaryCard(TenantModel, table=True):
    __tablename__ = "document_summary_cards"  # type: ignore[assignment]

    document_id: uuid.UUID = Field(
        nullable=False,
        index=True,
        foreign_key="documents.id",
    )

    # --- Extracted fields (JSONB: {value, chunk_id, section, quote} | null) ---
    parties: dict | None = Field(default=None, sa_column=Column(JSONB))
    effective_date: dict | None = Field(default=None, sa_column=Column(JSONB))
    term_length: dict | None = Field(default=None, sa_column=Column(JSONB))
    payment_terms: dict | None = Field(default=None, sa_column=Column(JSONB))
    termination_rights: dict | None = Field(default=None, sa_column=Column(JSONB))
    liability_caps: dict | None = Field(default=None, sa_column=Column(JSONB))
    governing_law: dict | None = Field(default=None, sa_column=Column(JSONB))

    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
