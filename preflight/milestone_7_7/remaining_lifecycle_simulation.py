"""Side-effect-free execution of every remaining Milestone 7.7 handoff.

The simulation deliberately uses the production serializers and consumers.  It
does not call Azure, Docker, ACR, or a scanner.  Its fake clock advances through
the complete 90-minute soak while the real soak state machine validates every
sample and writes the same integrity-bound progress artifacts used in a live run.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, cast

from infra.milestone_7_7 import api_image_publication, scanner_bridge_recovery_adapter
from infra.milestone_7_7.publication_state_machine import (
    PublicationState,
    simulate_already_pushed_reconciliation,
)
from infra.milestone_7_7.scripts.scanner_bridge_deployment import (
    bicep_parameters,
    load_deployment_evidence,
)
from performance.milestone_7_7.framework import JsonValue, canonical_bytes, load_json
from preflight.milestone_7_7 import terminal_lifecycle
from preflight.milestone_7_7.managed_binding_contracts import (
    build_authorization_ledger,
    validate_authorization_ledger,
)
from preflight.milestone_7_7.scanner_result_bridge import (
    ScannerResultBridgeDeploymentEvidence,
)

DURABLE_MARKERS: Final = (
    "IMAGE_PUBLISHED",
    "PUBLISHER_REVOKED",
    "SCANNER_RESULT_BRIDGE_PROVED",
    "POST_SECRET_FOUNDATION_READY",
    "MIGRATION_COMPLETED",
    "READINESS_PASSED",
    "VALIDATION_PASSED",
    "SOAK_STARTED",
    "SOAK_COMPLETED",
    "READY_FOR_FINAL_CLEANUP",
    "CLEANUP_COMPLETED",
    "ZERO_RESIDUE_PROVED",
    terminal_lifecycle.MILESTONE_COMPLETION_MARKER,
)
MIGRATION_REVISION: Final = terminal_lifecycle.MIGRATION_REVISION
_REGISTRY_IMAGE_PREFIX: Final = "acrmobius7711564669.azurecr.io/opencanvas-api@"
_RESOURCE_GROUPS: Final = (
    "rg-solarplexus-mobius-77-staging",
    "rg-solarplexus-mobius-77-cleanup-control",
    "rg-solarplexus-mobius-77-containerapps-infrastructure",
)


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
class _SimulationClock:
    value: datetime
    monotonic_seconds: float = 0.0

    def now(self) -> datetime:
        return self.value

    def monotonic(self) -> float:
        return self.monotonic_seconds

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise RemainingLifecycleSimulationError("simulation-clock-regressed")
        self.monotonic_seconds += seconds
        self.value += timedelta(seconds=seconds)


@dataclass(slots=True)
class Milestone77RemainingLifecycleSimulation:
    """One ordered exercise of the exact production artifact boundaries."""

    value: RemainingLifecycleSimulationInput
    now: datetime
    markers: list[str] = field(default_factory=list)
    operation_counts: dict[str, int] = field(default_factory=dict)

    def _record(self, marker: str) -> None:
        expected = (
            DURABLE_MARKERS[len(self.markers)] if len(self.markers) < len(DURABLE_MARKERS) else None
        )
        if marker != expected:
            raise RemainingLifecycleSimulationError("durable-marker-order-invalid")
        self.markers.append(marker)

    def _operation(self, name: str) -> None:
        self.operation_counts[name] = self.operation_counts.get(name, 0) + 1
        if self.operation_counts[name] != 1:
            raise RemainingLifecycleSimulationError("duplicate-simulated-operation")

    def _image_reference(self) -> str:
        if self.value.immutable_digest.startswith(_REGISTRY_IMAGE_PREFIX):
            return self.value.immutable_digest
        if self.value.immutable_digest.startswith("sha256:"):
            return _REGISTRY_IMAGE_PREFIX + self.value.immutable_digest
        raise RemainingLifecycleSimulationError("immutable-digest-required")

    def _ledger(self) -> dict[str, JsonValue]:
        build_input = api_image_publication._api_image_build_input_sha256(
            self.value.control_plane_head
        )
        pending: dict[str, JsonValue] = {
            "configDigest": "sha256:" + "c" * 64,
            "imageBuildInputSha256": build_input,
            "imageSourceCommit": self.value.control_plane_head,
            "localImageId": "sha256:" + "c" * 64,
            "platform": "linux/amd64",
            "registryManifestDigest": None,
            "repository": "opencanvas-api",
            "sourceTag": f"source-{self.value.control_plane_head}",
        }
        produced = build_authorization_ledger(
            issued_at_utc=self.now,
            repository_head=self.value.control_plane_head,
            pending_image=pending,
        )
        decoded = json.loads(canonical_bytes(cast(JsonValue, produced)))
        return validate_authorization_ledger(
            cast(JsonValue, decoded),
            now_utc=self.now,
            expected_repository_head=self.value.control_plane_head,
        )

    def _produce_stage(
        self,
        *,
        receipt_directory: Path,
        ledger: dict[str, JsonValue],
        stage: str,
        payload: dict[str, JsonValue],
        started_at: datetime,
        completed_at: datetime,
    ) -> terminal_lifecycle.TerminalStageEvidence:
        predecessor = terminal_lifecycle.STAGE_PREDECESSOR[stage]
        previous = (
            None
            if predecessor is None
            else terminal_lifecycle.load_stage_evidence(
                terminal_lifecycle.stage_evidence_path(receipt_directory, predecessor),
                expected_stage=predecessor,
                repository_head=self.value.control_plane_head,
                ledger_integrity_sha256=str(ledger["ledgerIntegritySha256"]),
            )
        )
        produced = terminal_lifecycle.build_stage_evidence(
            stage=stage,
            repository_head=self.value.control_plane_head,
            ledger_integrity_sha256=str(ledger["ledgerIntegritySha256"]),
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            payload=payload,
            previous=previous,
        )
        terminal_lifecycle.write_stage_evidence(receipt_directory, produced)
        return terminal_lifecycle.load_stage_evidence(
            terminal_lifecycle.stage_evidence_path(receipt_directory, stage),
            expected_stage=stage,
            repository_head=self.value.control_plane_head,
            ledger_integrity_sha256=str(ledger["ledgerIntegritySha256"]),
        )

    def _live_sample(
        self, *, clock: _SimulationClock, runtime_graph: str, deadline: datetime
    ) -> terminal_lifecycle.LiveValidationSample:
        return terminal_lifecycle.LiveValidationSample(
            observed_at_utc=clock.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            runtime_graph_integrity_sha256=runtime_graph,
            private_address_sha256="b" * 64,
            private_dns_proved=True,
            tls_version="TLS1_3",
            api_live=True,
            api_ready=True,
            worker_ready=True,
            telemetry_ready=True,
            cleanup_armed=True,
            cleanup_deadline_utc=deadline.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            maximum_cost_usd_cents=20_607,
            temporary_authority_absent=True,
        )

    def run(self) -> tuple[str, ...]:
        if self.now.tzinfo is None:
            raise RemainingLifecycleSimulationError("simulation-clock-not-utc")
        if not self.value.sufficient_cost_and_time:
            raise RemainingLifecycleSimulationError("cost-or-timing-reserve-insufficient")
        image_reference = self._image_reference()
        if self.value.cleanup_generation < 1 or not self.value.cleanup_resources:
            raise RemainingLifecycleSimulationError("cleanup-inventory-incomplete")
        if self.value.bridge_evidence.control_plane_head != self.value.control_plane_head:
            raise RemainingLifecycleSimulationError("bridge-control-plane-mismatch")

        ledger = self._ledger()
        self._operation("current-head-ledger")
        publication = simulate_already_pushed_reconciliation(
            source_tag_present=True, oauth_responses=(401, 403, 200)
        )
        if publication[-1] is not PublicationState.PUBLICATION_COMPLETE:
            raise RemainingLifecycleSimulationError("publication-reconciliation-incomplete")
        self._operation("image-admission-and-publication-reconciliation")
        self._record("IMAGE_PUBLISHED")
        self._record("PUBLISHER_REVOKED")

        with tempfile.TemporaryDirectory(prefix="mobius77-terminal-simulation-") as raw:
            receipt_directory = Path(raw)
            bridge_path = receipt_directory / "scanner-bridge-deployment-evidence.json"
            scanner_bridge_recovery_adapter._write_evidence(bridge_path, self.value.bridge_evidence)
            bridge_evidence = load_deployment_evidence(
                bridge_path,
                repository_head=self.value.control_plane_head,
                now=self.now.astimezone(UTC),
            )
            parameters = bicep_parameters(
                bridge_evidence,
                repository_head=self.value.control_plane_head,
                now=self.now.astimezone(UTC),
            )
            required = {
                "scannerResultBridgeState=RESOLVED",
                "scannerResultBridgeUnresolvedReasonCount=0",
                "scannerResultBridgeEvidenceIntegrity=" + bridge_evidence.integrity_sha256(),
            }
            if not required <= set(parameters):
                raise RemainingLifecycleSimulationError("bicep-bridge-parameters-incomplete")
            self._operation("scanner-evidence-producer-consumer")
            self._record("SCANNER_RESULT_BRIDGE_PROVED")

            cursor = self.now.astimezone(UTC).replace(microsecond=0)
            post_secret = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="post-secret-provisioning",
                payload={
                    "apiDefinitionAuthoritative": True,
                    "immutableImageDigest": image_reference,
                    "managedEnvironmentAuthoritative": True,
                    "managedSecretCount": 11,
                    "migrationDefinitionAuthoritative": True,
                    "postgresqlAuthoritative": True,
                    "redisAuthoritative": True,
                    "scannerEvidenceIntegritySha256": bridge_evidence.integrity_sha256(),
                    "secretValueAccessed": False,
                    "telemetryDefinitionAuthoritative": True,
                    "workerDefinitionAuthoritative": True,
                },
                started_at=cursor,
                completed_at=cursor + timedelta(seconds=1),
            )
            del post_secret
            cursor += timedelta(seconds=2)
            self._operation("post-secret-provisioning")
            self._record("POST_SECRET_FOUNDATION_READY")

            if not self.value.migration_job_name or not self.value.migration_job_resource_id:
                raise RemainingLifecycleSimulationError("migration-job-output-empty")
            migration = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="migration-execution",
                payload={
                    "executionNameSha256": self.value.operation_id_sha256,
                    "expectedRevision": MIGRATION_REVISION,
                    "singleExecution": True,
                    "terminalStatus": "Succeeded",
                },
                started_at=cursor,
                completed_at=cursor + timedelta(seconds=1),
            )
            del migration
            cursor += timedelta(seconds=2)
            self._operation("migration-execution")
            self._record("MIGRATION_COMPLETED")

            readiness = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="readiness-validation",
                payload={
                    "apiRevisionSha256": "1" * 64,
                    "immutableImageDigest": image_reference,
                    "privateIngressOnly": True,
                    "telemetryRevisionSha256": "2" * 64,
                    "workerRevisionSha256": "3" * 64,
                },
                started_at=cursor,
                completed_at=cursor + timedelta(seconds=1),
            )
            del readiness
            cursor += timedelta(seconds=2)
            self._operation("readiness-validation")
            self._record("READINESS_PASSED")

            runtime_graph = "4" * 64
            cleanup_deadline = cursor + timedelta(hours=5)
            clock = _SimulationClock(cursor)
            sample = self._live_sample(
                clock=clock, runtime_graph=runtime_graph, deadline=cleanup_deadline
            )
            live = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="live-validation",
                payload={
                    "apiLive": sample.api_live,
                    "apiReady": sample.api_ready,
                    "cleanupArmed": sample.cleanup_armed,
                    "cleanupDeadlineUtc": sample.cleanup_deadline_utc,
                    "maximumCostUsdCents": sample.maximum_cost_usd_cents,
                    "privateAddressSha256": sample.private_address_sha256,
                    "privateDnsProved": sample.private_dns_proved,
                    "runtimeGraphIntegritySha256": runtime_graph,
                    "runtimeMode": "live-staging",
                    "telemetryReady": sample.telemetry_ready,
                    "temporaryAuthorityAbsent": sample.temporary_authority_absent,
                    "tlsVersion": sample.tls_version,
                    "workerReady": sample.worker_ready,
                },
                started_at=cursor,
                completed_at=cursor + timedelta(seconds=1),
            )
            del live
            clock.sleep(2)
            self._operation("live-validation")
            self._record("VALIDATION_PASSED")
            self._record("SOAK_STARTED")

            soak_result = terminal_lifecycle.run_uninterrupted_soak(
                repository_head=self.value.control_plane_head,
                ledger_integrity_sha256=str(ledger["ledgerIntegritySha256"]),
                cleanup_deadline_utc=cleanup_deadline,
                sample=lambda: self._live_sample(
                    clock=clock,
                    runtime_graph=runtime_graph,
                    deadline=cleanup_deadline,
                ),
                clock=clock.now,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                progress=lambda document: terminal_lifecycle.write_soak_progress(
                    receipt_directory / terminal_lifecycle.SOAK_PROGRESS_FILE,
                    document,
                ),
            )
            soak = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="soak",
                payload=soak_result.payload,
                started_at=soak_result.started_at_utc,
                completed_at=soak_result.completed_at_utc,
            )
            self._operation("uninterrupted-soak")
            self._record("SOAK_COMPLETED")

            closeout = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="successful-closeout",
                payload={
                    "lifecycleTemporaryTagCount": 0,
                    "proofJobResidueCount": 0,
                    "publisherFinalizerResidueCount": 0,
                    "requiredEvidenceChainIntegritySha256": soak.integrity_sha256,
                    "temporaryAssignmentCount": 0,
                    "temporaryAuthorizationCount": 0,
                    "temporaryCustomRoleCount": 0,
                },
                started_at=clock.now(),
                completed_at=clock.now() + timedelta(seconds=1),
            )
            self._operation("successful-closeout")
            self._record("READY_FOR_FINAL_CLEANUP")

            authorization = terminal_lifecycle.build_successful_cleanup_authorization(
                closeout_evidence=closeout,
                authorization_id=str(ledger["authorizationId"]),
                resource_groups=_RESOURCE_GROUPS,
                issued_at_utc=clock.now() + timedelta(seconds=1),
            )
            terminal_lifecycle.write_cleanup_authorization(receipt_directory, authorization)
            decoded_authorization = load_json(
                receipt_directory / terminal_lifecycle.CLEANUP_AUTHORIZATION_FILE
            )
            if not isinstance(decoded_authorization, dict):
                raise RemainingLifecycleSimulationError("cleanup-authorization-malformed")
            terminal_lifecycle.validate_cleanup_authorization(
                decoded_authorization,
                authorization_id=str(ledger["authorizationId"]),
                repository_head=self.value.control_plane_head,
                resource_groups=_RESOURCE_GROUPS,
                now_utc=clock.now() + timedelta(seconds=2),
                closeout_evidence=closeout,
            )
            (receipt_directory / terminal_lifecycle.CLEANUP_AUTHORIZATION_FILE).unlink()
            cleanup = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="cleanup",
                payload={
                    "authorizationMode": "successful-closeout",
                    "resourceGroupDeleteCount": 3,
                    "softDeletedVaultAbsent": True,
                    "temporaryAuthorityRevoked": True,
                },
                started_at=clock.now() + timedelta(seconds=2),
                completed_at=clock.now() + timedelta(seconds=3),
            )
            del cleanup
            self._operation("cleanup-authorization-and-execution")
            self._record("CLEANUP_COMPLETED")

            zero = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="zero-residue-verification",
                payload={
                    "finalizerIdentityCount": 0,
                    "lifecycleTemporaryTagCount": 0,
                    "proofJobCount": 0,
                    "publisherIdentityCount": 0,
                    "resourceGroupCount": 0,
                    "softDeletedVaultCount": 0,
                    "targetResourceCount": 0,
                    "temporaryAssignmentCount": 0,
                    "temporaryAuthorizationCount": 0,
                    "temporaryCustomRoleCount": 0,
                },
                started_at=clock.now() + timedelta(seconds=4),
                completed_at=clock.now() + timedelta(seconds=5),
            )
            self._operation("zero-residue-verification")
            self._record("ZERO_RESIDUE_PROVED")

            completion = self._produce_stage(
                receipt_directory=receipt_directory,
                ledger=ledger,
                stage="milestone-completion",
                payload={
                    "marker": terminal_lifecycle.MILESTONE_COMPLETION_MARKER,
                    "milestone78Started": False,
                    "provisioningAuthorized": False,
                    "zeroResidueEvidenceIntegritySha256": zero.integrity_sha256,
                },
                started_at=clock.now() + timedelta(seconds=6),
                completed_at=clock.now() + timedelta(seconds=7),
            )
            final_mapping = json.loads(canonical_bytes(completion.canonical()))
            terminal_lifecycle.stage_evidence_from_mapping(final_mapping)
            self._operation("milestone-completion")
            self._record(terminal_lifecycle.MILESTONE_COMPLETION_MARKER)

        return tuple(self.markers)


__all__ = [
    "DURABLE_MARKERS",
    "MIGRATION_REVISION",
    "Milestone77RemainingLifecycleSimulation",
    "RemainingLifecycleSimulationError",
    "RemainingLifecycleSimulationInput",
]
