"""Role enforcement tests — Phase 10E.

Two layers:
- ``normalize_role`` is a pure function, tested directly with no DB or HTTP.
- The HTTP tests prove a viewer is rejected with 403 on every write endpoint.
  The guard runs during dependency resolution, before any service or DB work,
  so the session override yields None and no database is required.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.deps import (
    OrgRole,
    get_current_role,
    get_current_tenant,
    get_current_user,
    normalize_role,
    require_admin,
    require_editor,
)
from app.core.exceptions import ForbiddenError
from app.db.session import get_rls_db
from app.main import create_app
from app.schemas.auth import TenantContext, UserContext

FAKE_USER = UserContext(user_id="user_role_test")
FAKE_TENANT = TenantContext(tenant_id="org_role_test", slug="role-test")


# ---------------------------------------------------------------------------
# normalize_role — pure unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Clerk's prefixed form and the bare form both work.
        ("org:admin", OrgRole.ADMIN),
        ("admin", OrgRole.ADMIN),
        ("ORG:ADMIN", OrgRole.ADMIN),
        ("org:viewer", OrgRole.VIEWER),
        ("viewer", OrgRole.VIEWER),
        ("guest", OrgRole.VIEWER),
        # Clerk's built-in non-admin role keeps write access.
        ("org:member", OrgRole.EDITOR),
        ("editor", OrgRole.EDITOR),
        # Unknown or absent role stays permissive so an instance without
        # custom roles is unaffected; only VIEWER is ever restricted.
        ("", OrgRole.EDITOR),
        ("org:something_new", OrgRole.EDITOR),
    ],
)
def test_normalize_role(raw: str, expected: OrgRole) -> None:
    assert normalize_role(raw) is expected


# ---------------------------------------------------------------------------
# Viewer is blocked on write endpoints
# ---------------------------------------------------------------------------


def _client_as(role: OrgRole) -> AsyncClient:
    """Build a client authenticated as ``role`` with a no-op DB session."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_current_tenant] = lambda: FAKE_TENANT
    app.dependency_overrides[get_current_role] = lambda: role

    async def override_db() -> AsyncGenerator[None, None]:
        yield None

    app.dependency_overrides[get_rls_db] = override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_DOC_ID = uuid.uuid4()
_CHUNK_ID = uuid.uuid4()


async def test_viewer_cannot_request_upload_url() -> None:
    async with _client_as(OrgRole.VIEWER) as client:
        resp = await client.post(
            "/api/v1/documents/upload-url",
            json={
                "filename": "contract.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1024,
            },
        )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "Forbidden"


async def test_viewer_cannot_confirm_upload() -> None:
    async with _client_as(OrgRole.VIEWER) as client:
        resp = await client.post(f"/api/v1/documents/{_DOC_ID}/confirm")
    assert resp.status_code == 403, resp.text


async def test_viewer_cannot_comment() -> None:
    async with _client_as(OrgRole.VIEWER) as client:
        resp = await client.post(
            f"/api/v1/documents/{_DOC_ID}/chunks/{_CHUNK_ID}/comments",
            json={"body": "This clause looks risky."},
        )
    assert resp.status_code == 403, resp.text


async def test_viewer_cannot_extract_obligations() -> None:
    async with _client_as(OrgRole.VIEWER) as client:
        resp = await client.post(f"/api/v1/documents/{_DOC_ID}/obligations/extract")
    assert resp.status_code == 403, resp.text


async def test_viewer_cannot_read_audit_log() -> None:
    """Audit log is admin-only, so a viewer is rejected there too."""
    async with _client_as(OrgRole.VIEWER) as client:
        resp = await client.get("/api/v1/audit-log")
    assert resp.status_code == 403, resp.text


async def test_viewer_cannot_delete_document() -> None:
    async with _client_as(OrgRole.VIEWER) as client:
        resp = await client.delete(f"/api/v1/documents/{_DOC_ID}")
    assert resp.status_code == 403, resp.text


async def test_editor_cannot_read_audit_log() -> None:
    """Editors have write access but are not admins."""
    async with _client_as(OrgRole.EDITOR) as client:
        resp = await client.get("/api/v1/audit-log")
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Guard dependencies, called directly
# ---------------------------------------------------------------------------


async def test_get_current_role_reads_claim() -> None:
    assert await get_current_role({"org_role": "org:admin"}) is OrgRole.ADMIN
    assert await get_current_role({}) is OrgRole.EDITOR


@pytest.mark.parametrize("role", [OrgRole.ADMIN, OrgRole.EDITOR])
async def test_require_editor_allows_write_roles(role: OrgRole) -> None:
    assert await require_editor(role) is role


async def test_require_editor_rejects_viewer() -> None:
    with pytest.raises(ForbiddenError):
        await require_editor(OrgRole.VIEWER)


async def test_require_admin_allows_admin() -> None:
    assert await require_admin(OrgRole.ADMIN) is OrgRole.ADMIN


@pytest.mark.parametrize("role", [OrgRole.EDITOR, OrgRole.VIEWER])
async def test_require_admin_rejects_non_admin(role: OrgRole) -> None:
    with pytest.raises(ForbiddenError):
        await require_admin(role)
