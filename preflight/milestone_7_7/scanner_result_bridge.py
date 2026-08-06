"""Fail-closed local contract for the Milestone 7.7 scanner-result bridge.

This module deliberately has no Azure client.  It turns sanitized, immutable
bridge evidence into a deterministic admission decision; live provider proof is
still required before the result can be ``RESOLVED`` in a deployment ledger.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

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
TRANSPORT: Final = "event-grid-system-topic-to-private-storage-queue"
SCHEMA_VERSION: Final = "mobius.scanner-result-bridge.v1"
MAXIMUM_EVIDENCE_AGE: Final = timedelta(hours=24)
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
DEPLOYMENT_EVIDENCE_VERSION: Final = "mobius.scanner-result-bridge.deployment-evidence.v1"
DEPLOYMENT_EVIDENCE_DOMAIN: Final = b"mobius.scanner-result-bridge.deployment-evidence.v1\0"


class ScannerResultBridgeError(ValueError):
    """A redacted, deterministic bridge-contract failure."""


@dataclass(frozen=True, slots=True)
class ScannerResultBridgeEvidence:
    """Sanitized evidence only; identifiers are stable aliases or SHA-256 values."""

    observed_at_utc: str
    provider: str
    transport: str
    schema_version: str
    proofs: dict[str, bool]
    correlation_id_sha256: str
    event_id_sha256: str
    provider_result_id_sha256: str
    object_version_or_etag_sha256: str
    storage_resource_sha256: str
    delivery_attempt_sha256: str
    decision: Literal["clean", "rejected", "unknown"]

    def canonical(self) -> dict[str, object]:
        return asdict(self)

    def integrity_sha256(self) -> str:
        canonical = json.dumps(self.canonical(), separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        return hashlib.sha256(b"mobius.scanner-result-bridge.evidence.v1\0" + canonical).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScannerResultBridgeError("bridge evidence timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ScannerResultBridgeError("bridge evidence timestamp lacks UTC offset")
    return parsed.astimezone(UTC)


def _sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


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
            return state, None
    if evidence.proofs.get("provider") is not True:
        return "PROVIDER_UNAVAILABLE", None
    if set(evidence.proofs) != set(_REQUIRED_PROOFS):
        return "CONTRACT_UNDEFINED", None
    if not all(
        _sha256(value)
        for value in (
            evidence.correlation_id_sha256,
            evidence.event_id_sha256,
            evidence.provider_result_id_sha256,
            evidence.object_version_or_etag_sha256,
            evidence.storage_resource_sha256,
            evidence.delivery_attempt_sha256,
        )
    ):
        return "CORRELATION_UNPROVED", None
    observed = _timestamp(evidence.observed_at_utc)
    if now.tzinfo is None or now.astimezone(UTC) - observed > MAXIMUM_EVIDENCE_AGE:
        return "STALE_EVIDENCE", None
    if evidence.decision not in {"clean", "rejected"}:
        return "CONSUMER_UNPROVED", None
    return "RESOLVED", evidence.integrity_sha256()


@dataclass(frozen=True, slots=True)
class ScannerResultBridgeDeploymentEvidence:
    """Operation-bound, sanitized bridge evidence for post-secret admission.

    Resource identifiers are SHA-256 aliases.  Live collection may compare raw
    IDs in memory, but neither the executor nor its persisted evidence retains
    them.  The legacy resolver evidence remains a component of this envelope;
    it is never replaced by a caller-supplied resolution boolean.
    """

    control_plane_head: str
    environment_sha256: str
    operation_id_sha256: str
    observed_at_utc: str
    legacy_evidence: ScannerResultBridgeEvidence
    provider_resource_id_sha256: str
    provider_api_version: str
    provider_enabled: bool
    provider_capability_proof_integrity: str
    storage_resource_id_sha256: str
    quarantine_container: str
    blob_identity_sha256: str
    content_sha256: str
    scan_request_id_sha256: str
    producer_proof_integrity: str
    system_topic_resource_id_sha256: str
    event_subscription_resource_id_sha256: str
    event_type: str
    event_schema_version: str
    filter_integrity: str
    private_queue_resource_id_sha256: str
    dead_letter_queue_resource_id_sha256: str
    transport_proof_integrity: str
    consumer_identity_sha256: str
    queue_adapter_identity_sha256: str
    malware_scan_receipt_id_sha256: str
    idempotency_key_sha256: str
    consumer_proof_integrity: str
    sender_identity_sha256: str
    processor_identity_sha256: str
    sender_role_definition_sha256: str
    processor_role_definition_sha256: str
    sender_scope_sha256: str
    processor_scope_sha256: str
    assignment_proof_integrity: str
    revocation_proof_integrity: str
    private_endpoint_resource_id_sha256: str
    private_dns_resource_id_sha256: str
    private_address_sha256: str
    tls_hostname_sha256: str
    tls_version: str
    private_path_proof_integrity: str
    cleanup_inventory_integrity: str
    unresolved_reasons: tuple[str, ...]

    def canonical(self) -> dict[str, object]:
        value = asdict(self)
        value["unresolved_reasons"] = list(self.unresolved_reasons)
        return value

    def integrity_sha256(self) -> str:
        canonical = json.dumps(self.canonical(), separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        return hashlib.sha256(DEPLOYMENT_EVIDENCE_DOMAIN + canonical).hexdigest()


def build_scanner_result_bridge_deployment_evidence(
    evidence: ScannerResultBridgeDeploymentEvidence, *, now: datetime
) -> ScannerResultBridgeDeploymentEvidence:
    """Validate a complete typed proof envelope and return it canonically.

    This local builder does not contact Azure or make deployment decisions. It
    preserves every unresolved reason so callers cannot collapse an incomplete
    live proof into a successful boolean.
    """

    if len(evidence.control_plane_head) != 40 or not all(
        character in "0123456789abcdef" for character in evidence.control_plane_head
    ):
        raise ScannerResultBridgeError("bridge control-plane head is invalid")
    if evidence.provider_enabled is not True:
        raise ScannerResultBridgeError("bridge provider is unproved")
    if evidence.quarantine_container != "quarantine":
        raise ScannerResultBridgeError("bridge producer is unproved")
    if evidence.event_type != "Microsoft.Security.MalwareScanningResult":
        raise ScannerResultBridgeError("bridge transport is unproved")
    if evidence.event_schema_version != SCHEMA_VERSION:
        raise ScannerResultBridgeError("bridge schema is unproved")
    if evidence.tls_version not in {"TLS1_2", "TLS1_3"}:
        raise ScannerResultBridgeError("bridge private path is unproved")
    if evidence.unresolved_reasons:
        raise ScannerResultBridgeError("bridge evidence has unresolved reasons")
    sha_values = (
        evidence.environment_sha256,
        evidence.operation_id_sha256,
        evidence.provider_resource_id_sha256,
        evidence.provider_capability_proof_integrity,
        evidence.storage_resource_id_sha256,
        evidence.blob_identity_sha256,
        evidence.content_sha256,
        evidence.scan_request_id_sha256,
        evidence.producer_proof_integrity,
        evidence.system_topic_resource_id_sha256,
        evidence.event_subscription_resource_id_sha256,
        evidence.filter_integrity,
        evidence.private_queue_resource_id_sha256,
        evidence.dead_letter_queue_resource_id_sha256,
        evidence.transport_proof_integrity,
        evidence.consumer_identity_sha256,
        evidence.queue_adapter_identity_sha256,
        evidence.malware_scan_receipt_id_sha256,
        evidence.idempotency_key_sha256,
        evidence.consumer_proof_integrity,
        evidence.sender_identity_sha256,
        evidence.processor_identity_sha256,
        evidence.sender_role_definition_sha256,
        evidence.processor_role_definition_sha256,
        evidence.sender_scope_sha256,
        evidence.processor_scope_sha256,
        evidence.assignment_proof_integrity,
        evidence.revocation_proof_integrity,
        evidence.private_endpoint_resource_id_sha256,
        evidence.private_dns_resource_id_sha256,
        evidence.private_address_sha256,
        evidence.tls_hostname_sha256,
        evidence.private_path_proof_integrity,
        evidence.cleanup_inventory_integrity,
    )
    if not all(_sha256(value) for value in sha_values):
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
    value: Mapping[str, object], *, now: datetime
) -> ScannerResultBridgeDeploymentEvidence:
    """Decode a canonical external evidence artifact without retaining raw IDs."""

    expected = {field.name for field in fields(ScannerResultBridgeDeploymentEvidence)}
    if set(value) != expected:
        raise ScannerResultBridgeError("bridge deployment evidence fields are invalid")
    legacy_raw = value.get("legacy_evidence")
    if not isinstance(legacy_raw, Mapping):
        raise ScannerResultBridgeError("bridge legacy evidence is malformed")
    legacy_expected = {field.name for field in fields(ScannerResultBridgeEvidence)}
    if set(legacy_raw) != legacy_expected:
        raise ScannerResultBridgeError("bridge legacy evidence fields are invalid")
    try:
        legacy = ScannerResultBridgeEvidence(**dict(legacy_raw))
        decoded = ScannerResultBridgeDeploymentEvidence(
            **{**dict(value), "legacy_evidence": legacy, "unresolved_reasons": tuple(value["unresolved_reasons"])}
        )
    except (TypeError, KeyError) as exc:
        raise ScannerResultBridgeError("bridge deployment evidence is malformed") from exc
    return build_scanner_result_bridge_deployment_evidence(decoded, now=now)
