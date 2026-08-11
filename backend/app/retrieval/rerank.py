"""Reranking of retrieved chunks.
Provider selection
------------------
1. **Cohere Rerank** — when ``settings.cohere_api_key`` is set.
2. **Local lexical fallback** — token-overlap score (dev/CI only).
"""

from __future__ import annotations

import re

import httpx
import structlog

from app.core.config import settings
from app.models.chunk import Chunk

log = structlog.get_logger(__name__)
_COHERE_URL = "https://api.cohere.com/v2/rerank"
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


async def rerank(
    query: str,
    candidates: list[Chunk],
    *,
    top_n: int,
) -> list[Chunk]:
    """Return up to ``top_n`` chunks ordered by relevance to ``query``."""
    if not candidates or top_n <= 0:
        return []
    top_n = min(top_n, len(candidates))
    if settings.cohere_api_key:
        try:
            return await _cohere_rerank(query, candidates, top_n=top_n)
        except Exception as exc:
            log.error("cohere_rerank_failed", error=str(exc))
            # Fall through to local so a transient Cohere outage does not
            # fail the whole Q&A request.
    return _local_rerank(query, candidates, top_n=top_n)


async def _cohere_rerank(
    query: str,
    candidates: list[Chunk],
    *,
    top_n: int,
) -> list[Chunk]:
    documents = [c.content for c in candidates]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            _COHERE_URL,
            headers={
                "Authorization": f"Bearer {settings.cohere_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.cohere_rerank_model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"Cohere rerank failed: HTTP {response.status_code}")
    data = response.json()
    results = data.get("results") or []
    ordered: list[Chunk] = []
    for item in results:
        idx = int(item["index"])
        if 0 <= idx < len(candidates):
            ordered.append(candidates[idx])
    log.info("cohere_rerank_ok", candidate_count=len(candidates), top_n=top_n)
    return ordered[:top_n]


def _local_rerank(query: str, candidates: list[Chunk], *, top_n: int) -> list[Chunk]:
    """Deterministic lexical overlap score for local/CI use."""
    query_tokens = set(_TOKEN_RE.findall(query.lower()))
    if not query_tokens:
        return candidates[:top_n]

    def score(chunk: Chunk) -> float:
        content_tokens = set(_TOKEN_RE.findall(chunk.content.lower()))
        if not content_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / len(query_tokens)

    ranked = sorted(candidates, key=score, reverse=True)
    log.info(
        "local_rerank_ok",
        candidate_count=len(candidates),
        top_n=top_n,
    )
    return ranked[:top_n]
