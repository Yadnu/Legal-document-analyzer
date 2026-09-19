"""Obligation extraction and CRUD service — Phase 10A.

Extracts contractual obligations and deadlines from a document using a single
Bedrock call over the document's chunks, then persists them in the obligations
table.  Also provides thin CRUD wrappers used by the API layer.
"""

from __future__ import annotations

import json
import re
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AwsError, NotFoundError, ValidationError
from app.infra import bedrock
from app.models.document import DocumentStatus
from app.repositories import document_repo, obligation_repo
from app.schemas.obligation import ObligationCreate, ObligationOut, ObligationPatch
from app.services import audit_service
from app.services.retrieval_service import retrieve

log = structlog.get_logger(__name__)

# Broad query that surfaces clauses likely to contain obligations/deadlines.
_RETRIEVAL_QUERY = (
    "payment deadline notice termination renewal obligation due date "
    "effective date liability warranty indemnification"
)

_SYSTEM_PROMPT = """\
You are a legal document analysis assistant. Identify every contractual
obligation or deadline in the provided clauses. You never give legal advice.

Rules:
1. Use ONLY the provided clauses. Do not use outside knowledge.
2. Set chunk_id to one of the provided chunk IDs that contains the obligation.
3. Set deadline to an ISO-8601 date (YYYY-MM-DD) if explicitly stated; \
   otherwise null.
4. obligation_type must be one of: payment, notice, renewal, termination, other.
5. Return ONLY a valid JSON array — no markdown, no commentary:
[
  {
    "description": "<one-sentence description of the obligation>",
    "obligation_type": "<type>",
    "deadline": "<YYYY-MM-DD or null>",
    "reminder_days_before": <integer, default 7>,
    "chunk_id": "<chunk UUID>"
  }
]
Return an empty array [] if no obligations are found.
"""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


async def extract_for_document(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    user_id: str = "system",
) -> list[ObligationOut]:
    """Extract obligations from a document using Bedrock (or local stub in CI).

    Existing obligations for the document are **replaced** on each call so
    a re-extraction always reflects the latest chunked content.

    Returns the freshly extracted ObligationOut list.
    """
    # ── 1. Verify document ────────────────────────────────────────────────────
    doc = await document_repo.get_by_id(session, tenant_id, document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found.")
    if doc.status != DocumentStatus.READY:
        raise ValidationError(
            f"Document is not ready for obligation extraction "
            f"(status: {doc.status})."
        )

    # ── 2. Retrieve relevant chunks ───────────────────────────────────────────
    chunks = await retrieve(
        session,
        tenant_id,
        _RETRIEVAL_QUERY,
        document_id=document_id,
    )
    valid_chunk_ids = {str(c.id) for c in chunks}

    # ── 3. Extract (Bedrock or local stub) ────────────────────────────────────
    try:
        raw = await bedrock.converse_text(
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(chunks),
            max_tokens=2048,
            temperature=0.0,
        )
        items = _parse_response(raw, valid_chunk_ids)
    except AwsError:
        log.warning("obligation_extraction_stub", reason="bedrock_unavailable")
        items = _local_stub(chunks)

    # ── 4. Replace existing obligations for this document ────────────────────
    existing = await obligation_repo.list_for_document(
        session, tenant_id, document_id, include_resolved=True
    )
    for old in existing:
        await session.delete(old)
    await session.flush()

    # ── 5. Insert new obligations ─────────────────────────────────────────────
    creates = [
        ObligationCreate(
            document_id=document_id,
            chunk_id=uuid.UUID(item["chunk_id"]) if item.get("chunk_id") else None,
            description=item["description"],
            obligation_type=item.get("obligation_type"),
            deadline=item.get("deadline"),
            reminder_days_before=int(item.get("reminder_days_before") or 7),
        )
        for item in items
    ]
    obligations = (
        await obligation_repo.create_batch(session, tenant_id, creates)
        if creates
        else []
    )

    # ── 6. Audit + commit ─────────────────────────────────────────────────────
    await audit_service.log(
        session,
        tenant_id,
        user_id,
        "obligation.extracted",
        resource_type="document",
        resource_id=document_id,
        metadata={"count": len(obligations)},
    )
    await session.commit()

    log.info(
        "obligation_extraction_done",
        document_id=str(document_id),
        count=len(obligations),
    )
    return [ObligationOut.model_validate(o) for o in obligations]


# ---------------------------------------------------------------------------
# CRUD helpers (thin — delegates to repo + commits)
# ---------------------------------------------------------------------------


async def list_for_document(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    *,
    include_resolved: bool = True,
) -> list[ObligationOut]:
    """Return all obligations for a document."""
    doc = await document_repo.get_by_id(session, tenant_id, document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found.")
    rows = await obligation_repo.list_for_document(
        session, tenant_id, document_id, include_resolved=include_resolved
    )
    return [ObligationOut.model_validate(r) for r in rows]


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: str,
    *,
    include_resolved: bool = False,
    obligation_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ObligationOut], int]:
    """Return paginated obligations across all tenant documents."""
    rows, total = await obligation_repo.list_for_tenant(
        session,
        tenant_id,
        include_resolved=include_resolved,
        obligation_type=obligation_type,
        limit=limit,
        offset=offset,
    )
    return [ObligationOut.model_validate(r) for r in rows], total


