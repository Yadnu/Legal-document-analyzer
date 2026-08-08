"""Unit tests for the chunker module.

These tests are pure — no database, no network, no AWS.
Only ``app.ingestion.chunker`` and ``app.ingestion.parser.ParsedElement``
are imported.
"""

from __future__ import annotations

import re

from app.ingestion.chunker import chunk_elements
from app.ingestion.parser import ParsedElement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _elem(
    text: str,
    page: int = 1,
    element_type: str = "narrative",
    section_number: str | None = None,
    heading: str | None = None,
) -> ParsedElement:
    return ParsedElement(
        text=text,
        element_type=element_type,
        page=page,
        section_number=section_number,
        heading=heading,
    )


def _heading(text: str, section: str | None = None, page: int = 1) -> ParsedElement:
    return ParsedElement(
        text=text,
        element_type="heading",
        page=page,
        section_number=section,
        heading=text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chunk_simple_narrative() -> None:
    """A handful of narrative elements produce at least one chunk."""
    elements = [
        _elem("The parties agree to the following terms."),
        _elem("Payment shall be made within thirty days."),
        _elem("Any disputes shall be resolved by arbitration."),
    ]
    chunks = chunk_elements(elements)
    assert len(chunks) >= 1
    combined = " ".join(c.content for c in chunks)
    assert "parties agree" in combined
    assert "arbitration" in combined


def test_chunk_respects_max_tokens() -> None:
    """No chunk content exceeds max_tokens words."""
    words_per_elem = 20
    word = "contract"
    many_elements = [_elem(" ".join([word] * words_per_elem)) for _ in range(30)]
    max_tokens = 50
    chunks = chunk_elements(many_elements, max_tokens=max_tokens)
    for chunk in chunks:
        assert (
            chunk.token_count <= max_tokens + words_per_elem
        ), f"Chunk exceeds max: {chunk.token_count} words"


def test_chunk_preserves_section_metadata() -> None:
    """Section number and heading are propagated into body chunks."""
    elements = [
        _heading("3.2 Payment Terms", section="3.2"),
        _elem(
            "Invoices shall be payable within thirty days.",
            section_number="3.2",
            heading="3.2 Payment Terms",
        ),
        _elem(
            "Late payments accrue interest at five percent per annum.",
            section_number="3.2",
            heading="3.2 Payment Terms",
        ),
    ]
    chunks = chunk_elements(elements)

    # Find the body chunk (not the heading standalone chunk)
    body_chunks = [c for c in chunks if "Invoices" in c.content or "Late" in c.content]
    assert body_chunks, "Expected at least one body chunk"
    for chunk in body_chunks:
        assert (
            chunk.section_number == "3.2"
        ), f"Expected section 3.2, got {chunk.section_number}"
        assert (
            chunk.heading == "3.2 Payment Terms"
        ), f"Unexpected heading: {chunk.heading}"


def test_chunk_extracts_cross_refs() -> None:
    """Cross-references to other sections are extracted into cross_refs."""
    elements = [
        _elem(
            "Subject to the provisions of Section 3.2 and Exhibit B, "
            "the Licensor grants the rights described in Schedule 1."
        ),
    ]
    chunks = chunk_elements(elements)
    assert chunks
    refs = chunks[0].cross_refs
    # At least Section 3.2, Exhibit B, Schedule 1 should be found
    refs_lower = [r.lower() for r in refs]
    assert any("section 3.2" in r for r in refs_lower), f"refs={refs}"
    assert any("exhibit b" in r for r in refs_lower), f"refs={refs}"
    assert any("schedule 1" in r for r in refs_lower), f"refs={refs}"


def test_chunk_idempotent() -> None:
    """Calling chunk_elements twice with the same input yields the same result."""
    elements = [
        _heading("Article I Definitions", section="Article I"),
        _elem("'Agreement' means this Service Agreement.", section_number="Article I"),
        _heading("Article II Obligations", section="Article II"),
        _elem("The Supplier shall deliver on time.", section_number="Article II"),
    ]
    chunks_a = chunk_elements(elements)
    chunks_b = chunk_elements(elements)
    assert len(chunks_a) == len(chunks_b)
    for a, b in zip(chunks_a, chunks_b, strict=True):
        assert a.content == b.content
        assert a.section_number == b.section_number
        assert a.cross_refs == b.cross_refs


def test_chunk_heading_becomes_standalone() -> None:
    """A heading element produces its own chunk."""
    elements = [
        _heading("4. Confidentiality", section="4"),
    ]
    chunks = chunk_elements(elements)
    assert any("Confidentiality" in c.content for c in chunks)


def test_chunk_empty_input() -> None:
    """Empty element list returns empty chunk list."""
    assert chunk_elements([]) == []


def test_chunk_cross_refs_deduplicated() -> None:
    """Repeated references to the same section appear only once."""
    text = (
        "See Section 5.1. As provided in Section 5.1, the party must comply. "
        "Refer to Section 5.1 for further details."
    )
    elements = [_elem(text)]
    chunks = chunk_elements(elements)
    assert chunks
    refs = chunks[0].cross_refs
    count_5_1 = sum(1 for r in refs if re.search(r"5\.1", r, re.IGNORECASE))
    assert count_5_1 == 1, f"Expected deduplicated ref, got: {refs}"
