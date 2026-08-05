"""Fail-closed local contract for the Milestone 7.7 scanner-result bridge.

This module deliberately has no Azure client.  It turns sanitized, immutable
bridge evidence into a deterministic admission decision; live provider proof is
still required before the result can be ``RESOLVED`` in a deployment ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
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
