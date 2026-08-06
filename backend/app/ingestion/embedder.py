"""Embedding function.

Provides a single ``embed_texts`` coroutine used for BOTH document chunks
(ingestion time) and queries (retrieval time).  Using the same function in
both paths guarantees the vectors are comparable.

Provider selection
------------------
1. **Voyage AI** — when ``settings.voyage_api_key`` is non-empty.
   Model: ``settings.embedding_model`` (default: ``voyage-law-2``).
   Dimension: 1024.

2. **Local fallback** — when no API key is configured.
   Generates deterministic unit-sphere vectors by hashing each text with
   SHA-256 and mapping the bytes to ``[-1, 1]`` floats, then L2-normalising.
   **Use only for local development and CI.**  These vectors are spatially
   meaningless for semantic retrieval.

The model name and version stored with each ``Chunk`` row must come from
``settings.embedding_model`` and ``settings.embedding_model_version``
so the retrieval service can enforce model consistency.
"""

from __future__ import annotations

import hashlib
import math

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_VOYAGE_BATCH = 128  # max texts per Voyage request


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per text string.

    The order of the returned list matches the order of ``texts``.
    Raises ``RuntimeError`` on provider errors (caller should let the worker
    mark the document as failed and retry).
    """
    if not texts:
        return []

    if settings.voyage_api_key:
        return await _voyage_embed(texts)

    log.warning(
        "embedder_using_local_fallback",
        reason="VOYAGE_API_KEY not set",
        text_count=len(texts),
    )
    return _local_fallback(texts, settings.embedding_dimensions)


# ---------------------------------------------------------------------------
# Voyage AI provider
# ---------------------------------------------------------------------------


async def _voyage_embed(texts: list[str]) -> list[list[float]]:
    """Call the Voyage AI embeddings endpoint in batches of _VOYAGE_BATCH."""
    all_vectors: list[list[float]] = []

    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(texts), _VOYAGE_BATCH):
            batch = texts[i : i + _VOYAGE_BATCH]
            response = await client.post(
                _VOYAGE_URL,
                headers={
                    "Authorization": f"Bearer {settings.voyage_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.embedding_model,
                    "input": batch,
                    "input_type": "document",
                },
            )
            if response.status_code != 200:
                log.error(
                    "voyage_embed_failed",
                    status=response.status_code,
                    batch_start=i,
                )
                raise RuntimeError(
                    f"Voyage AI embedding failed: HTTP {response.status_code}"
                )

            data = response.json()
            vectors = [item["embedding"] for item in data["data"]]
            all_vectors.extend(vectors)
            log.info(
                "voyage_embed_batch_ok",
                batch_start=i,
                batch_size=len(batch),
            )

    return all_vectors


# ---------------------------------------------------------------------------
# Local deterministic fallback
# ---------------------------------------------------------------------------


def _local_fallback(texts: list[str], dimensions: int) -> list[list[float]]:
    """Generate deterministic pseudo-embeddings for dev/CI use only.

    Each text is hashed with SHA-256; the digest bytes are repeated/truncated
    to fill ``dimensions`` floats in ``[-1, 1]``, then L2-normalised so
    cosine similarity still produces values in ``[-1, 1]``.
    """
    results: list[list[float]] = []
    for text in texts:
        digest = hashlib.sha256(text.encode()).digest()
        # Repeat digest bytes to cover all dimensions
        repeated = (digest * (dimensions // len(digest) + 1))[:dimensions]
        # Map byte value 0-255 → float -1.0 to 1.0
        raw = [(b / 127.5) - 1.0 for b in repeated]
        # L2 normalise
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        results.append([x / norm for x in raw])
    return results
