import uuid
from typing import Optional

from sqlmodel import Field

from app.models.base import TenantModel


class Conversation(TenantModel, table=True):
    """
    A Q&A session between a user and their documents.

    document_id is optional: None means the conversation spans all documents in
    the tenant (multi-document mode, introduced in Phase 9).
    """

    __tablename__ = "conversations"

    user_id: str = Field(nullable=False, index=True, description="Clerk user_id")
    # None = tenant-wide; a UUID = scoped to a single document
    document_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="documents.id",
        index=True,
    )
    title: Optional[str] = Field(default=None)
    is_archived: bool = Field(default=False, nullable=False)
