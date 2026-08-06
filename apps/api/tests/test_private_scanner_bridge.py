from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import MalwareScanRequest, StorageObjectVersion
from opencanvas_api.services.documents import (
    AzureBlobVersionedObjectStorage,
    AzureManagedIdentityTokenProvider,
    ProviderObjectVersion,
)
from opencanvas_api.services.documents.errors import DocumentStorageError
from opencanvas_api.services.jobs import DocumentWorker
from opencanvas_api.services.scanner_bridge import (
    BLOB_RESULT_TAG,
    BLOB_SCAN_TIME_TAG,
    AzureBlobScanEvidenceClient,
    AzureLogAnalyticsScanEvidenceClient,
    BlobScanEvidence,
    BlobScanEvidenceReader,
    LogAnalyticsScanEvidence,
    LogAnalyticsScanEvidenceReader,
    PrivateDnsVerifier,
    PrivateScannerResultBridgeConsumer,
    ScannerBridgeEvidenceError,
    bounded_scanner_retry_delay,
    correlate_scan_evidence,
)

NOW = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)
FINISHED = NOW - timedelta(minutes=1)
ACCOUNT = "mobius77scan"
URI = f"https://{ACCOUNT}.blob.core.windows.net/quarantine/objects/evidence"
ETAG = '"0x8DEFACED"'
VERSION_ID = "2026-08-06T14:58:00.0000000Z"
CORRELATION_ID = "00000000-0000-4000-8000-000000000077"


def _version() -> StorageObjectVersion:
    return StorageObjectVersion(
        object_version_id=uuid.uuid4(),
        object_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        security_class="quarantine",
        physical_key="quarantine/objects/evidence",
        provider_name="azure",
        provider_version_id=VERSION_ID,
        etag=ETAG,
        byte_size=18,
        content_sha256="a" * 64,
        media_type="text/plain",
        created_at=NOW - timedelta(minutes=3),
    )


def _request(version: StorageObjectVersion) -> MalwareScanRequest:
    return MalwareScanRequest(
        scan_request_id=uuid.uuid4(),
        object_version_id=version.object_version_id,
        workspace_id=version.workspace_id,
        requested_by_user_id=uuid.uuid4(),
        scanner_identity="azure-defender-for-storage",
        scanner_version="defender-storage-dual-source-v1",
        policy_version="mobius-malware-policy-v1",
        request_digest="b" * 64,
        timeout_seconds=3_600,
        trace_id=uuid.uuid4(),
        requested_at=NOW - timedelta(minutes=2),
        deadline_at=NOW + timedelta(minutes=58),
    )


def _blob(*, result: str = "No threats found") -> BlobScanEvidence:
    return BlobScanEvidence(
        account_name=ACCOUNT,
        object_uri=URI,
        provider_version_id=VERSION_ID,
        etag=ETAG,
        scan_result=result,
        scan_finished_at=FINISHED,
        evidence_sha256="c" * 64,
    )


def _log(*, result: str = "No Threat Found") -> LogAnalyticsScanEvidence:
    return LogAnalyticsScanEvidence(
        account_name=ACCOUNT,
        object_uri=URI,
        etag=ETAG,
        scan_result=result,
        correlation_id=CORRELATION_ID,
        scan_finished_at=FINISHED,
        time_generated=FINISHED + timedelta(seconds=2),
        evidence_sha256="d" * 64,
    )


def _correlate(
    *,
    blob: BlobScanEvidence | None = None,
    logs: tuple[LogAnalyticsScanEvidence, ...] | None = None,
    observed_at: datetime = NOW,
) -> object:
    version = _version()
    return correlate_scan_evidence(
        version=version,
        request=_request(version),
        blob=blob or _blob(),
        logs=logs if logs is not None else (_log(),),
        observed_at=observed_at,
        maximum_age=timedelta(hours=24),
    )


