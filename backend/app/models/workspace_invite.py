"""WorkspaceInvite — email invite into a shared workspace."""

from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field

from app.models.base import TenantModel


class WorkspaceInvite(TenantModel, table=True):
    """
    Pending or historical invitation to join a tenant workspace.

    The raw token is emailed once and never stored. ``token_hash`` is the
    SHA-256 hex digest used for lookup. Redeeming the token is the only
    cross-tenant read, and it is gated by a dedicated RLS policy.
    """

    __tablename__ = "workspace_invites"  # type: ignore[assignment]

    email: str = Field(nullable=False, index=True)
    # admin | editor | viewer
    role: str = Field(nullable=False)
    token_hash: str = Field(nullable=False, unique=True, index=True)
    # pending | accepted | revoked | expired
    status: str = Field(default="pending", nullable=False, index=True)
    invited_by: str = Field(nullable=False, description="Clerk user id of the admin")
    expires_at: datetime = Field(
        nullable=False,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )
    accepted_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
    )
    accepted_by: str | None = Field(default=None, description="Clerk user id")
