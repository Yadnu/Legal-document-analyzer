"""
JWKS caching and JWT verification for Clerk tokens.

The JWKS is fetched once and cached in memory for JWKS_TTL seconds. On cache
expiry the next request triggers a fresh fetch. This avoids hammering Clerk's
JWKS endpoint while staying responsive to key rotations.
"""

import time

import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AuthError

JWKS_TTL = 3600  # seconds

_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0


async def _fetch_jwks() -> dict:
    """Fetch and cache the Clerk JWKS. Returns the cached value if still fresh."""
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache and now - _jwks_fetched_at < JWKS_TTL:
        return _jwks_cache

    if not settings.clerk_jwks_url:
        raise AuthError("CLERK_JWKS_URL is not configured")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(settings.clerk_jwks_url)
        response.raise_for_status()

    _jwks_cache = response.json()
    _jwks_fetched_at = now
    return _jwks_cache


async def verify_token(token: str) -> dict:
    """
    Verify a Clerk-issued JWT against the cached JWKS.

    Returns the decoded payload dict on success.
    Raises AuthError on any verification failure.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthError(f"Invalid token header: {exc}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise AuthError("Token header is missing 'kid'")

    jwks = await _fetch_jwks()
    matching_keys = [k for k in jwks.get("keys", []) if k.get("kid") == kid]
    if not matching_keys:
        # Key may have rotated — force a refresh and retry once.
        global _jwks_fetched_at
        _jwks_fetched_at = 0.0
        jwks = await _fetch_jwks()
        matching_keys = [k for k in jwks.get("keys", []) if k.get("kid") == kid]

    if not matching_keys:
        raise AuthError(f"No JWKS key found for kid={kid!r}")

    key = matching_keys[0]

    try:
        options = {"verify_aud": False}
        if settings.clerk_issuer:
            options["verify_iss"] = True  # type: ignore[assignment]

        payload: dict = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options=options,
            issuer=settings.clerk_issuer or None,
        )
    except JWTError as exc:
        raise AuthError(f"Token verification failed: {exc}") from exc

    return payload
