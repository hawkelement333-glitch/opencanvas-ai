from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import _config, _runtime
from test_milestone_7_8_image_continuation import document, write
from test_milestone_7_8_image_replacement_ledger import NOW, image_decided

from infra.milestone_7_8 import image_continuation as continuation
from infra.milestone_7_8 import operator
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, Ledger, Phase, save_ledger

SOURCE_RESOLVER = continuation._plan_source


@pytest.fixture
def approved_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, dict[str, str], CampaignConfig, Ledger]:
    folder = tmp_path / ".runtime/milestone_7_8/p-five/ca"
    folder.mkdir(parents=True)
    monkeypatch.setattr(continuation, "ROOT", tmp_path)
    config, runtime = _config(), _runtime()
    config = replace(config, cleanup_deadline_utc="2030-01-01T04:00:00Z")
    ledger = image_decided(config)
    ledger.transition(Phase.DATABASE_BOOTSTRAPPED, NOW)
    save_ledger(folder / "ledger.json", ledger)
    write(folder / "campaign-cost.json", document(config))
    write(folder / "runtime.json", runtime)
    attempt = operator._stage_record(folder / "migrate-stage-attempt.json", "stage-attempt", {
        "operation": "migrate", "bindings": operator._stage_bindings(config, runtime, ledger),
        "authorizationSha256": "a" * 64,
    })
    operator._stage_record(folder / "migrate-stage-pause.json", "stage-pause", {
        "operation": "migrate", "bindings": operator._stage_bindings(config, runtime, ledger),
        "attemptSha256": attempt["recordSha256"], "failedExecution": "old-failed",
    })
    write(folder / "workload-recovery/plan.json", {
        "filesSha256": {"image-decision-stage-pause.json": "b" * 64},
    })
    plan: dict[str, object] = {
        "version": continuation.MIGRATION_VERSION, "planSha256": "c" * 64,
        "runtimeFile": str(folder / "runtime.json"),
        "configFile": str(folder / "campaign-cost.json"),
        "ledgerFile": str(folder / "ledger.json"), "sourceHead": "d" * 40,
        "canonicalBuildInputSha256": "9" * 64,
        "amendmentSha256": "8" * 64,
        "failedMigrationExecution": "old-failed", "retainedImageId": "sha256:" + "1" * 64,
        "originalImageDigest": ledger.image_digest,
        "migrationPauseSha256": continuation._file_hash(folder / "migrate-stage-pause.json"),
        "workloadRecoveryPlanFile": str(folder / "workload-recovery/plan.json"),
    }
    path = write(folder / "migration-image-continuation/plan.json", plan)
    receipt = write(path.parent / "completed.json", {"imageDigest": "sha256:" + "2" * 64})
    approval = write(path.parent / "explicit-retry-approval.json", {
        "version": "m7.8-explicit-migration-retry-approval-v1", "planSha256": plan["planSha256"],
        "operatorSourceHead": plan["sourceHead"], "failedExecution": "old-failed",
        "scope": "one-guarded-migration-retry", "maximumRetryDispatches": 1,
        "userText": "Synthetic explicit approval for one bounded corrected migration retry.",
    })
    # This suite exercises the separate window contract. Source, registry and
    # preservation admission are independently exercised by the normal operator suite.
    monkeypatch.setattr(continuation, "load_plan", lambda _: plan)
    monkeypatch.setattr(continuation, "_plan_source", lambda _: plan["sourceHead"])
    monkeypatch.setattr(continuation, "_effective", lambda _: (runtime, config))
    monkeypatch.setattr(continuation, "validate_admission", lambda *_: continuation._read(receipt))
    return path, approval, runtime, config, ledger


def test_separate_retry_window_binds_manifest_not_docker_id_and_preserves_history(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
) -> None:
    path, approval, runtime, config, ledger = approved_image
    old_pause = path.parent.parent / "migrate-stage-pause.json"
    original = old_pause.read_bytes()
    record = continuation.build_migration_retry_approval(
        path, explicit_approval=approval, issued_at=NOW, expires_at=NOW + timedelta(minutes=15),
    )
    write(path.parent / "migration-retry-approval.json", record)
    transition = continuation.migration_retry_transition(path, runtime, config, ledger)
    assert transition is not None
    assert str(transition["replacementImageReference"]).endswith("@sha256:" + "2" * 64)
    assert record["imageDigest"] != continuation.load_plan(path)["retainedImageId"]
    assert old_pause.read_bytes() == original
    continuation.validate_migration_retry_window(transition, now=NOW + timedelta(minutes=1))
    with pytest.raises(CampaignError, match="dispatch window"):
        continuation.validate_migration_retry_window(transition, now=NOW + timedelta(minutes=15))
    # Reconciliation does not invent an earlier completion or require a new mutation window.
    assert continuation.migration_retry_transition(path, runtime, config, ledger) == transition


