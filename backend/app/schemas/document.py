"""Pydantic DTOs for the document upload and status endpoints.

These are the *only* types that cross the HTTP boundary — the SQLModel table
objects (``app.models.document``) never leave the service layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UploadRequestBody(BaseModel):
    """Request body for ``POST /documents/upload-url``."""

    filename: str
    content_type: str
    size_bytes: int


class PresignedUploadResponse(BaseModel):
    """Returned after a successful ``request_upload`` call."""

    document_id: UUID
    upload_url: str  # presigned S3 PUT URL
    s3_key: str
    expires_in: int  # seconds until the presigned URL expires


class DocumentResponse(BaseModel):
    """Full document representation returned by status-polling and confirm endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: str
    title: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str  # processing | ready | failed
    created_at: datetime
    # error_reason is intentionally omitted — never exposed to API consumers


class ViewUrlResponse(BaseModel):
    """Returned by the view-url endpoint."""

    document_id: UUID
    url: str
    expires_in: int = 300


class DocumentSummary(BaseModel):
    """Lightweight representation used in the list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: str
    created_at: datetime
