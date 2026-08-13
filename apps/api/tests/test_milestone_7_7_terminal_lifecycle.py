from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_7 import terminal_lifecycle_adapter
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import terminal_lifecycle
from preflight.milestone_7_7.managed_binding_contracts import (
    EXPECTED_LIFECYCLE_OPERATIONS,
    load_operation_overlay,
)

HEAD = "a" * 40
LEDGER_INTEGRITY = "b" * 64
NOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)
IMAGE = "acrmobius7711564669.azurecr.io/opencanvas-api@sha256:" + "c" * 64


@dataclass(slots=True)
class _Clock:
    value: datetime
    monotonic_value: float = 0.0

    def now(self) -> datetime:
        return self.value

    def monotonic(self) -> float:
        return self.monotonic_value

    def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)
        self.monotonic_value += seconds


def _sample(
    clock: _Clock,
    *,
    deadline: datetime,
    runtime_graph: str = "d" * 64,
    maximum_cost: int = 20_607,
) -> terminal_lifecycle.LiveValidationSample:
    return terminal_lifecycle.LiveValidationSample(
        observed_at_utc=clock.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        runtime_graph_integrity_sha256=runtime_graph,
        private_address_sha256="e" * 64,
        private_dns_proved=True,
        tls_version="TLS1_3",
        api_live=True,
        api_ready=True,
        worker_ready=True,
        telemetry_ready=True,
        cleanup_armed=True,
        cleanup_deadline_utc=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        maximum_cost_usd_cents=maximum_cost,
        temporary_authority_absent=True,
    )


def _post_secret_payload() -> dict[str, JsonValue]:
    return {
        "apiDefinitionAuthoritative": True,
        "immutableImageDigest": IMAGE,
        "managedEnvironmentAuthoritative": True,
        "managedSecretCount": 11,
        "migrationDefinitionAuthoritative": True,
        "postgresqlAuthoritative": True,
        "redisAuthoritative": True,
        "scannerEvidenceIntegritySha256": "f" * 64,
        "secretValueAccessed": False,
        "telemetryDefinitionAuthoritative": True,
        "workerDefinitionAuthoritative": True,
    }


def _build(
    stage: str,
    payload: dict[str, JsonValue],
    previous: terminal_lifecycle.TerminalStageEvidence | None,
    *,
    offset: int,
) -> terminal_lifecycle.TerminalStageEvidence:
    return terminal_lifecycle.build_stage_evidence(
        stage=stage,
        repository_head=HEAD,
        ledger_integrity_sha256=LEDGER_INTEGRITY,
        started_at_utc=NOW + timedelta(seconds=offset),
        completed_at_utc=NOW + timedelta(seconds=offset + 1),
        payload=payload,
        previous=previous,
    )


def test_production_entry_point_and_overlay_expose_the_complete_terminal_chain() -> None:
    expected = (
        "pre-secret-provisioning",
        "private-path-verification",
        "publish-api-image",
        "reconcile-already-pushed-publication",
        "post-secret-provisioning",
        "migration-execution",
        "readiness-validation",
        "live-validation",
        "soak",
        "successful-closeout",
        "temporary-authority-revocation",
        "cleanup",
        "zero-residue-verification",
        "milestone-completion",
    )
    overlay = load_operation_overlay()
    assert expected == EXPECTED_LIFECYCLE_OPERATIONS
    assert tuple(item["id"] for item in overlay["lifecycleOperations"]) == expected
    assert (
        tuple(
            operation
            for operation in expected
            if operation != "reconcile-already-pushed-publication"
        )
        == lifecycle.LIFECYCLE_OPERATIONS
    )
    source = inspect.getsource(lifecycle.main)
    for symbol in (
        "_post_secret(",
        "_migration_stage(",
        "_readiness_stage(",
        "_live_validation_stage(",
        "_soak_stage(",
        "_successful_closeout(",
        "_cleanup(",
        "_zero_residue(",
        "_milestone_completion(",
        "_persist_terminal_stage(",
    ):
        assert symbol in source
    post_secret = next(
        item for item in overlay["lifecycleOperations"] if item["id"] == "post-secret-provisioning"
    )
    arguments = overlay["methodDefinitions"][post_secret["methodDefinition"]]["argumentVector"]
    assert arguments[arguments.index("--scanner-bridge-evidence") + 1] == (
        "{scannerBridgeEvidencePath}"
    )


