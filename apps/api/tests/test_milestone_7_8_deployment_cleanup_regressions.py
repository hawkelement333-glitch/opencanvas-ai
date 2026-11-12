from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_milestone_7_8_campaign_enablement import NOW, _config, _manifest, _runtime

from infra.milestone_7_8 import operator
from infra.milestone_7_8.campaign import ORDER, CampaignConfig, Ledger, Phase
from infra.milestone_7_8.operator import cleanup_job_parameters, command_plan

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "infra/milestone_7_8/scripts/Remove-M78Campaign.ps1"


def test_normal_deploy_template_serializes_postgres_child_writes(tmp_path: Path) -> None:
    compiler = shutil.which("bicep") or str(Path.home() / ".azure/bin/bicep.exe")
    if not Path(compiler).is_file():
        pytest.skip("installed Bicep is required for compiled dependency validation")
    command = command_plan("deploy", _config(), _runtime())[0]
    template = ROOT / command[command.index("--template-file") + 1]
    output = tmp_path / "main.json"
    subprocess.run([compiler, "build", str(template), "--outfile", str(output)], check=True)
    compiled = json.loads(output.read_text())

    def resources(document: dict[str, object]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        children = document["resources"]
        assert isinstance(children, list)
        for resource in children:
            assert isinstance(resource, dict)
            result.append(resource)
            if resource["type"] == "Microsoft.Resources/deployments":
                result.extend(resources(resource["properties"]["template"]))
        return result

    postgres = {
        str(item["type"]).rsplit("/", 1)[-1]: item
        for item in resources(compiled)
        if str(item["type"]).startswith("Microsoft.DBforPostgreSQL/flexibleServers/")
    }
    assert set(postgres) == {"administrators", "configurations", "databases"}
    # A shared parent alone permits concurrent writes: the extension must wait
    # for the admin, and the database for the extension. No retry/sleep required.
    configuration_deps = postgres["configurations"]["dependsOn"]
    database_deps = postgres["databases"]["dependsOn"]
    assert isinstance(configuration_deps, list) and isinstance(database_deps, list)
    assert any("/administrators'" in dep for dep in configuration_deps)
    assert any("/configurations'" in dep for dep in database_deps)


HARNESS = r"""param([string]$Runbook, [string]$Fixture)
$ErrorActionPreference = 'Stop'
$f = Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json -AsHashtable
$p = @{}
foreach ($key in $f.parameters.Keys) {
  $p[$key] = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($f.parameters[$key]))
}
# Get-AzResourceGroup returns string-valued tags, not JSON-coerced DateTimes.
foreach ($section in @('controllerTags', 'targetTags')) {
  foreach ($key in @($f[$section].Keys)) {
    $bytes = [Convert]::FromBase64String($f[$section][$key])
    $f[$section][$key] = [Text.Encoding]::UTF8.GetString($bytes)
  }
}
$state = @{ removed = $false; reads = 0 }
function Connect-AzAccount { param([switch]$Identity) }
function Get-AzContext { return @{ Subscription = @{ Id = $f.subscription } } }
function Get-AzResourceGroup {
  param([string]$Name, [string]$ErrorAction)
  if ($Name -eq $p.ControllerResourceGroupName) { return @{ Tags = $f.controllerTags } }
  if ($Name -ne $p.TargetResourceGroupName) { throw 'unexpected-group' }
  if (-not $state.removed) { return @{ Tags = $f.targetTags } }
}
function Invoke-AzRestMethod {
  param([string]$Path, [string]$Method)
  if ($Method -cne 'GET' -or -not $f.responses.ContainsKey($Path)) { throw 'unexpected-read' }
  $state.reads++
  return @{ Content = $f.responses[$Path]; StatusCode = 200 }
}
function Get-AzAccessToken { param([string]$ResourceUrl); return @{ Token = $f.token } }
function Get-AzRoleAssignment {
  param([string]$Scope)
  if (-not $f.roles.ContainsKey($Scope)) { throw 'unexpected-role-scope' }
  return $f.roles[$Scope]
}
function Remove-AzResourceGroup {
  param([string]$Name, [switch]$Force)
  if ($Name -cne $p.TargetResourceGroupName -or -not $Force) { throw 'wrong-delete' }
  $state.removed = $true
}
try {
  $receipt = & $Runbook @p | ConvertFrom-Json
  @{ status = $receipt.status; removed = $state.removed; reads = $state.reads } |
    ConvertTo-Json -Compress
} catch {
  @{ error = $_.Exception.Message; removed = $state.removed; reads = $state.reads } |
    ConvertTo-Json -Compress
  exit 2
}
"""


def _runbook_fixture(defect: str | None) -> dict[str, object]:
    runtime = _runtime()
    runtime["scheduleName"] = "m78-deadline-aabbccddee"
    subscription = runtime["subscriptionId"]
    correlation = hashlib.sha256(b"m7.8/subscription\0" + subscription.encode()).hexdigest()[:16]
    config = _config(subscription_correlation=correlation)
    parameters = cleanup_job_parameters(config, runtime)
    controller_tags = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": "reusable-automation-controller-v1",
        "mobius.subscription-correlation": correlation,
        "mobius.fresh-controller-admission-sha256": "0" * 64,
        "mobius.fresh-controller-admission-version": runtime[
            "freshControllerAdmissionEvidenceVersion"
        ],
    }
    target_tags = {
        "mobius.milestone": "7.8",
        "mobius.campaign": config.campaign_id,
        "mobius.generation": config.generation_id,
        "mobius.cleanup-deadline-utc": config.cleanup_deadline_utc,
        "mobius.cost-ceiling-cents": "5000",
        "mobius.fresh-controller-admission-sha256": "0" * 64,
        "mobius.fresh-controller-admission-version": runtime[
            "freshControllerAdmissionEvidenceVersion"
        ],
    }
    group = f"/subscriptions/{subscription}/resourceGroups/{config.cleanup_resource_group}"
    target = f"/subscriptions/{subscription}/resourceGroups/{config.target_resource_group}"
    account = (
        f"{group}/providers/Microsoft.Automation/automationAccounts/"
        f"{runtime['automationAccountName']}"
    )
    principal = "22222222-2222-4222-8222-222222222222"
    binding_parameters: dict[str, object] = dict(parameters)
    binding: dict[str, object] = {
        "id": f"{account}/jobSchedules/{runtime['bindingName']}",
        "type": "Microsoft.Automation/automationAccounts/jobSchedules",
        # Actual ARM exact-UUID response has no top-level name.
        "properties": {
            "jobScheduleId": runtime["bindingName"],
            "runbook": {"name": runtime["runbookName"]},
            "schedule": {"name": runtime["scheduleName"]},
            "parameters": binding_parameters,
        },
    }
    if defect == "value":
        binding_parameters["CleanupAuthorized"] = "PRIVATE-VALUE-MUST-NOT-LEAK"
    elif defect == "type":
        binding_parameters["CostCeilingCents"] = 5000
    elif defect == "missing":
        del binding_parameters["CleanupDeadlineUtc"]
    elif defect == "extra":
        binding_parameters["PRIVATE-KEY-MUST-NOT-LEAK"] = "secret"
    elif defect == "wrong-id":
        binding["id"] = f"{account}/jobSchedules/33333333-3333-4333-8333-333333333333"
    elif defect == "malformed-id":
        binding["id"] = [binding["id"]]
    elif defect == "conflicting-name":
        binding["name"] = "33333333-3333-4333-8333-333333333333"
    elif defect == "missing-identity":
        del binding["id"]
    elif defect == "legacy-name":
        binding["name"] = runtime["bindingName"]
        del binding["id"]
        properties = binding["properties"]
        assert isinstance(properties, dict)
        del properties["jobScheduleId"]
    elif defect == "wrong-uuid":
        properties = binding["properties"]
        assert isinstance(properties, dict)
        properties["jobScheduleId"] = "33333333-3333-4333-8333-333333333333"
    elif defect == "parameter-shape":
        properties = binding["properties"]
        assert isinstance(properties, dict)
        properties["parameters"] = None
    elif defect == "ownership":
        target_tags["mobius.campaign"] = "other-campaign"
    responses = {
        account: {
            "name": runtime["automationAccountName"],
            "tags": controller_tags,
            "identity": {"principalId": principal},
        },
        f"{account}/runbooks/{runtime['runbookName']}": {
            "name": runtime["runbookName"],
            "properties": {"state": "Published"},
        },
        f"{account}/schedules/{runtime['scheduleName']}": {
            "name": runtime["scheduleName"],
            "properties": {
                "frequency": "OneTime",
                "isEnabled": True,
                "interval": None,
                "timeZone": "Etc/UTC",
                "startTime": config.cleanup_deadline_utc,
            },
        },
        f"{account}/jobSchedules/{runtime['bindingName']}": binding,
    }
    token = (
        "e30."
        + base64.urlsafe_b64encode(json.dumps({"oid": principal}).encode()).decode().rstrip("=")
        + ".test"
    )
    encoded_responses = {
        f"{k}?api-version=2024-10-23": json.dumps(v) for k, v in responses.items()
    }
    binding_url = f"{account}/jobSchedules/{runtime['bindingName']}?api-version=2024-10-23"
    if defect == "invalid-json":
        encoded_responses[binding_url] = '{"PRIVATE-KEY-MUST-NOT-LEAK":'
    elif defect == "duplicate":
        encoded_responses[binding_url] = encoded_responses[binding_url].replace(
            '"CleanupAuthorized": "true"',
            '"CleanupAuthorized": "true", "cleanupauthorized": "true"',
        )
    return {
        "parameters": {k: base64.b64encode(v.encode()).decode() for k, v in parameters.items()},
        "subscription": subscription,
        "controllerTags": {
            k: base64.b64encode(v.encode()).decode()
            for k, v in {
                **controller_tags,
                "mobius.controller-authorized-until-utc": "2030-01-02T00:00:00Z",
            }.items()
        },
        "targetTags": {k: base64.b64encode(v.encode()).decode() for k, v in target_tags.items()},
        "token": token,
        "responses": encoded_responses,
        "roles": {
            group: [
                {
                    "ObjectId": principal,
                    "RoleDefinitionId": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
                    "Scope": group,
                }
            ],
            target: [
                {"ObjectId": principal, "RoleDefinitionId": role, "Scope": target}
                for role in (
                    "b24988ac-6180-42a0-ab88-20f7382dd24c",
                    "f58310d9-a9f6-439a-9e8d-f62e7b41a168",
                )
            ],
        },
    }


