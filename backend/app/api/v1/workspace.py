"""Shared workspace and invite routes.

Tenant for every management route comes from the verified JWT. Accepting an
invite is the exception: the caller may not belong to the workspace yet, so
the tenant is read from the invite row located by the secret token.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    OrgRole,
    get_current_role,
    get_current_tenant,
    get_current_user,
    require_admin,
)
from app.db.session import get_invite_db, get_rls_db
from app.infra.clerk_orgs import OrgDirectory, get_org_directory
from app.schemas.auth import TenantContext, UserContext
from app.schemas.workspace import (
    InviteAccept,
    InviteAccepted,
    InviteCreate,
    InviteCreated,
    MemberOut,
    MemberRolePatch,
    WorkspaceSnapshot,
)
from app.services import workspace_service

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceSnapshot)
async def get_workspace(
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    role: OrgRole = Depends(get_current_role),
    session: AsyncSession = Depends(get_rls_db),
    directory: OrgDirectory = Depends(get_org_directory),
) -> WorkspaceSnapshot:
    """Members, pending invites, and how many seats are left."""
    return await workspace_service.snapshot(session, tenant, user, role, directory)


@router.post("/invites", response_model=InviteCreated, status_code=201)
async def create_invite(
    body: InviteCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    role: OrgRole = Depends(require_admin),
    session: AsyncSession = Depends(get_rls_db),
    directory: OrgDirectory = Depends(get_org_directory),
) -> InviteCreated:
    """Invite someone by email. Admin only. The token is returned once."""
    return await workspace_service.create_invite(
        session,
        tenant,
        user,
        directory,
        email=body.email,
        role=body.role,
        caller_role=role,
    )


@router.post("/invites/accept", response_model=InviteAccepted)
async def accept_invite(
    body: InviteAccept,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_invite_db),
    directory: OrgDirectory = Depends(get_org_directory),
) -> InviteAccepted:
    """Join the workspace named by the invite token.

    Requires a signed-in user. Does not read ``org_id`` from the token's
    claims or from the request body.
    """
    return await workspace_service.accept_invite(
        session,
        user,
        directory,
        token=body.token,
    )


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    _role: OrgRole = Depends(require_admin),
    session: AsyncSession = Depends(get_rls_db),
) -> None:
    await workspace_service.revoke_invite(session, tenant, user, invite_id)


@router.patch("/members/{clerk_user_id}", response_model=MemberOut)
async def change_member_role(
    clerk_user_id: str,
    body: MemberRolePatch,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    _role: OrgRole = Depends(require_admin),
    session: AsyncSession = Depends(get_rls_db),
    directory: OrgDirectory = Depends(get_org_directory),
) -> MemberOut:
    return await workspace_service.change_role(
        session,
        tenant,
        user,
        directory,
        clerk_user_id=clerk_user_id,
        role=body.role,
    )


@router.delete("/members/{clerk_user_id}", status_code=204)
async def remove_member(
    clerk_user_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    _role: OrgRole = Depends(require_admin),
    session: AsyncSession = Depends(get_rls_db),
    directory: OrgDirectory = Depends(get_org_directory),
) -> None:
    await workspace_service.remove_member(
        session,
        tenant,
        user,
        directory,
        clerk_user_id=clerk_user_id,
    )
