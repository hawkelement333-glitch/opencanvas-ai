from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_8.automation_region import CLEANUP_REGION_CANDIDATES
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, SubprocessRunner
from infra.milestone_7_8.operator import validate_operation_results
from test_milestone_7_8_controller_admission import (
    DiscoveryRunner,
    authority_fixture,
    campaign_fixture,
)


def _result(value: object) -> dict[str, object]:
    return {"exitCode": 0, "stdout": json.dumps(value), "stderr": ""}


class RegionProvider(DiscoveryRunner):
    def __init__(self, authority: dict[str, object], *, extra_region: bool) -> None:
        super().__init__(authority)
        self.locations = list(CLEANUP_REGION_CANDIDATES)
        if extra_region:
            self.locations.append("Malaysia West")

    def discovery_results(self) -> tuple[dict[str, object], ...]:
        inherited_discovery = cast(
            Callable[[], tuple[dict[str, object], ...]], super().discovery_results,
        )
        results = list(inherited_discovery())
        results[2] = _result({
            "registrationState": "Registered",
            "resourceTypes": [{
                "resourceType": "automationAccounts", "locations": self.locations,
            }],
        })
        return tuple(results)


def _fixture(
    tmp_path: Path, *, prepared_extra_region: bool,
) -> tuple[dict[str, object], CampaignConfig, dict[str, str], bytes]:
    authority = authority_fixture()
    config, runtime = campaign_fixture(authority)
    selection = RegionProvider(authority, extra_region=prepared_extra_region).select(authority)
    config = replace(config, cleanup_region_selection_sha256=selection.sha256())
    path = tmp_path / "cleanup-region-selection.json"
    path.write_text(json.dumps(selection.document()), encoding="utf-8")
    runtime["cleanupRegionSelectionFile"] = str(path)
    runtime["cleanupRegionSelectionSha256"] = selection.sha256()
    return authority, config, runtime, path.read_bytes()


def _capacity(
    authority: dict[str, object],
    config: CampaignConfig,
    runtime: dict[str, str],
    provider: RegionProvider,
    *,
    discovery: tuple[dict[str, object], ...] | None = None,
) -> None:
    prefix = [
        *[_result({"registrationState": "Registered"}) for _ in range(6)],
        _result([{"name": "Standard_D2ds_v4"}]),
        _result({"value": [
            {"name": {"value": name}, "unit": "Count", "currentValue": 0, "limit": 10}
            for name in ("cores", "standardDDSv4Family")
        ]}),
        _result({"value": [{
            "name": {"value": "ManagedEnvironmentCount"}, "currentValue": 0, "limit": 1,
        }]}),
        _result({"nameAvailable": True}),
        _result({"nameAvailable": True}),
    ]
    baseline = cast(list[dict[str, object]], authority["baselineReadback"])
    validate_operation_results(
        "capacity-check",
        [*prefix, *(discovery or provider.discovery_results()), *baseline],
        config,
        runtime,
        runner=cast(SubprocessRunner, provider),
        controller_authority_evidence=authority,
    )


@pytest.mark.parametrize("prepared_extra_region", [False, True], ids=["added", "removed"])
def test_capacity_refresh_preserves_prepared_receipt_for_non_candidate_region_change(
    tmp_path: Path, prepared_extra_region: bool,
) -> None:
    authority, config, runtime, original_bytes = _fixture(
        tmp_path, prepared_extra_region=prepared_extra_region,
    )
    original_hash = config.cleanup_region_selection_sha256
    provider = RegionProvider(authority, extra_region=not prepared_extra_region)
    assert provider.select(authority).sha256() != original_hash

    _capacity(authority, config, runtime, provider)

    assert config.cleanup_region_selection_sha256 == original_hash
    assert runtime["cleanupRegionSelectionSha256"] == original_hash
    assert Path(runtime["cleanupRegionSelectionFile"]).read_bytes() == original_bytes


@pytest.mark.parametrize(
    "drift", ["selected-capability", "other-candidate-capability", "offer", "policy",
              "active-occupancy", "deleted-occupancy", "controller-tags", "controller-deadline"],
)
def test_capacity_refresh_rejects_bound_decision_drift(
    tmp_path: Path, drift: str,
) -> None:
    authority, config, runtime, original_bytes = _fixture(
        tmp_path, prepared_extra_region=True,
    )
    provider = RegionProvider(authority, extra_region=False)
    if drift == "selected-capability":
        provider.locations.remove(config.cleanup_region)
    elif drift == "other-candidate-capability":
        provider.locations.remove("eastus")
    elif drift == "controller-tags":
        provider.resources[1]["tags"]["mobius.owner"] = "unexpected-owner"
    elif drift == "controller-deadline":
        provider.resources[1]["tags"]["mobius.controller-authorized-until-utc"] = (
            "2030-01-03T00:00:00Z"
        )
    discovery = list(provider.discovery_results())
    if drift == "offer":
        metadata = json.loads(str(discovery[1]["stdout"]))
        metadata["subscriptionPolicies"]["quotaId"] = "AzureForStudents_ChangedEvidence"
        discovery[1] = _result(metadata)
    elif drift == "policy":
        discovery[5] = _result([{"enforcementMode": "DoNotEnforce"}])
    elif drift == "active-occupancy":
        discovery[3] = _result({
            "accounts": [provider.resources[1], {"location": "westus"}], "nextLink": None,
        })
    elif drift == "deleted-occupancy":
        discovery[4] = _result({"accounts": [{"location": "westus"}], "nextLink": None})

    with pytest.raises(CampaignError):
        _capacity(authority, config, runtime, provider, discovery=tuple(discovery))

    assert Path(runtime["cleanupRegionSelectionFile"]).read_bytes() == original_bytes


@pytest.mark.parametrize(
    "damage", ["missing-path", "missing-file", "malformed", "altered-hash", "replaced-receipt"],
)
def test_capacity_refresh_requires_the_exact_valid_prepared_receipt(
    tmp_path: Path, damage: str,
) -> None:
    authority, config, runtime, _ = _fixture(tmp_path, prepared_extra_region=True)
    provider = RegionProvider(authority, extra_region=False)
    path = Path(runtime["cleanupRegionSelectionFile"])
    if damage == "missing-path":
        del runtime["cleanupRegionSelectionFile"]
    elif damage == "missing-file":
        path.unlink()
    elif damage == "malformed":
        path.write_text("{not-json", encoding="utf-8")
    elif damage == "altered-hash":
        document = json.loads(path.read_text(encoding="utf-8"))
        document["providerLocationsSha256"] = "a" * 64
        path.write_text(json.dumps(document), encoding="utf-8")
    else:
        path.write_text(json.dumps(provider.select(authority).document()), encoding="utf-8")

    with pytest.raises(CampaignError):
        _capacity(authority, config, runtime, provider)
