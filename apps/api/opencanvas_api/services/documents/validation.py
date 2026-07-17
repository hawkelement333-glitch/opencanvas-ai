from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from docx import Document as WordDocument
from fastapi import UploadFile
from pypdf import PdfReader

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents.errors import DocumentValidationError

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".docx"}
_EXTENSION_TYPES = {
    ".pdf": ("pdf", "application/pdf"),
    ".txt": ("txt", "text/plain"),
    ".md": ("markdown", "text/markdown"),
    ".markdown": ("markdown", "text/markdown"),
    ".docx": ("docx", DOCX_MEDIA_TYPE),
}
_DECLARED_MEDIA_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "text/x-markdown", "application/octet-stream"},
    ".markdown": {
        "text/markdown",
        "text/plain",
        "text/x-markdown",
        "application/octet-stream",
    },
    ".docx": {
        DOCX_MEDIA_TYPE,
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    },
}
_INVALID_FILENAME_CHARS = re.compile(r"[^\w.()\- ]+", re.UNICODE)
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class ValidatedDocument:
    file_name: str
    file_type: str
    extension: str
    media_type: str
    size_bytes: int
    sha256: str
    content: bytes


def sanitize_filename(filename: str | None) -> str:
    raw = unicodedata.normalize("NFKC", filename or "")
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = "".join(character for character in raw if character.isprintable())
    raw = _INVALID_FILENAME_CHARS.sub("_", raw).strip(" .")
    if not raw:
        raise DocumentValidationError("The uploaded file must have a valid filename.")

    extension = PurePosixPath(raw).suffix.lower()
    stem = raw[: -len(extension)] if extension else raw
    stem = stem.strip(" ._") or "document"
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    max_stem_length = max(1, 180 - len(extension))
    return f"{stem[:max_stem_length]}{extension}"


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise DocumentValidationError(
            f"The file exceeds the {max_bytes // (1024 * 1024)} MiB upload limit.",
            code="file_too_large",
            status_code=413,
        )
    return content


def validate_document_bytes(
    *,
    filename: str | None,
    content: bytes,
    declared_media_type: str | None,
    settings: Settings,
) -> ValidatedDocument:
    file_name = sanitize_filename(filename)
    extension = PurePosixPath(file_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentValidationError(
            "Supported document formats are PDF, TXT, Markdown, and DOCX.",
            code="unsupported_file_type",
            status_code=415,
        )
    if not content:
        raise DocumentValidationError("The uploaded file is empty.")
    if len(content) > settings.document_max_file_size_bytes:
        raise DocumentValidationError(
            "The uploaded file exceeds the configured document size limit.",
            code="file_too_large",
            status_code=413,
        )

    normalized_declared = (declared_media_type or "").split(";", maxsplit=1)[0].strip().lower()
    if normalized_declared and normalized_declared not in _DECLARED_MEDIA_TYPES[extension]:
        raise DocumentValidationError(
            "The file's declared media type does not match its extension.",
            code="unsupported_media_type",
            status_code=415,
        )

    file_type, media_type = _EXTENSION_TYPES[extension]
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise DocumentValidationError("The uploaded PDF does not have a valid PDF signature.")
        _validate_pdf_structure(content, settings)
    elif extension == ".docx":
        _validate_docx_archive(content, settings)
    else:
        _validate_utf8_text(content)

    return ValidatedDocument(
        file_name=file_name,
        file_type=file_type,
        extension=extension,
        media_type=media_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def _validate_utf8_text(content: bytes) -> None:
    if b"\x00" in content:
        raise DocumentValidationError("Text documents must not contain binary data.")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentValidationError("Text documents must use UTF-8 encoding.") from exc


def _validate_pdf_structure(content: bytes, settings: Settings) -> None:
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        page_count = len(reader.pages)
    except Exception as exc:
        raise DocumentValidationError("The uploaded PDF is malformed and cannot be read.") from exc
    if page_count == 0:
        raise DocumentValidationError("The uploaded PDF does not contain any pages.")
    if page_count > settings.document_max_pdf_pages:
        raise DocumentValidationError("The uploaded PDF contains too many pages to process safely.")


def _validate_docx_archive(content: bytes, settings: Settings) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > settings.document_docx_max_members:
                raise DocumentValidationError("The DOCX archive contains too many files.")
            total_size = 0
            names: set[str] = set()
            for member in members:
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise DocumentValidationError("The DOCX archive contains an unsafe path.")
                if member.flag_bits & 0x1:
                    raise DocumentValidationError("Encrypted DOCX files are not supported.")
                total_size += member.file_size
                if total_size > settings.document_docx_max_uncompressed_bytes:
                    raise DocumentValidationError("The DOCX archive expands beyond the safe limit.")
                names.add(path.as_posix())
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required <= names:
                raise DocumentValidationError("The uploaded archive is not a valid DOCX document.")
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentValidationError("The uploaded DOCX archive is malformed.") from exc

    try:
        WordDocument(io.BytesIO(content))
    except Exception as exc:
        raise DocumentValidationError(
            "The uploaded DOCX contains malformed Office document XML."
        ) from exc
