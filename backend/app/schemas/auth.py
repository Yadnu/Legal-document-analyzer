from pydantic import BaseModel


class UserContext(BaseModel):
    """Extracted from the verified Clerk JWT.

    ``email`` and ``full_name`` are present when the session token includes
    them. Invite acceptance falls back to the Clerk Backend API when they
    are absent.
    """

    user_id: str
    email: str | None = None
    full_name: str | None = None


class TenantContext(BaseModel):
    """Extracted from the verified Clerk JWT `org_id` / `org_slug` claims."""

    tenant_id: str
    slug: str


class MeResponse(BaseModel):
    user_id: str
    tenant_id: str
    tenant_slug: str
