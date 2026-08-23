"""Cross-reference resolution service — Phase 8.

Loads the cross_refs JSON from a chunk and resolves each raw reference string
to the best-matching target chunk in the same document using section_number
and heading metadata (no AI call required).
"""

from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import chunk_repo
from app.repositories.chunk_repo import _normalise_ref
from app.schemas.cross_ref import ChunkRefsResponse, ResolvedRefOut

log = structlog.get_logger(__name__)

_SNIPPET_LEN = 400


async def get_resolved_refs(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
) -> ChunkRefsResponse:
    """Resolve all cross-references stored on a chunk.

    Raises
    ------
    NotFoundError
        If the chunk does not exist for this tenant + document.
    """
    chunk = await chunk_repo.get_by_id(session, tenant_id, chunk_id)
    if chunk is None or chunk.document_id != document_id:
        raise NotFoundError(f"Chunk {chunk_id} not found in document {document_id}.")

    # Deserialise cross_refs JSON (stored as text, e.g. '["Section 2.1", "Exhibit B"]')
    raw_refs: list[str] = []
    if chunk.cross_refs:
        try:
            parsed = json.loads(chunk.cross_refs)
            if isinstance(parsed, list):
                raw_refs = [str(r) for r in parsed if r]
        except (json.JSONDecodeError, TypeError):
            raw_refs = []

    if not raw_refs:
        return ChunkRefsResponse(
            chunk_id=chunk_id,
            document_id=document_id,
            refs=[],
        )

    resolved_map = await chunk_repo.resolve_refs(
        session, tenant_id, document_id, raw_refs
    )

    out: list[ResolvedRefOut] = []
    for raw in raw_refs:
        target = resolved_map.get(raw)
        if target is not None:
            snippet = target.content[:_SNIPPET_LEN] if target.content else None
            if snippet and len(target.content) > _SNIPPET_LEN:
                snippet += "…"
            out.append(
                ResolvedRefOut(
                    raw=raw,
                    normalised=_normalise_ref(raw),
                    target_chunk_id=target.id,
                    target_section=target.section_number,
                    target_heading=target.heading,
                    target_page=target.page,
                    target_content=snippet,
                )
            )
        else:
            out.append(
                ResolvedRefOut(
                    raw=raw,
                    normalised=_normalise_ref(raw),
                )
            )

    log.info(
        "cross_ref_resolved",
        chunk_id=str(chunk_id),
        total=len(out),
        resolved=sum(1 for r in out if r.target_chunk_id),
    )
    return ChunkRefsResponse(
        chunk_id=chunk_id,
        document_id=document_id,
        refs=out,
    )
