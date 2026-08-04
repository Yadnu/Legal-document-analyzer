import uuid

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import TenantModel


class AuditEvent(TenantModel, table=True):
    """
    Immutable audit log entry.

    Every significant user or system action produces one row. The table is
    append-only — rows are never updated or deleted. RLS ensures tenants can
    only query their own audit trail.

    metadata_json holds action-specific context, e.g. the document title on an
    upload event, or old/new values on a settings change.
    """

    __tablename__ = "audit_events"

    user_id: str = Field(
        nullable=False,
        index=True,
        description="Clerk user_id; 'system' for worker-initiated events",
    )
    action: str = Field(
        nullable=False, index=True, description="e.g. 'document.upload'"
    )
    resource_type: str | None = Field(
        default=None,
        description="e.g. 'document', 'conversation', 'message'",
    )
    resource_id: uuid.UUID | None = Field(default=None, index=True)
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    # JSON object with action-specific context; never contains secrets or document text
    metadata_json: str | None = Field(default=None, sa_column=Column(Text))
