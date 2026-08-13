from __future__ import annotations

import asyncio
import hashlib

# The API test root is normally the import root; this focused infrastructure contract
# also imports the repository-level campaign package after adding that explicit root.
# ruff: noqa: E402
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from infra.milestone_7_8 import operator as campaign_operator
from infra.milestone_7_8 import prepare
from infra.milestone_7_8.campaign import (
    HARD_CEILING,
    ORDER,
    RESIDUE_KEYS,
    CampaignConfig,
    CampaignError,
    CleanupBinding,
    CostItem,
    Ledger,
    Lifecycle,
    Phase,
    SimulatedRunner,
    terminal_receipt,
)
from infra.milestone_7_8.operator import (
    OPERATION_PHASE,
    command_plan,
    execute_commands,
    validate_cleanup_deployment,
    validate_cleanup_readback,
    verify_zero_residue,
)
from opencanvas_api.db.principal_manifest import (
    CAMPAIGN_ENV,
    CURRENT_PRINCIPAL_ID_ENV,
    GENERATION_ENV,
    MANIFEST_ENV,
    PrincipalManifestError,
    PrincipalSlot,
    load_principal_manifest,
)
from scripts import bootstrap_postgres, managed_postgres_evidence, migrate_and_grant

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def _object_id(value: int) -> str:
    return f"00000000-0000-4000-8000-{value:012d}"


def _manifest(
    *,
    campaign: str = "mobius78-pg-proof",
    generation: str = "g1-aabbccddeeff",
    names: dict[str, str] | None = None,
) -> dict[str, object]:
    labels = names or {slot.value: f"id-m78-proof-{slot.value}" for slot in PrincipalSlot}
    return {
        "version": "m7.8-principal-manifest-v1",
        "campaignId": campaign,
        "generationId": generation,
        "subscriptionCorrelation": "a" * 16,
        "principals": {
            slot.value: {
                "role": slot.value,
                "name": labels[slot.value],
                "objectId": _object_id(index + 1),
            }
            for index, slot in enumerate(PrincipalSlot)
        },
    }


def _set_manifest(monkeypatch: pytest.MonkeyPatch, value: dict[str, object]) -> None:
    monkeypatch.setenv(MANIFEST_ENV, json.dumps(value))
    monkeypatch.setenv(CAMPAIGN_ENV, str(value["campaignId"]))
    monkeypatch.setenv(GENERATION_ENV, str(value["generationId"]))


def _config(**changes: object) -> CampaignConfig:
    values: dict[str, object] = {
        "campaign_id": "mobius78-pg-proof",
        "generation_id": "g1-aabbccddeeff",
        "subscription_correlation": "a" * 16,
        "tenant_correlation": "b" * 16,
        "target_resource_group": "rg-m78-aabbccddee-target",
        "cleanup_resource_group": "rg-m78-aabbccddee-cleanup",
        "target_region": "centralus",
        "cleanup_region": "westus",
        "postgres_region": "centralus",
        "cleanup_deadline_utc": "2030-01-01T04:00:00Z",
        "conservative_estimate_usd": "25.6832",
        "contingency_percent": "25",
        "resource_items": (CostItem("bounded-campaign", "5.13664", 4),),
        "principal_manifest_sha256": "c" * 64,
        "image_digest": None,
    }
    values.update(changes)
    return CampaignConfig(**values)  # type: ignore[arg-type]


