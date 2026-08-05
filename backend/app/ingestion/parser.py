"""PDF parser — converts raw PDF bytes into structured ``ParsedElement`` objects.

Uses PyMuPDF (``fitz``) for fast, reliable text extraction from digital PDFs.
Scanned documents (image-only PDFs) are detected and raise ``ParseError`` so
the caller can route them to Amazon Textract (Phase 5+).

The module is a **pure function** — no I/O, no external dependencies beyond
PyMuPDF.  This makes it straightforward to unit-test with fixture bytes.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

import fitz  # PyMuPDF


class ParseError(Exception):
    """Raised when the document cannot be parsed (e.g. scanned, encrypted)."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedElement:
    """A single structural element extracted from a PDF page."""

    text: str
    element_type: str  # "heading" | "narrative" | "list_item" | "table"
    page: int  # 1-indexed
    section_number: str | None  # e.g. "3.2", "Article IV"
    heading: str | None  # nearest heading text above this element


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Matches leading section numbers like "1.", "2.3", "10.2.1", "Article IV",
# "ARTICLE III", "Section 3", "SECTION 2.1"
_SECTION_RE = re.compile(
    r"^(?:"
    r"(?:article|section)\s+[IVXLCDM\d][\w.]*"  # Article IV / Section 3.2
    r"|[A-Z][A-Z\s]{2,20}"  # ALL-CAPS headings (DEFINITIONS, PAYMENT TERMS)
    r"|\d+(?:\.\d+){0,3}\.?\s"  # 1. / 2.3 / 10.2.1
    r")",
    re.IGNORECASE,
)

_LIST_RE = re.compile(r"^\s*(?:[•\-\*]|\([a-z]\)|\d+\))\s")


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


def parse_pdf(data: bytes) -> list[ParsedElement]:
    """Parse a PDF into a flat list of ``ParsedElement`` objects.

    Algorithm
    ---------
    1. Open the PDF with PyMuPDF.
    2. Collect all text blocks with their font sizes and bounding boxes.
    3. Compute the median body font size; treat blocks with size ≥ 1.2× median
       as headings.
    4. Tag each block as heading / list_item / narrative.
    5. Propagate the nearest heading and parsed section_number downward.

    Raises ``ParseError`` if the document is encrypted, has no extractable
    text (likely scanned), or is otherwise unreadable.
    """
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError(f"Cannot open PDF: {exc}") from exc

    if doc.is_encrypted:
        raise ParseError("PDF is encrypted and cannot be parsed.")

    # ── Collect all text spans across all pages ──────────────────────────────
    raw_blocks: list[tuple[int, float, str]] = []  # (page, font_size, text)

    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)[
            "blocks"
        ]
        for block in blocks:
            if block.get("type") != 0:  # 0 = text block
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    size = span.get("size", 10.0)
                    if text:
                        raw_blocks.append((page_num, size, text))

    if not raw_blocks:
        raise ParseError(
            "No extractable text found. The PDF may be scanned or image-based."
        )

    # ── Determine heading font-size threshold ────────────────────────────────
    sizes = [s for _, s, _ in raw_blocks]
    median_size = statistics.median(sizes)
    heading_threshold = median_size * 1.2

    # ── Build ParsedElement list ─────────────────────────────────────────────
    elements: list[ParsedElement] = []
    current_heading: str | None = None
    current_section: str | None = None

    for page_num, font_size, text in raw_blocks:
        is_heading = font_size >= heading_threshold or bool(
            _SECTION_RE.match(text)
        )

        if is_heading:
            element_type = "heading"
            current_heading = text
            # Try to extract section number from the heading text
            m = re.match(
                r"^(\d+(?:\.\d+){0,3}|(?:article|section)\s+\S+)",
                text,
                re.IGNORECASE,
            )
            current_section = m.group(1) if m else None
        elif _LIST_RE.match(text):
            element_type = "list_item"
        else:
            element_type = "narrative"

        elements.append(
            ParsedElement(
                text=text,
                element_type=element_type,
                page=page_num,
                section_number=current_section,
                heading=current_heading,
            )
        )

    doc.close()
    return elements
