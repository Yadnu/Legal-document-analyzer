"""Audit log router — read-only audit trail for admins."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_tenant, require_admin
from app.db.session import get_rls_db
from app.repositories import audit_repo
from app.schemas.audit import AuditEventOut, AuditLogResponse
from app.schemas.auth import TenantContext

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=AuditLogResponse)
async def list_audit_events(
    action: str | None = Query(default=None, description="Filter by action string"),
    since: datetime | None = Query(
        default=None,
        description="Return events on or after this UTC timestamp",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(get_current_tenant),
    _role: str = Depends(require_admin),
    session: AsyncSession = Depends(get_rls_db),
) -> AuditLogResponse:
    """Return the tenant's audit trail, newest first.

    Requires the **org:admin** role.  Filter by ``action`` or ``since`` to
    narrow results; default page size is 100 (max 500).
    """
    items, total = await audit_repo.list_for_tenant(
        session,
        tenant.tenant_id,
        action_filter=action,
        since=since,
        limit=limit,
        offset=offset,
    )
    return AuditLogResponse(
        items=[AuditEventOut.model_validate(e) for e in items],
        total=total,
    )