def test_campaign_derived_principals_and_alternative_generation_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _manifest()
    _set_manifest(monkeypatch, first)
    assert (
        load_principal_manifest().principals[PrincipalSlot.MIGRATION].name
        == "id-m78-proof-migration"
    )
    second = _manifest(campaign="mobius78-pg-other", generation="g2-112233aabbcc")
    _set_manifest(monkeypatch, second)
    assert load_principal_manifest().generation_id == "g2-112233aabbcc"


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "swapped", "malformed", "stale", "unknown"]
)
def test_invalid_principal_manifests_fail_closed(
    monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    value = _manifest()
    principals = value["principals"]
    assert isinstance(principals, dict)
    if defect == "missing":
        principals.pop("worker")
    elif defect == "duplicate":
        principals["worker"]["objectId"] = principals["api"]["objectId"]  # type: ignore[index]
    elif defect == "swapped":
        principals["worker"]["role"] = "api"  # type: ignore[index]
    elif defect == "malformed":
        principals["api"]["name"] = 'bad"role'  # type: ignore[index]
    elif defect == "stale":
        value["generationId"] = "g2-112233aabbcc"
    else:
        value["unexpected"] = True
    _set_manifest(monkeypatch, value)
    if defect == "stale":
        monkeypatch.setenv(GENERATION_ENV, "g1-aabbccddeeff")
    with pytest.raises(PrincipalManifestError):
        load_principal_manifest()


def test_retained_labels_have_no_special_case(monkeypatch: pytest.MonkeyPatch) -> None:
    labels = {
        "bootstrap": "id-mobius77-db-admin",
        "migration": "id-mobius77-db-migration",
        "api": "id-mobius77-api",
        "worker": "id-mobius77-worker",
        "evidence": "id-mobius77-evidence",
        "cleanup": "id-mobius77-cleanup",
    }
    _set_manifest(monkeypatch, _manifest(names=labels))
    manifest = load_principal_manifest()
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, _object_id(2))
    manifest.require_current(PrincipalSlot.MIGRATION, current_name=labels["migration"])
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, _object_id(3))
    with pytest.raises(PrincipalManifestError):
        manifest.require_current(PrincipalSlot.MIGRATION, current_name=labels["migration"])


def test_bootstrap_and_migration_consume_same_semantic_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_manifest(monkeypatch, _manifest())
    contracts = bootstrap_postgres._principal_contracts()
    assert [item.name for item in contracts] == [
        "id-m78-proof-migration",
        "id-m78-proof-api",
        "id-m78-proof-worker",
        "id-m78-proof-evidence",
    ]
    assert migrate_and_grant._principals() == (
        "id-m78-proof-migration",
        "id-m78-proof-api",
        "id-m78-proof-worker",
    )


@pytest.mark.parametrize(
    ("estimate", "accepted"),
    [("49.99", True), ("50.00", True), ("50.01", False)],
)
def test_cost_ceiling_boundaries(estimate: str, accepted: bool) -> None:
    config = _config(
        conservative_estimate_usd=estimate,
        resource_items=(CostItem("bounded", "9.998", 4),),
    )
    if accepted:
        config.validate()
        assert Decimal(estimate) <= HARD_CEILING
    else:
        with pytest.raises(CampaignError, match="ceiling"):
            config.validate()


def test_contingency_deadline_and_generation_limits() -> None:
    with pytest.raises(CampaignError, match="contingency"):
        _config(contingency_percent="24.99").validate()
    with pytest.raises(CampaignError, match="resource-group scope"):
        _config(target_resource_group="production").validate()
    with pytest.raises(CampaignError, match="expired"):
        _config(cleanup_deadline_utc="2020-01-01T00:00:00Z").validate()
    ledger = Ledger("mobius78-pg-proof", "g1-aabbccddeeff")
    ledger.bind_deadline("2030-01-01T04:00:00Z")
    with pytest.raises(CampaignError, match="extension"):
        ledger.bind_deadline("2030-01-01T04:01:00Z")
    for phase in ORDER[1 : ORDER.index(Phase.BILLABLE_STARTED) + 1]:
        ledger.transition(phase, NOW)
    with pytest.raises(CampaignError, match="generation"):
        ledger.resource_generation_count = 1
        ledger.phase = Phase.CLEANUP_VERIFIED.value
        ledger.transition(Phase.BILLABLE_STARTED, NOW)
    ledger.record_image("sha256:" + "a" * 64, built=True)
    ledger.record_image_scan("sha256:" + "a" * 64, "c" * 64)
    with pytest.raises(CampaignError, match="second image"):
        ledger.record_image("sha256:" + "b" * 64, built=True)
    with pytest.raises(CampaignError, match="second image admission"):
        ledger.record_image_scan("sha256:" + "a" * 64, "d" * 64)


def test_full_lifecycle_reaches_sanitized_zero_residue() -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    result = Lifecycle(config, ledger, SimulatedRunner()).run_simulation(now=NOW)
    receipt = terminal_receipt(result)
    assert result.phase == Phase.FINALIZED
    assert result.resource_generation_count == result.image_generation_count == 1
    assert set(result.residue) == set(RESIDUE_KEYS)
    assert set(result.residue.values()) == {0}
    assert receipt["status"] == "zero-residue"
    assert config.campaign_id not in json.dumps(receipt)


