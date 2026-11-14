from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.milestone_7_8 import operator, workload_recovery
from infra.milestone_7_8.campaign import (
    ORDER,
    CampaignConfig,
    Ledger,
    Phase,
    load_ledger,
    save_ledger,
)
from infra.milestone_7_8.controller_renewal import _durable_record
from test_milestone_7_8_campaign_enablement import _config, _write_execution_authorization
from test_milestone_7_8_measurement_handoff import DIGEST, RUNTIME, _result


@pytest.mark.parametrize("defect", [
    None, "occupied", "ambiguous", "readback", "wrong-plan", "protection-loss",
])
def test_real_operator_admits_only_complete_workload_repair_then_unlocks_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    defect: str | None,
) -> None:
    now = datetime.now(UTC)
    deadline = (now + timedelta(hours=3)).replace(second=0, microsecond=0)
    def stamp(date: datetime) -> str:
        return date.isoformat(timespec="seconds").replace("+00:00", "Z")

    config = _config(cleanup_deadline_utc=stamp(deadline))
    runtime = {**RUNTIME, "cleanupAuthorityExpiresUtc": stamp(deadline + timedelta(hours=1))}
    folder = tmp_path / "workload-recovery"
    folder.mkdir()
    history = tmp_path / "workload-mount-diagnosis/resources"
    history.mkdir(parents=True)
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.bind_cleanup_region(config)
    ledger.bind_deadline(config.cleanup_deadline_utc)
    for phase in ORDER[1: ORDER.index(Phase.INFRASTRUCTURE_DEPLOYED) + 1]:
        if phase is Phase.CLEANUP_ARMED:
            ledger.record_cleanup_arm_evidence("a" * 64)
        ledger.transition(phase, now)
    ledger_path = tmp_path / "ledger.json"
    save_ledger(ledger_path, ledger)
    plan_path = folder / "plan.json"
    pause = operator._stage_record(tmp_path / "image-decision-stage-pause.json", "stage-pause", {
        "version": "m7.8-protected-stage-pause-v1", "operation": "image-decision",
        "bindings": {}, "attemptSha256": "a" * 64, "authorizationSha256": "b" * 64,
        "failedExecution": None, "failedAtUtc": stamp(now - timedelta(minutes=40)),
        "recoveryUntilUtc": stamp(now - timedelta(minutes=25)), "maximumRetryDispatches": 1,
    })
    monkeypatch.setattr(workload_recovery, "PRIVATE", tmp_path)
    monkeypatch.setattr(workload_recovery, "_binding", lambda *_: {
        "imageDigest": DIGEST, "scanSha256": "f" * 64,
        "cleanupArmEvidenceSha256": ledger.cleanup_arm_evidence_sha256,
        "filesSha256": {"image-decision-stage-pause.json": workload_recovery._hash(
            tmp_path / "image-decision-stage-pause.json",
        )},
    })
    monkeypatch.setattr(workload_recovery, "_template", lambda _: ({"resources": []}, {}))
    plan = workload_recovery.build_plan(plan_path, runtime, config, ledger,
                                       deploy_until=stamp(now + timedelta(hours=1)))
    _durable_record(plan_path, plan)
    auth_path = tmp_path / "auth.json"
    _write_execution_authorization(auth_path, config, runtime, expires_at=stamp(deadline),
                                   operations=["image-decision", "bootstrap", "cleanup"])
    targets = workload_recovery._targets(runtime, config)
    for key, field in workload_recovery.JOB_FIELDS:
        if key not in workload_recovery.MISSING:
            _durable_record(history / f"{field}-result.json", _result({"name": targets[key]}))
    monkeypatch.setattr(workload_recovery, "_observed_workload", lambda value, **_: json.loads(
        str(value["stdout"]),
    ))
    monkeypatch.setattr("infra.milestone_7_8.workload_repair_template.validate_repaired_mount",
                        lambda _: None)
    monkeypatch.setattr(CampaignConfig, "from_json", lambda *_a, **_kw: config)
    monkeypatch.setattr(operator, "load_runtime", lambda *_: runtime)
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_: None)
    def verify_protection(*_: object) -> None:
        if defect == "protection-loss":
            raise operator._ProtectedStageExpired("simulated cleanup protection loss")

    cleanup_calls = []

    def cleanup(*args: object) -> None:
        assert defect == "protection-loss"
        authorize = args[-1]
        assert callable(authorize)
        authorize()
        cleanup_calls.append(True)

    monkeypatch.setattr(operator, "_verify_retry_protection", verify_protection)
    monkeypatch.setattr(operator, "start_failure_cleanup", cleanup)
    monkeypatch.setattr(operator, "validate_operation_results", lambda *_a, **_kw: None)

    commands: list[tuple[str, ...]] = []
    repairs = 0

    class Provider:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            nonlocal repairs
            commands.append(command)
            name = command[command.index("--name") + 1]
            if command[:4] == ("az", "deployment", "sub", "create"):
                repairs += 1
                assert repairs == 1, "uncertain mutation must never repeat"
                assert (folder / "intent.json").exists()
                if defect == "ambiguous":
                    raise OSError("synthetic response loss")
                return _result({"name": name, "properties": {"provisioningState": "Succeeded"}})
            if command[:4] == ("az", "containerapp", "job", "start"):
                return _result({"name": "same-scope-bootstrap",
                                "properties": {"status": "Succeeded"}})
            key = next(key for key, path in targets.items() if path.endswith("/" + name))
            if ((not repairs and key in workload_recovery.MISSING and defect != "occupied")
                    or (repairs and key == "apiApp" and defect == "readback")):
                return {"exitCode": 1, "stdout": "", "stderr": f"(ResourceNotFound) {name}"}
            return _result({"name": targets[key]})

    monkeypatch.setattr(operator, "SubprocessRunner", lambda **_: Provider())
    args = [
        "--config", str(tmp_path / "campaign-cost.json"),
        "--runtime", str(tmp_path / "runtime.json"),
        "--ledger", str(ledger_path), "--workload-recovery", str(plan_path),
        "--workload-recovery-sha256",
        "0" * 64 if defect == "wrong-plan" else str(plan["planSha256"]),
        "--authorization", str(auth_path), "--execute",
    ]
    monkeypatch.setattr(sys, "argv", ["operator", "image-decision", *args])
    assert operator.main() == (0 if defect is None else 2), capsys.readouterr()
    expected_phase = {None: Phase.IMAGE_DECIDED, "protection-loss": Phase.CLEANING}
    assert load_ledger(ledger_path, config).phase == expected_phase.get(
        defect, Phase.INFRASTRUCTURE_DEPLOYED,
    )
    assert (folder / "completed.json").exists() is (defect is None)
    assert operator._read_stage_record(
        tmp_path / "image-decision-stage-pause.json", "stage-pause",
    ) == pause
    if defect == "ambiguous":
        assert operator.main() == 2
    assert repairs == int(defect not in {"occupied", "wrong-plan", "protection-loss"})
    assert len(cleanup_calls) == int(defect == "protection-loss")
    assert not any("delete" in command for command in commands)
    if defect is None:
        updated = load_ledger(ledger_path, config)
        assert (updated.image_generation_count, updated.image_scan_count) == (0, 1)
        # Continue through the actual operator's source/pause admission. Stub
        # the independent database prerequisite, not its phase transition.
        monkeypatch.setattr(operator, "_database_prerequisites", lambda *_a, **_kw: None)
        monkeypatch.setattr(sys, "argv", ["operator", "bootstrap", *args])
        assert operator.main() == 0, capsys.readouterr()
        assert load_ledger(ledger_path, config).phase == Phase.DATABASE_BOOTSTRAPPED
