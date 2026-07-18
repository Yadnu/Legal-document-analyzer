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

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import verify_token
from app.core.exceptions import AuthError, TenantMissingError
from app.schemas.auth import TenantContext, UserContext

_bearer = HTTPBearer(auto_error=False)


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