def test_exact_dual_source_clean_and_malicious_results_resolve() -> None:
    clean = _correlate()
    malicious = _correlate(
        blob=_blob(result="Malicious"),
        logs=(_log(result="Malicious"),),
    )

    assert clean is not None and clean.verdict == "clean"  # type: ignore[union-attr]
    assert malicious is not None and malicious.verdict == "infected"  # type: ignore[union-attr]
    assert clean.correlation_id == CORRELATION_ID  # type: ignore[union-attr]
    event_evidence = clean.event_evidence()  # type: ignore[union-attr]
    assert event_evidence["scannerBlobUriSha256"] == hashlib.sha256(URI.encode()).hexdigest()
    assert (
        event_evidence["scannerEtagSha256"] == hashlib.sha256(ETAG.strip('"').encode()).hexdigest()
    )


def test_http_quoted_and_log_unquoted_etags_are_the_same_exact_azure_etag() -> None:
    decision = _correlate(logs=(replace(_log(), etag=ETAG.strip('"')),))
    assert decision is not None
    assert decision.verdict == "clean"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("blob_result", "log_result"),
    [
        ("Error", "Error"),
        ("Not scanned", "Not Scanned"),
        ("No threats found", "Malicious"),
        ("Malicious", "No Threat Found"),
    ],
)
def test_error_not_scanned_and_conflicting_results_stay_pending(
    blob_result: str,
    log_result: str,
) -> None:
    assert _correlate(blob=_blob(result=blob_result), logs=(_log(result=log_result),)) is None


def test_missing_stale_ambiguous_or_mismatched_evidence_stays_pending() -> None:
    assert _correlate(logs=()) is None
    assert _correlate(observed_at=NOW + timedelta(days=2)) is None
    assert _correlate(logs=(_log(), replace(_log(), correlation_id=str(uuid.uuid4())))) is None
    assert _correlate(logs=(replace(_log(), account_name="wrongaccount"),)) is None
    assert _correlate(logs=(replace(_log(), object_uri=f"{URI}-wrong"),)) is None
    assert _correlate(logs=(replace(_log(), etag='"different"'),)) is None
    assert (
        _correlate(logs=(replace(_log(), scan_finished_at=FINISHED + timedelta(seconds=1)),))
        is None
    )
    assert _correlate(blob=replace(_blob(), provider_version_id="different-version")) is None


def test_identical_duplicate_log_rows_reconcile_without_a_duplicate_decision() -> None:
    duplicate = replace(
        _log(),
        time_generated=FINISHED + timedelta(seconds=3),
        evidence_sha256="e" * 64,
    )
    decision = _correlate(logs=(_log(), duplicate))
    assert decision is not None
    assert decision.verdict == "clean"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_private_dns_proof_rejects_public_answers() -> None:
    async def private(_hostname: str) -> tuple[str, ...]:
        return ("10.77.0.9",)

    async def public(_hostname: str) -> tuple[str, ...]:
        return ("20.42.1.9",)

    await PrivateDnsVerifier(private).verify("api.loganalytics.azure.com")
    with pytest.raises(ScannerBridgeEvidenceError, match="scanner-private-dns-unproved"):
        await PrivateDnsVerifier(public).verify("api.loganalytics.azure.com")


class _BlobStorage:
    account_url = f"https://{ACCOUNT}.blob.core.windows.net"

    def __init__(self) -> None:
        self.operations: list[str] = []

    async def read_version_properties(self, **_kwargs: str) -> tuple[str, str]:
        self.operations.append("HEAD")
        return VERSION_ID, ETAG

    async def read_version_tags_xml(self, **_kwargs: str) -> bytes:
        self.operations.append("GET_TAGS")
        return (
            "<?xml version='1.0' encoding='utf-8'?><Tags><TagSet>"
            f"<Tag><Key>{BLOB_RESULT_TAG}</Key><Value>No threats found</Value></Tag>"
            f"<Tag><Key>{BLOB_SCAN_TIME_TAG}</Key><Value>"
            f"{FINISHED.isoformat()}</Value></Tag></TagSet></Tags>"
        ).encode()

    def object_url(self, _physical_key: str) -> str:
        return URI


@pytest.mark.asyncio
async def test_blob_adapter_has_only_read_operations_and_binds_exact_version() -> None:
    async def private(_hostname: str) -> tuple[str, ...]:
        return ("10.77.0.9",)

    storage = _BlobStorage()
    client = AzureBlobScanEvidenceClient(
        cast(AzureBlobVersionedObjectStorage, storage),
        dns=PrivateDnsVerifier(private),
    )
    evidence = await client.read(_version(), observed_at=NOW)

    assert storage.operations == ["HEAD", "GET_TAGS"]
    assert evidence.provider_version_id == VERSION_ID
    assert evidence.etag == ETAG.strip('"')
    assert evidence.object_uri == URI


