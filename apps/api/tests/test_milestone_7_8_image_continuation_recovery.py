from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_local_image import Case, Provider, case

from infra.milestone_7_8 import image_continuation, local_image, operator, retained_image
from infra.milestone_7_8 import image_continuation_recovery as recovery
from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.canonical_inputs import BUILD_INPUTS

__all__ = ["case"]


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def prior(case: Case, monkeypatch: pytest.MonkeyPatch) -> Path:
    bundle = case.runtime_path.parent
    folder = bundle / "image-continuation"
    output = folder / "local-image"
    output.mkdir(parents=True)
    ledger_path = bundle / "ledger.json"
    write(ledger_path, asdict(case.ledger))
    plan = {
        "sourceHead": case.runtime["sourceHead"], "planSha256": "a" * 64,
        "runtimeFile": str(case.runtime_path), "ledgerFile": str(ledger_path),
        "baselineLedger": asdict(case.ledger),
        "baselineLedgerFileSha256": recovery._file_hash(ledger_path),
    }
    plan_path = folder / "plan.json"
    write(plan_path, plan)
    monkeypatch.setattr(recovery, "PRIOR_HEAD", case.runtime["sourceHead"])
    monkeypatch.setattr(recovery, "PRIOR_PLAN", plan["planSha256"])
    monkeypatch.setattr(image_continuation, "ROOT", local_image.ROOT)
    monkeypatch.setattr(image_continuation, "load_plan", lambda _path: plan)
    monkeypatch.setattr(image_continuation, "_effective", lambda _plan: (case.runtime, case.config))
    retained = {
        "imageId": "sha256:" + "c" * 64,
        "imageBuildSourceHead": case.runtime["sourceHead"],
        "provenanceFile": str(bundle / "retained-image.json"),
    }
    monkeypatch.setattr(retained_image, "load_retained_image", lambda *a, **k: retained)
    image_plan = local_image.build_plan(
        case.runtime, case.config, case.plan["before"], egress_ipv4="8.8.4.4",
        retained_image=Path(str(retained["provenanceFile"])), continuation=plan_path,
    )
    approval = local_image.build_approval(
        image_plan, issued_at="2030-01-01T00:00:00Z", expires_at="2030-01-01T01:00:00Z",
        restore_until="2030-01-01T05:00:00Z",
    )
    for path in (folder / "local-image-plan.json", output / "plan.json"):
        write(path, image_plan)
    for path in (folder / "local-image-approval.json", output / "approval.json"):
        write(path, approval)
    marker = folder / "local-image-attempt.json"
    write(marker, {"planSha256": image_plan["planSha256"],
                   "approvalSha256": approval["approvalSha256"]})
    for name, value in {"openBody": image_plan["openBody"],
                        "restoreBody": image_plan["restoreBody"],
                        "restore-scope": image_plan["restoreBody"]}.items():
        write(output / f"{name}.json", value)
    tail = ("--url", str(image_plan["registryUrl"]), "--subscription",
            case.runtime["subscriptionId"])
    get = ("az", "rest", "--method", "get", *tail, "--output", "json")
    commands = [
        ("docker", "image", "inspect", str(retained["imageId"])), get,
        ("az", "rest", "--method", "patch", *tail, "--body", f"@{output / 'openBody.json'}",
         "--output", "json"), get, ("docker", "info", "--format", "{{json .}}"),
        ("git", "-C", str(local_image.ROOT), *local_image.ARCHIVE_OPTIONS, "archive",
         "--format=tar", "--output", str(output / "source.tar"), recovery.PRIOR_HEAD,
         "--", *BUILD_INPUTS),
        ("git", "-C", str(local_image.ROOT), "ls-tree", "-r", "--full-tree",
         recovery.PRIOR_HEAD, "--", *BUILD_INPUTS),
        ("az", "rest", "--method", "patch", *tail, "--body", f"@{output / 'restoreBody.json'}",
         "--output", "json"), get,
    ]
    provider = Provider(case)
    for index, command in enumerate(commands, 1):
        write(output / f"{index:02}-intent.json", {
            "command": command, "approvalSha256": approval["approvalSha256"],
            "intentAtUtc": f"2030-01-01T00:00:{index:02}Z",
        })
        response = provider.run(command)
        write(output / f"{index:02}-response.json", response)
        if index in {2, 9}:
            write(output / ("fresh-before.json" if index == 2 else "restored.json"),
                  json.loads(cast(str, response["stdout"])))
    operator._stage_record(bundle / "local-image-stage-pause.json", "stage-pause", {
        "version": "m7.8-protected-stage-pause-v1", "operation": "local-image",
        "bindings": operator._stage_bindings(case.config, case.runtime, case.ledger),
        "attemptSha256": recovery._file_hash(marker),
        "authorizationSha256": approval["approvalSha256"], "failedExecution": None,
        "failedAtUtc": "2030-01-01T00:00:10Z", "recoveryUntilUtc": "2030-01-01T00:15:10Z",
        "maximumRetryDispatches": 1,
    })
    return plan_path


