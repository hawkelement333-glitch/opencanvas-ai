from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import ssl
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from opencanvas_api.db.models import MalwareScanRequest, StorageObjectVersion
from opencanvas_api.services.documents import (
    AzureBlobVersionedObjectStorage,
    AzureManagedIdentityTokenProvider,
    DocumentStorageError,
    ProviderObjectVersion,
)
from opencanvas_api.services.scanner_bridge import (
    AzureBlobScanEvidenceClient,
    AzureLogAnalyticsScanEvidenceClient,
    BlobScanEvidence,
    BlobScanEvidenceReader,
    LogAnalyticsScanEvidenceReader,
    PrivateDnsVerifier,
    ScannerBridgeDecision,
    diagnose_scan_evidence,
    log_analytics_query_sha256,
)

_CANARY = b"SolarPlexus Mobius Milestone 7.7 harmless scanner bridge canary\n"
_OBJECT_NAMESPACE = uuid.UUID("ddff9e14-5c8c-5e20-a610-1fcc4e1f44cb")
_WORKSPACE_ID = uuid.UUID("2b5f8ed5-725f-5b10-ab10-ad255bf42bb2")
_USER_ID = uuid.UUID("f9c06d27-29bf-59be-b236-fee627452a5f")
_TRACE_ID = uuid.UUID("9070a5fc-688a-5587-a3d4-69cf3bb767cd")
_FAILURE_CODE = re.compile(r"^scanner-[a-z0-9]+(?:-[a-z0-9]+)*$")


class ScannerBridgeProbeFailure(RuntimeError):
    """A sanitized terminal proof failure retained before canary cleanup."""

    def __init__(self, failure_code: str, attempt_count: int) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.attempt_count = attempt_count


