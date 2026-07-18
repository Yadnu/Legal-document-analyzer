from pydantic import BaseModel


class UserContext(BaseModel):
    """Extracted from the verified Clerk JWT `sub` claim."""

    user_id: str


class TenantContext(BaseModel):
    """Extracted from the verified Clerk JWT `org_id` / `org_slug` claims."""

    tenant_id: str
    slug: str


class MeResponse(BaseModel):
    user_id: str
    tenant_id: str
    tenant_slug: str
