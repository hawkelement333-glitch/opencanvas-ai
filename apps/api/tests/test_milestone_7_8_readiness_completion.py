from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_milestone_7_8_campaign_enablement import _config, _runtime

from infra.milestone_7_8 import image_continuation, operator
from infra.milestone_7_8.campaign import CampaignError, Ledger, Phase


def completion_case(tmp_path: Path, monkeypatch):
    config = _config(cleanup_deadline_utc="2030-01-01T01:00:00Z")
    runtime = _runtime()
    old, new = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.phase = Phase.MIGRATED.value
    ledger.image_digest = new
    ledger.cleanup_arm_evidence_sha256 = "a" * 64
    ledger.image_replacement = {"replacementPhase": Phase.MIGRATED.value}
    prior = operator._stage_bindings(replace(config, image_digest=old), runtime, ledger)
    commands = (("az", "synthetic", "--subscription", runtime["subscriptionId"]),)
    monkeypatch.setattr(operator, "command_plan", lambda *a, **k: (("az", "synthetic"),))
    monkeypatch.setattr(operator, "validate_evidence_execution_receipt", lambda *a, **k: None)
    (tmp_path / "managed-evidence-execution.json").write_text("validated receipt fixture")
    attempt = operator._stage_record(tmp_path / "evidence-stage-attempt.json", "stage-attempt", {
        "version": "m7.8-protected-stage-attempt-v1", "operation": "evidence",
        "bindings": prior, "commandSha256": operator._stage_hash("stage-command", commands),
        "authorizationSha256": "b" * 64, "startedAtUtc": "2030-01-01T00:01:00Z",
    })
    pause = operator._stage_record(tmp_path / "evidence-stage-pause.json", "stage-pause", {
        "version": "m7.8-protected-stage-pause-v1", "operation": "evidence",
        "bindings": prior, "attemptSha256": attempt["recordSha256"],
        "authorizationSha256": "b" * 64, "failedExecution": None,
        "failedAtUtc": "2030-01-01T00:02:00Z", "recoveryUntilUtc": "2030-01-01T00:17:00Z",
        "maximumRetryDispatches": 1,
    })
    origin = {
        "originalBindings": prior, "originalCommandSha256": attempt["commandSha256"],
        "originalAttemptSha256": attempt["recordSha256"],
        "originalPauseSha256": pause["recordSha256"], "continuationSha256": "c" * 64,
    }
    monkeypatch.setattr(image_continuation, "validate_readiness_evidence_origin",
                        lambda *a, **k: origin, raising=False)
    return config, runtime, ledger, origin


def test_corrected_image_completion_retains_original_attempt_and_pause(tmp_path, monkeypatch):
    config, runtime, ledger, origin = completion_case(tmp_path, monkeypatch)
    paths = [tmp_path / f"evidence-stage-{kind}.json" for kind in ("attempt", "pause")]
    before = [path.read_bytes() for path in paths]
    operator._reconcile_evidence_stage_completion(tmp_path, config, runtime, ledger, {})
    completed = json.loads((tmp_path / "evidence-stage-recovery-completed.json").read_text())
    assert completed["imageContinuationSha256"] == origin["continuationSha256"]
    assert completed["bindings"]["imageDigest"] == ledger.image_digest
    assert [path.read_bytes() for path in paths] == before
    # Subsequent disposal revalidates the same linkage without a second attempt.
    ledger.phase = Phase.EVIDENCE_EXECUTED.value
    operator._reconcile_evidence_stage_completion(tmp_path, config, runtime, ledger)


@pytest.mark.parametrize("field", ["originalAttemptSha256", "originalPauseSha256",
                                   "originalCommandSha256", "originalBindings"])
def test_corrected_image_completion_rejects_changed_origin(tmp_path, monkeypatch, field):
    config, runtime, ledger, origin = completion_case(tmp_path, monkeypatch)
    origin[field] = {} if field == "originalBindings" else "d" * 64
    with pytest.raises(CampaignError):
        operator._reconcile_evidence_stage_completion(tmp_path, config, runtime, ledger, {})
    assert not (tmp_path / "evidence-stage-recovery-completed.json").exists()


def test_old_image_history_without_validated_correction_remains_rejected(tmp_path, monkeypatch):
    config, runtime, ledger, _ = completion_case(tmp_path, monkeypatch)
    ledger.image_replacement = None
    with pytest.raises(CampaignError, match="original attempt binding"):
        operator._reconcile_evidence_stage_completion(tmp_path, config, runtime, ledger, {})


@pytest.mark.parametrize("missing", [("attempt",), ("pause",), ("attempt", "pause")])
def test_corrected_image_cannot_use_legacy_missing_history_path(tmp_path, monkeypatch, missing):
    config, runtime, ledger, _ = completion_case(tmp_path, monkeypatch)
    for kind in missing:
        (tmp_path / f"evidence-stage-{kind}.json").unlink()
    with pytest.raises(CampaignError, match="original history"):
        operator._reconcile_evidence_stage_completion(tmp_path, config, runtime, ledger, {})