@pytest.mark.parametrize("failed_at", ORDER[1:-1])
def test_every_lifecycle_phase_failure_is_bounded(failed_at: Phase) -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    result = Lifecycle(config, ledger, SimulatedRunner()).fail_and_cleanup(failed_at, now=NOW)
    if ORDER.index(failed_at) < ORDER.index(Phase.SCOPE_CREATED):
        assert result.cleanup_started_utc is None
    else:
        assert result.phase == Phase.FINALIZED
        assert set(result.residue.values()) == {0}


def test_resume_and_cleanup_binding_reject_substitution() -> None:
    config = _config()
    with pytest.raises(CampaignError, match="resume"):
        Lifecycle(config, Ledger(config.campaign_id, "g2-112233aabbcc"), SimulatedRunner())
    valid = CleanupBinding(
        config.campaign_id,
        config.generation_id,
        config.subscription_correlation,
        config.target_resource_group,
        config.cleanup_resource_group,
        "d" * 64,
        config.cleanup_deadline_utc,
        "50.00",
        1,
    )
    valid.validate(config)
    with pytest.raises(CampaignError, match="cleanup binding"):
        replace(valid, schedule_count=2).validate(config)


def test_evidence_contract_is_complete_and_redacted() -> None:
    required = managed_postgres_evidence.REQUIRED_PROOFS
    assert {
        "catalog.runtime-grants",
        "recovery.failover",
        "idempotency.canvas",
        "idempotency.edge",
        "tenant.post-failover",
        "tenant.forged-evidence-bundle",
        "operations.backup",
    } < required
    source = (REPOSITORY_ROOT / "apps/api/scripts/managed_postgres_evidence.py").read_text()
    assert "password" not in managed_postgres_evidence._digest({"password": "do-not-print"})
    assert "TODO" not in source and "NotImplemented" not in source


def _control_plane_evidence() -> dict[str, object]:
    return {
        "primaryZone": "1",
        "standbyZone": "2",
        "haMode": "ZoneRedundant",
        "maintenanceDay": 0,
        "maintenanceHour": 7,
        "storageGiB": 64,
        "storageTier": "P6",
        "backupRetentionDays": 7,
        "geoBackup": False,
        "latencyP95Ms": 12.5,
        "recoverySeconds": 42.0,
        "failoverObserved": True,
        "credentialRecoveryObserved": True,
        "postFailoverTenantIsolationObserved": True,
        "azureReservedConnections": 5,
        "poolCeilings": 50,
        "rolloutOverlap": 10,
        "operatorConsumers": 5,
        "observedPeak": 40,
        "safetyReserve": 20,
        "maxConnections": 100,
    }


def _operator_control_plane_evidence() -> dict[str, object]:
    return {
        key: value
        for key, value in _control_plane_evidence().items()
        if key
        not in {
            "recoverySeconds",
            "failoverObserved",
            "credentialRecoveryObserved",
            "postFailoverTenantIsolationObserved",
        }
    }


def test_control_plane_evidence_capacity_and_types_fail_closed() -> None:
    evidence = _control_plane_evidence()
    assertions = managed_postgres_evidence.validate_control_plane_evidence(json.dumps(evidence))
    assert assertions and all(item.passed for item in assertions)
    evidence["maxConnections"] = 89
    with pytest.raises(managed_postgres_evidence.EvidenceError):
        managed_postgres_evidence.validate_control_plane_evidence(json.dumps(evidence))
    evidence = _control_plane_evidence()
    evidence["maintenanceDay"] = True
    with pytest.raises(managed_postgres_evidence.EvidenceError):
        managed_postgres_evidence.validate_control_plane_evidence(json.dumps(evidence))


def test_image_scan_receipt_is_bound_before_workload_deployment(tmp_path: Path) -> None:
    runtime = _runtime()
    digest = "sha256:" + "e" * 64
    receipt = {
        "version": "m7.8-image-admission-v1",
        "sourceHead": runtime["sourceHead"],
        "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
        "imageDigest": digest,
        "scanner": "approved-image-admission-scanner",
        "scannerVersion": "1.0",
        "scannedAtUtc": "2030-01-01T01:00:00Z",
        "result": "passed",
        "criticalFindings": 0,
        "highFindings": 0,
    }
    path = tmp_path / "image-scan.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert (
        campaign_operator.load_image_scan_evidence(path, digest=digest, runtime=runtime)
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    receipt["highFindings"] = 1
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError, match="policy"):
        campaign_operator.load_image_scan_evidence(path, digest=digest, runtime=runtime)


