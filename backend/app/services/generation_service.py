"""Grounded answer generation from retrieved clauses.
Uses Bedrock Claude with a strict grounding prompt. When Bedrock is
unavailable, a deterministic local stub is used (dev/CI only).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

import structlog

from app.core.exceptions import AwsError
from app.infra import bedrock
from app.models.chunk import Chunk

log = structlog.get_logger(__name__)
NOT_FOUND_ANSWER = "not found in your documents."
_SYSTEM_PROMPT = """\
You are a legal document comprehension assistant. You help users understand \
their own uploaded documents. You never give legal advice.
Rules:
1. Answer ONLY using the provided clauses. Do not use outside knowledge.
2. Every factual claim must be supported by one of the provided clauses.
3. If the clauses do not contain enough information, respond with exactly:
   not found in your documents.
4. Return ONLY valid JSON with this shape:
   {"answer": "<string>",
    "citations": [{"chunk_id": "<uuid>", "quote": "<short quote>"}]}
5. Citations must only use chunk_id values from the provided clauses.
6. Keep quotes short (one sentence or less) and verbatim from the clause text.
"""


@dataclass(frozen=True, slots=True)
class Citation:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    section: str | None
    quote: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    answer: str
    citations: list[Citation]
    not_found: bool


async def generate_answer(
    question: str,
    chunks: list[Chunk],
) -> GenerationResult:
    """Generate a grounded answer (or the not-found phrase)."""
    if not chunks:
        return GenerationResult(
            answer=NOT_FOUND_ANSWER,
            citations=[],
            not_found=True,
        )
    by_id = {c.id: c for c in chunks}
    user_prompt = _build_user_prompt(question, chunks)
    try:
        raw = await bedrock.converse_text(system=_SYSTEM_PROMPT, user=user_prompt)
        return _parse_model_output(raw, by_id)
    except AwsError:
        log.warning("generation_using_local_stub", reason="bedrock_unavailable")
        return _local_stub(question, chunks)


def _build_user_prompt(question: str, chunks: list[Chunk]) -> str:
    lines = [
        "Clauses:",
    ]
    for chunk in chunks:
        section = chunk.section_number or chunk.heading or "unknown"
        lines.append(f"- chunk_id={chunk.id} section={section}\n  {chunk.content}")
    lines.append("")
    lines.append(f"Question: {question}")
    lines.append("Respond with JSON only.")
    return "\n".join(lines)


def _parse_model_output(
    raw: str,
    by_id: dict[uuid.UUID, Chunk],
) -> GenerationResult:
    payload = _extract_json(raw)
    if payload is None:
        return GenerationResult(
            answer=NOT_FOUND_ANSWER,
            citations=[],
            not_found=True,
        )
    answer = str(payload.get("answer") or "").strip()
    raw_citations = payload.get("citations") or []
    if not isinstance(raw_citations, list):
        raw_citations = []
    citations: list[Citation] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        try:
            chunk_id = uuid.UUID(str(item.get("chunk_id")))
        except (TypeError, ValueError):
            continue
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        quote = str(item.get("quote") or "").strip()
        if not quote:
            quote = chunk.content[:240]
        section = chunk.section_number or chunk.heading
        citations.append(
            Citation(
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                section=section,
                quote=quote,
            )
        )
    not_found_phrase = NOT_FOUND_ANSWER.rstrip(".").lower()
    if not citations or not answer or not_found_phrase in answer.lower():
        return GenerationResult(
            answer=NOT_FOUND_ANSWER,
            citations=[],
            not_found=True,
        )
    return GenerationResult(answer=answer, citations=citations, not_found=False)


def _extract_json(raw: str) -> dict | None:
    text = raw.strip()
    # Strip common markdown fences.
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
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _local_stub(question: str, chunks: list[Chunk]) -> GenerationResult:
    """Deterministic grounded stub for local/CI when Bedrock is unavailable.
    Uses simple token overlap: if the top chunk shares no tokens with the
    question, return not-found; otherwise cite the top chunk.
    """
    q_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    best = chunks[0]
    best_tokens = set(re.findall(r"[a-z0-9]+", best.content.lower()))
    if not q_tokens or not (q_tokens & best_tokens):
        return GenerationResult(
            answer=NOT_FOUND_ANSWER,
            citations=[],
            not_found=True,
        )
    section = best.section_number or best.heading
    quote = best.content[:240]
    answer = f"Based on your documents" f"{f' ({section})' if section else ''}: {quote}"
    return GenerationResult(
        answer=answer,
        citations=[
            Citation(
                document_id=best.document_id,
                chunk_id=best.id,
                section=section,
                quote=quote,
            )
        ],
        not_found=False,
    )
