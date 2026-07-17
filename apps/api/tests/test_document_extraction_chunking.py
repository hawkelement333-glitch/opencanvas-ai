from __future__ import annotations

from pathlib import Path

import pytest

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents import (
    DocumentExtractionError,
    chunk_document,
    extract_document,
)
from tests.document_fixtures import make_docx_bytes, make_pdf_bytes


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test")


def test_pdf_text_extraction_preserves_page_number(settings: Settings) -> None:
    extracted = extract_document(file_type="pdf", content=make_pdf_bytes(), settings=settings)
    assert "Aurora Finch" in extracted.text
    assert extracted.page_count == 1
    assert extracted.segments[0].page_number == 1


def test_markdown_heading_extraction(settings: Settings) -> None:
    fixture = Path(__file__).parent / "fixtures" / "aurora.md"
    extracted = extract_document(
        file_type="markdown", content=fixture.read_bytes(), settings=settings
    )
    assert [segment.heading for segment in extracted.segments] == ["Launch brief", "Scope"]
    assert "14 April 2026" in extracted.text
    chunks = chunk_document(extracted, chunk_size=256, overlap=32)
    assert [chunk.heading for chunk in chunks] == ["Launch brief", "Scope"]
    assert all(
        not ({"Launch brief", "Scope"} <= set(chunk.content.splitlines())) for chunk in chunks
    )


def test_docx_heading_extraction(settings: Settings) -> None:
    extracted = extract_document(file_type="docx", content=make_docx_bytes(), settings=settings)
    assert [segment.heading for segment in extracted.segments] == ["Launch brief", "Scope"]
    assert "twelve research teams" in extracted.text


def test_image_only_pdf_has_actionable_error(settings: Settings) -> None:
    with pytest.raises(DocumentExtractionError, match="OCR"):
        extract_document(file_type="pdf", content=make_pdf_bytes(""), settings=settings)


def test_pdf_chunks_never_cross_page_boundaries(settings: Settings) -> None:
    extracted = extract_document(
        file_type="pdf",
        content=make_pdf_bytes(["Aurora Finch is on page one.", "Scope is on page two."]),
        settings=settings,
    )
    chunks = chunk_document(extracted, chunk_size=256, overlap=32)
    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert "page two" not in chunks[0].content
    assert "page one" not in chunks[1].content


def test_semantic_chunks_have_controlled_overlap_and_offsets(settings: Settings) -> None:
    text = (
        "# Context\n\n"
        "Aurora Finch is the launch codename. The pilot began on 14 April 2026. "
        "This sentence provides enough additional detail to require another passage.\n\n"
        "The final paragraph records the operational scope and closes the brief."
    )
    extracted = extract_document(file_type="markdown", content=text.encode(), settings=settings)
    chunks = chunk_document(extracted, chunk_size=100, overlap=24)
    assert len(chunks) >= 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert extracted.text[chunk.char_start : chunk.char_end] == chunk.content
    assert chunks[1].char_start < chunks[0].char_end
    overlap = extracted.text[chunks[1].char_start : chunks[0].char_end]
    assert overlap.strip() in chunks[0].content
    assert overlap.strip() in chunks[1].content