@pytest.mark.parametrize(
    "defect, expected",
    [
        (None, None),
        ("legacy-name", None),
        ("value", "cleanup-binding-parameter-mismatch:CleanupAuthorized:value"),
        ("type", "cleanup-binding-parameter-mismatch:CostCeilingCents:type-Number"),
        ("missing", "cleanup-binding-parameter-set-mismatch:CleanupDeadlineUtc:missing"),
        ("extra", "cleanup-binding-parameter-set-mismatch:unknown-field"),
        ("wrong-id", "cleanup-binding-identity-mismatch:id"),
        ("malformed-id", "cleanup-binding-identity-mismatch:id"),
        ("parameter-shape", "cleanup-binding-parameter-set-mismatch:parameters-shape"),
        ("invalid-json", "cleanup-binding-parameter-set-mismatch:invalid-json"),
        ("duplicate", "cleanup-binding-parameter-set-mismatch:CleanupAuthorized:duplicate"),
        ("conflicting-name", "cleanup-binding-identity-mismatch:name"),
        ("missing-identity", "cleanup-binding-identity-mismatch:missing"),
        ("wrong-uuid", "cleanup-binding-identity-mismatch:jobScheduleId"),
        ("ownership", "cleanup-resource-tag-mismatch"),
    ],
)
def test_full_cleanup_runbook_handles_raw_automation_response(
    tmp_path: Path,
    defect: str | None,
    expected: str | None,
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is required for the cleanup response replay")
    fixture = tmp_path / "synthetic.json"
    fixture.write_text(json.dumps(_runbook_fixture(defect)), encoding="utf-8")
    harness = tmp_path / "run.ps1"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(harness), str(RUNBOOK), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "POWERSHELL_TELEMETRY_OPTOUT": "1"},
    )
    observed = json.loads(result.stdout)
    assert "PRIVATE-" not in result.stdout + result.stderr
    if expected is None:
        assert result.returncode == 0, observed
        assert observed == {
            "status": "target-removed-controller-disarm-required",
            "removed": True,
            "reads": 4,
        }
    else:
        assert result.returncode == 2, observed
        assert observed["error"] == expected
        assert observed["removed"] is False


