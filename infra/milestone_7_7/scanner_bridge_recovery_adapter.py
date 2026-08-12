"""Production adapter for the two narrow private scanner-bridge stages."""

from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn, cast

from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
)
from preflight.milestone_7_7.cleanup_control_recovery import (
    CleanupControlReprovisionAuthorization,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    authorization_ledger_integrity_sha256,
    load_managed_binding_contract,
    managed_binding_integrity_sha256,
)
from preflight.milestone_7_7.scanner_bridge_recovery import (
    FOUNDATION_STAGE,
    LOG_ANALYTICS_WORKSPACE,
    MONITOR_PRIVATE_ENDPOINT,
    PRIVATE_ENDPOINT_RECOVERY_STAGE,
    PROOF_JOB,
    PROOF_STAGE,
    STORAGE_ACCOUNT,
    TARGET_RESOURCE_GROUP,
    ScannerBridgeRecoveryAuthorization,
    validate_scanner_bridge_recovery_authorization,
)
from preflight.milestone_7_7.scanner_result_bridge import (
    PROVIDER,
    SCHEMA_VERSION,
    TRANSPORT,
    ScannerResultBridgeDeploymentEvidence,
    ScannerResultBridgeEvidence,
    build_scanner_result_bridge_deployment_evidence,
)

RECEIPT_VERSION: Final = "mobius.milestone-7.7.scanner-bridge-recovery-receipt.v1"
RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-bridge-recovery-receipt/v1\0"
)
FOUNDATION_RECEIPT_FILE: Final = "scanner-bridge-foundation.receipt.json"
PRIVATE_ENDPOINT_RECOVERY_RECEIPT_FILE: Final = (
    "scanner-bridge-private-endpoint-recovery.receipt.json"
)
PROOF_RECEIPT_FILE: Final = "scanner-bridge-proof.receipt.json"
EVIDENCE_DOMAIN: Final = b"mobius.milestone-7.7.scanner-bridge-live-proof/v1\0"

STORAGE_API_VERSION: Final = "2025-06-01"
DEFENDER_API_VERSION: Final = "2025-06-01"
DIAGNOSTIC_API_VERSION: Final = "2021-05-01-preview"
AMPLS_API_VERSION: Final = "2021-09-01"
PRIVATE_ENDPOINT_API_VERSION: Final = "2024-10-01"
PRIVATE_DNS_API_VERSION: Final = "2024-06-01"
IDENTITY_API_VERSION: Final = "2024-11-30"
ROLE_API_VERSION: Final = "2022-04-01"
JOB_API_VERSION: Final = "2025-01-01"
EVENT_GRID_API_VERSION: Final = "2025-02-15"

STAGING_LOCATION: Final = "southcentralus"
_USAGE_DECIMAL_INTEGER: Final = re.compile(r"(?:0|[1-9][0-9]{0,19})")
VIRTUAL_NETWORK: Final = "vnet-mobius77-staging"
PRIVATE_ENDPOINT_SUBNET: Final = "snet-mobius77-private-endpoints"
STORAGE_PRIVATE_ENDPOINT: Final = "pe-mobius77-storage"
MANAGED_ENVIRONMENT: Final = "cae-mobius77-staging"
PROOF_CONSOLE_DIAGNOSTIC: Final = "mobius77-scanner-proof-console"
BLOB_TAG_OBSERVATION_MARKER: Final = "SCANNER_BLOB_TAG_OBSERVATION"
BLOB_TAG_OBSERVATION_SCHEMA: Final = (
    "mobius.scanner-result-bridge.blob-tags-observation.v1"
)
BLOB_TAG_NORMALIZATION_PATH: Final = "azure-blob-tags-xml-local-name-v1"
BLOB_RESULT_TAG: Final = "Malware Scanning scan result"
BLOB_SCAN_TIME_TAG: Final = "Malware Scanning scan time UTC"
SCAN_FINISHED_NORMALIZATION_PATH: Final = (
    "trim-z-to-offset-truncate-beyond-microseconds-fromisoformat-utc-v1"
)
SCAN_FINISHED_COMPARISON_CONTRACT: Final = (
    "maximum-common-representable-precision-equality-v1"
)
LEGACY_SCAN_FINISHED_COMPARISON_CONTRACT: Final = "exact-parsed-utc-instant-equality-v1"
PROOF_LOG_TAIL_LINES: Final = 32
PROOF_LOG_OUTPUT_MAX_BYTES: Final = 49_152
FAILURE_EVIDENCE_MAX_BYTES: Final = 32_768
RECONCILIATION_EVIDENCE_MAX_BYTES: Final = 32_768
RETAINED_PROOF_EXECUTION: Final = "caj-mobius77-scanner-proof-jqlmaym"
RETAINED_PROOF_AUTHORIZATION_INTEGRITY: Final = (
    "c357f0e932b9693b144f418c37e494f09fdb43bfbbb737663af175214335c8b8"
)
RETAINED_PROOF_FAILURE_MARKER_INTEGRITY: Final = (
    "c412042f2cdb45eed23f61a299f99dd85ae46715ae49c79c24d900622778c29d"
)
RETAINED_PROOF_TERMINAL_EVIDENCE_INTEGRITY: Final = (
    "af32dd0ec8d8a4e80e756c01e32da54dfcf9bcbbf4c2e3a64e7e8f9475544089"
)
RETAINED_PROOF_BLOB_OBSERVATION_INTEGRITY: Final = (
    "9e2eccc0b0fda84bfde0f59419742da5a271d999f1e181060cf01214a68de5ba"
)
RETAINED_PROOF_IMAGE: Final = (
    "acrmobius7711564669.azurecr.io/opencanvas-api@"
    "sha256:5ab6b370e015628bd36e5f5e6077f723f6854e43f99d8dc4c9cc94a8a04003d7"
)
RETAINED_PROOF_OCI_CONFIG: Final = (
    "sha256:a4c77d21e09563c696901c8720420577befb914514aaa3cb9e8586c142fdb044"
)
RETAINED_PROOF_SOURCE_HEAD: Final = "1fac5e876ff76bdfa393a9c719d769fa4ee117b1"
RETAINED_PROOF_CLEANUP_DEADLINE: Final = "2026-08-12T22:15:00Z"
API_IDENTITY: Final = "id-mobius77-api"
DEFENDER_SCANNER: Final = "StorageDataScanner"
DEFENDER_SCANNER_ROLE: Final = "cd50fd1f-0421-46f2-8cce-afc587dbcc77"
LOG_ANALYTICS_READER_ROLE: Final = "73c42c96-874c-492b-b04d-ab87d138a893"
API_QUARANTINE_ROLE: Final = "43c7bdad-b8f9-4d4b-9881-ae8af70cf269"
API_CLEAN_READER_ROLE: Final = "a59d0f11-7f62-4699-97d9-6c8565ba77a4"
WORKER_QUARANTINE_ROLE: Final = "292f18b2-0b41-4a86-a4af-46cd22d2e52e"
WORKER_CLEAN_ROLE: Final = "6ecfca2a-29a1-4802-a236-706d77995e21"
TAG_WRITE_ACTION: Final = (
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write"
)
PROOF_CONTAINER: Final = "scanner-bridge-proof"
FOUNDATION_POLL_SECONDS: Final = 15.0
FOUNDATION_PROPAGATION_SECONDS: Final = 900.0
EXECUTION_POLL_SECONDS: Final = 15.0
EXECUTION_PROPAGATION_SECONDS: Final = 4_500.0
PROOF_MAX_ATTEMPTS: Final = 120
PROOF_DELAY_SECONDS: Final = 30
PROOF_REPLICA_TIMEOUT_SECONDS: Final = 4_200
PROOF_GRAPH_POLL_SECONDS: Final = 5.0
PROOF_GRAPH_PROPAGATION_SECONDS: Final = 300.0
PROOF_RBAC_POLL_SECONDS: Final = 15.0
PROOF_RBAC_PROPAGATION_SECONDS: Final = 900.0
PROOF_DIAGNOSTIC_POLL_SECONDS: Final = 15.0
PROOF_DIAGNOSTIC_PROPAGATION_SECONDS: Final = 600.0
DELETION_POLL_SECONDS: Final = 5.0
DELETION_PROPAGATION_SECONDS: Final = 180.0
PRIVATE_ENDPOINT_RECOVERY_POLL_SECONDS: Final = 10.0
PRIVATE_ENDPOINT_RECOVERY_PROPAGATION_SECONDS: Final = 300.0
REPROVISION_FOUNDATION_MAXIMUM_DEPLOYMENTS: Final = 3
REPROVISION_FOUNDATION_DEPLOYMENT_SECONDS: Final = 1_800.0
REPROVISION_FOUNDATION_DEPLOYMENT_POLL_SECONDS: Final = 15.0
REPROVISION_FOUNDATION_READ_RETRY_DELAYS: Final = (2.0, 5.0)
REPROVISION_FOUNDATION_TRANSIENT_AZURE_CODES: Final = frozenset(
    {
        "conflict",
        "gateway-timeout",
        "gatewaytimeout",
        "internal-server-error",
        "internalservererror",
        "service-unavailable",
        "serviceunavailable",
        "too-many-requests",
        "toomanyrequests",
    }
)

RETAINED_SUCCESS_PROOF_EXECUTION: Final = "caj-mobius77-scanner-proof-o0e02fj"
RETAINED_SUCCESS_AUTHORIZATION_INTEGRITY: Final = (
    "066c029b71dd4bf25b4f32b255eaecd1b5702795d3c8fd3af8baa2fb1eb677c2"
)
RETAINED_SUCCESS_MARKER_INTEGRITY: Final = (
    "acd390b610e9b71fcf7060167b29980233d27685c5d739d983259c2450e535eb"
)
RETAINED_SUCCESS_IMAGE: Final = (
    "acrmobius7711564669.azurecr.io/opencanvas-api@"
    "sha256:f4cfbdb663f8cfc20318019ab3ae0fbe63a3b07b047fcf00359e1a89cc054d0e"
)
RETAINED_SUCCESS_IMAGE_SOURCE: Final = "56380ce47649a3fc3ce525d921d498dc6bd39a56"
RETAINED_SUCCESS_BUILD_INPUT: Final = (
    "5f1a5b71c45e7b9183ed09205a5bd815b120e3c278026c4238c05834684b4c81"
)
RETAINED_SUCCESS_OCI_CONFIG: Final = (
    "sha256:39d0bf5669c1d89820c2049ea176e645e02366b401610a9a3ea8b1138f17885e"
)
RETAINED_SUCCESS_SOURCE_HEAD: Final = "f023c87b0d68e4cacdba905c15e52ea4986b8ec3"
RETAINED_SUCCESS_LEDGER_INTEGRITY: Final = (
    "3de2dee6435d308cce667a47d9245ea1a187e05e44edf76ec89d6a5e5f6f3157"
)
RETAINED_SUCCESS_DEPLOYMENT: Final = (
    "mobius77-managed-binding-scanner-proof-066c029b71dd4bf2"
)
RETAINED_SUCCESS_NESTED_DEPLOYMENT: Final = (
    "mobius77-managed-binding-scanner-result-bridge"
)
RETAINED_SUCCESS_DEPLOYMENT_TEMPLATE_HASH: Final = "78836874253782165"
RETAINED_SUCCESS_NESTED_TEMPLATE_HASH: Final = "9439949074609830269"
RETAINED_SUCCESS_BINDING_VERSION: Final = (
    "mobius.milestone-7.7.scanner-proof-retained-success-binding.v1"
)
RETAINED_SUCCESS_BINDING_DOMAIN: Final = (
    "solarplexus-mobius/milestone-7.7/scanner-proof-retained-success-binding/v1"
)
FINALIZATION_EVIDENCE_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/acr-tag-finalization-evidence/v1\0"
)

MONITOR_PRIVATE_DNS_BINDINGS: Final = (
    ("privatelink.monitor.azure.com", "link-mobius77-monitor", "monitor"),
    ("privatelink.oms.opinsights.azure.com", "link-mobius77-oms", "oms"),
    ("privatelink.ods.opinsights.azure.com", "link-mobius77-ods", "ods"),
    (
        "privatelink.agentsvc.azure-automation.net",
        "link-mobius77-agent",
        "agent",
    ),
    ("privatelink.blob.core.windows.net", "link-mobius77-storage", "blob"),
)
MONITOR_REQUIRED_MEMBERS: Final = frozenset(
    {
        "agent-southcentralus",
        "agentsolutionpackstore",
        "api",
        "dce-global",
        "diagservicesquery",
        "global.in.ai",
        "live",
        "ods-southcentralus",
        "oms-southcentralus",
        "profiler",
        "snapshot",
    }
)

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_FAILURE_CODE = re.compile(r"^scanner-[a-z0-9]+(?:-[a-z0-9]+)*$")
_SANITIZED_TIMESTAMP = re.compile(r"^[0-9TtZz:+. -]{1,128}$")
_REPRESENTED_TIMESTAMP = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt ]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,32}))?"
    r"(?P<timezone>[Zz]|[+-]\d{2}:\d{2})$"
)
_BLOB_TAG_DECISIONS: Final = frozenset(
    {
        "accepted",
        "rejected-empty",
        "rejected-http-status",
        "rejected-observability-gap",
        "rejected-parser-normalization",
        "rejected-required-key-missing",
        "rejected-unexpected-key",
        "rejected-version-mismatch",
    }
)
_BLOB_TAG_VERSION_PATHS: Final = frozenset(
    {
        "request-version-id-plus-if-match",
        "response-etag",
        "response-unavailable",
        "response-version-id",
        "response-version-id-and-etag",
    }
)
_BLOB_TAG_FAILURE_DECISIONS: Final = {
    "scanner-blob-tags-empty": "rejected-empty",
    "scanner-blob-tags-http-status": "rejected-http-status",
    "scanner-blob-tags-key-missing": "rejected-required-key-missing",
    "scanner-blob-tags-key-unexpected": "rejected-unexpected-key",
    "scanner-blob-tags-observability-gap": "rejected-observability-gap",
    "scanner-blob-tags-parser-normalization-failed": "rejected-parser-normalization",
    "scanner-blob-tags-version-mismatch": "rejected-version-mismatch",
}
_PROVIDER_REQUIREMENTS: Final = (
    ("Microsoft.Storage", "storageAccounts", STORAGE_API_VERSION, True),
    ("Microsoft.Security", "defenderForStorageSettings", DEFENDER_API_VERSION, False),
    ("Microsoft.Insights", "diagnosticSettings", DIAGNOSTIC_API_VERSION, False),
    ("Microsoft.Insights", "privateLinkScopes", AMPLS_API_VERSION, False),
    ("Microsoft.OperationalInsights", "workspaces", "2026-03-01", True),
    ("Microsoft.Network", "privateEndpoints", PRIVATE_ENDPOINT_API_VERSION, True),
    ("Microsoft.Network", "privateDnsZones", PRIVATE_DNS_API_VERSION, False),
    ("Microsoft.ManagedIdentity", "userAssignedIdentities", IDENTITY_API_VERSION, True),
    ("Microsoft.EventGrid", "systemTopics", EVENT_GRID_API_VERSION, True),
    ("Microsoft.App", "jobs", JOB_API_VERSION, True),
)


class ScannerBridgeRecoveryExecutionError(RuntimeError):
    """Raised when production mutation or authoritative reconciliation is unproved."""


@dataclass(frozen=True, slots=True)
class _FoundationReadback:
    api_principal_id: str
    worker_principal_id: str
    worker_client_id: str
    workspace_customer_id: str
    provider_topic_id: str
    provider_proof_integrity: str
    diagnostic_proof_integrity: str
    rbac_proof_integrity: str
    tag_write_denial_integrity: str
    private_path_control_plane_integrity: str
    inventory_integrity: str


@dataclass(frozen=True, slots=True)
class _ReprovisionFoundationScope:
    """Exact scanner-foundation view of the already-consumed Generation-4 grant."""

    stage: str
    subscriptionId: str
    targetResourceGroupId: str
    storageAccountId: str
    logAnalyticsWorkspaceId: str
    workerIdentityId: str
    privateLinkScopeId: str
    monitorPrivateEndpointId: str
    proofJobId: None
    proofRoleDefinitionId: None
    apiImageDigest: None


type _FoundationScope = ScannerBridgeRecoveryAuthorization | _ReprovisionFoundationScope


def _fail(code: str) -> NoReturn:
    raise ScannerBridgeRecoveryExecutionError(code)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(code)


def _outside_repository(path: Path, code: str) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        _fail(code)
    return resolved