def test_scanner_retry_backoff_is_exponential_capped_and_rejects_invalid_policy() -> None:
    assert [
        bounded_scanner_retry_delay(attempt, base_seconds=5, maximum_seconds=20)
        for attempt in range(1, 6)
    ] == [5, 10, 20, 20, 20]
    with pytest.raises(ValueError, match="invalid scanner retry policy"):
        bounded_scanner_retry_delay(0, base_seconds=5, maximum_seconds=20)
    with pytest.raises(ValueError, match="invalid scanner retry policy"):
        bounded_scanner_retry_delay(1, base_seconds=20, maximum_seconds=5)


def test_consumer_retry_state_defers_and_resets_without_unbounded_growth() -> None:
    settings = Settings(
        scanner_result_bridge_retry_base_seconds=5,
        scanner_result_bridge_retry_max_seconds=20,
    )
    consumer = PrivateScannerResultBridgeConsumer(
        settings=settings,
        storage=cast(AzureBlobVersionedObjectStorage, object()),
        blob_reader=cast(BlobScanEvidenceReader, object()),
        log_reader=cast(LogAnalyticsScanEvidenceReader, object()),
        clock=lambda: NOW,
    )
    for _attempt in range(40):
        consumer._defer(NOW)
    assert consumer._retry_failures == 32
    assert consumer._retry_not_before == NOW + timedelta(seconds=20)
    consumer._reset_retry()
    assert consumer._retry_failures == 0
    assert consumer._retry_not_before is None


def _azure_storage() -> AzureBlobVersionedObjectStorage:
    return AzureBlobVersionedObjectStorage(
        account_url=f"https://{ACCOUNT}.blob.core.windows.net",
        quarantine_container="quarantine",
        clean_container="clean",
        rejected_container="rejected",
        retained_container="retained",
        token_provider=cast(AzureManagedIdentityTokenProvider, object()),
    )


@pytest.mark.asyncio
async def test_ambiguous_canary_upload_is_adopted_by_authoritative_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    content = b"bounded-canary"
    digest = hashlib.sha256(content).hexdigest()
    methods: list[str] = []

    async def request(method: str, _physical_key: str, **_kwargs: object) -> httpx.Response:
        methods.append(method)
        if method == "PUT":
            raise DocumentStorageError("ambiguous-write-response")
        return httpx.Response(
            200,
            headers={
                "x-ms-meta-sha256": digest,
                "content-length": str(len(content)),
                "x-ms-version-id": VERSION_ID,
                "etag": ETAG,
            },
        )

    monkeypatch.setattr(storage, "_request", request)
    result = await storage.put_immutable(
        security_class="quarantine",
        object_id=uuid.uuid4(),
        object_version_id=uuid.uuid4(),
        content=content,
        expected_sha256=digest,
    )
    assert methods == ["PUT", "HEAD"]
    assert result.provider_version_id == VERSION_ID
    assert result.etag == ETAG