def test_every_stage_artifact_is_serialized_and_accepted_by_its_real_consumer(
    tmp_path: Path,
) -> None:
    ledger: dict[str, JsonValue] = {
        "authorizationId": "m7.7-managed-binding-closeout-20260731",
        "ledgerIntegritySha256": LEDGER_INTEGRITY,
        "repositoryHead": HEAD,
    }
    payloads: list[tuple[str, dict[str, JsonValue]]] = [
        ("post-secret-provisioning", _post_secret_payload()),
        (
            "migration-execution",
            {
                "executionNameSha256": "1" * 64,
                "expectedRevision": terminal_lifecycle.MIGRATION_REVISION,
                "singleExecution": True,
                "terminalStatus": "Succeeded",
            },
        ),
        (
            "readiness-validation",
            {
                "apiRevisionSha256": "2" * 64,
                "immutableImageDigest": IMAGE,
                "privateIngressOnly": True,
                "telemetryRevisionSha256": "3" * 64,
                "workerRevisionSha256": "4" * 64,
            },
        ),
        (
            "live-validation",
            {
                "apiLive": True,
                "apiReady": True,
                "cleanupArmed": True,
                "cleanupDeadlineUtc": "2026-08-11T09:00:00Z",
                "maximumCostUsdCents": 20_607,
                "privateAddressSha256": "5" * 64,
                "privateDnsProved": True,
                "runtimeGraphIntegritySha256": "6" * 64,
                "runtimeMode": "live-staging",
                "telemetryReady": True,
                "temporaryAuthorityAbsent": True,
                "tlsVersion": "TLS1_3",
                "workerReady": True,
            },
        ),
        (
            "soak",
            {
                "cleanupDeadlineUtc": "2026-08-11T09:00:00Z",
                "cleanupReserveSeconds": 10_800,
                "durationSeconds": 5_400,
                "interrupted": False,
                "maximumCostUsdCents": 20_607,
                "resetRequired": False,
                "runtimeGraphIntegritySha256": "6" * 64,
                "sampleChainIntegritySha256": "7" * 64,
                "sampleCount": 91,
                "sampleIntervalSeconds": 60,
            },
        ),
    ]
    evidence: terminal_lifecycle.TerminalStageEvidence | None = None
    for offset, (stage, result) in enumerate(payloads):
        evidence = lifecycle._persist_terminal_stage(
            operation=stage,
            result=result,
            ledger=ledger,
            receipt_directory=tmp_path,
            started_at_utc=NOW + timedelta(seconds=offset * 2),
            completed_at_utc=NOW + timedelta(seconds=offset * 2 + 1),
        )
        assert evidence is not None
        assert (
            terminal_lifecycle.load_stage_evidence(
                terminal_lifecycle.stage_evidence_path(tmp_path, stage),
                expected_stage=stage,
                repository_head=HEAD,
                ledger_integrity_sha256=LEDGER_INTEGRITY,
            )
            == evidence
        )

    assert evidence is not None and evidence.stage == "soak"
    closeout_result: dict[str, JsonValue] = {
        "lifecycleTemporaryTagCount": 0,
        "proofJobResidueCount": 0,
        "publisherFinalizerResidueCount": 0,
        "requiredEvidenceChainIntegritySha256": evidence.integrity_sha256,
        "temporaryAssignmentCount": 0,
        "temporaryAuthorizationCount": 0,
        "temporaryCustomRoleCount": 0,
    }
    closeout = lifecycle._persist_terminal_stage(
        operation="successful-closeout",
        result=closeout_result,
        ledger=ledger,
        receipt_directory=tmp_path,
        started_at_utc=NOW + timedelta(seconds=10),
        completed_at_utc=NOW + timedelta(seconds=11),
    )
    assert closeout is not None
    authorization = lifecycle._issue_successful_cleanup_authorization(
        ledger=ledger,
        receipt_directory=tmp_path,
        closeout_evidence=closeout,
        issued_at_utc=NOW + timedelta(seconds=11),
    )
    terminal_lifecycle.validate_cleanup_authorization(
        authorization,
        authorization_id=str(ledger["authorizationId"]),
        repository_head=HEAD,
        resource_groups=(
            lifecycle.TARGET_GROUP,
            lifecycle.CLEANUP_GROUP,
            lifecycle.INFRASTRUCTURE_GROUP,
        ),
        now_utc=NOW + timedelta(seconds=12),
        closeout_evidence=closeout,
    )
    with pytest.raises(
        terminal_lifecycle.TerminalLifecycleError,
        match="terminal-stage-evidence-already-exists",
    ):
        terminal_lifecycle.write_cleanup_authorization(tmp_path, authorization)
    with pytest.raises(
        terminal_lifecycle.TerminalLifecycleError,
        match="cleanup-authorization-stale",
    ):
        terminal_lifecycle.validate_cleanup_authorization(
            authorization,
            authorization_id=str(ledger["authorizationId"]),
            repository_head=HEAD,
            resource_groups=(
                lifecycle.TARGET_GROUP,
                lifecycle.CLEANUP_GROUP,
                lifecycle.INFRASTRUCTURE_GROUP,
            ),
            now_utc=NOW + timedelta(hours=1, seconds=11),
            closeout_evidence=closeout,
        )
    (tmp_path / terminal_lifecycle.CLEANUP_AUTHORIZATION_FILE).unlink()
    cleanup_result: dict[str, JsonValue] = {
        "authorizationMode": "successful-closeout",
        "resourceGroupDeleteCount": 3,
        "softDeletedVaultAbsent": True,
        "temporaryAuthorityRevoked": True,
    }
    cleanup = lifecycle._persist_terminal_stage(
        operation="cleanup",
        result=cleanup_result,
        ledger=ledger,
        receipt_directory=tmp_path,
        started_at_utc=NOW + timedelta(seconds=12),
        completed_at_utc=NOW + timedelta(seconds=13),
    )
    assert cleanup is not None
    zero_result: dict[str, JsonValue] = {
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
    }
    zero = lifecycle._persist_terminal_stage(
        operation="zero-residue-verification",
        result=zero_result,
        ledger=ledger,
        receipt_directory=tmp_path,
        started_at_utc=NOW + timedelta(seconds=14),
        completed_at_utc=NOW + timedelta(seconds=15),
    )
    assert zero is not None
    completion = lifecycle._persist_terminal_stage(
        operation="milestone-completion",
        result={
            "marker": terminal_lifecycle.MILESTONE_COMPLETION_MARKER,
            "milestone78Started": False,
            "provisioningAuthorized": False,
            "zeroResidueEvidenceIntegritySha256": zero.integrity_sha256,
        },
        ledger=ledger,
        receipt_directory=tmp_path,
        started_at_utc=NOW + timedelta(seconds=16),
        completed_at_utc=NOW + timedelta(seconds=17),
    )
    assert completion is not None
    assert completion.status == terminal_lifecycle.MILESTONE_COMPLETION_MARKER


