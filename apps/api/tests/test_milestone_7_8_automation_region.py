from __future__ import annotations

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
    CLEANUP_REGION_CANDIDATES,
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
                else ["East US 2", "South Central US", "West US 2", "West US"],
            }
        ],
    }


def _discovery_results(
    *,
    locations: Sequence[object] | None = None,
    active: Sequence[object] | None = None,
    deleted: Sequence[object] | None = None,
    assignments: Sequence[object] | None = None,
) -> tuple[dict[str, object], ...]:
    return (
        _result({"environmentName": "AzureCloud", "state": "Enabled"}),
        _result(_provider(locations)),
        _result(list(active) if active is not None else []),
        _result(
            {
                "accounts": list(deleted) if deleted is not None else [],
                "nextLink": None,
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
    locations: Sequence[object] | None = None,
    active: Sequence[object] | None = None,
    deleted: Sequence[object] | None = None,
    assignments: Sequence[object] | None = None,
    definitions: dict[str, object] | None = None,
    candidate_order: tuple[str, ...] = CLEANUP_REGION_CANDIDATES,
) -> AutomationRegionSelection:
    return select_automation_region_from_results(
        FakeRunner(definitions),
        _discovery_results(
            locations=locations,
            active=active,
            deleted=deleted,
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
        "cleanupRegion": selection.selected_region,
        "cleanupRegionSelectionSha256": selection.sha256(),
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

    assert selection.selected_region == "southcentralus"
    assert selection.candidates[0].status == "policy-disallowed"


def test_provider_order_and_case_do_not_change_selection_or_hash() -> None:
    first = _select(locations=["West US", "east us 2", "WEST US 2", "South Central US"])
    second = _select(locations=["southcentralus", "westus2", "EASTUS2", "westus"])

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


def test_soft_deleted_inventory_pagination_fails_closed() -> None:
    results = list(_discovery_results())
    results[3] = _result(
        {
            "accounts": [],
            "nextLink": "https://management.azure.com/redacted-next-page",
        }
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
    with pytest.raises(CampaignError, match="region selection was substituted"):
        ledger.validate_resume(replace(config, cleanup_region="westus"))


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
        assert "cleanupRegionSelectionSha256" in (REPOSITORY_ROOT / relative).read_text(
            encoding="utf-8"
        )
    assert "cleanup_region_selection_sha256" in (
        REPOSITORY_ROOT / "infra/milestone_7_8/schemas/ledger.schema.json"
    ).read_text(encoding="utf-8")

    receipt_ledger = Ledger(config.campaign_id, config.generation_id)
    result = Lifecycle(config, receipt_ledger, SimulatedRunner()).run_simulation(now=NOW)
    receipt = terminal_receipt(result)
    assert receipt["cleanupRegion"] == selection.selected_region
    assert receipt["cleanupRegionSelectionSha256"] == selection.sha256()


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
    provider_inventory = commands[1]
    active_inventory = commands[2]
    deleted_inventory = commands[3]
    policy_inventory = commands[4]
    assert account_context[1:3] == ("account", "show")
    assert "--subscription" in account_context
    assert provider_inventory[1:3] == ("provider", "show")
    assert "--subscription" in provider_inventory
    assert active_inventory[1:3] == ("resource", "list")
    assert "[].{location:location}" in active_inventory
    assert "--subscription" in active_inventory
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
            return _result({})

    selection = _select()
    config = _config(selection)
    runner = RecordingRunner()
    start_direct_cleanup(runner, config)  # type: ignore[arg-type]
    assert [command[command.index("--name") + 1] for command in runner.commands] == [
        config.target_resource_group,
        config.cleanup_resource_group,
    ]
    assert all(command[:3] == ("az", "group", "delete") for command in runner.commands)


def test_selection_receipt_contains_no_resource_or_account_identifier() -> None:
    selection = _select(active=[{"location": "westus"}])
    encoded = json.dumps(selection.document(), sort_keys=True)
    assert "subscriptions/" not in encoded
    assert "resourceGroups/" not in encoded
    assert "automationAccounts/" not in encoded
    assert "00000000-" not in encoded
