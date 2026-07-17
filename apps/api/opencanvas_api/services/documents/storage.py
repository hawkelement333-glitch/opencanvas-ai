from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import aiofiles

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents.errors import DocumentStorageError


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_key: str
    byte_size: int


class LocalDocumentStorage:
    """Opaque, non-public local storage with strict root containment."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    async def store(self, document_id: uuid.UUID, extension: str, content: bytes) -> StoredFile:
        document_directory = self.root / document_id.hex
        await asyncio.to_thread(document_directory.mkdir, parents=True, exist_ok=True)
        key = f"{document_id.hex}/{uuid.uuid4().hex}{extension.lower()}"
        destination = self._resolve_key(key)
        temporary = destination.with_suffix(f"{destination.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            async with aiofiles.open(temporary, "xb") as handle:
                await handle.write(content)
                await handle.flush()
            await asyncio.to_thread(os.replace, temporary, destination)
        except OSError as exc:
            with suppress(OSError):
                await asyncio.to_thread(temporary.unlink, missing_ok=True)
            raise DocumentStorageError("The document could not be stored safely.") from exc
        return StoredFile(storage_key=key, byte_size=len(content))

    async def read(self, storage_key: str) -> bytes:
        source = self._resolve_key(storage_key)
        try:
            async with aiofiles.open(source, "rb") as handle:
                return await handle.read()
        except OSError as exc:
            raise DocumentStorageError("The stored document is unavailable.") from exc

    async def delete(self, storage_key: str) -> None:
        target = self._resolve_key(storage_key)
        try:
            await asyncio.to_thread(target.unlink, missing_ok=True)
            if target.parent != self.root:
                with suppress(OSError):
                    await asyncio.to_thread(target.parent.rmdir)
        except OSError as exc:
            raise DocumentStorageError("The stored document could not be removed.") from exc

    def _resolve_key(self, storage_key: str) -> Path:
        pure_key = PurePosixPath(storage_key)
        if pure_key.is_absolute() or not pure_key.parts or ".." in pure_key.parts:
            raise DocumentStorageError("The document storage key is invalid.")
        candidate = self.root.joinpath(*pure_key.parts).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise DocumentStorageError(
                "The document storage key is outside the storage root."
            ) from exc
        return candidate


def build_document_storage(settings: Settings) -> LocalDocumentStorage:
    return LocalDocumentStorage(settings.document_storage_root)
