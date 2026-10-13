"""Scanned-PDF fallback.

PyMuPDF still owns digital PDFs. These tests prove a blank PDF is treated as
a scan, that Textract LINE blocks become clause elements, and that a scan is
not sent to AWS when Textract is turned off.
"""

from __future__ import annotations

from typing import Any

import fitz  # type: ignore
import pytest

from app.core.config import settings
from app.infra.textract import TextractUnavailable, lines_from_blocks, read_scanned_pdf
from app.ingestion.parser import (
    ParseError,
    ScannedPdfError,
    elements_from_lines,
    parse_pdf,
)
from app.services.ingestion_service import parse_uploaded_pdf


def _blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


def _text_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "1. Definitions")
    page.insert_text((72, 96), "The parties agree to the following terms.")
    return doc.tobytes()


def test_blank_pdf_is_a_scan() -> None:
    with pytest.raises(ScannedPdfError):
        parse_pdf(_blank_pdf())


def test_text_pdf_is_not_a_scan() -> None:
    elements = parse_pdf(_text_pdf())
    assert elements
    assert any("Definitions" in element.text for element in elements)


def test_lines_keep_section_until_the_next_heading() -> None:
    elements = elements_from_lines(
        [
            (1, "Section 2. Payment"),
            (1, "Rent is due monthly."),
            (2, "(a) late fees apply"),
        ]
    )
    assert [element.element_type for element in elements] == [
        "heading",
        "narrative",
        "list_item",
    ]
    assert elements[1].section_number == "Section 2."
    assert elements[1].heading == "Section 2. Payment"
    assert elements[2].page == 2


def test_line_blocks_ignore_words() -> None:
    lines = lines_from_blocks(
        [
            {"BlockType": "PAGE", "Page": 1},
            {"BlockType": "LINE", "Text": "Section 1. Term", "Page": 1},
            {"BlockType": "WORD", "Text": "Section", "Page": 1},
            {"BlockType": "LINE", "Text": "  ", "Page": 1},
            {"BlockType": "LINE", "Text": "This agreement lasts one year.", "Page": 3},
        ]
    )
    assert lines == [
        (1, "Section 1. Term"),
        (3, "This agreement lasts one year."),
    ]


class _FakeTextract:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.index = 0
        self.started: dict[str, Any] | None = None

    async def start_document_text_detection(self, **kwargs: Any) -> dict[str, str]:
        self.started = kwargs
        return {"JobId": "job-1"}

    async def get_document_text_detection(self, **kwargs: Any) -> dict[str, Any]:
        page = self.pages[self.index]
        self.index += 1
        return page


@pytest.mark.asyncio
async def test_disabled_textract_does_not_call_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "textract_enabled", False)

    with pytest.raises(TextractUnavailable):
        await read_scanned_pdf("tenants/a/scan.pdf", client=_FakeTextract([]))


@pytest.mark.asyncio
async def test_textract_job_becomes_elements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "textract_enabled", True)
    monkeypatch.setattr(settings, "textract_timeout_seconds", 5)
    client = _FakeTextract(
        [
            {"JobStatus": "IN_PROGRESS"},
            {
                "JobStatus": "SUCCEEDED",
                "NextToken": "page-2",
                "Blocks": [
                    {"BlockType": "LINE", "Text": "Section 4. Term", "Page": 1},
                ],
            },
            {
                "JobStatus": "SUCCEEDED",
                "Blocks": [
                    {"BlockType": "LINE", "Text": "The term is one year.", "Page": 2},
                ],
            },
        ]
    )

    async def _no_sleep(_: float) -> None:
        return None

    elements = await read_scanned_pdf(
        "tenants/a/scan.pdf",
        client=client,
        sleep=_no_sleep,
    )

    assert client.started is not None
    location = client.started["DocumentLocation"]["S3Object"]
    assert location["Name"] == "tenants/a/scan.pdf"
    assert [element.text for element in elements] == [
        "Section 4. Term",
        "The term is one year.",
    ]
    assert elements[1].page == 2
    assert elements[1].heading == "Section 4. Term"


@pytest.mark.asyncio
async def test_textract_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "textract_enabled", True)
    monkeypatch.setattr(settings, "textract_timeout_seconds", 0)
    client = _FakeTextract([{"JobStatus": "IN_PROGRESS"}])
    now = {"t": 0.0}

    def _clock() -> float:
        return now["t"]

    async def _sleep(_: float) -> None:
        now["t"] += 1

    with pytest.raises(ParseError, match="timed out"):
        await read_scanned_pdf(
            "tenants/a/scan.pdf",
            client=client,
            sleep=_sleep,
            clock=_clock,
        )


@pytest.mark.asyncio
async def test_scan_is_routed_to_textract(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    async def _fake_read(s3_key: str) -> list[Any]:
        seen["key"] = s3_key
        return elements_from_lines([(1, "Section 1. Parties")])

    monkeypatch.setattr(
        "app.services.ingestion_service.read_scanned_pdf",
        _fake_read,
    )

    elements = await parse_uploaded_pdf(_blank_pdf(), "tenants/a/scan.pdf")
    assert seen["key"] == "tenants/a/scan.pdf"
    assert elements[0].element_type == "heading"


@pytest.mark.asyncio
async def test_digital_pdf_skips_textract(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(_: str) -> list[Any]:
        raise AssertionError("digital PDF must not call Textract")

    monkeypatch.setattr("app.services.ingestion_service.read_scanned_pdf", _fail)
    elements = await parse_uploaded_pdf(_text_pdf(), "tenants/a/digital.pdf")
    assert elements


@pytest.mark.asyncio
async def test_failed_textract_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "textract_enabled", True)
    monkeypatch.setattr(settings, "textract_timeout_seconds", 5)
    client = _FakeTextract([{"JobStatus": "FAILED"}])

    async def _no_sleep(_: float) -> None:
        return None

    with pytest.raises(ParseError, match="could not read"):
        await read_scanned_pdf("tenants/a/scan.pdf", client=client, sleep=_no_sleep)
