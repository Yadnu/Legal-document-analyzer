"""Clerk organization membership.

Roles on protected routes come from the JWT ``org_role`` claim, so a local
users row is not enough. Accepting an invite, changing a role, or removing
a member also updates the Clerk organization.

When ``CLERK_SECRET_KEY`` is empty the directory refuses membership changes
rather than recording a local role Clerk will never enforce.
"""

from __future__ import annotations

from typing import Protocol

import httpx
import structlog
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import OrgRole

log = structlog.get_logger(__name__)

_API = "https://api.clerk.com/v1"


class ClerkMembershipError(Exception):
    """Clerk rejected a membership change, or the secret key is missing."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UserProfile(BaseModel):
    email: str | None = None
    full_name: str | None = None


def to_clerk_role(role: str) -> str:
    """Map a product role onto a Clerk organization role.

    ``editor`` uses Clerk's built-in ``org:member``, which this API already
    treats as an editor. ``viewer`` requires the custom ``org:viewer`` role.
    """
    if role == OrgRole.ADMIN:
        return "org:admin"
    if role == OrgRole.VIEWER:
        return "org:viewer"
    return "org:member"


class OrgDirectory(Protocol):
    async def profile(self, user_id: str) -> UserProfile: ...

    async def add_member(self, org_id: str, user_id: str, role: str) -> None: ...

    async def update_member_role(
        self, org_id: str, user_id: str, role: str
    ) -> None: ...

    async def remove_member(self, org_id: str, user_id: str) -> None: ...


class NullOrgDirectory:
    """Fail closed when Clerk's secret key is not configured."""

    async def profile(self, user_id: str) -> UserProfile:
        return UserProfile()

    async def add_member(self, org_id: str, user_id: str, role: str) -> None:
        raise ClerkMembershipError("CLERK_SECRET_KEY is not configured")

    async def update_member_role(self, org_id: str, user_id: str, role: str) -> None:
        raise ClerkMembershipError("CLERK_SECRET_KEY is not configured")

    async def remove_member(self, org_id: str, user_id: str) -> None:
        raise ClerkMembershipError("CLERK_SECRET_KEY is not configured")


class ClerkOrgDirectory:
    def __init__(
        self,
        secret_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._client = client

    async def profile(self, user_id: str) -> UserProfile:
        response = await self._request("GET", f"/users/{user_id}")
        if response.status_code != 200:
            log.warning(
                "clerk_profile_failed",
                user_id=user_id,
                status=response.status_code,
            )
            return UserProfile()
        data = response.json()
        return UserProfile(email=_primary_email(data), full_name=_full_name(data))

    async def add_member(self, org_id: str, user_id: str, role: str) -> None:
        response = await self._request(
            "POST",
            f"/organizations/{org_id}/memberships",
            json={"user_id": user_id, "role": to_clerk_role(role)},
        )
        if response.status_code < 300 or _already_member(response):
            return
        _raise(response, "add_member")

    async def update_member_role(self, org_id: str, user_id: str, role: str) -> None:
        response = await self._request(
            "PATCH",
            f"/organizations/{org_id}/memberships/{user_id}",
            json={"role": to_clerk_role(role)},
        )
        if response.status_code < 300:
            return
        _raise(response, "update_member_role")

    async def remove_member(self, org_id: str, user_id: str) -> None:
        response = await self._request(
            "DELETE",
            f"/organizations/{org_id}/memberships/{user_id}",
        )
        if response.status_code < 300 or response.status_code == 404:
            return
        _raise(response, "remove_member")

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._secret_key}"}
        url = f"{_API}{path}"
        if self._client is not None:
            return await self._client.request(method, url, headers=headers, json=json)
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.request(method, url, headers=headers, json=json)


def get_org_directory() -> OrgDirectory:
    if settings.clerk_secret_key:
        return ClerkOrgDirectory(settings.clerk_secret_key)
    return NullOrgDirectory()


def _primary_email(data: dict) -> str | None:
    primary_id = data.get("primary_email_address_id")
    addresses = data.get("email_addresses") or []
    chosen: str | None = None
    for item in addresses:
        if not isinstance(item, dict):
            continue
        address = item.get("email_address")
        if not isinstance(address, str) or not address.strip():
            continue
        if item.get("id") == primary_id:
            return address.strip().lower()
        chosen = chosen or address.strip().lower()
    return chosen


def _full_name(data: dict) -> str | None:
    parts = [
        part.strip()
        for part in (data.get("first_name"), data.get("last_name"))
        if isinstance(part, str) and part.strip()
    ]
    return " ".join(parts) or None


def _already_member(response: httpx.Response) -> bool:
    if response.status_code not in (400, 409, 422):
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("code") == "already_a_member_in_organization"
        for item in errors
    )


def _raise(response: httpx.Response, action: str) -> None:
    code = None
    try:
        payload = response.json()
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            code = errors[0].get("code")
    except ValueError:
        code = None
    log.error(
        "clerk_membership_failed",
        action=action,
        status=response.status_code,
        code=code,
    )
    raise ClerkMembershipError(f"Clerk {action} failed ({response.status_code})")