def test_deployed_principal_manifest_matches_prepared_semantic_plan() -> None:
    names = {
        "bootstrap": "id-m78-proof-bootstrap",
        "migration": "id-m78-proof-migration",
        "api": "id-m78-proof-api",
        "worker": "id-m78-proof-worker",
        "evidence": "id-m78-proof-evidence",
        "cleanup": "cleanup-proof",
    }
    planned = {
        "campaignId": "mobius78-pg-proof",
        "generationId": "g1-aabbccddeeff",
        "principals": {
            key: names[key] for key in ("bootstrap", "migration", "api", "worker", "evidence")
        },
        "cleanup": names["cleanup"],
    }
    config = _config(
        principal_manifest_sha256=hashlib.sha256(
            json.dumps(planned, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )
    manifest = {
        "version": "m7.8-principal-manifest-v1",
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "principals": {
            slot: {"role": slot, "name": name, "objectId": _object_id(index)}
            for index, (slot, name) in enumerate(names.items(), 1)
        },
    }
    outputs: dict[str, object] = {
        "campaignBinding": {
            "campaignId": config.campaign_id,
            "generationId": config.generation_id,
            "subscriptionCorrelation": config.subscription_correlation,
            "cleanupDeadlineUtc": config.cleanup_deadline_utc,
            "maximumHours": 4,
            "costCeilingCents": 5000,
            "cleanupResourceGroupName": config.cleanup_resource_group,
            "principalManifest": json.dumps(manifest),
        }
    }
    campaign_operator.validate_deployed_principal_manifest(outputs, config)
    manifest["principals"]["worker"]["objectId"] = _object_id(3)  # type: ignore[index]
    outputs["campaignBinding"]["principalManifest"] = json.dumps(manifest)  # type: ignore[index]
    with pytest.raises(CampaignError, match="not distinct"):
        campaign_operator.validate_deployed_principal_manifest(outputs, config)


def test_fake_postgres_adapter_proves_campaign_login_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSettings:
        def require_database_role(self, _role: object) -> None:
            return None

    class DeniedContext:
        async def __aenter__(self) -> None:
            raise ConnectionError("synthetic login denied")

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> DeniedContext:
            return DeniedContext()

    class FakeDatabase:
        engine = FakeEngine()

        @classmethod
        def from_settings(cls, *_args: object, **_kwargs: object) -> FakeDatabase:
            return cls()

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(managed_postgres_evidence, "get_settings", FakeSettings)
    monkeypatch.setattr(managed_postgres_evidence, "Database", FakeDatabase)
    assertions = asyncio.run(managed_postgres_evidence.credential_denial_assertion())
    assert [item.code for item in assertions] == ["recovery.credential-revocation"]


def test_new_bicep_has_no_executable_milestone_7_7_coupling() -> None:
    root = REPOSITORY_ROOT / "infra/milestone_7_8"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.*")
        if path.suffix in {".bicep", ".json", ".ps1", ".py"}
    )
    assert "id-mobius77" not in combined
    assert "milestone_7_7" not in combined
    assert "2026-08-09" not in combined
    assert "TODO" not in combined
    assert (root / "main.bicep").is_file()
    assert (root / "cleanup.bicep").is_file()
    cleanup = (root / "cleanup.bicep").read_text(encoding="utf-8")
    assert cleanup.count("./modules/cleanup-rbac.bicep") == 4
    assert "b24988ac-6180-42a0-ab88-20f7382dd24c" in cleanup
    assert "f58310d9-a9f6-439a-9e8d-f62e7b41a168" in cleanup


def _runtime() -> dict[str, str]:
    return {
        "subscriptionId": _object_id(100),
        "sourceHead": "a" * 40,
        "canonicalBuildInputSha256": "b" * 64,
        "dockerfileSha256": "c" * 64,
        "cleanupScriptSha256": "d" * 64,
        "cleanupDeploymentName": "m78-cleanup",
        "campaignDeploymentName": "m78-campaign",
        "automationAccountName": "aa-m78-proof",
        "runbookName": "Remove-M78Campaign-proof",
        "scheduleName": "m78-deadline-proof",
        "bootstrapJobName": "job-proof-bootstrap",
        "migrationJobName": "job-proof-migration",
        "workerJobName": "job-proof-worker",
        "evidenceJobName": "job-proof-evidence",
        "apiProbeJobName": "job-proof-probe-api",
        "workerProbeJobName": "job-proof-probe-worker",
        "migrationProbeJobName": "job-proof-probe-migration",
        "recoveryJobName": "job-proof-credential-recovery",
        "recoveryRestoreJobName": "job-proof-credential-restore",
        "postgresServerName": "pg-m78-proof",
        "registryName": "acrm78proof",
        "logAnalyticsWorkspaceName": "law-m78-proof",
        "resourceGroupName": "rg-m78-aabbccddee-target",
        "cleanupResourceGroupName": "rg-m78-aabbccddee-cleanup",
        "cleanupParametersFile": "runtime/m78.cleanup.parameters.json",
        "campaignParametersFile": "runtime/m78.campaign.parameters.json",
    }


def test_operator_runbook_maps_every_phase_to_implemented_commands() -> None:
    runtime = _runtime()
    config = _config()
    for operation in OPERATION_PHASE:
        commands = command_plan(operation, config, runtime)
        assert isinstance(commands, tuple)
        assert all(command and all(part for part in command) for command in commands)
    evidence = command_plan("evidence", config, runtime)
    rendered = "\n".join(" ".join(command) for command in evidence)
    assert "--failover Forced" in rendered
    assert "--phase application" in rendered
    assert "--phase operations" in rendered
    scope = " ".join(command_plan("scope-create", config, runtime)[0])
    assert "mobius.milestone=7.8" in scope
    assert f"mobius.cleanup-deadline-utc={config.cleanup_deadline_utc}" in scope
    assert "mobius.cost-ceiling-cents=5000" in scope


def _command_result(value: object) -> dict[str, object]:
    return {"exitCode": 0, "stdout": json.dumps(value), "stderr": ""}


def _cleanup_deployment_result(config: CampaignConfig) -> dict[str, object]:
    values = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "targetResourceGroupName": config.target_resource_group,
        "cleanupResourceGroupName": config.cleanup_resource_group,
        "cleanupPrincipalId": _object_id(201),
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "costCeilingCents": 5000,
        "scheduleCount": 1,
    }
    return _command_result(
        {"properties": {"outputs": {key: {"value": value} for key, value in values.items()}}}
    )