@pytest.mark.asyncio
async def test_version_readback_rejects_an_overwritten_current_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    calls: list[tuple[str, dict[str, str] | None, dict[str, str] | None]] = []

    async def request(
        method: str,
        _physical_key: str,
        *,
        query: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> httpx.Response:
        calls.append((method, query, extra_headers))
        if query is not None:
            return httpx.Response(
                200,
                headers={"x-ms-version-id": VERSION_ID, "etag": ETAG},
            )
        return httpx.Response(
            200,
            headers={"x-ms-version-id": "newer-version", "etag": '"newer"'},
        )

    monkeypatch.setattr(storage, "_request", request)
    with pytest.raises(DocumentStorageError, match="no longer current"):
        await storage.read_version_properties(
            physical_key="quarantine/objects/evidence",
            provider_version_id=VERSION_ID,
            expected_etag=ETAG,
        )
    assert calls == [
        ("HEAD", {"versionid": VERSION_ID}, {"If-Match": ETAG}),
        ("HEAD", None, {"If-Match": ETAG}),
    ]


@pytest.mark.asyncio
async def test_promotion_read_is_conditioned_on_exact_version_and_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    calls: list[tuple[str, dict[str, str] | None, dict[str, str] | None]] = []

    async def request(
        method: str,
        _physical_key: str,
        *,
        query: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> httpx.Response:
        calls.append((method, query, extra_headers))
        return httpx.Response(
            200,
            content=b"changed",
            headers={"x-ms-version-id": VERSION_ID, "etag": '"wrong"'},
        )

    monkeypatch.setattr(storage, "_request", request)
    source = ProviderObjectVersion(
        physical_key="quarantine/objects/evidence",
        provider_name="azure",
        provider_version_id=VERSION_ID,
        etag=ETAG,
        byte_size=7,
        content_sha256=hashlib.sha256(b"changed").hexdigest(),
    )
    with pytest.raises(DocumentStorageError, match="identity changed"):
        await storage.copy_immutable(
            source=source,
            target_security_class="clean",
            object_id=uuid.uuid4(),
            target_object_version_id=uuid.uuid4(),
        )
    assert calls == [
        ("GET", {"versionid": VERSION_ID}, {"If-Match": ETAG}),
    ]


@pytest.mark.asyncio
async def test_exact_version_absence_readback_accepts_only_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    observed: list[frozenset[int]] = []

    async def request(
        _method: str,
        _physical_key: str,
        *,
        accepted_statuses: frozenset[int] = frozenset(),
        **_kwargs: object,
    ) -> httpx.Response:
        observed.append(accepted_statuses)
        return httpx.Response(404)

    monkeypatch.setattr(storage, "_request", request)
    assert (
        await storage.version_exists(
            physical_key="quarantine/objects/evidence",
            provider_version_id=VERSION_ID,
        )
        is False
    )
    assert observed == [frozenset({404})]


@pytest.mark.asyncio
async def test_deleted_version_residue_inventory_and_permanent_delete_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    inventory = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b"<EnumerationResults><Blobs><Blob><Name>objects/evidence</Name>"
        b"<VersionId>" + VERSION_ID.encode() + b"</VersionId><Deleted>true</Deleted>"
        b"</Blob></Blobs><NextMarker /></EnumerationResults>"
    )
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    async def request(
        method: str,
        physical_key: str,
        *,
        query: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> httpx.Response:
        calls.append((method, physical_key, query))
        if method == "GET":
            return httpx.Response(200, content=inventory)
        return httpx.Response(
            202,
            headers={"x-ms-delete-type-permanent": "true"},
        )

    monkeypatch.setattr(storage, "_request", request)
    assert await storage.version_residue_exists(
        physical_key="quarantine/objects/evidence",
        provider_version_id=VERSION_ID,
    )
    await storage.permanently_delete_version(
        physical_key="quarantine/objects/evidence",
        provider_version_id=VERSION_ID,
    )
    assert calls == [
        (
            "GET",
            "quarantine",
            {
                "restype": "container",
                "comp": "list",
                "prefix": "objects/evidence",
                "include": "versions,deleted",
                "maxresults": "100",
            },
        ),
        (
            "DELETE",
            "quarantine/objects/evidence",
            {"versionid": VERSION_ID, "deletetype": "permanent"},
        ),
    ]


@pytest.mark.asyncio
async def test_current_version_is_demoted_then_soft_deleted_by_exact_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    current = True
    version_active = True
    calls: list[
        tuple[
            str,
            dict[str, str] | None,
            dict[str, str] | None,
            frozenset[int],
        ]
    ] = []

    async def request(
        method: str,
        _physical_key: str,
        *,
        query: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
        **_kwargs: object,
    ) -> httpx.Response:
        nonlocal current, version_active
        calls.append((method, query, extra_headers, accepted_statuses))
        if method == "HEAD" and query is None:
            if not current:
                return httpx.Response(404)
            return httpx.Response(
                200,
                headers={"x-ms-version-id": VERSION_ID, "etag": ETAG},
            )
        if method == "HEAD":
            if not version_active:
                return httpx.Response(404)
            return httpx.Response(
                200,
                headers={"x-ms-version-id": VERSION_ID, "etag": ETAG},
            )
        if query is None:
            current = False
            return httpx.Response(202)
        version_active = False
        return httpx.Response(
            202,
            headers={"x-ms-delete-type-permanent": "false"},
        )

    monkeypatch.setattr(storage, "_request", request)
    await storage.delete_version(
        physical_key="quarantine/objects/evidence",
        provider_version_id=VERSION_ID,
    )

    assert calls == [
        ("HEAD", {"versionid": VERSION_ID}, None, frozenset()),
        ("HEAD", None, None, frozenset({404})),
        ("DELETE", None, {"If-Match": ETAG}, frozenset()),
        ("HEAD", None, None, frozenset({404})),
        (
            "HEAD",
            {"versionid": VERSION_ID},
            {"If-Match": ETAG},
            frozenset(),
        ),
        (
            "DELETE",
            {"versionid": VERSION_ID},
            {"If-Match": ETAG},
            frozenset(),
        ),
        ("HEAD", {"versionid": VERSION_ID}, None, frozenset({404})),
    ]


@pytest.mark.asyncio
async def test_demoted_version_retry_never_redeletes_the_blob_wide_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    version_active = True
    calls: list[tuple[str, dict[str, str] | None]] = []

    async def request(
        method: str,
        _physical_key: str,
        *,
        query: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> httpx.Response:
        nonlocal version_active
        calls.append((method, query))
        if method == "HEAD" and query is None:
            return httpx.Response(404)
        if method == "HEAD":
            if not version_active:
                return httpx.Response(404)
            return httpx.Response(
                200,
                headers={"x-ms-version-id": VERSION_ID, "etag": ETAG},
            )
        version_active = False
        return httpx.Response(
            202,
            headers={"x-ms-delete-type-permanent": "false"},
        )

    monkeypatch.setattr(storage, "_request", request)
    await storage.delete_version(
        physical_key="quarantine/objects/evidence",
        provider_version_id=VERSION_ID,
    )

    assert calls == [
        ("HEAD", {"versionid": VERSION_ID}),
        ("HEAD", None),
        ("DELETE", {"versionid": VERSION_ID}),
        ("HEAD", {"versionid": VERSION_ID}),
    ]


@pytest.mark.asyncio
async def test_delete_version_rejects_a_different_current_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _azure_storage()
    methods: list[str] = []

    async def request(
        method: str,
        _physical_key: str,
        *,
        query: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> httpx.Response:
        methods.append(method)
        if query is not None:
            return httpx.Response(
                200,
                headers={"x-ms-version-id": VERSION_ID, "etag": ETAG},
            )
        return httpx.Response(
            200,
            headers={"x-ms-version-id": "different-version", "etag": '"different"'},
        )

    monkeypatch.setattr(storage, "_request", request)
    with pytest.raises(DocumentStorageError, match="different Azure object version"):
        await storage.delete_version(
            physical_key="quarantine/objects/evidence",
            provider_version_id=VERSION_ID,
        )
    assert methods == ["HEAD", "HEAD"]


class _TokenProvider:
    def __init__(self) -> None:
        self.resources: list[str] = []

    async def get_token(self, resource: str) -> str:
        self.resources.append(resource)
        return "bounded-test-token"


@pytest.mark.parametrize("scan_result", ["No Threat Found", "No threats found"])
@pytest.mark.asyncio
async def test_log_adapter_queries_only_exact_dual_source_identity(
    scan_result: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert ACCOUNT not in body["query"]
        assert URI not in body["query"]
        return httpx.Response(
            200,
            json={
                "tables": [
                    {
                        "name": "PrimaryResult",
                        "columns": [
                            {"name": "StorageAccountName", "type": "string"},
                            {"name": "ScannedObjectUri", "type": "string"},
                            {"name": "ScannedObjectEtag", "type": "string"},
                            {"name": "ScanResultType", "type": "string"},
                            {"name": "CorrelationId", "type": "string"},
                            {"name": "ScanFinishedTimeUtc", "type": "datetime"},
                            {"name": "TimeGenerated", "type": "datetime"},
                        ],
                        "rows": [
                            [
                                ACCOUNT,
                                URI,
                                ETAG.strip('"'),
                                scan_result,
                                CORRELATION_ID,
                                FINISHED.isoformat(),
                                (FINISHED + timedelta(seconds=2)).isoformat(),
                            ]
                        ],
                    }
                ]
            },
        )

    async def private(_hostname: str) -> tuple[str, ...]:
        return ("10.77.0.10",)

    token = _TokenProvider()
    client = AzureLogAnalyticsScanEvidenceClient(
        workspace_id=uuid.UUID("00000000-0000-4000-8000-000000000077"),
        endpoint="https://api.loganalytics.azure.com",
        token_provider=cast(AzureManagedIdentityTokenProvider, token),
        dns=PrivateDnsVerifier(private),
        transport=httpx.MockTransport(handler),
    )
    evidence = await client.read(
        account_name=ACCOUNT,
        object_uri=URI,
        etag=ETAG,
        requested_at=NOW - timedelta(minutes=2),
        observed_at=NOW,
    )

    assert len(evidence) == 1
    assert evidence[0].correlation_id == CORRELATION_ID
    assert evidence[0].etag == ETAG.strip('"')
    assert evidence[0].scan_result == "No threats found"
    decision = _correlate(logs=evidence)
    assert decision is not None and decision.verdict == "clean"  # type: ignore[union-attr]
    assert token.resources == ["https://api.loganalytics.io/"]
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path.endswith("/query")


@pytest.mark.parametrize("scan_result", ["No threats found ", "Clean", None])
def test_log_parser_rejects_unknown_or_malformed_clean_results(
    scan_result: object,
) -> None:
    client = AzureLogAnalyticsScanEvidenceClient(
        workspace_id=uuid.UUID("00000000-0000-4000-8000-000000000077"),
        endpoint="https://api.loganalytics.azure.com",
        token_provider=cast(AzureManagedIdentityTokenProvider, _TokenProvider()),
    )
    payload = {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "StorageAccountName", "type": "string"},
                    {"name": "ScannedObjectUri", "type": "string"},
                    {"name": "ScannedObjectEtag", "type": "string"},
                    {"name": "ScanResultType", "type": "string"},
                    {"name": "CorrelationId", "type": "string"},
                    {"name": "ScanFinishedTimeUtc", "type": "datetime"},
                    {"name": "TimeGenerated", "type": "datetime"},
                ],
                "rows": [
                    [
                        ACCOUNT,
                        URI,
                        ETAG.strip('"'),
                        scan_result,
                        CORRELATION_ID,
                        FINISHED.isoformat(),
                        FINISHED.isoformat(),
                    ]
                ],
            }
        ]
    }
    with pytest.raises(
        ScannerBridgeEvidenceError,
        match="scanner-log-query-response-invalid",
    ):
        client._parse_response(payload)


def test_malicious_log_result_cannot_normalize_to_clean() -> None:
    malicious = _log(result="Malicious")
    infected = _correlate(
        blob=_blob(result="Malicious"),
        logs=(malicious,),
    )
    assert infected is not None and infected.verdict == "infected"  # type: ignore[union-attr]
    assert _correlate(logs=(malicious,)) is None


@pytest.mark.asyncio
async def test_log_analytics_outage_fails_closed_without_evidence() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "redacted"})

    async def private(_hostname: str) -> tuple[str, ...]:
        return ("10.77.0.10",)

    client = AzureLogAnalyticsScanEvidenceClient(
        workspace_id=uuid.UUID("00000000-0000-4000-8000-000000000077"),
        endpoint="https://api.loganalytics.azure.com",
        token_provider=cast(AzureManagedIdentityTokenProvider, _TokenProvider()),
        dns=PrivateDnsVerifier(private),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ScannerBridgeEvidenceError, match="scanner-log-query-unavailable"):
        await client.read(
            account_name=ACCOUNT,
            object_uri=URI,
            etag=ETAG,
            requested_at=NOW - timedelta(minutes=2),
            observed_at=NOW,
        )


