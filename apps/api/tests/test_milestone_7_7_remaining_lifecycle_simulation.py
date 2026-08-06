from __future__ import annotations

from datetime import UTC, datetime

import pytest
from preflight.milestone_7_7.remaining_lifecycle_simulation import (
    DURABLE_MARKERS,
    Milestone77RemainingLifecycleSimulation,
    RemainingLifecycleSimulationError,
    RemainingLifecycleSimulationInput,
)
from preflight.milestone_7_7.scanner_result_bridge import (
    PROVIDER,
    SCHEMA_VERSION,
    TRANSPORT,
    ScannerResultBridgeDeploymentEvidence,
    ScannerResultBridgeEvidence,
)


def _input(**changes: object) -> RemainingLifecycleSimulationInput:
    digest = "a" * 64
    legacy = ScannerResultBridgeEvidence(
        observed_at_utc="2026-08-05T04:00:00Z",
        provider=PROVIDER,
        transport=TRANSPORT,
        schema_version=SCHEMA_VERSION,
        proofs={
            key: True
            for key in (
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
        },
        correlation_id_sha256=digest,
        event_id_sha256=digest,
        provider_result_id_sha256=digest,
        object_version_or_etag_sha256=digest,
        storage_resource_sha256=digest,
        delivery_attempt_sha256=digest,
        decision="clean",
    )
    evidence = ScannerResultBridgeDeploymentEvidence(
        control_plane_head="b" * 40,
        environment_sha256=digest,
        operation_id_sha256=digest,
        observed_at_utc="2026-08-05T04:00:00Z",
        legacy_evidence=legacy,
        provider_resource_id_sha256=digest,
        provider_api_version="2024-01-01",
        provider_enabled=True,
        provider_capability_proof_integrity=digest,
        storage_resource_id_sha256=digest,
        quarantine_container="quarantine",
        blob_identity_sha256=digest,
        content_sha256=digest,
        scan_request_id_sha256=digest,
        producer_proof_integrity=digest,
        system_topic_resource_id_sha256=digest,
        event_subscription_resource_id_sha256=digest,
        event_type="Microsoft.Security.MalwareScanningResult",
        event_schema_version=SCHEMA_VERSION,
        filter_integrity=digest,
        private_queue_resource_id_sha256=digest,
        dead_letter_queue_resource_id_sha256=digest,
        transport_proof_integrity=digest,
        consumer_identity_sha256=digest,
        queue_adapter_identity_sha256=digest,
        malware_scan_receipt_id_sha256=digest,
        idempotency_key_sha256=digest,
        consumer_proof_integrity=digest,
        sender_identity_sha256=digest,
        processor_identity_sha256=digest,
        sender_role_definition_sha256=digest,
        processor_role_definition_sha256=digest,
        sender_scope_sha256=digest,
        processor_scope_sha256=digest,
        assignment_proof_integrity=digest,
        revocation_proof_integrity=digest,
        private_endpoint_resource_id_sha256=digest,
        private_dns_resource_id_sha256=digest,
        private_address_sha256=digest,
        tls_hostname_sha256=digest,
        tls_version="TLS1_2",
        private_path_proof_integrity=digest,
        cleanup_inventory_integrity=digest,
        unresolved_reasons=(),
    )
    values: dict[str, object] = {
        "operation_id_sha256": digest,
        "control_plane_head": "b" * 40,
        "immutable_digest": "sha256:" + digest,
        "migration_job_name": "migration-job",
        "migration_job_resource_id": "opaque-resource-alias",
        "bridge_evidence": evidence,
        "cleanup_resources": ("bridge", "runtime", "migration"),
        "cleanup_generation": 2,
    }
    values.update(changes)
    return RemainingLifecycleSimulationInput(**values)  # type: ignore[arg-type]


def test_complete_remaining_path_reaches_cleanup_proved_in_order() -> None:
    simulation = Milestone77RemainingLifecycleSimulation(
        _input(), datetime(2026, 8, 5, 4, 1, tzinfo=UTC)
    )
    assert simulation.run() == DURABLE_MARKERS
    assert simulation.operation_counts == {
        "publication-reconciliation": 1,
        "canonical-finalizer": 1,
        "tag-delete": 1,
        "migration-execution": 1,
        "cleanup": 1,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"immutable_digest": "source-tag"},
        {"migration_job_name": ""},
        {"cleanup_resources": ()},
        {"sufficient_cost_and_time": False},
    ],
)
def test_remaining_path_fails_closed_before_invalid_marker(changes: dict[str, object]) -> None:
    simulation = Milestone77RemainingLifecycleSimulation(
        _input(**changes), datetime(2026, 8, 5, 4, 1, tzinfo=UTC)
    )
    with pytest.raises(RemainingLifecycleSimulationError):
        simulation.run()
    assert len(simulation.markers) < len(DURABLE_MARKERS)
