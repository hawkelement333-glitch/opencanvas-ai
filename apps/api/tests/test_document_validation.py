from __future__ import annotations

import io
import zipfile

import pytest

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents import (
    DOCX_MEDIA_TYPE,
    DocumentValidationError,
    sanitize_filename,
    validate_document_bytes,
)
from tests.document_fixtures import make_docx_bytes, make_pdf_bytes


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", document_max_file_size_bytes=100_000)


@pytest.mark.parametrize(
    ("filename", "content", "media_type", "expected_type"),
    [
        ("brief.pdf", make_pdf_bytes(), "application/pdf", "pdf"),
        ("notes.txt", b"A UTF-8 note", "text/plain", "txt"),
        ("brief.md", b"# Brief\n\nGrounded facts.", "text/markdown", "markdown"),
        ("brief.docx", make_docx_bytes(), DOCX_MEDIA_TYPE, "docx"),
    ],
    ids=("pdf", "txt", "markdown", "docx"),
)
def test_supported_documents_are_sniffed_and_validated(
    settings: Settings,
    filename: str,
    content: bytes,
    media_type: str,
    expected_type: str,
) -> None:
    validated = validate_document_bytes(
        filename=filename,
        content=content,
        declared_media_type=media_type,
        settings=settings,
    )
    assert validated.file_type == expected_type
    assert validated.size_bytes == len(content)
    assert len(validated.sha256) == 64


@pytest.mark.security
def test_unsupported_and_mismatched_files_are_rejected(settings: Settings) -> None:
    with pytest.raises(DocumentValidationError) as unsupported:
        validate_document_bytes(
            filename="payload.exe",
            content=b"MZ",
            declared_media_type="application/octet-stream",
            settings=settings,
        )
    assert unsupported.value.status_code == 415

    with pytest.raises(DocumentValidationError) as disguised:
        validate_document_bytes(
            filename="disguised.pdf",
            content=b"not a pdf",
            declared_media_type="application/pdf",
            settings=settings,
        )
    assert disguised.value.code == "invalid_document"


@pytest.mark.security
def test_valid_pdf_signature_with_malformed_structure_is_rejected(settings: Settings) -> None:
    with pytest.raises(DocumentValidationError, match="malformed") as error:
        validate_document_bytes(
            filename="broken.pdf",
            content=b"%PDF-1.7\nnot-a-real-pdf",
            declared_media_type="application/pdf",
            settings=settings,
        )
    assert error.value.status_code == 422


@pytest.mark.security
def test_oversized_file_is_rejected() -> None:
    settings = Settings(environment="test", document_max_file_size_bytes=1_024)
    with pytest.raises(DocumentValidationError) as error:
        validate_document_bytes(
            filename="large.txt",
            content=b"x" * 1_025,
            declared_media_type="text/plain",
            settings=settings,
        )
    assert error.value.status_code == 413
    assert error.value.code == "file_too_large"


@pytest.mark.security
def test_filename_is_sanitized_without_path_components() -> None:
    assert sanitize_filename("../../secret<>name.md") == "secret_name.md"
    assert sanitize_filename("C:\\temp\\CON.txt") == "_CON.txt"


@pytest.mark.security
def test_docx_zip_bomb_and_unsafe_paths_are_rejected() -> None:
    settings = Settings(
        environment="test",
        document_max_file_size_bytes=4_096,
        document_docx_max_members=10,
        document_docx_max_uncompressed_bytes=1_048_576,
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
        archive.writestr("../escape.xml", "unsafe")
    with pytest.raises(DocumentValidationError, match="unsafe path"):
        validate_document_bytes(
            filename="unsafe.docx",
            content=output.getvalue(),
            declared_media_type=DOCX_MEDIA_TYPE,
            settings=settings,
        )


@pytest.mark.security
def test_signature_bearing_docx_with_malformed_xml_is_rejected(settings: Settings) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "not xml")

    with pytest.raises(DocumentValidationError, match="malformed Office document XML"):
        validate_document_bytes(
            filename="malformed.docx",
            content=output.getvalue(),
            declared_media_type=DOCX_MEDIA_TYPE,
            settings=settings,
        )
