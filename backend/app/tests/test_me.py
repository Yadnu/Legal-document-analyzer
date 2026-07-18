"""
Tests for GET /api/v1/me.

Strategy:
- Authenticated (200): override get_current_user and get_current_tenant with
  known values so the test never touches Clerk or a real JWT.
- Unauthenticated (401): call with no Authorization header; the real dependency
  chain runs and raises AuthError -> 401.
- No org (403): override get_verified_claims to return claims without org_id;
  the real get_current_tenant raises TenantMissingError -> 403.
"""

import pytest
from httpx import AsyncClient

from app.core.deps import get_current_tenant, get_current_user, get_verified_claims
from app.main import create_app
from app.schemas.auth import TenantContext, UserContext

FAKE_USER = UserContext(user_id="user_test123")
FAKE_TENANT = TenantContext(tenant_id="org_test456", slug="acme-legal")


@pytest.fixture()
async def authed_client() -> AsyncClient:
    """Client whose auth dependencies are stubbed with known values."""
    from httpx import ASGITransport

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_current_tenant] = lambda: FAKE_TENANT

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture()
async def unauthed_client() -> AsyncClient:
    """Vanilla client with no dependency overrides."""
    from httpx import ASGITransport

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture()
async def no_org_client() -> AsyncClient:
    """Client whose JWT claims have no org_id (user has no active org)."""
    from httpx import ASGITransport

    app = create_app()
    app.dependency_overrides[get_verified_claims] = lambda: {"sub": "user_test123"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_me_authenticated(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/api/v1/me")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == FAKE_USER.user_id
    assert data["tenant_id"] == FAKE_TENANT.tenant_id
    assert data["tenant_slug"] == FAKE_TENANT.slug


async def test_me_unauthenticated(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "Unauthorized"
    assert "detail" in body


async def test_me_no_org(no_org_client: AsyncClient) -> None:
    response = await no_org_client.get("/api/v1/me")
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "Forbidden"
    assert "detail" in body
