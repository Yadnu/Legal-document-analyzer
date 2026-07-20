import uuid
from typing import Optional

from sqlmodel import Field

from app.models.base import TenantModel


class DocumentStatus:
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(TenantModel, table=True):
    """
    A legal document uploaded by a tenant user.

    Lifecycle: processing -> ready | failed
    The s3_key is the authoritative reference to the raw file.
    The ingestion worker owns all status transitions.
    """

    __tablename__ = "documents"

    title: str = Field(nullable=False)
    original_filename: str = Field(nullable=False)
    content_type: str = Field(nullable=False)
    size_bytes: int = Field(nullable=False)
    s3_key: str = Field(nullable=False, unique=True, index=True)
    # Idempotency key — the SQS worker uses this to detect reprocessing.
    idempotency_key: str = Field(nullable=False, unique=True, index=True)
    status: str = Field(
        default=DocumentStatus.PROCESSING,
        nullable=False,
        index=True,
    )
    # Populated by the worker on failure; never logged or returned in API responses.
    error_reason: Optional[str] = Field(default=None)
    uploaded_by: str = Field(nullable=False, description="Clerk user_id of the uploader")
    page_count: Optional[int] = Field(default=None)
