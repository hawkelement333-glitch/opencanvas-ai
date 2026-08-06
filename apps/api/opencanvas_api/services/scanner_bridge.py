from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import socket
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    MalwareScanRequest,
    MalwareScanResult,
    StorageObjectLifecycleTransition,
    StorageObjectVersion,
)
from opencanvas_api.services.documents import (
    AzureBlobVersionedObjectStorage,
    AzureManagedIdentityTokenProvider,
    build_versioned_object_storage,
)
from opencanvas_api.services.documents.errors import DocumentStorageError
from opencanvas_api.services.object_ingestion import (
    MalwareScanService,
    ObjectReconciler,
    TrustedScanResult,
)

BLOB_RESULT_TAG: Final = "Malware scanning scan result"
BLOB_SCAN_TIME_TAG: Final = "Malware scanning scan time"
LOG_ANALYTICS_TOKEN_RESOURCE: Final = "https://api.loganalytics.io/"
SCANNER_IDENTITY: Final = "azure-defender-for-storage"
SCANNER_VERSION: Final = "defender-storage-dual-source-v1"
BRIDGE_PROVENANCE: Final = "defender-blob-tags-plus-storage-malware-scanning-results"
_ACCOUNT_NAME = re.compile(r"^[a-z0-9]{3,24}$")
_AZURE_ETAG = re.compile(r"^0x[0-9A-Fa-f]+$")
_BLOB_RESULTS = frozenset({"No threats found", "Malicious", "Error", "Not scanned"})
_LOG_RESULTS = frozenset({"No Threat Found", "Malicious", "Error", "Not Scanned"})

BridgeVerdict = Literal["clean", "infected"]
AddressResolver = Callable[[str], Awaitable[tuple[str, ...]]]
Clock = Callable[[], datetime]


class ScannerBridgeEvidenceError(RuntimeError):
    """A deterministic, non-sensitive failure at the dual-source trust boundary."""