def test_production_stage_consumes_predecessor_before_downstream_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger: dict[str, JsonValue] = {
        "ledgerIntegritySha256": LEDGER_INTEGRITY,
        "repositoryHead": HEAD,
    }
    monkeypatch.setattr(
        terminal_lifecycle_adapter,
        "migration_job_ready",
        lambda _subscription: pytest.fail(
            "migration execution must remain unreachable before predecessor admission"
        ),
    )
    with pytest.raises(lifecycle.LifecycleError, match="terminal-stage-predecessor-missing"):
        lifecycle._migration_stage(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
        )

    post_secret = _build("post-secret-provisioning", _post_secret_payload(), None, offset=0)
    path = terminal_lifecycle.write_stage_evidence(tmp_path, post_secret)
    value = json.loads(path.read_text(encoding="utf-8"))
    cast(dict[str, JsonValue], value["payload"])["postgresqlAuthoritative"] = False
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="terminal-stage-evidence-integrity-invalid"):
        lifecycle._migration_stage(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
        )


def test_migration_start_reconciles_ambiguous_response_without_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_name = "caj-mobius77-migration-execution"
    inventory_reads = 0
    start_count = 0

    def run(command: tuple[str, ...], **_kwargs: object) -> JsonValue:
        nonlocal inventory_reads, start_count
        if command[3:5] == ("execution", "list"):
            inventory_reads += 1
            if inventory_reads == 1:
                return []
            return [{"name": execution_name, "status": "Running"}]
        if command[3] == "start":
            start_count += 1
            raise lifecycle.AzureCommandError("gatewaytimeout")
        if command[3:5] == ("execution", "show"):
            return {"name": execution_name, "status": "Succeeded"}
        pytest.fail(f"unexpected command: {command}")

    monkeypatch.setattr(lifecycle, "_run", run)
    monkeypatch.setattr(terminal_lifecycle_adapter.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        terminal_lifecycle_adapter.time,
        "sleep",
        lambda _seconds: pytest.fail("reconciled execution should not be replayed"),
    )

    assert terminal_lifecycle_adapter.migration_job_ready("opaque-subscription") == execution_name
    assert start_count == 1
    assert inventory_reads == 2


