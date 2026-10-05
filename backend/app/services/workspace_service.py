"""Shared workspace membership and invites."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import OrgRole
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    QuotaExceededError,
    ValidationError,
)
from app.db.rls import set_invite_token, set_tenant_context
from app.infra.clerk_orgs import ClerkMembershipError, OrgDirectory
from app.infra.ses import send_invite_email
from app.models.user import User
from app.models.workspace_invite import WorkspaceInvite
from app.repositories import invite_repo, org_repo, user_repo
from app.schemas.auth import TenantContext, UserContext
from app.schemas.workspace import (
    InviteAccepted,
    InviteCreated,
    InviteOut,
    MemberOut,
    WorkspaceSnapshot,
)
from app.services import audit_service

log = structlog.get_logger(__name__)

_DEFAULT_MAX_MEMBERS = 5


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _member_out(user: User) -> MemberOut:
    return MemberOut(
        user_id=user.clerk_user_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _invite_out(invite: WorkspaceInvite) -> InviteOut:
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        status=invite.status,
        invited_by=invite.invited_by,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


def _invite_url(raw_token: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/invite/{raw_token}"


async def _workspace_name(
    session: AsyncSession, tenant: TenantContext
) -> tuple[str, str, int]:
    org = await org_repo.get_for_tenant(session, tenant.tenant_id)
    if org is None:
        return tenant.slug or "Workspace", tenant.slug, _DEFAULT_MAX_MEMBERS
    return org.name, org.slug, org.max_members


async def _caller_email(
    user: UserContext, directory: OrgDirectory
) -> tuple[str | None, str | None]:
    if user.email:
        return user.email, user.full_name
    profile = await directory.profile(user.user_id)
    return profile.email or None, user.full_name or profile.full_name


async def snapshot(
    session: AsyncSession,
    tenant: TenantContext,
    user: UserContext,
    role: OrgRole,
    directory: OrgDirectory,
) -> WorkspaceSnapshot:
    now = datetime.now(UTC)
    await invite_repo.expire_overdue(session, tenant.tenant_id, now)
    email, full_name = await _caller_email(user, directory)
    if email:
        await user_repo.ensure_member(
            session,
            tenant.tenant_id,
            clerk_user_id=user.user_id,
            email=email,
            full_name=full_name,
            role=role.value,
        )
    name, slug, max_members = await _workspace_name(session, tenant)
    members = await user_repo.list_active(session, tenant.tenant_id)
    invites = await invite_repo.list_pending(session, tenant.tenant_id)
    await session.commit()
    return WorkspaceSnapshot(
        name=name,
        slug=slug,
        caller_role=role.value,
        max_members=max_members,
        seat_count=len(members) + len(invites),
        members=[_member_out(member) for member in members],
        invites=[_invite_out(invite) for invite in invites],
    )


async def create_invite(
    session: AsyncSession,
    tenant: TenantContext,
    user: UserContext,
    directory: OrgDirectory,
    *,
    email: str,
    role: str,
    caller_role: OrgRole,
) -> InviteCreated:
    now = datetime.now(UTC)
    await invite_repo.expire_overdue(session, tenant.tenant_id, now)
    caller_email, caller_name = await _caller_email(user, directory)
    if caller_email:
        await user_repo.ensure_member(
            session,
            tenant.tenant_id,
            clerk_user_id=user.user_id,
            email=caller_email,
            full_name=caller_name,
            role=caller_role.value,
        )
    name, _slug, max_members = await _workspace_name(session, tenant)

    existing = await user_repo.get_by_email(session, tenant.tenant_id, email)
    if existing is not None and existing.is_active:
        raise ValidationError("That person is already in this workspace.")

    pending = await invite_repo.get_pending_for_email(session, tenant.tenant_id, email)
    if pending is not None:
        raise ValidationError("An invite is already pending for that email.")

    active = await user_repo.count_active(session, tenant.tenant_id)
    waiting = await invite_repo.count_pending(session, tenant.tenant_id)
    if active + waiting >= max_members:
        raise QuotaExceededError(
            f"This workspace has reached its member limit ({max_members})."
        )

    raw_token = secrets.token_urlsafe(32)
    invite = await invite_repo.create(
        session,
        tenant.tenant_id,
        email=email,
        role=role,
        token_hash=hash_invite_token(raw_token),
        invited_by=user.user_id,
        expires_at=now + timedelta(days=settings.invite_ttl_days),
    )
    await audit_service.log(
        session,
        tenant.tenant_id,
        user.user_id,
        "member.invited",
        resource_type="workspace_invite",
        resource_id=invite.id,
        metadata={"email": email, "role": role},
    )
    await session.commit()

    url = _invite_url(raw_token)
    await send_invite_email(
        to_address=email,
        workspace_name=name,
        role=role,
        invite_url=url,
    )
    log.info(
        "workspace_invite_created",
        tenant_id=tenant.tenant_id,
        invite_id=str(invite.id),
        role=role,
    )
    created = _invite_out(invite)
    return InviteCreated(**created.model_dump(), invite_url=url)


async def revoke_invite(
    session: AsyncSession,
    tenant: TenantContext,
    user: UserContext,
    invite_id: uuid.UUID,
) -> None:
    invite = await invite_repo.get(session, tenant.tenant_id, invite_id)
    if invite is None:
        raise NotFoundError("Invite not found.")
    if invite.status != "pending":
        raise ValidationError("Only a pending invite can be revoked.")
    invite.status = "revoked"
    session.add(invite)
    await audit_service.log(
        session,
        tenant.tenant_id,
        user.user_id,
        "member.invite_revoked",
        resource_type="workspace_invite",
        resource_id=invite.id,
        metadata={"email": invite.email},
    )
    await session.commit()


async def accept_invite(
    session: AsyncSession,
    user: UserContext,
    directory: OrgDirectory,
    *,
    token: str,
) -> InviteAccepted:
    token_hash = hash_invite_token(token)
    await set_invite_token(session, token_hash)
    invite = await invite_repo.get_by_token_hash(session, token_hash)
    if invite is None:
        raise NotFoundError("Invite not found.")
    if invite.status != "pending":
        raise ValidationError("This invite is no longer pending.")
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise ValidationError("This invite has expired.")

    email, full_name = await _caller_email(user, directory)
    if not email:
        raise ValidationError(
            "We couldn't read an email address from your account. "
            "Sign in with the address that received the invite."
        )
    if email != invite.email:
        raise ForbiddenError("This invite was sent to a different email address.")

    tenant_id = invite.tenant_id
    await set_tenant_context(session, tenant_id)
    await _apply_membership(
        session,
        directory,
        tenant_id=tenant_id,
        user=user,
        email=email,
        full_name=full_name,
        role=invite.role,
    )
    invite.status = "accepted"
    invite.accepted_at = datetime.now(UTC)
    invite.accepted_by = user.user_id
    session.add(invite)
    await audit_service.log(
        session,
        tenant_id,
        user.user_id,
        "member.joined",
        resource_type="workspace_invite",
        resource_id=invite.id,
        metadata={"email": email, "role": invite.role},
    )
    name, _slug, _max = await _workspace_name(
        session, TenantContext(tenant_id=tenant_id, slug="")
    )
    joined_role = invite.role
    await session.commit()
    return InviteAccepted(tenant_id=tenant_id, workspace_name=name, role=joined_role)


async def change_role(
    session: AsyncSession,
    tenant: TenantContext,
    actor: UserContext,
    directory: OrgDirectory,
    *,
    clerk_user_id: str,
    role: str,
) -> MemberOut:
    member = await user_repo.get_by_clerk_id(session, tenant.tenant_id, clerk_user_id)
    if member is None or not member.is_active:
        raise NotFoundError("Member not found.")
    await _keep_an_admin(session, tenant.tenant_id, member, role)
    previous = member.role
    await _clerk(directory.update_member_role, tenant.tenant_id, clerk_user_id, role)
    member.role = role
    session.add(member)
    await audit_service.log(
        session,
        tenant.tenant_id,
        actor.user_id,
        "member.role_changed",
        resource_type="user",
        resource_id=member.id,
        metadata={
            "clerk_user_id": clerk_user_id,
            "from": previous,
            "to": role,
        },
    )
    await session.commit()
    return _member_out(member)


async def remove_member(
    session: AsyncSession,
    tenant: TenantContext,
    actor: UserContext,
    directory: OrgDirectory,
    *,
    clerk_user_id: str,
) -> None:
    member = await user_repo.get_by_clerk_id(session, tenant.tenant_id, clerk_user_id)
    if member is None or not member.is_active:
        raise NotFoundError("Member not found.")
    await _keep_an_admin(session, tenant.tenant_id, member, None)
    await _clerk(directory.remove_member, tenant.tenant_id, clerk_user_id)
    member.is_active = False
    session.add(member)
    await audit_service.log(
        session,
        tenant.tenant_id,
        actor.user_id,
        "member.removed",
        resource_type="user",
        resource_id=member.id,
        metadata={"clerk_user_id": clerk_user_id, "email": member.email},
    )
    await session.commit()


async def _apply_membership(
    session: AsyncSession,
    directory: OrgDirectory,
    *,
    tenant_id: str,
    user: UserContext,
    email: str,
    full_name: str | None,
    role: str,
) -> None:
    existing = await user_repo.get_by_clerk_id(session, tenant_id, user.user_id)
    by_email = await user_repo.get_by_email(session, tenant_id, email)
    if by_email is not None and (existing is None or by_email.id != existing.id):
        raise ValidationError(
            "That email already belongs to someone in this workspace."
        )

    await _clerk(directory.add_member, tenant_id, user.user_id, role)

    if existing is None:
        await user_repo.ensure_member(
            session,
            tenant_id,
            clerk_user_id=user.user_id,
            email=email,
            full_name=full_name,
            role=role,
        )
        return
    existing.is_active = True
    existing.role = role
    existing.email = email
    if full_name:
        existing.full_name = full_name
    session.add(existing)


async def _keep_an_admin(
    session: AsyncSession,
    tenant_id: str,
    member: User,
    new_role: str | None,
) -> None:
    if member.role != OrgRole.ADMIN or not member.is_active:
        return
    if new_role == OrgRole.ADMIN:
        return
    admins = await user_repo.count_active_admins(session, tenant_id)
    if admins <= 1:
        raise ValidationError("This workspace needs at least one admin.")


async def _clerk(method, org_id: str, user_id: str, role: str | None = None) -> None:
    try:
        if role is None:
            await method(org_id, user_id)
        else:
            await method(org_id, user_id, role)
    except ClerkMembershipError as exc:
        log.error("workspace_membership_failed", error=exc.message)
        raise ValidationError(
            "This workspace can't update membership right now. Try again later."
        ) from exc
