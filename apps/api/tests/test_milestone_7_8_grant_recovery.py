from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from test_milestone_7_8_campaign_enablement import _config
from test_milestone_7_8_image_continuation import Case, write
from test_milestone_7_8_image_continuation import case as case
from test_milestone_7_8_image_replacement_ledger import NOW, image_decided
from test_milestone_7_8_migration_image_continuation import approved_image as approved_image

from infra.milestone_7_8 import image_continuation as continuation
from infra.milestone_7_8 import operator
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    load_ledger,
    save_ledger,
)


def two_replacements() -> Ledger:
    ledger = image_decided(_config())
    ledger.transition(Phase.DATABASE_BOOTSTRAPPED, NOW)
    ledger.record_image_replacement(
        "sha256:" + "b" * 64,
        "d" * 64,
        "e" * 64,
        conservative_estimate_usd="42",
        now=NOW + timedelta(seconds=1),
        at_phase=Phase.DATABASE_BOOTSTRAPPED,
    )
    ledger.record_image_replacement(
        "sha256:" + "e" * 64,
        "f" * 64,
        "1" * 64,
        conservative_estimate_usd="43",
        now=NOW + timedelta(seconds=2),
        at_phase=Phase.DATABASE_BOOTSTRAPPED,
        grant_recovery=True,
    )
    return ledger


def test_exact_second_replacement_preserves_first_and_rejects_third() -> None:
    ledger = two_replacements()
    assert ledger.previous_image_replacement is not None
    assert ledger.previous_image_replacement["replacementImageDigest"] == "sha256:" + "b" * 64
    assert ledger.image_scan_count == ledger.required_scan_count == 3
    assert ledger.resource_generation_count == 1 and ledger.image_generation_count == 0
    ledger._validate_image_history(image_reached=True)
    with pytest.raises(CampaignError, match="exactly one prior"):
        ledger.record_image_replacement(
            "sha256:" + "2" * 64,
            "3" * 64,
            "4" * 64,
            conservative_estimate_usd="44",
            now=NOW + timedelta(seconds=3),
            at_phase=Phase.DATABASE_BOOTSTRAPPED,
            grant_recovery=True,
        )


@pytest.mark.parametrize(
    "key",
    [
        "replacementImageDigest",
        "replacementScanEvidenceSha256",
        "replacementConservativeEstimateUsd",
    ],
)
def test_second_replacement_rejects_altered_prior_binding(key: str) -> None:
    ledger = two_replacements()
    assert ledger.previous_image_replacement is not None
    ledger.previous_image_replacement[key] = (
        "sha256:" + "2" * 64
        if key.endswith("Digest")
        else "3" * 64
        if key.endswith("Sha256")
        else "41"
    )
    with pytest.raises(CampaignError, match="predecessor"):
        ledger._validate_image_history(image_reached=True)


def grant_context(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
) -> tuple[Path, dict[str, str], CampaignConfig, Ledger]:
    path, _, runtime, config, ledger = approved_image
    plan = continuation.load_plan(path)
    consumed = operator._stage_record(
        path.parent.parent / "migrate-stage-retry-intent.json",
        "stage-retry-intent",
        {
            "operation": "migrate",
            "bindings": operator._stage_bindings(config, runtime, ledger),
            "authorizationSha256": "a" * 64,
        },
    )
    failed = write(path.parent / "failed-execution.json", {"observedAtUtc": NOW.isoformat()})
    plan.update(
        {
            "version": continuation.GRANT_VERSION,
            "consumedRetryIntentSha256": consumed["recordSha256"],
            "consumedRetryExecution": "failed-consumed-retry",
            "failedExecutionReadbackFile": str(failed),
            "previousPlanFile": str(path),
            "cleanupMustBeginByUtc": (NOW + timedelta(minutes=20)).isoformat(),
        }
    )
    return path, runtime, config, ledger


