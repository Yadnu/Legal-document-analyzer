import uuid
from typing import Optional

from sqlmodel import Field

from app.models.base import TenantModel


class User(TenantModel, table=True):
    """
    Application user within a tenant.

    clerk_user_id maps to the Clerk JWT `sub` claim.
    A user may exist in multiple tenants (one row per tenant membership).
    """

    __tablename__ = "users"

    clerk_user_id: str = Field(nullable=False, index=True)
    email: str = Field(nullable=False, index=True)
    full_name: Optional[str] = Field(default=None)
    # Role within the organization: "admin" | "member"
    role: str = Field(default="member", nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    last_seen_at: Optional[str] = Field(default=None)