def test_live_validation_probes_exact_private_ingress_hostnames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deadline = NOW + timedelta(hours=4)
    probes: list[str] = []

    monkeypatch.setattr(lifecycle, "_utc_now", lambda: NOW)
    monkeypatch.setattr(
        lifecycle,
        "_read_current_transient_state",
        lambda _path, *, ledger: {
            "cleanupAtUtc": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temporaryKeyVaultAssignmentId": None,
            "temporaryRegistryAssignmentId": None,
        },
    )
    monkeypatch.setattr(lifecycle, "_verify_cleanup_control", lambda *_args: "binding")
    monkeypatch.setattr(
        terminal_lifecycle_adapter,
        "private_revision_ready",
        lambda _subscription: {
            "ca-mobius77-api": "api-revision",
            "ca-mobius77-telemetry": "telemetry-revision",
            "ca-mobius77-worker": "worker-revision",
        },
    )
    monkeypatch.setattr(lifecycle, "_reconcile_published_api_image", lambda **_kwargs: IMAGE)
    monkeypatch.setattr(
        lifecycle,
        "_container_apps_private_dns_projection",
        lambda _subscription: (
            "delightfulgrass-bfebe48e.southcentralus.azurecontainerapps.io",
            "10.77.0.87",
        ),
    )

    def probe(hostname: str, *, expected_address: str) -> tuple[str, str]:
        assert expected_address == "10.77.0.87"
        probes.append(hostname)
        return "e" * 64, "TLS1_3"

    monkeypatch.setattr(terminal_lifecycle_adapter, "_private_tls_projection", probe)
    monkeypatch.setattr(lifecycle, "_verified_cost", lambda: (3_110, 20_607))

    sample = terminal_lifecycle_adapter.live_validation_sample(
        ledger={"ledgerIntegritySha256": LEDGER_INTEGRITY, "repositoryHead": HEAD},
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    domain = "delightfulgrass-bfebe48e.southcentralus.azurecontainerapps.io"
    assert probes == [
        f"ca-mobius77-api.internal.{domain}",
        f"ca-mobius77-telemetry.internal.{domain}",
    ]
    assert sample.api_ready is True
    assert sample.telemetry_ready is True


def test_uninterrupted_soak_runs_exactly_90_minutes_and_finishes_progress(
    tmp_path: Path,
) -> None:
    clock = _Clock(NOW)
    deadline = NOW + timedelta(hours=4)
    documents: list[dict[str, JsonValue]] = []
    result = terminal_lifecycle.run_uninterrupted_soak(
        repository_head=HEAD,
        ledger_integrity_sha256=LEDGER_INTEGRITY,
        cleanup_deadline_utc=deadline,
        sample=lambda: _sample(clock, deadline=deadline),
        clock=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        progress=lambda value: documents.append(dict(value)),
    )

    assert result.completed_at_utc - result.started_at_utc == timedelta(minutes=90)
    assert result.payload["durationSeconds"] == 5_400
    assert result.payload["sampleCount"] == 91
    assert documents[-1]["status"] == "COMPLETED"
    terminal_lifecycle.write_soak_progress(tmp_path / "progress.json", documents[-1])
    written = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert written["status"] == "COMPLETED"
    assert written["resetRequired"] is False


def test_soak_cadence_accounts_for_nonzero_live_readback_duration() -> None:
    clock = _Clock(NOW)
    deadline = NOW + timedelta(hours=4)

    def delayed_sample() -> terminal_lifecycle.LiveValidationSample:
        clock.sleep(20)
        return _sample(clock, deadline=deadline)

    result = terminal_lifecycle.run_uninterrupted_soak(
        repository_head=HEAD,
        ledger_integrity_sha256=LEDGER_INTEGRITY,
        cleanup_deadline_utc=deadline,
        sample=delayed_sample,
        clock=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        progress=lambda _value: None,
    )

    assert result.payload["sampleCount"] == 91
    assert result.completed_at_utc - result.started_at_utc == timedelta(minutes=90, seconds=20)


def test_soak_interruption_or_graph_change_invalidates_the_whole_run() -> None:
    clock = _Clock(NOW)
    deadline = NOW + timedelta(hours=4)
    documents: list[dict[str, JsonValue]] = []
    calls = 0

    def changing_sample() -> terminal_lifecycle.LiveValidationSample:
        nonlocal calls
        calls += 1
        return _sample(
            clock,
            deadline=deadline,
            runtime_graph=("d" if calls == 1 else "e") * 64,
        )

    with pytest.raises(
        terminal_lifecycle.TerminalLifecycleError,
        match="soak-runtime-graph-changed",
    ):
        terminal_lifecycle.run_uninterrupted_soak(
            repository_head=HEAD,
            ledger_integrity_sha256=LEDGER_INTEGRITY,
            cleanup_deadline_utc=deadline,
            sample=changing_sample,
            clock=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            progress=lambda value: documents.append(dict(value)),
        )
    assert documents[-1]["status"] == "INVALIDATED"
    assert documents[-1]["resetRequired"] is True
    assert documents[-1]["failureCode"] == "soak-runtime-graph-changed"


@pytest.mark.parametrize(
    ("deadline", "maximum_cost", "error"),
    [
        (NOW + timedelta(minutes=179), 20_607, "soak-cleanup-reserve-insufficient"),
        (NOW + timedelta(hours=4), 25_001, "soak-cost-ceiling-exceeded"),
    ],
)
def test_soak_rejects_expired_reserve_or_cost_ceiling(
    deadline: datetime, maximum_cost: int, error: str
) -> None:
    clock = _Clock(NOW)
    with pytest.raises(terminal_lifecycle.TerminalLifecycleError, match=error):
        terminal_lifecycle.run_uninterrupted_soak(
            repository_head=HEAD,
            ledger_integrity_sha256=LEDGER_INTEGRITY,
            cleanup_deadline_utc=deadline,
            sample=lambda: _sample(clock, deadline=deadline, maximum_cost=maximum_cost),
            clock=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            progress=lambda _value: None,
        )


def test_stage_and_cleanup_evidence_reject_tamper_residue_expiry_and_replay(
    tmp_path: Path,
) -> None:
    post_secret = _build("post-secret-provisioning", _post_secret_payload(), None, offset=0)
    terminal_lifecycle.write_stage_evidence(tmp_path, post_secret)
    tampered = json.loads(json.dumps(post_secret.canonical()))
    cast(dict[str, JsonValue], tampered["payload"])["postgresqlAuthoritative"] = False
    with pytest.raises(
        terminal_lifecycle.TerminalLifecycleError,
        match="terminal-stage-evidence-integrity-invalid",
    ):
        terminal_lifecycle.stage_evidence_from_mapping(tampered)
    with pytest.raises(
        terminal_lifecycle.TerminalLifecycleError,
        match="terminal-stage-evidence-already-exists",
    ):
        terminal_lifecycle.write_stage_evidence(tmp_path, post_secret)

    migration = _build(
        "migration-execution",
        {
            "executionNameSha256": "1" * 64,
            "expectedRevision": terminal_lifecycle.MIGRATION_REVISION,
            "singleExecution": True,
            "terminalStatus": "Succeeded",
        },
        post_secret,
        offset=2,
    )
    bad_migration = dict(migration.payload)
    bad_migration["terminalStatus"] = "Failed"
    with pytest.raises(
        terminal_lifecycle.TerminalLifecycleError, match="migration-terminal-status-invalid"
    ):
        _build("migration-execution", bad_migration, post_secret, offset=2)

    with pytest.raises(terminal_lifecycle.TerminalLifecycleError, match="closeout-residue-present"):
        terminal_lifecycle._validate_closeout(
            {
                "lifecycleTemporaryTagCount": 0,
                "proofJobResidueCount": 1,
                "publisherFinalizerResidueCount": 0,
                "requiredEvidenceChainIntegritySha256": "1" * 64,
                "temporaryAssignmentCount": 0,
                "temporaryAuthorizationCount": 0,
                "temporaryCustomRoleCount": 0,
            }
        )