def test_grant_window_is_separate_bound_to_consumed_retry_and_manifest(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
) -> None:
    path, runtime, config, ledger = grant_context(approved_image)
    record = continuation.build_grant_retry_approval(
        path,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    write(path.parent / "grant-retry-approval.json", record)
    transition = continuation.grant_retry_transition(path, runtime, config, ledger)
    assert transition["grantOnly"] is True
    assert transition["originalConsumedRetryIntentSha256"] == record["consumedRetryIntentSha256"]
    assert str(transition["replacementImageReference"]).endswith("@sha256:" + "2" * 64)
    assert transition["recoveryDirectory"] == str(path.parent / "grant-recovery")
    assert record["requiredRevision"] == "20260726_0029"
    assert record["bootstrapReplayAllowed"] is record["alembicReplayAllowed"] is False
    assert not (path.parent / "grant-recovery/migrate-stage-attempt.json").exists()
    with pytest.raises(CampaignError, match="already exists"):
        continuation.build_grant_retry_approval(
            path,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )


def test_grant_window_cannot_cross_cleanup_start(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
) -> None:
    path, *_ = grant_context(approved_image)
    with pytest.raises(CampaignError, match="approved cutoff"):
        continuation.build_grant_retry_approval(
            path,
            issued_at=NOW + timedelta(minutes=10),
            expires_at=NOW + timedelta(minutes=25),
        )


@pytest.mark.parametrize(
    "key", ["consumedRetryIntentSha256", "imageDigest", "alembicReplayAllowed"]
)
def test_grant_authority_rejects_changed_consumed_history_or_image(
    approved_image: tuple[Path, Path, dict[str, str], CampaignConfig, Ledger],
    key: str,
) -> None:
    path, runtime, config, ledger = grant_context(approved_image)
    record = continuation.build_grant_retry_approval(
        path,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    record[key] = True if key == "alembicReplayAllowed" else "altered"
    body = {name: value for name, value in record.items() if name != "authorizationSha256"}
    record["authorizationSha256"] = continuation._hash(body)
    write(path.parent / "grant-retry-approval.json", record)
    with pytest.raises(CampaignError, match="authority or accepted image"):
        continuation.grant_retry_transition(path, runtime, config, ledger)


def test_normal_image_admission_preserves_first_replacement_and_updates_only_ten_existing_resources(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = CampaignConfig.from_json(case.folder / "cost.json", allow_expired=True)
    ledger = image_decided(original)
    ledger.transition(Phase.DATABASE_BOOTSTRAPPED, NOW)
    ledger.record_image_replacement(
        continuation.ORIGINAL_IMAGE,
        "5" * 64,
        "6" * 64,
        conservative_estimate_usd=original.conservative_estimate_usd,
        now=NOW + timedelta(seconds=1),
        at_phase=Phase.DATABASE_BOOTSTRAPPED,
    )
    first = dict(ledger.image_replacement or {})
    save_ledger(case.folder / "ledger.json", ledger)
    plan = continuation._read(case.plan)
    plan.update(
        {
            "version": continuation.GRANT_VERSION,
            "originalImageDigest": continuation.ORIGINAL_IMAGE,
            "baselineLedger": continuation._read(case.folder / "ledger.json"),
            "baselineLedgerFileSha256": continuation._file_hash(case.folder / "ledger.json"),
            "previousPlanFile": str(case.folder / "prior-plan.json"),
        }
    )
    prior: dict[str, object] = {"prior": True}
    # The accepted prior-image/plan proof is a separate boundary; this test drives
    # the actual operator, ten scoped updates, preserved readbacks and new receipt.
    monkeypatch.setattr(
        continuation, "load_plan", lambda path: prior if path.name == "prior-plan.json" else plan
    )
    monkeypatch.setattr(
        continuation,
        "_effective",
        lambda value: (case.runtime, original if value is prior else case.config),
    )
    monkeypatch.setattr(continuation, "_plan_source", lambda _: case.runtime["sourceHead"])
    assert case.invoke(monkeypatch) == 0
    admitted = load_ledger(case.folder / "ledger.json", case.config)
    assert admitted.previous_image_replacement == first
    assert admitted.image_scan_count == admitted.required_scan_count == 3
    assert admitted.phase == Phase.DATABASE_BOOTSTRAPPED
    assert case.provider.patches == 10
    continuation.validate_admission(case.plan, case.runtime, case.config, admitted)
