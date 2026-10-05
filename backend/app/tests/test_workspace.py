"""Shared workspace invites and membership — Phase 10 collaboration.

Auth deps are stubbed. A live Postgres session is wired in like the comment
tests. Clerk is a recording double so tests never call the network; one case
uses the null directory to prove membership changes fail closed without a
secret key.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import col

from app.core.config import settings
from app.core.deps import (
    OrgRole,
    get_current_role,
    get_current_tenant,
    get_current_user,
)
from app.db.rls import set_tenant_context
from app.db.session import get_invite_db, get_rls_db
from app.infra.clerk_orgs import (
    ClerkOrgDirectory,
    NullOrgDirectory,
    OrgDirectory,
    UserProfile,
    get_org_directory,
)
from app.main import create_app
from app.models.audit_event import AuditEvent
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace_invite import WorkspaceInvite
from app.schemas.auth import TenantContext, UserContext
from app.services.workspace_service import hash_invite_token as service_hash

ADMIN = UserContext(
    user_id=f"user_admin_{uuid.uuid4().hex[:8]}",
    email="admin@example.com",
    full_name="Ada Admin",
)
EDITOR = UserContext(
    user_id=f"user_editor_{uuid.uuid4().hex[:8]}",
    email="editor@example.com",
)
INVITEE = UserContext(
    user_id=f"user_invitee_{uuid.uuid4().hex[:8]}",
    email="new.person@example.com",
    full_name="New Person",
)
TENANT = TenantContext(
    tenant_id=f"org_ws_{uuid.uuid4().hex[:8]}",
    slug="shared-workspace",
)
OTHER_TENANT = TenantContext(
    tenant_id=f"org_ws_b_{uuid.uuid4().hex[:8]}",
    slug="other-workspace",
)

_DB_URL = settings.test_database_url or settings.database_url


class RecordingDirectory:
    def __init__(self) -> None:
        self.added: list[tuple[str, str, str]] = []
        self.updated: list[tuple[str, str, str]] = []
        self.removed: list[tuple[str, str]] = []

    async def profile(self, user_id: str) -> UserProfile:
        return UserProfile()

    async def add_member(self, org_id: str, user_id: str, role: str) -> None:
        self.added.append((org_id, user_id, role))

    async def update_member_role(self, org_id: str, user_id: str, role: str) -> None:
        self.updated.append((org_id, user_id, role))

    async def remove_member(self, org_id: str, user_id: str) -> None:
        self.removed.append((org_id, user_id))


def test_hash_invite_token_is_stable() -> None:
    assert service_hash("abc") == service_hash("abc")
    assert service_hash("abc") != service_hash("abd")


async def test_clerk_maps_editor_to_builtin_member_role() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = ClerkOrgDirectory("sk_test", client=client)
        await directory.add_member("org_1", "user_1", "editor")
    assert seen["path"] == "/v1/organizations/org_1/memberships"
    assert seen["body"] == {"user_id": "user_1", "role": "org:member"}


async def test_clerk_treats_existing_membership_as_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"errors": [{"code": "already_a_member_in_organization"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = ClerkOrgDirectory("sk_test", client=client)
        await directory.add_member("org_1", "user_1", "viewer")


@pytest.fixture()
async def db_engine():
    engine = create_async_engine(_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def tenant_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await set_tenant_context(session, TENANT.tenant_id)
        yield session


def _client(
    session: AsyncSession,
    *,
    user: UserContext,
    role: OrgRole,
    directory: OrgDirectory,
    tenant: TenantContext = TENANT,
    with_tenant: bool = True,
) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda u=user: u
    app.dependency_overrides[get_org_directory] = lambda: directory
    if with_tenant:
        app.dependency_overrides[get_current_tenant] = lambda t=tenant: t
        app.dependency_overrides[get_current_role] = lambda r=role: r

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_rls_db] = override_db
    app.dependency_overrides[get_invite_db] = override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _bind(session: AsyncSession) -> TenantContext:
    """Point the session at a fresh tenant so cases do not share rows."""
    tenant = TenantContext(
        tenant_id=f"org_ws_{uuid.uuid4().hex[:8]}",
        slug=f"ws-{uuid.uuid4().hex[:6]}",
    )
    await set_tenant_context(session, tenant.tenant_id)
    return tenant


async def _org(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    max_members: int = 5,
) -> None:
    session.add(
        Organization(
            tenant_id=tenant.tenant_id,
            name="Northwind Contracts",
            slug=f"northwind-{uuid.uuid4().hex[:8]}",
            clerk_org_id=tenant.tenant_id,
            max_members=max_members,
        )
    )
    await session.commit()


def _token_from(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


async def test_admin_is_listed_and_can_invite(tenant_session: AsyncSession) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        listed = await client.get("/api/v1/workspace")
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["name"] == "Northwind Contracts"
        assert body["caller_role"] == "admin"
        assert body["members"][0]["email"] == ADMIN.email
        assert body["members"][0]["role"] == "admin"

        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "New.Person@Example.com", "role": "editor"},
        )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["email"] == "new.person@example.com"
    assert payload["role"] == "editor"
    assert "token" not in payload
    assert "token_hash" not in payload
    token = _token_from(payload["invite_url"])
    assert token not in payload["invite_url"].replace(token, "")

    result = await tenant_session.execute(select(WorkspaceInvite))
    stored = result.scalars().one()
    assert stored.token_hash == service_hash(token)
    assert stored.token_hash != token

    events = await tenant_session.execute(
        select(AuditEvent).where(col(AuditEvent.action) == "member.invited")
    )
    event = events.scalars().one()
    assert token not in (event.metadata_json or "")


async def test_accept_joins_workspace_from_another_tenant_context(
    tenant_session: AsyncSession,
    db_engine,
) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": INVITEE.email, "role": "editor"},
        )
    assert created.status_code == 201, created.text
    token = _token_from(created.json()["invite_url"])

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as outsider:
        await set_tenant_context(outsider, OTHER_TENANT.tenant_id)
        async with _client(
            outsider,
            user=INVITEE,
            role=OrgRole.VIEWER,
            directory=directory,
            tenant=OTHER_TENANT,
            with_tenant=False,
        ) as client:
            accepted = await client.post(
                "/api/v1/workspace/invites/accept",
                json={"token": token},
            )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tenant_id"] == tenant.tenant_id
    assert accepted.json()["role"] == "editor"
    assert accepted.json()["workspace_name"] == "Northwind Contracts"
    assert directory.added == [(tenant.tenant_id, INVITEE.user_id, "editor")]

    await set_tenant_context(tenant_session, tenant.tenant_id)
    members = await tenant_session.execute(
        select(User).where(col(User.clerk_user_id) == INVITEE.user_id)
    )
    joined = members.scalars().one()
    assert joined.tenant_id == tenant.tenant_id
    assert joined.role == "editor"
    assert joined.is_active is True


async def test_accept_rejects_wrong_email(tenant_session: AsyncSession) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": INVITEE.email, "role": "viewer"},
        )
        token = _token_from(created.json()["invite_url"])
        denied = await client.post(
            "/api/v1/workspace/invites/accept",
            json={"token": token},
        )
    assert denied.status_code == 403, denied.text
    assert directory.added == []


async def test_unknown_token_is_not_found(tenant_session: AsyncSession) -> None:
    tenant = await _bind(tenant_session)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=INVITEE,
        role=OrgRole.EDITOR,
        directory=directory,
        tenant=tenant,
        with_tenant=False,
    ) as client:
        resp = await client.post(
            "/api/v1/workspace/invites/accept",
            json={"token": "a" * 32},
        )
    assert resp.status_code == 404, resp.text


async def test_revoked_and_expired_invites_cannot_be_accepted(
    tenant_session: AsyncSession,
) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as admin:
        created = await admin.post(
            "/api/v1/workspace/invites",
            json={"email": "revoked@example.com", "role": "editor"},
        )
        invite_id = created.json()["id"]
        revoked = await admin.delete(f"/api/v1/workspace/invites/{invite_id}")
        assert revoked.status_code == 204, revoked.text
        token = _token_from(created.json()["invite_url"])
        async with _client(
            tenant_session,
            user=UserContext(user_id="user_revoked", email="revoked@example.com"),
            role=OrgRole.EDITOR,
            directory=directory,
            with_tenant=False,
        ) as invitee:
            denied = await invitee.post(
                "/api/v1/workspace/invites/accept",
                json={"token": token},
            )
    assert denied.status_code == 422, denied.text

    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as admin:
        created = await admin.post(
            "/api/v1/workspace/invites",
            json={"email": "stale@example.com", "role": "viewer"},
        )
    token = _token_from(created.json()["invite_url"])
    stored = (
        (
            await tenant_session.execute(
                select(WorkspaceInvite).where(
                    col(WorkspaceInvite.email) == "stale@example.com"
                )
            )
        )
        .scalars()
        .one()
    )
    stored.expires_at = datetime.now(UTC) - timedelta(days=1)
    tenant_session.add(stored)
    await tenant_session.commit()
    async with _client(
        tenant_session,
        user=UserContext(user_id="user_stale", email="stale@example.com"),
        role=OrgRole.EDITOR,
        directory=directory,
        with_tenant=False,
    ) as invitee:
        expired = await invitee.post(
            "/api/v1/workspace/invites/accept",
            json={"token": token},
        )
    assert expired.status_code == 422, expired.text
    assert directory.added == []


async def test_duplicate_invite_and_seat_cap(tenant_session: AsyncSession) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant, max_members=2)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        first = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "one@example.com", "role": "editor"},
        )
        assert first.status_code == 201, first.text
        again = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "one@example.com", "role": "viewer"},
        )
        assert again.status_code == 422, again.text
        second = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "two@example.com", "role": "viewer"},
        )
    # Admin seat + one pending invite fills a workspace of 2.
    assert second.status_code == 429, second.text


async def test_other_tenant_cannot_see_members_or_invites(
    tenant_session: AsyncSession,
    db_engine,
) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "hidden@example.com", "role": "editor"},
        )
    assert created.status_code == 201, created.text

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as other:
        await set_tenant_context(other, OTHER_TENANT.tenant_id)
        async with _client(
            other,
            user=UserContext(user_id="user_outsider", email="outsider@example.com"),
            role=OrgRole.ADMIN,
            directory=RecordingDirectory(),
            tenant=OTHER_TENANT,
        ) as client:
            snapshot = await client.get("/api/v1/workspace")
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    emails = [item["email"] for item in body["members"]]
    invited = [item["email"] for item in body["invites"]]
    assert ADMIN.email not in emails
    assert "hidden@example.com" not in invited
    assert "invite_url" not in json.dumps(body["invites"])


async def test_role_change_and_last_admin(tenant_session: AsyncSession) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        await client.get("/api/v1/workspace")
        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": EDITOR.email, "role": "editor"},
        )
        token = _token_from(created.json()["invite_url"])
    async with _client(
        tenant_session,
        user=EDITOR,
        role=OrgRole.EDITOR,
        directory=directory,
        with_tenant=False,
    ) as invitee:
        accepted = await invitee.post(
            "/api/v1/workspace/invites/accept",
            json={"token": token},
        )
    assert accepted.status_code == 200, accepted.text

    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        demote_self = await client.patch(
            f"/api/v1/workspace/members/{ADMIN.user_id}",
            json={"role": "viewer"},
        )
        assert demote_self.status_code == 422, demote_self.text
        changed = await client.patch(
            f"/api/v1/workspace/members/{EDITOR.user_id}",
            json={"role": "viewer"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["role"] == "viewer"
        extra = await client.patch(
            f"/api/v1/workspace/members/{EDITOR.user_id}",
            json={"role": "viewer", "email": "nope@example.com"},
        )
    assert extra.status_code == 422, extra.text
    assert directory.updated == [(tenant.tenant_id, EDITOR.user_id, "viewer")]


async def test_remove_member_and_refuse_last_admin(
    tenant_session: AsyncSession,
) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        await client.get("/api/v1/workspace")
        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": EDITOR.email, "role": "editor"},
        )
        token = _token_from(created.json()["invite_url"])
    async with _client(
        tenant_session,
        user=EDITOR,
        role=OrgRole.EDITOR,
        directory=directory,
        with_tenant=False,
    ) as invitee:
        await invitee.post("/api/v1/workspace/invites/accept", json={"token": token})

    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        remove_self = await client.delete(f"/api/v1/workspace/members/{ADMIN.user_id}")
        assert remove_self.status_code == 422, remove_self.text
        removed = await client.delete(f"/api/v1/workspace/members/{EDITOR.user_id}")
    assert removed.status_code == 204, removed.text
    assert directory.removed == [(tenant.tenant_id, EDITOR.user_id)]

    await set_tenant_context(tenant_session, tenant.tenant_id)
    row = (
        (
            await tenant_session.execute(
                select(User).where(col(User.clerk_user_id) == EDITOR.user_id)
            )
        )
        .scalars()
        .one()
    )
    assert row.is_active is False


async def test_accept_fails_closed_without_clerk(tenant_session: AsyncSession) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=ADMIN,
        role=OrgRole.ADMIN,
        directory=directory,
        tenant=tenant,
    ) as client:
        created = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "solo@example.com", "role": "editor"},
        )
    token = _token_from(created.json()["invite_url"])
    async with _client(
        tenant_session,
        user=UserContext(user_id="user_solo", email="solo@example.com"),
        role=OrgRole.EDITOR,
        directory=NullOrgDirectory(),
        with_tenant=False,
    ) as invitee:
        refused = await invitee.post(
            "/api/v1/workspace/invites/accept",
            json={"token": token},
        )
    assert refused.status_code == 422, refused.text
    await set_tenant_context(tenant_session, tenant.tenant_id)
    invite = (
        (
            await tenant_session.execute(
                select(WorkspaceInvite).where(
                    col(WorkspaceInvite.email) == "solo@example.com"
                )
            )
        )
        .scalars()
        .one()
    )
    assert invite.status == "pending"


async def test_viewer_can_read_workspace_but_not_invite(
    tenant_session: AsyncSession,
) -> None:
    tenant = await _bind(tenant_session)
    await _org(tenant_session, tenant)
    directory = RecordingDirectory()
    async with _client(
        tenant_session,
        user=INVITEE,
        role=OrgRole.VIEWER,
        directory=directory,
        tenant=tenant,
    ) as client:
        listed = await client.get("/api/v1/workspace")
        assert listed.status_code == 200, listed.text
        assert listed.json()["caller_role"] == "viewer"
        denied = await client.post(
            "/api/v1/workspace/invites",
            json={"email": "another@example.com", "role": "editor"},
        )
    assert denied.status_code == 403, denied.text
