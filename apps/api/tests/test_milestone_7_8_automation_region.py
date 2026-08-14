from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

# The API test root is normally the import root; this focused infrastructure
# contract imports the repository-level campaign package after adding that root.
# ruff: noqa: E402
from infra.milestone_7_8.automation_region import (
    CLEANUP_CANDIDATE_REGIONS_BINDING,
    CLEANUP_REGION_CANDIDATES,
    OFFER_ELIGIBILITY_SOURCE,
    OFFER_ELIGIBLE_REGIONS_BINDING,
    RESTRICTED_OFFER_ELIGIBLE_REGIONS,
    AutomationRegionSelection,
    automation_region_discovery_commands,
    discover_automation_region,
    select_automation_region_from_results,
    selection_from_document,
)
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    CostItem,
    Ledger,
    Lifecycle,
    Phase,
    SimulatedRunner,
    terminal_receipt,
)
from infra.milestone_7_8.operator import (
    command_plan,
    start_direct_cleanup,
    validate_operation_results,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def _result(value: object, *, exit_code: int = 0) -> dict[str, object]:
    return {"exitCode": exit_code, "stdout": json.dumps(value), "stderr": ""}


def _provider(locations: Sequence[object] | None = None) -> dict[str, object]:
    return {
        "registrationState": "Registered",
        "resourceTypes": [
            {
                "resourceType": "automationAccounts",
                "locations": list(locations)
                if locations is not None
                else [
                    "East US 2",
                    "South Central US",
                    "West US 2",
                    "West US",
                    "East US",
                    "North Europe",
                    "Southeast Asia",
                ],
            }
        ],
    }


def _discovery_results(
    *,
    subscription: object | None = None,
    locations: Sequence[object] | None = None,
    active: Sequence[object] | None = None,
    active_next_link: object = None,
    deleted: Sequence[object] | None = None,
    deleted_next_link: object = None,
    assignments: Sequence[object] | None = None,
) -> tuple[dict[str, object], ...]:
    return (
        _result({"environmentName": "AzureCloud", "state": "Enabled"}),
        _result(
            subscription
            if subscription is not None
            else {
                "subscriptionPolicies": {
                    "locationPlacementId": "Public_2014-09-01",
                    "quotaId": "AzureForStudents_2018-01-01",
                    "spendingLimit": "On",
                }
            }
        ),
        _result(_provider(locations)),
        _result(
            {
                "accounts": list(active) if active is not None else [],
                "nextLink": active_next_link,
            }
        ),
        _result(
            {
                "accounts": list(deleted) if deleted is not None else [],
                "nextLink": deleted_next_link,
            }
        ),
        _result(list(assignments) if assignments is not None else []),
    )


class FakeRunner:
    def __init__(self, definitions: dict[str, object] | None = None) -> None:
        self.definitions = definitions or {}
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        if command[:4] == ("az", "rest", "--method", "get"):
            url = command[command.index("--url") + 1]
            for definition_id, value in self.definitions.items():
                if definition_id in url:
                    return _result(value)
        return _result({})


def _select(
    *,
    subscription: object | None = None,
    locations: Sequence[object] | None = None,
    active: Sequence[object] | None = None,
    active_next_link: object = None,
    deleted: Sequence[object] | None = None,
    deleted_next_link: object = None,
    assignments: Sequence[object] | None = None,
    definitions: dict[str, object] | None = None,
    candidate_order: tuple[str, ...] = CLEANUP_REGION_CANDIDATES,
) -> AutomationRegionSelection:
    return select_automation_region_from_results(
        FakeRunner(definitions),
        _discovery_results(
            subscription=subscription,
            locations=locations,
            active=active,
            active_next_link=active_next_link,
            deleted=deleted,
            deleted_next_link=deleted_next_link,
            assignments=assignments,
        ),
        observed_at=NOW,
        candidate_order=candidate_order,
    )


def _config(selection: AutomationRegionSelection) -> CampaignConfig:
    return CampaignConfig(
        campaign_id="mobius78-region-proof",
        generation_id="g1-aabbccddeeff",
        subscription_correlation="a" * 16,
        tenant_correlation="b" * 16,
        target_resource_group="rg-m78-aabbccddee-target",
        cleanup_resource_group="rg-m78-aabbccddee-cleanup",
        target_region="centralus",
        cleanup_region=selection.selected_region,
        postgres_region="centralus",
        cleanup_deadline_utc="2030-01-01T04:00:00Z",
        conservative_estimate_usd="25.6832",
        contingency_percent="25",
        resource_items=(CostItem("bounded", "5.13664", 4),),
        principal_manifest_sha256="c" * 64,
        cleanup_region_selection_sha256=selection.sha256(),
        cleanup_candidate_regions=",".join(selection.candidate_order),
        cleanup_offer_classification=selection.offer_classification,
        cleanup_offer_eligibility_disposition=(selection.offer_eligibility_disposition),
        cleanup_offer_eligible_regions=",".join(selection.offer_eligible_regions),
        cleanup_offer_eligibility_source=selection.offer_eligibility_source,
        cleanup_offer_eligibility_sha256=selection.offer_eligibility_sha256,
    )


def _runtime(selection: AutomationRegionSelection) -> dict[str, str]:
    return {
        "subscriptionId": "00000000-0000-4000-8000-000000000100",
        "resourceGroupName": "rg-m78-aabbccddee-target",
        "cleanupResourceGroupName": "rg-m78-aabbccddee-cleanup",
        "automationAccountName": "aa-m78-proof",
        "runbookName": "Remove-M78Campaign-proof",
        "registryName": "acrm78proof",
        "postgresServerName": "pgm78proof",
        "cleanupDeploymentName": "m78-cleanup-proof",
        "cleanupParametersFile": "runtime/cleanup.parameters.json",
        "automationApiVersion": "2024-10-23",
        "cleanupRegion": selection.selected_region,
        "cleanupRegionSelectionSha256": selection.sha256(),
        "cleanupCandidateRegions": ",".join(selection.candidate_order),
        "cleanupOfferClassification": selection.offer_classification,
        "cleanupOfferEligibilityDisposition": (selection.offer_eligibility_disposition),
        "cleanupOfferEligibleRegions": ",".join(selection.offer_eligible_regions),
        "cleanupOfferEligibilitySource": selection.offer_eligibility_source,
        "cleanupOfferEligibilitySha256": selection.offer_eligibility_sha256,
    }


def test_occupied_westus_is_rejected_before_mutation_and_alternate_is_selected() -> None:
    selection = _select(active=[{"location": "WEST US"}])

    assert selection.selected_region == "eastus2"
    westus = next(item for item in selection.candidates if item.region == "westus")
    assert westus.status == "occupied"
    assert westus.active_account_count == 1


def test_supported_policy_allowed_zero_occupancy_alternate_is_deterministic() -> None:
    definition_id = "/providers/Microsoft.Authorization/policyDefinitions/allowed-locations"
    assignments = [
        {
            "enforcementMode": "Default",
            "policyDefinitionId": definition_id,
            "parameters": {
                "listOfAllowedLocations": {"value": ["southcentralus", "westus2", "westus"]}
            },
        }
    ]
    definition = {
        "properties": {
            "parameters": {"listOfAllowedLocations": {"type": "Array"}},
            "policyRule": {
                "if": {
                    "allOf": [
                        {
                            "field": "type",
                            "equals": "Microsoft.Automation/automationAccounts",
                        },
                        {
                            "field": "location",
                            "notIn": "[parameters('listOfAllowedLocations')]",
                        },
                    ]
                },
                "then": {"effect": "deny"},
            },
        }
    }

    selection = _select(
        assignments=assignments,
        definitions={definition_id: definition},
    )

    assert selection.selected_region == "westus"
    assert selection.candidates[0].status == "policy-disallowed"
    assert selection.candidates[1].status == "offer-ineligible"
    assert selection.candidates[2].status == "offer-ineligible"


def test_m78_pg_008_restricted_offer_is_an_independent_mandatory_gate() -> None:
    selection = _select(
        locations=["East US 2", "South Central US", "West US 2", "West US"],
    )

    assert selection.selected_region == "eastus2"
    by_region = {item.region: item for item in selection.candidates}
    for region in ("southcentralus", "westus2"):
        evidence = by_region[region]
        assert evidence.provider_supported is True
        assert evidence.offer_eligible is False
        assert evidence.policy_allowed is True
        assert evidence.active_account_count == 0
        assert evidence.soft_deleted_account_count == 0
        assert evidence.status == "offer-ineligible"
    assert selection.offer_eligible_regions == RESTRICTED_OFFER_ELIGIBLE_REGIONS
    assert selection.offer_eligibility_source == OFFER_ELIGIBILITY_SOURCE


def test_m78_pg_009_previously_omitted_viable_candidate_is_selected() -> None:
    selection = _select(
        deleted=[
            {"location": "East US 2"},
            {"location": "West US"},
            {"location": "East US"},
            {"location": "North Europe"},
        ]
    )

    assert selection.selected_region == "southeastasia"
    assert selection.candidate_order == CLEANUP_REGION_CANDIDATES
    assert set(RESTRICTED_OFFER_ELIGIBLE_REGIONS) <= set(selection.candidate_order)
    by_region = {item.region: item for item in selection.candidates}
    assert len(by_region) == len(CLEANUP_REGION_CANDIDATES) == 7
    for region in ("eastus2", "westus", "eastus", "northeurope"):
        assert by_region[region].status == "occupied"
        assert by_region[region].soft_deleted_account_count == 1
    for region in ("southcentralus", "westus2"):
        assert by_region[region].status == "offer-ineligible"
    assert by_region["southeastasia"].status == "viable"


def test_m78_pg_009_offer_safe_candidates_cannot_be_silently_dropped() -> None:
    assert CLEANUP_CANDIDATE_REGIONS_BINDING == (
        "eastus2,southcentralus,westus2,westus,eastus,northeurope,southeastasia"
    )
    assert set(RESTRICTED_OFFER_ELIGIBLE_REGIONS) <= set(CLEANUP_REGION_CANDIDATES)
    with pytest.raises(CampaignError, match="reviewed contract"):
        _select(candidate_order=CLEANUP_REGION_CANDIDATES[:-1])


def test_active_and_soft_deleted_occupancy_are_independent_offer_aware_gates() -> None:
    active = _select(active=[{"location": "East US 2"}])
    assert active.selected_region == "westus"
    eastus2 = active.candidates[0]
    assert (eastus2.active_account_count, eastus2.soft_deleted_account_count) == (1, 0)
    assert eastus2.status == "occupied"

    deleted = _select(deleted=[{"location": "East US 2"}])
    assert deleted.selected_region == "westus"
    eastus2 = deleted.candidates[0]
    assert (eastus2.active_account_count, eastus2.soft_deleted_account_count) == (0, 1)
    assert eastus2.status == "occupied"


@pytest.mark.parametrize(
    "subscription",
    [
        {},
        {"subscriptionPolicies": None},
        {"subscriptionPolicies": {"quotaId": None}},
        {"subscriptionPolicies": {"quotaId": "UnknownEnterpriseOffer"}},
    ],
)
def test_unknown_or_malformed_offer_metadata_applies_safe_restrictive_baseline(
    subscription: object,
) -> None:
    selection = _select(subscription=subscription)

    assert selection.offer_classification == "unclassified"
    assert selection.offer_eligibility_disposition == ("restrictive-public-baseline-applied")
    assert selection.offer_eligible_regions == RESTRICTED_OFFER_ELIGIBLE_REGIONS
    assert selection.candidates[1].status == "offer-ineligible"
    assert selection.candidates[2].status == "offer-ineligible"


def test_provider_and_policy_cannot_expand_restricted_offer_eligibility() -> None:
    with pytest.raises(CampaignError, match="automation-region-offer-ineligible"):
        _select(locations=["South Central US", "West US 2"])


def test_caller_candidate_or_offer_bypass_is_not_accepted() -> None:
    with pytest.raises(CampaignError, match="reviewed contract"):
        _select(
            candidate_order=(
                "southcentralus",
                "westus2",
                "eastus2",
                "westus",
            )
        )


def test_documented_japanwest2_alias_is_not_guessed_from_japan_west_provider() -> None:
    selection = _select(locations=["East US 2", "Japan West"])

    assert "japanwest" not in selection.offer_eligible_regions
    assert "japanwest2" not in selection.offer_eligible_regions
    assert selection.selected_region == "eastus2"


def test_provider_order_and_case_do_not_change_selection_or_hash() -> None:
    first = _select(
        locations=[
            "SOUTHEAST ASIA",
            "North Europe",
            "East US",
            "West US",
            "east us 2",
            "WEST US 2",
            "South Central US",
        ]
    )
    second = _select(
        locations=[
            "southcentralus",
            "westus2",
            "EASTUS2",
            "westus",
            "eastus",
            "NORTHEUROPE",
            "southeastasia",
        ]
    )

    assert first.document() == second.document()
    assert first.sha256() == second.sha256()


def test_policy_assignment_order_does_not_change_selection_or_hash() -> None:
    first_id = "/providers/Microsoft.Authorization/policyDefinitions/first"
    second_id = "/providers/Microsoft.Authorization/policyDefinitions/second"
    assignments = [
        {
            "enforcementMode": "Default",
            "policyDefinitionId": first_id,
            "parameters": {},
        },
        {
            "enforcementMode": "Default",
            "policyDefinitionId": second_id,
            "parameters": {},
        },
    ]
    definition = {
        "properties": {
            "parameters": {},
            "policyRule": {
                "if": {"field": "type", "equals": "unused"},
                "then": {"effect": "audit"},
            },
        }
    }
    definitions: dict[str, object] = {first_id: definition, second_id: definition}

    first = _select(assignments=assignments, definitions=definitions)
    second = _select(assignments=list(reversed(assignments)), definitions=definitions)

    assert first.document() == second.document()
    assert first.sha256() == second.sha256()


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"candidate_order": ("eastus2", "eastus2", "westus2", "westus")}, "reviewed"),
        ({"locations": ["???"]}, "malformed"),
        ({"active": [{"location": "moonbase"}]}, "unknown"),
        ({"locations": ["Central US"]}, "automation-region-unsupported"),
    ],
)
def test_duplicate_malformed_unknown_and_unsupported_inputs_fail_closed(
    changes: dict[str, object], error: str
) -> None:
    with pytest.raises(CampaignError, match=error):
        _select(**changes)  # type: ignore[arg-type]