@pytest.mark.asyncio
async def test_managed_identity_adapter_refuses_unrelated_token_audiences() -> None:
    provider = AzureManagedIdentityTokenProvider(
        endpoint="http://127.0.0.1/metadata/identity/oauth2/token",
        identity_header="test-header",
    )
    with pytest.raises(DocumentStorageError, match="token audience is not allowed"):
        await provider.get_token("https://management.azure.com/")


def test_production_worker_entry_point_invokes_private_pull_consumer_first() -> None:
    source = inspect.getsource(DocumentWorker.run_once)
    assert "self.scanner_bridge.consume_once(session)" in source
    assert source.index("self.scanner_bridge.consume_once(session)") < source.index(
        "service.claim_one"
    )


def test_live_probe_is_bounded_sanitized_and_deletes_its_exact_version() -> None:
    from scripts import scanner_bridge_probe

    source = inspect.getsource(scanner_bridge_probe.run)
    cleanup_source = inspect.getsource(scanner_bridge_probe._remove_exact_canary)
    assert "for attempt in range(max_attempts)" in source
    assert "finally:" in source
    assert "_remove_exact_canary(storage, provider)" in source
    assert "storage.delete_version" in cleanup_source
    assert "storage.permanently_delete_version" in cleanup_source
    assert "storage.version_residue_exists" in cleanup_source
    assert "OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED" in source
    assert "uuid.uuid5" in source
    assert "SCANNER_RESULT_BRIDGE_PROVED" in source
    assert "provider.provider_version_id" in source
    assert "print(" in source


