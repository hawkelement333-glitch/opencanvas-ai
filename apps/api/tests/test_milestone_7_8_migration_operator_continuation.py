from __future__ import annotations

import hashlib
import io
import json
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from test_milestone_7_8_campaign_enablement import (
    _cleanup_arm_success_results,
    _config,
    _manifest,
    _runtime,
)
from test_milestone_7_8_job_diagnostics import NOW, FakeProvider, result

from infra.milestone_7_8 import image_continuation, operator
from infra.milestone_7_8.campaign import CampaignConfig, CostItem, Phase

OLD = "sha256:" + "d" * 64
NEW = "sha256:" + "e" * 64
LOCAL_ID = "sha256:" + "f" * 64


class MigrationProvider(FakeProvider):
    def __init__(self, runtime: dict[str, str], config: CampaignConfig, defect: str) -> None:
        super().__init__(runtime)
        self.operation = "migrate"
        self.execution = "failed-migration"
        self.defect = defect
        self.prerequisite_token = ""
        self.manifest = _manifest()
        principals = cast(dict[str, dict[str, str]], self.manifest["principals"])
        principal = principals["migration"]
        client = "00000000-0000-0000-0000-000000000099"
        identity = (
            f"{self.group_id}/providers/Microsoft.ManagedIdentity"
            f"/userAssignedIdentities/{principal['name']}"
        )
        environment = {
            "OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST": json.dumps(self.manifest),
            "OPENCANVAS_CAMPAIGN_ID": config.campaign_id,
            "OPENCANVAS_CAMPAIGN_GENERATION_ID": config.generation_id,
            "OPENCANVAS_DATABASE_URL": (
                f"postgresql+asyncpg://{principal['name']}"
                f"@{runtime['postgresServerName']}.postgres.database.azure.com:5432/opencanvas"
            ),
            "OPENCANVAS_DATABASE_ROLE": "migration",
            "OPENCANVAS_DATABASE_AUTH_MODE": "entra",
            "OPENCANVAS_DATABASE_TLS_MODE": "require",
            "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID": client,
            "OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID": principal["objectId"],
            # Deployment environment remains original despite the operator/image transition.
            "M78_ORIGINAL_SOURCE_HEAD": "a" * 40,
        }
        self.template = {"containers": [{
            "name": "migration", "image": self.image(NEW),
            "command": ["python", "-m", "scripts.migrate_and_grant"],
            "resources": {"cpu": 0.5, "memory": "1Gi"},
            "env": [{"name": name, "value": value} for name, value in environment.items()],
        }]}
        self.original_template = deepcopy(self.template)
        cast(list[dict[str, object]], self.original_template["containers"])[0]["image"] = (
            self.image(OLD)
        )
        if defect == "wrong-image":
            cast(list[dict[str, object]], self.template["containers"])[0]["image"] = (
                self.image(LOCAL_ID)
            )
        if defect == "environment-drift":
            cast(list[dict[str, object]], self.original_template["containers"])[0]["env"] = []
        self.resource = {
            "id": self.job_id(),
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {
                identity: {"principalId": principal["objectId"], "clientId": client},
            }},
            "properties": {
                "configuration": {
                    "triggerType": "Manual", "replicaTimeout": 1800, "replicaRetryLimit": 0,
                    "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
                },
                "template": self.template,
            },
        }

    def image(self, digest: str) -> str:
        return f"{self.runtime['registryName']}.azurecr.io/mobius-api@{digest}"

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        if command[:4] == ("az", "containerapp", "job", "show"):
            self.commands.append(command)
            self.events.append("job-readback")
            return result(self.resource)
        if command[:4] == ("az", "containerapp", "job", "start") and "--yaml" in command:
            template = json.loads(Path(command[command.index("--yaml") + 1]).read_text())
            container = template["containers"][0]
            if container["args"] == ["--diagnose-prerequisites"]:
                self.commands.append(command)
                self.events.append("prerequisite-start")
                self.prerequisite_token = next(
                    item["value"] for item in container["env"]
                    if item["name"] == "M78_DATABASE_PREREQUISITE_TOKEN"
                )
                return result({
                    "id": self.job_id() + "/executions/corrected-prerequisite",
                    "name": "corrected-prerequisite", "properties": {"status": "Succeeded"},
                })
        return super().run(command)

    def execution_result(self, name: str, status: str) -> dict[str, object]:
        value = super().execution_result(name, status)
        if name == self.execution:
            payload = json.loads(str(value["stdout"]))
            payload["properties"]["template"] = self.original_template
            value["stdout"] = json.dumps(payload)
        return value

    def run_database_retry(self) -> None:
        self.events.append("db-inspection")
        self.retry_status = "Failed" if self.defect == "retry-failure" else "Succeeded"
        self.retry_marker = "M78_DATABASE_RECOVERY " + json.dumps({
            "version": "m7.8-database-recovery-observation-v1", "operation": "migrate",
            "previousExecution": self.execution, "campaignId": self.manifest["campaignId"],
            "generationId": self.manifest["generationId"],
            "manifestSha256": operator._stage_hash("database-recovery-manifest", self.manifest),
            "observedRevision": "base", "state": "migration-empty", "principalCount": 4,
            "applicationRelationCount": 0, "snapshotSha256": "9" * 64,
            "status": "retry-preflight-passed",
        })
        if self.defect == "wrong-marker":
            self.retry_marker = self.retry_marker.replace('"migration-empty"', '"bootstrap-empty"')


