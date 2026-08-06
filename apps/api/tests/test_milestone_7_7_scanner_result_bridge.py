from __future__ import annotations

from datetime import UTC, datetime

from infra.milestone_7_7.scripts.scanner_bridge_deployment import bicep_parameters
from preflight.milestone_7_7.scanner_result_bridge import (
    PROVIDER,
    SCHEMA_VERSION,
    TRANSPORT,
    ScannerResultBridgeDeploymentEvidence,
    ScannerResultBridgeError,
    ScannerResultBridgeEvidence,
    build_scanner_result_bridge_deployment_evidence,
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
    state, _integrity = resolve_bridge(
        _evidence(decision="unknown"),
        now=datetime(2026, 8, 5, 4, 1, tzinfo=UTC),
    )

    assert state == "CONSUMER_UNPROVED"


def _deployment_evidence(**changes: object) -> ScannerResultBridgeDeploymentEvidence:
    hash_value = "a" * 64
    values: dict[str, object] = {
        "control_plane_head": "b" * 40,
        "environment_sha256": hash_value,
        "operation_id_sha256": hash_value,
        "observed_at_utc": "2026-08-05T04:00:00Z",
        "legacy_evidence": _evidence(),
        "provider_resource_id_sha256": hash_value,
        "provider_api_version": "2024-01-01",
        "provider_enabled": True,
        "provider_capability_proof_integrity": hash_value,
        "storage_resource_id_sha256": hash_value,
        "quarantine_container": "quarantine",
        "blob_identity_sha256": hash_value,
        "content_sha256": hash_value,
        "scan_request_id_sha256": hash_value,
        "producer_proof_integrity": hash_value,
        "system_topic_resource_id_sha256": hash_value,
        "event_subscription_resource_id_sha256": hash_value,
        "event_type": "Microsoft.Security.MalwareScanningResult",
        "event_schema_version": SCHEMA_VERSION,
        "filter_integrity": hash_value,
        "private_queue_resource_id_sha256": hash_value,
        "dead_letter_queue_resource_id_sha256": hash_value,
        "transport_proof_integrity": hash_value,
        "consumer_identity_sha256": hash_value,
        "queue_adapter_identity_sha256": hash_value,
        "malware_scan_receipt_id_sha256": hash_value,
        "idempotency_key_sha256": hash_value,
        "consumer_proof_integrity": hash_value,
        "sender_identity_sha256": hash_value,
        "processor_identity_sha256": hash_value,
        "sender_role_definition_sha256": hash_value,
        "processor_role_definition_sha256": hash_value,
        "sender_scope_sha256": hash_value,
        "processor_scope_sha256": hash_value,
        "assignment_proof_integrity": hash_value,
        "revocation_proof_integrity": hash_value,
        "private_endpoint_resource_id_sha256": hash_value,
        "private_dns_resource_id_sha256": hash_value,
        "private_address_sha256": hash_value,
        "tls_hostname_sha256": hash_value,
        "tls_version": "TLS1_2",
        "private_path_proof_integrity": hash_value,
        "cleanup_inventory_integrity": hash_value,
        "unresolved_reasons": (),
    }
    values.update(changes)
    return ScannerResultBridgeDeploymentEvidence(**values)  # type: ignore[arg-type]


def test_deployment_evidence_is_typed_complete_and_maps_all_required_proofs() -> None:
    evidence = _deployment_evidence()
    now = datetime(2026, 8, 5, 4, 1, tzinfo=UTC)
    assert build_scanner_result_bridge_deployment_evidence(evidence, now=now) == evidence
    parameters = bicep_parameters(evidence, repository_head="b" * 40, now=now)
    expected = {
        "scannerResultBridgeProviderProofIntegrity",
        "scannerResultBridgeProducerProofIntegrity",
        "scannerResultBridgeTransportProofIntegrity",
        "scannerResultBridgeConsumerProofIntegrity",
        "scannerResultBridgeIdentityRbacProofIntegrity",
        "scannerResultBridgePrivatePathProofIntegrity",
        "scannerResultBridgeCorrelationProofIntegrity",
        "scannerResultBridgeRevocationProofIntegrity",
        "scannerResultBridgeCleanupInventoryIntegrity",
    }
    assert expected <= {parameter.split("=", 1)[0] for parameter in parameters}
    assert not any("scannerResultBridgeResolved" in parameter for parameter in parameters)


def test_deployment_evidence_fails_closed_for_unresolved_or_incomplete_proof() -> None:
    now = datetime(2026, 8, 5, 4, 1, tzinfo=UTC)
    for evidence in (
        _deployment_evidence(unresolved_reasons=("transport-unproved",)),
        _deployment_evidence(provider_enabled=False),
        _deployment_evidence(event_type="wrong"),
        _deployment_evidence(tls_version="TLS1_0"),
    ):
        try:
            build_scanner_result_bridge_deployment_evidence(evidence, now=now)
        except ScannerResultBridgeError:
            pass
        else:
            raise AssertionError("incomplete bridge proof was accepted")


def test_existing_ingestion_service_has_managed_identity_bridge_entry_point() -> None:
    source = __import__(
        "opencanvas_api.services.object_ingestion", fromlist=["MalwareScanService"]
    ).MalwareScanService.record_bridge_result.__doc__
    assert source is not None
    assert "legacy shared secret" in source
