from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_8.campaign import (
    ORDER,
    RESIDUE_KEYS,
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    load_ledger,
    save_ledger,
    terminal_receipt,
)
from test_milestone_7_8_campaign_enablement import _config

NOW = datetime(2030, 1, 1, tzinfo=UTC)
OLD_DIGEST = "sha256:" + "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64
OLD_SCAN = "c" * 64
NEW_SCAN = "d" * 64
CONTINUATION = "e" * 64
NEW_ESTIMATE = "42.00"


def image_decided(config: CampaignConfig, *, built: bool = False) -> Ledger:
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.bind_cleanup_region(config)
    ledger.bind_deadline(config.cleanup_deadline_utc)
    for phase in ORDER[1 : ORDER.index(Phase.IMAGE_DECIDED) + 1]:
        if phase is Phase.CLEANUP_ARMED:
            ledger.record_cleanup_arm_evidence("f" * 64)
        if phase is Phase.IMAGE_DECIDED:
            ledger.record_image(OLD_DIGEST, built=built)
            ledger.record_image_scan(OLD_DIGEST, OLD_SCAN)
        ledger.transition(phase, NOW)
    return ledger


def replace_image(ledger: Ledger, *, at: datetime = NOW + timedelta(minutes=1)) -> None:
    ledger.record_image_replacement(
        NEW_DIGEST, NEW_SCAN, CONTINUATION, conservative_estimate_usd=NEW_ESTIMATE, now=at,
    )


@pytest.mark.parametrize("built", [False, True])
def test_one_replacement_preserves_original_image_and_counters(tmp_path: Path, built: bool) -> None:
    config = _config()
    ledger = image_decided(config, built=built)
    path = tmp_path / "ledger.json"
    save_ledger(path, ledger)
    old_bytes = path.read_bytes()
    assert "image_replacement" not in json.loads(old_bytes)
    ledger = load_ledger(path, config)
    replace_image(ledger)

    assert path.read_bytes() == old_bytes
    assert ledger.phase == Phase.IMAGE_DECIDED
    assert ledger.resource_generation_count == 1
    assert ledger.image_generation_count == int(built)
    assert ledger.image_scan_count == ledger.required_scan_count == 2
    assert ledger.image_replacement == {
        "previousImageDigest": OLD_DIGEST,
        "previousScanEvidenceSha256": OLD_SCAN,
        "previousConservativeEstimateUsd": config.conservative_estimate_usd,
        "replacementImageDigest": NEW_DIGEST,
        "replacementScanEvidenceSha256": NEW_SCAN,
        "replacementConservativeEstimateUsd": NEW_ESTIMATE,
        "continuationSha256": CONTINUATION,
        "recordedAtUtc": "2030-01-01T00:01:00Z",
    }

    save_ledger(path, ledger)
    with pytest.raises(CampaignError, match="ledger limits"):
        load_ledger(path, config)
    updated = replace(config, conservative_estimate_usd=NEW_ESTIMATE)
    assert load_ledger(path, updated) == ledger
    with pytest.raises(CampaignError, match="differs from the replacement"):
        load_ledger(path, replace(updated, image_digest=OLD_DIGEST))
    with pytest.raises(CampaignError, match="second image replacement"):
        replace_image(ledger)
    with pytest.raises(CampaignError, match="second image digest"):
        ledger.record_image(NEW_DIGEST, built=True)
    assert ledger.image_digest == NEW_DIGEST
    assert ledger.image_scan_evidence_sha256 == NEW_SCAN


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("continuationSha256", None),
        ("unexpected", "unexpected"),
        ("continuationSha256", "malformed"),
        ("previousImageDigest", NEW_DIGEST),
        ("previousScanEvidenceSha256", NEW_SCAN),
        ("replacementImageDigest", "sha256:" + "f" * 64),
        ("replacementScanEvidenceSha256", "f" * 64),
        ("previousConservativeEstimateUsd", "NaN"),
        ("replacementConservativeEstimateUsd", "50.01"),
        ("recordedAtUtc", "2029-12-31T23:59:59Z"),
    ],
)
def test_malformed_or_spliced_replacement_history_is_rejected(
    tmp_path: Path, key: str, value: str | None,
) -> None:
    config = _config()
    ledger = image_decided(config)
    replace_image(ledger)
    path = tmp_path / "ledger.json"
    save_ledger(path, ledger)
    data = json.loads(path.read_text(encoding="utf-8"))
    history = cast(dict[str, object], data["image_replacement"])
    if value is None:
        del history[key]
    else:
        history[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CampaignError, match="image replacement"):
        load_ledger(path, replace(config, conservative_estimate_usd=NEW_ESTIMATE))


