"""Clause comments router.

Routes
------
GET    /documents/{doc_id}/chunks/{chunk_id}/comments
POST   /documents/{doc_id}/chunks/{chunk_id}/comments
PATCH  /comments/{comment_id}
DELETE /comments/{comment_id}

Authorization rules (enforced here, not in the DB):
  - Any authenticated org member can GET and POST.
  - PATCH and DELETE require either:
      a) the caller is the comment author (user_id matches), OR
      b) the caller holds the org:admin role.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_tenant, get_current_user, get_verified_claims
from app.core.exceptions import NotFoundError
from app.db.session import get_rls_db
from app.repositories import comment_repo
from app.repositories.document_repo import get_by_id as get_document
from app.schemas.auth import TenantContext, UserContext
from app.schemas.comment import (
    CommentCreate,
    CommentListResponse,
    CommentOut,
    CommentPatch,
)
from app.services import audit_service

router = APIRouter(tags=["comments"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_admin(claims: dict) -> bool:
    role: str = claims.get("org_role", "")
    return role in ("org:admin", "admin")


async def _require_author_or_admin(
    tenant_id: str,
    comment_id: uuid.UUID,
    user_id: str,
    claims: dict,
    session: AsyncSession,
) -> None:
    """Raise 403 if the caller is neither the author nor an admin."""
    comment = await comment_repo.get(session, tenant_id, comment_id)
    if comment is None:
        raise NotFoundError(f"Comment {comment_id} not found.")
    if comment.user_id != user_id and not _is_admin(claims):
        raise HTTPException(
            status_code=403,
            detail="Only the comment author or an org admin can perform this action.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{doc_id}/chunks/{chunk_id}/comments",
    response_model=CommentListResponse,
)
async def list_comments(
    doc_id: uuid.UUID,
    chunk_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> CommentListResponse:
    """Return all comments for a specific chunk, oldest first."""
    # Verify the document belongs to this tenant (raises 404 otherwise).
    doc = await get_document(session, tenant.tenant_id, doc_id)
    if doc is None:
        raise NotFoundError(f"Document {doc_id} not found.")

    items = await comment_repo.list_for_chunk(
        session, tenant.tenant_id, doc_id, chunk_id
    )
    return CommentListResponse(items=[CommentOut.model_validate(c) for c in items])


@router.post(
    "/documents/{doc_id}/chunks/{chunk_id}/comments",
    response_model=CommentOut,
    status_code=201,
)
async def create_comment(
    doc_id: uuid.UUID,
    chunk_id: uuid.UUID,
    body: CommentCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_db),
) -> CommentOut:
    """Post a new comment on a clause."""
    doc = await get_document(session, tenant.tenant_id, doc_id)
    if doc is None:
        raise NotFoundError(f"Document {doc_id} not found.")

    comment = await comment_repo.create(
        session,
        tenant.tenant_id,
        document_id=doc_id,
        chunk_id=chunk_id,
        user_id=user.user_id,
        body=body.body,
    )

    await audit_service.log(
        session,
        tenant.tenant_id,
        user.user_id,
        "comment.created",
        resource_type="clause_comment",
        resource_id=comment.id,
        metadata={"document_id": str(doc_id), "chunk_id": str(chunk_id)},
    )
    await session.commit()

    return CommentOut.model_validate(comment)


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def patch_comment(
    comment_id: uuid.UUID,
    body: CommentPatch,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    claims: dict = Depends(get_verified_claims),
    session: AsyncSession = Depends(get_rls_db),
) -> CommentOut:
    """Edit the body or resolve/unresolve a comment.

    Requires the caller to be the comment author **or** an org admin.
    """
    await _require_author_or_admin(
        tenant.tenant_id, comment_id, user.user_id, claims, session
    )

    updated = None
    if body.body is not None:
        updated = await comment_repo.update_body(
            session, tenant.tenant_id, comment_id, body.body
        )
    if body.is_resolved is not None:
        updated = await comment_repo.set_resolved(
            session, tenant.tenant_id, comment_id, resolved=body.is_resolved
        )

    if updated is None:
        # Both fields were None — no-op, just return the existing comment.
        existing = await comment_repo.get(session, tenant.tenant_id, comment_id)
        if existing is None:
            raise NotFoundError(f"Comment {comment_id} not found.")
        updated = existing

    await session.commit()
    return CommentOut.model_validate(updated)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    claims: dict = Depends(get_verified_claims),
    session: AsyncSession = Depends(get_rls_db),
) -> None:
    """Hard-delete a comment. Author or admin only."""
    await _require_author_or_admin(
        tenant.tenant_id, comment_id, user.user_id, claims, session
    )

    deleted = await comment_repo.delete(session, tenant.tenant_id, comment_id)
    if not deleted:
        raise NotFoundError(f"Comment {comment_id} not found.")

    await audit_service.log(
        session,
        tenant.tenant_id,
        user.user_id,
        "comment.deleted",
        resource_type="clause_comment",
        resource_id=comment_id,
    )
    await session.commit()