@dataclass
class Case:
    directory: Path
    config: CampaignConfig
    runtime: dict[str, str]
    ledger: Mock
    provider: MigrationProvider
    transition: dict[str, object]
    original: dict[Path, bytes]

    def run(self, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
        monkeypatch.setattr(sys, "argv", [
            "operator", "migrate", "--execute", "--resume-database-job",
            "--runtime", str(self.directory / "runtime.json"),
            "--config", str(self.directory / "config.json"),
            "--ledger", str(self.directory / "ledger.json"),
            "--authorization", str(self.directory / "authorization.json"),
            "--image-continuation", str(self.directory / "corrected/plan.json"),
        ])
        errors = io.StringIO()
        with redirect_stderr(errors), redirect_stdout(io.StringIO()):
            status = operator.main()
        assert all(path.read_bytes() == value for path, value in self.original.items())
        return status, errors.getvalue()


def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str = "") -> Case:
    config = replace(
        _config(), cleanup_deadline_utc="2030-01-01T01:00:00Z",
        conservative_estimate_usd="26",
        resource_items=(
            *_config().resource_items,
            CostItem("database-prerequisites", "0", 1, "0.0567"),
            CostItem("database-recovery-job-allowance", "0", 1, "0.0567"),
            CostItem("corrected-migration-prerequisite", "0", 1, "0.0378"),
        ),
    )
    runtime = _runtime()
    runtime.update({
        "sourceHead": "a" * 40, "registryName": "acrm78test",
        "cleanupScriptSha256": hashlib.sha256(b"cleanup-content").hexdigest(),
        "cleanupAuthorityExpiresUtc": operator.runtime_authority_expiry(config),
    })
    arm = _cleanup_arm_success_results(config, runtime)
    readbacks = [*arm[:6], arm[9], arm[11], arm[12]]
    ledger = Mock(
        phase=Phase.DATABASE_BOOTSTRAPPED.value, image_digest=OLD,
        actual_cost_usd=None, authorized_ceiling_usd="50",
        cleanup_arm_evidence_sha256=operator.validate_cleanup_readback(readbacks, config, runtime),
    )
    for name in ("config.json", "runtime.json", "authorization.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    bindings = operator._stage_bindings(config, runtime, ledger)
    attempt = operator._stage_record(tmp_path / "migrate-stage-attempt.json", "stage-attempt", {
        "version": "m7.8-protected-stage-attempt-v1", "operation": "migrate",
        "bindings": bindings, "commandSha256": "1" * 64, "authorizationSha256": "2" * 64,
        "startedAtUtc": (NOW - timedelta(minutes=30)).isoformat(),
    })
    pause_path = tmp_path / "migrate-stage-pause.json"
    operator._stage_record(pause_path, "stage-pause", {
        "version": "m7.8-protected-stage-pause-v1", "operation": "migrate",
        "bindings": bindings, "attemptSha256": attempt["recordSha256"],
        "authorizationSha256": "2" * 64, "failedExecution": "failed-migration",
        "failedAtUtc": (NOW - timedelta(minutes=20)).isoformat(),
        "recoveryUntilUtc": (NOW - timedelta(minutes=5)).isoformat(), "maximumRetryDispatches": 1,
    })
    workload_path = tmp_path / "image-decision-stage-pause.json"
    workload = json.loads(pause_path.read_text())
    workload.pop("recordSha256")
    workload["operation"] = "image-decision"
    operator._stage_record(workload_path, "stage-pause", workload)
    original = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    runtime = {**runtime, "sourceHead": "b" * 40, "canonicalBuildInputSha256": "c" * 64}
    ledger.image_digest = NEW
    transition: dict[str, object] = {
        "kind": "migration-image-continuation", "operatorSourceHead": runtime["sourceHead"],
        "transitionSha256": "3" * 64, "issuedAtUtc": (NOW - timedelta(minutes=1)).isoformat(),
        "expiresAtUtc": (NOW + timedelta(minutes=14)).isoformat(), "originalBindings": bindings,
        "migrationPauseSha256": hashlib.sha256(pause_path.read_bytes()).hexdigest(),
        "originalAttemptSha256": attempt["recordSha256"],
        "previousImageReference": f"acrm78test.azurecr.io/mobius-api@{OLD}",
        "replacementImageReference": f"acrm78test.azurecr.io/mobius-api@{NEW}",
        "resolvedWorkloadPauseSha256": hashlib.sha256(workload_path.read_bytes()).hexdigest(),
    }
    if defect == "expired":
        transition["expiresAtUtc"] = NOW.isoformat()
    if defect == "wrong-history":
        transition["originalAttemptSha256"] = "0" * 64
    provider = MigrationProvider(runtime, config, defect)
    provider.cleanup_reads = dict(zip((
        (*command, "--subscription", runtime["subscriptionId"])
        for command in operator.command_plan("cleanup-verify", config, runtime)
    ), readbacks, strict=True))
    (tmp_path / "corrected").mkdir()

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Clock:
            return cls.fromtimestamp(NOW.timestamp(), tz)

    def read_marker(*_args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["execution"] == "corrected-prerequisite"
        assert kwargs["token"] == provider.prerequisite_token
        provider.events.append("prerequisite-marker")
        return {
            "version": "m7.8-database-prerequisites-v1", "operation": "migrate",
            "status": "read-only-prerequisites-passed", "identityDatabase": "postgres",
            "applicationDatabase": "opencanvas", "identityMatches": True,
            "applicationBindingMatches": True, "listingRead": defect != "listing-denied",
            "createExecute": None, "campaignId": config.campaign_id,
            "generationId": config.generation_id,
            "vector": {"version": "0.8.2", "trusted": False, "superuserRequired": True,
                       "installed": True, "installerAllowed": False},
        }

    def advance(phase: Phase, *_args: object, **_kwargs: object) -> None:
        ledger.phase = phase.value

    ledger.transition.side_effect = advance
    monkeypatch.setattr(operator, "datetime", Clock)
    monkeypatch.setattr(operator, "SubprocessRunner", lambda **_kw: provider)
    monkeypatch.setattr(operator, "load_execution_authorization", lambda *_, **__: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_: None)
    monkeypatch.setattr(operator, "save_ledger", lambda *_: None)
    monkeypatch.setattr(
        operator, "start_failure_cleanup", lambda *_: provider.events.append("cleanup"),
    )
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        image_continuation, "load_context", lambda *_, **__: (runtime, config, ledger),
    )
    monkeypatch.setattr(image_continuation, "migration_retry_transition", lambda *_: transition)
    monkeypatch.setattr(image_continuation, "resolved_image_pause", lambda *_: None)
    monkeypatch.setattr(
        image_continuation, "prerequisite_directory", lambda *_: tmp_path / "corrected",
    )
    monkeypatch.setattr("infra.milestone_7_8.evidence_console.read_job_marker", read_marker)
    return Case(tmp_path, config, runtime, ledger, provider, transition, original)


def test_normal_migration_continuation_runs_new_prerequisite_then_single_guarded_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = case(tmp_path, monkeypatch)
    status, errors = value.run(monkeypatch)
    assert status == 0, errors
    assert value.ledger.phase == Phase.MIGRATED.value
    assert (value.provider.events.index("prerequisite-marker")
            < value.provider.events.index("retry-start"))
    assert value.provider.events.count("prerequisite-start") == 1
    assert value.provider.events.count("retry-start") == 1
    assert "cleanup" not in value.provider.events
    completed = operator._read_stage_record(
        tmp_path / "migrate-stage-recovery-completed.json", "stage-recovery-completed",
    )
    assert completed["migrationImageTransitionSha256"] == value.transition["transitionSha256"]
    assert "bootstrapSourceTransitionSha256" not in completed
    assert operator._active_protected_pause(
        tmp_path, value.config, value.runtime, value.ledger, value.transition,
        resolved_workload_pause_sha256=str(value.transition["resolvedWorkloadPauseSha256"]),
    ) is None
    status, _ = value.run(monkeypatch)
    assert status == 2
    assert value.provider.events.count("retry-start") == 1


@pytest.mark.parametrize("defect", [
    "expired", "wrong-history", "wrong-image", "environment-drift", "listing-denied",
    "wrong-marker", "retry-failure",
])
def test_normal_migration_continuation_rejects_unproved_history_or_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    value = case(tmp_path, monkeypatch, defect)
    status, errors = value.run(monkeypatch)
    assert status == 2, errors
    assert value.ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert "cleanup" not in value.provider.events
    assert not (tmp_path / "migrate-stage-recovery-completed.json").exists()
    if defect in {"expired", "wrong-history"}:
        assert not value.provider.commands
    if defect not in {"wrong-marker", "retry-failure"}:
        assert "retry-start" not in value.provider.events
    if defect == "retry-failure":
        assert "logs" in value.provider.events
        assert "stage-pause-recording-incomplete" not in errors
