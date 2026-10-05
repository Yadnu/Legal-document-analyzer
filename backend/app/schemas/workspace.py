"""Pydantic schemas for shared workspaces and invites."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.deps import OrgRole

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ROLES = {role.value for role in OrgRole}


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def require_role_name(value: str) -> str:
    name = value.strip().lower()
    if name not in _ROLES:
        raise ValueError("Role must be admin, editor, or viewer.")
    return name


class MemberOut(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime


class InviteOut(BaseModel):
    """Invite as shown in the workspace. Never includes the token."""

    id: uuid.UUID
    email: str
    role: str
    status: str
    invited_by: str
    expires_at: datetime
    created_at: datetime


class InviteCreated(InviteOut):
    """Returned once, to the admin who just created the invite."""

    invite_url: str


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    role: str

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("role")
    @classmethod
    def clean_role(cls, value: str) -> str:
        return require_role_name(value)


class InviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str

    @field_validator("token")
    @classmethod
    def clean_token(cls, value: str) -> str:
        token = value.strip()
        if len(token) < 20 or len(token) > 128:
            raise ValueError("Invite token is invalid.")
        return token


class InviteAccepted(BaseModel):
    tenant_id: str
    workspace_name: str
    role: str


class MemberRolePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str

    @field_validator("role")
    @classmethod
    def clean_role(cls, value: str) -> str:
        return require_role_name(value)


class WorkspaceSnapshot(BaseModel):
    name: str
    slug: str
    caller_role: str
    max_members: int
    seat_count: int
    members: list[MemberOut]
    invites: list[InviteOut]