def test_cleanup_binding_and_readback_reject_substitution() -> None:
    config = _config()
    runtime = _runtime()
    deployment = _cleanup_deployment_result(config)
    validate_cleanup_deployment(deployment, config)
    results = [
        deployment,
        _command_result({"identity": {"principalId": _object_id(201)}}),
        _command_result({"name": runtime["runbookName"], "state": "Published"}),
        _command_result(
            {
                "name": runtime["scheduleName"],
                "frequency": "OneTime",
                "startTime": config.cleanup_deadline_utc,
            }
        ),
        _command_result(
            [
                {
                    "name": "one-bound-job-schedule",
                    "runbook": {"name": runtime["runbookName"]},
                    "schedule": {"name": runtime["scheduleName"]},
                }
            ]
        ),
        {
            "exitCode": 0,
            "stdout": "cleanup-content",
            "stderr": "",
        },
    ]
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    validate_cleanup_readback(results, config, runtime)
    results[3] = _command_result(
        {
            "name": runtime["scheduleName"],
            "frequency": "OneTime",
            "startTime": "2030-01-01T04:01:00Z",
        }
    )
    with pytest.raises(CampaignError, match="readback drifted"):
        validate_cleanup_readback(results, config, runtime)


def test_fake_azure_job_adapter_waits_for_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAzureRunner:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            self.commands.append(command)
            if "execution" in command and "show" in command:
                return _command_result(
                    {"name": "execution-one", "properties": {"status": "Succeeded"}}
                )
            return _command_result({"name": "execution-one", "properties": {"status": "Running"}})

    monkeypatch.setattr(campaign_operator.time, "sleep", lambda _seconds: None)
    runner = FakeAzureRunner()
    command = (
        "az",
        "containerapp",
        "job",
        "start",
        "--resource-group",
        "rg-proof",
        "--name",
        "job-proof",
        "--output",
        "json",
    )
    result = execute_commands(runner, (command,))  # type: ignore[arg-type]
    assert result[0]["terminalStatus"] == "Succeeded"
    assert len(runner.commands) == 2


