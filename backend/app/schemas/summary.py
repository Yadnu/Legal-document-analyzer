"""Pydantic DTOs for the document summary card endpoint."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SummaryFieldOut(BaseModel):
    """A single extracted field with its supporting citation."""

    value: str | None = None
    chunk_id: UUID | None = None
    section: str | None = None
    quote: str | None = None

    @classmethod
    def from_jsonb(cls, data: dict | None) -> SummaryFieldOut:
        if not data:
            return cls()
        chunk_id_raw = data.get("chunk_id")
        try:
            chunk_id = UUID(str(chunk_id_raw)) if chunk_id_raw else None
        except (TypeError, ValueError):
            chunk_id = None
        return cls(
            value=data.get("value"),
            chunk_id=chunk_id,
            section=data.get("section"),
            quote=data.get("quote"),
        )


class DocumentSummaryCardResponse(BaseModel):
    """Full structured extraction card returned by GET /documents/{id}/summary."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    parties: SummaryFieldOut
    effective_date: SummaryFieldOut
    term_length: SummaryFieldOut
    payment_terms: SummaryFieldOut
    termination_rights: SummaryFieldOut
    liability_caps: SummaryFieldOut
    governing_law: SummaryFieldOut
    extracted_at: datetime

    @classmethod
    def from_card(cls, card) -> DocumentSummaryCardResponse:  # type: ignore[type-arg]
        return cls(
            document_id=card.document_id,
            parties=SummaryFieldOut.from_jsonb(card.parties),
            effective_date=SummaryFieldOut.from_jsonb(card.effective_date),
            term_length=SummaryFieldOut.from_jsonb(card.term_length),
            payment_terms=SummaryFieldOut.from_jsonb(card.payment_terms),
            termination_rights=SummaryFieldOut.from_jsonb(card.termination_rights),
            liability_caps=SummaryFieldOut.from_jsonb(card.liability_caps),
            governing_law=SummaryFieldOut.from_jsonb(card.governing_law),
            extracted_at=card.extracted_at,
        )
