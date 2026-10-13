"""Amazon Textract fallback for scanned PDFs.

Digital PDFs are parsed locally. This module runs only when PyMuPDF finds no
text layer. It starts an async Textract job against the object already stored
in S3, then turns LINE blocks into the same ``ParsedElement`` list the chunker
expects. Document text is never written to logs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from app.core.config import settings
from app.infra.aws import get_textract_client
from app.ingestion.parser import ParsedElement, ParseError, elements_from_lines

log = structlog.get_logger(__name__)

_Sleep = Callable[[float], Awaitable[None]]


class TextractUnavailable(ParseError):
    """A scanned PDF arrived while Textract is turned off."""


def lines_from_blocks(blocks: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Keep Textract LINE blocks, in order, as (page, text) pairs."""
    lines: list[tuple[int, str]] = []
    for block in blocks:
        if block.get("BlockType") != "LINE":
            continue
        text = str(block.get("Text") or "").strip()
        if not text:
            continue
        page = int(block.get("Page") or 1)
        lines.append((page, text))
    return lines


async def read_scanned_pdf(
    s3_key: str,
    *,
    client: Any | None = None,
    sleep: _Sleep = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[ParsedElement]:
    """Read an image-only PDF from S3 and return structured elements.

    ``client`` is injectable so tests never call AWS. When omitted, a real
    Textract client is opened from the shared AWS settings.
    """
    if not settings.textract_enabled:
        raise TextractUnavailable(
            "This PDF has no extractable text. Scanned documents need Textract."
        )

    if client is not None:
        return await _read_with_client(client, s3_key, sleep=sleep, clock=clock)

    async with get_textract_client() as textract:
        return await _read_with_client(textract, s3_key, sleep=sleep, clock=clock)


async def _read_with_client(
    client: Any,
    s3_key: str,
    *,
    sleep: _Sleep,
    clock: Callable[[], float],
) -> list[ParsedElement]:
    started = await client.start_document_text_detection(
        DocumentLocation={
            "S3Object": {
                "Bucket": settings.s3_bucket_name,
                "Name": s3_key,
            }
        }
    )
    job_id = started["JobId"]
    log.info("textract_started", job_id=job_id)

    deadline = clock() + settings.textract_timeout_seconds
    next_token: str | None = None
    blocks: list[dict[str, Any]] = []

    while True:
        if clock() > deadline:
            raise ParseError("Textract timed out reading this scanned PDF.")

        kwargs: dict[str, Any] = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token
        result = await client.get_document_text_detection(**kwargs)
        status = result.get("JobStatus")

        if status == "IN_PROGRESS":
            await sleep(settings.textract_poll_interval_seconds)
            continue
        if status != "SUCCEEDED":
            log.error("textract_failed", job_id=job_id, status=status)
            raise ParseError("Textract could not read this scanned PDF.")

        blocks.extend(result.get("Blocks") or [])
        next_token = result.get("NextToken")
        if not next_token:
            break

    lines = lines_from_blocks(blocks)
    if not lines:
        raise ParseError("Textract returned no text for this scanned PDF.")

    log.info("textract_finished", job_id=job_id, line_count=len(lines))
    return elements_from_lines(lines)