@pytest.mark.asyncio
async def test_live_probe_reconciles_role_propagation_before_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import scanner_bridge_probe

    provider = ProviderObjectVersion(
        physical_key="quarantine/objects/proof",
        provider_name="azure",
        provider_version_id=VERSION_ID,
        etag=ETAG,
        byte_size=len(scanner_bridge_probe._CANARY),
        content_sha256=hashlib.sha256(scanner_bridge_probe._CANARY).hexdigest(),
    )

    class DelayedStorage:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def put_immutable(self, **kwargs: object) -> ProviderObjectVersion:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise DocumentStorageError("role propagation pending")
            return provider

    async def no_sleep(_seconds: float) -> None:
        return None

    storage = DelayedStorage()
    monkeypatch.setattr(scanner_bridge_probe.asyncio, "sleep", no_sleep)
    object_id = uuid.uuid4()
    object_version_id = uuid.uuid4()
    result = await scanner_bridge_probe._put_exact_canary(
        cast(AzureBlobVersionedObjectStorage, storage),
        object_id=object_id,
        object_version_id=object_version_id,
        digest=provider.content_sha256,
    )

    assert result == provider
    assert len(storage.calls) == 2
    assert storage.calls[0] == storage.calls[1]
    assert storage.calls[0]["object_id"] == object_id
    assert storage.calls[0]["object_version_id"] == object_version_id


