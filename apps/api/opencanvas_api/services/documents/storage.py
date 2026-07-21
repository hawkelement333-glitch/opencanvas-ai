from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote, urlparse

import aiofiles
import httpx

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents.errors import DocumentStorageError


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_key: str
    byte_size: int


class DocumentStorage(Protocol):
    name: str

    async def store(self, document_id: uuid.UUID, extension: str, content: bytes) -> StoredFile: ...

    async def read(self, storage_key: str) -> bytes: ...

    async def delete(self, storage_key: str) -> None: ...

    async def healthcheck(self) -> None: ...


class LocalDocumentStorage:
    """Opaque, non-public local storage with strict root containment."""

    name = "local"

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

    async def healthcheck(self) -> None:
        try:
            await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise DocumentStorageError("The document store is unavailable.") from exc

    def _resolve_key(self, storage_key: str) -> Path:
        pure_key = _validate_key(storage_key)
        candidate = self.root.joinpath(*pure_key.parts).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise DocumentStorageError(
                "The document storage key is outside the storage root."
            ) from exc
        return candidate


@dataclass(slots=True)
class MemoryDocumentStorage:
    name: str = "memory"
    _objects: dict[str, bytes] = field(default_factory=dict)

    async def store(self, document_id: uuid.UUID, extension: str, content: bytes) -> StoredFile:
        key = f"{document_id.hex}/{uuid.uuid4().hex}{extension.lower()}"
        self._objects[key] = bytes(content)
        return StoredFile(key, len(content))

    async def read(self, storage_key: str) -> bytes:
        _validate_key(storage_key)
        try:
            return self._objects[storage_key]
        except KeyError as exc:
            raise DocumentStorageError("The stored document is unavailable.") from exc

    async def delete(self, storage_key: str) -> None:
        _validate_key(storage_key)
        self._objects.pop(storage_key, None)

    async def healthcheck(self) -> None:
        return None


class S3DocumentStorage:
    """Private S3-compatible storage using SigV4 and no public object URLs."""

    name = "s3"
    _service = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str,
        endpoint: str | None,
        force_path_style: bool,
    ) -> None:
        if not bucket or not access_key_id or not secret_access_key:
            raise DocumentStorageError("S3-compatible storage is not completely configured.")
        self.bucket = bucket
        self.region = region
        self.access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self.prefix = prefix.strip("/")
        self.endpoint = (endpoint or f"https://s3.{region}.amazonaws.com").rstrip("/")
        self.force_path_style = force_path_style or endpoint is not None

    async def store(self, document_id: uuid.UUID, extension: str, content: bytes) -> StoredFile:
        key = "/".join(
            part
            for part in (self.prefix, document_id.hex, f"{uuid.uuid4().hex}{extension.lower()}")
            if part
        )
        await self._request("PUT", key, content)
        return StoredFile(storage_key=key, byte_size=len(content))

    async def read(self, storage_key: str) -> bytes:
        _validate_key(storage_key)
        return await self._request("GET", storage_key)

    async def delete(self, storage_key: str) -> None:
        _validate_key(storage_key)
        await self._request("DELETE", storage_key)

    async def healthcheck(self) -> None:
        await self._request("HEAD", "")

    async def _request(self, method: str, key: str, body: bytes = b"") -> bytes:
        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        url, canonical_uri, host = self._object_url(key)
        canonical_headers = (
            f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{timestamp}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date_stamp}/{self.region}/{self._service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                timestamp,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        headers = {
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
            "Host": host,
            "X-Amz-Content-Sha256": payload_hash,
            "X-Amz-Date": timestamp,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, url, headers=headers, content=body)
            if response.status_code < 200 or response.status_code >= 300:
                raise DocumentStorageError(
                    f"The private object store rejected the {method.lower()} operation."
                )
            return response.content
        except DocumentStorageError:
            raise
        except httpx.HTTPError as exc:
            raise DocumentStorageError("The private object store is unavailable.") from exc

    def _object_url(self, key: str) -> tuple[str, str, str]:
        endpoint = urlparse(self.endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise DocumentStorageError("The object-storage endpoint is invalid.")
        encoded_key = "/".join(quote(part, safe="-_.~") for part in PurePosixPath(key).parts)
        base_path = endpoint.path.rstrip("/")
        if self.force_path_style:
            canonical_uri = f"{base_path}/{quote(self.bucket, safe='-_.~')}"
            if encoded_key:
                canonical_uri += f"/{encoded_key}"
            host = endpoint.netloc
        else:
            canonical_uri = f"{base_path}/{encoded_key}" if encoded_key else f"{base_path}/"
            host = f"{self.bucket}.{endpoint.netloc}"
        return f"{endpoint.scheme}://{host}{canonical_uri}", canonical_uri or "/", host

    def _signing_key(self, date_stamp: str) -> bytes:
        date_key = hmac.new(
            f"AWS4{self._secret_access_key}".encode(),
            date_stamp.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        region_key = hmac.new(date_key, self.region.encode("utf-8"), hashlib.sha256).digest()
        service_key = hmac.new(region_key, self._service.encode("utf-8"), hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _validate_key(storage_key: str) -> PurePosixPath:
    pure_key = PurePosixPath(storage_key)
    if (
        pure_key.is_absolute()
        or not pure_key.parts
        or ".." in pure_key.parts
        or "\\" in storage_key
        or any(part in {"", "."} for part in pure_key.parts)
    ):
        raise DocumentStorageError("The document storage key is invalid.")
    return pure_key


def build_document_storage(settings: Settings) -> DocumentStorage:
    if settings.storage_provider == "memory":
        return MemoryDocumentStorage()
    if settings.storage_provider in {"local", "demo"}:
        return LocalDocumentStorage(settings.document_storage_root)
    if (
        settings.object_storage_bucket is None
        or settings.object_storage_access_key_id is None
        or settings.object_storage_secret_access_key is None
    ):
        raise DocumentStorageError("S3-compatible storage is not completely configured.")
    return S3DocumentStorage(
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
        access_key_id=settings.object_storage_access_key_id,
        secret_access_key=settings.object_storage_secret_access_key,
        prefix=settings.object_storage_prefix,
        endpoint=settings.object_storage_endpoint,
        force_path_style=settings.object_storage_force_path_style,
    )


__all__ = [
    "DocumentStorage",
    "LocalDocumentStorage",
    "MemoryDocumentStorage",
    "S3DocumentStorage",
    "StoredFile",
    "build_document_storage",
]
