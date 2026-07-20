import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TenantModel(SQLModel):
    """
    Base for every domain table.

    Every subclass inherits:
      - id         UUID primary key
      - tenant_id  Clerk org_id; indexed; used by RLS policies
      - created_at UTC timestamp set on insert
    """

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        nullable=False,
    )
    tenant_id: str = Field(
        index=True,
        nullable=False,
        description="Clerk Organization ID — enforced by Postgres RLS",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
    )