def test_policy_discovery_that_cannot_be_evaluated_fails_closed() -> None:
    definition_id = "/providers/Microsoft.Authorization/policyDefinitions/unknown-location"
    assignments = [
        {
            "enforcementMode": "Default",
            "policyDefinitionId": definition_id,
            "parameters": {},
        }
    ]
    definition = {
        "properties": {
            "parameters": {},
            "policyRule": {
                "if": {
                    "allOf": [
                        {"field": "location", "notEquals": "centralus"},
                        {"field": "unknownProperty", "equals": "value"},
                    ]
                },
                "then": {"effect": "deny"},
            },
        }
    }

    with pytest.raises(CampaignError, match="cannot be evaluated safely"):
        _select(assignments=assignments, definitions={definition_id: definition})


def test_all_candidates_occupied_stops_before_an_armable_selection() -> None:
    active = [{"location": region} for region in CLEANUP_REGION_CANDIDATES]
    with pytest.raises(CampaignError, match="automation-region-occupied-capacity-unproved"):
        _select(active=active)


def test_m78_pg_009_empty_offer_safe_intersection_remains_fail_closed() -> None:
    deleted = [{"location": region} for region in RESTRICTED_OFFER_ELIGIBLE_REGIONS]
    with pytest.raises(CampaignError, match="automation-region-occupied-capacity-unproved"):
        _select(deleted=deleted)