def test_two_scans_without_replacement_are_rejected() -> None:
    config = _config()
    ledger = image_decided(config)
    ledger.image_scan_count = ledger.required_scan_count = 2
    with pytest.raises(CampaignError, match="image scan state"):
        ledger.validate_resume(config)


@pytest.mark.parametrize("phase", [Phase.INFRASTRUCTURE_DEPLOYED, Phase.DATABASE_BOOTSTRAPPED])
def test_replacement_is_rejected_outside_original_image_phase(phase: Phase) -> None:
    ledger = image_decided(_config())
    ledger.phase = phase.value
    with pytest.raises(CampaignError, match="original admitted image phase"):
        replace_image(ledger)


def test_migration_replacement_retains_bootstrap_and_predecessor_history(tmp_path: Path) -> None:
    config = _config()
    ledger = image_decided(config)
    bootstrap_at = NOW + timedelta(minutes=1)
    ledger.transition(Phase.DATABASE_BOOTSTRAPPED, bootstrap_at)
    transitions = list(ledger.transitions)
    replacement_at = bootstrap_at + timedelta(seconds=30)
    ledger.record_image_replacement(
        NEW_DIGEST, NEW_SCAN, CONTINUATION, conservative_estimate_usd=NEW_ESTIMATE,
        now=replacement_at, at_phase=Phase.DATABASE_BOOTSTRAPPED,
    )
    assert ledger.transitions == transitions
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED
    assert ledger.image_replacement is not None
    assert ledger.image_replacement["replacementPhase"] == Phase.DATABASE_BOOTSTRAPPED
    assert ledger.image_replacement["previousImageDigest"] == OLD_DIGEST
    assert ledger.image_replacement["previousScanEvidenceSha256"] == OLD_SCAN
    assert ledger.image_scan_count == ledger.required_scan_count == 2
    assert ledger.image_generation_count == 0 and ledger.resource_generation_count == 1
    ledger.transition(Phase.MIGRATED, replacement_at + timedelta(seconds=30))
    path = tmp_path / "ledger.json"
    save_ledger(path, ledger)
    updated = replace(config, conservative_estimate_usd=NEW_ESTIMATE)
    assert load_ledger(path, updated) == ledger

    ledger.image_replacement.pop("replacementPhase")
    save_ledger(path, ledger)
    with pytest.raises(CampaignError, match="timestamp differs from its phase"):
        load_ledger(path, updated)


@pytest.mark.parametrize("case", ["pre-bootstrap", "post-migration", "built-image"])
def test_migration_replacement_enforces_zero_build_and_exact_phase(case: str) -> None:
    ledger = image_decided(_config(), built=case == "built-image")
    if case != "pre-bootstrap":
        ledger.transition(Phase.DATABASE_BOOTSTRAPPED, NOW + timedelta(minutes=1))
    if case == "post-migration":
        ledger.transition(Phase.MIGRATED, NOW + timedelta(minutes=2))
    with pytest.raises(CampaignError, match="image replacement"):
        ledger.record_image_replacement(
            NEW_DIGEST, NEW_SCAN, CONTINUATION, conservative_estimate_usd=NEW_ESTIMATE,
            now=NOW + timedelta(minutes=3), at_phase=Phase.DATABASE_BOOTSTRAPPED,
        )
    assert ledger.image_digest == OLD_DIGEST and ledger.image_replacement is None


def test_startup_failure_finalizes_only_as_cleanup_with_replacement_history(tmp_path: Path) -> None:
    config = _config()
    ledger = image_decided(config)
    replace_image(ledger)
    then = NOW + timedelta(minutes=2)
    ledger.transition(Phase.CLEANING, then)
    ledger.transition(Phase.CLEANED, then)
    ledger.record_cleanup_disarm_evidence("f" * 64)
    ledger.transition(Phase.CLEANUP_DISARMED, then)
    ledger.verify_residue(dict.fromkeys(RESIDUE_KEYS, 0))
    ledger.transition(Phase.RESIDUE_VERIFIED, then)
    ledger.transition(Phase.FINALIZED, then)
    path = tmp_path / "ledger.json"
    save_ledger(path, ledger)
    finalized = load_ledger(path, replace(config, conservative_estimate_usd=NEW_ESTIMATE))
    receipt = terminal_receipt(finalized)
    assert receipt["status"] == "zero-residue"
    assert receipt["imageReplacement"] == ledger.image_replacement
    assert receipt["requiredScanCount"] == receipt["imageScanCount"] == 2
    assert receipt["imageGenerationCount"] == 0
    assert receipt["resourceGenerationCount"] == 1
    assert not any(entry["to"] == Phase.EVIDENCE_EXECUTED for entry in finalized.transitions)
    assert "observationsPassed" not in receipt
