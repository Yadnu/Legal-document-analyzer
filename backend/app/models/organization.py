from typing import Optional

from sqlmodel import Field

from app.models.base import TenantModel


class Organization(TenantModel, table=True):
    """
    One row per Clerk Organization (the tenant primitive).

    tenant_id == clerk_org_id for this table — a self-referential relationship
    that keeps RLS consistent across all tables.
    """

    __tablename__ = "organizations"

    name: str = Field(nullable=False)
    slug: str = Field(nullable=False, unique=True, index=True)
    # Clerk org_id stored explicitly so it can be queried directly.
    clerk_org_id: str = Field(nullable=False, unique=True, index=True)
    plan: str = Field(default="free", nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    max_documents: int = Field(default=50, nullable=False)
    max_members: int = Field(default=5, nullable=False)
    logo_url: Optional[str] = Field(default=None)
