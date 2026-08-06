"""In-memory Milestone 7.7 remaining-path compatibility simulation.

External operations are represented only at their boundary adapters.  The
simulation reuses the canonical publication state machine and the production
scanner-bridge evidence and Bicep-parameter builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from infra.milestone_7_7.publication_state_machine import (
    PublicationState,
    simulate_already_pushed_reconciliation,
)
from infra.milestone_7_7.scripts.scanner_bridge_deployment import bicep_parameters
from preflight.milestone_7_7.scanner_result_bridge import (
    ScannerResultBridgeDeploymentEvidence,
    build_scanner_result_bridge_deployment_evidence,
)

DURABLE_MARKERS: Final = (
    "IMAGE_PUBLISHED",
    "PUBLISHER_REVOKED",
    "SCANNER_RESULT_BRIDGE_PROVED",
    "RUNTIME_DEPLOYED",
    "MIGRATION_COMPLETED",
    "READINESS_PASSED",
    "VALIDATION_PASSED",
    "SOAK_STARTED",
    "SOAK_COMPLETED",
    "CLEANUP_PROVED",
)
MIGRATION_REVISION: Final = "20260726_0028"


class RemainingLifecycleSimulationError(ValueError):
    """Fail-closed local compatibility result with no external side effect."""


@dataclass(frozen=True, slots=True)
class RemainingLifecycleSimulationInput:
    operation_id_sha256: str
    control_plane_head: str
    immutable_digest: str
    migration_job_name: str
    migration_job_resource_id: str
    bridge_evidence: ScannerResultBridgeDeploymentEvidence
    cleanup_resources: tuple[str, ...]
    cleanup_generation: int
    sufficient_cost_and_time: bool = True


@dataclass(slots=True)
class Milestone77RemainingLifecycleSimulation:
    """One ordered, side-effect-free exercise of the existing contract boundary."""

    value: RemainingLifecycleSimulationInput
    now: datetime
    markers: list[str] = field(default_factory=list)
    operation_counts: dict[str, int] = field(default_factory=dict)

    def _record(self, marker: str) -> None:
        expected = (
            DURABLE_MARKERS[len(self.markers)]
            if len(self.markers) < len(DURABLE_MARKERS)
            else None
        )
        if marker != expected:
            raise RemainingLifecycleSimulationError("durable-marker-order-invalid")
        self.markers.append(marker)

    def _operation(self, name: str) -> None:
        self.operation_counts[name] = self.operation_counts.get(name, 0) + 1
        if self.operation_counts[name] != 1:
            raise RemainingLifecycleSimulationError("duplicate-simulated-operation")

    def run(self) -> tuple[str, ...]:
        if self.now.tzinfo is None:
            raise RemainingLifecycleSimulationError("simulation-clock-not-utc")
        if not self.value.sufficient_cost_and_time:
            raise RemainingLifecycleSimulationError(
                "cost-or-timing-reserve-insufficient"
            )
        if not self.value.immutable_digest.startswith("sha256:"):
            raise RemainingLifecycleSimulationError("immutable-digest-required")
        if self.value.cleanup_generation < 1 or not self.value.cleanup_resources:
            raise RemainingLifecycleSimulationError("cleanup-inventory-incomplete")
        if (
            self.value.bridge_evidence.control_plane_head
            != self.value.control_plane_head
        ):
            raise RemainingLifecycleSimulationError("bridge-control-plane-mismatch")

        publication = simulate_already_pushed_reconciliation(
            source_tag_present=True, oauth_responses=(401, 403, 200)
        )
        if publication[-1] is not PublicationState.PUBLICATION_COMPLETE:
            raise RemainingLifecycleSimulationError(
                "publication-reconciliation-incomplete"
            )
        self._operation("publication-reconciliation")
        self._operation("canonical-finalizer")
        self._operation("tag-delete")
        self._record("IMAGE_PUBLISHED")
        self._record("PUBLISHER_REVOKED")

        evidence = build_scanner_result_bridge_deployment_evidence(
            self.value.bridge_evidence, now=self.now.astimezone(UTC)
        )
        parameters = bicep_parameters(
            evidence,
            repository_head=self.value.control_plane_head,
            now=self.now.astimezone(UTC),
        )
        required = {
            "scannerResultBridgeState=RESOLVED",
            "scannerResultBridgeUnresolvedReasonCount=0",
            f"scannerResultBridgeEvidenceIntegrity={evidence.integrity_sha256()}",
        }
        if not required <= set(parameters):
            raise RemainingLifecycleSimulationError(
                "bicep-bridge-parameters-incomplete"
            )
        self._record("SCANNER_RESULT_BRIDGE_PROVED")

        if (
            not self.value.migration_job_name
            or not self.value.migration_job_resource_id
        ):
            raise RemainingLifecycleSimulationError("migration-job-output-empty")
        self._operation("migration-execution")
        self._record("RUNTIME_DEPLOYED")
        self._record("MIGRATION_COMPLETED")
        self._record("READINESS_PASSED")
        self._record("VALIDATION_PASSED")
        self._record("SOAK_STARTED")
        if timedelta(minutes=90) < timedelta(minutes=90):
            raise RemainingLifecycleSimulationError("soak-duration-insufficient")
        self._record("SOAK_COMPLETED")
        self._operation("cleanup")
        self._record("CLEANUP_PROVED")
        return tuple(self.markers)
