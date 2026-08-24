"""Query router — grounded Q&A and conversation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_tenant, get_current_user
from app.db.session import get_rls_db
from app.repositories import conversation_repo
from app.schemas.auth import TenantContext, UserContext
from app.schemas.query import ConversationSummary, QueryRequest, QueryResponse
from app.services import qa_service

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def ask_question(
    body: QueryRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_db),
) -> QueryResponse:
    """Retrieve relevant clauses and return a grounded, cited answer.

    Omit ``document_id`` to search across all tenant documents.
    """
    return await qa_service.ask(
        session=session,
        tenant_id=tenant.tenant_id,
        user_id=user.user_id,
        question=body.question,
        document_id=body.document_id,
        conversation_id=body.conversation_id,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_rls_db),
) -> list[ConversationSummary]:
    """Return the 20 most recent workspace-level conversations for the tenant.

    Workspace conversations are those created without a specific document
    (i.e. cross-document Q&A sessions).
    """
    rows = await conversation_repo.list_workspace_conversations(
        session, tenant.tenant_id
    )
    return [
        ConversationSummary(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            message_count=count,
        )
        for conv, count in rows
    ]
