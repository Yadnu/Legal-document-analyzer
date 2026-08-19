"""Structured clause extraction — Phase 7.

Extracts seven structured fields from a document using a single Bedrock call
over the top retrieved chunks, then caches the result in document_summary_cards.

Cache policy: results older than CACHE_TTL_HOURS are re-extracted on the next
GET /documents/{id}/summary request.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AwsError, NotFoundError, ValidationError
from app.infra import bedrock
from app.models.document import DocumentStatus
from app.models.summary import DocumentSummaryCard
from app.repositories import document_repo, summary_repo
from app.services.retrieval_service import retrieve

log = structlog.get_logger(__name__)

CACHE_TTL_HOURS = 24

# Broad query that surfaces relevant chunks for all seven fields in one retrieval call.
_RETRIEVAL_QUERY = (
    "parties effective date term length payment termination liability governing law"
)

_SYSTEM_PROMPT = """\
You are a legal document comprehension assistant. Extract the following \
structured fields from the provided clauses. You never give legal advice.

Rules:
1. Use ONLY the provided clauses. Do not use outside knowledge.
2. For each field set chunk_id to one of the provided chunk IDs that supports \
the value. If no clause supports a field, set the entire field to null.
3. Keep "quote" short (one sentence or less), verbatim from the clause.
4. Return ONLY valid JSON with exactly this shape — no markdown, no commentary:
{
  "parties":            {"value": "...", "chunk_id": "...", "quote": "..."} | null,
  "effective_date":     {"value": "...", "chunk_id": "...", "quote": "..."} | null,
  "term_length":        {"value": "...", "chunk_id": "...", "quote": "..."} | null,
  "payment_terms":      {"value": "...", "chunk_id": "...", "quote": "..."} | null,
  "termination_rights": {"value": "...", "chunk_id": "...", "quote": "..."} | null,
  "liability_caps":     {"value": "...", "chunk_id": "...", "quote": "..."} | null,
  "governing_law":      {"value": "...", "chunk_id": "...", "quote": "..."} | null
}
"""

_FIELD_NAMES = (
    "parties",
    "effective_date",
    "term_length",
    "payment_terms",
    "termination_rights",
    "liability_caps",
    "governing_law",
)


async def get_or_extract(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
) -> DocumentSummaryCard:
    """Return a cached summary card, or run extraction if missing / stale."""

    # ── 1. Verify the document exists and is ready ────────────────────────────
    doc = await document_repo.get_by_id(session, tenant_id, document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found.")
    if doc.status != DocumentStatus.READY:
        raise ValidationError(
            f"Document is not ready for extraction (status: {doc.status})."
        )

    # ── 2. Return cached card if still fresh ──────────────────────────────────
    card = await summary_repo.get_for_document(session, tenant_id, document_id)
    if card is not None:
        age = datetime.now(UTC) - card.extracted_at.replace(tzinfo=UTC)
        if age < timedelta(hours=CACHE_TTL_HOURS):
            log.info(
                "extraction_cache_hit",
                document_id=str(document_id),
                age_hours=round(age.total_seconds() / 3600, 1),
            )
            return card

    # ── 3. Retrieve relevant chunks ───────────────────────────────────────────
    chunks = await retrieve(
        session,
        tenant_id,
        _RETRIEVAL_QUERY,
        document_id=document_id,
    )

    # ── 4. Extract (Bedrock or local stub) ────────────────────────────────────
    valid_ids = {str(c.id) for c in chunks}
    try:
        raw = await bedrock.converse_text(
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(chunks),
            max_tokens=1024,
            temperature=0.0,
        )
        fields = _parse_response(raw, valid_ids, chunks)
    except AwsError:
        log.warning("extraction_using_local_stub", reason="bedrock_unavailable")
        fields = _local_stub(chunks)

    # ── 5. Enrich each field with section metadata ────────────────────────────
    chunk_by_id = {str(c.id): c for c in chunks}
    for _key, val in fields.items():
        if val and val.get("chunk_id") in chunk_by_id:
            c = chunk_by_id[val["chunk_id"]]
            val["section"] = c.section_number or c.heading
        elif val:
            val["section"] = None

    # ── 6. Persist and return ─────────────────────────────────────────────────
    card = await summary_repo.upsert(
        session, tenant_id, document_id, fields
    )
    await session.commit()

    log.info(
        "extraction_complete",
        document_id=str(document_id),
        fields_found=sum(1 for v in fields.values() if v),
    )
    return card


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_user_prompt(chunks) -> str:  # type: ignore[type-arg]
    lines = ["Clauses:"]
    for chunk in chunks:
        section = chunk.section_number or chunk.heading or "unknown"
        lines.append(f"- chunk_id={chunk.id} section={section}\n  {chunk.content}")
    lines.append("\nExtract the seven fields. Return JSON only.")
    return "\n".join(lines)


def _parse_response(
    raw: str,
    valid_ids: set[str],
    chunks,  # type: ignore[type-arg]
) -> dict:
    payload = _extract_json(raw)
    if payload is None:
        return {f: None for f in _FIELD_NAMES}

    result: dict = {}
    for field in _FIELD_NAMES:
        entry = payload.get(field)
        if not isinstance(entry, dict):
            result[field] = None
            continue
        chunk_id = str(entry.get("chunk_id") or "").strip()
        value = str(entry.get("value") or "").strip()
        quote = str(entry.get("quote") or "").strip()
        if not value or chunk_id not in valid_ids:
            result[field] = None
        else:
            result[field] = {
                "value": value,
                "chunk_id": chunk_id,
                "quote": quote or None,
                "section": None,  # enriched in caller
            }
    return result


def _extract_json(raw: str) -> dict | None:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _local_stub(chunks) -> dict:  # type: ignore[type-arg]
    """Deterministic fallback when Bedrock is unavailable (dev / CI).

    Cites the top chunk for every field so tests can verify the response
    shape without a live Bedrock connection.
    """
    if not chunks:
        return {f: None for f in _FIELD_NAMES}
    top = chunks[0]
    stub_entry = {
        "value": "See document",
        "chunk_id": str(top.id),
        "quote": top.content[:120],
        "section": None,
    }
    return {f: dict(stub_entry) for f in _FIELD_NAMES}