def test_exact_nine_command_failed_attempt_replays_without_extraction(prior: Path) -> None:
    record = recovery.build_prior(prior)
    recovery.validate_prior(record)
    pause = recovery._read(Path(str(record["pauseFile"])))
    assert recovery.bound_pause_matches(record, pause)
    assert not recovery.bound_pause_matches(record, {**pause, "operation": "bootstrap"})
    assert not (prior.parent / "local-image/source").exists()
    assert not (prior.parent / "local-image/completed.json").exists()


@pytest.mark.parametrize("defect", [
    "push", "extra", "missing", "lost", "authorization", "expired", "restore", "snapshot",
    "archive", "pause", "marker", "ledger", "body", "source",
])
def test_changed_failed_history_cannot_be_admitted(prior: Path, defect: str) -> None:
    record = recovery.build_prior(prior)
    output = prior.parent / "local-image"
    if defect in {"push", "authorization", "expired", "source"}:
        path = output / ("06-intent.json" if defect == "source" else "03-intent.json")
        data = recovery._read(path)
        if defect == "push":
            data["command"] = ["docker", "push", "unapproved"]
        elif defect == "authorization":
            data["approvalSha256"] = "b" * 64
        elif defect == "expired":
            data["intentAtUtc"] = "2030-01-01T02:00:00Z"
        else:
            command = cast(list[str], data["command"])
            command[command.index(recovery.PRIOR_HEAD)] = "b" * 40
        write(path, data)
    elif defect == "extra":
        write(output / "10-intent.json", {"command": ["docker", "push"]})
    elif defect == "missing":
        (output / "07-response.json").unlink()
    elif defect == "lost":
        write(output / "03-response.json", {"exitCode": 1, "stdout": "", "stderr": "lost"})
    elif defect in {"restore", "snapshot"}:
        path = output / ("09-response.json" if defect == "restore" else "restored.json")
        data = recovery._read(path)
        actual = json.loads(cast(str, data["stdout"])) if defect == "restore" else data
        local_image._object(actual["properties"])["publicNetworkAccess"] = "Enabled"
        if defect == "restore":
            data["stdout"] = json.dumps(actual)
        write(path, data)
    elif defect == "archive":
        (output / "source.tar").write_bytes(b"invalid archive")
    elif defect == "pause":
        path = Path(str(record["pauseFile"]))
        data = recovery._read(path)
        data["attemptSha256"] = "b" * 64
        write(path, data)
    elif defect == "marker":
        write(prior.parent / "local-image-attempt.json", {})
    elif defect == "ledger":
        write(Path(str(recovery._read(prior)["ledgerFile"])), {})
    else:
        write(output / "restoreBody.json", {})
    with pytest.raises((CampaignError, OSError)):
        recovery.build_prior(prior)
    if defect != "ledger":
        with pytest.raises((CampaignError, OSError)):
            recovery.validate_prior(record)


def test_changed_bound_diagnostic_file_is_rejected(prior: Path) -> None:
    record = recovery.build_prior(prior)
    write(prior.parent / "extra-review.json", {"added": True})
    with pytest.raises(CampaignError):
        recovery.validate_prior(record)


def test_receipt_is_closed(prior: Path) -> None:
    record = recovery.build_prior(prior)
    record["extra"] = True
    record["priorAttemptSha256"] = recovery._hash({
        key: value for key, value in record.items() if key != "priorAttemptSha256"
    })
    with pytest.raises(CampaignError):
        recovery.validate_prior(record)