@pytest.mark.parametrize("inventory_index", [3, 4])
def test_active_and_soft_deleted_inventory_pagination_fail_closed(
    inventory_index: int,
) -> None:
    results = list(_discovery_results())
    results[inventory_index] = _result(
        {"accounts": [], "nextLink": "https://management.azure.com/next-page"}
    )
    with pytest.raises(CampaignError, match="inventory is incomplete"):
        select_automation_region_from_results(FakeRunner(), tuple(results))


def test_all_candidates_policy_disallowed_has_a_classified_failure() -> None:
    definition_id = "/providers/Microsoft.Authorization/policyDefinitions/no-locations"
    assignments = [
        {
            "enforcementMode": "Default",
            "policyDefinitionId": definition_id,
            "parameters": {},
        }
    ]
    definition = {
        "properties": {
            "parameters": {},
            "policyRule": {
                "if": {"field": "location", "in": list(CLEANUP_REGION_CANDIDATES)},
                "then": {"effect": "deny"},
            },
        }
    }
    with pytest.raises(CampaignError, match="automation-region-policy-disallowed"):
        _select(assignments=assignments, definitions={definition_id: definition})


def test_discovery_failure_has_no_hardcoded_fallback() -> None:
    class FailingRunner:
        def run(self, _command: tuple[str, ...]) -> dict[str, object]:
            return _result({}, exit_code=1)

    with pytest.raises(CampaignError, match="failed safely"):
        discover_automation_region(
            FailingRunner(),
            "00000000-0000-4000-8000-000000000100",
            observed_at=NOW,
        )