@pytest.mark.parametrize("minutes", [0, 16, 241])
def test_retry_window_is_positive_and_at_most_fifteen_minutes(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger], minutes: int,
) -> None:
    path, approval, *_ = approved_image
    with pytest.raises(CampaignError, match="bounded dispatch window"):
        continuation.build_migration_retry_approval(
            path, explicit_approval=approval, issued_at=NOW,
            expires_at=NOW + timedelta(minutes=minutes),
        )


@pytest.mark.parametrize("defect", ["scope", "planSha256", "failedExecution", "extra"])
def test_wrong_explicit_approval_cannot_open_retry_window(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger], defect: str,
) -> None:
    path, approval, *_ = approved_image
    payload = continuation._read(approval)
    payload[defect] = "wrong"
    write(approval, payload)
    with pytest.raises(CampaignError, match="separate exact explicit approval"):
        continuation.build_migration_retry_approval(
            path, explicit_approval=approval, issued_at=NOW, expires_at=NOW + timedelta(minutes=15),
        )


@pytest.mark.parametrize(
    "name", ["migrate-stage-retry-intent.json", "migrate-stage-retry-start.json"],
)
def test_existing_retry_cannot_receive_another_window(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger], name: str,
) -> None:
    path, approval, *_ = approved_image
    write(path.parent.parent / name, {"already": "dispatched or indeterminate"})
    with pytest.raises(CampaignError, match="already been consumed"):
        continuation.build_migration_retry_approval(
            path, explicit_approval=approval, issued_at=NOW, expires_at=NOW + timedelta(minutes=15),
        )


@pytest.mark.parametrize("name", ["migrate-stage-pause.json", "migrate-stage-attempt.json"])
def test_original_history_change_invalidates_separate_approval(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger], name: str,
) -> None:
    path, approval, runtime, config, ledger = approved_image
    record = continuation.build_migration_retry_approval(
        path, explicit_approval=approval, issued_at=NOW, expires_at=NOW + timedelta(minutes=15),
    )
    write(path.parent / "migration-retry-approval.json", record)
    original = path.parent.parent / name
    # Even a semantically identical reserialization changes the approved bytes.
    original.write_text(json.dumps(json.loads(original.read_text()), indent=2), encoding="utf-8")
    with pytest.raises(CampaignError, match="original evidence binding"):
        continuation.migration_retry_transition(path, runtime, config, ledger)


def test_cost_preserves_prior_allowances_and_adds_exact_prerequisite(tmp_path: Path) -> None:
    before = document(_config())
    original = write(tmp_path / "original.json", before)
    after = json.loads(json.dumps(before))
    items = cast(list[dict[str, object]], after["resourceItems"])
    items.append({"name": "corrected-migration-prerequisite", "fixedUsd": "0.0378",
                  "hourlyUsd": "0", "hours": 1, "pricedAtUtc": NOW.isoformat()})
    subtotal = sum(Decimal(str(item["fixedUsd"]))
                   + Decimal(str(item["hourlyUsd"])) * Decimal(str(item["hours"]))
                   for item in items)
    after["conservativeEstimateUsd"] = str(
        (subtotal * Decimal("1.25")).quantize(Decimal(".0001"), rounding=ROUND_CEILING)
    )
    replacement = write(tmp_path / "replacement.json", after)
    continuation._migration_cost(original, replacement)
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    items[0]["name"] = "unapproved-reallocation"
    write(replacement, after)
    with pytest.raises(CampaignError, match="preserve all prior allowances"):
        continuation._migration_cost(original, replacement)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash


