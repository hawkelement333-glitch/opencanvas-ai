from __future__ import annotations

from datetime import UTC, datetime

from preflight.milestone_7_7.scanner_result_bridge import (
    PROVIDER,
    SCHEMA_VERSION,
    TRANSPORT,
    ScannerResultBridgeEvidence,
    resolve_bridge,
)


def _evidence(**changes: object) -> ScannerResultBridgeEvidence:
    values: dict[str, object] = {
        "observed_at_utc": "2026-08-05T04:00:00Z",
        "provider": PROVIDER,
        "transport": TRANSPORT,
        "schema_version": SCHEMA_VERSION,
        "proofs": {
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
        "correlation_id_sha256": "a" * 64,
        "event_id_sha256": "b" * 64,
        "provider_result_id_sha256": "c" * 64,
        "object_version_or_etag_sha256": "d" * 64,
        "storage_resource_sha256": "e" * 64,
        "delivery_attempt_sha256": "f" * 64,
        "decision": "clean",
    }
    values.update(changes)
    return ScannerResultBridgeEvidence(**values)  # type: ignore[arg-type]


def test_complete_evidence_is_deterministic_and_resolved() -> None:
    evidence = _evidence()
    first = resolve_bridge(evidence, now=datetime(2026, 8, 5, 4, 1, tzinfo=UTC))
    second = resolve_bridge(evidence, now=datetime(2026, 8, 5, 4, 1, tzinfo=UTC))
    assert first == second
    assert first[0] == "RESOLVED"
    assert first[1] == evidence.integrity_sha256()


def test_naked_boolean_cannot_replace_complete_evidence() -> None:
    assert resolve_bridge(None, now=datetime.now(UTC)) == ("CONTRACT_UNDEFINED", None)


def test_each_security_proof_fails_closed() -> None:
    expected = {
        "provider": "PROVIDER_UNAVAILABLE",
        "resources": "RESOURCES_UNDEPLOYED",
        "identity": "IDENTITY_UNPROVED",
        "rbac": "RBAC_UNPROVED",
        "privatePath": "PRIVATE_PATH_UNPROVED",
        "producer": "PRODUCER_UNPROVED",
        "transport": "TRANSPORT_UNPROVED",
        "consumer": "CONSUMER_UNPROVED",
        "schema": "SCHEMA_UNPROVED",
        "correlation": "CORRELATION_UNPROVED",
        "revocation": "REVOCATION_UNPROVED",
    }
    for proof, state in expected.items():
        proofs = dict(_evidence().proofs)
        proofs[proof] = False
        assert resolve_bridge(_evidence(proofs=proofs), now=datetime.now(UTC))[0] == state


def test_stale_or_incomplete_correlation_never_resolves() -> None:
    stale = _evidence(observed_at_utc="2026-08-01T00:00:00Z")
    assert resolve_bridge(stale, now=datetime(2026, 8, 5, tzinfo=UTC))[0] == "STALE_EVIDENCE"
    assert (
        resolve_bridge(_evidence(event_id_sha256="not-a-hash"), now=datetime.now(UTC))[0]
        == "CORRELATION_UNPROVED"
    )


def test_unknown_decision_never_resolves() -> None:
    state, _integrity = resolve_bridge(_evidence(decision="unknown"), now=datetime.now(UTC))

    assert state == "CONSUMER_UNPROVED"


def test_existing_ingestion_service_has_managed_identity_bridge_entry_point() -> None:
    source = __import__(
        "opencanvas_api.services.object_ingestion", fromlist=["MalwareScanService"]
    ).MalwareScanService.record_bridge_result.__doc__
    assert source is not None
    assert "legacy shared secret" in source
