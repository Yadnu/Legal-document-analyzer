"""Query router — grounded Q&A endpoint.

POST /query  Ask a question about tenant documents; returns a cited answer

             or "not found in your documents."

"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_tenant, get_current_user
from app.db.session import get_rls_db
from app.schemas.auth import TenantContext, UserContext
from app.schemas.query import QueryRequest, QueryResponse
from app.services import qa_service

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def ask_question(
    body: QueryRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_db),
) -> QueryResponse:
    """Retrieve relevant clauses and return a grounded, cited answer."""

    return await qa_service.ask(
        session=session,
        tenant_id=tenant.tenant_id,
        user_id=user.user_id,
        question=body.question,
        document_id=body.document_id,
        conversation_id=body.conversation_id,
    )