def amend_source(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    path, approval, *_ = approved_image
    original = continuation.build_migration_retry_approval(
        path, explicit_approval=approval, issued_at=NOW, expires_at=NOW + timedelta(minutes=15),
    )
    write(path.parent / "migration-retry-approval.json", original)
    standing = write(path.parent / "source-approval.json", {
        "planSha256": continuation.load_plan(path)["planSha256"],
        "scope": "unused-migration-retry-operator-correction", "userText": "Synthetic approval",
    })
    monkeypatch.setattr(continuation, "_inspect_amended_source", lambda _: "e" * 40)
    monkeypatch.setattr(continuation, "_predispatch_capture_files", lambda *_: {
        str(approval): continuation._file_hash(approval),
    })
    record = continuation.build_operator_source_amendment(path, approval=standing)
    write(path.parent / "operator-source-amendment.json", record)
    monkeypatch.setattr(continuation, "_plan_source", SOURCE_RESOLVER)
    return record


def test_operator_source_amendment_retains_image_source_and_old_dispatch_window(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _, runtime, config, ledger = approved_image
    record = amend_source(approved_image, monkeypatch)
    plan = continuation.load_plan(path)
    assert continuation._plan_source(plan) == "e" * 40
    assert plan["sourceHead"] == "d" * 40
    transition = continuation.migration_retry_transition(path, runtime, config, ledger)
    assert transition is not None
    assert transition["operatorSourceHead"] == record["operatorSourceHead"]
    assert transition["expiresAtUtc"] == (NOW + timedelta(minutes=15)).isoformat()
    _, _, cleanup_ledger = continuation.load_context(
        path, Path(str(plan["runtimeFile"])), Path(str(plan["configFile"])),
        Path(str(plan["ledgerFile"])), operation="cleanup",
    )
    assert cleanup_ledger.phase == Phase.DATABASE_BOOTSTRAPPED


@pytest.mark.parametrize("defect", ["source", "capture", "approval", "unknown-field"])
def test_source_amendment_tampering_does_not_admit_new_operator(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
    monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    path, *_ = approved_image
    record = amend_source(approved_image, monkeypatch)
    if defect == "source":
        monkeypatch.setattr(continuation, "_inspect_amended_source", lambda _: "f" * 40)
    elif defect == "capture":
        monkeypatch.setattr(continuation, "_predispatch_capture_files", lambda *_: {})
    elif defect == "approval":
        write(Path(str(record["approvalFile"])), {"scope": "wrong"})
    else:
        record["unexpected"] = True
        record["amendmentSha256"] = continuation._hash({
            key: value for key, value in record.items() if key != "amendmentSha256"
        })
        write(path.parent / "operator-source-amendment.json", record)
    with pytest.raises(CampaignError, match="source amendment"):
        continuation._plan_source(continuation.load_plan(path))


def test_expired_unused_window_can_be_superseded_once_without_rewriting_original(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, explicit, runtime, config, ledger = approved_image
    amend_source(approved_image, monkeypatch)
    old_path = path.parent / "migration-retry-approval.json"
    old_bytes = old_path.read_bytes()
    replacement = write(path.parent / "replacement-explicit.json", continuation._read(explicit))
    with pytest.raises(CampaignError, match="still open"):
        continuation.build_migration_retry_supersession(
            path, explicit_approval=replacement, issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )
    supersession = continuation.build_migration_retry_supersession(
        path, explicit_approval=replacement, issued_at=NOW + timedelta(minutes=16),
        expires_at=NOW + timedelta(minutes=31),
    )
    write(path.parent / "migration-retry-supersession.json", supersession)
    transition = continuation.migration_retry_transition(path, runtime, config, ledger)
    assert transition is not None
    continuation.validate_migration_retry_window(transition, now=NOW + timedelta(minutes=17))
    assert old_path.read_bytes() == old_bytes
    with pytest.raises(CampaignError, match="already exists"):
        continuation.build_migration_retry_supersession(
            path, explicit_approval=replacement, issued_at=NOW + timedelta(minutes=32),
            expires_at=NOW + timedelta(minutes=47),
        )


def test_supersession_rejects_any_recorded_retry_intent(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, explicit, *_ = approved_image
    amend_source(approved_image, monkeypatch)
    write(path.parent.parent / "migrate-stage-retry-intent.json", {"uncertain": True})
    with pytest.raises(CampaignError, match="already dispatched or indeterminate"):
        continuation.build_migration_retry_supersession(
            path, explicit_approval=explicit, issued_at=NOW + timedelta(minutes=16),
            expires_at=NOW + timedelta(minutes=31),
        )