@pytest.mark.parametrize("failed", [False, True])
def test_operator_base_deploy_uses_template_and_retains_failure_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: bool,
) -> None:
    config, runtime = _config(), _runtime()
    manifest = _manifest()
    principals = manifest["principals"]
    assert isinstance(principals, dict)
    planned = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "principals": {
            slot: principals[slot]["name"]
            for slot in ("bootstrap", "migration", "api", "worker", "evidence")
        },
        "cleanup": principals["cleanup"]["name"],
    }
    config = replace(
        config,
        principal_manifest_sha256=hashlib.sha256(
            json.dumps(planned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    binding = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "maximumHours": 4,
        "costCeilingCents": 5000,
        "cleanupResourceGroupName": config.cleanup_resource_group,
        "cleanupLocation": config.cleanup_region,
        "cleanupRegionSelectionSha256": config.cleanup_region_selection_sha256,
        "cleanupCandidateRegions": config.cleanup_candidate_regions,
        "cleanupOfferClassification": config.cleanup_offer_classification,
        "cleanupOfferEligibilityDisposition": config.cleanup_offer_eligibility_disposition,
        "cleanupOfferEligibleRegions": config.cleanup_offer_eligible_regions,
        "cleanupOfferEligibilitySource": config.cleanup_offer_eligibility_source,
        "cleanupOfferEligibilitySha256": config.cleanup_offer_eligibility_sha256,
        "freshControllerAdmissionEvidenceSha256": config.fresh_controller_admission_evidence_sha256,
        "principalManifest": json.dumps(manifest),
    }
    outputs = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "deploymentStage": "base",
        "campaignBinding": binding,
    }
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.bind_cleanup_region(config)
    ledger.bind_deadline(config.cleanup_deadline_utc)
    for phase in ORDER[1 : ORDER.index(Phase.BILLABLE_STARTED) + 1]:
        if phase == Phase.CLEANUP_ARMED:
            ledger.record_cleanup_arm_evidence("a" * 64)
        ledger.transition(phase, NOW)
    commands: list[tuple[str, ...]] = []

    class FakeProvider:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            commands.append(command)
            if "deployment" in command:
                return {
                    "exitCode": 1 if failed else 0,
                    "stderr": "",
                    "stdout": json.dumps(
                        {
                            "properties": {
                                "outputs": {k: {"value": v} for k, v in outputs.items()}
                            },
                        }
                    ),
                }
            assert command[:4] == ("az", "automation", "runbook", "start")
            return {"exitCode": 0, "stdout": "{}", "stderr": ""}

    monkeypatch.setattr(CampaignConfig, "from_json", classmethod(lambda cls, *a, **k: config))
    monkeypatch.setattr(operator, "load_runtime", lambda *_: runtime)
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_: None)
    monkeypatch.setattr(operator, "load_execution_authorization", lambda *a, **k: None)
    monkeypatch.setattr(operator, "load_ledger", lambda *_: ledger)
    monkeypatch.setattr(operator, "save_ledger", lambda *_: None)
    monkeypatch.setattr(operator, "SubprocessRunner", FakeProvider)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "operator",
            "deploy",
            "--config",
            "config",
            "--runtime",
            "runtime",
            "--ledger",
            "ledger",
            "--authorization",
            "auth",
            "--execute",
        ],
    )
    assert operator.main() == (2 if failed else 0)
    assert commands[0] == command_plan("deploy", config, runtime)[0]
    assert len(commands) == (2 if failed else 1)  # No automatic deployment retry.
    assert ledger.phase == (Phase.CLEANING if failed else Phase.INFRASTRUCTURE_DEPLOYED).value
    capsys.readouterr()
