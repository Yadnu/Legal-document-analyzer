"""Documents router — upload pipeline endpoints.

Routes
------
POST   /documents/upload-url          Request a presigned S3 PUT URL.
POST   /documents/{document_id}/confirm  Confirm the browser PUT completed.
GET    /documents/{document_id}        Fetch a single document (status polling).
GET    /documents                      List all tenant documents.

All routes are thin: they validate HTTP input via Pydantic, delegate to the
upload service, and return a DTO.  Zero direct DB or AWS calls here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_tenant, get_current_user
from app.core.exceptions import NotFoundError
from app.db.session import get_rls_db
from app.repositories import document_repo
from app.schemas.auth import TenantContext, UserContext
from app.schemas.document import (
    DocumentResponse,
    DocumentSummary,
    PresignedUploadResponse,
    UploadRequestBody,
    ViewUrlResponse,
)
from app.services.upload_service import upload_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload-url", response_model=PresignedUploadResponse, status_code=201)
async def request_upload_url(
    body: UploadRequestBody,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_db),
) -> PresignedUploadResponse:
    """Validate the upload request, persist a Document row, and return a presigned URL.

    The client must PUT the file to ``upload_url`` before calling the confirm endpoint.
    """
    return await upload_service.request_upload(
        session=session,
        tenant_id=tenant.tenant_id,
        user_id=user.user_id,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
    )


@router.post(
    "/{document_id}/confirm",
    response_model=DocumentResponse,
    status_code=200,
)
async def confirm_upload(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> DocumentResponse:
    """Enqueue the ingestion job after the browser PUT to S3 completes.

    Returns the document DTO so the client can begin polling ``status``.
    """
    return await upload_service.confirm_upload(
        session=session,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> DocumentResponse:
    """Return a single document for status polling.

    Returns 404 when the document does not exist or belongs to a different tenant.
    """
    doc = await document_repo.get_by_id(session, tenant.tenant_id, document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found.")
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/view-url", response_model=ViewUrlResponse)
async def get_view_url(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> ViewUrlResponse:
    """Return a short-lived presigned S3 GET URL for viewing the document in-browser."""
    url = await upload_service.get_view_url(
        session=session,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
    )
    return ViewUrlResponse(document_id=document_id, url=url)


@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> list[DocumentSummary]:
    """Return all documents for the current tenant, newest first."""
    docs = await document_repo.list_for_tenant(session, tenant.tenant_id)
    return [DocumentSummary.model_validate(d) for d in docs]