@dataclass(frozen=True, slots=True)
class BlobScanEvidence:
    account_name: str
    object_uri: str
    provider_version_id: str
    etag: str
    scan_result: str
    scan_finished_at: datetime
    evidence_sha256: str

    def canonical(self) -> dict[str, str]:
        return {
            "accountName": self.account_name,
            "objectUri": self.object_uri,
            "providerVersionId": self.provider_version_id,
            "etag": self.etag,
            "scanResult": self.scan_result,
            "scanFinishedAtUtc": _format_utc(self.scan_finished_at),
            "evidenceSha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class LogAnalyticsScanEvidence:
    account_name: str
    object_uri: str
    etag: str
    scan_result: str
    correlation_id: str
    scan_finished_at: datetime
    time_generated: datetime
    evidence_sha256: str

    def correlation_tuple(self) -> tuple[str, str, str, str, str, datetime]:
        return (
            self.account_name,
            self.object_uri,
            self.etag,
            self.scan_result,
            self.correlation_id,
            self.scan_finished_at,
        )


@dataclass(frozen=True, slots=True)
class ScannerBridgeDecision:
    verdict: BridgeVerdict
    correlation_id: str
    scan_finished_at: datetime
    blob_evidence_sha256: str
    log_analytics_evidence_sha256: str
    object_uri_sha256: str
    etag_sha256: str
    evidence_integrity_sha256: str

    def event_evidence(self) -> dict[str, JsonValue]:
        return {
            "scannerEvidenceIntegrity": self.evidence_integrity_sha256,
            "scannerCorrelationSha256": _sha256_text(self.correlation_id),
            "scannerBlobTagEvidenceSha256": self.blob_evidence_sha256,
            "scannerLogAnalyticsEvidenceSha256": self.log_analytics_evidence_sha256,
            "scannerBlobUriSha256": self.object_uri_sha256,
            "scannerEtagSha256": self.etag_sha256,
            "scannerCompletionAtUtc": _format_utc(self.scan_finished_at),
            "scannerProvenance": BRIDGE_PROVENANCE,
        }


class BlobScanEvidenceReader(Protocol):
    async def read(
        self, version: StorageObjectVersion, *, observed_at: datetime
    ) -> BlobScanEvidence: ...


class LogAnalyticsScanEvidenceReader(Protocol):
    async def read(
        self,
        *,
        account_name: str,
        object_uri: str,
        etag: str,
        requested_at: datetime,
        observed_at: datetime,
    ) -> tuple[LogAnalyticsScanEvidence, ...]: ...


class PrivateDnsVerifier:
    """Fail closed unless each Azure data-plane name resolves only to private addresses."""

    def __init__(self, resolver: AddressResolver | None = None) -> None:
        self._resolver = resolver or _resolve_addresses
        self._verified: set[str] = set()

    async def verify(self, hostname: str) -> None:
        normalized = hostname.rstrip(".").lower()
        if not normalized or normalized in self._verified:
            return
        try:
            addresses = await self._resolver(normalized)
            parsed = tuple(ipaddress.ip_address(address) for address in addresses)
        except (OSError, ValueError) as exc:
            raise ScannerBridgeEvidenceError("scanner-private-dns-unproved") from exc
        if not parsed or any(
            not address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            for address in parsed
        ):
            raise ScannerBridgeEvidenceError("scanner-private-dns-unproved")
        self._verified.add(normalized)


class AzureBlobScanEvidenceClient:
    """Read Defender blob-index evidence through the existing private Blob client."""

    def __init__(
        self,
        storage: AzureBlobVersionedObjectStorage,
        *,
        dns: PrivateDnsVerifier | None = None,
    ) -> None:
        self.storage = storage
        parsed = urlparse(storage.account_url)
        self.hostname = parsed.hostname or ""
        self.account_name = self.hostname.split(".", 1)[0]
        if not _ACCOUNT_NAME.fullmatch(self.account_name):
            raise ScannerBridgeEvidenceError("scanner-storage-account-invalid")
        self.dns = dns or PrivateDnsVerifier()

    async def read(
        self, version: StorageObjectVersion, *, observed_at: datetime
    ) -> BlobScanEvidence:
        del observed_at
        if version.provider_name != "azure" or version.security_class != "quarantine":
            raise ScannerBridgeEvidenceError("scanner-object-identity-invalid")
        await self.dns.verify(self.hostname)
        await self.storage.read_version_properties(
            physical_key=version.physical_key,
            provider_version_id=version.provider_version_id,
            expected_etag=version.etag,
        )
        xml = await self.storage.read_version_tags_xml(
            physical_key=version.physical_key,
            provider_version_id=version.provider_version_id,
            expected_etag=version.etag,
        )
        tags = _parse_blob_tags(xml)
        if set(tags) != {BLOB_RESULT_TAG, BLOB_SCAN_TIME_TAG}:
            raise ScannerBridgeEvidenceError("scanner-blob-tag-evidence-incomplete")
        result = tags[BLOB_RESULT_TAG]
        if result not in _BLOB_RESULTS:
            raise ScannerBridgeEvidenceError("scanner-blob-tag-result-invalid")
        finished = _parse_utc(tags[BLOB_SCAN_TIME_TAG])
        uri = self.storage.object_url(version.physical_key)
        etag = _normalize_azure_etag(version.etag)
        integrity = _canonical_sha256(
            {
                "accountName": self.account_name,
                "objectUri": uri,
                "providerVersionId": version.provider_version_id,
                "etag": etag,
                "scanResult": result,
                "scanFinishedAtUtc": _format_utc(finished),
            },
            domain="mobius.scanner-bridge.blob-tags.v1",
        )
        return BlobScanEvidence(
            account_name=self.account_name,
            object_uri=uri,
            provider_version_id=version.provider_version_id,
            etag=etag,
            scan_result=result,
            scan_finished_at=finished,
            evidence_sha256=integrity,
        )


class AzureLogAnalyticsScanEvidenceClient:
    """Query the private AMPLS path for exact StorageMalwareScanningResults rows."""

    _required_columns: Final = (
        "StorageAccountName",
        "ScannedObjectUri",
        "ScannedObjectEtag",
        "ScanResultType",
        "CorrelationId",
        "ScanFinishedTimeUtc",
        "TimeGenerated",
    )

    def __init__(
        self,
        *,
        workspace_id: uuid.UUID,
        endpoint: str,
        token_provider: AzureManagedIdentityTokenProvider,
        dns: PrivateDnsVerifier | None = None,
        max_rows: int = 4,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlparse(endpoint.rstrip("/"))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.loganalytics.azure.com"
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ScannerBridgeEvidenceError("scanner-log-analytics-endpoint-invalid")
        self.workspace_id = workspace_id
        self.endpoint = endpoint.rstrip("/")
        self.hostname = parsed.hostname
        self.token_provider = token_provider
        self.dns = dns or PrivateDnsVerifier()
        self.max_rows = max(1, min(max_rows, 8))
        self.timeout_seconds = max(1.0, min(timeout_seconds, 30.0))
        self.transport = transport

    async def read(
        self,
        *,
        account_name: str,
        object_uri: str,
        etag: str,
        requested_at: datetime,
        observed_at: datetime,
    ) -> tuple[LogAnalyticsScanEvidence, ...]:
        if not _ACCOUNT_NAME.fullmatch(account_name):
            raise ScannerBridgeEvidenceError("scanner-log-query-identity-invalid")
        uri = urlparse(object_uri)
        if uri.scheme != "https" or uri.hostname != f"{account_name}.blob.core.windows.net":
            raise ScannerBridgeEvidenceError("scanner-log-query-identity-invalid")
        await self.dns.verify(self.hostname)
        query = _log_analytics_query(
            account_name=account_name,
            object_uri=object_uri,
            etag=etag,
            max_rows=self.max_rows,
        )
        start = _aware_utc(requested_at) - timedelta(minutes=5)
        end = _aware_utc(observed_at) + timedelta(minutes=1)
        token = await self.token_provider.get_token(LOG_ANALYTICS_TOKEN_RESOURCE)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.endpoint}/v1/workspaces/{self.workspace_id}/query",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": query, "timespan": f"{_format_utc(start)}/{_format_utc(end)}"},
                )
            if not 200 <= response.status_code < 300 or len(response.content) > 262_144:
                raise ScannerBridgeEvidenceError("scanner-log-query-unavailable")
            payload = response.json()
        except ScannerBridgeEvidenceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ScannerBridgeEvidenceError("scanner-log-query-unavailable") from exc
        return self._parse_response(payload)

    def _parse_response(self, payload: object) -> tuple[LogAnalyticsScanEvidence, ...]:
        if not isinstance(payload, Mapping) or set(payload) - {"tables"}:
            raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
        tables = payload.get("tables")
        if not isinstance(tables, list) or len(tables) != 1:
            raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
        table = tables[0]
        if not isinstance(table, Mapping) or set(table) - {"name", "columns", "rows"}:
            raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
        columns = table.get("columns")
        rows = table.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) > self.max_rows:
            raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
        names: list[str] = []
        for column in columns:
            if not isinstance(column, Mapping) or set(column) - {"name", "type"}:
                raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
            name = column.get("name")
            if not isinstance(name, str):
                raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
            names.append(name)
        if tuple(names) != self._required_columns:
            raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
        parsed: list[LogAnalyticsScanEvidence] = []
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != len(names)
                or not all(isinstance(item, str) for item in row)
            ):
                raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
            values = dict(zip(names, row, strict=True))
            result = values["ScanResultType"]
            if result not in _LOG_RESULTS or not values["CorrelationId"]:
                raise ScannerBridgeEvidenceError("scanner-log-query-response-invalid")
            finished = _parse_utc(values["ScanFinishedTimeUtc"])
            generated = _parse_utc(values["TimeGenerated"])
            integrity = _canonical_sha256(values, domain="mobius.scanner-bridge.log-row.v1")
            parsed.append(
                LogAnalyticsScanEvidence(
                    account_name=values["StorageAccountName"],
                    object_uri=values["ScannedObjectUri"],
                    etag=_normalize_azure_etag(values["ScannedObjectEtag"]),
                    scan_result=result,
                    correlation_id=values["CorrelationId"],
                    scan_finished_at=finished,
                    time_generated=generated,
                    evidence_sha256=integrity,
                )
            )
        return tuple(parsed)


