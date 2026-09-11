"""Pydantic schemas for the Obligation resource."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class ObligationOut(BaseModel):
    """Public representation of a single obligation row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID | None
    description: str
    obligation_type: str | None
    deadline: datetime | None
    reminder_days_before: int
    reminder_sent_at: datetime | None
    is_resolved: bool
    assigned_to: str | None
    created_at: datetime


class ObligationListResponse(BaseModel):
    items: list[ObligationOut]
    total: int


# ---------------------------------------------------------------------------
# Input — create (used by the extraction endpoint and manual creation)
# ---------------------------------------------------------------------------

class ObligationCreate(BaseModel):
    """Fields required to create one obligation."""

    document_id: uuid.UUID
    chunk_id: uuid.UUID | None = None
    description: str
    obligation_type: str | None = None
    deadline: datetime | None = None
    reminder_days_before: int = 7
    assigned_to: str | None = None

    @field_validator("obligation_type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        allowed = {"payment", "notice", "renewal", "termination", "other", None}
        if v not in allowed:
            raise ValueError(f"obligation_type must be one of {allowed - {None}}")
        return v

    @field_validator("reminder_days_before")
    @classmethod
    def validate_reminder(cls, v: int) -> int:
        if v < 0 or v > 365:
            raise ValueError("reminder_days_before must be between 0 and 365")
        return v


# ---------------------------------------------------------------------------
# Input — patch (all fields optional)
# ---------------------------------------------------------------------------

class ObligationPatch(BaseModel):
    """Subset of fields that can be edited after creation."""

    description: str | None = None
    obligation_type: str | None = None
    deadline: datetime | None = None
    reminder_days_before: int | None = None
    assigned_to: str | None = None

    @field_validator("obligation_type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        allowed = {"payment", "notice", "renewal", "termination", "other", None}
        if v not in allowed:
            raise ValueError(f"obligation_type must be one of {allowed - {None}}")
        return v

    @field_validator("reminder_days_before")
    @classmethod
    def validate_reminder(cls, v: int | None) -> int | None:
        if v is not None and (v < 0 or v > 365):
            raise ValueError("reminder_days_before must be between 0 and 365")
        return v