def _json_object(value: JsonValue | None, code: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        _fail(code)
    return value


def _canonical_hash(value: JsonValue, domain: str) -> str:
    return integrity_sha256(value, domain.encode() + b"\0")


def _scanner_runtime_hash(value: JsonValue, domain: str) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(domain.encode() + b"\0" + canonical).hexdigest()


def _blob_tag_observation_hash(value: JsonValue) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(
        b"mobius.scanner-bridge.blob-tag-observation.v1\0" + canonical
    ).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _same_resource_id(value: JsonValue | None, expected: str) -> bool:
    return isinstance(value, str) and value.casefold() == expected.casefold()


def _claim_authorization(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    receipt_directory: Path,
    now_utc: datetime,
) -> Path:
    directory = _outside_repository(
        receipt_directory, "scanner-bridge-receipts-inside-repository"
    )
    directory.mkdir(parents=True, exist_ok=True)
    if authorization.stage == FOUNDATION_STAGE:
        filename = FOUNDATION_RECEIPT_FILE
    elif authorization.stage == PRIVATE_ENDPOINT_RECOVERY_STAGE:
        filename = PRIVATE_ENDPOINT_RECOVERY_RECEIPT_FILE
    else:
        filename = PROOF_RECEIPT_FILE
    path = directory / filename
    body: dict[str, JsonValue] = {
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "claimedAtUtc": _format_utc(now_utc),
        "receiptVersion": RECEIPT_VERSION,
        "replayDecision": "deny",
        "repositoryHead": authorization.repositoryHead,
        "stage": authorization.stage,
    }
    receipt: dict[str, JsonValue] = {
        **body,
        "receiptIntegritySha256": integrity_sha256(body, RECEIPT_DOMAIN),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-bridge-authorization-already-consumed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("scanner-bridge-receipt-write-failed")
    return path


def _write_evidence(
    path: Path, evidence: ScannerResultBridgeDeploymentEvidence
) -> None:
    resolved = _outside_repository(path, "scanner-bridge-evidence-inside-repository")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    value = cast(JsonValue, evidence.canonical())
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-bridge-evidence-already-exists")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("scanner-bridge-evidence-write-failed")


def _write_failure_evidence(
    path: Path,
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    execution_name: str,
    execution: Mapping[str, str | None],
    marker: Mapping[str, JsonValue],
    blob_tag_observation: Mapping[str, JsonValue] | None,
    observed_at: datetime,
) -> None:
    resolved = _outside_repository(path, "scanner-bridge-evidence-inside-repository")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    terminal_evidence = marker.get("terminalEvidence")
    body = cast(
        dict[str, JsonValue],
        {
            "attemptCount": marker["attemptCount"],
            "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
            "blobTagObservation": (
                dict(blob_tag_observation) if blob_tag_observation is not None else None
            ),
            "blobTagObservationCount": marker["blobTagObservationCount"],
            "executionEndAtUtc": execution["endTime"],
            "executionNameSha256": _hash_text(execution_name),
            "executionStartAtUtc": execution["startTime"],
            "executionStatus": execution["status"],
            "finalBoundedErrorCode": marker["failureCode"],
            "failureCode": marker["failureCode"],
            "marker": marker["marker"],
            "markerIntegritySha256": marker["markerIntegritySha256"],
            "observedAtUtc": _format_utc(observed_at),
            "proofExecutionCount": 1,
            "proofExecutionOrdinal": authorization.proofExecutionOrdinal,
            "scanFinishedComparison": (
                dict(terminal_evidence)
                if isinstance(terminal_evidence, Mapping)
                else None
            ),
            "schemaVersion": "mobius.scanner-result-bridge.failure-evidence.v3",
            "terminalEdge": marker["failureCode"],
            "terminalLogSummary": {
                "maximumSerializedBytes": PROOF_LOG_OUTPUT_MAX_BYTES,
                "rawHistoryRetained": False,
                "retentionDecision": "final-integrity-bound-markers-only",
                "tailLineLimit": PROOF_LOG_TAIL_LINES,
            },
        },
    )
    value: dict[str, JsonValue] = {
        **body,
        "failureEvidenceIntegritySha256": _canonical_hash(
            cast(JsonValue, body), "mobius.scanner-bridge.failure-evidence.v3"
        ),
    }
    serialized = canonical_bytes(cast(JsonValue, value))
    if len(serialized) > FAILURE_EVIDENCE_MAX_BYTES:
        _fail("scanner-proof-failure-evidence-oversized")
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-bridge-evidence-already-exists")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("scanner-bridge-evidence-write-failed")


def _validate_managed_binding(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    cleanup_deadline_utc: str | None = None,
) -> dict[str, JsonValue]:
    contract = load_managed_binding_contract()
    resources = contract.get("resources")
    groups = contract.get("resourceGroups")
    cleanup = contract.get("cleanupExecution")
    if (
        not isinstance(resources, dict)
        or not isinstance(groups, dict)
        or not isinstance(cleanup, dict)
    ):
        _fail("scanner-bridge-managed-binding-malformed")
    exact = {
        "target-group": groups.get("target") == TARGET_RESOURCE_GROUP,
        "storage-account": STORAGE_ACCOUNT == "stmobius7711564669",
        "workspace": resources.get("logAnalyticsWorkspace") == LOG_ANALYTICS_WORKSPACE,
        "cleanup-account": resources.get("cleanupAutomationAccount")
        == "aa-mobius77-cleanup-recovery",
        "cleanup-deadline": cleanup.get("deadlineUtc")
        == (cleanup_deadline_utc or authorization.cleanupDeadlineUtc),
        "cleanup-target": cleanup.get("targetResourceGroup") == TARGET_RESOURCE_GROUP,
    }
    if not all(exact.values()):
        _fail("scanner-bridge-managed-binding-drift")
    return contract


def _deployment_binding(
    authorization: ScannerBridgeRecoveryAuthorization,
    contract: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "authorizationId": (
            f"scanner-bridge-{authorization.stage}-"
            f"{authorization.authorizationIntegritySha256[:24]}"
        ),
        "ledgerIntegritySha256": authorization.authorizationIntegritySha256,
        "managedBindingIntegritySha256": managed_binding_integrity_sha256(contract),
        "repositoryHead": authorization.repositoryHead,
    }


def _verify_provider_api_versions(subscription_id: str) -> None:
    for namespace, resource_type, version, regional in _PROVIDER_REQUIREMENTS:
        value = lifecycle._run(
            (
                "az",
                "provider",
                "show",
                "--namespace",
                namespace,
                "--subscription",
                subscription_id,
                "--query",
                (
                    "{registrationState:registrationState,"
                    f"resourceType:resourceTypes[?resourceType=='{resource_type}']|[0]}}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        row = _json_object(value, "scanner-bridge-provider-metadata-malformed")
        metadata = row.get("resourceType")
        if row.get("registrationState") != "Registered" or not isinstance(
            metadata, dict
        ):
            _fail("scanner-bridge-provider-unavailable")
        versions = metadata.get("apiVersions")
        locations = metadata.get("locations")
        if (
            metadata.get("resourceType") != resource_type
            or not isinstance(versions, list)
            or version not in versions
            or not isinstance(locations, list)
        ):
            _fail("scanner-bridge-provider-api-version-unavailable")
        normalized_locations = {
            location.replace(" ", "").casefold()
            for location in locations
            if isinstance(location, str)
        }
        if regional and STAGING_LOCATION not in normalized_locations:
            _fail("scanner-bridge-provider-region-unavailable")


def _network_usage_integer(value: JsonValue) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and _USAGE_DECIMAL_INTEGER.fullmatch(value) is not None:
        return int(value)
    _fail("scanner-bridge-network-quota-malformed")


def _verify_network_capacity(subscription_id: str) -> None:
    value = lifecycle._run(
        (
            "az",
            "network",
            "list-usages",
            "--location",
            STAGING_LOCATION,
            "--subscription",
            subscription_id,
            "--query",
            "[?name.value=='PrivateEndpoints'].{current:currentValue,limit:limit}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        _fail("scanner-bridge-network-quota-malformed")
    current = _network_usage_integer(value[0].get("current"))
    limit = _network_usage_integer(value[0].get("limit"))
    if current + 2 > limit:
        _fail("scanner-bridge-network-quota-insufficient")


def _rest_get(resource_id: str, api_version: str, query: str) -> dict[str, JsonValue]:
    value = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={api_version}",
            "--query",
            query,
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    return _json_object(value, "scanner-bridge-resource-readback-malformed")


def _rest_collection(resource_id: str, api_version: str, query: str) -> JsonValue:
    return lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={api_version}",
            "--query",
            query,
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )


def _rest_put(
    resource_id: str,
    api_version: str,
    body: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    value = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "put",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={api_version}",
            "--body",
            json.dumps(body, separators=(",", ":"), sort_keys=True),
            "--query",
            "{id:id,provisioningState:properties.provisioningState}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    return _json_object(value, "scanner-private-endpoint-recovery-write-malformed")


def _monitor_recovery_resource_ids(
    authorization: _FoundationScope,
) -> tuple[str, str, dict[str, str]]:
    vnet_id = (
        f"{authorization.targetResourceGroupId}/providers/Microsoft.Network/"
        f"virtualNetworks/{VIRTUAL_NETWORK}"
    )
    subnet_id = f"{vnet_id}/subnets/{PRIVATE_ENDPOINT_SUBNET}"
    zone_ids = {
        zone: (
            f"{authorization.targetResourceGroupId}/providers/Microsoft.Network/"
            f"privateDnsZones/{zone}"
        )
        for zone, _link, _config in MONITOR_PRIVATE_DNS_BINDINGS
    }
    return vnet_id, subnet_id, zone_ids


def _exact_monitor_private_endpoint_recovery_state(
    authorization: _FoundationScope,
) -> dict[str, JsonValue]:
    target = authorization.targetResourceGroupId
    vnet_id, subnet_id, zone_ids = _monitor_recovery_resource_ids(authorization)
    endpoints = _rest_collection(
        f"{target}/providers/Microsoft.Network/privateEndpoints",
        PRIVATE_ENDPOINT_API_VERSION,
        "value[].{id:id,name:name,location:location,"
        "provisioningState:properties.provisioningState,"
        "subnetId:properties.subnet.id,networkInterfaceIds:properties.networkInterfaces[].id,"
        "connections:properties.privateLinkServiceConnections[].{"
        "name:name,serviceId:properties.privateLinkServiceId,"
        "groupIds:properties.groupIds,status:properties.privateLinkServiceConnectionState.status,"
        "provisioningState:properties.provisioningState},tags:tags}",
    )
    if not isinstance(endpoints, list) or any(
        not isinstance(row, dict) for row in endpoints
    ):
        _fail("scanner-private-endpoint-recovery-inventory-malformed")
    matching_endpoints = [
        cast(dict[str, JsonValue], row)
        for row in endpoints
        if _same_resource_id(
            cast(dict[str, JsonValue], row).get("id"),
            authorization.monitorPrivateEndpointId,
        )
    ]
    if len(matching_endpoints) != 1:
        _fail("scanner-private-endpoint-recovery-endpoint-count-invalid")
    endpoint = matching_endpoints[0]
    connections = endpoint.get("connections")
    network_interface_ids = endpoint.get("networkInterfaceIds")
    tags = endpoint.get("tags")
    if (
        endpoint.get("name") != MONITOR_PRIVATE_ENDPOINT
        or endpoint.get("location") != STAGING_LOCATION
        or endpoint.get("provisioningState") not in {"Failed", "Succeeded"}
        or not _same_resource_id(endpoint.get("subnetId"), subnet_id)
        or not isinstance(connections, list)
        or len(connections) != 1
        or not isinstance(connections[0], dict)
        or connections[0].get("name") != "azuremonitor"
        or not _same_resource_id(
            connections[0].get("serviceId"), authorization.privateLinkScopeId
        )
        or connections[0].get("groupIds") != ["azuremonitor"]
        or connections[0].get("status") != "Approved"
        or connections[0].get("provisioningState") not in {"Failed", "Succeeded"}
        or not isinstance(network_interface_ids, list)
        or len(network_interface_ids) != 1
        or not isinstance(network_interface_ids[0], str)
        or not isinstance(tags, dict)
    ):
        _fail("scanner-private-endpoint-recovery-endpoint-drift")
    try:
        lifecycle._verify_recovered_cleanup_tags(tags)
    except lifecycle.LifecycleError:
        _fail("scanner-private-endpoint-recovery-tags-unproved")

    subnet = _rest_get(
        subnet_id,
        PRIVATE_ENDPOINT_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState,"
        "addressPrefix:properties.addressPrefix,"
        "privateEndpointNetworkPolicies:properties.privateEndpointNetworkPolicies,"
        "privateLinkServiceNetworkPolicies:properties.privateLinkServiceNetworkPolicies}",
    )
    if (
        not _same_resource_id(subnet.get("id"), subnet_id)
        or subnet.get("provisioningState") != "Succeeded"
        or subnet.get("addressPrefix") != "10.77.2.0/24"
        or subnet.get("privateEndpointNetworkPolicies") != "Disabled"
        or subnet.get("privateLinkServiceNetworkPolicies") != "Enabled"
    ):
        _fail("scanner-private-endpoint-recovery-subnet-unproved")

    ampls = _rest_get(
        authorization.privateLinkScopeId,
        AMPLS_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState,"
        "queryAccessMode:properties.accessModeSettings.queryAccessMode,"
        "ingestionAccessMode:properties.accessModeSettings.ingestionAccessMode,"
        "exclusions:properties.accessModeSettings.exclusions,"
        "connections:properties.privateEndpointConnections[].{"
        "id:id,privateEndpointId:properties.privateEndpoint.id,"
        "status:properties.privateLinkServiceConnectionState.status,"
        "actionsRequired:properties.privateLinkServiceConnectionState.actionsRequired,"
        "provisioningState:properties.provisioningState}}",
    )
    ampls_connections = ampls.get("connections")
    if (
        not _same_resource_id(ampls.get("id"), authorization.privateLinkScopeId)
        or ampls.get("provisioningState") != "Succeeded"
        or ampls.get("queryAccessMode") != "PrivateOnly"
        or ampls.get("ingestionAccessMode") != "PrivateOnly"
        or ampls.get("exclusions") != []
        or not isinstance(ampls_connections, list)
        or len(ampls_connections) != 1
        or not isinstance(ampls_connections[0], dict)
        or not _same_resource_id(
            ampls_connections[0].get("privateEndpointId"),
            authorization.monitorPrivateEndpointId,
        )
        or ampls_connections[0].get("status") != "Approved"
        or ampls_connections[0].get("actionsRequired") != "None"
        or ampls_connections[0].get("provisioningState") != "Succeeded"
    ):
        _fail("scanner-private-endpoint-recovery-ampls-unproved")

    nics = _rest_collection(
        f"{target}/providers/Microsoft.Network/networkInterfaces",
        PRIVATE_ENDPOINT_API_VERSION,
        "value[].{id:id,name:name,provisioningState:properties.provisioningState,"
        "privateEndpointId:properties.privateEndpoint.id,"
        "ipConfigurations:properties.ipConfigurations[].{"
        "privateIPAddress:properties.privateIPAddress,"
        "provisioningState:properties.provisioningState,"
        "subnetId:properties.subnet.id,"
        "requiredMemberName:properties.privateLinkConnectionProperties.requiredMemberName}}",
    )
    if not isinstance(nics, list) or any(not isinstance(row, dict) for row in nics):
        _fail("scanner-private-endpoint-recovery-nic-inventory-malformed")
    matching_nics = [
        cast(dict[str, JsonValue], row)
        for row in nics
        if _same_resource_id(
            cast(dict[str, JsonValue], row).get("privateEndpointId"),
            authorization.monitorPrivateEndpointId,
        )
    ]
    if len(matching_nics) != 1:
        _fail("scanner-private-endpoint-recovery-nic-count-invalid")
    nic = matching_nics[0]
    ip_configurations = nic.get("ipConfigurations")
    if (
        not _same_resource_id(nic.get("id"), network_interface_ids[0])
        or nic.get("provisioningState") != "Succeeded"
        or not isinstance(ip_configurations, list)
        or len(ip_configurations) != len(MONITOR_REQUIRED_MEMBERS)
        or any(not isinstance(row, dict) for row in ip_configurations)
    ):
        _fail("scanner-private-endpoint-recovery-nic-unproved")
    member_names: set[str] = set()
    private_addresses: set[str] = set()
    approved_network = ipaddress.ip_network("10.77.2.0/24")
    for raw in ip_configurations:
        row = cast(dict[str, JsonValue], raw)
        member = row.get("requiredMemberName")
        address = row.get("privateIPAddress")
        if (
            row.get("provisioningState") != "Succeeded"
            or not _same_resource_id(row.get("subnetId"), subnet_id)
            or not isinstance(member, str)
            or not isinstance(address, str)
        ):
            _fail("scanner-private-endpoint-recovery-nic-unproved")
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError:
            _fail("scanner-private-endpoint-recovery-nic-unproved")
        if parsed_address not in approved_network:
            _fail("scanner-private-endpoint-recovery-nic-unproved")
        member_names.add(member)
        private_addresses.add(address)
    if member_names != MONITOR_REQUIRED_MEMBERS or len(private_addresses) != len(
        MONITOR_REQUIRED_MEMBERS
    ):
        _fail("scanner-private-endpoint-recovery-nic-unproved")

    zone_links: list[dict[str, JsonValue]] = []
    for zone, link, _config in MONITOR_PRIVATE_DNS_BINDINGS:
        link_id = f"{zone_ids[zone]}/virtualNetworkLinks/{link}"
        row = _rest_get(
            link_id,
            PRIVATE_DNS_API_VERSION,
            "{id:id,provisioningState:properties.provisioningState,"
            "registrationEnabled:properties.registrationEnabled,"
            "virtualNetworkId:properties.virtualNetwork.id}",
        )
        if (
            not _same_resource_id(row.get("id"), link_id)
            or row.get("provisioningState") != "Succeeded"
            or row.get("registrationEnabled") is not False
            or not _same_resource_id(row.get("virtualNetworkId"), vnet_id)
        ):
            _fail("scanner-private-endpoint-recovery-dns-link-unproved")
        zone_links.append(row)

    zone_groups = _rest_collection(
        f"{authorization.monitorPrivateEndpointId}/privateDnsZoneGroups",
        PRIVATE_ENDPOINT_API_VERSION,
        "value[].{id:id,name:name,provisioningState:properties.provisioningState,"
        "zoneIds:properties.privateDnsZoneConfigs[].properties.privateDnsZoneId}",
    )
    if not isinstance(zone_groups, list) or any(
        not isinstance(row, dict) for row in zone_groups
    ):
        _fail("scanner-private-endpoint-recovery-zone-group-inventory-malformed")
    expected_zone_group_id = (
        f"{authorization.monitorPrivateEndpointId}/privateDnsZoneGroups/default"
    )
    if len(zone_groups) > 1:
        _fail("scanner-private-endpoint-recovery-zone-group-count-invalid")
    zone_group_state: JsonValue = None
    if zone_groups:
        zone_group = cast(dict[str, JsonValue], zone_groups[0])
        observed_zone_ids = zone_group.get("zoneIds")
        if (
            zone_group.get("name") != "default"
            or not _same_resource_id(zone_group.get("id"), expected_zone_group_id)
            or zone_group.get("provisioningState") not in {"Failed", "Succeeded"}
            or not isinstance(observed_zone_ids, list)
            or {str(value).casefold() for value in observed_zone_ids}
            != {value.casefold() for value in zone_ids.values()}
        ):
            _fail("scanner-private-endpoint-recovery-zone-group-drift")
        zone_group_state = zone_group["provisioningState"]

    projection: dict[str, JsonValue] = {
        "amplsConnectionCount": len(ampls_connections),
        "endpointId": authorization.monitorPrivateEndpointId,
        "endpointProvisioningState": endpoint["provisioningState"],
        "endpointTags": tags,
        "networkInterfaceId": nic["id"],
        "networkInterfaceProvisioningState": nic["provisioningState"],
        "pendingConnectionCount": 0,
        "privateDnsZoneGroupProvisioningState": zone_group_state,
        "privateDnsZoneLinkCount": len(zone_links),
        "subnetId": subnet_id,
    }
    projection["integritySha256"] = _canonical_hash(
        cast(JsonValue, projection),
        "mobius.scanner-bridge.private-endpoint-recovery-state.v1",
    )
    return projection


def _monitor_private_endpoint_write_body(
    authorization: _FoundationScope,
    state: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    _vnet_id, subnet_id, _zone_ids = _monitor_recovery_resource_ids(authorization)
    tags = state.get("endpointTags")
    if not isinstance(tags, dict):
        _fail("scanner-private-endpoint-recovery-tags-unproved")
    return {
        "location": STAGING_LOCATION,
        "properties": {
            "privateLinkServiceConnections": [
                {
                    "name": "azuremonitor",
                    "properties": {
                        "groupIds": ["azuremonitor"],
                        "privateLinkServiceId": authorization.privateLinkScopeId,
                    },
                }
            ],
            "subnet": {"id": subnet_id},
        },
        "tags": tags,
    }


def _monitor_private_dns_zone_group_write_body(
    authorization: _FoundationScope,
) -> dict[str, JsonValue]:
    _vnet_id, _subnet_id, zone_ids = _monitor_recovery_resource_ids(authorization)
    return {
        "properties": {
            "privateDnsZoneConfigs": [
                {
                    "name": config,
                    "properties": {"privateDnsZoneId": zone_ids[zone]},
                }
                for zone, _link, config in MONITOR_PRIVATE_DNS_BINDINGS
            ]
        }
    }


def _wait_for_monitor_private_endpoint(
    authorization: _FoundationScope,
    *,
    ambiguous_error_code: str | None,
) -> None:
    _vnet_id, subnet_id, _zone_ids = _monitor_recovery_resource_ids(authorization)
    deadline = time.monotonic() + PRIVATE_ENDPOINT_RECOVERY_PROPAGATION_SECONDS
    while True:
        try:
            row = _rest_get(
                authorization.monitorPrivateEndpointId,
                PRIVATE_ENDPOINT_API_VERSION,
                "{id:id,provisioningState:properties.provisioningState,"
                "subnetId:properties.subnet.id,connections:"
                "properties.privateLinkServiceConnections[].{"
                "serviceId:properties.privateLinkServiceId,groupIds:properties.groupIds,"
                "status:properties.privateLinkServiceConnectionState.status,"
                "provisioningState:properties.provisioningState}}",
            )
            connections = row.get("connections")
            if (
                _same_resource_id(row.get("id"), authorization.monitorPrivateEndpointId)
                and row.get("provisioningState") == "Succeeded"
                and _same_resource_id(row.get("subnetId"), subnet_id)
                and isinstance(connections, list)
                and len(connections) == 1
                and isinstance(connections[0], dict)
                and _same_resource_id(
                    connections[0].get("serviceId"), authorization.privateLinkScopeId
                )
                and connections[0].get("groupIds") == ["azuremonitor"]
                and connections[0].get("status") == "Approved"
                and connections[0].get("provisioningState") == "Succeeded"
            ):
                return
        except lifecycle.AzureCommandError as exc:
            if not _not_found(exc):
                ambiguous_error_code = exc.sanitized_azure_error_code
        if time.monotonic() >= deadline:
            code = ambiguous_error_code or "provider-terminal-failed"
            _fail(f"scanner-private-endpoint-recovery-azure-{code}")
        time.sleep(PRIVATE_ENDPOINT_RECOVERY_POLL_SECONDS)


def _wait_for_monitor_private_dns_zone_group(
    authorization: _FoundationScope,
    *,
    ambiguous_error_code: str | None,
) -> None:
    _vnet_id, _subnet_id, zone_ids = _monitor_recovery_resource_ids(authorization)
    group_id = f"{authorization.monitorPrivateEndpointId}/privateDnsZoneGroups/default"
    deadline = time.monotonic() + PRIVATE_ENDPOINT_RECOVERY_PROPAGATION_SECONDS
    while True:
        try:
            row = _rest_get(
                group_id,
                PRIVATE_ENDPOINT_API_VERSION,
                "{id:id,provisioningState:properties.provisioningState,"
                "zoneIds:properties.privateDnsZoneConfigs[].properties.privateDnsZoneId}",
            )
            observed_zone_ids = row.get("zoneIds")
            if (
                _same_resource_id(row.get("id"), group_id)
                and row.get("provisioningState") == "Succeeded"
                and isinstance(observed_zone_ids, list)
                and {str(value).casefold() for value in observed_zone_ids}
                == {value.casefold() for value in zone_ids.values()}
            ):
                return
        except lifecycle.AzureCommandError as exc:
            if not _not_found(exc):
                ambiguous_error_code = exc.sanitized_azure_error_code
        if time.monotonic() >= deadline:
            code = ambiguous_error_code or "dns-zone-group-terminal-failed"
            _fail(f"scanner-private-endpoint-recovery-azure-{code}")
        time.sleep(PRIVATE_ENDPOINT_RECOVERY_POLL_SECONDS)


def _repair_exact_monitor_private_endpoint(
    authorization: _FoundationScope,
) -> dict[str, JsonValue]:
    before = _exact_monitor_private_endpoint_recovery_state(authorization)
    endpoint_mutation_issued = False
    zone_group_mutation_issued = False
    if before.get("endpointProvisioningState") != "Succeeded":
        endpoint_mutation_issued = True
        ambiguous_code: str | None = None
        try:
            _rest_put(
                authorization.monitorPrivateEndpointId,
                PRIVATE_ENDPOINT_API_VERSION,
                _monitor_private_endpoint_write_body(authorization, before),
            )
        except lifecycle.AzureCommandError as exc:
            ambiguous_code = exc.sanitized_azure_error_code
        _wait_for_monitor_private_endpoint(
            authorization,
            ambiguous_error_code=ambiguous_code,
        )

    after_endpoint = _exact_monitor_private_endpoint_recovery_state(authorization)
    if after_endpoint.get("privateDnsZoneGroupProvisioningState") != "Succeeded":
        zone_group_mutation_issued = True
        ambiguous_code = None
        group_id = (
            f"{authorization.monitorPrivateEndpointId}/privateDnsZoneGroups/default"
        )
        try:
            _rest_put(
                group_id,
                PRIVATE_ENDPOINT_API_VERSION,
                _monitor_private_dns_zone_group_write_body(authorization),
            )
        except lifecycle.AzureCommandError as exc:
            ambiguous_code = exc.sanitized_azure_error_code
        _wait_for_monitor_private_dns_zone_group(
            authorization,
            ambiguous_error_code=ambiguous_code,
        )

    after = _exact_monitor_private_endpoint_recovery_state(authorization)
    if (
        after.get("endpointProvisioningState") != "Succeeded"
        or after.get("networkInterfaceProvisioningState") != "Succeeded"
        or after.get("privateDnsZoneGroupProvisioningState") != "Succeeded"
        or after.get("pendingConnectionCount") != 0
    ):
        _fail("scanner-private-endpoint-recovery-readback-unproved")
    return {
        "endpointMutationIssued": endpoint_mutation_issued,
        "preRecoveryIntegritySha256": before["integritySha256"],
        "postRecoveryIntegritySha256": after["integritySha256"],
        "zoneGroupMutationIssued": zone_group_mutation_issued,
    }


def _verify_monitor_private_tls_path(workspace_customer_id: str) -> str:
    hostnames = (
        "api.monitor.azure.com",
        f"{workspace_customer_id}.oms.opinsights.azure.com",
        f"{workspace_customer_id}.ods.opinsights.azure.com",
    )
    for hostname in hostnames:
        lifecycle._private_tls_endpoint(hostname)
    return _canonical_hash(
        cast(JsonValue, list(hostnames)),
        "mobius.scanner-bridge.private-endpoint-live-path.v1",
    )


def _output_values(value: JsonValue | None) -> dict[str, JsonValue]:
    raw = _json_object(value, "scanner-bridge-deployment-output-malformed")
    result: dict[str, JsonValue] = {}
    for name, projection in raw.items():
        if not isinstance(projection, dict) or set(projection) - {"type", "value"}:
            _fail("scanner-bridge-deployment-output-malformed")
        result[name] = projection.get("value")
    return result


def _read_deployment_outputs(
    *, subscription_id: str, stage: str, binding: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    deployment_name = lifecycle._deployment_name(stage, binding)
    deadline = time.monotonic() + 120.0
    while True:
        try:
            raw = lifecycle._run(
                (
                    "az",
                    "deployment",
                    "sub",
                    "show",
                    "--name",
                    deployment_name,
                    "--subscription",
                    subscription_id,
                    "--query",
                    "properties.outputs",
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                require_json=True,
            )
            return _output_values(raw)
        except (lifecycle.AzureCommandError, ScannerBridgeRecoveryExecutionError):
            if time.monotonic() >= deadline:
                _fail("scanner-bridge-deployment-reconciliation-unproved")
            time.sleep(5.0)


def _validate_deployment_outputs(
    authorization: _FoundationScope,
    outputs: Mapping[str, JsonValue],
) -> str | None:
    exact: dict[str, JsonValue] = {
        "deploymentStage": authorization.stage,
        "deploymentEnabled": False,
        "managedBindingDeploymentEnabled": True,
        "targetResourceGroupName": TARGET_RESOURCE_GROUP,
        "scannerBridgeFoundationDeployed": True,
        "scannerBridgeTransport": TRANSPORT,
        "scannerBridgeStorageAccountId": authorization.storageAccountId,
        "scannerBridgePrivateLinkScopeId": authorization.privateLinkScopeId,
        "scannerBridgePrivateEndpointId": authorization.monitorPrivateEndpointId,
        "scannerBridgeWorkerIdentityId": authorization.workerIdentityId,
        "scannerBridgeWorkerTagWriteAuthorized": False,
        "defaultProvisioningAuthorized": False,
        "secretValueAccessAuthorized": False,
        "storageAccountUrl": f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/",
    }
    if any(outputs.get(key) != value for key, value in exact.items()):
        _fail("scanner-bridge-deployment-output-drift")
    principal_id = outputs.get("scannerBridgeWorkerPrincipalId")
    if not isinstance(principal_id, str) or _UUID.fullmatch(principal_id) is None:
        _fail("scanner-bridge-worker-principal-unproved")
    if authorization.stage == FOUNDATION_STAGE:
        empty = {
            "scannerBridgeProofJobName": "",
            "scannerBridgeProofJobId": "",
            "scannerBridgeTemporaryRoleId": "",
            "scannerBridgeTemporaryRoleAssignmentId": "",
            "scannerBridgeProofImageDigest": "",
        }
        if any(outputs.get(key) != value for key, value in empty.items()):
            _fail("scanner-foundation-proof-authority-reachable")
        return None
    proof_exact: dict[str, JsonValue] = {
        "scannerBridgeProofJobName": PROOF_JOB,
        "scannerBridgeProofJobId": authorization.proofJobId,
        "scannerBridgeTemporaryRoleId": authorization.proofRoleDefinitionId,
        "scannerBridgeProofImageDigest": authorization.apiImageDigest,
    }
    if any(outputs.get(key) != value for key, value in proof_exact.items()):
        _fail("scanner-proof-deployment-output-drift")
    assignment_id = outputs.get("scannerBridgeTemporaryRoleAssignmentId")
    quarantine_scope = (
        f"{authorization.storageAccountId}/blobServices/default/containers/quarantine"
    )
    prefix = f"{quarantine_scope}/providers/Microsoft.Authorization/roleAssignments/"
    if not isinstance(assignment_id, str) or not assignment_id.casefold().startswith(
        prefix.casefold()
    ):
        _fail("scanner-proof-role-assignment-output-invalid")
    return assignment_id


def _role_assignment_rows(
    subscription_id: str,
    *,
    principal_id: str | None = None,
    scope: str | None = None,
) -> list[dict[str, str]]:
    argv: list[str] = ["az", "role", "assignment", "list"]
    if principal_id is not None:
        argv.extend(("--assignee-object-id", principal_id, "--all"))
    if scope is not None:
        argv.extend(("--scope", scope, "--include-inherited"))
    if principal_id is None and scope is None:
        argv.append("--all")
    argv.extend(
        (
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    value = lifecycle._run(tuple(argv), require_json=True)
    if not isinstance(value, list):
        _fail("scanner-bridge-role-assignment-readback-malformed")
    result: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "principalId",
            "roleDefinitionId",
            "scope",
        }:
            _fail("scanner-bridge-role-assignment-readback-malformed")
        if not all(isinstance(item, str) and item for item in row.values()):
            _fail("scanner-bridge-role-assignment-readback-malformed")
        result.append(cast(dict[str, str], row))
    return result


def _storage_role_assignment_rows(
    subscription_id: str, storage_account_id: str
) -> list[dict[str, str]]:
    """Return every assignment inherited by or nested below the storage account."""

    inherited = _role_assignment_rows(subscription_id, scope=storage_account_id)
    subscription_rows = _role_assignment_rows(subscription_id)
    normalized_storage = storage_account_id.rstrip("/").casefold()
    descendants = [
        row
        for row in subscription_rows
        if row["scope"].rstrip("/").casefold().startswith(f"{normalized_storage}/")
    ]
    by_id = {row["id"].casefold(): row for row in [*inherited, *descendants]}
    return sorted(by_id.values(), key=lambda row: row["id"].casefold())


def _role_permissions(
    role_definition_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    row = _rest_get(
        role_definition_id,
        ROLE_API_VERSION,
        "{permissions:properties.permissions}",
    )
    permissions = row.get("permissions")
    if not isinstance(permissions, list) or not permissions:
        _fail("scanner-bridge-role-definition-readback-malformed")
    data_actions: list[str] = []
    not_data_actions: list[str] = []
    for permission in permissions:
        if not isinstance(permission, dict):
            _fail("scanner-bridge-role-definition-readback-malformed")
        granted = permission.get("dataActions")
        denied = permission.get("notDataActions")
        if (
            not isinstance(granted, list)
            or not all(isinstance(value, str) for value in granted)
            or not isinstance(denied, list)
            or not all(isinstance(value, str) for value in denied)
        ):
            _fail("scanner-bridge-role-definition-readback-malformed")
        data_actions.extend(cast(list[str], granted))
        not_data_actions.extend(cast(list[str], denied))
    return tuple(data_actions), tuple(not_data_actions)


def _grants_tag_write(role_definition_id: str) -> bool:
    data_actions, denied = _role_permissions(role_definition_id)
    target = TAG_WRITE_ACTION.casefold()
    granted = any(
        fnmatch.fnmatchcase(target, action.casefold()) for action in data_actions
    )
    explicitly_denied = any(
        fnmatch.fnmatchcase(target, action.casefold()) for action in denied
    )
    return granted and not explicitly_denied


def _role_name(role_definition_id: str) -> str:
    return role_definition_id.rstrip("/").rsplit("/", 1)[-1].casefold()


def _canonical_role_definition_id(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> str:
    return (
        f"/subscriptions/{authorization.subscriptionId}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{_role_name(cast(str, authorization.proofRoleDefinitionId))}"
    )


def _normalized_proof_role_permissions(value: JsonValue | None) -> list[JsonValue]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        _fail("scanner-proof-role-definition-readback-unproved")
    permission = dict(value[0])
    allowed = {
        "actions",
        "condition",
        "conditionVersion",
        "dataActions",
        "notActions",
        "notDataActions",
    }
    if (
        set(permission) - allowed
        or permission.get("condition") is not None
        or permission.get("conditionVersion") is not None
    ):
        _fail("scanner-proof-role-definition-readback-unproved")
    permission.pop("condition", None)
    permission.pop("conditionVersion", None)
    return [cast(JsonValue, permission)]


def _verify_ordinary_identity_roles(
    *,
    subscription_id: str,
    principal_id: str,
    expected: frozenset[tuple[str, str]],
) -> tuple[list[dict[str, str]], str]:
    rows = _role_assignment_rows(subscription_id, principal_id=principal_id)
    projected = {
        (_role_name(row["roleDefinitionId"]), row["scope"].casefold()) for row in rows
    }
    if not expected.issubset(projected):
        _fail("scanner-bridge-required-role-assignment-absent")
    for row in rows:
        if _grants_tag_write(row["roleDefinitionId"]):
            _fail("scanner-bridge-ordinary-identity-tag-write-authorized")
    value = cast(JsonValue, sorted(rows, key=lambda row: row["id"].casefold()))
    return rows, _canonical_hash(value, "mobius.scanner-bridge.identity-rbac.v1")


def _identity_projection(resource_id: str) -> dict[str, JsonValue]:
    return _rest_get(
        resource_id,
        IDENTITY_API_VERSION,
        "{id:id,clientId:properties.clientId,principalId:properties.principalId}",
    )


def _verify_private_endpoint(
    *, resource_id: str, service_id: str, group_id: str, subnet_id: str
) -> dict[str, JsonValue]:
    row = _rest_get(
        resource_id,
        PRIVATE_ENDPOINT_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState,"
        "subnetId:properties.subnet.id,connections:"
        "properties.privateLinkServiceConnections[].{serviceId:properties.privateLinkServiceId,"
        "groupIds:properties.groupIds,status:properties.privateLinkServiceConnectionState.status,"
        "provisioningState:properties.provisioningState}}",
    )
    connections = row.get("connections")
    if (
        row.get("id") != resource_id
        or row.get("provisioningState") != "Succeeded"
        or row.get("subnetId") != subnet_id
        or not isinstance(connections, list)
        or len(connections) != 1
        or connections[0]
        != {
            "serviceId": service_id,
            "groupIds": [group_id],
            "status": "Approved",
            "provisioningState": "Succeeded",
        }
    ):
        _fail("scanner-bridge-private-endpoint-unproved")
    return row


def _verify_private_dns_zone_group(
    *, private_endpoint_id: str, expected_zone_ids: frozenset[str]
) -> dict[str, JsonValue]:
    group_id = f"{private_endpoint_id}/privateDnsZoneGroups/default"
    row = _rest_get(
        group_id,
        PRIVATE_ENDPOINT_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState,"
        "zoneIds:properties.privateDnsZoneConfigs[].properties.privateDnsZoneId}",
    )
    zone_ids = row.get("zoneIds")
    if (
        row.get("id") != group_id
        or row.get("provisioningState") != "Succeeded"
        or not isinstance(zone_ids, list)
        or any(not isinstance(value, str) for value in zone_ids)
        or {cast(str, value).casefold() for value in zone_ids}
        != {value.casefold() for value in expected_zone_ids}
    ):
        _fail("scanner-bridge-private-dns-zone-group-unproved")
    return row


def _verify_private_dns_zone_link(
    *, zone_id: str, link_name: str, virtual_network_id: str
) -> dict[str, JsonValue]:
    link_id = f"{zone_id}/virtualNetworkLinks/{link_name}"
    row = _rest_get(
        link_id,
        PRIVATE_DNS_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState,"
        "registrationEnabled:properties.registrationEnabled,"
        "virtualNetworkId:properties.virtualNetwork.id}",
    )
    if (
        not _same_resource_id(row.get("id"), link_id)
        or row.get("provisioningState") != "Succeeded"
        or row.get("registrationEnabled") is not False
        or not _same_resource_id(row.get("virtualNetworkId"), virtual_network_id)
    ):
        _fail("scanner-bridge-private-dns-zone-link-unproved")
    return row


def _validate_proof_console_diagnostic(
    diagnostic: Mapping[str, JsonValue],
    *,
    diagnostic_id: str,
    workspace_id: str,
) -> None:
    logs = diagnostic.get("logs")
    if (
        not _same_resource_id(diagnostic.get("id"), diagnostic_id)
        or not _same_resource_id(diagnostic.get("workspaceId"), workspace_id)
        or diagnostic.get("destinationType") not in {None, "Dedicated"}
        or not isinstance(logs, list)
    ):
        _fail("scanner-proof-console-diagnostic-unproved")
    categories: set[str] = set()
    enabled: list[dict[str, JsonValue]] = []
    for row in logs:
        if (
            not isinstance(row, dict)
            or set(row) != {"category", "enabled"}
            or not isinstance(row.get("category"), str)
            or not isinstance(row.get("enabled"), bool)
            or cast(str, row["category"]) in categories
        ):
            _fail("scanner-proof-console-diagnostic-unproved")
        categories.add(cast(str, row["category"]))
        if row["enabled"] is True:
            enabled.append(row)
    if enabled != [{"category": "ContainerAppConsoleLogs", "enabled": True}]:
        _fail("scanner-proof-console-diagnostic-unproved")


def _foundation_readback_once(
    authorization: _FoundationScope,
    *,
    require_proof_console_diagnostic: bool = False,
) -> _FoundationReadback:
    subscription_id = authorization.subscriptionId
    target = authorization.targetResourceGroupId
    vnet_id = f"{target}/providers/Microsoft.Network/virtualNetworks/{VIRTUAL_NETWORK}"
    subnet_id = f"{vnet_id}/subnets/{PRIVATE_ENDPOINT_SUBNET}"
    storage = _rest_get(
        authorization.storageAccountId,
        STORAGE_API_VERSION,
        "{id:id,location:location,kind:kind,sku:sku.name,"
        "publicNetworkAccess:properties.publicNetworkAccess,"
        "allowSharedKeyAccess:properties.allowSharedKeyAccess,"
        "allowBlobPublicAccess:properties.allowBlobPublicAccess,"
        "defaultToOAuthAuthentication:properties.defaultToOAuthAuthentication,"
        "minimumTlsVersion:properties.minimumTlsVersion,"
        "supportsHttpsTrafficOnly:properties.supportsHttpsTrafficOnly,"
        "networkDefaultAction:properties.networkAcls.defaultAction,"
        "networkBypass:properties.networkAcls.bypass,"
        "resourceAccessRules:properties.networkAcls.resourceAccessRules}",
    )
    scanner_resource_id = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Security/"
        f"dataScanners/{DEFENDER_SCANNER}"
    )
    expected_storage: dict[str, JsonValue] = {
        "id": authorization.storageAccountId,
        "location": STAGING_LOCATION,
        "kind": "StorageV2",
        "sku": "Standard_LRS",
        "publicNetworkAccess": "Disabled",
        "allowSharedKeyAccess": False,
        "allowBlobPublicAccess": False,
        "defaultToOAuthAuthentication": True,
        "minimumTlsVersion": "TLS1_2",
        "supportsHttpsTrafficOnly": True,
        "networkDefaultAction": "Deny",
        "networkBypass": "None",
    }
    if any(storage.get(key) != value for key, value in expected_storage.items()):
        _fail("scanner-bridge-storage-security-boundary-unproved")
    access_rules = storage.get("resourceAccessRules")
    if (
        not isinstance(access_rules, list)
        or len(access_rules) != 1
        or not isinstance(access_rules[0], dict)
        or set(access_rules[0]) != {"resourceId", "tenantId"}
        or not isinstance(access_rules[0].get("tenantId"), str)
        or _UUID.fullmatch(cast(str, access_rules[0]["tenantId"])) is None
        or not isinstance(access_rules[0].get("resourceId"), str)
        or cast(str, access_rules[0]["resourceId"]).casefold()
        != scanner_resource_id.casefold()
    ):
        _fail("scanner-bridge-storage-scanner-network-access-unproved")

    blob_service_id = f"{authorization.storageAccountId}/blobServices/default"
    blob_service = _rest_get(
        blob_service_id,
        STORAGE_API_VERSION,
        "{id:id,versioning:properties.isVersioningEnabled,"
        "softDeleteEnabled:properties.deleteRetentionPolicy.enabled,"
        "softDeleteDays:properties.deleteRetentionPolicy.days,"
        "permanentDeleteEnabled:properties.deleteRetentionPolicy.allowPermanentDelete}",
    )
    if blob_service != {
        "id": blob_service_id,
        "versioning": True,
        "softDeleteEnabled": True,
        "softDeleteDays": 7,
        "permanentDeleteEnabled": True,
    }:
        _fail("scanner-bridge-storage-versioning-unproved")
    container_rows: list[dict[str, JsonValue]] = []
    for container in ("quarantine", "clean", "rejected", "retained"):
        container_id = f"{blob_service_id}/containers/{container}"
        row = _rest_get(
            container_id,
            STORAGE_API_VERSION,
            "{id:id,publicAccess:properties.publicAccess,"
            "denyEncryptionScopeOverride:properties.denyEncryptionScopeOverride}",
        )
        if (
            row.get("id") != container_id
            or row.get("publicAccess") not in {None, "None"}
            or row.get("denyEncryptionScopeOverride") is not True
        ):
            _fail("scanner-bridge-container-security-boundary-unproved")
        container_rows.append(row)

    defender_id = (
        f"{authorization.storageAccountId}/providers/Microsoft.Security/"
        "defenderForStorageSettings/current"
    )
    defender = _rest_get(
        defender_id,
        DEFENDER_API_VERSION,
        "{id:id,isEnabled:properties.isEnabled,"
        "override:properties.overrideSubscriptionLevelSettings,"
        "malwareScanning:properties.malwareScanning,"
        "sensitiveDataDiscovery:properties.sensitiveDataDiscovery}",
    )
    malware = defender.get("malwareScanning")
    discovery = defender.get("sensitiveDataDiscovery")
    if (
        defender.get("id") != defender_id
        or defender.get("isEnabled") is not True
        or defender.get("override") is not True
        or not isinstance(malware, dict)
        or malware.get("blobScanResultsOptions") != "BlobIndexTags"
        or bool(malware.get("scanResultsEventGridTopicResourceId"))
        or not isinstance(malware.get("onUpload"), dict)
        or cast(dict[str, JsonValue], malware["onUpload"]).get("isEnabled") is not True
        or cast(dict[str, JsonValue], malware["onUpload"]).get("capGBPerMonth") != 1
        or not isinstance(discovery, dict)
        or discovery.get("isEnabled") is not False
    ):
        _fail("scanner-bridge-defender-setting-unproved")

    diagnostic_id = (
        f"{defender_id}/providers/Microsoft.Insights/diagnosticSettings/"
        "mobius77-defender-scan-results"
    )
    diagnostic = _rest_get(
        diagnostic_id,
        DIAGNOSTIC_API_VERSION,
        "{id:id,workspaceId:properties.workspaceId,logs:properties.logs}",
    )
    logs = diagnostic.get("logs")
    if (
        not _same_resource_id(diagnostic.get("id"), diagnostic_id)
        or not isinstance(diagnostic.get("workspaceId"), str)
        or cast(str, diagnostic["workspaceId"]).casefold()
        != authorization.logAnalyticsWorkspaceId.casefold()
        or not isinstance(logs, list)
        or not any(
            isinstance(log, dict)
            and log.get("category") == "ScanResults"
            and log.get("enabled") is True
            for log in logs
        )
    ):
        _fail("scanner-bridge-log-analytics-diagnostic-unproved")

    proof_console_diagnostic: dict[str, JsonValue] | None = None
    if require_proof_console_diagnostic:
        managed_environment_id = f"{target}/providers/Microsoft.App/managedEnvironments/{MANAGED_ENVIRONMENT}"
        proof_console_diagnostic_id = (
            f"{managed_environment_id}/providers/Microsoft.Insights/diagnosticSettings/"
            f"{PROOF_CONSOLE_DIAGNOSTIC}"
        )
        proof_console_diagnostic = _rest_get(
            proof_console_diagnostic_id,
            DIAGNOSTIC_API_VERSION,
            "{id:id,workspaceId:properties.workspaceId,"
            "destinationType:properties.logAnalyticsDestinationType,"
            "logs:properties.logs[].{category:category,enabled:enabled}}",
        )
        _validate_proof_console_diagnostic(
            proof_console_diagnostic,
            diagnostic_id=proof_console_diagnostic_id,
            workspace_id=authorization.logAnalyticsWorkspaceId,
        )

    workspace = _rest_get(
        authorization.logAnalyticsWorkspaceId,
        "2026-03-01",
        "{id:id,customerId:properties.customerId,"
        "publicIngestion:properties.publicNetworkAccessForIngestion,"
        "publicQuery:properties.publicNetworkAccessForQuery,"
        "resourcePermissionsOnly:properties.features.enableLogAccessUsingOnlyResourcePermissions,"
        "retentionDays:properties.retentionInDays,dailyQuotaGb:properties.workspaceCapping.dailyQuotaGb}",
    )
    workspace_customer_id = workspace.get("customerId")
    if (
        workspace.get("id") != authorization.logAnalyticsWorkspaceId
        or not isinstance(workspace_customer_id, str)
        or _UUID.fullmatch(workspace_customer_id) is None
        or workspace.get("publicIngestion") != "Disabled"
        or workspace.get("publicQuery") != "Disabled"
        or workspace.get("resourcePermissionsOnly") is not True
        or workspace.get("retentionDays") != 30
        or workspace.get("dailyQuotaGb") != 2
    ):
        _fail("scanner-bridge-workspace-readback-unproved")

    ampls = _rest_get(
        authorization.privateLinkScopeId,
        AMPLS_API_VERSION,
        "{id:id,queryAccessMode:properties.accessModeSettings.queryAccessMode,"
        "ingestionAccessMode:properties.accessModeSettings.ingestionAccessMode,"
        "exclusions:properties.accessModeSettings.exclusions}",
    )
    if (
        not _same_resource_id(ampls.get("id"), authorization.privateLinkScopeId)
        or ampls.get("queryAccessMode") != "PrivateOnly"
        or ampls.get("ingestionAccessMode") != "PrivateOnly"
        or ampls.get("exclusions") != []
    ):
        _fail("scanner-bridge-ampls-private-only-unproved")
    scoped_id = (
        f"{authorization.privateLinkScopeId}/scopedResources/{LOG_ANALYTICS_WORKSPACE}"
    )
    scoped = _rest_get(
        scoped_id,
        AMPLS_API_VERSION,
        "{id:id,linkedResourceId:properties.linkedResourceId}",
    )
    if (
        not _same_resource_id(scoped.get("id"), scoped_id)
        or not isinstance(scoped.get("linkedResourceId"), str)
        or cast(str, scoped["linkedResourceId"]).casefold()
        != authorization.logAnalyticsWorkspaceId.casefold()
    ):
        _fail("scanner-bridge-ampls-workspace-association-unproved")

    storage_pe_id = f"{target}/providers/Microsoft.Network/privateEndpoints/{STORAGE_PRIVATE_ENDPOINT}"
    storage_pe = _verify_private_endpoint(
        resource_id=storage_pe_id,
        service_id=authorization.storageAccountId,
        group_id="blob",
        subnet_id=subnet_id,
    )
    monitor_pe = _verify_private_endpoint(
        resource_id=authorization.monitorPrivateEndpointId,
        service_id=authorization.privateLinkScopeId,
        group_id="azuremonitor",
        subnet_id=subnet_id,
    )
    required_zones = tuple(
        zone for zone, _link, _config in MONITOR_PRIVATE_DNS_BINDINGS
    )
    link_names = {zone: link for zone, link, _config in MONITOR_PRIVATE_DNS_BINDINGS}
    zone_rows: list[dict[str, JsonValue]] = []
    zone_link_rows: list[dict[str, JsonValue]] = []
    for zone in required_zones:
        zone_id = f"{target}/providers/Microsoft.Network/privateDnsZones/{zone}"
        row = _rest_get(zone_id, PRIVATE_DNS_API_VERSION, "{id:id,location:location}")
        if row != {"id": zone_id, "location": "global"}:
            _fail("scanner-bridge-private-dns-zone-unproved")
        zone_rows.append(row)
        zone_link_rows.append(
            _verify_private_dns_zone_link(
                zone_id=zone_id,
                link_name=link_names[zone],
                virtual_network_id=vnet_id,
            )
        )
    zone_ids = {
        zone: f"{target}/providers/Microsoft.Network/privateDnsZones/{zone}"
        for zone in required_zones
    }
    storage_zone_group = _verify_private_dns_zone_group(
        private_endpoint_id=storage_pe_id,
        expected_zone_ids=frozenset({zone_ids["privatelink.blob.core.windows.net"]}),
    )
    monitor_zone_group = _verify_private_dns_zone_group(
        private_endpoint_id=authorization.monitorPrivateEndpointId,
        expected_zone_ids=frozenset(zone_ids.values()),
    )

    worker = _identity_projection(authorization.workerIdentityId)
    api_identity_id = f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{API_IDENTITY}"
    api_identity = _identity_projection(api_identity_id)
    worker_principal = worker.get("principalId")
    worker_client = worker.get("clientId")
    api_principal = api_identity.get("principalId")
    if (
        not _same_resource_id(worker.get("id"), authorization.workerIdentityId)
        or not _same_resource_id(api_identity.get("id"), api_identity_id)
        or not isinstance(worker_principal, str)
        or _UUID.fullmatch(worker_principal) is None
        or not isinstance(worker_client, str)
        or _UUID.fullmatch(worker_client) is None
        or not isinstance(api_principal, str)
        or _UUID.fullmatch(api_principal) is None
    ):
        _fail("scanner-bridge-identity-readback-unproved")

    quarantine_scope = f"{blob_service_id}/containers/quarantine"
    clean_scope = f"{blob_service_id}/containers/clean"
    worker_expected = frozenset(
        {
            (WORKER_QUARANTINE_ROLE, quarantine_scope.casefold()),
            (WORKER_CLEAN_ROLE, clean_scope.casefold()),
            (
                LOG_ANALYTICS_READER_ROLE,
                authorization.logAnalyticsWorkspaceId.casefold(),
            ),
        }
    )
    api_expected = frozenset(
        {
            (API_QUARANTINE_ROLE, quarantine_scope.casefold()),
            (API_CLEAN_READER_ROLE, clean_scope.casefold()),
        }
    )
    worker_rows, worker_rbac = _verify_ordinary_identity_roles(
        subscription_id=subscription_id,
        principal_id=worker_principal,
        expected=worker_expected,
    )
    api_rows, api_rbac = _verify_ordinary_identity_roles(
        subscription_id=subscription_id,
        principal_id=api_principal,
        expected=api_expected,
    )

    scanner = lifecycle._run(
        (
            "az",
            "resource",
            "show",
            "--ids",
            scanner_resource_id,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id,principalId:identity.principalId}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    scanner_row = _json_object(scanner, "scanner-bridge-storage-scanner-malformed")
    scanner_principal = scanner_row.get("principalId")
    if (
        not isinstance(scanner_row.get("id"), str)
        or cast(str, scanner_row["id"]).casefold() != scanner_resource_id.casefold()
        or not isinstance(scanner_principal, str)
        or _UUID.fullmatch(scanner_principal) is None
    ):
        _fail("scanner-bridge-storage-scanner-identity-unproved")
    storage_rows = _storage_role_assignment_rows(
        subscription_id, authorization.storageAccountId
    )
    tag_writers = [
        row for row in storage_rows if _grants_tag_write(row["roleDefinitionId"])
    ]
    if len(tag_writers) != 1:
        _fail("scanner-bridge-tag-writer-boundary-unproved")
    writer = tag_writers[0]
    if (
        writer["principalId"].casefold() != scanner_principal.casefold()
        or _role_name(writer["roleDefinitionId"]) != DEFENDER_SCANNER_ROLE
        or writer["scope"].casefold() != authorization.storageAccountId.casefold()
    ):
        _fail("scanner-bridge-unauthorized-tag-writer-present")

    topics_collection = f"{target}/providers/Microsoft.EventGrid/systemTopics"
    topics = _rest_collection(
        topics_collection,
        EVENT_GRID_API_VERSION,
        "value[].{id:id,source:properties.source,topicType:properties.topicType}",
    )
    if not isinstance(topics, list):
        _fail("scanner-bridge-provider-topic-readback-malformed")
    provider_topics = [
        topic
        for topic in topics
        if isinstance(topic, dict)
        and isinstance(topic.get("source"), str)
        and cast(str, topic["source"]).casefold()
        == authorization.storageAccountId.casefold()
        and isinstance(topic.get("topicType"), str)
        and cast(str, topic["topicType"]).casefold()
        == "microsoft.storage.storageaccounts"
        and isinstance(topic.get("id"), str)
    ]
    if len(provider_topics) != 1:
        _fail("scanner-bridge-provider-topic-unproved")
    custom_topics = _rest_collection(
        f"{target}/providers/Microsoft.EventGrid/topics",
        EVENT_GRID_API_VERSION,
        "value[].id",
    )
    if custom_topics != []:
        _fail("scanner-bridge-custom-push-topic-present")

    private_projection = cast(
        JsonValue,
        {
            "ampls": ampls,
            "monitorPrivateEndpoint": monitor_pe,
            "monitorPrivateDnsZoneGroup": monitor_zone_group,
            "scopedWorkspace": scoped,
            "storagePrivateEndpoint": storage_pe,
            "storagePrivateDnsZoneGroup": storage_zone_group,
            "zoneLinks": zone_link_rows,
            "zones": zone_rows,
        },
    )
    rbac_projection = cast(
        JsonValue,
        {"api": api_rows, "worker": worker_rows, "storage": storage_rows},
    )
    inventory = cast(
        JsonValue,
        {
            "blobService": blob_service,
            "containers": container_rows,
            "customTopics": custom_topics,
            "diagnosticSettings": {
                "defenderScanResults": diagnostic,
                "proofConsole": proof_console_diagnostic,
            },
            "providerTopics": topics,
            "storage": storage,
        },
    )
    diagnostic_projection = cast(
        JsonValue,
        {
            "defenderScanResults": diagnostic,
            "proofConsole": proof_console_diagnostic,
        },
    )
    return _FoundationReadback(
        api_principal_id=api_principal,
        worker_principal_id=worker_principal,
        worker_client_id=worker_client,
        workspace_customer_id=workspace_customer_id,
        provider_topic_id=cast(str, provider_topics[0]["id"]),
        provider_proof_integrity=_canonical_hash(
            cast(JsonValue, defender), "mobius.scanner-bridge.provider.v1"
        ),
        diagnostic_proof_integrity=_canonical_hash(
            diagnostic_projection, "mobius.scanner-bridge.diagnostic.v1"
        ),
        rbac_proof_integrity=_canonical_hash(
            rbac_projection, "mobius.scanner-bridge.rbac.v1"
        ),
        tag_write_denial_integrity=_canonical_hash(
            cast(
                JsonValue,
                {
                    "api": api_rbac,
                    "authorizedWriter": writer,
                    "worker": worker_rbac,
                },
            ),
            "mobius.scanner-bridge.tag-writer-boundary.v1",
        ),
        private_path_control_plane_integrity=_canonical_hash(
            private_projection, "mobius.scanner-bridge.private-path-control-plane.v1"
        ),
        inventory_integrity=_canonical_hash(
            inventory, "mobius.scanner-bridge.foundation-inventory.v1"
        ),
    )


def _verify_foundation(
    authorization: _FoundationScope,
    *,
    require_proof_console_diagnostic: bool = False,
) -> _FoundationReadback:
    deadline = time.monotonic() + FOUNDATION_PROPAGATION_SECONDS
    while True:
        try:
            return _foundation_readback_once(
                authorization,
                require_proof_console_diagnostic=require_proof_console_diagnostic,
            )
        except (lifecycle.AzureCommandError, ScannerBridgeRecoveryExecutionError):
            if time.monotonic() >= deadline:
                _fail("scanner-bridge-foundation-readback-unproved")
            time.sleep(FOUNDATION_POLL_SECONDS)


def _proof_graph(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    assignment_id: str,
    worker_principal_id: str,
    worker_client_id: str,
    workspace_customer_id: str,
) -> str:
    if authorization.proofJobId is None or authorization.proofRoleDefinitionId is None:
        _fail("scanner-proof-authorization-incomplete")
    job = _rest_get(
        authorization.proofJobId,
        JOB_API_VERSION,
        "{id:id,triggerType:properties.configuration.triggerType,"
        "retryLimit:properties.configuration.replicaRetryLimit,"
        "replicaTimeout:properties.configuration.replicaTimeout,"
        "parallelism:properties.configuration.manualTriggerConfig.parallelism,"
        "completionCount:properties.configuration.manualTriggerConfig.replicaCompletionCount,"
        "image:properties.template.containers[0].image,"
        "container:properties.template.containers[0].name,"
        "command:properties.template.containers[0].command,"
        "args:properties.template.containers[0].args,"
        "environment:properties.template.containers[0].env[].{name:name,value:value},"
        "identityIds:keys(identity.userAssignedIdentities)}",
    )
    expected_environment: list[JsonValue] = [
        {
            "name": "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL",
            "value": f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/",
        },
        {"name": "OPENCANVAS_AZURE_QUARANTINE_CONTAINER", "value": "quarantine"},
        {"name": "OPENCANVAS_AZURE_CLEAN_CONTAINER", "value": "clean"},
        {"name": "OPENCANVAS_AZURE_REJECTED_CONTAINER", "value": "rejected"},
        {"name": "OPENCANVAS_AZURE_RETAINED_CONTAINER", "value": "retained"},
        {
            "name": "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID",
            "value": worker_client_id,
        },
        {
            "name": "OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID",
            "value": workspace_customer_id,
        },
        {
            "name": "OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT",
            "value": "https://api.loganalytics.azure.com",
        },
        {
            "name": "OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED",
            "value": authorization.authorizationIntegritySha256,
        },
    ]
    job_projection = {
        key: value for key, value in job.items() if key not in {"id", "identityIds"}
    }
    identity_ids = job.get("identityIds")
    if (
        job_projection
        != {
            "triggerType": "Manual",
            "retryLimit": 0,
            "replicaTimeout": PROOF_REPLICA_TIMEOUT_SECONDS,
            "parallelism": 1,
            "completionCount": 1,
            "image": authorization.apiImageDigest,
            "container": PROOF_CONTAINER,
            "command": ["python"],
            "args": [
                "-m",
                "scripts.scanner_bridge_probe",
                "--max-attempts",
                str(PROOF_MAX_ATTEMPTS),
                "--delay-seconds",
                str(PROOF_DELAY_SECONDS),
            ],
            "environment": expected_environment,
        }
        or not _same_resource_id(job.get("id"), authorization.proofJobId)
        or not (
            isinstance(identity_ids, list)
            and len(identity_ids) == 1
            and _same_resource_id(identity_ids[0], authorization.workerIdentityId)
        )
    ):
        _fail("scanner-proof-job-readback-unproved")
    role = _rest_get(
        authorization.proofRoleDefinitionId,
        ROLE_API_VERSION,
        "{id:id,roleName:properties.roleName,assignableScopes:properties.assignableScopes,"
        "permissions:properties.permissions}",
    )
    permissions = _normalized_proof_role_permissions(role.get("permissions"))
    assignable_scopes = role.get("assignableScopes")
    canonical_role_id = _canonical_role_definition_id(authorization)
    exact_permissions: list[JsonValue] = [
        {
            "actions": [
                "Microsoft.Storage/storageAccounts/blobServices/containers/read"
            ],
            "dataActions": [
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/deleteBlobVersion/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/permanentDelete/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read",
            ],
            "notActions": [],
            "notDataActions": [],
        }
    ]
    if (
        not _same_resource_id(role.get("id"), canonical_role_id)
        or role.get("roleName") != "Mobius77 Temporary Scanner Bridge Probe"
        or not (
            isinstance(assignable_scopes, list)
            and len(assignable_scopes) == 1
            and _same_resource_id(
                assignable_scopes[0], authorization.targetResourceGroupId
            )
        )
        or permissions != exact_permissions
        or _grants_tag_write(authorization.proofRoleDefinitionId)
    ):
        _fail("scanner-proof-role-definition-readback-unproved")
    assignment = _rest_get(
        assignment_id,
        ROLE_API_VERSION,
        "{id:id,principalId:properties.principalId,roleDefinitionId:properties.roleDefinitionId}",
    )
    quarantine_scope = (
        f"{authorization.storageAccountId}/blobServices/default/containers/quarantine"
    )
    assignment_principal = assignment.get("principalId")
    if (
        not _same_resource_id(assignment.get("id"), assignment_id)
        or not isinstance(assignment_principal, str)
        or assignment_principal.casefold() != worker_principal_id.casefold()
        or not isinstance(assignment.get("roleDefinitionId"), str)
        or cast(str, assignment["roleDefinitionId"]).casefold()
        != canonical_role_id.casefold()
        or not assignment_id.casefold().startswith(
            f"{quarantine_scope}/providers/Microsoft.Authorization/roleAssignments/".casefold()
        )
    ):
        _fail("scanner-proof-role-assignment-readback-unproved")
    return _canonical_hash(
        cast(JsonValue, {"assignment": assignment, "job": job, "role": role}),
        "mobius.scanner-bridge.proof-graph.v1",
    )


def _job_execution_rows(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> list[dict[str, str | None]]:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            PROOF_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "[].{name:name,status:properties.status,startTime:properties.startTime,"
            "endTime:properties.endTime}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("scanner-proof-execution-readback-malformed")
    result: list[dict[str, str | None]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "name",
            "status",
            "startTime",
            "endTime",
        }:
            _fail("scanner-proof-execution-readback-malformed")
        if not isinstance(row.get("name"), str) or not isinstance(
            row.get("status"), str
        ):
            _fail("scanner-proof-execution-readback-malformed")
        if any(
            item is not None and not isinstance(item, str)
            for item in (row.get("startTime"), row.get("endTime"))
        ):
            _fail("scanner-proof-execution-readback-malformed")
        result.append(cast(dict[str, str | None], row))
    return result


def _start_one_execution(authorization: ScannerBridgeRecoveryAuthorization) -> str:
    initial = _job_execution_rows(authorization)
    if initial:
        _fail("scanner-proof-duplicate-execution-present")
    requested_name: str | None = None
    try:
        value = lifecycle._run(
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--name",
                PROOF_JOB,
                "--resource-group",
                TARGET_RESOURCE_GROUP,
                "--subscription",
                authorization.subscriptionId,
                "--query",
                "name",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if isinstance(value, str) and value:
            requested_name = value
    except lifecycle.AzureCommandError:
        requested_name = None
    deadline = time.monotonic() + 120.0
    while True:
        rows = _job_execution_rows(authorization)
        if len(rows) == 1:
            name = rows[0]["name"]
            if isinstance(name, str) and (
                requested_name is None or requested_name == name
            ):
                return name
        if len(rows) > 1:
            _fail("scanner-proof-duplicate-execution-created")
        if time.monotonic() >= deadline:
            _fail("scanner-proof-execution-start-unproved")
        time.sleep(5.0)


def _wait_for_execution(
    authorization: ScannerBridgeRecoveryAuthorization, execution_name: str
) -> dict[str, str | None]:
    deadline = time.monotonic() + EXECUTION_PROPAGATION_SECONDS
    while True:
        rows = _job_execution_rows(authorization)
        matching = [row for row in rows if row["name"] == execution_name]
        if len(rows) != 1 or len(matching) != 1:
            _fail("scanner-proof-execution-reconciliation-drift")
        row = matching[0]
        status = row["status"]
        terminal = status in {"Succeeded", "Failed", "Degraded", "Stopped", "Cancelled"}
        # Azure may omit the non-security-sensitive completion timestamp from a
        # terminal execution list row.  The terminal status and canonical start
        # timestamp are sufficient here; the proof or failure marker remains the
        # authoritative execution result and correlation evidence.
        if terminal and row["startTime"] is not None:
            return row
        if time.monotonic() >= deadline:
            if terminal:
                _fail("scanner-proof-execution-terminal-time-unproved")
            _fail("scanner-proof-execution-timeout")
        time.sleep(EXECUTION_POLL_SECONDS)


def _find_markers(value: object, marker_name: str) -> tuple[dict[str, object], ...]:
    found: list[dict[str, object]] = []
    if isinstance(value, Mapping):
        if value.get("marker") == marker_name:
            found.append(dict(value))
        else:
            for child in value.values():
                found.extend(_find_markers(child, marker_name))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found.extend(_find_markers(child, marker_name))
    elif isinstance(value, str):
        decoded = _decode_container_log_envelope(value)
        if decoded is not None:
            found.extend(_find_markers(decoded, marker_name))
    return tuple(found)


def _decode_container_log_envelope(value: str) -> object | None:
    """Decode only direct JSON or the observed Azure Container Apps `F ` envelope."""

    if len(value.encode()) > PROOF_LOG_OUTPUT_MAX_BYTES:
        return None
    payload = value.strip()
    if payload.startswith("F "):
        payload = payload[2:]
    if not payload.startswith(("{", "[")):
        return None
    try:
        return cast(object, json.loads(payload))
    except json.JSONDecodeError:
        return None


def _find_marker(value: object, marker_name: str) -> dict[str, object] | None:
    markers = _find_markers(value, marker_name)
    return markers[0] if markers else None


def _proof_log_output(
    authorization: ScannerBridgeRecoveryAuthorization, execution_name: str
) -> str:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "logs",
            "show",
            "--name",
            PROOF_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--execution",
            execution_name,
            "--container",
            PROOF_CONTAINER,
            "--tail",
            str(PROOF_LOG_TAIL_LINES),
            "--format",
            "json",
            "--subscription",
            authorization.subscriptionId,
            "--only-show-errors",
        ),
        require_text=True,
    )
    if not isinstance(value, str) or len(value.encode()) > PROOF_LOG_OUTPUT_MAX_BYTES:
        _fail("scanner-proof-log-output-malformed")
    return value


def _proof_marker(
    authorization: ScannerBridgeRecoveryAuthorization, execution_name: str
) -> dict[str, JsonValue]:
    return _proof_marker_from_log_output(
        _proof_log_output(authorization, execution_name)
    )


def _proof_marker_from_log_output(log_output: str) -> dict[str, JsonValue]:
    success_markers = _find_markers(log_output, "SCANNER_RESULT_BRIDGE_PROVED")
    failure_markers = _find_markers(log_output, "SCANNER_RESULT_BRIDGE_FAILED")
    if failure_markers:
        _fail("scanner-proof-contradictory-terminal-marker")
    if not success_markers:
        _fail("scanner-proof-success-marker-not-yet-ingested")
    if len(success_markers) != 1:
        _fail("scanner-proof-marker-malformed")
    marker = success_markers[0]
    required = {
        "accountNameSha256",
        "attemptCount",
        "blobEvidenceSha256",
        "blobTagObservation",
        "blobTagObservationCount",
        "blobTagResultSha256",
        "blobUriSha256",
        "completionTimeSha256",
        "contentSha256",
        "correlationIdSha256",
        "decision",
        "dualSourceEvidenceSha256",
        "etagSha256",
        "logAnalyticsEvidenceSha256",
        "logQuerySha256",
        "marker",
        "markerIntegritySha256",
        "privateDnsEvidenceSha256",
        "providerVersionSha256",
        "residue",
        "scanFinishedComparison",
        "scanRequestIdSha256",
        "schemaVersion",
        "storageResourceSha256",
        "tlsEvidenceSha256",
        "tlsHostnameSha256",
        "tlsVersion",
    }
    if set(marker) != required:
        _fail("scanner-proof-marker-malformed")
    exact = {
        "decision": "clean",
        "marker": "SCANNER_RESULT_BRIDGE_PROVED",
        "residue": "canary-version-deleted",
        "schemaVersion": "mobius.scanner-result-bridge.proof.v2",
    }
    if any(marker.get(key) != expected for key, expected in exact.items()):
        _fail("scanner-proof-marker-unresolved")
    if marker.get("tlsVersion") not in {"TLS1_2", "TLS1_3"}:
        _fail("scanner-proof-tls-unproved")
    hashes = {
        "accountNameSha256",
        "blobEvidenceSha256",
        "blobTagResultSha256",
        "blobUriSha256",
        "completionTimeSha256",
        "contentSha256",
        "correlationIdSha256",
        "dualSourceEvidenceSha256",
        "etagSha256",
        "logAnalyticsEvidenceSha256",
        "logQuerySha256",
        "privateDnsEvidenceSha256",
        "providerVersionSha256",
        "scanRequestIdSha256",
        "storageResourceSha256",
        "tlsEvidenceSha256",
        "tlsHostnameSha256",
    }
    if any(
        not isinstance(marker.get(key), str)
        or _SHA256.fullmatch(cast(str, marker[key])) is None
        for key in hashes
    ):
        _fail("scanner-proof-marker-integrity-malformed")
    attempt_count = marker.get("attemptCount")
    observation_count = marker.get("blobTagObservationCount")
    integrity = marker.get("markerIntegritySha256")
    body = {
        key: value for key, value in marker.items() if key != "markerIntegritySha256"
    }
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or not 1 <= attempt_count <= 120
        or not isinstance(observation_count, int)
        or isinstance(observation_count, bool)
        or not 1 <= observation_count <= attempt_count
        or not isinstance(integrity, str)
        or _SHA256.fullmatch(integrity) is None
        or integrity
        != _scanner_runtime_hash(
            cast(JsonValue, body),
            "mobius.scanner-bridge.proof-success-marker.v2",
        )
    ):
        _fail("scanner-proof-marker-integrity-malformed")
    comparison = marker.get("scanFinishedComparison")
    _validate_scan_finished_terminal_evidence(
        comparison,
        expected_decision="equal-common-precision",
    )
    observation = _validate_blob_tag_observation_marker(
        marker.get("blobTagObservation"),
        expected_decision="accepted",
    )
    if not isinstance(comparison, Mapping):
        _fail("scanner-proof-marker-correlation-unproved")
    blob_timestamp = comparison.get("blobTagsTimestamp")
    log_timestamp = comparison.get("logAnalyticsTimestamp")
    if not isinstance(blob_timestamp, Mapping) or not isinstance(
        log_timestamp, Mapping
    ):
        _fail("scanner-proof-marker-correlation-unproved")
    blob_canonical = blob_timestamp.get("canonicalUtc")
    blob_common = comparison.get("blobTagsCommonPrecisionUtc")
    log_common = comparison.get("logAnalyticsCommonPrecisionUtc")
    cross_bindings = {
        "blobEvidenceSha256": "blobEvidenceSha256",
        "correlationIdSha256": "correlationIdSha256",
        "etagSha256": "etagSha256",
        "logAnalyticsEvidenceSha256": "logAnalyticsEvidenceSha256",
        "providerVersionSha256": "providerVersionSha256",
        "uriSha256": "blobUriSha256",
    }
    observation_bindings = {
        "queriedBlobUriSha256": "blobUriSha256",
        "queriedBlobVersionIdSha256": "providerVersionSha256",
        "queriedEtagSha256": "etagSha256",
    }
    if (
        not isinstance(blob_canonical, str)
        or not isinstance(blob_common, str)
        or blob_common != log_common
        or comparison.get("commonPrecisionEqual") is not True
        or marker.get("completionTimeSha256") != _hash_text(blob_canonical)
        or marker.get("blobTagResultSha256")
        != _hash_text(cast(str, comparison.get("blobTagResult")))
        or any(
            comparison.get(evidence_key) != marker.get(marker_key)
            for evidence_key, marker_key in cross_bindings.items()
        )
        or any(
            observation.get(evidence_key) != marker.get(marker_key)
            for evidence_key, marker_key in observation_bindings.items()
        )
    ):
        _fail("scanner-proof-marker-correlation-unproved")
    return cast(dict[str, JsonValue], marker)


def _wait_for_proof_marker(
    authorization: ScannerBridgeRecoveryAuthorization, execution_name: str
) -> dict[str, JsonValue]:
    """Wait separately for terminal diagnostic evidence to become queryable."""

    deadline = time.monotonic() + PROOF_DIAGNOSTIC_PROPAGATION_SECONDS
    while True:
        try:
            return _proof_marker(authorization, execution_name)
        except ScannerBridgeRecoveryExecutionError as exc:
            if str(exc) != "scanner-proof-success-marker-not-yet-ingested":
                raise
        if time.monotonic() >= deadline:
            _fail("scanner-proof-diagnostic-ingestion-incomplete")
        time.sleep(PROOF_DIAGNOSTIC_POLL_SECONDS)


def _precise_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class _ValidatedTimestampRepresentation:
    parsed: datetime
    utc_second: datetime
    fractional_digits: str

    @property
    def precision(self) -> int:
        return len(self.fractional_digits)


def _parsed_timestamp_representation(
    value: object,
) -> _ValidatedTimestampRepresentation:
    if not isinstance(value, Mapping):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    required = {
        "canonicalUtc",
        "fractionalSecondDigits",
        "parserNormalizationPath",
        "rawLengthBytes",
        "rawValue",
        "rawValueSha256",
        "timezoneRepresentation",
    }
    if set(value) != required:
        _fail("scanner-proof-scan-finished-evidence-malformed")
    raw_value = value.get("rawValue")
    raw_hash = value.get("rawValueSha256")
    raw_length = value.get("rawLengthBytes")
    precision = value.get("fractionalSecondDigits")
    timezone = value.get("timezoneRepresentation")
    canonical = value.get("canonicalUtc")
    if (
        not isinstance(raw_value, str)
        or _SANITIZED_TIMESTAMP.fullmatch(raw_value) is None
        or not isinstance(raw_hash, str)
        or _SHA256.fullmatch(raw_hash) is None
        or raw_hash != _hash_text(raw_value)
        or not isinstance(raw_length, int)
        or isinstance(raw_length, bool)
        or raw_length != len(raw_value.encode())
        or not isinstance(precision, int)
        or isinstance(precision, bool)
        or not 0 <= precision <= 32
        or not isinstance(timezone, str)
        or not isinstance(canonical, str)
        or value.get("parserNormalizationPath") != SCAN_FINISHED_NORMALIZATION_PATH
    ):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    stripped = raw_value.strip()
    represented = _REPRESENTED_TIMESTAMP.fullmatch(stripped)
    if represented is None:
        _fail("scanner-proof-scan-finished-evidence-malformed")
    fraction = re.search(r"\.(\d+)", stripped)
    expected_precision = len(fraction.group(1)) if fraction is not None else 0
    offset = re.search(r"([+-]\d\d:\d\d)$", stripped)
    expected_timezone = (
        stripped[-1]
        if stripped.endswith(("Z", "z"))
        else offset.group(1)
        if offset is not None
        else "unproved"
    )
    normalized = f"{stripped[:-1]}+00:00" if stripped.endswith(("Z", "z")) else stripped
    oversized_fraction = re.search(r"\.(\d{7,})(?=[+-]\d\d:\d\d$)", normalized)
    if oversized_fraction is not None:
        normalized = (
            normalized[: oversized_fraction.start(1)]
            + oversized_fraction.group(1)[:6]
            + normalized[oversized_fraction.end(1) :]
        )
    try:
        parsed_raw = datetime.fromisoformat(normalized)
        canonical_normalized = (
            f"{canonical[:-1]}+00:00" if canonical.endswith(("Z", "z")) else canonical
        )
        parsed_canonical = datetime.fromisoformat(canonical_normalized)
    except ValueError:
        _fail("scanner-proof-scan-finished-evidence-malformed")
    if (
        parsed_raw.tzinfo is None
        or parsed_raw.utcoffset() is None
        or parsed_canonical.tzinfo is None
        or parsed_canonical.utcoffset() is None
        or expected_precision != precision
        or expected_timezone != timezone
        or _precise_utc(parsed_raw) != canonical
        or _precise_utc(parsed_canonical) != canonical
    ):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    represented_timezone = represented.group("timezone")
    normalized_timezone = (
        "+00:00" if represented_timezone in {"Z", "z"} else represented_timezone
    )
    try:
        utc_second = datetime.fromisoformat(
            f"{represented.group('date')}T{represented.group('time')}{normalized_timezone}"
        ).astimezone(UTC)
    except ValueError:
        _fail("scanner-proof-scan-finished-evidence-malformed")
    return _ValidatedTimestampRepresentation(
        parsed=parsed_canonical.astimezone(UTC),
        utc_second=utc_second,
        fractional_digits=represented.group("fraction") or "",
    )


def _delta_microseconds(left: datetime, right: datetime) -> int:
    delta = left - right
    return ((delta.days * 86_400) + delta.seconds) * 1_000_000 + delta.microseconds


def _timestamp_units(value: _ValidatedTimestampRepresentation, precision: int) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value.utc_second - epoch
    seconds = delta.days * 86_400 + delta.seconds
    if precision == 0:
        fraction = 0
    elif value.precision >= precision:
        fraction = int(value.fractional_digits[:precision])
    else:
        fraction = int(value.fractional_digits or "0") * 10 ** (
            precision - value.precision
        )
    return int(seconds * 10**precision + fraction)


def _common_precision_utc(
    value: _ValidatedTimestampRepresentation, precision: int
) -> str:
    base = value.utc_second.strftime("%Y-%m-%dT%H:%M:%S")
    if precision == 0:
        return f"{base}Z"
    return f"{base}.{value.fractional_digits[:precision]}Z"


def _validate_scan_finished_terminal_evidence(
    value: object,
    *,
    expected_decision: str = "different-common-precision",
) -> None:
    if not isinstance(value, Mapping):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    required = {
        "blobEvidenceSha256",
        "blobTagResult",
        "blobTagsCommonPrecisionUtc",
        "blobTagsTimestamp",
        "commonPrecisionEqual",
        "comparisonContract",
        "comparisonDecision",
        "comparisonPrecisionFractionalSecondDigits",
        "correlationIdSha256",
        "etagComparison",
        "etagSha256",
        "exactInstantDeltaMicroseconds",
        "exactInstantEqual",
        "integritySha256",
        "logAnalyticsEvidenceSha256",
        "logAnalyticsCommonPrecisionUtc",
        "logAnalyticsMinusBlobTagsMicroseconds",
        "logAnalyticsResult",
        "logAnalyticsTimestamp",
        "providerVersionSha256",
        "uriComparison",
        "uriSha256",
    }
    if set(value) != required:
        _fail("scanner-proof-scan-finished-evidence-malformed")
    integrity = value.get("integritySha256")
    body = {
        key: cast(JsonValue, item)
        for key, item in value.items()
        if key != "integritySha256"
    }
    hashes = {
        "blobEvidenceSha256",
        "correlationIdSha256",
        "etagSha256",
        "logAnalyticsEvidenceSha256",
        "providerVersionSha256",
        "uriSha256",
    }
    delta = value.get("logAnalyticsMinusBlobTagsMicroseconds")
    if (
        expected_decision
        not in {"different-common-precision", "equal-common-precision"}
        or not isinstance(integrity, str)
        or _SHA256.fullmatch(integrity) is None
        or integrity
        != _scanner_runtime_hash(
            cast(JsonValue, body),
            "mobius.scanner-bridge.scan-finished-comparison.v2",
        )
        or any(
            not isinstance(value.get(key), str)
            or _SHA256.fullmatch(cast(str, value[key])) is None
            for key in hashes
        )
        or value.get("comparisonContract") != SCAN_FINISHED_COMPARISON_CONTRACT
        or value.get("comparisonDecision") != expected_decision
        or value.get("uriComparison") != "matched"
        or value.get("etagComparison") != "matched"
        or value.get("blobTagResult")
        not in {"Error", "Malicious", "No threats found", "Not scanned"}
        or value.get("logAnalyticsResult")
        not in {"Error", "Malicious", "No threats found", "Not Scanned"}
        or not isinstance(delta, int)
        or isinstance(delta, bool)
        or value.get("exactInstantDeltaMicroseconds") != delta
    ):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    blob_timestamp = _parsed_timestamp_representation(value.get("blobTagsTimestamp"))
    log_timestamp = _parsed_timestamp_representation(value.get("logAnalyticsTimestamp"))
    common_precision = min(blob_timestamp.precision, log_timestamp.precision)
    exact_precision = max(blob_timestamp.precision, log_timestamp.precision)
    exact_equal = _timestamp_units(blob_timestamp, exact_precision) == _timestamp_units(
        log_timestamp, exact_precision
    )
    common_equal = _timestamp_units(
        blob_timestamp, common_precision
    ) == _timestamp_units(log_timestamp, common_precision)
    if (
        _delta_microseconds(log_timestamp.parsed, blob_timestamp.parsed) != delta
        or value.get("comparisonPrecisionFractionalSecondDigits") != common_precision
        or value.get("exactInstantEqual") is not exact_equal
        or value.get("commonPrecisionEqual") is not common_equal
        or value.get("blobTagsCommonPrecisionUtc")
        != _common_precision_utc(blob_timestamp, common_precision)
        or value.get("logAnalyticsCommonPrecisionUtc")
        != _common_precision_utc(log_timestamp, common_precision)
        or (expected_decision == "equal-common-precision") is not common_equal
    ):
        _fail("scanner-proof-scan-finished-evidence-malformed")


def _validate_legacy_scan_finished_terminal_evidence(value: object) -> None:
    """Validate retained v1 failure evidence without reinterpreting its bytes."""

    if not isinstance(value, Mapping):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    required = {
        "blobEvidenceSha256",
        "blobTagResult",
        "blobTagsTimestamp",
        "comparisonContract",
        "comparisonDecision",
        "correlationIdSha256",
        "etagComparison",
        "etagSha256",
        "integritySha256",
        "logAnalyticsEvidenceSha256",
        "logAnalyticsMinusBlobTagsMicroseconds",
        "logAnalyticsResult",
        "logAnalyticsTimestamp",
        "providerVersionSha256",
        "uriComparison",
        "uriSha256",
    }
    if set(value) != required:
        _fail("scanner-proof-scan-finished-evidence-malformed")
    integrity = value.get("integritySha256")
    body = {
        key: cast(JsonValue, item)
        for key, item in value.items()
        if key != "integritySha256"
    }
    hashes = {
        "blobEvidenceSha256",
        "correlationIdSha256",
        "etagSha256",
        "logAnalyticsEvidenceSha256",
        "providerVersionSha256",
        "uriSha256",
    }
    delta = value.get("logAnalyticsMinusBlobTagsMicroseconds")
    if (
        not isinstance(integrity, str)
        or _SHA256.fullmatch(integrity) is None
        or integrity
        != _scanner_runtime_hash(
            cast(JsonValue, body),
            "mobius.scanner-bridge.scan-finished-comparison.v1",
        )
        or any(
            not isinstance(value.get(key), str)
            or _SHA256.fullmatch(cast(str, value[key])) is None
            for key in hashes
        )
        or value.get("comparisonContract") != LEGACY_SCAN_FINISHED_COMPARISON_CONTRACT
        or value.get("comparisonDecision") != "different-instant"
        or value.get("uriComparison") != "matched"
        or value.get("etagComparison") != "matched"
        or value.get("blobTagResult") != "No threats found"
        or value.get("logAnalyticsResult") != "No threats found"
        or not isinstance(delta, int)
        or isinstance(delta, bool)
        or delta == 0
    ):
        _fail("scanner-proof-scan-finished-evidence-malformed")
    blob_timestamp = _parsed_timestamp_representation(value.get("blobTagsTimestamp"))
    log_timestamp = _parsed_timestamp_representation(value.get("logAnalyticsTimestamp"))
    if _delta_microseconds(log_timestamp.parsed, blob_timestamp.parsed) != delta:
        _fail("scanner-proof-scan-finished-evidence-malformed")


def _proof_failure_marker(
    authorization: ScannerBridgeRecoveryAuthorization,
    execution_name: str,
    *,
    log_output: str | None = None,
) -> dict[str, JsonValue]:
    marker = _find_marker(
        log_output
        if log_output is not None
        else _proof_log_output(authorization, execution_name),
        "SCANNER_RESULT_BRIDGE_FAILED",
    )
    required = {
        "attemptCount",
        "blobTagObservationCount",
        "failureCode",
        "marker",
        "markerIntegritySha256",
        "schemaVersion",
        "terminalEvidence",
    }
    if marker is None or set(marker) != required:
        _fail("scanner-proof-failure-marker-malformed")
    attempt_count = marker.get("attemptCount")
    observation_count = marker.get("blobTagObservationCount")
    failure_code = marker.get("failureCode")
    integrity = marker.get("markerIntegritySha256")
    body = {
        key: value for key, value in marker.items() if key != "markerIntegritySha256"
    }
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or not 1 <= attempt_count <= 120
        or not isinstance(observation_count, int)
        or isinstance(observation_count, bool)
        or not 0 <= observation_count <= 120
        or not isinstance(failure_code, str)
        or _FAILURE_CODE.fullmatch(failure_code) is None
        or not isinstance(integrity, str)
        or _SHA256.fullmatch(integrity) is None
        or integrity
        != _scanner_runtime_hash(
            cast(JsonValue, body),
            "mobius.scanner-bridge.proof-failure-marker.v2",
        )
        or marker.get("marker") != "SCANNER_RESULT_BRIDGE_FAILED"
        or marker.get("schemaVersion")
        != "mobius.scanner-result-bridge.proof-failure.v2"
    ):
        _fail("scanner-proof-failure-marker-malformed")
    terminal_evidence = marker.get("terminalEvidence")
    if failure_code == "scanner-correlation-scan-finished-mismatch":
        _validate_scan_finished_terminal_evidence(terminal_evidence)
    elif terminal_evidence is not None:
        _fail("scanner-proof-failure-marker-malformed")
    return cast(dict[str, JsonValue], marker)


def _marker_string_tuple(
    marker: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    value = marker.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str)
        or not item
        or len(item.encode()) > 256
        or any(ord(character) < 32 for character in item)
        for item in value
    ):
        _fail("scanner-proof-blob-tag-observation-malformed")
    return tuple(cast(list[str], value))


def _validate_blob_tag_observation_marker(
    marker: object,
    *,
    failure_code: str | None = None,
    expected_decision: str | None = None,
) -> dict[str, JsonValue]:
    if not isinstance(marker, dict):
        _fail("scanner-proof-blob-tag-observation-malformed")
    required = {
        "differentBlobVersion",
        "exactComparisonDecision",
        "httpStatus",
        "integritySha256",
        "marker",
        "parserNormalizationPath",
        "queriedBlobUriSha256",
        "queriedBlobVersionIdSha256",
        "queriedEtagSha256",
        "requestCorrelationId",
        "requiredKeysFound",
        "requiredKeysMissing",
        "responseEmpty",
        "responseEtagSha256",
        "responseVersionIdSha256",
        "returnedTagKeys",
        "schemaVersion",
        "tagCount",
        "unexpectedKeys",
        "versionIdentityPath",
    }
    if set(marker) != required:
        _fail("scanner-proof-blob-tag-observation-malformed")
    integrity = marker.get("integritySha256")
    if not isinstance(integrity, str) or _SHA256.fullmatch(integrity) is None:
        _fail("scanner-proof-blob-tag-observation-malformed")
    body = {
        key: cast(JsonValue, value)
        for key, value in marker.items()
        if key != "integritySha256"
    }
    if _blob_tag_observation_hash(cast(JsonValue, body)) != integrity:
        _fail("scanner-proof-blob-tag-observation-integrity-unproved")
    hashes = (
        "queriedBlobUriSha256",
        "queriedBlobVersionIdSha256",
        "queriedEtagSha256",
    )
    if any(
        not isinstance(marker.get(key), str)
        or _SHA256.fullmatch(cast(str, marker[key])) is None
        for key in hashes
    ):
        _fail("scanner-proof-blob-tag-observation-malformed")
    for key in ("responseEtagSha256", "responseVersionIdSha256"):
        value = marker.get(key)
        if value is not None and (
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
        ):
            _fail("scanner-proof-blob-tag-observation-malformed")
    request_id = marker.get("requestCorrelationId")
    if request_id is not None and (
        not isinstance(request_id, str) or _UUID.fullmatch(request_id) is None
    ):
        _fail("scanner-proof-blob-tag-observation-malformed")
    http_status = marker.get("httpStatus")
    if http_status is not None and (
        not isinstance(http_status, int)
        or isinstance(http_status, bool)
        or not 100 <= http_status <= 599
    ):
        _fail("scanner-proof-blob-tag-observation-malformed")
    tag_count = marker.get("tagCount")
    different_version = marker.get("differentBlobVersion")
    response_empty = marker.get("responseEmpty")
    if (
        not isinstance(tag_count, int)
        or isinstance(tag_count, bool)
        or not 0 <= tag_count <= 10
        or not isinstance(different_version, bool)
        or not isinstance(response_empty, bool)
    ):
        _fail("scanner-proof-blob-tag-observation-malformed")
    returned = _marker_string_tuple(marker, "returnedTagKeys")
    found = _marker_string_tuple(marker, "requiredKeysFound")
    missing = _marker_string_tuple(marker, "requiredKeysMissing")
    unexpected = _marker_string_tuple(marker, "unexpectedKeys")
    expected_keys = (BLOB_RESULT_TAG, BLOB_SCAN_TIME_TAG)
    if (
        tag_count != len(returned)
        or response_empty != (not returned)
        or found != tuple(key for key in expected_keys if key in returned)
        or missing != tuple(key for key in expected_keys if key not in returned)
        or unexpected != tuple(key for key in returned if key not in expected_keys)
    ):
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    decision = marker.get("exactComparisonDecision")
    normalization = marker.get("parserNormalizationPath")
    version_path = marker.get("versionIdentityPath")
    if (
        not isinstance(decision, str)
        or decision not in _BLOB_TAG_DECISIONS
        or normalization
        not in {
            "not-run",
            BLOB_TAG_NORMALIZATION_PATH,
            f"{BLOB_TAG_NORMALIZATION_PATH}:failed",
        }
        or version_path not in _BLOB_TAG_VERSION_PATHS
        or marker.get("marker") != BLOB_TAG_OBSERVATION_MARKER
        or marker.get("schemaVersion") != BLOB_TAG_OBSERVATION_SCHEMA
    ):
        _fail("scanner-proof-blob-tag-observation-malformed")
    response_version = marker.get("responseVersionIdSha256")
    response_etag = marker.get("responseEtagSha256")
    expected_header_presence = {
        "request-version-id-plus-if-match": (False, False),
        "response-etag": (False, True),
        "response-unavailable": (False, False),
        "response-version-id": (True, False),
        "response-version-id-and-etag": (True, True),
    }
    if expected_header_presence[version_path] != (
        response_version is not None,
        response_etag is not None,
    ):
        _fail("scanner-proof-blob-tag-observation-version-unproved")
    if decision == "rejected-http-status":
        if (
            http_status is None
            or 200 <= http_status < 300
            or normalization != "not-run"
        ):
            _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    elif decision == "rejected-observability-gap":
        if http_status is not None or normalization != "not-run":
            _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    elif http_status is None or not 200 <= http_status < 300:
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if decision == "rejected-parser-normalization" and normalization != (
        f"{BLOB_TAG_NORMALIZATION_PATH}:failed"
    ):
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if decision == "rejected-version-mismatch" and not different_version:
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if decision == "rejected-empty" and not response_empty:
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if decision == "rejected-required-key-missing" and (not missing or response_empty):
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if decision == "rejected-unexpected-key" and (not unexpected or missing):
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if decision == "accepted" and (
        missing
        or unexpected
        or different_version
        or normalization != BLOB_TAG_NORMALIZATION_PATH
    ):
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    if (
        failure_code in _BLOB_TAG_FAILURE_DECISIONS
        and _BLOB_TAG_FAILURE_DECISIONS[failure_code] != decision
    ):
        _fail("scanner-proof-blob-tag-observation-failure-mismatch")
    if expected_decision is not None and decision != expected_decision:
        _fail("scanner-proof-blob-tag-observation-comparison-unproved")
    return cast(dict[str, JsonValue], marker)


def _verified_retained_record(
    value: Mapping[str, object],
    *,
    schema: str,
    domain: str,
    required: set[str],
) -> dict[str, JsonValue]:
    if set(value) != required or value.get("schemaVersion") != schema:
        _fail("scanner-proof-reconciliation-history-malformed")
    integrity = value.get("integritySha256")
    body = {
        key: cast(JsonValue, item)
        for key, item in value.items()
        if key != "integritySha256"
    }
    if (
        not isinstance(integrity, str)
        or _SHA256.fullmatch(integrity) is None
        or integrity != _canonical_hash(cast(JsonValue, body), domain)
    ):
        _fail("scanner-proof-reconciliation-history-integrity-invalid")
    return cast(dict[str, JsonValue], dict(value))


def _retained_failure_marker(log_output: str) -> dict[str, JsonValue]:
    marker = _find_marker(log_output, "SCANNER_RESULT_BRIDGE_FAILED")
    required = {
        "attemptCount",
        "blobTagObservationCount",
        "failureCode",
        "marker",
        "markerIntegritySha256",
        "schemaVersion",
        "terminalEvidence",
    }
    if marker is None or set(marker) != required:
        _fail("scanner-proof-reconciliation-failure-marker-malformed")
    integrity = marker.get("markerIntegritySha256")
    body = {
        key: cast(JsonValue, item)
        for key, item in marker.items()
        if key != "markerIntegritySha256"
    }
    if (
        marker.get("attemptCount") != 120
        or marker.get("blobTagObservationCount") != 120
        or marker.get("failureCode") != "scanner-correlation-scan-finished-mismatch"
        or marker.get("marker") != "SCANNER_RESULT_BRIDGE_FAILED"
        or marker.get("schemaVersion")
        != "mobius.scanner-result-bridge.proof-failure.v2"
        or integrity != RETAINED_PROOF_FAILURE_MARKER_INTEGRITY
        or integrity
        != _scanner_runtime_hash(
            cast(JsonValue, body),
            "mobius.scanner-bridge.proof-failure-marker.v2",
        )
    ):
        _fail("scanner-proof-reconciliation-failure-marker-integrity-invalid")
    terminal = marker.get("terminalEvidence")
    _validate_legacy_scan_finished_terminal_evidence(terminal)
    if (
        not isinstance(terminal, Mapping)
        or terminal.get("integritySha256") != RETAINED_PROOF_TERMINAL_EVIDENCE_INTEGRITY
    ):
        _fail("scanner-proof-reconciliation-terminal-integrity-invalid")
    return cast(dict[str, JsonValue], marker)


def _retained_blob_tag_observation(log_output: str) -> dict[str, JsonValue]:
    marker = _find_marker(log_output, BLOB_TAG_OBSERVATION_MARKER)
    observation = _validate_blob_tag_observation_marker(
        marker,
        expected_decision="accepted",
    )
    if observation.get("integritySha256") != RETAINED_PROOF_BLOB_OBSERVATION_INTEGRITY:
        _fail("scanner-proof-reconciliation-blob-observation-integrity-invalid")
    return observation


def reconcile_retained_scanner_proof(
    *,
    correction_repository_head: str,
    ordinal_binding: Mapping[str, object],
    execution_start: Mapping[str, object],
    failure_log_output: str,
    blob_tag_log_output: str,
    proof_residue_count: int,
    observed_at: datetime,
    output_path: Path,
) -> dict[str, JsonValue]:
    """Reconcile retained Proof #2 evidence without authority or Azure execution."""

    if (
        _SHA40.fullmatch(correction_repository_head) is None
        or correction_repository_head == RETAINED_PROOF_SOURCE_HEAD
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or proof_residue_count != 0
    ):
        _fail("scanner-proof-reconciliation-binding-invalid")
    ordinal = _verified_retained_record(
        ordinal_binding,
        schema="mobius.milestone-7.7.scanner-proof-ordinal-binding-evidence.v1",
        domain=(
            "solarplexus-mobius/milestone-7.7/scanner-proof-ordinal-binding-evidence/v1"
        ),
        required={
            "absoluteTotalExecutionCeiling",
            "apiImageDigest",
            "authorizedAdditionalExecutionCount",
            "authorizedAtUtc",
            "buildInputSha256",
            "cleanupDeadlineUtc",
            "cleanupGeneration",
            "expiresAtUtc",
            "foundationIntegritySha256",
            "integritySha256",
            "ociConfigDigest",
            "priorExecutionCorrelationId",
            "priorExecutionCount",
            "repositoryHead",
            "schemaVersion",
            "typedAuthorizationIntegritySha256",
        },
    )
    start = _verified_retained_record(
        execution_start,
        schema="mobius.milestone-7.7.scanner-proof-execution-start-evidence.v1",
        domain=(
            "solarplexus-mobius/milestone-7.7/scanner-proof-execution-start-evidence/v1"
        ),
        required={
            "absoluteTotalExecutionCeiling",
            "apiImageDigest",
            "authorizationIntegritySha256",
            "executionName",
            "executionOrdinal",
            "integritySha256",
            "ociConfigDigest",
            "priorExecutionCount",
            "proofJobId",
            "schemaVersion",
            "startTimeUtc",
            "temporaryAuthorityPrincipalId",
            "temporaryAuthorityScope",
            "temporaryRoleAssignmentId",
            "temporaryRoleDefinitionId",
        },
    )
    ordinal_expectations: dict[str, JsonValue] = {
        "absoluteTotalExecutionCeiling": 2,
        "apiImageDigest": RETAINED_PROOF_IMAGE,
        "authorizedAdditionalExecutionCount": 1,
        "cleanupDeadlineUtc": RETAINED_PROOF_CLEANUP_DEADLINE,
        "cleanupGeneration": 4,
        "ociConfigDigest": RETAINED_PROOF_OCI_CONFIG,
        "priorExecutionCount": 1,
        "repositoryHead": RETAINED_PROOF_SOURCE_HEAD,
        "typedAuthorizationIntegritySha256": RETAINED_PROOF_AUTHORIZATION_INTEGRITY,
    }
    start_expectations: dict[str, JsonValue] = {
        "absoluteTotalExecutionCeiling": 2,
        "apiImageDigest": RETAINED_PROOF_IMAGE,
        "authorizationIntegritySha256": RETAINED_PROOF_AUTHORIZATION_INTEGRITY,
        "executionName": RETAINED_PROOF_EXECUTION,
        "executionOrdinal": 2,
        "ociConfigDigest": RETAINED_PROOF_OCI_CONFIG,
        "priorExecutionCount": 1,
    }
    if any(
        ordinal.get(key) != expected for key, expected in ordinal_expectations.items()
    ) or any(
        start.get(key) != expected for key, expected in start_expectations.items()
    ):
        _fail("scanner-proof-reconciliation-execution-history-invalid")

    failure_marker = _retained_failure_marker(failure_log_output)
    observation = _retained_blob_tag_observation(blob_tag_log_output)
    terminal = failure_marker.get("terminalEvidence")
    if not isinstance(terminal, Mapping):
        _fail("scanner-proof-reconciliation-terminal-evidence-malformed")
    blob_mapping = terminal.get("blobTagsTimestamp")
    log_mapping = terminal.get("logAnalyticsTimestamp")
    if not isinstance(blob_mapping, Mapping) or not isinstance(log_mapping, Mapping):
        _fail("scanner-proof-reconciliation-terminal-evidence-malformed")
    blob_timestamp = _parsed_timestamp_representation(blob_mapping)
    log_timestamp = _parsed_timestamp_representation(log_mapping)
    common_precision = min(blob_timestamp.precision, log_timestamp.precision)
    exact_precision = max(blob_timestamp.precision, log_timestamp.precision)
    exact_equal = _timestamp_units(blob_timestamp, exact_precision) == _timestamp_units(
        log_timestamp, exact_precision
    )
    common_equal = _timestamp_units(
        blob_timestamp, common_precision
    ) == _timestamp_units(log_timestamp, common_precision)
    blob_raw = blob_mapping.get("rawValue")
    log_raw = log_mapping.get("rawValue")
    delta = terminal.get("logAnalyticsMinusBlobTagsMicroseconds")
    required_keys = (BLOB_RESULT_TAG, BLOB_SCAN_TIME_TAG)
    if (
        blob_raw != "2026-08-11 17:15:16Z"
        or log_raw != "2026-08-11T17:15:16.4539552Z"
        or blob_timestamp.precision != 0
        or log_timestamp.precision != 7
        or delta != 453_955
        or exact_equal
        or not common_equal
        or terminal.get("uriComparison") != "matched"
        or terminal.get("etagComparison") != "matched"
        or terminal.get("blobTagResult") != "No threats found"
        or terminal.get("logAnalyticsResult") != "No threats found"
        or observation.get("queriedBlobUriSha256") != terminal.get("uriSha256")
        or observation.get("queriedEtagSha256") != terminal.get("etagSha256")
        or observation.get("queriedBlobVersionIdSha256")
        != terminal.get("providerVersionSha256")
        or tuple(cast(list[str], observation.get("returnedTagKeys"))) != required_keys
        or tuple(cast(list[str], observation.get("requiredKeysFound"))) != required_keys
        or observation.get("requiredKeysMissing") != []
        or observation.get("unexpectedKeys") != []
    ):
        _fail("scanner-proof-reconciliation-correlation-unproved")

    body: dict[str, JsonValue] = {
        "authorizationCreated": False,
        "authorizationIntegritySha256": RETAINED_PROOF_AUTHORIZATION_INTEGRITY,
        "azureMutationPerformed": False,
        "blobTagObservationIntegritySha256": (
            RETAINED_PROOF_BLOB_OBSERVATION_INTEGRITY
        ),
        "cleanupDeadlineUtc": RETAINED_PROOF_CLEANUP_DEADLINE,
        "commonPrecisionEqual": common_equal,
        "commonPrecisionProjection": {
            "blobTagsUtc": _common_precision_utc(blob_timestamp, common_precision),
            "logAnalyticsUtc": _common_precision_utc(log_timestamp, common_precision),
        },
        "comparisonPrecisionFractionalSecondDigits": common_precision,
        "correctionRepositoryHead": correction_repository_head,
        "correlationDecisions": {
            "blobTagKeySet": "matched",
            "etag": "matched",
            "result": "matched-clean",
            "uri": "matched",
            "version": "matched",
        },
        "exactInstantDeltaMicroseconds": delta,
        "exactInstantEqual": exact_equal,
        "executionName": RETAINED_PROOF_EXECUTION,
        "finalSemanticDecision": (
            "equivalent-at-maximum-common-representable-precision"
        ),
        "historicalFailureMarkerIntegritySha256": (
            RETAINED_PROOF_FAILURE_MARKER_INTEGRITY
        ),
        "historicalMarkerBytesRewritten": False,
        "historicalTerminalEvidenceIntegritySha256": (
            RETAINED_PROOF_TERMINAL_EVIDENCE_INTEGRITY
        ),
        "ociConfigDigest": RETAINED_PROOF_OCI_CONFIG,
        "originalParsedUtc": {
            "blobTags": cast(str, blob_mapping.get("canonicalUtc")),
            "logAnalytics": cast(str, log_mapping.get("canonicalUtc")),
        },
        "originalRaw": {
            "blobTags": blob_raw,
            "logAnalytics": log_raw,
        },
        "proofExecutionCount": 2,
        "proofExecutionCreated": False,
        "proofImageDigest": RETAINED_PROOF_IMAGE,
        "proofResidueCount": proof_residue_count,
        "reconciledAtUtc": _format_utc(observed_at),
        "scannerGateDecision": "SCANNER_PROOF_PASSED_FROM_RECONCILED_EVIDENCE",
        "schemaVersion": "mobius.scanner-result-bridge.proof-reconciliation.v1",
        "sourcePrecisionFractionalSecondDigits": {
            "blobTags": blob_timestamp.precision,
            "logAnalytics": log_timestamp.precision,
        },
        "sourceRepositoryHead": RETAINED_PROOF_SOURCE_HEAD,
        "sourceRecordIntegrities": {
            "executionStart": cast(str, start["integritySha256"]),
            "ordinalBinding": cast(str, ordinal["integritySha256"]),
        },
    }
    artifact: dict[str, JsonValue] = {
        **body,
        "reconciliationIntegritySha256": _canonical_hash(
            cast(JsonValue, body),
            "mobius.scanner-result-bridge.proof-reconciliation.v1",
        ),
    }
    serialized = canonical_bytes(cast(JsonValue, artifact))
    if len(serialized) > RECONCILIATION_EVIDENCE_MAX_BYTES:
        _fail("scanner-proof-reconciliation-evidence-oversized")
    resolved = _outside_repository(
        output_path,
        "scanner-proof-reconciliation-evidence-inside-repository",
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-proof-reconciliation-evidence-already-exists")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("scanner-proof-reconciliation-evidence-write-failed")
    return artifact


def _proof_blob_tag_observation(
    authorization: ScannerBridgeRecoveryAuthorization,
    execution_name: str,
    *,
    failure_code: str,
    log_output: str | None = None,
) -> dict[str, JsonValue] | None:
    markers = _find_markers(
        log_output
        if log_output is not None
        else _proof_log_output(authorization, execution_name),
        BLOB_TAG_OBSERVATION_MARKER,
    )
    required_for_failure = failure_code in _BLOB_TAG_FAILURE_DECISIONS
    if not markers:
        if required_for_failure:
            _fail("scanner-proof-blob-tag-observation-missing")
        return None
    return _validate_blob_tag_observation_marker(
        markers[-1],
        failure_code=failure_code,
    )


def _not_found(exc: lifecycle.AzureCommandError) -> bool:
    return exc.sanitized_azure_error_code in {
        "notfound",
        "not-found",
        "containerappsjobnotfound",
        "container-apps-job-not-found",
        "roleassignmentnotfound",
        "role-assignment-not-found",
        "roledefinitiondoesnotexist",
        "role-definition-does-not-exist",
        "resourcenotfound",
        "resource-not-found",
    }


def _verify_proof_graph(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    assignment_id: str,
    worker_principal_id: str,
    worker_client_id: str,
    workspace_customer_id: str,
) -> str:
    deadline = time.monotonic() + PROOF_GRAPH_PROPAGATION_SECONDS
    while True:
        try:
            return _proof_graph(
                authorization,
                assignment_id=assignment_id,
                worker_principal_id=worker_principal_id,
                worker_client_id=worker_client_id,
                workspace_customer_id=workspace_customer_id,
            )
        except lifecycle.AzureCommandError as exc:
            if not (
                _not_found(exc)
                or exc.sanitized_azure_error_code == "azure-command-nonzero"
            ):
                raise
            if time.monotonic() >= deadline:
                _fail("scanner-proof-graph-propagation-timeout")
            time.sleep(PROOF_GRAPH_POLL_SECONDS)


def _wait_for_proof_rbac_propagation(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    assignment_id: str,
    worker_principal_id: str,
    worker_client_id: str,
    workspace_customer_id: str,
) -> str:
    """Hold the exact graph stable while Azure Storage's RBAC cache converges."""

    deadline = time.monotonic() + PROOF_RBAC_PROPAGATION_SECONDS
    while True:
        integrity = _verify_proof_graph(
            authorization,
            assignment_id=assignment_id,
            worker_principal_id=worker_principal_id,
            worker_client_id=worker_client_id,
            workspace_customer_id=workspace_customer_id,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return integrity
        time.sleep(min(PROOF_RBAC_POLL_SECONDS, remaining))


def _resource_absent(resource_id: str, api_version: str) -> bool:
    try:
        _rest_get(resource_id, api_version, "{id:id}")
    except lifecycle.AzureCommandError as exc:
        if _not_found(exc):
            return True
        raise
    return False


def _wait_absent(resource_id: str, api_version: str, code: str) -> None:
    deadline = time.monotonic() + DELETION_PROPAGATION_SECONDS
    while True:
        if _resource_absent(resource_id, api_version):
            return
        if time.monotonic() >= deadline:
            _fail(code)
        time.sleep(DELETION_POLL_SECONDS)


def _delete_rest_resource(resource_id: str, api_version: str) -> None:
    deadline = time.monotonic() + DELETION_PROPAGATION_SECONDS
    while True:
        try:
            lifecycle._run(
                (
                    "az",
                    "rest",
                    "--method",
                    "delete",
                    "--url",
                    f"https://management.azure.com{resource_id}?api-version={api_version}",
                    "--output",
                    "none",
                    "--only-show-errors",
                )
            )
            return
        except lifecycle.AzureCommandError:
            if _resource_absent(resource_id, api_version):
                return
            if time.monotonic() >= deadline:
                raise
            time.sleep(DELETION_POLL_SECONDS)


def _remove_proof_residue(
    authorization: ScannerBridgeRecoveryAuthorization, assignment_id: str
) -> str:
    if authorization.proofJobId is None or authorization.proofRoleDefinitionId is None:
        _fail("scanner-proof-authorization-incomplete")
    try:
        lifecycle._delete_assignment(authorization.subscriptionId, assignment_id)
    except lifecycle.AzureCommandError:
        if not _resource_absent(assignment_id, ROLE_API_VERSION):
            raise
    _wait_absent(
        assignment_id,
        ROLE_API_VERSION,
        "scanner-proof-role-assignment-revocation-unproved",
    )
    _delete_rest_resource(authorization.proofJobId, JOB_API_VERSION)
    _wait_absent(
        authorization.proofJobId,
        JOB_API_VERSION,
        "scanner-proof-job-deletion-unproved",
    )
    _delete_rest_resource(authorization.proofRoleDefinitionId, ROLE_API_VERSION)
    _wait_absent(
        authorization.proofRoleDefinitionId,
        ROLE_API_VERSION,
        "scanner-proof-role-definition-deletion-unproved",
    )
    return _canonical_hash(
        cast(
            JsonValue,
            {
                "job": "absent",
                "roleAssignment": "absent",
                "roleDefinition": "absent",
            },
        ),
        "mobius.scanner-bridge.proof-residue.v1",
    )


def _success_marker_text(marker: Mapping[str, JsonValue], key: str) -> str:
    value = marker.get(key)
    if not isinstance(value, str):
        _fail("scanner-proof-marker-malformed")
    return value


def _build_live_evidence(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    readback: _FoundationReadback,
    execution_name: str,
    execution: Mapping[str, str | None],
    marker: Mapping[str, JsonValue],
    proof_graph_integrity: str,
    revocation_integrity: str,
    observed_at: datetime,
    control_plane_head: str | None = None,
) -> ScannerResultBridgeDeploymentEvidence:
    evidence_head = control_plane_head or authorization.repositoryHead
    completion_hash = _success_marker_text(marker, "completionTimeSha256")
    legacy = ScannerResultBridgeEvidence(
        observed_at_utc=_format_utc(observed_at),
        provider=PROVIDER,
        transport=TRANSPORT,
        schema_version=SCHEMA_VERSION,
        proofs={
            "provider": True,
            "resources": True,
            "identity": True,
            "rbac": True,
            "privatePath": True,
            "producer": True,
            "transport": True,
            "consumer": True,
            "schema": True,
            "correlation": True,
            "revocation": True,
        },
        correlation_id_sha256=_success_marker_text(marker, "correlationIdSha256"),
        blob_tag_evidence_sha256=_success_marker_text(marker, "blobEvidenceSha256"),
        log_analytics_evidence_sha256=_success_marker_text(
            marker, "logAnalyticsEvidenceSha256"
        ),
        object_version_or_etag_sha256=_success_marker_text(marker, "etagSha256"),
        storage_resource_sha256=_hash_text(authorization.storageAccountId),
        completion_time_sha256=completion_hash,
        decision="clean",
    )
    environment = _canonical_hash(
        cast(
            JsonValue,
            {
                "subscription": _hash_text(authorization.subscriptionId),
                "target": _hash_text(authorization.targetResourceGroupId),
            },
        ),
        "mobius.scanner-bridge.environment.v1",
    )
    operation = _hash_text(authorization.authorizationIntegritySha256)
    execution_projection = cast(
        JsonValue,
        {"execution": dict(execution), "marker": dict(marker)},
    )
    consumer_projection: dict[str, JsonValue] = {
        "apiImageDigest": authorization.apiImageDigest,
        "execution": execution_projection,
        "sourceHead": authorization.repositoryHead,
    }
    if control_plane_head is not None:
        consumer_projection["reconciliationControlPlaneHead"] = evidence_head
    consumer_proof = _canonical_hash(
        cast(JsonValue, consumer_projection),
        "mobius.scanner-bridge.consumer-live-proof.v1",
    )
    malicious_contract_proof = _canonical_hash(
        cast(
            JsonValue,
            {
                "proofType": "focused-local-contract-test",
                "repositoryHead": evidence_head,
                "test": "private-scanner-bridge-malicious-idempotent-rejection",
            },
        ),
        "mobius.scanner-bridge.malicious-contract-proof.v1",
    )
    evidence = ScannerResultBridgeDeploymentEvidence(
        control_plane_head=evidence_head,
        environment_sha256=environment,
        operation_id_sha256=operation,
        observed_at_utc=_format_utc(observed_at),
        legacy_evidence=legacy,
        provider_resource_id_sha256=_hash_text(
            f"{authorization.storageAccountId}/providers/Microsoft.Security/"
            "defenderForStorageSettings/current"
        ),
        provider_api_version=DEFENDER_API_VERSION,
        provider_enabled=True,
        provider_capability_proof_integrity=readback.provider_proof_integrity,
        diagnostic_setting_resource_id_sha256=_hash_text(
            f"{authorization.storageAccountId}/providers/Microsoft.Security/"
            "defenderForStorageSettings/current/providers/Microsoft.Insights/"
            "diagnosticSettings/mobius77-defender-scan-results"
        ),
        storage_resource_id_sha256=_hash_text(authorization.storageAccountId),
        quarantine_container="quarantine",
        blob_identity_sha256=_success_marker_text(marker, "blobUriSha256"),
        content_sha256=_success_marker_text(marker, "contentSha256"),
        scan_request_id_sha256=_success_marker_text(marker, "scanRequestIdSha256"),
        producer_proof_integrity=_canonical_hash(
            cast(
                JsonValue,
                {
                    "account": _success_marker_text(marker, "accountNameSha256"),
                    "blob": _success_marker_text(marker, "blobUriSha256"),
                    "providerVersion": _success_marker_text(
                        marker, "providerVersionSha256"
                    ),
                },
            ),
            "mobius.scanner-bridge.producer-live-proof.v1",
        ),
        blob_tag_result_sha256=_success_marker_text(marker, "blobTagResultSha256"),
        log_analytics_workspace_id_sha256=_hash_text(
            authorization.logAnalyticsWorkspaceId
        ),
        log_analytics_table="StorageMalwareScanningResults",
        log_query_sha256=_success_marker_text(marker, "logQuerySha256"),
        dual_source_proof_integrity=_success_marker_text(
            marker, "dualSourceEvidenceSha256"
        ),
        consumer_identity_sha256=_hash_text(readback.worker_principal_id),
        consumer_entry_point="scripts.worker.DocumentWorker",
        consumer_proof_integrity=consumer_proof,
        blob_reader_role_definition_sha256=_hash_text(WORKER_QUARANTINE_ROLE),
        log_reader_role_definition_sha256=_hash_text(LOG_ANALYTICS_READER_ROLE),
        blob_reader_scope_sha256=_hash_text(
            f"{authorization.storageAccountId}/blobServices/default/containers/quarantine"
        ),
        log_reader_scope_sha256=_hash_text(authorization.logAnalyticsWorkspaceId),
        worker_tag_write_denied=True,
        tag_write_denial_proof_integrity=readback.tag_write_denial_integrity,
        assignment_proof_integrity=proof_graph_integrity,
        ampls_resource_id_sha256=_hash_text(authorization.privateLinkScopeId),
        private_endpoint_resource_id_sha256=_hash_text(
            authorization.monitorPrivateEndpointId
        ),
        private_dns_zone_set_sha256=readback.private_path_control_plane_integrity,
        private_address_sha256=_success_marker_text(marker, "privateDnsEvidenceSha256"),
        tls_hostname_sha256=_success_marker_text(marker, "tlsHostnameSha256"),
        tls_version=_success_marker_text(marker, "tlsVersion"),
        private_path_proof_integrity=_canonical_hash(
            cast(
                JsonValue,
                {
                    "controlPlane": readback.private_path_control_plane_integrity,
                    "dns": _success_marker_text(marker, "privateDnsEvidenceSha256"),
                    "tls": _success_marker_text(marker, "tlsEvidenceSha256"),
                },
            ),
            "mobius.scanner-bridge.private-path-live-proof.v1",
        ),
        proof_job_resource_id_sha256=_hash_text(cast(str, authorization.proofJobId)),
        proof_execution_id_sha256=_hash_text(execution_name),
        clean_decision_proof_integrity=_success_marker_text(
            marker, "dualSourceEvidenceSha256"
        ),
        malicious_decision_proof_integrity=malicious_contract_proof,
        provider_owned_system_topic_preserved=True,
        revocation_proof_integrity=revocation_integrity,
        cleanup_inventory_integrity=readback.inventory_integrity,
        unresolved_reasons=(),
    )
    return build_scanner_result_bridge_deployment_evidence(evidence, now=observed_at)


def _precise_datetime(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        _fail(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code)
    return parsed.astimezone(UTC)


def _deployment_projection_values(value: object, code: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        _fail(code)
    result: dict[str, JsonValue] = {}
    for name, raw in value.items():
        if (
            not isinstance(name, str)
            or not isinstance(raw, Mapping)
            or "value" not in raw
        ):
            _fail(code)
        result[name] = cast(JsonValue, raw["value"])
    return result


def _log_analytics_rows(
    workspace_customer_id: str, query: str
) -> list[dict[str, JsonValue]]:
    raw = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "post",
            "--url",
            f"https://api.loganalytics.io/v1/workspaces/{workspace_customer_id}/query",
            "--body",
            json.dumps({"query": query}, separators=(",", ":")),
            "--headers",
            "Content-Type=application/json",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(raw, Mapping) or set(raw) - {"tables", "statistics", "render"}:
        _fail("scanner-proof-retained-diagnostics-malformed")
    tables = raw.get("tables")
    if (
        not isinstance(tables, list)
        or len(tables) != 1
        or not isinstance(tables[0], Mapping)
    ):
        _fail("scanner-proof-retained-diagnostics-malformed")
    table = tables[0]
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) > 64:
        _fail("scanner-proof-retained-diagnostics-malformed")
    names: list[str] = []
    for column in columns:
        if not isinstance(column, Mapping) or not isinstance(column.get("name"), str):
            _fail("scanner-proof-retained-diagnostics-malformed")
        names.append(cast(str, column["name"]))
    result: list[dict[str, JsonValue]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            _fail("scanner-proof-retained-diagnostics-malformed")
        result.append(dict(zip(names, row, strict=True)))
    return result


def _retained_success_readback(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    workspace_customer_id: str,
) -> dict[str, JsonValue]:
    execution = RETAINED_SUCCESS_PROOF_EXECUTION
    marker_query = f'''ContainerAppConsoleLogs
| where TimeGenerated between (datetime({authorization.authorizedAtUtc}) .. datetime({authorization.expiresAtUtc}))
| where JobName == "{PROOF_JOB}"
| where ContainerGroupName startswith "{execution}-"
| where Log contains "SCANNER_RESULT_BRIDGE_PROVED" or Log contains "SCANNER_RESULT_BRIDGE_FAILED"
| project TimeGenerated, IngestedAt=ingestion_time(), JobName, ContainerGroupName,
    ContainerName, ContainerImage, Stream, _ResourceId, Log
| order by TimeGenerated asc'''
    summary_query = f'''ContainerAppConsoleLogs
| where TimeGenerated between (datetime({authorization.authorizedAtUtc}) .. datetime({authorization.expiresAtUtc}))
| where JobName == "{PROOF_JOB}"
| summarize First=min(TimeGenerated), Last=max(TimeGenerated), Rows=count(),
    Success=countif(Log contains "SCANNER_RESULT_BRIDGE_PROVED"),
    Failure=countif(Log contains "SCANNER_RESULT_BRIDGE_FAILED"),
    Groups=dcount(ContainerGroupName), Images=dcount(ContainerImage)
    by ContainerGroupName, ContainerImage, JobName'''
    top = lifecycle._run(
        (
            "az",
            "deployment",
            "sub",
            "show",
            "--name",
            RETAINED_SUCCESS_DEPLOYMENT,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "{name:name,id:id,location:location,state:properties.provisioningState,"
            "timestamp:properties.timestamp,correlationId:properties.correlationId,"
            "templateHash:properties.templateHash,parameters:properties.parameters,"
            "outputs:properties.outputs}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    nested = lifecycle._run(
        (
            "az",
            "deployment",
            "group",
            "show",
            "--name",
            RETAINED_SUCCESS_NESTED_DEPLOYMENT,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "{name:name,id:id,state:properties.provisioningState,"
            "timestamp:properties.timestamp,correlationId:properties.correlationId,"
            "templateHash:properties.templateHash,parameters:properties.parameters,"
            "outputs:properties.outputs}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    operations = lifecycle._run(
        (
            "az",
            "deployment",
            "operation",
            "group",
            "list",
            "--name",
            RETAINED_SUCCESS_NESTED_DEPLOYMENT,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "[].{id:properties.targetResource.id,type:properties.targetResource.resourceType,"
            "operation:properties.provisioningOperation,state:properties.provisioningState,"
            "status:properties.statusCode,timestamp:properties.timestamp,"
            "trackingId:properties.trackingId}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    activity = lifecycle._run(
        (
            "az",
            "monitor",
            "activity-log",
            "list",
            "--subscription",
            authorization.subscriptionId,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--start-time",
            authorization.authorizedAtUtc,
            "--end-time",
            authorization.expiresAtUtc,
            "--max-events",
            "200",
            "--query",
            "[?operationName.value=='Microsoft.App/jobs/start/action' || "
            "operationName.value=='Microsoft.App/jobs/getAuthToken/action' || "
            "operationName.value=='Microsoft.App/jobs/delete' || "
            "operationName.value=='Microsoft.Authorization/roleAssignments/delete' || "
            "operationName.value=='Microsoft.Authorization/roleDefinitions/delete']."
            "{time:eventTimestamp,operation:operationName.value,status:status.value,"
            "subStatus:subStatus.value,resourceId:resourceId,correlationId:correlationId}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    return {
        "activity": activity,
        "consoleSummary": cast(
            JsonValue,
            _log_analytics_rows(workspace_customer_id, summary_query),
        ),
        "deployment": top,
        "deploymentOperations": operations,
        "markerRows": cast(
            JsonValue,
            _log_analytics_rows(workspace_customer_id, marker_query),
        ),
        "nestedDeployment": nested,
    }


def _matching_history_rows(
    rows: object,
    *,
    operation: str,
    resource_id: str,
    status: str,
) -> list[Mapping[str, object]]:
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        _fail("scanner-proof-retained-history-malformed")
    return [
        cast(Mapping[str, object], row)
        for row in rows
        if row.get("operation") == operation
        and row.get("status") == status
        and _same_resource_id(
            cast(JsonValue | None, row.get("resourceId")), resource_id
        )
    ]


def _single_history_time(
    rows: object,
    *,
    operation: str,
    resource_id: str,
    status: str,
) -> datetime:
    matching = _matching_history_rows(
        rows,
        operation=operation,
        resource_id=resource_id,
        status=status,
    )
    if len(matching) != 1:
        _fail("scanner-proof-retained-history-ambiguous")
    return _precise_datetime(
        matching[0].get("time"),
        "scanner-proof-retained-history-time-invalid",
    )


def _validate_consumed_proof_receipt(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    path = (
        _outside_repository(
            receipt_directory,
            "scanner-bridge-receipts-inside-repository",
        )
        / PROOF_RECEIPT_FILE
    )
    value = load_json(path)
    if not isinstance(value, Mapping):
        _fail("scanner-proof-retained-receipt-malformed")
    required = {
        "authorizationIntegritySha256",
        "claimedAtUtc",
        "receiptIntegritySha256",
        "receiptVersion",
        "replayDecision",
        "repositoryHead",
        "stage",
    }
    body = {key: item for key, item in value.items() if key != "receiptIntegritySha256"}
    claimed_raw = value.get("claimedAtUtc")
    if not isinstance(claimed_raw, str):
        _fail("scanner-proof-retained-receipt-time-invalid")
    claimed = _parse_utc(
        claimed_raw,
        "scanner-proof-retained-receipt-time-invalid",
    )
    if (
        set(value) != required
        or value.get("authorizationIntegritySha256")
        != authorization.authorizationIntegritySha256
        or value.get("receiptVersion") != RECEIPT_VERSION
        or value.get("replayDecision") != "deny"
        or value.get("repositoryHead") != authorization.repositoryHead
        or value.get("stage") != PROOF_STAGE
        or value.get("receiptIntegritySha256") != integrity_sha256(body, RECEIPT_DOMAIN)
    ):
        _fail("scanner-proof-retained-receipt-invalid")
    validate_scanner_bridge_recovery_authorization(
        authorization,
        expected_repository_head=authorization.repositoryHead,
        now_utc=claimed,
    )
    return cast(dict[str, JsonValue], dict(value))


def _validate_retained_publication_binding(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    ledger_path: Path,
    finalization_evidence_path: Path,
) -> dict[str, JsonValue]:
    ledger_value = load_json(_outside_repository(ledger_path, "retained-proof-ledger"))
    if (
        not isinstance(ledger_value, Mapping)
        or ledger_value.get("repositoryHead") != authorization.repositoryHead
        or ledger_value.get("ledgerIntegritySha256")
        != RETAINED_SUCCESS_LEDGER_INTEGRITY
        or authorization_ledger_integrity_sha256(ledger_value)
        != RETAINED_SUCCESS_LEDGER_INTEGRITY
    ):
        _fail("scanner-proof-retained-ledger-invalid")
    ledger = ledger_value
    published = ledger.get("publishedImage")
    if not isinstance(published, Mapping):
        _fail("scanner-proof-retained-image-binding-malformed")
    exact = {
        "controlPlaneHead": RETAINED_SUCCESS_SOURCE_HEAD,
        "imageBuildInputSha256": RETAINED_SUCCESS_BUILD_INPUT,
        "imageConfigDigest": RETAINED_SUCCESS_OCI_CONFIG,
        "imageSourceCommit": RETAINED_SUCCESS_IMAGE_SOURCE,
        "localImageId": RETAINED_SUCCESS_IMAGE.split("@", 1)[1],
        "platform": "linux/amd64",
        "repository": "opencanvas-api",
        "sourceTag": f"source-{RETAINED_SUCCESS_IMAGE_SOURCE}",
    }
    if any(published.get(key) != expected for key, expected in exact.items()):
        _fail("scanner-proof-retained-image-binding-invalid")
    finalization_value = load_json(
        _outside_repository(
            finalization_evidence_path, "retained-proof-finalization-evidence"
        )
    )
    if not isinstance(finalization_value, Mapping):
        _fail("scanner-proof-retained-finalization-malformed")
    finalization_body = {
        key: item
        for key, item in finalization_value.items()
        if key != "evidenceIntegritySha256"
    }
    manifest = RETAINED_SUCCESS_IMAGE.split("@", 1)[1]
    if (
        finalization_value.get("schemaVersion")
        != "mobius.milestone-7.7.acr-tag-finalization-evidence.v1"
        or finalization_value.get("ledgerIntegritySha256")
        != ledger.get("ledgerIntegritySha256")
        or finalization_value.get("manifestDigest") != manifest
        or finalization_value.get("registryConfigDigest") != RETAINED_SUCCESS_OCI_CONFIG
        or finalization_value.get("sourceTagSha256")
        != _hash_text(f"source-{RETAINED_SUCCESS_IMAGE_SOURCE}")
        or finalization_value.get("sourceTagAbsent") is not True
        or finalization_value.get("immutableManifestRetained") is not True
        or finalization_value.get("finalizerIdentityDeleted") is not True
        or finalization_value.get("secretValueAccessed") is not False
        or finalization_value.get("evidenceIntegritySha256")
        != integrity_sha256(finalization_body, FINALIZATION_EVIDENCE_DOMAIN)
    ):
        _fail("scanner-proof-retained-finalization-invalid")
    return {
        "finalizationEvidenceIntegritySha256": cast(
            str,
            finalization_value["evidenceIntegritySha256"],
        ),
        "ledgerIntegritySha256": cast(str, ledger["ledgerIntegritySha256"]),
    }


def _validate_retained_success_history(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    readback: Mapping[str, JsonValue],
    proof_resources_absent: bool,
) -> tuple[
    dict[str, str | None],
    dict[str, JsonValue],
    str,
    str,
    dict[str, JsonValue],
]:
    if not proof_resources_absent:
        _fail("scanner-proof-retained-residue-present")
    top = readback.get("deployment")
    nested = readback.get("nestedDeployment")
    operations = readback.get("deploymentOperations")
    activity = readback.get("activity")
    summaries = readback.get("consoleSummary")
    marker_rows = readback.get("markerRows")
    if (
        not isinstance(top, Mapping)
        or not isinstance(nested, Mapping)
        or not isinstance(operations, list)
        or not isinstance(activity, list)
        or not isinstance(summaries, list)
        or not isinstance(marker_rows, list)
    ):
        _fail("scanner-proof-retained-history-malformed")
    top_parameters = _deployment_projection_values(
        top.get("parameters"),
        "scanner-proof-retained-deployment-malformed",
    )
    top_outputs = _output_values(top.get("outputs"))
    assignment_id = _validate_deployment_outputs(authorization, top_outputs)
    if assignment_id is None:
        _fail("scanner-proof-retained-deployment-invalid")
    nested_parameters = _deployment_projection_values(
        nested.get("parameters"),
        "scanner-proof-retained-deployment-malformed",
    )
    nested_outputs = _output_values(nested.get("outputs"))
    correlation_id = top.get("correlationId")
    top_timestamp = _precise_datetime(
        top.get("timestamp"),
        "scanner-proof-retained-deployment-time-invalid",
    )
    nested_timestamp = _precise_datetime(
        nested.get("timestamp"),
        "scanner-proof-retained-deployment-time-invalid",
    )
    lifecycle_tags = nested_parameters.get("lifecycleTags")
    if (
        top.get("name") != RETAINED_SUCCESS_DEPLOYMENT
        or top.get("state") != "Succeeded"
        or top.get("location") != STAGING_LOCATION
        or top.get("templateHash") != RETAINED_SUCCESS_DEPLOYMENT_TEMPLATE_HASH
        or not isinstance(correlation_id, str)
        or _UUID.fullmatch(correlation_id) is None
        or nested.get("name") != RETAINED_SUCCESS_NESTED_DEPLOYMENT
        or nested.get("state") != "Succeeded"
        or nested.get("correlationId") != correlation_id
        or nested.get("templateHash") != RETAINED_SUCCESS_NESTED_TEMPLATE_HASH
        or nested_timestamp > top_timestamp
        or top_parameters.get("authorizationLedgerSha256")
        != authorization.authorizationIntegritySha256
        or top_parameters.get("deploymentStage") != PROOF_STAGE
        or top_parameters.get("apiImageDigest") != authorization.apiImageDigest
        or top_parameters.get("cleanupAtUtc") != authorization.cleanupDeadlineUtc
        or nested_parameters.get("proofCanarySeed")
        != authorization.authorizationIntegritySha256
        or nested_parameters.get("apiImageDigest") != authorization.apiImageDigest
        or nested_parameters.get("scannerProofDeploymentEnabled") is not True
        or nested_parameters.get("deploymentEnabled") is not False
        or nested_parameters.get("managedBindingDeploymentEnabled") is not True
        or not _same_resource_id(
            nested_parameters.get("targetResourceGroupId"),
            authorization.targetResourceGroupId,
        )
        or not _same_resource_id(
            nested_parameters.get("workerIdentityId"),
            authorization.workerIdentityId,
        )
        or not isinstance(lifecycle_tags, Mapping)
        or lifecycle_tags.get("mobius-source-commit") != authorization.repositoryHead
        or lifecycle_tags.get("mobius-cleanup-binding-sha256")
        != authorization.authorizationIntegritySha256
        or lifecycle_tags.get("mobius-expires-at-utc")
        != authorization.cleanupDeadlineUtc
        or nested_outputs.get("proofJobId") != authorization.proofJobId
        or nested_outputs.get("temporaryProofRoleId")
        != authorization.proofRoleDefinitionId
        or nested_outputs.get("temporaryProofRoleAssignmentId") != assignment_id
        or nested_outputs.get("proofDeploymentEnabled") is not True
        or nested_outputs.get("workerTagWriteAuthorized") is not False
    ):
        _fail("scanner-proof-retained-deployment-invalid")

    expected_operations = {
        cast(str, authorization.proofJobId): "Microsoft.App/jobs",
        cast(str, authorization.proofRoleDefinitionId): (
            "Microsoft.Authorization/roleDefinitions"
        ),
        assignment_id: "Microsoft.Authorization/roleAssignments",
    }
    operation_projection: list[dict[str, JsonValue]] = []
    for resource_id, resource_type in expected_operations.items():
        matching = [
            row
            for row in operations
            if isinstance(row, Mapping)
            and _same_resource_id(row.get("id"), resource_id)
            and row.get("type") == resource_type
            and row.get("operation") == "Create"
            and row.get("state") == "Succeeded"
        ]
        if len(matching) != 1:
            _fail("scanner-proof-retained-deployment-operation-ambiguous")
        row = matching[0]
        operation_projection.append(
            {
                "idSha256": _hash_text(resource_id.casefold()),
                "state": cast(str, row["state"]),
                "timestamp": cast(str, row["timestamp"]),
                "trackingId": cast(str, row["trackingId"]),
                "type": resource_type,
            }
        )

    job_id = cast(str, authorization.proofJobId)
    role_id = cast(str, authorization.proofRoleDefinitionId)
    start_time = _single_history_time(
        activity,
        operation="Microsoft.App/jobs/start/action",
        resource_id=job_id,
        status="Succeeded",
    )
    diagnostic_read_time = _single_history_time(
        activity,
        operation="Microsoft.App/jobs/getAuthToken/action",
        resource_id=job_id,
        status="Succeeded",
    )
    assignment_delete_started = _single_history_time(
        activity,
        operation="Microsoft.Authorization/roleAssignments/delete",
        resource_id=assignment_id,
        status="Started",
    )
    assignment_deleted = _single_history_time(
        activity,
        operation="Microsoft.Authorization/roleAssignments/delete",
        resource_id=assignment_id,
        status="Succeeded",
    )
    job_deleted = _single_history_time(
        activity,
        operation="Microsoft.App/jobs/delete",
        resource_id=job_id,
        status="Succeeded",
    )
    role_deleted = _single_history_time(
        activity,
        operation="Microsoft.Authorization/roleDefinitions/delete",
        resource_id=role_id,
        status="Succeeded",
    )
    start_successes = _matching_history_rows(
        activity,
        operation="Microsoft.App/jobs/start/action",
        resource_id=job_id,
        status="Succeeded",
    )
    if len(start_successes) != 1 or not (
        top_timestamp < start_time < assignment_delete_started
    ):
        _fail("scanner-proof-retained-execution-history-invalid")

    activity_bindings = [
        _matching_history_rows(
            activity,
            operation=operation,
            resource_id=resource_id,
            status=status,
        )[0]
        for operation, resource_id, status in (
            ("Microsoft.App/jobs/start/action", job_id, "Succeeded"),
            ("Microsoft.App/jobs/getAuthToken/action", job_id, "Succeeded"),
            (
                "Microsoft.Authorization/roleAssignments/delete",
                assignment_id,
                "Started",
            ),
            (
                "Microsoft.Authorization/roleAssignments/delete",
                assignment_id,
                "Succeeded",
            ),
            (
                "Microsoft.Authorization/roleDefinitions/delete",
                role_id,
                "Succeeded",
            ),
            ("Microsoft.App/jobs/delete", job_id, "Succeeded"),
        )
    ]
    activity_projection: list[dict[str, JsonValue]] = []
    for activity_row in activity_bindings:
        activity_correlation = activity_row.get("correlationId")
        activity_resource_id = activity_row.get("resourceId")
        if (
            not isinstance(activity_correlation, str)
            or _UUID.fullmatch(activity_correlation) is None
            or not isinstance(activity_resource_id, str)
        ):
            _fail("scanner-proof-retained-history-binding-invalid")
        activity_projection.append(
            {
                "correlationId": activity_correlation,
                "operation": cast(str, activity_row["operation"]),
                "resourceIdSha256": _hash_text(activity_resource_id.casefold()),
                "status": cast(str, activity_row["status"]),
                "time": cast(str, activity_row["time"]),
            }
        )
    activity_integrity = _canonical_hash(
        cast(JsonValue, activity_projection),
        "mobius.scanner-bridge.retained-activity-history.v1",
    )

    if len(summaries) != 1 or not isinstance(summaries[0], Mapping):
        _fail("scanner-proof-retained-diagnostics-ambiguous")
    summary = summaries[0]
    if len(marker_rows) != 1 or not isinstance(marker_rows[0], Mapping):
        _fail("scanner-proof-retained-marker-ambiguous")
    marker_row = marker_rows[0]
    log_output = marker_row.get("Log")
    if (
        not isinstance(log_output, str)
        or len(log_output.encode()) > PROOF_LOG_OUTPUT_MAX_BYTES
    ):
        _fail("scanner-proof-retained-marker-malformed")
    marker = _proof_marker_from_log_output(log_output)
    marker_time = _precise_datetime(
        marker_row.get("TimeGenerated"),
        "scanner-proof-retained-marker-time-invalid",
    )
    ingested_at = _precise_datetime(
        marker_row.get("IngestedAt"),
        "scanner-proof-retained-ingestion-time-invalid",
    )
    group = marker_row.get("ContainerGroupName")
    managed_environment_id = (
        f"{authorization.targetResourceGroupId}/providers/Microsoft.App/"
        f"managedEnvironments/{MANAGED_ENVIRONMENT}"
    )
    if (
        marker.get("markerIntegritySha256") != RETAINED_SUCCESS_MARKER_INTEGRITY
        or marker_row.get("JobName") != PROOF_JOB
        or marker_row.get("ContainerName") != PROOF_CONTAINER
        or marker_row.get("ContainerImage") != authorization.apiImageDigest
        or marker_row.get("Stream") != "stdout"
        or not isinstance(group, str)
        or re.fullmatch(
            rf"{re.escape(RETAINED_SUCCESS_PROOF_EXECUTION)}-[a-z0-9]+", group
        )
        is None
        or not _same_resource_id(marker_row.get("_ResourceId"), managed_environment_id)
        or summary.get("ContainerGroupName") != group
        or summary.get("ContainerImage") != authorization.apiImageDigest
        or summary.get("JobName") != PROOF_JOB
        or summary.get("Success") != 1
        or summary.get("Failure") != 0
        or summary.get("Groups") != 1
        or summary.get("Images") != 1
        or not isinstance(summary.get("Rows"), int)
        or cast(int, summary["Rows"]) < 1
        or not (start_time <= marker_time < diagnostic_read_time)
        or not (diagnostic_read_time < assignment_delete_started < ingested_at)
        or not (assignment_delete_started <= assignment_deleted < ingested_at)
        or not (assignment_delete_started <= job_deleted < ingested_at)
        or not (assignment_delete_started <= role_deleted < ingested_at)
    ):
        _fail("scanner-proof-retained-success-binding-invalid")

    graph_projection: dict[str, JsonValue] = {
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "deploymentCorrelationId": correlation_id,
        "deploymentOperations": cast(JsonValue, operation_projection),
        "deploymentTemplateHash": cast(str, top["templateHash"]),
        "nestedDeploymentTemplateHash": cast(str, nested["templateHash"]),
        "proofCanarySeed": cast(str, nested_parameters["proofCanarySeed"]),
        "temporaryRoleAssignmentIdSha256": _hash_text(assignment_id.casefold()),
    }
    graph_integrity = _canonical_hash(
        cast(JsonValue, graph_projection),
        "mobius.scanner-bridge.retained-proof-graph.v1",
    )
    revocation_projection: dict[str, JsonValue] = {
        "job": "absent",
        "jobDeletedAtUtc": _precise_utc(job_deleted),
        "roleAssignment": "absent",
        "roleAssignmentDeletedAtUtc": _precise_utc(assignment_deleted),
        "roleDefinition": "absent",
        "roleDefinitionDeletedAtUtc": _precise_utc(role_deleted),
    }
    revocation_integrity = _canonical_hash(
        cast(JsonValue, revocation_projection),
        "mobius.scanner-bridge.proof-residue.v1",
    )
    binding_body: dict[str, JsonValue] = {
        "activityHistoryIntegritySha256": activity_integrity,
        "adapterDiagnosticReadAtUtc": _precise_utc(diagnostic_read_time),
        "adapterFailureCode": "scanner-proof-marker-malformed",
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "authorizationReplayDecision": "deny",
        "canaryResidue": "absent-integrity-bound-runtime-marker",
        "contradictoryFailureMarkerCount": 0,
        "deploymentCorrelationId": correlation_id,
        "deploymentHistoryIntegritySha256": graph_integrity,
        "deploymentName": RETAINED_SUCCESS_DEPLOYMENT,
        "diagnosticIngestionAtUtc": _precise_utc(ingested_at),
        "executionName": RETAINED_SUCCESS_PROOF_EXECUTION,
        "executionStartUtc": _format_utc(start_time),
        "immutableImageDigest": RETAINED_SUCCESS_IMAGE,
        "markerEmittedAtUtc": _precise_utc(marker_time),
        "markerIntegritySha256": RETAINED_SUCCESS_MARKER_INTEGRITY,
        "markerLogSha256": _hash_text(log_output),
        "markerParserDecision": "accepted-production-parser",
        "proofExecutionCount": 1,
        "proofExecutionOrdinal": 4,
        "proofJobAbsent": True,
        "proofRoleAssignmentAbsent": True,
        "proofRoleDefinitionAbsent": True,
        "revocationIntegritySha256": revocation_integrity,
        "schemaVersion": RETAINED_SUCCESS_BINDING_VERSION,
        "terminalStatus": "Succeeded",
        "terminalStatusEvidence": "success-marker-preceded-adapter-terminal-log-read",
    }
    execution: dict[str, str | None] = {
        "endTime": None,
        "name": RETAINED_SUCCESS_PROOF_EXECUTION,
        "startTime": _format_utc(start_time),
        "status": "Succeeded",
    }
    return execution, marker, graph_integrity, revocation_integrity, binding_body


def _write_retained_success_binding(
    path: Path,
    *,
    body: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    artifact = {
        **body,
        "integritySha256": _canonical_hash(
            cast(JsonValue, dict(body)),
            RETAINED_SUCCESS_BINDING_DOMAIN,
        ),
    }
    resolved = _outside_repository(
        path,
        "scanner-proof-retained-success-evidence-inside-repository",
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-proof-retained-success-already-reconciled")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(cast(JsonValue, artifact)))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("scanner-proof-retained-success-write-failed")
    return artifact


def reconcile_retained_successful_scanner_proof(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    authorization_receipt_directory: Path,
    lifecycle_ledger_path: Path,
    finalization_evidence_path: Path,
    correction_repository_head: str,
    binding_output: Path,
    deployment_evidence_output: Path,
    now_utc: datetime | None = None,
) -> dict[str, JsonValue]:
    """Admit only the delayed, already-consumed successful Proof #4 execution."""

    now = (now_utc or lifecycle._utc_now()).astimezone(UTC).replace(microsecond=0)
    if (
        authorization.authorizationIntegritySha256
        != RETAINED_SUCCESS_AUTHORIZATION_INTEGRITY
        or authorization.repositoryHead != RETAINED_SUCCESS_SOURCE_HEAD
        or authorization.stage != PROOF_STAGE
        or authorization.proofExecutionOrdinal != 4
        or authorization.maximumProofExecutions != 1
        or authorization.apiImageDigest != RETAINED_SUCCESS_IMAGE
        or authorization.buildInputSha256 != RETAINED_SUCCESS_BUILD_INPUT
        or _SHA40.fullmatch(correction_repository_head) is None
        or correction_repository_head == authorization.repositoryHead
    ):
        _fail("scanner-proof-retained-authorization-invalid")
    lifecycle._verify_repository_state(correction_repository_head)
    receipt = _validate_consumed_proof_receipt(
        authorization=authorization,
        receipt_directory=authorization_receipt_directory,
    )
    publication = _validate_retained_publication_binding(
        authorization=authorization,
        ledger_path=lifecycle_ledger_path,
        finalization_evidence_path=finalization_evidence_path,
    )
    subscription_id = lifecycle._account_binding(now)
    if subscription_id != authorization.subscriptionId:
        _fail("scanner-proof-retained-subscription-mismatch")
    if not lifecycle._group_exists(subscription_id, TARGET_RESOURCE_GROUP):
        _fail("scanner-proof-retained-target-missing")
    cleanup_at = lifecycle._cleanup_deadline(now)
    contract = _validate_managed_binding(
        authorization, cleanup_deadline_utc=_format_utc(cleanup_at)
    )
    _, maximum_cost = lifecycle._verified_cost()
    if maximum_cost > authorization.maximumCostUsdCents:
        _fail("scanner-proof-retained-cost-ceiling-exceeded")
    cleanup_principal = lifecycle._verify_cleanup_control(subscription_id, cleanup_at)
    cleanup_role = cast(dict[str, JsonValue], contract["cleanupExecution"]).get(
        "cleanupContributorRoleDefinitionId"
    )
    if not isinstance(cleanup_role, str):
        _fail("scanner-proof-retained-cleanup-role-malformed")
    lifecycle._verify_cleanup_target_role(
        subscription_id, cleanup_principal, cleanup_role
    )
    foundation = _verify_foundation(
        authorization,
        require_proof_console_diagnostic=True,
    )
    history = _retained_success_readback(
        authorization,
        workspace_customer_id=foundation.workspace_customer_id,
    )
    resources_absent = all(
        (
            _resource_absent(cast(str, authorization.proofJobId), JOB_API_VERSION),
            _resource_absent(
                cast(str, authorization.proofRoleDefinitionId),
                ROLE_API_VERSION,
            ),
        )
    )
    top = history.get("deployment")
    if not isinstance(top, Mapping):
        _fail("scanner-proof-retained-history-malformed")
    outputs = _output_values(top.get("outputs"))
    assignment_id = _validate_deployment_outputs(authorization, outputs)
    if assignment_id is None or not _resource_absent(assignment_id, ROLE_API_VERSION):
        _fail("scanner-proof-retained-residue-present")
    execution, marker, graph_integrity, revocation_integrity, binding_body = (
        _validate_retained_success_history(
            authorization=authorization,
            readback=history,
            proof_resources_absent=resources_absent,
        )
    )
    binding = _write_retained_success_binding(
        binding_output,
        body={
            **binding_body,
            "authorizationReceiptIntegritySha256": cast(
                str,
                receipt["receiptIntegritySha256"],
            ),
            "buildInputSha256": RETAINED_SUCCESS_BUILD_INPUT,
            "correctionRepositoryHead": correction_repository_head,
            "finalizationEvidenceIntegritySha256": publication[
                "finalizationEvidenceIntegritySha256"
            ],
            "imageSourceCommit": RETAINED_SUCCESS_IMAGE_SOURCE,
            "ledgerIntegritySha256": publication["ledgerIntegritySha256"],
            "ociConfigDigest": RETAINED_SUCCESS_OCI_CONFIG,
        },
    )
    evidence = _build_live_evidence(
        authorization=authorization,
        readback=foundation,
        execution_name=RETAINED_SUCCESS_PROOF_EXECUTION,
        execution=execution,
        marker=marker,
        proof_graph_integrity=cast(str, binding["integritySha256"]),
        revocation_integrity=revocation_integrity,
        observed_at=now,
        control_plane_head=correction_repository_head,
    )
    if graph_integrity != binding_body["deploymentHistoryIntegritySha256"]:
        _fail("scanner-proof-retained-graph-integrity-drift")
    _write_evidence(deployment_evidence_output, evidence)
    return {
        "authorization-consumed-exactly-once": True,
        "authorization-replay-denied": True,
        "cleanup-executable-and-armed": True,
        "deployment-evidence-integrity-sha256": evidence.integrity_sha256(),
        "marker": "PROOF_4_RETAINED_SUCCESS_EVIDENCE_BOUND",
        "proof-execution-count": 1,
        "proof-execution-ordinal": 4,
        "proof-residue-absent": True,
        "retained-success-binding-integrity-sha256": binding["integritySha256"],
        "scanner-marker": "SCANNER_RESULT_BRIDGE_PROVED",
        "status": "scanner-result-bridge-proved-from-retained-success",
    }


def _reprovision_foundation_scope(
    authorization: CleanupControlReprovisionAuthorization,
) -> _ReprovisionFoundationScope:
    if (
        authorization.foundationStage != FOUNDATION_STAGE
        or authorization.imageRestorationAuthorized is not False
        or authorization.scannerProofAuthorized is not False
        or authorization.maximumScannerProofExecutions != 0
    ):
        _fail("scanner-foundation-reprovision-authority-expanded")
    return _ReprovisionFoundationScope(
        stage=FOUNDATION_STAGE,
        subscriptionId=authorization.subscriptionId,
        targetResourceGroupId=authorization.targetResourceGroupId,
        storageAccountId=authorization.storageAccountId,
        logAnalyticsWorkspaceId=authorization.logAnalyticsWorkspaceId,
        workerIdentityId=authorization.workerIdentityId,
        privateLinkScopeId=authorization.privateLinkScopeId,
        monitorPrivateEndpointId=authorization.monitorPrivateEndpointId,
        proofJobId=None,
        proofRoleDefinitionId=None,
        apiImageDigest=None,
    )


def _monitor_private_endpoint_precreation_count(
    authorization: _FoundationScope,
) -> int:
    value: JsonValue | None = None
    for attempt in range(len(REPROVISION_FOUNDATION_READ_RETRY_DELAYS) + 1):
        try:
            value = _rest_collection(
                (
                    f"{authorization.targetResourceGroupId}/providers/"
                    "Microsoft.Network/privateEndpoints"
                ),
                PRIVATE_ENDPOINT_API_VERSION,
                "value[].{id:id,name:name}",
            )
            break
        except lifecycle.AzureCommandError:
            if attempt == len(REPROVISION_FOUNDATION_READ_RETRY_DELAYS):
                raise
            time.sleep(REPROVISION_FOUNDATION_READ_RETRY_DELAYS[attempt])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        _fail("scanner-foundation-reprovision-endpoint-inventory-malformed")
    matching: list[dict[str, JsonValue]] = []
    for raw in value:
        row = cast(dict[str, JsonValue], raw)
        exact_id = _same_resource_id(
            row.get("id"), authorization.monitorPrivateEndpointId
        )
        exact_name = row.get("name") == MONITOR_PRIVATE_ENDPOINT
        if exact_id != exact_name:
            _fail("scanner-foundation-reprovision-endpoint-identity-drift")
        if exact_id:
            matching.append(row)
    if len(matching) > 1:
        _fail("scanner-foundation-reprovision-endpoint-duplicate")
    return len(matching)


def _foundation_deployment_state(
    *,
    subscription_id: str,
    deployment_binding: Mapping[str, JsonValue],
) -> str | None:
    deployment_name = lifecycle._deployment_name(FOUNDATION_STAGE, deployment_binding)
    try:
        value = lifecycle._run(
            (
                "az",
                "deployment",
                "sub",
                "show",
                "--name",
                deployment_name,
                "--subscription",
                subscription_id,
                "--query",
                "{state:properties.provisioningState}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
    except lifecycle.AzureCommandError as exc:
        if _not_found(exc):
            return None
        raise
    row = _json_object(
        value, "scanner-foundation-reprovision-deployment-state-malformed"
    )
    if set(row) != {"state"} or row.get("state") not in {
        "Canceled",
        "Failed",
        "Running",
        "Succeeded",
    }:
        _fail("scanner-foundation-reprovision-deployment-state-malformed")
    return cast(str, row["state"])


def _wait_for_foundation_deployment_terminal(
    *,
    subscription_id: str,
    deployment_binding: Mapping[str, JsonValue],
) -> str | None:
    deadline = time.monotonic() + REPROVISION_FOUNDATION_DEPLOYMENT_SECONDS
    while True:
        state = _foundation_deployment_state(
            subscription_id=subscription_id,
            deployment_binding=deployment_binding,
        )
        if state != "Running":
            return state
        if time.monotonic() >= deadline:
            _fail("scanner-foundation-reprovision-deployment-terminal-state-unproved")
        time.sleep(REPROVISION_FOUNDATION_DEPLOYMENT_POLL_SECONDS)


def reconcile_reprovision_scanner_foundation(
    *,
    authorization: CleanupControlReprovisionAuthorization,
    deployment_binding: dict[str, JsonValue],
    cleanup_at: datetime,
    expected_cost: int,
    maximum_cost: int,
) -> dict[str, JsonValue]:
    """Complete the existing foundation under the consumed Generation-4 grant."""

    scope = _reprovision_foundation_scope(authorization)
    if (
        set(deployment_binding)
        != {
            "authorizationId",
            "ledgerIntegritySha256",
            "managedBindingIntegritySha256",
            "repositoryHead",
        }
        or deployment_binding.get("ledgerIntegritySha256")
        != authorization.authorizationIntegritySha256
        or deployment_binding.get("repositoryHead") != authorization.repositoryHead
        or not isinstance(deployment_binding.get("authorizationId"), str)
        or not isinstance(deployment_binding.get("managedBindingIntegritySha256"), str)
        or _SHA256.fullmatch(
            cast(str, deployment_binding["managedBindingIntegritySha256"])
        )
        is None
        or _format_utc(cleanup_at) != authorization.deadlineUtc
        or expected_cost < 0
        or expected_cost > maximum_cost
        or maximum_cost > authorization.costCeilingUsdCents
    ):
        _fail("scanner-foundation-reprovision-binding-invalid")

    _verify_provider_api_versions(authorization.subscriptionId)
    _verify_network_capacity(authorization.subscriptionId)
    precreation_count = _monitor_private_endpoint_precreation_count(scope)
    recovery: dict[str, JsonValue] | None = None
    deployment_attempts = 0
    with tempfile.TemporaryDirectory(
        prefix="mobius77-reprovision-foundation-"
    ) as directory:
        template = Path(directory) / "main.json"
        lifecycle._compile_template(template)
        while deployment_attempts < REPROVISION_FOUNDATION_MAXIMUM_DEPLOYMENTS:
            if _monitor_private_endpoint_precreation_count(scope) == 1:
                recovery = _repair_exact_monitor_private_endpoint(scope)
            deployment_attempts += 1
            azure_error_code: str | None = None
            try:
                lifecycle._deploy_stage(
                    template_path=template,
                    subscription_id=authorization.subscriptionId,
                    ledger=deployment_binding,
                    stage=FOUNDATION_STAGE,
                    cleanup_at=cleanup_at,
                    expected_cost=expected_cost,
                    maximum_cost=maximum_cost,
                )
            except lifecycle.AzureCommandError as exc:
                azure_error_code = exc.sanitized_azure_error_code
            except lifecycle.LifecycleError as exc:
                if str(exc) != "lifecycle-process-timed-out":
                    raise
                azure_error_code = "lifecycle-process-timed-out"
            if azure_error_code is None:
                break

            deployment_state = _foundation_deployment_state(
                subscription_id=authorization.subscriptionId,
                deployment_binding=deployment_binding,
            )
            if deployment_state == "Running":
                deployment_state = _wait_for_foundation_deployment_terminal(
                    subscription_id=authorization.subscriptionId,
                    deployment_binding=deployment_binding,
                )
            if deployment_state == "Succeeded":
                break

            endpoint_count = _monitor_private_endpoint_precreation_count(scope)
            reconciled_partial_endpoint = endpoint_count == 1
            if reconciled_partial_endpoint:
                recovery = _repair_exact_monitor_private_endpoint(scope)
            retryable_pre_mutation = (
                endpoint_count == 0
                and azure_error_code in REPROVISION_FOUNDATION_TRANSIENT_AZURE_CODES
            )
            if (
                deployment_attempts >= REPROVISION_FOUNDATION_MAXIMUM_DEPLOYMENTS
                or not (reconciled_partial_endpoint or retryable_pre_mutation)
            ):
                _fail(f"scanner-foundation-reprovision-azure-{azure_error_code}")
            time.sleep(float(deployment_attempts * 2))
        else:
            _fail("scanner-foundation-reprovision-deployment-attempts-exhausted")

    outputs = _read_deployment_outputs(
        subscription_id=authorization.subscriptionId,
        stage=FOUNDATION_STAGE,
        binding=deployment_binding,
    )
    if _validate_deployment_outputs(scope, outputs) is not None:
        _fail("scanner-foundation-reprovision-proof-authority-reachable")
    endpoint_state = _exact_monitor_private_endpoint_recovery_state(scope)
    readback = _verify_foundation(scope, require_proof_console_diagnostic=True)
    private_path_integrity = _verify_monitor_private_tls_path(
        readback.workspace_customer_id
    )
    final_expected_cost, final_maximum_cost = lifecycle._verified_cost()
    if (final_expected_cost, final_maximum_cost) != (expected_cost, maximum_cost):
        _fail("scanner-foundation-reprovision-cost-envelope-drift")
    return {
        "deployment-attempt-count": deployment_attempts,
        "diagnostic-integrity-sha256": readback.diagnostic_proof_integrity,
        "expected-cost-usd-cents": final_expected_cost,
        "foundation-integrity-sha256": readback.inventory_integrity,
        "maximum-cost-usd-cents": final_maximum_cost,
        "monitor-private-endpoint-precreation-count": precreation_count,
        "monitor-private-endpoint-recovery": recovery,
        "monitor-private-endpoint-state": endpoint_state,
        "networking-integrity-sha256": (readback.private_path_control_plane_integrity),
        "private-tls-integrity-sha256": private_path_integrity,
        "rbac-integrity-sha256": readback.rbac_proof_integrity,
        "scanner-proof-execution-count": 0,
        "status": "staging-foundation-authoritative",
        "tag-writer-boundary-integrity-sha256": (readback.tag_write_denial_integrity),
    }


class ProductionScannerBridgeRecoveryAdapter:
    """Consume one stage grant through the existing production lifecycle primitives."""

    def __init__(self, *, clock: Callable[[], datetime] = lifecycle._utc_now) -> None:
        self._clock = clock

    def execute(
        self,
        *,
        authorization: ScannerBridgeRecoveryAuthorization,
        receipt_directory: Path,
        expected_repository_head: str,
        evidence_output: Path | None = None,
    ) -> dict[str, JsonValue]:
        now = self._clock().astimezone(UTC).replace(microsecond=0)
        validate_scanner_bridge_recovery_authorization(
            authorization,
            expected_repository_head=expected_repository_head,
            now_utc=now,
        )
        if (authorization.stage == PROOF_STAGE) != (evidence_output is not None):
            _fail("scanner-bridge-evidence-output-contract-invalid")
        lifecycle._verify_repository_state(expected_repository_head)
        subscription_id = lifecycle._account_binding(now)
        if subscription_id != authorization.subscriptionId:
            _fail("scanner-bridge-subscription-mismatch")
        if not lifecycle._group_exists(subscription_id, TARGET_RESOURCE_GROUP):
            _fail("scanner-bridge-target-resource-group-missing")
        contract = _validate_managed_binding(authorization)
        expected_cost, maximum_cost = lifecycle._verified_cost()
        if maximum_cost > authorization.maximumCostUsdCents:
            _fail("scanner-bridge-cost-ceiling-exceeded")
        _verify_provider_api_versions(subscription_id)
        _verify_network_capacity(subscription_id)
        cleanup_at = _parse_utc(
            authorization.cleanupDeadlineUtc, "scanner-bridge-cleanup-deadline-invalid"
        )
        cleanup_principal = lifecycle._verify_cleanup_control(
            subscription_id, cleanup_at
        )
        cleanup_role = cast(dict[str, JsonValue], contract["cleanupExecution"]).get(
            "cleanupContributorRoleDefinitionId"
        )
        if not isinstance(cleanup_role, str):
            _fail("scanner-bridge-cleanup-role-contract-malformed")
        lifecycle._verify_cleanup_target_role(
            subscription_id, cleanup_principal, cleanup_role
        )

        if authorization.stage == PRIVATE_ENDPOINT_RECOVERY_STAGE:
            _exact_monitor_private_endpoint_recovery_state(authorization)
            _claim_authorization(
                authorization=authorization,
                receipt_directory=receipt_directory,
                now_utc=now,
            )
            recovery = _repair_exact_monitor_private_endpoint(authorization)
            readback = _verify_foundation(
                authorization,
                require_proof_console_diagnostic=True,
            )
            live_path_integrity = _verify_monitor_private_tls_path(
                readback.workspace_customer_id
            )
            cleanup_principal = lifecycle._verify_cleanup_control(
                subscription_id, cleanup_at
            )
            lifecycle._verify_cleanup_target_role(
                subscription_id, cleanup_principal, cleanup_role
            )
            final_expected_cost, final_maximum_cost = lifecycle._verified_cost()
            if (final_expected_cost, final_maximum_cost) != (
                expected_cost,
                maximum_cost,
            ):
                _fail("scanner-private-endpoint-recovery-cost-envelope-drift")
            return {
                "authorization-consumed": True,
                "authorization-integrity-sha256": (
                    authorization.authorizationIntegritySha256
                ),
                "cleanup-executable-and-armed": True,
                "cost-envelope-unchanged": True,
                "dns-resolution-private": True,
                "foundation-integrity-sha256": readback.inventory_integrity,
                "marker": "STAGING_FOUNDATION_AUTHORITATIVE",
                "no-duplicate-private-endpoint": True,
                "no-orphaned-private-endpoint-resources": True,
                "private-endpoint-id": authorization.monitorPrivateEndpointId,
                "private-path-integrity-sha256": live_path_integrity,
                "recovery": recovery,
                "scanner-proof-execution-count": 0,
                "status": "scanner-foundation-private-endpoint-recovered",
                "tls-path-proved": True,
            }

        binding = _deployment_binding(authorization, contract)
        if authorization.stage == PROOF_STAGE:
            _verify_foundation(
                authorization,
                require_proof_console_diagnostic=False,
            )
        _claim_authorization(
            authorization=authorization,
            receipt_directory=receipt_directory,
            now_utc=now,
        )
        with tempfile.TemporaryDirectory(
            prefix="mobius77-scanner-bridge-"
        ) as directory:
            template = Path(directory) / "main.json"
            lifecycle._compile_template(template)
            # A lost or failed response is reconciled from ARM before any retry.
            with suppress(lifecycle.AzureCommandError):
                lifecycle._deploy_stage(
                    template_path=template,
                    subscription_id=subscription_id,
                    ledger=binding,
                    stage=authorization.stage,
                    cleanup_at=cleanup_at,
                    expected_cost=expected_cost,
                    maximum_cost=maximum_cost,
                    runtime_config=(
                        {"apiImageDigest": cast(str, authorization.apiImageDigest)}
                        if authorization.stage == PROOF_STAGE
                        else None
                    ),
                )
        outputs = _read_deployment_outputs(
            subscription_id=subscription_id,
            stage=authorization.stage,
            binding=binding,
        )
        assignment_id = _validate_deployment_outputs(authorization, outputs)
        readback = _verify_foundation(
            authorization,
            require_proof_console_diagnostic=True,
        )
        if authorization.stage == FOUNDATION_STAGE:
            return {
                "authorization-consumed": True,
                "authorization-integrity-sha256": (
                    authorization.authorizationIntegritySha256
                ),
                "cleanup-executable-and-armed": True,
                "foundation-integrity-sha256": readback.inventory_integrity,
                "public-access-enabled": False,
                "scanner-bridge-foundation-deployed": True,
                "status": "scanner-bridge-foundation-reconciled",
                "tag-write-authorized-for-worker": False,
            }

        if assignment_id is None or evidence_output is None:
            _fail("scanner-proof-authorization-incomplete")
        try:
            try:
                proof_graph = _verify_proof_graph(
                    authorization,
                    assignment_id=assignment_id,
                    worker_principal_id=readback.worker_principal_id,
                    worker_client_id=readback.worker_client_id,
                    workspace_customer_id=readback.workspace_customer_id,
                )
                proof_graph = _wait_for_proof_rbac_propagation(
                    authorization,
                    assignment_id=assignment_id,
                    worker_principal_id=readback.worker_principal_id,
                    worker_client_id=readback.worker_client_id,
                    workspace_customer_id=readback.workspace_customer_id,
                )
            except lifecycle.AzureCommandError as exc:
                _fail(f"scanner-proof-graph-azure-{exc.sanitized_azure_error_code}")
            try:
                execution_name = _start_one_execution(authorization)
            except lifecycle.AzureCommandError as exc:
                _fail(f"scanner-proof-start-azure-{exc.sanitized_azure_error_code}")
            try:
                execution = _wait_for_execution(authorization, execution_name)
            except lifecycle.AzureCommandError as exc:
                _fail(f"scanner-proof-wait-azure-{exc.sanitized_azure_error_code}")
            if execution["status"] != "Succeeded":
                try:
                    terminal_log_output = _proof_log_output(
                        authorization, execution_name
                    )
                    failure_marker = _proof_failure_marker(
                        authorization,
                        execution_name,
                        log_output=terminal_log_output,
                    )
                except lifecycle.AzureCommandError as exc:
                    _fail(
                        f"scanner-proof-failure-marker-azure-{exc.sanitized_azure_error_code}"
                    )
                failure_code = cast(str, failure_marker["failureCode"])
                try:
                    blob_tag_observation = _proof_blob_tag_observation(
                        authorization,
                        execution_name,
                        failure_code=failure_code,
                        log_output=terminal_log_output,
                    )
                except lifecycle.AzureCommandError as exc:
                    _fail(
                        f"scanner-proof-blob-tag-observation-azure-{exc.sanitized_azure_error_code}"
                    )
                _write_failure_evidence(
                    evidence_output,
                    authorization=authorization,
                    execution_name=execution_name,
                    execution=execution,
                    marker=failure_marker,
                    blob_tag_observation=blob_tag_observation,
                    observed_at=self._clock().astimezone(UTC).replace(microsecond=0),
                )
                _fail(failure_code)
            try:
                marker = _wait_for_proof_marker(authorization, execution_name)
            except lifecycle.AzureCommandError as exc:
                _fail(f"scanner-proof-marker-azure-{exc.sanitized_azure_error_code}")
        finally:
            try:
                revocation = _remove_proof_residue(authorization, assignment_id)
            except lifecycle.AzureCommandError as exc:
                _fail(f"scanner-proof-cleanup-azure-{exc.sanitized_azure_error_code}")
        final_readback = _verify_foundation(
            authorization,
            require_proof_console_diagnostic=True,
        )
        observed = self._clock().astimezone(UTC).replace(microsecond=0)
        evidence = _build_live_evidence(
            authorization=authorization,
            readback=final_readback,
            execution_name=execution_name,
            execution=execution,
            marker=marker,
            proof_graph_integrity=proof_graph,
            revocation_integrity=revocation,
            observed_at=observed,
        )
        _write_evidence(evidence_output, evidence)
        return {
            "authorization-consumed": True,
            "authorization-integrity-sha256": (
                authorization.authorizationIntegritySha256
            ),
            "cleanup-executable-and-armed": True,
            "evidence-integrity-sha256": evidence.integrity_sha256(),
            "immutable-image-digest": authorization.apiImageDigest,
            "marker": "SCANNER_RESULT_BRIDGE_PROVED",
            "proof-execution-count": 1,
            "proof-execution-ordinal": authorization.proofExecutionOrdinal,
            "proof-residue-absent": True,
            "provider-system-topic-preserved": True,
            "public-access-enabled": False,
            "status": "scanner-result-bridge-proved",
            "tag-write-authorized-for-worker": False,
        }


__all__ = [
    "ProductionScannerBridgeRecoveryAdapter",
    "ScannerBridgeRecoveryExecutionError",
    "reconcile_retained_scanner_proof",
    "reconcile_retained_successful_scanner_proof",
]