@pytest.mark.asyncio
async def test_live_probe_reconciles_ambiguous_canary_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import scanner_bridge_probe

    provider = ProviderObjectVersion(
        physical_key="quarantine/objects/proof",
        provider_name="azure",
        provider_version_id=VERSION_ID,
        etag=ETAG,
        byte_size=1,
        content_sha256="a" * 64,
    )

    class AmbiguousStorage:
        def __init__(self) -> None:
            self.residue = [True, True, False]
            self.soft_delete_calls = 0
            self.permanent_delete_calls = 0

        async def delete_version(self, **_kwargs: object) -> None:
            self.soft_delete_calls += 1
            raise DocumentStorageError("ambiguous soft delete")

        async def version_exists(self, **_kwargs: object) -> bool:
            return False

        async def version_residue_exists(self, **_kwargs: object) -> bool:
            return self.residue.pop(0)

        async def permanently_delete_version(self, **_kwargs: object) -> None:
            self.permanent_delete_calls += 1
            raise DocumentStorageError("ambiguous permanent delete")

    async def no_sleep(_seconds: float) -> None:
        return None

    storage = AmbiguousStorage()
    monkeypatch.setattr(scanner_bridge_probe.asyncio, "sleep", no_sleep)
    await scanner_bridge_probe._remove_exact_canary(
        cast(AzureBlobVersionedObjectStorage, storage),
        provider,
    )

    assert storage.soft_delete_calls == 1
    assert storage.permanent_delete_calls == 1
    assert storage.residue == []
