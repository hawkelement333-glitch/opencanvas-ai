from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import (
    _config,
    _manifest,
    _runtime,
    _write_execution_authorization,
)
from test_milestone_7_8_image_replacement_ledger import (
    NEW_DIGEST,
    NOW,
    image_decided,
    replace_image,
)

from infra.milestone_7_8 import image_continuation, operator
from infra.milestone_7_8.campaign import CostItem, Phase, load_ledger, save_ledger
from infra.milestone_7_8.database_prerequisites import PREREQUISITE_MARKER, PREREQUISITE_TOKEN


@pytest.mark.parametrize("defect", ["", "failed-execution", "wrong-marker", "wrong-execution"])
def test_corrected_prerequisite_gates_real_operator_bootstrap_and_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    defect: str,
) -> None:
    config = replace(
        _config(), resource_items=(CostItem("database-prerequisites", "0", 1, "0.0567"),),
    )
    ledger = image_decided(config)
    replace_image(ledger)
    config = replace(config, conservative_estimate_usd=ledger.conservative_estimate_usd)
    runtime = _runtime()
    ledger_file = tmp_path / "ledger.json"
    runtime_file = tmp_path / "runtime.json"
    config_file = tmp_path / "config.json"
    approval_file = tmp_path / "authorization.json"
    plan_file = tmp_path / "image-continuation" / "plan.json"
    plan_file.parent.mkdir()
    save_ledger(ledger_file, ledger)
    _write_execution_authorization(
        approval_file, config, runtime, expires_at="2030-01-01T04:30:00Z",
        operations=["bootstrap", "migrate", "cleanup"],
    )
    original_intent = tmp_path / "bootstrap-prerequisite-intent.json"
    original_body: dict[str, object] = {"operation": "bootstrap", "previousEvidence": True}
    operator._stage_record(original_intent, "database-prerequisite-intent", original_body)
    original_bytes = original_intent.read_bytes()

    # Image, source, and controller admission have independent tests. Replay
    # this contract from an already-replaced ledger with the real auth loader.
    def load_context(*_args: object, operation: str) -> object:
        assert operation in {"bootstrap", "migrate"}
        return runtime, config, load_ledger(ledger_file, config)

    class FrozenClock:
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return (NOW + timedelta(minutes=2)).astimezone(tz)

    monkeypatch.setattr(image_continuation, "load_context", load_context)
    monkeypatch.setattr(image_continuation, "validate_admission", lambda *_: {})
    monkeypatch.setattr(
        image_continuation, "load_plan", lambda _: {"runtimeFile": str(runtime_file)},
    )
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_: None)
    monkeypatch.setattr(operator, "_verify_retry_protection", lambda *_: None)
    monkeypatch.setattr(operator, "datetime", FrozenClock)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    subscription = runtime["subscriptionId"]
    group_id = f"/subscriptions/{subscription}/resourceGroups/{runtime['resourceGroupName']}"
    workspace = runtime["logAnalyticsWorkspaceName"]
    workspace_id = f"{group_id}/providers/Microsoft.OperationalInsights/workspaces/{workspace}"
    customer = "00000000-0000-0000-0000-000000000099"
    jobs = {runtime["bootstrapJobName"]: "bootstrap", runtime["migrationJobName"]: "migration"}
    starts: list[str] = []
    tokens: dict[str, str] = {}
    commands: list[tuple[str, ...]] = []
    manifest = _manifest()
    principals = cast(dict[str, dict[str, str]], manifest["principals"])

    def job_template(job: str, slot: str) -> dict[str, object]:
        principal = principals[slot]
        identity_id = f"{group_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        env = {
            "OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST": json.dumps(manifest),
            "OPENCANVAS_CAMPAIGN_ID": config.campaign_id,
            "OPENCANVAS_CAMPAIGN_GENERATION_ID": config.generation_id,
            "OPENCANVAS_DATABASE_URL": (
                f"postgresql+asyncpg://{principal['name']}"
                f"@{runtime['postgresServerName']}.postgres.database.azure.com:5432/opencanvas"
            ),
            "OPENCANVAS_DATABASE_ROLE": "provisioning" if slot == "bootstrap" else "migration",
            "OPENCANVAS_DATABASE_AUTH_MODE": "entra",
            "OPENCANVAS_DATABASE_TLS_MODE": "require",
            "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID": customer,
            "OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID": principal["objectId"],
        }
        module = (
            "scripts.bootstrap_postgres" if slot == "bootstrap" else "scripts.migrate_and_grant"
        )
        return {
            "id": f"{group_id}/providers/Microsoft.App/jobs/{job}",
            "identity": {
                "type": "UserAssigned", "userAssignedIdentities": {
                    identity_id + principal["name"]: {
                        "principalId": principal["objectId"], "clientId": customer,
                    },
                },
            },
            "properties": {
                "configuration": {
                    "triggerType": "Manual", "replicaTimeout": 900, "replicaRetryLimit": 0,
                    "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
                },
                "template": {"containers": [{
                    "name": slot,
                    "image": f"{runtime['registryName']}.azurecr.io/mobius-api@{NEW_DIGEST}",
                    "command": ["python", "-m", module], "resources": {"cpu": 0.5, "memory": "1Gi"},
                    "env": [{"name": key, "value": value} for key, value in env.items()],
                }]},
            },
        }

    class FakeProvider:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            commands.append(command)
            prefix = command[:4]
            payload: object
            if command[:3] == ("az", "containerapp", "job") and prefix[-1] in {"show", "start"}:
                job = command[command.index("--name") + 1]
                slot = jobs[job]
                assert command[command.index("--subscription") + 1] == subscription
                if prefix[-1] == "show":
                    payload = job_template(job, slot)
                else:
                    diagnostic = "--yaml" in command
                    execution = f"{slot}-{'diag' if diagnostic else 'normal'}"
                    starts.append(execution)
                    if diagnostic:
                        path = Path(command[command.index("--yaml") + 1])
                        container = json.loads(path.read_text(encoding="utf-8"))["containers"][0]
                        assert container["args"] == ["--diagnose-prerequisites"]
                        assert container["image"].endswith(f"@{NEW_DIGEST}")
                        tokens[slot] = next(
                            entry["value"] for entry in container["env"]
                            if entry["name"] == PREREQUISITE_TOKEN
                        )
                    payload = {
                        "name": execution,
                        "id": (
                            f"{group_id}/providers/Microsoft.App/jobs/{job}/executions/{execution}"
                        ),
                        "properties": {
                            "status": "Failed" if diagnostic and defect == "failed-execution"
                            else "Running" if diagnostic else "Succeeded",
                        },
                    }
            elif prefix == ("az", "containerapp", "job", "execution"):
                job = command[command.index("--name") + 1]
                execution = command[command.index("--job-execution-name") + 1]
                assert command[command.index("--subscription") + 1] == subscription
                assert execution in starts
                identity = "wrong" if defect == "wrong-execution" else execution
                payload = {
                    "name": execution,
                    "id": f"{group_id}/providers/Microsoft.App/jobs/{job}/executions/{identity}",
                    "properties": {"status": "Succeeded"},
                }
            elif prefix == ("az", "monitor", "log-analytics", "workspace"):
                payload = {"id": workspace_id, "customerId": customer}
            elif prefix == ("az", "rest", "--method", "get"):
                url = command[command.index("--url") + 1]
                execution = starts[-1]
                assert f"{group_id}/providers/Microsoft.App/jobs/" in url
                assert f"/executions/{execution}/replicas?" in url
                payload = {"value": [{"name": f"{execution}-replica"}]}
            elif prefix == ("az", "monitor", "log-analytics", "query"):
                execution = starts[-1]
                slot = execution.split("-")[0]
                marker = f"{PREREQUISITE_MARKER} {tokens[slot]} "
                query = command[command.index("--analytics-query") + 1]
                assert f"{execution}-replica" in query
                assert command[command.index("--workspace") + 1] == customer
                body = {
                    "version": "m7.8-database-prerequisites-v1",
                    "operation": "bootstrap" if slot == "bootstrap" else "migrate",
                    "status": "read-only-prerequisites-passed",
                    "identityDatabase": "postgres", "applicationDatabase": "opencanvas",
                    "identityMatches": True, "applicationBindingMatches": True,
                    "listingRead": True, "createExecute": True if slot == "bootstrap" else None,
                    "campaignId": (
                        "wrong-campaign" if defect == "wrong-marker" else config.campaign_id
                    ),
                    "generationId": config.generation_id,
                    "vector": {
                        "version": "0.8.2", "trusted": False, "superuserRequired": True,
                        "installed": slot == "migration", "installerAllowed": slot == "bootstrap",
                    },
                }
                if defect == "failed-execution":
                    payload = []
                else:
                    assert marker in query
                    payload = [{"replica": f"{execution}-replica", "container": slot,
                                "message": marker + json.dumps(body)}]
            else:
                raise AssertionError(f"unexpected fake provider action: {prefix}")
            return {"exitCode": 0, "stdout": json.dumps(payload), "stderr": ""}

    runner = FakeProvider()
    monkeypatch.setattr(operator, "SubprocessRunner", lambda **_: runner)

    def run(operation: str) -> int:
        monkeypatch.setattr(sys, "argv", [
            "operator", operation, "--execute", "--config", str(config_file),
            "--runtime", str(runtime_file), "--ledger", str(ledger_file),
            "--authorization", str(approval_file), "--image-continuation", str(plan_file),
        ])
        return operator.main()

    directory = plan_file.parent / "prerequisites"
    assert run("bootstrap") == (2 if defect else 0)
    result = load_ledger(ledger_file, config)
    assert original_intent.read_bytes() == original_bytes
    assert (directory / "bootstrap-prerequisite-intent.json").is_file()
    assert (directory / "bootstrap-prerequisite-start.json").is_file()
    assert result.cleanup_arm_evidence_sha256 == ledger.cleanup_arm_evidence_sha256
    if defect:
        assert result.phase == Phase.IMAGE_DECIDED
        assert not (directory / "bootstrap-prerequisites.json").exists()
        assert not (tmp_path / "bootstrap-stage-attempt.json").exists()
        assert starts == ["bootstrap-diag"]
        assert run("bootstrap") == 2
        assert starts == ["bootstrap-diag"]
        assert "prerequisite evidence is incomplete" in capsys.readouterr().err
    else:
        assert result.phase == Phase.DATABASE_BOOTSTRAPPED
        assert (directory / "bootstrap-prerequisites.json").is_file()
        assert (tmp_path / "bootstrap-stage-attempt.json").is_file()
        assert starts == ["bootstrap-diag", "bootstrap-normal"]
        assert run("migrate") == 0
        assert load_ledger(ledger_file, config).phase == Phase.MIGRATED
        assert starts == [
            "bootstrap-diag", "bootstrap-normal", "migration-diag", "migration-normal",
        ]
    assert not any(part in {"delete", "stop"} for command in commands for part in command)
