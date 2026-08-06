"""Structure-aware clause chunker.

Converts a flat list of ``ParsedElement`` objects (from the parser) into
``ChunkData`` objects suitable for embedding and storage.

This module has **zero external dependencies** — no DB, no AWS, no AI — so it
can be unit-tested quickly and in isolation.

Chunking rules
--------------
- Elements are grouped by their heading / section boundary.
- When accumulated word count would exceed ``max_tokens``, the current buffer
  is flushed as a chunk and a new one begins, with ``overlap_tokens`` words
  carried forward to preserve context across boundaries.
- Standalone heading elements are emitted as their own small chunks so they
  are searchable by section title.
- Cross-references are extracted with a regex and stored as a deduplicated
  list on each chunk.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.ingestion.parser import ParsedElement

# ---------------------------------------------------------------------------
# Output data type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChunkData:
    content: str
    section_number: str | None
    heading: str | None
    page: int | None  # page of the first element in this chunk
    cross_refs: list[str]  # JSON-serialisable list of referenced sections
    token_count: int  # word count (tiktoken in Phase 5)


# ---------------------------------------------------------------------------
# Cross-reference extraction
# ---------------------------------------------------------------------------

_XREF_RE = re.compile(
    r"\b(?:"
    r"(?:Section|Article|Clause|Schedule|Exhibit|Appendix|Annex|Part)"
    r"\s+[A-Z\d][A-Z\d.\-]*"  # Section 3.2 / Exhibit B / Schedule 1
    r"|\bclause\s+\d+(?:\.\d+)*"  # clause 4.1
    r")",
    re.IGNORECASE,
)


def _extract_cross_refs(text: str) -> list[str]:
    """Return deduplicated cross-references found in ``text``."""
    found = [m.group(0) for m in _XREF_RE.finditer(text)]
    seen: set[str] = set()
    unique: list[str] = []
    for ref in found:
        # Normalise: lowercase and strip trailing punctuation for dedup key
        key = ref.lower().rstrip(".,;:")
        if key not in seen:
            seen.add(key)
            # Store the version without trailing punctuation for cleanliness
            unique.append(ref.rstrip(".,;:"))
    return unique


# ---------------------------------------------------------------------------
# Token counting (word-based; replace with tiktoken in Phase 5)
# ---------------------------------------------------------------------------


def _word_count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


def chunk_elements(
    elements: list[ParsedElement],
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[ChunkData]:
    """Convert ``ParsedElement`` list to ``ChunkData`` list.

    Parameters
    ----------
    elements:
        Output of ``parse_pdf``.
    max_tokens:
        Maximum word count per chunk before a boundary is forced.
    overlap_tokens:
        Number of words carried from the end of the previous chunk into the
        next one to preserve cross-boundary context.

    Returns
    -------
    list[ChunkData]
        Ordered list of chunks, each associated with a section.
    """
    chunks: list[ChunkData] = []

    # State for the current accumulation window
    buffer_texts: list[str] = []
    buffer_words: int = 0
    current_section: str | None = None
    current_heading: str | None = None
    current_page: int | None = None

    def flush(
        section: str | None,
        heading: str | None,
        page: int | None,
        texts: list[str],
    ) -> None:
        content = " ".join(texts).strip()
        if not content:
            return
        chunks.append(
            ChunkData(
                content=content,
                section_number=section,
                heading=heading,
                page=page,
                cross_refs=_extract_cross_refs(content),
                token_count=_word_count(content),
            )
        )

    def _overlap_words(texts: list[str]) -> list[str]:
        """Return the last ``overlap_tokens`` words as a list of one element."""
        # Cap overlap at half of max_tokens to prevent the carried-over text
        # from immediately exceeding the limit on the very next element.
        effective_overlap = min(overlap_tokens, max_tokens // 2)
        all_words = " ".join(texts).split()
        if len(all_words) > effective_overlap:
            tail = all_words[-effective_overlap:]
        else:
            tail = all_words
        return [" ".join(tail)] if tail else []

    for elem in elements:
        # ── Heading boundary ────────────────────────────────────────────────
        if elem.element_type == "heading":
            # Flush the current buffer before starting the new section
            if buffer_texts:
                flush(current_section, current_heading, current_page, buffer_texts)
                buffer_texts = []
                buffer_words = 0

            # Emit the heading itself as a standalone chunk
            heading_text = elem.text.strip()
            if heading_text:
                chunks.append(
                    ChunkData(
                        content=heading_text,
                        section_number=elem.section_number,
                        heading=heading_text,
                        page=elem.page,
                        cross_refs=[],
                        token_count=_word_count(heading_text),
                    )
                )

            current_section = elem.section_number
            current_heading = elem.heading
            current_page = elem.page
            continue

        # ── Body element ─────────────────────────────────────────────────────
        # If section context changed (section_number changed without a heading
        # element — can happen with inline numbering), flush and reset
        if elem.section_number and elem.section_number != current_section:
            if buffer_texts:
                flush(current_section, current_heading, current_page, buffer_texts)
                buffer_texts = []
                buffer_words = 0
            current_section = elem.section_number
            current_heading = elem.heading
            current_page = current_page or elem.page

        if current_page is None:
            current_page = elem.page

        elem_words = _word_count(elem.text)

        # If this single element already exceeds max_tokens, flush it alone
        if elem_words >= max_tokens:
            if buffer_texts:
                flush(current_section, current_heading, current_page, buffer_texts)
                buffer_texts = []
                buffer_words = 0
            flush(current_section, current_heading, elem.page, [elem.text])
            continue

        # If adding this element would overflow, flush and start new buffer
        # with overlap from previous
        if buffer_words + elem_words > max_tokens and buffer_texts:
            flush(current_section, current_heading, current_page, buffer_texts)
            overlap = _overlap_words(buffer_texts)
            buffer_texts = overlap
            buffer_words = _word_count(" ".join(buffer_texts))
            current_page = elem.page

        buffer_texts.append(elem.text)
        buffer_words += elem_words

    # Final flush
    if buffer_texts:
        flush(current_section, current_heading, current_page, buffer_texts)

    return chunks


def chunks_to_texts(chunks: list[ChunkData]) -> list[str]:
    """Extract the plain ``content`` string from each chunk for embedding."""
    return [c.content for c in chunks]


def cross_refs_to_json(refs: list[str]) -> str | None:
    """Serialise cross-refs list to JSON string for DB storage; None if empty."""
    return json.dumps(refs) if refs else None
