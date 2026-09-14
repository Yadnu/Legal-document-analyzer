"""Pydantic schemas for the AuditEvent resource."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    """Public representation of a single audit event row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    ip_address: str | None
    user_agent: str | None
    # metadata_json is omitted from the public schema — it may contain
    # internal identifiers.  Callers that need it can request it explicitly.
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditEventOut]
    total: int
