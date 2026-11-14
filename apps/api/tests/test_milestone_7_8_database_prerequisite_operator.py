from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_milestone_7_8_campaign_enablement import _config, _manifest, _runtime

from infra.milestone_7_8 import operator
from infra.milestone_7_8.campaign import CampaignError, CostItem, Phase


@pytest.mark.parametrize(
    "operation,defect,dispatches",
    [
        ("bootstrap", "", 1),
        ("bootstrap", "wrong-identity", 0),
        ("bootstrap", "listing-denied", 1),
        ("bootstrap", "wrong-execution", 1),
        ("migrate", "listing-denied", 1),
    ],
)
def test_prerequisites_require_bound_execution_before_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
    defect: str, dispatches: int,
) -> None:
    config = replace(
        _config(),
        cleanup_deadline_utc=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        resource_items=(CostItem("database-prerequisites", "0", 1, "0.0567"),),
    )
    runtime = _runtime()
    runtime["registryName"] = "acrm78test"
    assert runtime["postgresServerName"]
    digest = "sha256:" + "a" * 64
    ledger = Mock(
        image_digest=digest, phase=Phase.IMAGE_DECIDED.value, cleanup_arm_evidence_sha256="b" * 64,
    )
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(operator, "_stage_is_protected", lambda *_: True)
    monkeypatch.setattr(operator, "_verify_retry_protection", lambda *_: [])
    monkeypatch.setattr(operator, "load_execution_authorization", lambda *_, **__: None)
    manifest = _manifest()
    manifest.update({
        "campaignId": config.campaign_id, "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
    })
    slot = "bootstrap" if operation == "bootstrap" else "migration"
    principals = manifest["principals"]
    assert isinstance(principals, dict)
    principal = principals[slot]
    subscription = runtime["subscriptionId"]
    group = runtime["resourceGroupName"]
    job = runtime["bootstrapJobName" if operation == "bootstrap" else "migrationJobName"]
    job_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.App/jobs/{job}"
    )
    identity_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{principal['name']}"
    )
    client = "00000000-0000-0000-0000-000000000099"
    runtime_environment = {
        "OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST": json.dumps(manifest),
        "OPENCANVAS_CAMPAIGN_ID": config.campaign_id,
        "OPENCANVAS_CAMPAIGN_GENERATION_ID": config.generation_id,
        "OPENCANVAS_DATABASE_URL": (
            f"postgresql+asyncpg://{principal['name']}"
            f"@{runtime['postgresServerName']}.postgres.database.azure.com:5432/opencanvas"
        ),
        "OPENCANVAS_DATABASE_ROLE": "provisioning" if operation == "bootstrap" else "migration",
        "OPENCANVAS_DATABASE_AUTH_MODE": "entra",
        "OPENCANVAS_DATABASE_TLS_MODE": "require",
        "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID": client,
        "OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID": principal["objectId"],
    }
    resource = {
        "id": job_id,
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {
            identity_id: {
                "principalId": client if defect == "wrong-identity" else principal["objectId"],
                "clientId": client,
            },
        }},
        "properties": {
            "configuration": {
                "triggerType": "Manual", "replicaTimeout": 900, "replicaRetryLimit": 0,
                "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
            },
            "template": {"containers": [{
                "name": slot, "image": f"acrm78test.azurecr.io/mobius-api@{digest}",
                "command": [
                    "python", "-m",
                    "scripts.bootstrap_postgres" if slot == "bootstrap"
                    else "scripts.migrate_and_grant",
                ],
                "resources": {"cpu": 0.5, "memory": "1Gi"},
                "env": [{"name": name, "value": value}
                        for name, value in runtime_environment.items()],
            }]},
        },
    }
    starts: list[str] = []

    def run(parts: tuple[str, ...]) -> dict[str, object]:
        if parts[3] == "show":
            payload = resource
        else:
            assert parts[3] == "start"
            template = json.loads(Path(parts[parts.index("--yaml") + 1]).read_text())
            assert template["containers"][0]["args"] == ["--diagnose-prerequisites"]
            starts.extend(
                item["value"] for item in template["containers"][0]["env"]
                if item["name"] == "M78_DATABASE_PREREQUISITE_TOKEN"
            )
            payload = {
                "id": (
                    f"{job_id}/executions/prereq"
                    if defect != "wrong-execution" else "/unbound/job"
                ),
                "name": "prereq", "properties": {"status": "Succeeded"},
            }
        return {"exitCode": 0, "stdout": json.dumps(payload), "stderr": ""}

    def read_marker(*_args: object, **kwargs: object) -> dict[str, object]:
        assert starts == [kwargs["token"]] and kwargs["execution"] == "prereq"
        return {
            "version": "m7.8-database-prerequisites-v1", "operation": operation,
            "status": "read-only-prerequisites-passed", "identityDatabase": "postgres",
            "applicationDatabase": "opencanvas", "identityMatches": True,
            "applicationBindingMatches": True, "listingRead": defect != "listing-denied",
            "createExecute": True if operation == "bootstrap" else None,
            "campaignId": config.campaign_id, "generationId": config.generation_id,
            "vector": {
                "version": "0.8.2", "trusted": False, "superuserRequired": True,
                "installed": operation == "migrate", "installerAllowed": slot == "bootstrap",
            },
        }

    monkeypatch.setattr("infra.milestone_7_8.evidence_console.read_job_marker", read_marker)
    runner = Mock()
    runner.run.side_effect = run
    monkeypatch.setattr(operator, "SubprocessRunner", lambda **_kw: runner)
    command = operator.command_plan(operation, config, runtime)[0]

    def gate(*, retry: bool = False) -> None:
        operator._database_prerequisites(
            runner, command, operation=operation, config=config, runtime=runtime,
            ledger=ledger, directory=tmp_path, authorization_path=auth, retry=retry,
        )

    if not defect or operation == "migrate":
        gate()
        gate()
        if defect == "listing-denied":
            with pytest.raises(CampaignError, match="unproved for guarded retry"):
                gate(retry=True)
        else:
            gate(retry=True)
    else:
        with pytest.raises(CampaignError):
            gate()
        assert not (tmp_path / f"{operation}-prerequisites.json").exists()
    assert len(starts) == dispatches