def correlate_scan_evidence(
    *,
    version: StorageObjectVersion,
    request: MalwareScanRequest,
    blob: BlobScanEvidence,
    logs: Sequence[LogAnalyticsScanEvidence],
    observed_at: datetime,
    maximum_age: timedelta,
) -> ScannerBridgeDecision | None:
    """Resolve only exact dual-source agreement; every uncertainty remains pending."""

    if (
        version.provider_name != "azure"
        or version.security_class != "quarantine"
        or blob.provider_version_id != version.provider_version_id
        or not _azure_etags_equal(blob.etag, version.etag)
        or not logs
    ):
        return None
    first = logs[0]
    if any(item.correlation_tuple() != first.correlation_tuple() for item in logs[1:]):
        return None
    if (
        first.account_name != blob.account_name
        or first.object_uri != blob.object_uri
        or not _azure_etags_equal(first.etag, blob.etag)
        or first.scan_finished_at != blob.scan_finished_at
    ):
        return None
    verdict: BridgeVerdict
    if (blob.scan_result, first.scan_result) == ("No threats found", "No Threat Found"):
        verdict = "clean"
    elif (blob.scan_result, first.scan_result) == ("Malicious", "Malicious"):
        verdict = "infected"
    else:
        return None
    finished = _aware_utc(blob.scan_finished_at)
    now = _aware_utc(observed_at)
    if (
        finished < _aware_utc(request.requested_at) - timedelta(seconds=60)
        or finished > _aware_utc(request.deadline_at)
        or finished > now + timedelta(seconds=60)
        or now - finished > maximum_age
    ):
        return None
    integrity = _canonical_sha256(
        {
            "objectVersionId": str(version.object_version_id),
            "providerVersionId": version.provider_version_id,
            "etag": version.etag,
            "contentSha256": version.content_sha256,
            "blobEvidenceSha256": blob.evidence_sha256,
            "logAnalyticsEvidenceSha256": first.evidence_sha256,
            "correlationIdSha256": _sha256_text(first.correlation_id),
            "verdict": verdict,
            "scanFinishedAtUtc": _format_utc(finished),
        },
        domain="mobius.scanner-bridge.dual-source.v1",
    )
    return ScannerBridgeDecision(
        verdict=verdict,
        correlation_id=first.correlation_id,
        scan_finished_at=finished,
        blob_evidence_sha256=blob.evidence_sha256,
        log_analytics_evidence_sha256=first.evidence_sha256,
        object_uri_sha256=_sha256_text(blob.object_uri),
        etag_sha256=_sha256_text(_normalize_azure_etag(blob.etag)),
        evidence_integrity_sha256=integrity,
    )


