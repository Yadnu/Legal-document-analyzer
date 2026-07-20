import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field

from app.models.base import TenantModel


class Obligation(TenantModel, table=True):
    """
    A contractual obligation or deadline extracted from a Document.

    Linked to the specific chunk that contains the obligation so the user can
    jump directly to the source clause. The worker service populates this table
    during Phase 10 (obligation extraction).
    """

    __tablename__ = "obligations"

    document_id: uuid.UUID = Field(nullable=False, index=True, foreign_key="documents.id")
    chunk_id: Optional[uuid.UUID] = Field(
        default=None,
        index=True,
        foreign_key="chunks.id",
    )
    description: str = Field(nullable=False)
    obligation_type: Optional[str] = Field(
        default=None,
        description="e.g. 'payment', 'notice', 'renewal', 'termination'",
    )
    deadline: Optional[datetime] = Field(default=None, index=True)
    reminder_days_before: int = Field(default=7, nullable=False)
    reminder_sent_at: Optional[datetime] = Field(default=None)
    is_resolved: bool = Field(default=False, nullable=False)
    assigned_to: Optional[str] = Field(
        default=None,
        description="Clerk user_id of the responsible party",
    )