async def update(
    session: AsyncSession,
    tenant_id: str,
    obligation_id: uuid.UUID,
    data: ObligationPatch,
) -> ObligationOut:
    """Apply a partial update to an obligation."""
    row = await obligation_repo.patch(session, tenant_id, obligation_id, data)
    if row is None:
        raise NotFoundError(f"Obligation {obligation_id} not found.")
    await session.commit()
    return ObligationOut.model_validate(row)


async def resolve(
    session: AsyncSession,
    tenant_id: str,
    obligation_id: uuid.UUID,
    user_id: str,
) -> ObligationOut:
    """Mark an obligation as resolved and append an audit event."""
    row = await obligation_repo.mark_resolved(session, tenant_id, obligation_id)
    if row is None:
        raise NotFoundError(f"Obligation {obligation_id} not found.")
    await audit_service.log(
        session,
        tenant_id,
        user_id,
        "obligation.resolved",
        resource_type="obligation",
        resource_id=obligation_id,
    )
    await session.commit()
    return ObligationOut.model_validate(row)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_user_prompt(chunks) -> str:  # type: ignore[type-arg]
    lines = ["Clauses:"]
    for chunk in chunks:
        section = chunk.section_number or chunk.heading or "unknown"
        lines.append(f"- chunk_id={chunk.id} section={section}\n  {chunk.content}")
    lines.append("\nIdentify all obligations. Return JSON array only.")
    return "\n".join(lines)


def _parse_response(raw: str, valid_chunk_ids: set[str]) -> list[dict]:
    """Parse the Bedrock JSON array; silently drop malformed entries."""
    text = raw.strip()

    # Strip optional markdown fence
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    results: list[dict] = []
    allowed_types = {"payment", "notice", "renewal", "termination", "other"}
    for item in data:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        if chunk_id not in valid_chunk_ids:
            chunk_id = next(iter(valid_chunk_ids), "") if valid_chunk_ids else ""
        obligation_type = str(item.get("obligation_type") or "other").lower()
        if obligation_type not in allowed_types:
            obligation_type = "other"
        # Validate deadline format
        deadline = item.get("deadline")
        if deadline:
            try:
                # Accept YYYY-MM-DD; store as string for ObligationCreate parsing
                parts = str(deadline).split("-")
                if len(parts) != 3 or not all(p.isdigit() for p in parts):
                    deadline = None
            except Exception:
                deadline = None
        results.append(
            {
                "description": description,
                "obligation_type": obligation_type,
                "deadline": deadline,
                "reminder_days_before": int(item.get("reminder_days_before") or 7),
                "chunk_id": chunk_id or None,
            }
        )
    return results


def _local_stub(chunks) -> list[dict]:  # type: ignore[type-arg]
    """Deterministic fallback when Bedrock is unavailable (dev / CI).

    Produces one obligation per top chunk mentioning a keyword.
    """
    keywords = {"payment", "notice", "terminat", "renew", "deadline", "due"}
    results: list[dict] = []
    for chunk in chunks[:4]:
        content_lower = chunk.content.lower()
        matched = next((k for k in keywords if k in content_lower), None)
        if matched is None:
            continue
        obl_type = (
            "payment"
            if "payment" in content_lower
            else (
                "termination"
                if "terminat" in content_lower
                else (
                    "notice"
                    if "notice" in content_lower
                    else "renewal" if "renew" in content_lower else "other"
                )
            )
        )
        results.append(
            {
                "description": chunk.content[:120].strip(),
                "obligation_type": obl_type,
                "deadline": None,
                "reminder_days_before": 7,
                "chunk_id": str(chunk.id),
            }
        )
    return results
