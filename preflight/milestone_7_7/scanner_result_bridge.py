"""Fail-closed contract for the Milestone 7.7 private-pull scanner bridge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, cast

BridgeState = Literal[
    "CONTRACT_UNDEFINED",
    "PROVIDER_UNAVAILABLE",
    "RESOURCES_UNDEPLOYED",
    "IDENTITY_UNPROVED",
    "RBAC_UNPROVED",
    "PRIVATE_PATH_UNPROVED",
    "PRODUCER_UNPROVED",
    "TRANSPORT_UNPROVED",
    "CONSUMER_UNPROVED",
    "SCHEMA_UNPROVED",
    "CORRELATION_UNPROVED",
    "REVOCATION_UNPROVED",
    "STALE_EVIDENCE",
    "RESOLVED",
]

PROVIDER: Final = "microsoft-defender-for-storage-malware-scanning"
TRANSPORT: Final = "private-blob-tags-plus-ampls-log-analytics-pull"
SCHEMA_VERSION: Final = "mobius.scanner-result-bridge.v2"
MAXIMUM_EVIDENCE_AGE: Final = timedelta(hours=24)
DEPLOYMENT_EVIDENCE_VERSION: Final = (
    "mobius.scanner-result-bridge.deployment-evidence.v2"
)
DEPLOYMENT_EVIDENCE_DOMAIN: Final = (
    b"mobius.scanner-result-bridge.deployment-evidence.v2\0"
)
_REQUIRED_PROOFS: Final = (
    "provider",
    "resources",
    "identity",
    "rbac",
    "privatePath",
    "producer",
    "transport",
    "consumer",
    "schema",
    "correlation",
    "revocation",
)


class ScannerResultBridgeError(ValueError):
    """A redacted, deterministic bridge-contract failure."""


@dataclass(frozen=True, slots=True)
class ScannerResultBridgeEvidence:
    """Sanitized proof that two private authoritative sources agreed exactly."""

    observed_at_utc: str
    provider: str
    transport: str
    schema_version: str
    proofs: dict[str, bool]
    correlation_id_sha256: str
    blob_tag_evidence_sha256: str
    log_analytics_evidence_sha256: str
    object_version_or_etag_sha256: str
    storage_resource_sha256: str
    completion_time_sha256: str
    decision: Literal["clean", "rejected", "unknown"]

    def canonical(self) -> dict[str, object]:
        return asdict(self)

    def integrity_sha256(self) -> str:
        canonical = json.dumps(
            self.canonical(), separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(
            b"mobius.scanner-result-bridge.evidence.v2\0" + canonical
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ScannerResultBridgeDeploymentEvidence:
    """Operation-bound, sanitized live proof for later lifecycle admission."""

    control_plane_head: str
    environment_sha256: str
    operation_id_sha256: str
    observed_at_utc: str
    legacy_evidence: ScannerResultBridgeEvidence
    provider_resource_id_sha256: str
    provider_api_version: str
    provider_enabled: bool
    provider_capability_proof_integrity: str
    diagnostic_setting_resource_id_sha256: str
    storage_resource_id_sha256: str
    quarantine_container: str
    blob_identity_sha256: str
    content_sha256: str
    scan_request_id_sha256: str
    producer_proof_integrity: str
    blob_tag_result_sha256: str
    log_analytics_workspace_id_sha256: str
    log_analytics_table: str
    log_query_sha256: str
    dual_source_proof_integrity: str
    consumer_identity_sha256: str
    consumer_entry_point: str
    consumer_proof_integrity: str
    blob_reader_role_definition_sha256: str
    log_reader_role_definition_sha256: str
    blob_reader_scope_sha256: str
    log_reader_scope_sha256: str
    worker_tag_write_denied: bool
    tag_write_denial_proof_integrity: str
    assignment_proof_integrity: str
    ampls_resource_id_sha256: str
    private_endpoint_resource_id_sha256: str
    private_dns_zone_set_sha256: str
    private_address_sha256: str
    tls_hostname_sha256: str
    tls_version: str
    private_path_proof_integrity: str
    proof_job_resource_id_sha256: str
    proof_execution_id_sha256: str
    clean_decision_proof_integrity: str
    malicious_decision_proof_integrity: str
    provider_owned_system_topic_preserved: bool
    revocation_proof_integrity: str
    cleanup_inventory_integrity: str
    unresolved_reasons: tuple[str, ...]

    def canonical(self) -> dict[str, object]:
        value = asdict(self)
        value["unresolved_reasons"] = list(self.unresolved_reasons)
        return value

    def integrity_sha256(self) -> str:
        canonical = json.dumps(
            self.canonical(), separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(DEPLOYMENT_EVIDENCE_DOMAIN + canonical).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScannerResultBridgeError("bridge evidence timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ScannerResultBridgeError("bridge evidence timestamp lacks UTC offset")
    return parsed.astimezone(UTC)


def _sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def resolve_bridge(
    evidence: ScannerResultBridgeEvidence | None,
    *,
    now: datetime,
) -> tuple[BridgeState, str | None]:
    """Return the first fail-closed state and optional sanitized integrity hash."""

    if evidence is None:
        return "CONTRACT_UNDEFINED", None
    if evidence.provider != PROVIDER:
        return "PROVIDER_UNAVAILABLE", None
    if evidence.transport != TRANSPORT:
        return "TRANSPORT_UNPROVED", None
    if evidence.schema_version != SCHEMA_VERSION:
        return "SCHEMA_UNPROVED", None
    for proof, state in (
        ("resources", "RESOURCES_UNDEPLOYED"),
        ("identity", "IDENTITY_UNPROVED"),
        ("rbac", "RBAC_UNPROVED"),
        ("privatePath", "PRIVATE_PATH_UNPROVED"),
        ("producer", "PRODUCER_UNPROVED"),
        ("transport", "TRANSPORT_UNPROVED"),
        ("consumer", "CONSUMER_UNPROVED"),
        ("schema", "SCHEMA_UNPROVED"),
        ("correlation", "CORRELATION_UNPROVED"),
        ("revocation", "REVOCATION_UNPROVED"),
    ):
        if evidence.proofs.get(proof) is not True:
            return state, None  # type: ignore[return-value]
    if evidence.proofs.get("provider") is not True:
        return "PROVIDER_UNAVAILABLE", None
    if set(evidence.proofs) != set(_REQUIRED_PROOFS):
        return "CONTRACT_UNDEFINED", None
    if not all(
        _sha256(value)
        for value in (
            evidence.correlation_id_sha256,
            evidence.blob_tag_evidence_sha256,
            evidence.log_analytics_evidence_sha256,
            evidence.object_version_or_etag_sha256,
            evidence.storage_resource_sha256,
            evidence.completion_time_sha256,
        )
    ):
        return "CORRELATION_UNPROVED", None
    observed = _timestamp(evidence.observed_at_utc)
    if (
        now.tzinfo is None
        or now.astimezone(UTC) - observed > MAXIMUM_EVIDENCE_AGE
        or observed > now.astimezone(UTC) + timedelta(minutes=5)
    ):
        return "STALE_EVIDENCE", None
    if evidence.decision not in {"clean", "rejected"}:
        return "CONSUMER_UNPROVED", None
    return "RESOLVED", evidence.integrity_sha256()


def build_scanner_result_bridge_deployment_evidence(
    evidence: ScannerResultBridgeDeploymentEvidence,
    *,
    now: datetime,
) -> ScannerResultBridgeDeploymentEvidence:
    """Validate a complete typed proof envelope without contacting Azure."""

    if len(evidence.control_plane_head) != 40 or not all(
        character in "0123456789abcdef" for character in evidence.control_plane_head
    ):
        raise ScannerResultBridgeError("bridge control-plane head is invalid")
    if evidence.provider_enabled is not True:
        raise ScannerResultBridgeError("bridge provider is unproved")
    if evidence.provider_api_version != "2025-06-01":
        raise ScannerResultBridgeError("bridge provider API version is unproved")
    if evidence.quarantine_container != "quarantine":
        raise ScannerResultBridgeError("bridge producer is unproved")
    if evidence.log_analytics_table != "StorageMalwareScanningResults":
        raise ScannerResultBridgeError("bridge dual-source transport is unproved")
    if evidence.consumer_entry_point != "scripts.worker.DocumentWorker":
        raise ScannerResultBridgeError("bridge consumer is unproved")
    if evidence.worker_tag_write_denied is not True:
        raise ScannerResultBridgeError("bridge least privilege is unproved")
    if evidence.provider_owned_system_topic_preserved is not True:
        raise ScannerResultBridgeError(
            "bridge provider resource preservation is unproved"
        )
    if evidence.tls_version not in {"TLS1_2", "TLS1_3"}:
        raise ScannerResultBridgeError("bridge private path is unproved")
    if evidence.unresolved_reasons:
        raise ScannerResultBridgeError("bridge evidence has unresolved reasons")
    ignored = {
        "control_plane_head",
        "observed_at_utc",
        "legacy_evidence",
        "provider_api_version",
        "provider_enabled",
        "quarantine_container",
        "log_analytics_table",
        "consumer_entry_point",
        "worker_tag_write_denied",
        "tls_version",
        "provider_owned_system_topic_preserved",
        "unresolved_reasons",
    }
    sha_values = (
        value
        for field in fields(evidence)
        if field.name not in ignored
        for value in (getattr(evidence, field.name),)
    )
    if not all(isinstance(value, str) and _sha256(value) for value in sha_values):
        raise ScannerResultBridgeError("bridge evidence integrity is invalid")
    state, _ = resolve_bridge(evidence.legacy_evidence, now=now)
    if state != "RESOLVED":
        raise ScannerResultBridgeError(f"bridge resolver is {state.casefold()}")
    observed = _timestamp(evidence.observed_at_utc)
    if now.tzinfo is None or now.astimezone(UTC) - observed > MAXIMUM_EVIDENCE_AGE:
        raise ScannerResultBridgeError("bridge deployment evidence is stale")
    if observed > now.astimezone(UTC) + timedelta(minutes=5):
        raise ScannerResultBridgeError("bridge deployment evidence is future")
    return evidence


def deployment_evidence_from_mapping(
    value: Mapping[str, object],
    *,
    now: datetime,
) -> ScannerResultBridgeDeploymentEvidence:
    """Decode a canonical external evidence artifact without retaining raw IDs."""

    expected = {field.name for field in fields(ScannerResultBridgeDeploymentEvidence)}
    if set(value) != expected:
        raise ScannerResultBridgeError("bridge deployment evidence fields are invalid")
    legacy_raw = value.get("legacy_evidence")
    reasons = value.get("unresolved_reasons")
    if (
        not isinstance(legacy_raw, Mapping)
        or not isinstance(reasons, (list, tuple))
        or not all(isinstance(reason, str) for reason in reasons)
    ):
        raise ScannerResultBridgeError("bridge deployment evidence is malformed")
    legacy_expected = {field.name for field in fields(ScannerResultBridgeEvidence)}
    if set(legacy_raw) != legacy_expected:
        raise ScannerResultBridgeError("bridge legacy evidence fields are invalid")
    proofs = legacy_raw.get("proofs")
    if not isinstance(proofs, Mapping) or not all(
        isinstance(key, str) and isinstance(enabled, bool)
        for key, enabled in proofs.items()
    ):
        raise ScannerResultBridgeError("bridge legacy evidence is malformed")
    try:
        legacy = ScannerResultBridgeEvidence(**cast(Any, dict(legacy_raw)))
        decoded = ScannerResultBridgeDeploymentEvidence(
            **cast(
                Any,
                {
                    **dict(value),
                    "legacy_evidence": legacy,
                    "unresolved_reasons": tuple(reasons),
                },
            )
        )
        return build_scanner_result_bridge_deployment_evidence(decoded, now=now)
    except (TypeError, KeyError) as exc:
        raise ScannerResultBridgeError(
            "bridge deployment evidence is malformed"
        ) from exc


__all__ = [
    "DEPLOYMENT_EVIDENCE_VERSION",
    "MAXIMUM_EVIDENCE_AGE",
    "PROVIDER",
    "SCHEMA_VERSION",
    "TRANSPORT",
    "BridgeState",
    "ScannerResultBridgeDeploymentEvidence",
    "ScannerResultBridgeError",
    "ScannerResultBridgeEvidence",
    "build_scanner_result_bridge_deployment_evidence",
    "deployment_evidence_from_mapping",
    "resolve_bridge",
]
