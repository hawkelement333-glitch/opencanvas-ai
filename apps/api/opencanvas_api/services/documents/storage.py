from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import uuid
import xml.etree.ElementTree as ET
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from urllib.parse import quote, urlencode, urlparse

import aiofiles
import httpx

from opencanvas_api.core.config import Settings
from opencanvas_api.services.documents.errors import DocumentStorageError


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_key: str
    byte_size: int
    provider_version_id: str | None = None
    etag: str | None = None


SecurityClass = Literal["quarantine", "clean", "rejected", "retained"]


@dataclass(frozen=True, slots=True)
class ProviderObjectVersion:
    physical_key: str
    provider_name: str
    provider_version_id: str
    etag: str
    byte_size: int
    content_sha256: str


class VersionedObjectStorage(Protocol):
    name: str

    async def put_immutable(
        self,
        *,
        security_class: SecurityClass,
        object_id: uuid.UUID,
        object_version_id: uuid.UUID,
        content: bytes,
        expected_sha256: str,
    ) -> ProviderObjectVersion: ...

    async def read_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> bytes: ...

    async def copy_immutable(
        self,
        *,
        source: ProviderObjectVersion,
        target_security_class: SecurityClass,
        object_id: uuid.UUID,
        target_object_version_id: uuid.UUID,
    ) -> ProviderObjectVersion: ...

    async def delete_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> None: ...

    async def healthcheck(self) -> None: ...


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


@dataclass(slots=True)
class MemoryVersionedObjectStorage:
    name: str = "memory"
    _objects: dict[tuple[str, str], bytes] = field(default_factory=dict)

    async def put_immutable(
        self,
        *,
        security_class: SecurityClass,
        object_id: uuid.UUID,
        object_version_id: uuid.UUID,
        content: bytes,
        expected_sha256: str,
    ) -> ProviderObjectVersion:
        digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(digest, expected_sha256):
            raise DocumentStorageError("The object checksum does not match the upload contract.")
        key = _object_key(security_class, object_id, object_version_id)
        existing = next(
            (
                (provider_version, value)
                for (existing_key, provider_version), value in self._objects.items()
                if existing_key == key
            ),
            None,
        )
        if existing is not None:
            provider_version, value = existing
            if not hmac.compare_digest(hashlib.sha256(value).hexdigest(), digest):
                raise DocumentStorageError("The immutable object version already exists.")
            return ProviderObjectVersion(
                physical_key=key,
                provider_name=self.name,
                provider_version_id=provider_version,
                etag=f'"{digest}"',
                byte_size=len(value),
                content_sha256=digest,
            )
        version = uuid.uuid4().hex
        self._objects[(key, version)] = bytes(content)
        return ProviderObjectVersion(
            physical_key=key,
            provider_name=self.name,
            provider_version_id=version,
            etag=f'"{digest}"',
            byte_size=len(content),
            content_sha256=digest,
        )

    async def read_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> bytes:
        _validate_key(physical_key)
        try:
            return self._objects[(physical_key, provider_version_id)]
        except KeyError as exc:
            raise DocumentStorageError("The immutable object version is unavailable.") from exc

    async def copy_immutable(
        self,
        *,
        source: ProviderObjectVersion,
        target_security_class: SecurityClass,
        object_id: uuid.UUID,
        target_object_version_id: uuid.UUID,
    ) -> ProviderObjectVersion:
        content = await self.read_version(
            physical_key=source.physical_key,
            provider_version_id=source.provider_version_id,
        )
        return await self.put_immutable(
            security_class=target_security_class,
            object_id=object_id,
            object_version_id=target_object_version_id,
            content=content,
            expected_sha256=source.content_sha256,
        )

    async def delete_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> None:
        _validate_key(physical_key)
        self._objects.pop((physical_key, provider_version_id), None)

    async def healthcheck(self) -> None:
        return None