class PrivateScannerResultBridgeConsumer:
    """Production worker adapter for private Blob-tag plus AMPLS Log Analytics pull."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: AzureBlobVersionedObjectStorage,
        blob_reader: BlobScanEvidenceReader,
        log_reader: LogAnalyticsScanEvidenceReader,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.blob_reader = blob_reader
        self.log_reader = log_reader
        self.clock = clock or (lambda: datetime.now(UTC))
        self._retry_failures = 0
        self._retry_not_before: datetime | None = None

    async def consume_once(self, session: AsyncSession) -> bool:
        now = _aware_utc(self.clock())
        if self._retry_not_before is not None and now < self._retry_not_before:
            return False
        latest_state = (
            select(StorageObjectLifecycleTransition.current_state)
            .where(
                StorageObjectLifecycleTransition.object_version_id
                == MalwareScanRequest.object_version_id
            )
            .order_by(StorageObjectLifecycleTransition.sequence.desc())
            .limit(1)
            .scalar_subquery()
        )
        request = await session.scalar(
            select(MalwareScanRequest)
            .where(
                MalwareScanRequest.deadline_at > now,
                latest_state == "scan_pending",
                ~MalwareScanRequest.scan_request_id.in_(select(MalwareScanResult.scan_request_id)),
            )
            .order_by(MalwareScanRequest.requested_at, MalwareScanRequest.scan_request_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if request is None:
            self._reset_retry()
            expired = await ObjectReconciler(session, settings=self.settings).expire_scan_requests(
                now=now,
                limit=self.settings.scanner_result_bridge_batch_size,
            )
            return expired > 0
        version = await session.get(StorageObjectVersion, request.object_version_id)
        if version is None:
            return False
        latest = await session.scalar(
            select(StorageObjectLifecycleTransition)
            .where(StorageObjectLifecycleTransition.object_version_id == version.object_version_id)
            .order_by(StorageObjectLifecycleTransition.sequence.desc())
            .limit(1)
        )
        if latest is None or latest.current_state != "scan_pending":
            return False
        try:
            blob = await self.blob_reader.read(version, observed_at=now)
            logs = await self.log_reader.read(
                account_name=blob.account_name,
                object_uri=blob.object_uri,
                etag=blob.etag,
                requested_at=request.requested_at,
                observed_at=now,
            )
        except (DocumentStorageError, ScannerBridgeEvidenceError):
            self._defer(now)
            return False
        decision = correlate_scan_evidence(
            version=version,
            request=request,
            blob=blob,
            logs=logs,
            observed_at=now,
            maximum_age=timedelta(seconds=self.settings.malware_scan_result_max_age_seconds),
        )
        if decision is None:
            self._defer(now)
            return False
        result = TrustedScanResult(
            scan_request_id=request.scan_request_id,
            object_version_id=version.object_version_id,
            workspace_id=version.workspace_id,
            outcome=decision.verdict,
            scanner_identity=SCANNER_IDENTITY,
            scanner_version=SCANNER_VERSION,
            engine_version="microsoft-defender-for-storage",
            signature_version="dual-source-private-pull-v1",
            policy_version=request.policy_version,
            provider_result_id=decision.correlation_id,
            provider_record_digest=decision.evidence_integrity_sha256,
            provider_version_id=version.provider_version_id,
            etag=version.etag,
            content_sha256=version.content_sha256,
            scanned_at=decision.scan_finished_at,
            safe_reason_code=(
                "defender_dual_source_clean"
                if decision.verdict == "clean"
                else "defender_dual_source_malicious"
            ),
        )
        await MalwareScanService(
            session,
            settings=self.settings,
            storage=self.storage,
        ).record_bridge_result(
            result=result,
            evidence_integrity_sha256=decision.evidence_integrity_sha256,
            event_evidence=decision.event_evidence(),
        )
        self._reset_retry()
        return True

    def _defer(self, now: datetime) -> None:
        self._retry_failures = min(self._retry_failures + 1, 32)
        delay = bounded_scanner_retry_delay(
            self._retry_failures,
            base_seconds=self.settings.scanner_result_bridge_retry_base_seconds,
            maximum_seconds=self.settings.scanner_result_bridge_retry_max_seconds,
        )
        self._retry_not_before = now + timedelta(seconds=delay)

    def _reset_retry(self) -> None:
        self._retry_failures = 0
        self._retry_not_before = None


def bounded_scanner_retry_delay(
    failure_count: int, *, base_seconds: int, maximum_seconds: int
) -> int:
    """Return a capped exponential delay; the scan-request deadline bounds attempts."""

    if failure_count < 1 or base_seconds < 1 or maximum_seconds < base_seconds:
        raise ValueError("invalid scanner retry policy")
    exponent = min(failure_count - 1, 30)
    scaled = base_seconds << exponent
    return maximum_seconds if scaled > maximum_seconds else scaled


def build_private_scanner_result_bridge(
    settings: Settings,
) -> PrivateScannerResultBridgeConsumer | None:
    if settings.scanner_result_bridge_mode == "disabled":
        return None
    if (
        settings.scanner_result_bridge_mode != "private_pull"
        or settings.storage_provider != "azure"
        or settings.azure_log_analytics_workspace_id is None
    ):
        raise ScannerBridgeEvidenceError("scanner-private-pull-configuration-invalid")
    storage = build_versioned_object_storage(settings)
    if not isinstance(storage, AzureBlobVersionedObjectStorage):
        raise ScannerBridgeEvidenceError("scanner-private-pull-configuration-invalid")
    dns = PrivateDnsVerifier()
    blob = AzureBlobScanEvidenceClient(storage, dns=dns)
    logs = AzureLogAnalyticsScanEvidenceClient(
        workspace_id=settings.azure_log_analytics_workspace_id,
        endpoint=settings.azure_log_analytics_endpoint,
        token_provider=storage.token_provider,
        dns=dns,
        max_rows=settings.scanner_result_bridge_max_log_rows,
        timeout_seconds=settings.scanner_result_bridge_query_timeout_seconds,
    )
    return PrivateScannerResultBridgeConsumer(
        settings=settings,
        storage=storage,
        blob_reader=blob,
        log_reader=logs,
    )


async def _resolve_addresses(hostname: str) -> tuple[str, ...]:
    records = await asyncio.to_thread(
        socket.getaddrinfo,
        hostname,
        443,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
    )
    return tuple(sorted({str(record[4][0]) for record in records}))


def _parse_blob_tags(value: bytes) -> dict[str, str]:
    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise ScannerBridgeEvidenceError("scanner-blob-tag-evidence-invalid") from exc
    result: dict[str, str] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Tag":
            continue
        children = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in element}
        if set(children) != {"Key", "Value"} or children["Key"] in result:
            raise ScannerBridgeEvidenceError("scanner-blob-tag-evidence-invalid")
        result[children["Key"]] = children["Value"]
    return result


def _log_analytics_query(*, account_name: str, object_uri: str, etag: str, max_rows: int) -> str:
    normalized_etag = _normalize_azure_etag(etag)
    encoded = {
        "account": base64.b64encode(account_name.encode()).decode(),
        "uri": base64.b64encode(object_uri.encode()).decode(),
        "etag": base64.b64encode(normalized_etag.encode()).decode(),
    }
    return "\n".join(
        (
            f'let expectedAccount = base64_decode_tostring("{encoded["account"]}");',
            f'let expectedUri = base64_decode_tostring("{encoded["uri"]}");',
            f'let expectedEtag = base64_decode_tostring("{encoded["etag"]}");',
            "StorageMalwareScanningResults",
            "| extend EffectiveUri = iff(isnotempty(ScannedObjectUri), ScannedObjectUri, BlobUri)",
            "| extend EffectiveEtag = iff(isnotempty(ScannedObjectEtag), "
            "ScannedObjectEtag, BlobEtag)",
            "| extend NormalizedEtag = replace_string(EffectiveEtag, '\"', '')",
            "| where StorageAccountName == expectedAccount",
            "| where EffectiveUri == expectedUri and NormalizedEtag == expectedEtag",
            "| project StorageAccountName, ScannedObjectUri=EffectiveUri, "
            "ScannedObjectEtag=NormalizedEtag, ScanResultType, CorrelationId, "
            "ScanFinishedTimeUtc, TimeGenerated",
            "| order by ScanFinishedTimeUtc desc, TimeGenerated desc",
            f"| take {max_rows}",
        )
    )


def log_analytics_query_sha256(
    *, account_name: str, object_uri: str, etag: str, max_rows: int
) -> str:
    """Return a sanitized binding to the exact Log Analytics query issued."""

    return _sha256_text(
        _log_analytics_query(
            account_name=account_name,
            object_uri=object_uri,
            etag=etag,
            max_rows=max(1, min(max_rows, 8)),
        )
    )


def _parse_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    fraction = re.search(r"\.(\d{7,})(?=[+-]\d\d:\d\d$)", normalized)
    if fraction is not None:
        normalized = (
            normalized[: fraction.start(1)] + fraction.group(1)[:6] + normalized[fraction.end(1) :]
        )
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ScannerBridgeEvidenceError("scanner-evidence-time-invalid") from exc
    if parsed.tzinfo is None:
        raise ScannerBridgeEvidenceError("scanner-evidence-time-invalid")
    return parsed.astimezone(UTC)


def _normalize_azure_etag(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith('"') or normalized.endswith('"'):
        if len(normalized) < 3 or not normalized.startswith('"') or not normalized.endswith('"'):
            raise ScannerBridgeEvidenceError("scanner-evidence-etag-invalid")
        normalized = normalized[1:-1]
    if _AZURE_ETAG.fullmatch(normalized) is None:
        raise ScannerBridgeEvidenceError("scanner-evidence-etag-invalid")
    return normalized


def _azure_etags_equal(left: str, right: str) -> bool:
    try:
        return _normalize_azure_etag(left) == _normalize_azure_etag(right)
    except ScannerBridgeEvidenceError:
        return False


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha256(value: object, *, domain: str) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(domain.encode() + b"\0" + canonical).hexdigest()


__all__ = [
    "BLOB_RESULT_TAG",
    "BLOB_SCAN_TIME_TAG",
    "BRIDGE_PROVENANCE",
    "AzureBlobScanEvidenceClient",
    "AzureLogAnalyticsScanEvidenceClient",
    "BlobScanEvidence",
    "LogAnalyticsScanEvidence",
    "PrivateDnsVerifier",
    "PrivateScannerResultBridgeConsumer",
    "ScannerBridgeDecision",
    "ScannerBridgeEvidenceError",
    "build_private_scanner_result_bridge",
    "correlate_scan_evidence",
    "log_analytics_query_sha256",
]
