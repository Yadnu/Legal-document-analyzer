"""
FastAPI dependency functions for authentication and tenant resolution.

Dependency chain:
  get_verified_claims  (verifies JWT once per request)
      └── get_current_user   (extracts UserContext from claims)
      └── get_current_tenant (extracts TenantContext from claims)

FastAPI caches dependency results within a single request, so the JWT is
decoded only once even when both get_current_user and get_current_tenant are
injected into the same endpoint.
"""

from enum import StrEnum

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import verify_token
from app.core.exceptions import AuthError, ForbiddenError, TenantMissingError
from app.schemas.auth import TenantContext, UserContext

_bearer = HTTPBearer(auto_error=False)


class OrgRole(StrEnum):
    """Normalised org role, ordered from most to least privileged."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


async def get_verified_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    Extract and verify the Bearer JWT from the Authorization header.

    Raises AuthError (-> 401) when the header is absent or the token is invalid.
    """
    if credentials is None:
        raise AuthError("Authorization header is required")

    return await verify_token(credentials.credentials)


async def get_current_user(
    claims: dict = Depends(get_verified_claims),
) -> UserContext:
    """Return the authenticated user extracted from the verified JWT claims."""
    user_id: str | None = claims.get("sub")
    if not user_id:
        raise AuthError("Token is missing the 'sub' claim")
    return UserContext(user_id=user_id)


async def get_current_tenant(
    claims: dict = Depends(get_verified_claims),
) -> TenantContext:
    """
    Return the active tenant extracted from the verified JWT claims.

    Raises TenantMissingError (-> 403) when the token has no org_id — the user
    must have an active Clerk Organization to use protected endpoints.
    """
    tenant_id: str | None = claims.get("org_id")
    if not tenant_id:
        raise TenantMissingError(
            "Token contains no org_id claim. "
            "The user must belong to and have an active Clerk Organization."
        )
    slug: str = claims.get("org_slug", "")
    return TenantContext(tenant_id=tenant_id, slug=slug)


def normalize_role(raw_role: str) -> OrgRole:
    """Map a raw Clerk ``org_role`` claim onto an :class:`OrgRole`.

    Clerk sends either the prefixed form (``"org:admin"``) or the bare name
    (``"admin"``).  Its two built-in roles are ``org:admin`` and ``org:member``;
    read-only access requires a custom ``org:viewer`` role.  Anything
    unrecognised — including a missing claim — is treated as EDITOR so that a
    Clerk instance without custom roles keeps full write access.  Only VIEWER
    is restricted, and it must be granted explicitly.
    """
    name = raw_role.split(":", 1)[-1].strip().lower()
    if name == OrgRole.ADMIN:
        return OrgRole.ADMIN
    if name in (OrgRole.VIEWER, "guest"):
        return OrgRole.VIEWER
    return OrgRole.EDITOR


async def get_current_role(
    claims: dict = Depends(get_verified_claims),
) -> OrgRole:
    """Return the caller's normalised org role from the verified JWT."""
    return normalize_role(claims.get("org_role", ""))


async def require_admin(
    role: OrgRole = Depends(get_current_role),
) -> OrgRole:
    """Enforce that the caller holds the org:admin role.

    Raises ForbiddenError (→ 403) for any non-admin role.
    """
    if role is not OrgRole.ADMIN:
        raise ForbiddenError("This endpoint requires the org:admin role.")
    return role


async def require_editor(
    role: OrgRole = Depends(get_current_role),
) -> OrgRole:
    """Enforce write access: admin or editor, never viewer.

    Raises ForbiddenError (→ 403) for viewers.
    """
    if role is OrgRole.VIEWER:
        raise ForbiddenError(
            "This endpoint requires write access; viewers are read-only."
        )
    return role