@pytest.mark.parametrize("subscription", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_malformed_subscription_binding_fails_before_discovery(subscription: str) -> None:
    with pytest.raises(CampaignError, match="subscription binding is malformed"):
        automation_region_discovery_commands(subscription)


def test_disabled_or_non_public_subscription_context_fails_closed() -> None:
    for context in (
        {"environmentName": "AzureCloud", "state": "Disabled"},
        {"environmentName": "AzureUSGovernment", "state": "Enabled"},
    ):
        results = list(_discovery_results())
        results[0] = _result(context)
        with pytest.raises(CampaignError, match="subscription context"):
            select_automation_region_from_results(FakeRunner(), tuple(results))


def test_selection_receipt_and_ledger_binding_are_immutable() -> None:
    selection = _select()
    config = _config(selection)
    ledger = Ledger(config.campaign_id, config.generation_id)
    Lifecycle(config, ledger, SimulatedRunner())
    ledger.transition(Phase.PREFLIGHT, NOW)

    assert selection_from_document(selection.document()).sha256() == selection.sha256()
    with pytest.raises(CampaignError, match="observation time"):
        replace(selection, observed_at_utc="2030-01-01T01:00:00+01:00").validate()
    with pytest.raises(CampaignError, match="selection or offer eligibility"):
        ledger.validate_resume(replace(config, cleanup_region="westus"))
    with pytest.raises(CampaignError, match="selection or offer eligibility"):
        ledger.validate_resume(replace(config, cleanup_offer_eligibility_sha256="0" * 64))


def test_selection_is_bound_to_plan_bicep_schemas_and_terminal_receipt() -> None:
    selection = _select()
    config = _config(selection)
    runtime = _runtime(selection)
    deploy = command_plan("cleanup-deploy", config, runtime)[0]
    assert deploy.count(selection.selected_region) == 1
    assert "@runtime/cleanup.parameters.json" in deploy

    for relative in (
        "infra/milestone_7_8/cleanup.bicep",
        "infra/milestone_7_8/main.bicep",
        "infra/milestone_7_8/modules/cleanup-controller.bicep",
        "infra/milestone_7_8/modules/campaign-resources.bicep",
        "infra/milestone_7_8/schemas/campaign.schema.json",
        "infra/milestone_7_8/schemas/runtime.schema.json",
    ):
        content = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        for binding in (
            "cleanupRegionSelectionSha256",
            "cleanupCandidateRegions",
            "cleanupOfferClassification",
            "cleanupOfferEligibilityDisposition",
            "cleanupOfferEligibleRegions",
            "cleanupOfferEligibilitySource",
            "cleanupOfferEligibilitySha256",
        ):
            assert binding in content
    ledger_schema = (REPOSITORY_ROOT / "infra/milestone_7_8/schemas/ledger.schema.json").read_text(
        encoding="utf-8"
    )
    for binding in (
        "cleanup_region_selection_sha256",
        "cleanup_candidate_regions",
        "cleanup_offer_classification",
        "cleanup_offer_eligibility_disposition",
        "cleanup_offer_eligible_regions",
        "cleanup_offer_eligibility_source",
        "cleanup_offer_eligibility_sha256",
    ):
        assert binding in ledger_schema

    receipt_ledger = Ledger(config.campaign_id, config.generation_id)
    result = Lifecycle(config, receipt_ledger, SimulatedRunner()).run_simulation(now=NOW)
    receipt = terminal_receipt(result)
    assert receipt["cleanupRegion"] == selection.selected_region
    assert receipt["cleanupRegionSelectionSha256"] == selection.sha256()
    assert receipt["cleanupCandidateRegions"] == CLEANUP_CANDIDATE_REGIONS_BINDING
    assert receipt["cleanupOfferClassification"] == selection.offer_classification
    assert receipt["cleanupOfferEligibleRegions"] == OFFER_ELIGIBLE_REGIONS_BINDING
    assert receipt["cleanupOfferEligibilitySha256"] == (selection.offer_eligibility_sha256)


def test_configuration_rejects_region_outside_bound_offer_set() -> None:
    selection = _select()
    with pytest.raises(CampaignError, match="offer eligibility binding"):
        replace(_config(selection), cleanup_region="southcentralus").validate(allow_expired=True)


def test_m78_pg_009_configuration_rejects_dropped_candidate() -> None:
    selection = _select()
    with pytest.raises(CampaignError, match="candidate region binding"):
        replace(
            _config(selection),
            cleanup_candidate_regions=",".join(CLEANUP_REGION_CANDIDATES[:-1]),
        ).validate(allow_expired=True)


def test_cleanup_deployment_plan_has_one_region_and_no_hopping_or_reuse() -> None:
    selection = _select()
    config = _config(selection)
    runtime = _runtime(selection)

    commands = command_plan("cleanup-deploy", config, runtime)
    assert len(commands) == 1
    rendered = " ".join(commands[0])
    assert rendered.count(config.cleanup_region) == 1
    assert "restore" not in rendered.casefold()
    assert "update" not in rendered.casefold()


def test_capacity_check_revalidates_selection_before_scope_mutation() -> None:
    selection = _select()
    config = _config(selection)
    runtime = _runtime(selection)
    prefix = [
        *[_result({"registrationState": "Registered"}) for _ in range(6)],
        _result([{"name": "Standard_D2ds_v5"}]),
        _result([{"name": "regional-vcpu", "currentValue": 0, "limit": 10}]),
        _result({"nameAvailable": True}),
        _result({"nameAvailable": True}),
    ]
    validate_operation_results(
        "capacity-check",
        [*prefix, *_discovery_results()],
        config,
        runtime,
        runner=FakeRunner(),  # type: ignore[arg-type]
    )
    assert config.cleanup_candidate_regions == CLEANUP_CANDIDATE_REGIONS_BINDING

    changed_offer_results = list(_discovery_results())
    changed_offer_results[1] = _result(
        {"subscriptionPolicies": {"quotaId": "FreeTrial_ChangedEvidence"}}
    )
    with pytest.raises(CampaignError, match="no longer armable"):
        validate_operation_results(
            "capacity-check",
            [*prefix, *changed_offer_results],
            config,
            runtime,
            runner=FakeRunner(),  # type: ignore[arg-type]
        )

    with pytest.raises(CampaignError, match="no longer armable"):
        validate_operation_results(
            "capacity-check",
            [
                *prefix,
                *_discovery_results(active=[{"location": "eastus2"}]),
            ],
            config,
            runtime,
            runner=FakeRunner(),  # type: ignore[arg-type]
        )


def test_discovery_and_cleanup_never_target_unrelated_automation_accounts() -> None:
    commands = automation_region_discovery_commands("00000000-0000-4000-8000-000000000100")
    account_context = commands[0]
    subscription_metadata = commands[1]
    provider_inventory = commands[2]
    active_inventory = commands[3]
    deleted_inventory = commands[4]
    policy_inventory = commands[5]
    assert account_context[1:3] == ("account", "show")
    assert "--subscription" in account_context
    assert subscription_metadata[1:3] == ("rest", "--method")
    assert any("subscriptionPolicies" in part for part in subscription_metadata)
    assert provider_inventory[1:3] == ("provider", "show")
    assert "--subscription" in provider_inventory
    assert active_inventory[1:3] == ("rest", "--method")
    active_query = active_inventory[active_inventory.index("--query") + 1]
    assert "accounts:value[].{location:location}" in active_query
    assert "nextLink:nextLink" in active_query
    assert "--name" not in active_inventory
    deleted_query = deleted_inventory[deleted_inventory.index("--query") + 1]
    assert "accounts:value[].{location:Location}" in deleted_query
    assert "nextLink:nextLink" in deleted_query
    assert policy_inventory[1:4] == ("policy", "assignment", "list")
    assert "/subscriptions/00000000-0000-4000-8000-000000000100" in policy_inventory

    class RecordingRunner:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            self.commands.append(command)
            if command[:2] == ("az", "rest"):
                return _result({"value": []})
            return _result({})

    selection = _select()
    config = _config(selection)
    runtime = _runtime(selection)
    expected_resource_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
        f"automationAccounts/{runtime['automationAccountName']}"
    ).casefold()
    runtime["deletedAutomationAccountBindingSha256"] = hashlib.sha256(
        b"m7.8/deleted-automation-account/v1\0" + expected_resource_id.encode()
    ).hexdigest()
    runner = RecordingRunner()
    start_direct_cleanup(runner, config, runtime)  # type: ignore[arg-type]
    delete_commands = runner.commands[:2]
    assert [command[command.index("--name") + 1] for command in delete_commands] == [
        config.target_resource_group,
        config.cleanup_resource_group,
    ]
    assert all(command[:3] == ("az", "group", "delete") for command in delete_commands)
    assert all(command[:2] == ("az", "rest") for command in runner.commands[2:])


def test_selection_receipt_contains_no_resource_or_account_identifier() -> None:
    selection = _select(active=[{"location": "westus"}])
    encoded = json.dumps(selection.document(), sort_keys=True)
    assert "subscriptions/" not in encoded
    assert "resourceGroups/" not in encoded
    assert "automationAccounts/" not in encoded
    assert "00000000-" not in encoded