class LocalVersionedObjectStorage:
    """Local deterministic substitute with immutable opaque object-version keys."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    async def put_immutable(
        self,
        *,
        security_class: SecurityClass,
        object_id: uuid.UUID,
        object_version_id: uuid.UUID,
        content: bytes,
        expected_sha256: str,
    ) -> ProviderObjectVersion:
        digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(digest, expected_sha256):
            raise DocumentStorageError("The object checksum does not match the upload contract.")
        key = _object_key(security_class, object_id, object_version_id)
        destination = self._resolve_key(key)
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        if await asyncio.to_thread(destination.exists):
            existing = await asyncio.to_thread(destination.read_bytes)
            if not hmac.compare_digest(hashlib.sha256(existing).hexdigest(), digest):
                raise DocumentStorageError("The immutable object version already exists.")
            return ProviderObjectVersion(
                physical_key=key,
                provider_name=self.name,
                provider_version_id=object_version_id.hex,
                etag=f'"{digest}"',
                byte_size=len(existing),
                content_sha256=digest,
            )
        try:
            async with aiofiles.open(destination, "xb") as handle:
                await handle.write(content)
                await handle.flush()
        except FileExistsError as exc:
            existing = await asyncio.to_thread(destination.read_bytes)
            if not hmac.compare_digest(hashlib.sha256(existing).hexdigest(), digest):
                raise DocumentStorageError("The immutable object version already exists.") from exc
            return ProviderObjectVersion(
                physical_key=key,
                provider_name=self.name,
                provider_version_id=object_version_id.hex,
                etag=f'"{digest}"',
                byte_size=len(existing),
                content_sha256=digest,
            )
        except OSError as exc:
            raise DocumentStorageError("The object could not be stored safely.") from exc
        provider_version = object_version_id.hex
        return ProviderObjectVersion(
            physical_key=key,
            provider_name=self.name,
            provider_version_id=provider_version,
            etag=f'"{digest}"',
            byte_size=len(content),
            content_sha256=digest,
        )

    async def read_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> bytes:
        del provider_version_id
        source = self._resolve_key(physical_key)
        try:
            async with aiofiles.open(source, "rb") as handle:
                return await handle.read()
        except OSError as exc:
            raise DocumentStorageError("The immutable object version is unavailable.") from exc

    async def copy_immutable(
        self,
        *,
        source: ProviderObjectVersion,
        target_security_class: SecurityClass,
        object_id: uuid.UUID,
        target_object_version_id: uuid.UUID,
    ) -> ProviderObjectVersion:
        content = await self.read_version(
            physical_key=source.physical_key,
            provider_version_id=source.provider_version_id,
        )
        return await self.put_immutable(
            security_class=target_security_class,
            object_id=object_id,
            object_version_id=target_object_version_id,
            content=content,
            expected_sha256=source.content_sha256,
        )

    async def delete_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> None:
        del provider_version_id
        target = self._resolve_key(physical_key)
        try:
            await asyncio.to_thread(target.unlink, missing_ok=True)
        except OSError as exc:
            raise DocumentStorageError("The object version could not be removed.") from exc

    async def healthcheck(self) -> None:
        try:
            await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise DocumentStorageError("The versioned object store is unavailable.") from exc

    def _resolve_key(self, physical_key: str) -> Path:
        pure_key = _validate_key(physical_key)
        candidate = self.root.joinpath(*pure_key.parts).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise DocumentStorageError("The object key is outside the storage root.") from exc
        return candidate


class AzureManagedIdentityTokenProvider:
    """Fetch short-lived, allowlisted data-plane tokens from the workload identity."""

    _allowed_resources = frozenset(
        {
            "https://storage.azure.com/",
            "https://api.loganalytics.io/",
        }
    )

    def __init__(
        self, *, endpoint: str, identity_header: str, client_id: str | None = None
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or not parsed.netloc:
            raise DocumentStorageError("The managed-identity endpoint is invalid.")
        self.endpoint = endpoint
        self._identity_header = identity_header
        self._client_id = client_id

    async def get_token(self, resource: str = "https://storage.azure.com/") -> str:
        if resource not in self._allowed_resources:
            raise DocumentStorageError("The requested Azure token audience is not allowed.")
        parameters = {
            "api-version": "2019-08-01",
            "resource": resource,
        }
        if self._client_id:
            parameters["client_id"] = self._client_id
        query = urlencode(parameters)
        separator = "&" if "?" in self.endpoint else "?"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(
                    f"{self.endpoint}{separator}{query}",
                    headers={"X-IDENTITY-HEADER": self._identity_header},
                )
            response.raise_for_status()
            token = response.json().get("access_token")
        except (httpx.HTTPError, ValueError) as exc:
            raise DocumentStorageError("The Azure workload identity is unavailable.") from exc
        if not isinstance(token, str) or not token:
            raise DocumentStorageError("The Azure workload identity returned no token.")
        return token


class AzureBlobVersionedObjectStorage:
    """Private versioned Azure Blob adapter using workload identity only."""

    name = "azure"
    _api_version = "2023-11-03"

    def __init__(
        self,
        *,
        account_url: str,
        quarantine_container: str,
        clean_container: str,
        rejected_container: str,
        retained_container: str,
        token_provider: AzureManagedIdentityTokenProvider,
    ) -> None:
        parsed = urlparse(account_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise DocumentStorageError("The Azure storage account URL is invalid.")
        self.account_url = account_url.rstrip("/")
        self.containers = {
            "quarantine": quarantine_container,
            "clean": clean_container,
            "rejected": rejected_container,
            "retained": retained_container,
        }
        if any(not _safe_container_name(value) for value in self.containers.values()):
            raise DocumentStorageError("An Azure storage container name is invalid.")
        self.token_provider = token_provider

    async def put_immutable(
        self,
        *,
        security_class: SecurityClass,
        object_id: uuid.UUID,
        object_version_id: uuid.UUID,
        content: bytes,
        expected_sha256: str,
    ) -> ProviderObjectVersion:
        digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(digest, expected_sha256):
            raise DocumentStorageError("The object checksum does not match the upload contract.")
        key = _object_key(security_class, object_id, object_version_id)
        reconciled = False
        try:
            response = await self._request(
                "PUT",
                key,
                content=content,
                extra_headers={
                    "If-None-Match": "*",
                    "X-Ms-Blob-Type": "BlockBlob",
                    "X-Ms-Meta-Sha256": digest,
                },
                accepted_statuses=frozenset({409, 412}),
            )
        except DocumentStorageError as put_error:
            try:
                response = await self._request("HEAD", key)
            except DocumentStorageError:
                raise put_error from None
            reconciled = True
        if response.status_code in {409, 412}:
            response = await self._request("HEAD", key)
            reconciled = True
        if reconciled:
            recorded_digest = response.headers.get("x-ms-meta-sha256")
            recorded_size = response.headers.get("content-length")
            if (
                recorded_digest is None
                or not hmac.compare_digest(recorded_digest, digest)
                or recorded_size != str(len(content))
            ):
                raise DocumentStorageError("The immutable object version already exists.")
        version_id = response.headers.get("x-ms-version-id")
        etag = response.headers.get("etag")
        if not version_id or not etag:
            raise DocumentStorageError("Azure Blob versioning evidence is unavailable.")
        return ProviderObjectVersion(
            physical_key=key,
            provider_name=self.name,
            provider_version_id=version_id,
            etag=etag,
            byte_size=len(content),
            content_sha256=digest,
        )

    async def read_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> bytes:
        response = await self._request(
            "GET",
            physical_key,
            query={"versionid": provider_version_id},
        )
        return response.content

    def object_url(self, physical_key: str) -> str:
        """Return the canonical data-plane URI for one validated physical key."""

        return self._object_url(physical_key)

    async def read_version_properties(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
        expected_etag: str,
    ) -> tuple[str, str]:
        """Authoritatively bind a stored version ID and ETag without reading content."""

        response = await self._request(
            "HEAD",
            physical_key,
            query={"versionid": provider_version_id},
            extra_headers={"If-Match": expected_etag},
        )
        version_id = response.headers.get("x-ms-version-id")
        etag = response.headers.get("etag")
        if version_id != provider_version_id or etag != expected_etag:
            raise DocumentStorageError("The immutable Azure object identity changed.")
        current = await self._request(
            "HEAD",
            physical_key,
            extra_headers={"If-Match": expected_etag},
        )
        if (
            current.headers.get("x-ms-version-id") != provider_version_id
            or current.headers.get("etag") != expected_etag
        ):
            raise DocumentStorageError("The scanned Azure object version is no longer current.")
        return version_id, etag

    async def read_version_tags_xml(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
        expected_etag: str,
    ) -> bytes:
        """Read, but never write, the blob-index tags for one immutable version."""

        response = await self._request(
            "GET",
            physical_key,
            query={"comp": "tags", "versionid": provider_version_id},
            extra_headers={"If-Match": expected_etag},
        )
        if len(response.content) > 32_768:
            raise DocumentStorageError("The Azure blob-tag response is too large.")
        return response.content

    async def version_exists(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> bool:
        """Authoritatively test one exact version without accepting access failures."""

        response = await self._request(
            "HEAD",
            physical_key,
            query={"versionid": provider_version_id},
            accepted_statuses=frozenset({404}),
        )
        return response.status_code != 404

    async def version_residue_exists(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> bool:
        """List active and soft-deleted versions to prove exact canary residue absence."""

        pure = _validate_key(physical_key)
        blob_name = "/".join(pure.parts[1:])
        if not blob_name:
            raise DocumentStorageError("The Azure object key is invalid.")
        response = await self._request(
            "GET",
            pure.parts[0],
            query={
                "restype": "container",
                "comp": "list",
                "prefix": blob_name,
                "include": "versions,deleted",
                "maxresults": "100",
            },
        )
        if len(response.content) > 131_072:
            raise DocumentStorageError("The Azure version inventory is too large.")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise DocumentStorageError("The Azure version inventory is malformed.") from exc
        next_markers = [
            element.text or ""
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "NextMarker"
        ]
        if any(value for value in next_markers):
            raise DocumentStorageError("The Azure version inventory is incomplete.")
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "Blob":
                continue
            values = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in element}
            if values.get("Name") == blob_name and values.get("VersionId") == provider_version_id:
                return True
        return False

    async def copy_immutable(
        self,
        *,
        source: ProviderObjectVersion,
        target_security_class: SecurityClass,
        object_id: uuid.UUID,
        target_object_version_id: uuid.UUID,
    ) -> ProviderObjectVersion:
        response = await self._request(
            "GET",
            source.physical_key,
            query={"versionid": source.provider_version_id},
            extra_headers={"If-Match": source.etag},
        )
        content = response.content
        if (
            response.headers.get("x-ms-version-id") != source.provider_version_id
            or response.headers.get("etag") != source.etag
        ):
            raise DocumentStorageError("The quarantine object identity changed.")
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), source.content_sha256):
            raise DocumentStorageError("The quarantine object changed before promotion.")
        return await self.put_immutable(
            security_class=target_security_class,
            object_id=object_id,
            object_version_id=target_object_version_id,
            content=content,
            expected_sha256=source.content_sha256,
        )

    async def delete_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> None:
        response = await self._request(
            "DELETE",
            physical_key,
            query={"versionid": provider_version_id},
        )
        if response.headers.get("x-ms-delete-type-permanent") != "false":
            raise DocumentStorageError("The Azure object version was not soft-deleted as required.")

    async def permanently_delete_version(
        self,
        *,
        physical_key: str,
        provider_version_id: str,
    ) -> None:
        """Permanently delete one already-soft-deleted proof version."""

        response = await self._request(
            "DELETE",
            physical_key,
            query={"versionid": provider_version_id, "deletetype": "permanent"},
        )
        if response.headers.get("x-ms-delete-type-permanent") != "true":
            raise DocumentStorageError("The Azure proof version permanent deletion is unproved.")

    async def healthcheck(self) -> None:
        container = self.containers["quarantine"]
        url = (
            f"{self.account_url}/{container}"
            f"?{urlencode({'restype': 'container', 'comp': 'list', 'maxresults': '1'})}"
        )
        headers = {
            "Authorization": f"Bearer {await self.token_provider.get_token()}",
            "X-Ms-Date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "X-Ms-Version": self._api_version,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(url, headers=headers)
            if not 200 <= response.status_code < 300:
                raise DocumentStorageError("The private Azure quarantine container is not ready.")
        except DocumentStorageError:
            raise
        except httpx.HTTPError as exc:
            raise DocumentStorageError(
                "The private Azure quarantine container is unavailable."
            ) from exc

    async def _request(
        self,
        method: str,
        physical_key: str,
        *,
        content: bytes = b"",
        query: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        url = self._object_url(physical_key)
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Authorization": f"Bearer {await self.token_provider.get_token()}",
            "X-Ms-Date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "X-Ms-Version": self._api_version,
            **(extra_headers or {}),
        }
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, url, headers=headers, content=content)
            if not 200 <= response.status_code < 300 and (
                response.status_code not in accepted_statuses
            ):
                raise DocumentStorageError("The private Azure object store rejected the operation.")
            return response
        except DocumentStorageError:
            raise
        except httpx.HTTPError as exc:
            raise DocumentStorageError("The private Azure object store is unavailable.") from exc

    def _object_url(self, physical_key: str) -> str:
        pure = _validate_key(physical_key)
        security_class = pure.parts[0]
        if security_class not in self.containers:
            raise DocumentStorageError("The object security class is invalid.")
        blob = "/".join(quote(part, safe="-_.~") for part in pure.parts[1:])
        return f"{self.account_url}/{self.containers[security_class]}/{blob}"


class AzureDocumentStorage:
    """Read-only compatibility view over clean immutable Azure object keys."""

    name = "azure"

    def __init__(self, versioned: AzureBlobVersionedObjectStorage) -> None:
        self.versioned = versioned

    async def store(self, document_id: uuid.UUID, extension: str, content: bytes) -> StoredFile:
        del document_id, extension, content
        raise DocumentStorageError("Azure uploads require a secure upload session.")

    async def read(self, storage_key: str) -> bytes:
        response = await self.versioned._request("GET", storage_key)
        return response.content

    async def delete(self, storage_key: str) -> None:
        del storage_key
        raise DocumentStorageError("Azure object deletion requires an exact version request.")

    async def healthcheck(self) -> None:
        await self.versioned.healthcheck()


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


def _object_key(
    security_class: SecurityClass,
    object_id: uuid.UUID,
    object_version_id: uuid.UUID,
) -> str:
    return f"{security_class}/{object_id.hex}/{object_version_id.hex}"


def _safe_container_name(value: str) -> bool:
    return (
        3 <= len(value) <= 63
        and value == value.lower()
        and value[0].isalnum()
        and value[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in value)
        and "--" not in value
    )


def _azure_versioned_storage(settings: Settings) -> AzureBlobVersionedObjectStorage:
    if (
        settings.azure_storage_account_url is None
        or settings.azure_managed_identity_endpoint is None
        or settings.azure_managed_identity_header is None
    ):
        raise DocumentStorageError("Azure workload-identity storage is not completely configured.")
    return AzureBlobVersionedObjectStorage(
        account_url=settings.azure_storage_account_url,
        quarantine_container=settings.azure_quarantine_container,
        clean_container=settings.azure_clean_container,
        rejected_container=settings.azure_rejected_container,
        retained_container=settings.azure_retained_container,
        token_provider=AzureManagedIdentityTokenProvider(
            endpoint=settings.azure_managed_identity_endpoint,
            identity_header=settings.azure_managed_identity_header,
            client_id=settings.azure_managed_identity_client_id,
        ),
    )


def build_document_storage(settings: Settings) -> DocumentStorage:
    if settings.storage_provider == "memory":
        return MemoryDocumentStorage()
    if settings.storage_provider in {"local", "demo"}:
        root = (
            settings.document_storage_root / "objects-v2"
            if settings.object_ingestion_mode != "disabled"
            else settings.document_storage_root
        )
        return LocalDocumentStorage(root)
    if settings.storage_provider == "azure":
        return AzureDocumentStorage(_azure_versioned_storage(settings))
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


def build_versioned_object_storage(settings: Settings) -> VersionedObjectStorage:
    if settings.storage_provider == "memory":
        return MemoryVersionedObjectStorage()
    if settings.storage_provider in {"local", "demo"}:
        return LocalVersionedObjectStorage(settings.document_storage_root / "objects-v2")
    if settings.storage_provider == "azure":
        return _azure_versioned_storage(settings)
    raise DocumentStorageError(
        "The configured object store does not support the secure versioned-ingestion contract."
    )


__all__ = [
    "AzureBlobVersionedObjectStorage",
    "AzureDocumentStorage",
    "AzureManagedIdentityTokenProvider",
    "DocumentStorage",
    "LocalDocumentStorage",
    "LocalVersionedObjectStorage",
    "MemoryDocumentStorage",
    "MemoryVersionedObjectStorage",
    "ProviderObjectVersion",
    "S3DocumentStorage",
    "SecurityClass",
    "StoredFile",
    "VersionedObjectStorage",
    "build_document_storage",
    "build_versioned_object_storage",
]
