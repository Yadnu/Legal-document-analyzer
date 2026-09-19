"""Obligations router — Phase 10A.

Routes
------
GET    /documents/{doc_id}/obligations         — list obligations for a document
POST   /documents/{doc_id}/obligations/extract — trigger Bedrock extraction
POST   /documents/{doc_id}/obligations         — create a single obligation manually
GET    /obligations                            — paginated obligations across all docs
PATCH  /obligations/{obligation_id}            — edit an obligation
POST   /obligations/{obligation_id}/resolve    — mark an obligation resolved
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_tenant, get_current_user
from app.core.exceptions import NotFoundError
from app.db.session import get_rls_db
from app.repositories.document_repo import get_by_id as get_document
from app.schemas.auth import TenantContext, UserContext
from app.schemas.obligation import (
    ObligationCreate,
    ObligationListResponse,
    ObligationOut,
    ObligationPatch,
)
from app.services import obligation_service

router = APIRouter(tags=["obligations"])


# ---------------------------------------------------------------------------
# Per-document
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{doc_id}/obligations",
    response_model=ObligationListResponse,
)
async def list_for_document(
    doc_id: uuid.UUID,
    include_resolved: bool = Query(default=True),
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> ObligationListResponse:
    """Return all obligations extracted from a single document."""
    items = await obligation_service.list_for_document(
        session,
        tenant.tenant_id,
        doc_id,
        include_resolved=include_resolved,
    )
    return ObligationListResponse(items=items, total=len(items))


@router.post(
    "/documents/{doc_id}/obligations/extract",
    response_model=ObligationListResponse,
    status_code=201,
)
async def extract_obligations(
    doc_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_db),
) -> ObligationListResponse:
    """Trigger Bedrock obligation extraction for a document.

    Existing obligations for the document are replaced on each call.
    """
    items = await obligation_service.extract_for_document(
        session,
        tenant.tenant_id,
        doc_id,
        user_id=user.user_id,
    )
    return ObligationListResponse(items=items, total=len(items))


@router.post(
    "/documents/{doc_id}/obligations",
    response_model=ObligationOut,
    status_code=201,
)
async def create_obligation(
    doc_id: uuid.UUID,
    body: ObligationCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> ObligationOut:
    """Manually create one obligation for a document."""
    doc = await get_document(session, tenant.tenant_id, doc_id)
    if doc is None:
        raise NotFoundError(f"Document {doc_id} not found.")

    # Enforce that the obligation belongs to this document.
    if body.document_id != doc_id:
        body = body.model_copy(update={"document_id": doc_id})

    from app.repositories import obligation_repo

    row = await obligation_repo.create(session, tenant.tenant_id, body)
    await session.commit()
    return ObligationOut.model_validate(row)


# ---------------------------------------------------------------------------
# Tenant-wide
# ---------------------------------------------------------------------------


@router.get("/obligations", response_model=ObligationListResponse)
async def list_for_tenant(
    include_resolved: bool = Query(default=False),
    obligation_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> ObligationListResponse:
    """Return paginated obligations across all documents for the tenant."""
    items, total = await obligation_service.list_for_tenant(
        session,
        tenant.tenant_id,
        include_resolved=include_resolved,
        obligation_type=obligation_type,
        limit=limit,
        offset=offset,
    )
    return ObligationListResponse(items=items, total=total)


@router.patch("/obligations/{obligation_id}", response_model=ObligationOut)
async def patch_obligation(
    obligation_id: uuid.UUID,
    body: ObligationPatch,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> ObligationOut:
    """Edit description, type, deadline, reminder days, or assignee."""
    return await obligation_service.update(
        session, tenant.tenant_id, obligation_id, body
    )


@router.post(
    "/obligations/{obligation_id}/resolve",
    response_model=ObligationOut,
)
async def resolve_obligation(
    obligation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_db),
) -> ObligationOut:
    """Mark an obligation as resolved and write an audit event."""
    return await obligation_service.resolve(
        session, tenant.tenant_id, obligation_id, user_id=user.user_id
    )
