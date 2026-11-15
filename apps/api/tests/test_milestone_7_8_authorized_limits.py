"""Explicit fresh-campaign authority must not enlarge historical limits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_milestone_7_8_campaign_enablement import (
    NOW,
    _config,
    _runtime,
    _write_execution_authorization,
)

from infra.milestone_7_8 import operator, prepare
from infra.milestone_7_8.campaign import CampaignError, load_ledger, save_ledger
from infra.milestone_7_8.cleanup_controller import (
    cleanup_authority_sha256,
    load_execution_authorization,
)


@pytest.mark.parametrize(
    "ceiling,estimate,accepted",
    [("50.00", "50.00", True), ("50.00", "50.01", False),
     ("56.51", "56.51", True), ("56.51", "56.52", False)],
)
def test_estimate_uses_selected_ceiling(ceiling: str, estimate: str, accepted: bool) -> None:
    config = _config(authorized_ceiling_usd=ceiling, conservative_estimate_usd=estimate)
    if accepted:
        config.validate()
    else:
        with pytest.raises(CampaignError, match="ceiling"):
            config.validate()


@pytest.mark.parametrize("limits", [
    {"authorized_ceiling_usd": "56.52"}, {"authorized_ceiling_usd": "NaN"},
    {"maximum_hours": 9}, {"maximum_hours": True},
])
def test_unapproved_limits_are_rejected(limits: dict[str, object]) -> None:
    with pytest.raises(CampaignError, match="approved"):
        _config(**limits).validate()


def test_ledger_keeps_selected_ceiling_and_rejects_substitution(tmp_path: Path) -> None:
    config = _config(authorized_ceiling_usd="56.51", maximum_hours=8)
    path = tmp_path / "ledger.json"
    ledger = load_ledger(path, config)
    assert ledger.authorized_ceiling_usd == "56.51"
    ledger.actual_cost_usd = "56.51"
    save_ledger(path, ledger)
    load_ledger(path, config)
    with pytest.raises(CampaignError, match="ledger limits"):
        load_ledger(path, replace(config, authorized_ceiling_usd="50.00"))
    ledger.actual_cost_usd = "56.52"
    save_ledger(path, ledger)
    with pytest.raises(CampaignError, match="actual cost"):
        load_ledger(path, config)


@pytest.mark.parametrize("field,value", [
    ("authorizedCeilingUsd", "50.00"), ("maximumHours", 4), ("maximumHours", True),
])
def test_fresh_authorization_binds_exact_limits(
    tmp_path: Path, field: str, value: object,
) -> None:
    config = _config(authorized_ceiling_usd="56.51", maximum_hours=8)
    runtime = _runtime()
    path = tmp_path / "authorization.json"
    _write_execution_authorization(
        path, config, runtime, expires_at="2030-01-01T04:30:00Z", operations=["deploy"],
    )
    # A newly hashed legacy authorization still cannot approve new limits.
    with pytest.raises(CampaignError, match="not exact"):
        load_execution_authorization(
            path, config=config, runtime=runtime, operation="deploy", now=NOW,
        )
    document = json.loads(path.read_text())
    document.update(version="m7.8-execution-authorization-v6",
                    authorizedCeilingUsd="56.51", maximumHours=8)

    def write() -> None:
        unsigned = {k: v for k, v in document.items() if k != "authorizationSha256"}
        document["authorizationSha256"] = hashlib.sha256(
            b"m7.8/execution-authorization/v6\0"
            + json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        path.write_text(json.dumps(document))

    write()
    load_execution_authorization(path, config=config, runtime=runtime, operation="deploy", now=NOW)
    document[field] = value
    write()
    with pytest.raises(CampaignError, match="not exact"):
        load_execution_authorization(
            path, config=config, runtime=runtime, operation="deploy", now=NOW,
        )


def test_fresh_cleanup_parameters_tags_and_authority_bind_selected_ceiling() -> None:
    legacy = _config()
    fresh = replace(legacy, authorized_ceiling_usd="56.51", maximum_hours=8)
    runtime = _runtime()
    assert operator.cleanup_job_parameters(legacy, runtime)["CostCeilingCents"] == "5000"
    assert operator.cleanup_job_parameters(fresh, runtime)["CostCeilingCents"] == "5651"
    assert cleanup_authority_sha256(legacy, runtime) != cleanup_authority_sha256(fresh, runtime)
    assert "mobius.cost-ceiling-cents=5651" in operator.command_plan(
        "scope-create", fresh, runtime,
    )[0]
    assert "authorized_ceiling_usd" not in legacy.binding_document()
    assert "maximum_hours" not in legacy.binding_document()
    assert fresh.binding_document()["authorized_ceiling_usd"] == "56.51"
    assert fresh.binding_document()["maximum_hours"] == 8


def test_nonlegacy_preparation_requires_reviewed_cost_fields(tmp_path: Path) -> None:
    with pytest.raises(CampaignError, match="require reviewed"):
        prepare.load_cost_fields(None, required=True)
    assert prepare.load_cost_fields(None, required=False) == {}
    path = tmp_path / "cost.json"
    valid = {"conservativeEstimateUsd": "56.5095", "contingencyPercent": "25",
             "resourceItems": []}
    path.write_text(json.dumps(valid))
    before = path.read_bytes()
    assert prepare.load_cost_fields(path, required=True) == valid
    assert path.read_bytes() == before
    path.write_text(json.dumps({**valid, "cleanupDeadlineUtc": "2030-01-01T08:00:00Z"}))
    with pytest.raises(CampaignError, match="exactly the three"):
        prepare.load_cost_fields(path, required=True)


def test_fresh_cost_arithmetic_cannot_understate_itemized_envelope() -> None:
    from infra.milestone_7_8.campaign import CostItem

    config = _config(
        authorized_ceiling_usd="56.51", maximum_hours=8,
        conservative_estimate_usd="56.50",
        resource_items=(CostItem("nine-hour-envelope", "0", 1, "45.2076"),),
    )
    with pytest.raises(CampaignError, match="does not cover"):
        config.validate()