@dataclass(frozen=True, slots=True)
class _ProofMatch:
    decision: ScannerBridgeDecision
    blob: BlobScanEvidence
    attempt_count: int


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError("scanner-bridge-probe-configuration-incomplete")
    return value.strip()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _prove_private_tls(hostnames: tuple[str, ...]) -> tuple[str, str]:
    observed: dict[str, str] = {}
    context = ssl.create_default_context()
    for hostname in hostnames:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    hostname,
                    443,
                    family=socket.AF_UNSPEC,
                    ssl=context,
                    server_hostname=hostname,
                ),
                timeout=20.0,
            )
            del reader
            ssl_object = writer.get_extra_info("ssl_object")
            version = ssl_object.version() if ssl_object is not None else None
            writer.close()
            await writer.wait_closed()
        except (OSError, TimeoutError, ssl.SSLError) as exc:
            raise RuntimeError("scanner-bridge-probe-private-tls-unproved") from exc
        if version not in {"TLSv1.2", "TLSv1.3"}:
            raise RuntimeError("scanner-bridge-probe-private-tls-unproved")
        observed[hostname] = version
    minimum = "TLS1_2" if "TLSv1.2" in observed.values() else "TLS1_3"
    return (
        minimum,
        hashlib.sha256(
            json.dumps(observed, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
    )


async def _remove_exact_canary(
    storage: AzureBlobVersionedObjectStorage,
    provider: ProviderObjectVersion,
) -> None:
    for soft_delete_attempt in range(2):
        try:
            await storage.delete_version(
                physical_key=provider.physical_key,
                provider_version_id=provider.provider_version_id,
            )
            break
        except DocumentStorageError:
            if not await storage.version_exists(
                physical_key=provider.physical_key,
                provider_version_id=provider.provider_version_id,
            ):
                break
            if soft_delete_attempt == 1:
                raise
    if not await storage.version_residue_exists(
        physical_key=provider.physical_key,
        provider_version_id=provider.provider_version_id,
    ):
        return
    for permanent_delete_attempt in range(2):
        with suppress(DocumentStorageError):
            await storage.permanently_delete_version(
                physical_key=provider.physical_key,
                provider_version_id=provider.provider_version_id,
            )
        for reconciliation_attempt in range(5):
            if not await storage.version_residue_exists(
                physical_key=provider.physical_key,
                provider_version_id=provider.provider_version_id,
            ):
                return
            if reconciliation_attempt < 4:
                await asyncio.sleep(2.0)
        if permanent_delete_attempt == 1:
            raise RuntimeError("scanner-bridge-probe-canary-residue-present")


async def _put_exact_canary(
    storage: AzureBlobVersionedObjectStorage,
    *,
    object_id: uuid.UUID,
    object_version_id: uuid.UUID,
    digest: str,
) -> ProviderObjectVersion:
    for attempt in range(30):
        try:
            return await storage.put_immutable(
                security_class="quarantine",
                object_id=object_id,
                object_version_id=object_version_id,
                content=_CANARY,
                expected_sha256=digest,
            )
        except DocumentStorageError:
            if attempt == 29:
                raise
            await asyncio.sleep(10.0)
    raise RuntimeError("scanner-bridge-probe-upload-reconciliation-exhausted")


def _safe_failure_code(exc: RuntimeError, fallback: str) -> str:
    value = str(exc)
    if len(value) <= 128 and _FAILURE_CODE.fullmatch(value) is not None:
        return value
    return fallback


async def _poll_dual_source_evidence(
    *,
    version: StorageObjectVersion,
    request: MalwareScanRequest,
    blob_reader: BlobScanEvidenceReader,
    log_reader: LogAnalyticsScanEvidenceReader,
    max_attempts: int,
    delay_seconds: float,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> _ProofMatch:
    if max_attempts < 1:
        raise RuntimeError("scanner-bridge-probe-bounds-invalid")
    latest_failure = "scanner-correlation-log-evidence-missing"
    for attempt in range(max_attempts):
        observed_at = clock()
        try:
            blob = await blob_reader.read(version, observed_at=observed_at)
        except RuntimeError as exc:
            latest_failure = _safe_failure_code(exc, "scanner-blob-evidence-unavailable")
        else:
            try:
                logs = await log_reader.read(
                    account_name=blob.account_name,
                    object_uri=blob.object_uri,
                    etag=blob.etag,
                    requested_at=request.requested_at,
                    observed_at=observed_at,
                )
            except RuntimeError as exc:
                latest_failure = _safe_failure_code(exc, "scanner-log-query-unavailable")
            else:
                try:
                    correlation = diagnose_scan_evidence(
                        version=version,
                        request=request,
                        blob=blob,
                        logs=logs,
                        observed_at=observed_at,
                        maximum_age=timedelta(hours=24),
                    )
                except RuntimeError as exc:
                    latest_failure = _safe_failure_code(
                        exc, "scanner-correlation-validation-failed"
                    )
                else:
                    if correlation.decision is not None:
                        if not logs:
                            raise RuntimeError("scanner-correlation-log-evidence-missing")
                        return _ProofMatch(
                            decision=correlation.decision,
                            blob=blob,
                            attempt_count=attempt + 1,
                        )
                    latest_failure = (
                        correlation.failure_code or "scanner-correlation-validation-failed"
                    )
        if attempt + 1 < max_attempts:
            await asyncio.sleep(delay_seconds)
    raise ScannerBridgeProbeFailure(latest_failure, max_attempts)


async def run(*, max_attempts: int, delay_seconds: float) -> int:
    account_url = _required_environment("OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL")
    workspace_customer_id = uuid.UUID(
        _required_environment("OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID")
    )
    identity_endpoint = _required_environment("IDENTITY_ENDPOINT")
    identity_header = _required_environment("IDENTITY_HEADER")
    identity_client_id = _required_environment("OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID")
    token_provider = AzureManagedIdentityTokenProvider(
        endpoint=identity_endpoint,
        identity_header=identity_header,
        client_id=identity_client_id,
    )
    storage = AzureBlobVersionedObjectStorage(
        account_url=account_url,
        quarantine_container="quarantine",
        clean_container="clean",
        rejected_container="rejected",
        retained_container="retained",
        token_provider=token_provider,
    )
    resolved: dict[str, tuple[str, ...]] = {}

    async def recording_resolver(hostname: str) -> tuple[str, ...]:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            443,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
        addresses = tuple(sorted({str(record[4][0]) for record in records}))
        resolved[hostname] = addresses
        return addresses

    dns = PrivateDnsVerifier(recording_resolver)
    blob_reader = AzureBlobScanEvidenceClient(storage, dns=dns)
    log_reader = AzureLogAnalyticsScanEvidenceClient(
        workspace_id=workspace_customer_id,
        endpoint="https://api.loganalytics.azure.com",
        token_provider=token_provider,
        dns=dns,
        max_rows=4,
        timeout_seconds=20.0,
    )
    digest = hashlib.sha256(_CANARY).hexdigest()
    requested_at = datetime.now(UTC)
    proof_seed = _required_environment("OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED")
    if re.fullmatch(r"[0-9a-f]{64}", proof_seed) is None:
        raise RuntimeError("scanner-bridge-probe-configuration-incomplete")
    object_version_id = uuid.uuid5(_OBJECT_NAMESPACE, proof_seed)
    object_id = uuid.uuid5(_OBJECT_NAMESPACE, str(object_version_id))
    provider = await _put_exact_canary(
        storage,
        object_id=object_id,
        object_version_id=object_version_id,
        digest=digest,
    )
    version = StorageObjectVersion(
        object_version_id=object_version_id,
        object_id=object_id,
        workspace_id=_WORKSPACE_ID,
        document_version_id=uuid.uuid5(object_version_id, "document-version"),
        security_class="quarantine",
        physical_key=provider.physical_key,
        provider_name="azure",
        provider_version_id=provider.provider_version_id,
        etag=provider.etag,
        byte_size=provider.byte_size,
        content_sha256=provider.content_sha256,
        media_type="text/plain",
        created_at=requested_at,
    )
    request = MalwareScanRequest(
        scan_request_id=uuid.uuid5(object_version_id, provider.provider_version_id),
        object_version_id=object_version_id,
        workspace_id=_WORKSPACE_ID,
        requested_by_user_id=_USER_ID,
        scanner_identity="azure-defender-for-storage",
        scanner_version="defender-storage-dual-source-v1",
        policy_version="mobius-malware-policy-v1",
        request_digest=hashlib.sha256(provider.provider_version_id.encode()).hexdigest(),
        timeout_seconds=3_600,
        trace_id=_TRACE_ID,
        requested_at=requested_at,
        deadline_at=requested_at + timedelta(hours=1),
    )
    try:
        try:
            match = await _poll_dual_source_evidence(
                version=version,
                request=request,
                blob_reader=blob_reader,
                log_reader=log_reader,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
            )
        except ScannerBridgeProbeFailure as exc:
            print(
                json.dumps(
                    {
                        "attemptCount": exc.attempt_count,
                        "failureCode": exc.failure_code,
                        "marker": "SCANNER_RESULT_BRIDGE_FAILED",
                        "schemaVersion": "mobius.scanner-result-bridge.proof-failure.v1",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                flush=True,
            )
            raise
    finally:
        await _remove_exact_canary(storage, provider)
    decision = match.decision
    matched_blob = match.blob
    if decision.verdict != "clean":
        raise RuntimeError("scanner-correlation-scan-result-mismatch")
    dns_integrity = hashlib.sha256(
        json.dumps(resolved, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    storage_hostname = urlparse(account_url).hostname
    if storage_hostname is None:
        raise RuntimeError("scanner-bridge-probe-configuration-incomplete")
    tls_version, tls_integrity = await _prove_private_tls(
        (storage_hostname, "api.loganalytics.azure.com")
    )
    completion = decision.scan_finished_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    print(
        json.dumps(
            {
                "accountNameSha256": _sha256_text(matched_blob.account_name),
                "blobEvidenceSha256": decision.blob_evidence_sha256,
                "blobTagResultSha256": _sha256_text(matched_blob.scan_result),
                "blobUriSha256": _sha256_text(matched_blob.object_uri),
                "completionTimeSha256": _sha256_text(completion),
                "contentSha256": digest,
                "correlationIdSha256": _sha256_text(decision.correlation_id),
                "decision": decision.verdict,
                "dualSourceEvidenceSha256": decision.evidence_integrity_sha256,
                "etagSha256": _sha256_text(matched_blob.etag),
                "logAnalyticsEvidenceSha256": decision.log_analytics_evidence_sha256,
                "logQuerySha256": log_analytics_query_sha256(
                    account_name=matched_blob.account_name,
                    object_uri=matched_blob.object_uri,
                    etag=matched_blob.etag,
                    max_rows=4,
                ),
                "marker": "SCANNER_RESULT_BRIDGE_PROVED",
                "privateDnsEvidenceSha256": dns_integrity,
                "providerVersionSha256": _sha256_text(matched_blob.provider_version_id),
                "residue": "canary-version-deleted",
                "scanRequestIdSha256": _sha256_text(str(request.scan_request_id)),
                "schemaVersion": "mobius.scanner-result-bridge.proof.v1",
                "storageResourceSha256": _sha256_text(account_url),
                "tlsEvidenceSha256": tls_integrity,
                "tlsHostnameSha256": _sha256_text(
                    "|".join((storage_hostname, "api.loganalytics.azure.com"))
                ),
                "tlsVersion": tls_version,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded private scanner-result bridge proof")
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--delay-seconds", type=float, default=30.0)
    arguments = parser.parse_args()
    if not 1 <= arguments.max_attempts <= 120 or not 1.0 <= arguments.delay_seconds <= 60.0:
        raise RuntimeError("scanner-bridge-probe-bounds-invalid")
    return asyncio.run(
        run(
            max_attempts=arguments.max_attempts,
            delay_seconds=arguments.delay_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
