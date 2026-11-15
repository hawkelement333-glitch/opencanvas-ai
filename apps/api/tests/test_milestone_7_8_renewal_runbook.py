"""Exercise cleanup protection before and after a replacement schedule activates."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_milestone_7_8_deployment_cleanup_regressions import HARNESS, RUNBOOK, _runbook_fixture


def _encode(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _fixture(state: str, defect: str | None = None) -> dict:
    fixture = _runbook_fixture(None)
    old = {k: base64.b64decode(v).decode() for k, v in fixture["parameters"].items()}
    new = dict(old)
    new.update(
        CleanupScheduleName="m78-deadline-1122334455",
        CleanupBindingName="33333333-3333-4333-8333-333333333333",
        CleanupDeadlineUtc="2030-01-01T08:00:00Z",
        CleanupAuthorityExpiresUtc="2030-01-01T09:00:00Z",
    )
    fields = [
        "CampaignId",
        "GenerationId",
        "SubscriptionCorrelation",
        "TargetResourceGroupName",
        "ControllerResourceGroupName",
        "AutomationAccountName",
        "CleanupRunbookName",
        "CleanupScheduleName",
        "CleanupBindingName",
        "CleanupDeadlineUtc",
        "CleanupAuthorityExpiresUtc",
        "CostCeilingCents",
        "ControllerBindingSha256",
        "FreshControllerAdmissionEvidenceSha256",
        "FreshControllerAdmissionEvidenceVersion",
    ]
    values = ["reusable-automation-controller-v1", *(new[k] for k in fields)]
    new["CleanupAuthoritySha256"] = hashlib.sha256(
        b"m7.8/cleanup-authority/v4\0" + "\0".join(values).encode()
    ).hexdigest()
    account = (
        f"/subscriptions/{fixture['subscription']}/resourceGroups/{new['ControllerResourceGroupName']}"
        f"/providers/Microsoft.Automation/automationAccounts/{new['AutomationAccountName']}"
    )
    binding = {
        "id": f"{account}/jobSchedules/{new['CleanupBindingName']}",
        "properties": {
            "jobScheduleId": new["CleanupBindingName"],
            "runbook": {"name": new["CleanupRunbookName"]},
            "schedule": {"name": new["CleanupScheduleName"]},
            "parameters": dict(new),
        },
    }
    schedule = {
        "name": new["CleanupScheduleName"],
        "properties": {
            "frequency": "OneTime",
            "isEnabled": True,
            "startTime": new["CleanupDeadlineUtc"],
            "timeZone": "Etc/UTC",
        },
    }
    if defect == "wrong-scope":
        binding["properties"]["parameters"]["TargetResourceGroupName"] = "rg-m78-9999999999-target"
    elif defect == "disabled":
        schedule["properties"]["isEnabled"] = False
    elif defect == "wrong-hash":
        binding["properties"]["parameters"]["CleanupAuthoritySha256"] = "f" * 64
    elif defect == "hybrid-worker":
        binding["properties"]["runOn"] = "unapproved-worker"
    elif defect in {"missing-target-authority", "wrong-target-role-scope"}:
        target = (
            f"/subscriptions/{fixture['subscription']}"
            f"/resourceGroups/{new['TargetResourceGroupName']}"
        )
        if defect == "missing-target-authority":
            fixture["roles"][target] = []
        else:
            for assignment in fixture["roles"][target]:
                assignment["Scope"] = f"/subscriptions/{fixture['subscription']}"
    fixture["responses"][
        f"{account}/jobSchedules/{new['CleanupBindingName']}?api-version=2024-10-23"
    ] = json.dumps(binding)
    fixture["responses"][
        f"{account}/schedules/{new['CleanupScheduleName']}?api-version=2024-10-23"
    ] = json.dumps(schedule)
    if state != "staged":
        active = {
            "mobius.cleanup-deadline-utc": new["CleanupDeadlineUtc"],
            "mobius.expiry": new["CleanupDeadlineUtc"],
            "mobius.cleanup-schedule": new["CleanupScheduleName"],
            "mobius.cleanup-binding": new["CleanupBindingName"],
            "mobius.cleanup-authority-sha256": new["CleanupAuthoritySha256"],
            "mobius.cleanup-parent-binding": old["CleanupBindingName"],
            "mobius.cleanup-parent-authority-sha256": old["CleanupAuthoritySha256"],
            "mobius.cleanup-renewal-planned-utc": "2026-01-01T02:00:00.123456Z",
        }
        if defect == "wrong-parent":
            active["mobius.cleanup-parent-authority-sha256"] = "f" * 64
        fixture["targetTags"].update({k: _encode(v) for k, v in active.items()})
    if state == "new-invocation":
        fixture["parameters"] = {k: _encode(v) for k, v in new.items()}
    return fixture


@pytest.mark.parametrize("state", ["staged", "activated", "new-invocation"])
def test_replacement_activation_preserves_cleanup(tmp_path: Path, state: str) -> None:
    observed, code = _run(tmp_path, _fixture(state))
    assert code == 0, observed
    if state == "activated":
        assert observed["status"] == "superseded-cleanup-verified"
        assert observed["removed"] is False
    else:
        assert observed["status"] == "target-removed-controller-disarm-required"
        assert observed["removed"] is True


@pytest.mark.parametrize(
    "defect",
    [
        "wrong-scope",
        "disabled",
        "wrong-hash",
        "wrong-parent",
        "hybrid-worker",
        "missing-target-authority",
        "wrong-target-role-scope",
    ],
)
def test_superseded_cleanup_requires_valid_replacement(tmp_path: Path, defect: str) -> None:
    observed, code = _run(tmp_path, _fixture("activated", defect))
    assert code != 0
    assert observed["removed"] is False


def _run(tmp_path: Path, fixture: dict) -> tuple[dict, int]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 required")
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture))
    harness = tmp_path / "run.ps1"
    harness.write_text(HARNESS)
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(harness), str(RUNBOOK), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "POWERSHELL_TELEMETRY_OPTOUT": "1"},
    )
    return json.loads(result.stdout), result.returncode