def test_managed_evidence_sequence_derives_recovery_and_persists_receipt(
    tmp_path: Path,
) -> None:
    class FakeEvidenceRunner:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            if command[:4] == ("az", "containerapp", "job", "start"):
                return _command_result(
                    {
                        "name": "execution-"
                        + hashlib.sha256(" ".join(command).encode()).hexdigest()[:8],
                        "status": "Succeeded",
                    }
                )
            return _command_result({"status": "Succeeded"})

    runtime = _runtime()
    config = _config(image_digest="sha256:" + "e" * 64)
    control = _operator_control_plane_evidence()
    commands = command_plan(
        "evidence",
        config,
        runtime,
        control_plane_evidence="<derived-after-successful-managed-probes>",
    )
    results = campaign_operator.execute_evidence_commands(
        FakeEvidenceRunner(),
        commands,
        control,  # type: ignore[arg-type]
    )
    assert len(results) == 12
    path = tmp_path / "managed-evidence-execution.json"
    campaign_operator.persist_evidence_execution_receipt(
        path,
        config=config,
        runtime=runtime,
        commands=commands,
        results=results,
        control_plane_evidence=control,
    )
    campaign_operator.validate_evidence_execution_receipt(
        path,
        config=config,
        runtime=runtime,
        control_plane_evidence=control,
    )
    assert "<derived-after" not in path.read_text(encoding="utf-8")


def test_zero_residue_requires_all_control_plane_reads_to_be_empty() -> None:
    results = [
        _command_result(False),
        _command_result(False),
        _command_result([]),
        _command_result([]),
    ]
    assert set(verify_zero_residue(results).values()) == {0}
    results[2] = _command_result([{"type": "campaign-residue"}])
    with pytest.raises(CampaignError, match="nonzero"):
        verify_zero_residue(results)


def test_resume_ledger_rejects_substituted_phase() -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.phase = Phase.CORRELATED.value
    with pytest.raises(CampaignError, match="transition chain"):
        ledger.validate_resume(config)


def test_prepare_creates_one_private_restart_safe_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subscription = _object_id(101)
    tenant = _object_id(102)
    output = tmp_path / "runtime"
    monkeypatch.setenv("M78_SUBSCRIPTION_ID", subscription)
    monkeypatch.setenv("M78_TENANT_ID", tenant)
    git_values = {
        ("status", "--porcelain=v1"): "",
        ("branch", "--show-current"): "milestone-7-8-production-readiness-audit-local",
        (
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        ): "",
        ("stash", "list", "--format=%H"): "\n".join(str(index) for index in range(5)),
        ("rev-parse", "HEAD"): "a" * 40,
    }
    monkeypatch.setattr(prepare, "_git", lambda *args: git_values[args])
    monkeypatch.setattr(
        prepare,
        "canonical_snapshot",
        lambda _treeish: {
            "buildInputSha256": "b" * 64,
            "dockerfileSha256": "c" * 64,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare", "--campaign-id", "mobius78-managed-proof", "--output", str(output)],
    )
    assert prepare.main() == 0
    stdout = capsys.readouterr().out
    assert subscription not in stdout and tenant not in stdout
    config = CampaignConfig.from_json(output / "campaign.json")
    assert config.campaign_id == "mobius78-managed-proof"
    runtime_path = output / "runtime.json"
    runtime = campaign_operator.load_runtime(runtime_path)
    campaign_operator.validate_prepared_bundle(runtime_path, runtime, config)
    assert set(json.loads(runtime_path.read_text())) == {
        *{
            "subscriptionId",
            "sourceHead",
            "canonicalBuildInputSha256",
            "dockerfileSha256",
            "cleanupScriptSha256",
            "cleanupDeploymentName",
            "campaignDeploymentName",
            "automationAccountName",
            "runbookName",
            "scheduleName",
            "bootstrapJobName",
            "migrationJobName",
            "workerJobName",
            "evidenceJobName",
            "apiProbeJobName",
            "workerProbeJobName",
            "migrationProbeJobName",
            "recoveryJobName",
            "recoveryRestoreJobName",
            "postgresServerName",
            "registryName",
            "logAnalyticsWorkspaceName",
            "resourceGroupName",
            "cleanupResourceGroupName",
            "cleanupParametersFile",
            "campaignParametersFile",
        }
    }
    cleanup_path = output / "cleanup.parameters.json"
    cleanup = json.loads(cleanup_path.read_text())
    cleanup["parameters"]["targetResourceGroupName"]["value"] = "rg-m78-0000000000-target"
    cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")
    with pytest.raises(CampaignError, match="campaign binding differs"):
        campaign_operator.validate_prepared_bundle(runtime_path, runtime, config)
    with pytest.raises(FileExistsError):
        output.mkdir()
