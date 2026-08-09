from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from infra.milestone_7_7 import cleanup_control_recovery_adapter as adapter_module
from infra.milestone_7_7 import scanner_bridge_recovery_adapter as scanner_adapter_module
from infra.milestone_7_7.cleanup_control_recovery_adapter import (
    CleanupControlRecoveryExecutionError,
    ProductionCleanupControlRecoveryAdapter,
)
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from infra.milestone_7_7.scripts.cleanup_resource_reconciliation import (
    exact_deleted_key_vault_purge_command,
)
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import cleanup_control_recovery
from preflight.milestone_7_7.cleanup_control_recovery import (
    CleanupControlRecoveryAuthorization,
    CleanupControlRecoveryError,
    CleanupControlReprovisionAuthorization,
    build_cleanup_control_recovery_authorization,
    build_cleanup_control_reprovision_authorization,
    cleanup_control_recovery_authorization_integrity,
    cleanup_control_reprovision_authorization_integrity,
    validate_cleanup_control_recovery_authorization,
    validate_cleanup_control_reprovision_authorization,
    write_cleanup_control_recovery_authorization,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    CLEANUP_RUNBOOK_PATH,
    cleanup_runbook_sha256,
)

SUBSCRIPTION_ID = "opaque-subscription"
SUBSCRIPTION = f"/subscriptions/{SUBSCRIPTION_ID}"
CLEANUP_GROUP = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-cleanup-control"
TARGET_GROUP = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-staging"
AUTOMATION_PREFIX = f"{CLEANUP_GROUP}/providers/Microsoft.Automation/automationAccounts"
NOW = datetime(2026, 8, 6, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 6, 12, tzinfo=UTC)
REPROVISION_NOW = datetime(2026, 8, 9, 22, 10, tzinfo=UTC)
PRINCIPAL_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CORRUPTED_PRINCIPAL_ID = "be0e6b8d-f742-4c8f-8df1-9f302559a6c8"
CORRUPTED_ASSIGNMENT_ID = (
    f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
    "5c1b559b-638a-5d58-b77b-b6291747f9d4"
)
REPLACEMENT_ASSIGNMENT_ID = (
    f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
    "b4acad78-f3f0-59d4-8e36-901644af1ff6"
)
DELETED_KEY_VAULT_ID = (
    f"{SUBSCRIPTION}/providers/Microsoft.KeyVault/locations/southcentralus/"
    "deletedVaults/kv-mobius77-11564669"
)
DELETED_WORKSPACE_ID = (
    f"{TARGET_GROUP}/providers/Microsoft.OperationalInsights/workspaces/law-mobius77-staging"
)


def _runbook_sha256() -> str:
    return cleanup_runbook_sha256(CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8"))


def _authorization() -> CleanupControlRecoveryAuthorization:
    return build_cleanup_control_recovery_authorization(
        repository_head="a" * 40,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        corrupted_principal_id=CORRUPTED_PRINCIPAL_ID,
        corrupted_role_assignment_id=CORRUPTED_ASSIGNMENT_ID,
        replacement_automation_account_id=(f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery"),
        target_resource_group_id=TARGET_GROUP,
        runbook_content_sha256=_runbook_sha256(),
        now_utc=NOW,
    )


def _reprovision_authorization() -> CleanupControlReprovisionAuthorization:
    return build_cleanup_control_reprovision_authorization(
        repository_head="a" * 40,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        corrupted_principal_id=CORRUPTED_PRINCIPAL_ID,
        corrupted_role_assignment_id=CORRUPTED_ASSIGNMENT_ID,
        replacement_automation_account_id=(f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery"),
        replacement_principal_id=(
            cleanup_control_recovery.DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID
        ),
        replacement_role_assignment_id=REPLACEMENT_ASSIGNMENT_ID,
        replacement_location=(cleanup_control_recovery.DEADLINE_RECOVERY_REPLACEMENT_LOCATION),
        target_resource_group_id=TARGET_GROUP,
        prior_generation_source_commit=(
            cleanup_control_recovery.POST_CLEANUP_REPROVISION_PRIOR_SOURCE_COMMIT
        ),
        prior_lifecycle_binding_sha256=(
            cleanup_control_recovery.POST_CLEANUP_REPROVISION_PRIOR_BINDING_SHA256
        ),
        prior_manifest_sha256=(
            cleanup_control_recovery.POST_CLEANUP_REPROVISION_PRIOR_MANIFEST_SHA256
        ),
        deleted_key_vault_id=DELETED_KEY_VAULT_ID,
        deleted_key_vault_name="kv-mobius77-11564669",
        deleted_key_vault_location="southcentralus",
        deleted_key_vault_at_utc="2026-08-09T08:01:54Z",
        deleted_workspace_id=DELETED_WORKSPACE_ID,
        deleted_workspace_name="law-mobius77-staging",
        deleted_workspace_location="southcentralus",
        deleted_workspace_at_utc="2026-08-09T08:02:25.8464081Z",
        deleted_workspace_customer_id="df2bb7a1-9504-4a8d-9d3d-de421ea1b409",
        runbook_content_sha256=_runbook_sha256(),
        now_utc=REPROVISION_NOW,
    )


def _resign(
    authorization: CleanupControlRecoveryAuthorization,
) -> CleanupControlRecoveryAuthorization:
    return replace(
        authorization,
        authorizationIntegritySha256=(
            cleanup_control_recovery_authorization_integrity(authorization)
        ),
    )


def _final_inventory(
    authorization: CleanupControlRecoveryAuthorization,
) -> frozenset[str]:
    account = "microsoft.automation/automationaccounts/aa-mobius77-cleanup-recovery"
    return frozenset(
        {
            "microsoft.automation/automationaccounts/aa-mobius77-cleanup",
            (
                "microsoft.automation/automationaccounts/aa-mobius77-cleanup/"
                f"runbooks/{authorization.runbook.casefold()}"
            ),
            (
                "microsoft.automation/automationaccounts/aa-mobius77-cleanup/"
                f"schedules/{authorization.schedule.casefold()}"
            ),
            account,
            f"{account}/runbooks/{authorization.runbook.casefold()}",
            f"{account}/schedules/{authorization.schedule.casefold()}",
            f"{account}/jobschedules/{authorization.bindingId.casefold()}",
        }
    )


def _install_execution_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: CleanupControlRecoveryAuthorization,
    *,
    initial_inventory: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, tuple[Any, ...]]]]:
    initial = initial_inventory or frozenset(
        item
        for item in _final_inventory(authorization)
        if "aa-mobius77-cleanup-recovery" not in item
    )
    inventories = iter((initial, _final_inventory(authorization)))
    deployments: list[dict[str, Any]] = []
    calls: list[tuple[str, tuple[Any, ...]]] = []
    historical_contract: dict[str, JsonValue] = {
        "cleanupExecution": {
            "activeBindingId": authorization.bindingId,
            "authorizationParameter": authorization.authorizationParameter,
            "authorizationValue": authorization.authorizationParameterValue,
            "bindingContractVersion": authorization.bindingContractVersion,
            "cleanupContributorRoleDefinitionId": authorization.roleDefinitionId,
            "deadlineUtc": authorization.deadlineUtc,
            "publishedContentSha256": authorization.runbookContentSha256,
            "targetParameter": authorization.targetParameter,
            "targetResourceGroup": authorization.targetParameterValue,
        },
        "rbac": {"cleanupContributorRoleDefinitionId": authorization.roleDefinitionId},
    }
    monkeypatch.setattr(
        adapter_module,
        "load_managed_binding_contract",
        lambda: historical_contract,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_repository_state",
        lambda head: calls.append(("repository", (head,))),
    )
    monkeypatch.setattr(managed_binding_lifecycle, "_account_binding", lambda now: SUBSCRIPTION_ID)
    monkeypatch.setattr(
        managed_binding_lifecycle, "_group_exists", lambda subscription, group: True
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: next(inventories),
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_corrupted_evidence_graph",
        lambda authorization, subscription, *, assignment_required: calls.append(
            ("corrupted-graph", (subscription, assignment_required))
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "_revoke_corrupted_role_assignment",
        lambda authorization, subscription: calls.append(
            ("corrupted-role-revoke", (subscription, authorization.corruptedRoleAssignmentId))
        ),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_compile_template",
        lambda template: calls.append(("compile", (template,))),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_deploy_stage",
        lambda **kwargs: deployments.append(kwargs),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_configure_cleanup_runbook",
        lambda subscription: calls.append(("runbook", (subscription,))),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_control",
        lambda subscription, cleanup_at: PRINCIPAL_ID,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_target_role",
        lambda *args: calls.append(("role", args)),
    )
    return deployments, calls


def _install_corrupted_graph_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: CleanupControlRecoveryAuthorization,
    **overrides: object,
) -> None:
    account: object = overrides.get(
        "account",
        {
            "id": authorization.corruptedAutomationAccountId,
            "identityType": "SystemAssigned",
            "localAuthDisabled": True,
            "location": "westus",
            "principalId": authorization.corruptedPrincipalId,
            "publicNetworkAccess": False,
            "state": "Ok",
        },
    )
    collections: dict[str, object] = {
        "runbooks": [
            {
                "id": (
                    f"{authorization.corruptedAutomationAccountId}/runbooks/{authorization.runbook}"
                ),
                "name": authorization.runbook,
                "runbookType": "PowerShell72",
                "state": "Published",
            }
        ],
        "schedules": [
            {
                "id": (
                    f"{authorization.corruptedAutomationAccountId}/schedules/"
                    f"{authorization.schedule}"
                ),
                "name": authorization.schedule,
            }
        ],
        "jobSchedules": [],
        "webhooks": [],
        "variables": [],
        "credentials": [],
        "certificates": [],
        "connections": [],
        "hybridRunbookWorkerGroups": [],
        "sourceControls": [],
        "jobs": [
            {
                "id": f"{authorization.corruptedAutomationAccountId}/jobs/historical",
                "runbook": authorization.runbook,
                "status": "Failed",
            }
        ],
    }
    for key in tuple(collections):
        if key in overrides:
            collections[key] = overrides[key]
    expected_role = {
        "id": authorization.corruptedRoleAssignmentId,
        "principalId": authorization.corruptedPrincipalId,
        "roleDefinitionId": (
            f"/subscriptions/{authorization.subscriptionId}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            f"{authorization.roleDefinitionId}"
        ),
        "scope": authorization.roleScope,
    }
    roles: object = overrides.get("roles", [expected_role])
    content: object = overrides.get("content", CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8"))

    def run(
        argv: tuple[str, ...],
        *,
        require_json: bool = False,
        require_text: bool = False,
        **_kwargs: object,
    ) -> object:
        del require_json
        if argv[1:4] == ("automation", "account", "show"):
            return account
        if argv[1:4] == ("role", "assignment", "list"):
            return roles
        if argv[1:3] != ("rest", "--method"):
            raise AssertionError(f"unexpected command: {argv!r}")
        url = argv[argv.index("--url") + 1]
        if "/content?" in url:
            assert require_text is True
            return content
        for name, rows in collections.items():
            if f"/{name}?" in url:
                return {"nextLink": None, "value": rows}
        raise AssertionError(f"unexpected REST URL: {url}")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)


def test_exact_preserved_corrupted_execution_graph_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    _install_corrupted_graph_fakes(monkeypatch, authorization)
    adapter_module._verify_corrupted_evidence_graph(
        authorization,
        SUBSCRIPTION_ID,
        assignment_required=True,
    )
    _install_corrupted_graph_fakes(monkeypatch, authorization, roles=[])
    adapter_module._verify_corrupted_evidence_graph(
        authorization,
        SUBSCRIPTION_ID,
        assignment_required=False,
    )


def test_webhook_readback_uses_supported_authoritative_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    observed: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> object:
        observed.append(argv)
        return {"nextLink": None, "value": []}

    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)
    assert (
        adapter_module._automation_collection(
            authorization=authorization,
            subscription_id=SUBSCRIPTION_ID,
            collection="webhooks",
            query="value[].{id:id,name:name}",
        )
        == []
    )
    assert "api-version=2024-10-23" in observed[0][observed[0].index("--url") + 1]


def test_inventory_enriches_generic_readback_with_schedule_and_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    replacement = f"{AUTOMATION_PREFIX}/{authorization.replacementAutomationAccount}"
    nested = {
        "runbooks": [{"id": f"{replacement}/runbooks/{authorization.runbook}"}],
        "schedules": [{"id": f"{replacement}/schedules/{authorization.schedule}"}],
        "jobSchedules": [{"id": f"{replacement}/jobSchedules/{authorization.bindingId}"}],
    }

    def run(argv: tuple[str, ...], **_kwargs: object) -> object:
        if argv[1:3] == ("resource", "list"):
            return [
                {
                    "id": replacement,
                    "type": "Microsoft.Automation/automationAccounts",
                },
                {
                    "id": f"{replacement}/runbooks/{authorization.runbook}",
                    "type": "Microsoft.Automation/automationAccounts/runbooks",
                },
            ]
        url = argv[argv.index("--url") + 1]
        for collection, rows in nested.items():
            if f"/{collection}?" in url:
                return {"nextLink": None, "value": rows}
        return {"nextLink": None, "value": []}

    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)
    inventory = adapter_module._cleanup_resource_group_inventory(SUBSCRIPTION_ID)
    assert (
        "microsoft.automation/automationaccounts/aa-mobius77-cleanup-recovery/"
        f"schedules/{authorization.schedule.casefold()}"
    ) in inventory
    assert (
        "microsoft.automation/automationaccounts/aa-mobius77-cleanup-recovery/"
        f"jobschedules/{authorization.bindingId.casefold()}"
    ) in inventory


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "jobSchedules": [
                {
                    "id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup/jobSchedules/binding",
                    "jobScheduleId": "binding",
                    "runbook": "Remove-Mobius77Staging",
                    "schedule": "schedule-mobius77-cleanup",
                }
            ]
        },
        {"webhooks": [{"id": "webhook-id", "name": "trigger"}]},
        {
            "jobs": [
                {
                    "id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup/jobs/active",
                    "runbook": "Remove-Mobius77Staging",
                    "status": "Running",
                }
            ]
        },
        {"content": "Write-Output 'altered'\n"},
        {"variables": [{"id": "variable-id", "name": "unexpected"}]},
        {
            "runbooks": [
                {
                    "id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup/runbooks/Other",
                    "name": "Other",
                    "runbookType": "PowerShell72",
                    "state": "Published",
                }
            ]
        },
        {
            "schedules": [
                {
                    "id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup/schedules/other",
                    "name": "other",
                }
            ]
        },
        {
            "jobSchedules": [
                {
                    "id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup/jobSchedules/generation-3",
                    "jobScheduleId": "generation-3",
                    "runbook": "Remove-Mobius77Staging",
                    "schedule": "schedule-mobius77-cleanup",
                }
            ]
        },
    ],
    ids=(
        "binding",
        "webhook",
        "nonterminal-job",
        "altered-runbook",
        "extra-capability-resource",
        "other-runbook",
        "other-schedule",
        "generation-3",
    ),
)
def test_corrupted_execution_graph_rejects_each_nearby_drift(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    authorization = _authorization()
    _install_corrupted_graph_fakes(monkeypatch, authorization, **overrides)
    with pytest.raises(CleanupControlRecoveryExecutionError):
        adapter_module._verify_corrupted_evidence_graph(
            authorization,
            SUBSCRIPTION_ID,
            assignment_required=True,
        )


def test_corrupted_graph_rejects_effective_role_after_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    _install_corrupted_graph_fakes(monkeypatch, authorization)
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-recovery-corrupted-role-drift",
    ):
        adapter_module._verify_corrupted_evidence_graph(
            authorization,
            SUBSCRIPTION_ID,
            assignment_required=False,
        )


def test_exact_assignment_is_deleted_once_and_role_definition_is_never_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_delete_assignment",
        lambda subscription, assignment: deleted.append((subscription, assignment)),
    )
    monkeypatch.setattr(adapter_module, "_corrupted_role_rows", lambda *_args: [])

    adapter_module._revoke_corrupted_role_assignment(authorization, SUBSCRIPTION_ID)

    assert deleted == [(SUBSCRIPTION_ID, CORRUPTED_ASSIGNMENT_ID)]
    assert "/roleAssignments/" in deleted[0][1]
    assert "/roleDefinitions/" not in deleted[0][1]


def test_ambiguous_assignment_delete_reconciles_without_second_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    attempts: list[str] = []

    def ambiguous(_subscription: str, assignment: str) -> None:
        attempts.append(assignment)
        raise managed_binding_lifecycle.AzureCommandError("azure-command-nonzero")

    monkeypatch.setattr(managed_binding_lifecycle, "_delete_assignment", ambiguous)
    monkeypatch.setattr(adapter_module, "_corrupted_role_rows", lambda *_args: [])

    adapter_module._revoke_corrupted_role_assignment(authorization, SUBSCRIPTION_ID)

    assert attempts == [CORRUPTED_ASSIGNMENT_ID]


def test_cleanup_recovery_authorization_is_image_free_and_exact() -> None:
    authorization = _authorization()
    serialized = asdict(authorization)
    assert authorization.replacementAutomationAccount == "aa-mobius77-cleanup-recovery"
    assert authorization.corruptedPrincipalId == CORRUPTED_PRINCIPAL_ID
    assert authorization.corruptedRoleAssignmentId == CORRUPTED_ASSIGNMENT_ID
    assert authorization.corruptedRoleAssignmentAction == "delete-exact-role-assignment"
    assert authorization.bindingId == "ecdbb32f-9134-5697-85f9-d569ba57454b"
    assert authorization.roleScope == TARGET_GROUP
    assert authorization.targetParameter == "TargetResourceGroupName"
    assert authorization.targetParameterValue == "rg-solarplexus-mobius-77-staging"
    assert authorization.authorizationParameter == "CleanupAuthorized"
    assert authorization.authorizationParameterValue is True
    assert all("image" not in key.casefold() for key in serialized)
    assert all("acr" not in operation for operation in authorization.allowedOperations)
    assert (
        "build_authorization_ledger"
        not in build_cleanup_control_recovery_authorization.__code__.co_names
    )
    assert (
        validate_cleanup_control_recovery_authorization(
            authorization,
            expected_repository_head="a" * 40,
            now_utc=NOW,
        )
        is authorization
    )


@pytest.mark.parametrize("field", ["cleanup", "corrupted", "replacement", "target"])
def test_cleanup_recovery_rejects_scope_drift(field: str) -> None:
    kwargs = {
        "repository_head": "a" * 40,
        "subscription_id": SUBSCRIPTION_ID,
        "cleanup_resource_group_id": CLEANUP_GROUP,
        "corrupted_automation_account_id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        "corrupted_principal_id": CORRUPTED_PRINCIPAL_ID,
        "corrupted_role_assignment_id": CORRUPTED_ASSIGNMENT_ID,
        "replacement_automation_account_id": (f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery"),
        "target_resource_group_id": TARGET_GROUP,
        "runbook_content_sha256": _runbook_sha256(),
        "now_utc": NOW,
    }
    kwargs_by_field = {
        "cleanup": ("cleanup_resource_group_id", f"{SUBSCRIPTION}/resourceGroups/other"),
        "corrupted": (
            "corrupted_automation_account_id",
            f"{AUTOMATION_PREFIX}/other",
        ),
        "replacement": (
            "replacement_automation_account_id",
            f"{AUTOMATION_PREFIX}/other",
        ),
        "target": ("target_resource_group_id", f"{SUBSCRIPTION}/resourceGroups/other"),
    }
    key, value = kwargs_by_field[field]
    kwargs[key] = value
    with pytest.raises(CleanupControlRecoveryError):
        build_cleanup_control_recovery_authorization(**kwargs)


def test_production_adapter_consumes_authorization_and_maps_cleanup_primitives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)

    result = ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="a" * 40,
    )

    assert result["status"] == "cleanup-control-recovery-executable"
    assert result["authorization-consumed"] is True
    assert result["cleanup-executable"] is True
    assert [deployment["stage"] for deployment in deployments] == [
        "cleanup-control",
        "cleanup-job-binding",
        "cleanup-binding",
    ]
    assert all(deployment["subscription_id"] == SUBSCRIPTION_ID for deployment in deployments)
    assert all(deployment["cleanup_at"] == DEADLINE for deployment in deployments)
    assert all(deployment["maximum_cost"] == 25_000 for deployment in deployments)
    assert all(
        deployment["ledger"]["ledgerIntegritySha256"] == authorization.authorizationIntegritySha256
        for deployment in deployments
    )
    assert ("runbook", (SUBSCRIPTION_ID,)) in calls
    assert calls.index(("corrupted-graph", (SUBSCRIPTION_ID, True))) < calls.index(
        ("corrupted-role-revoke", (SUBSCRIPTION_ID, CORRUPTED_ASSIGNMENT_ID))
    )
    assert calls.index(
        ("corrupted-role-revoke", (SUBSCRIPTION_ID, CORRUPTED_ASSIGNMENT_ID))
    ) < calls.index(("corrupted-graph", (SUBSCRIPTION_ID, False)))
    assert calls.index(("corrupted-graph", (SUBSCRIPTION_ID, False))) < next(
        index for index, (name, _args) in enumerate(calls) if name == "compile"
    )
    assert (
        calls.count(
            (
                "role",
                (
                    SUBSCRIPTION_ID,
                    PRINCIPAL_ID,
                    "b24988ac-6180-42a0-ab88-20f7382dd24c",
                ),
            )
        )
        == 2
    )
    receipt = json.loads((tmp_path / adapter_module.RECEIPT_FILE).read_text(encoding="utf-8"))
    assert receipt["authorizationIntegritySha256"] == (authorization.authorizationIntegritySha256)
    assert receipt["replayDecision"] == "deny"


def test_prohibited_lifecycle_and_image_operations_are_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    _install_execution_fakes(monkeypatch, authorization)

    def prohibited(*args: object, **kwargs: object) -> None:
        pytest.fail("prohibited application/image operation was reached")

    for symbol in (
        "_prebuild_api_image",
        "_publish_api_image",
        "_publish_api_image_stage",
        "_post_secret",
        "_private_path_stage",
        "_cleanup",
    ):
        monkeypatch.setattr(managed_binding_lifecycle, symbol, prohibited)

    ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="a" * 40,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subscriptionId", "other-subscription"),
        ("corruptedPrincipalId", "00000000-0000-0000-0000-000000000000"),
        (
            "corruptedRoleAssignmentId",
            f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
            "00000000-0000-0000-0000-000000000000",
        ),
        ("corruptedRoleAssignmentAction", "delete-role-definition"),
        ("replacementAutomationAccount", "other-account"),
        ("replacementAutomationAccountId", f"{AUTOMATION_PREFIX}/other-account"),
        ("targetResourceGroupId", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("roleDefinitionId", "00000000-0000-0000-0000-000000000000"),
        ("roleScope", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("runbook", "OtherRunbook"),
        ("schedule", "other-schedule"),
        ("targetParameter", "OtherTarget"),
        ("targetParameterValue", "other-target"),
        ("authorizationParameter", "OtherAuthorization"),
        ("authorizationParameterValue", False),
    ],
)
def test_adapter_rejects_every_exact_scope_and_parameter_drift(field: str, value: object) -> None:
    authorization = _resign(replace(_authorization(), **{field: value}))
    with pytest.raises(CleanupControlRecoveryError):
        ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=Path("unused"),
            expected_repository_head="a" * 40,
        )


@pytest.mark.parametrize(
    "duplicate",
    [
        "microsoft.automation/automationaccounts/other-account",
        (
            "microsoft.automation/automationaccounts/aa-mobius77-cleanup-recovery/"
            "schedules/other-schedule"
        ),
        (
            "microsoft.automation/automationaccounts/aa-mobius77-cleanup-recovery/"
            "jobschedules/00000000-0000-0000-0000-000000000000"
        ),
    ],
)
def test_adapter_rejects_duplicate_cleanup_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, duplicate: str
) -> None:
    authorization = _authorization()
    initial = _final_inventory(authorization) | {duplicate}
    _install_execution_fakes(
        monkeypatch,
        authorization,
        initial_inventory=frozenset(initial),
    )
    with pytest.raises(CleanupControlRecoveryExecutionError):
        ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="a" * 40,
        )


def test_exact_existing_resources_are_safely_adopted_and_reconciled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    deployments, calls = _install_execution_fakes(
        monkeypatch,
        authorization,
        initial_inventory=_final_inventory(authorization),
    )
    result = ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="a" * 40,
    )
    assert result["cleanup-executable"] is True
    assert len(deployments) == 3
    assert not any(name == "seed" for name, _ in calls)


def test_authorization_replay_is_rejected_before_second_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    final = _final_inventory(authorization)
    inventories = iter((final, final, final))
    deployments, _calls = _install_execution_fakes(
        monkeypatch,
        authorization,
        initial_inventory=final,
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: next(inventories),
    )
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW)
    adapter.execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="a" * 40,
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-recovery-authorization-already-consumed",
    ):
        adapter.execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="a" * 40,
        )
    assert len(deployments) == 3


def test_adapter_does_not_construct_lifecycle_ledger_or_require_image_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    _install_execution_fakes(monkeypatch, authorization)

    def prohibited_ledger(*args: object, **kwargs: object) -> None:
        pytest.fail("complete lifecycle ledger construction was reached")

    monkeypatch.setattr(
        "preflight.milestone_7_7.managed_binding_contracts.build_authorization_ledger",
        prohibited_ledger,
    )
    signature = ProductionCleanupControlRecoveryAdapter.execute.__annotations__
    assert "image" not in " ".join(signature).casefold()
    result = ProductionCleanupControlRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="a" * 40,
    )
    assert result["cleanup-executable"] is True


def test_cleanup_recovery_entry_point_invokes_production_consumer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    authorization_path = tmp_path / "authorization.json"
    receipt_directory = tmp_path / "receipts"
    write_cleanup_control_recovery_authorization(authorization_path, _authorization())
    observed: dict[str, object] = {}

    def execute(**kwargs: object) -> dict[str, JsonValue]:
        observed.update(kwargs)
        return {"status": "cleanup-control-recovery-executable"}

    monkeypatch.setattr(cleanup_control_recovery, "execute_cleanup_control_recovery", execute)
    assert (
        cleanup_control_recovery.main(
            [
                "--authorization",
                str(authorization_path),
                "--receipt-directory",
                str(receipt_directory),
                "--repository-head",
                "a" * 40,
            ]
        )
        == 0
    )
    assert isinstance(observed["authorization"], CleanupControlRecoveryAuthorization)
    assert observed["receipt_directory"] == receipt_directory
    assert json.loads(capsys.readouterr().out) == {"status": "cleanup-control-recovery-executable"}


def test_post_cleanup_reprovision_authorization_is_exact_and_image_free() -> None:
    authorization = _reprovision_authorization()
    assert authorization.schedule == "schedule-mobius77-cleanup-g4"
    assert authorization.corruptedSchedule == "schedule-mobius77-cleanup"
    assert authorization.priorSchedule == "schedule-mobius77-cleanup-g3"
    assert authorization.bindingGeneration == 4
    assert authorization.bindingContractVersion == ("m7.7-automation-cleanup-binding-v4")
    assert authorization.priorBindingId == "12f27fa6-2cd5-548d-be20-c6e03a5e19d3"
    assert authorization.deadlineUtc == "2026-08-11T03:45:00Z"
    assert authorization.deletedKeyVaultId == DELETED_KEY_VAULT_ID
    assert authorization.deletedKeyVaultAction == ("purge-exact-soft-deleted-key-vault")
    assert authorization.deletedWorkspaceId == DELETED_WORKSPACE_ID
    assert authorization.deletedWorkspaceAction == ("recover-exact-workspace-after-cleanup-armed")
    assert authorization.foundationStage == "scanner-foundation"
    assert authorization.storageAccountId == (
        f"{TARGET_GROUP}/providers/Microsoft.Storage/storageAccounts/stmobius7711564669"
    )
    assert authorization.logAnalyticsWorkspaceId == DELETED_WORKSPACE_ID
    assert authorization.workerIdentityId.endswith(
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-mobius77-worker"
    )
    assert authorization.privateLinkScopeId.endswith(
        "/providers/Microsoft.Insights/privateLinkScopes/ampls-mobius77-staging"
    )
    assert authorization.monitorPrivateEndpointId.endswith(
        "/providers/Microsoft.Network/privateEndpoints/pe-mobius77-azure-monitor"
    )
    assert authorization.imageRestorationAuthorized is False
    assert authorization.scannerProofAuthorized is False
    assert authorization.maximumScannerProofExecutions == 0
    assert authorization.roleScope == TARGET_GROUP
    assert authorization.authorizationParameterValue is True
    assert "image" not in " ".join(authorization.allowedOperations).casefold()
    assert "migration" not in " ".join(authorization.allowedOperations).casefold()
    assert "build_authorization_ledger" not in (
        build_cleanup_control_reprovision_authorization.__code__.co_names
    )
    assert (
        validate_cleanup_control_reprovision_authorization(
            authorization,
            expected_repository_head="a" * 40,
            now_utc=REPROVISION_NOW,
        )
        is authorization
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schedule", "schedule-mobius77-cleanup-g3"),
        ("corruptedSchedule", "schedule-other"),
        ("priorSchedule", "schedule-other"),
        ("roleDefinitionId", "00000000-0000-0000-0000-000000000000"),
        ("roleScope", CLEANUP_GROUP),
        ("targetParameterValue", "rg-other"),
        ("authorizationParameterValue", False),
        ("bindingGeneration", 3),
        ("priorBindingId", "00000000-0000-0000-0000-000000000000"),
        ("deletedKeyVaultId", f"{SUBSCRIPTION}/providers/Microsoft.KeyVault/deletedVaults/other"),
        ("deletedKeyVaultName", "other-vault"),
        ("deletedKeyVaultAtUtc", "2026-08-09T08:01:55Z"),
        (
            "deletedWorkspaceId",
            f"{TARGET_GROUP}/providers/Microsoft.OperationalInsights/workspaces/other",
        ),
        ("deletedWorkspaceName", "other-workspace"),
        ("deletedWorkspaceAtUtc", "2026-08-09T08:02:26Z"),
        ("priorGenerationSourceCommit", "0" * 40),
        ("foundationStage", "scanner-proof"),
        ("storageAccountId", f"{TARGET_GROUP}/providers/Microsoft.Storage/storageAccounts/other"),
        (
            "logAnalyticsWorkspaceId",
            f"{TARGET_GROUP}/providers/Microsoft.OperationalInsights/workspaces/other",
        ),
        (
            "workerIdentityId",
            f"{TARGET_GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/other",
        ),
        (
            "privateLinkScopeId",
            f"{TARGET_GROUP}/providers/Microsoft.Insights/privateLinkScopes/other",
        ),
        (
            "monitorPrivateEndpointId",
            f"{TARGET_GROUP}/providers/Microsoft.Network/privateEndpoints/other",
        ),
        ("imageRestorationAuthorized", True),
        ("scannerProofAuthorized", True),
        ("maximumScannerProofExecutions", 1),
    ],
)
def test_post_cleanup_reprovision_authorization_rejects_scope_drift(
    field: str, value: object
) -> None:
    authorization = replace(_reprovision_authorization(), **{field: value})
    authorization = replace(
        authorization,
        authorizationIntegritySha256=(
            cleanup_control_reprovision_authorization_integrity(authorization)
        ),
    )
    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-reprovision-authorization-scope-invalid",
    ):
        validate_cleanup_control_reprovision_authorization(
            authorization,
            expected_repository_head="a" * 40,
            now_utc=REPROVISION_NOW,
        )


def test_reprovision_foundation_reuses_consumed_authorization_without_proof_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _reprovision_authorization()
    scope = scanner_adapter_module._reprovision_foundation_scope(authorization)
    assert scope.stage == "scanner-foundation"
    assert scope.proofJobId is None
    assert scope.proofRoleDefinitionId is None
    assert scope.apiImageDigest is None

    deployments: list[dict[str, object]] = []
    monkeypatch.setattr(
        scanner_adapter_module,
        "_verify_provider_api_versions",
        lambda _subscription: None,
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_verify_network_capacity",
        lambda _subscription: None,
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_monitor_private_endpoint_precreation_count",
        lambda _scope: 0,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_compile_template",
        lambda _template: None,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_deploy_stage",
        lambda **kwargs: deployments.append(kwargs),
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_read_deployment_outputs",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_validate_deployment_outputs",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_exact_monitor_private_endpoint_recovery_state",
        lambda _scope: {"endpointProvisioningState": "Succeeded"},
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_verify_foundation",
        lambda *_args, **_kwargs: scanner_adapter_module._FoundationReadback(
            api_principal_id="a",
            worker_principal_id="b",
            worker_client_id="c",
            workspace_customer_id="d",
            provider_topic_id="e",
            provider_proof_integrity="1" * 64,
            diagnostic_proof_integrity="2" * 64,
            rbac_proof_integrity="3" * 64,
            tag_write_denial_integrity="4" * 64,
            private_path_control_plane_integrity="5" * 64,
            inventory_integrity="6" * 64,
        ),
    )
    monkeypatch.setattr(
        scanner_adapter_module,
        "_verify_monitor_private_tls_path",
        lambda _workspace: "7" * 64,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verified_cost",
        lambda: (3_110, 20_607),
    )
    binding: dict[str, JsonValue] = {
        "authorizationId": "post-cleanup-reprovision-generation-4",
        "ledgerIntegritySha256": authorization.authorizationIntegritySha256,
        "managedBindingIntegritySha256": "8" * 64,
        "repositoryHead": authorization.repositoryHead,
    }
    result = scanner_adapter_module.reconcile_reprovision_scanner_foundation(
        authorization=authorization,
        deployment_binding=binding,
        cleanup_at=datetime(2026, 8, 11, 3, 45, tzinfo=UTC),
        expected_cost=3_110,
        maximum_cost=20_607,
    )
    assert result["status"] == "staging-foundation-authoritative"
    assert result["scanner-proof-execution-count"] == 0
    assert len(deployments) == 1
    assert deployments[0]["stage"] == "scanner-foundation"
    assert "runtime_config" not in deployments[0]
    assert "scanner_bridge_evidence" not in deployments[0]
    names = scanner_adapter_module.reconcile_reprovision_scanner_foundation.__code__.co_names
    assert "_claim_authorization" not in names
    assert "ScannerBridgeRecoveryAuthorization" not in names


def test_reprovision_foundation_private_endpoint_precreation_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = scanner_adapter_module._reprovision_foundation_scope(_reprovision_authorization())
    monkeypatch.setattr(scanner_adapter_module, "_rest_collection", lambda *_args: [])
    assert scanner_adapter_module._monitor_private_endpoint_precreation_count(scope) == 0

    exact = {"id": scope.monitorPrivateEndpointId, "name": "pe-mobius77-azure-monitor"}
    monkeypatch.setattr(
        scanner_adapter_module,
        "_rest_collection",
        lambda *_args: [exact],
    )
    assert scanner_adapter_module._monitor_private_endpoint_precreation_count(scope) == 1

    monkeypatch.setattr(
        scanner_adapter_module,
        "_rest_collection",
        lambda *_args: [{**exact, "id": f"{scope.targetResourceGroupId}/other"}],
    )
    with pytest.raises(
        scanner_adapter_module.ScannerBridgeRecoveryExecutionError,
        match="scanner-foundation-reprovision-endpoint-identity-drift",
    ):
        scanner_adapter_module._monitor_private_endpoint_precreation_count(scope)

    monkeypatch.setattr(
        scanner_adapter_module,
        "_rest_collection",
        lambda *_args: [exact, exact],
    )
    with pytest.raises(
        scanner_adapter_module.ScannerBridgeRecoveryExecutionError,
        match="scanner-foundation-reprovision-endpoint-duplicate",
    ):
        scanner_adapter_module._monitor_private_endpoint_precreation_count(scope)


def _generation_three_residue_rows(
    authorization: CleanupControlReprovisionAuthorization,
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    tags = adapter_module._generation_three_residue_tags(authorization)
    return (
        {
            "deletedAt": authorization.deletedKeyVaultAtUtc,
            "id": authorization.deletedKeyVaultId,
            "location": authorization.deletedKeyVaultLocation,
            "name": authorization.deletedKeyVaultName,
            "tags": tags,
        },
        {
            "customerId": authorization.deletedWorkspaceCustomerId,
            "deletedAt": authorization.deletedWorkspaceAtUtc,
            "id": authorization.deletedWorkspaceId,
            "location": authorization.deletedWorkspaceLocation,
            "name": authorization.deletedWorkspaceName,
            "tags": tags,
        },
    )


def test_reprovision_adapter_accepts_only_exact_generation_three_residue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _reprovision_authorization()
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (3_110, 20_607))
    vault, workspace = _generation_three_residue_rows(authorization)
    monkeypatch.setattr(adapter_module, "_deleted_key_vault_rows", lambda *_a: [vault])
    monkeypatch.setattr(adapter_module, "_deleted_workspace_rows", lambda *_a: [workspace])
    adapter_module._verify_generation_three_residue(authorization)

    drifted = {**workspace, "customerId": "00000000-0000-0000-0000-000000000000"}
    monkeypatch.setattr(adapter_module, "_deleted_workspace_rows", lambda *_a: [drifted])
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-reprovision-deleted-workspace-drift",
    ):
        adapter_module._verify_generation_three_residue(authorization)


def test_reprovision_adapter_reconciles_ambiguous_exact_vault_purge_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _reprovision_authorization()
    calls = 0

    def ambiguous(_subscription_id: str) -> bool:
        nonlocal calls
        calls += 1
        raise managed_binding_lifecycle.AzureCommandError("request-timeout")

    rows = iter(([{"id": authorization.deletedKeyVaultId}], []))
    monkeypatch.setattr(managed_binding_lifecycle, "_purge_exact_deleted_vault", ambiguous)
    monkeypatch.setattr(adapter_module, "_deleted_key_vault_rows", lambda *_a: next(rows))
    monkeypatch.setattr(adapter_module.time, "sleep", lambda _seconds: None)
    assert adapter_module._purge_generation_three_key_vault(authorization) is False
    assert calls == 1


def test_generation_three_residue_purge_command_is_exact_and_closed() -> None:
    command = exact_deleted_key_vault_purge_command(SUBSCRIPTION_ID)
    assert command == (
        "az",
        "keyvault",
        "purge",
        "--name",
        "kv-mobius77-11564669",
        "--location",
        "southcentralus",
        "--subscription",
        SUBSCRIPTION_ID,
        "--only-show-errors",
        "--output",
        "none",
    )
    with pytest.raises(ValueError, match="cleanup-residue-subscription-invalid"):
        exact_deleted_key_vault_purge_command("other/subscription")


def test_reprovision_deleted_workspace_readback_filters_only_exact_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _reprovision_authorization()
    observed: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> list[JsonValue]:
        observed.append(argv)
        return []

    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)
    assert adapter_module._deleted_workspace_rows(authorization) == []
    query = observed[0][observed[0].index("--query") + 1]
    assert authorization.deletedWorkspaceName in query
    assert "law-mobius76-recovery" not in query


def _install_reprovision_execution_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: CleanupControlReprovisionAuthorization,
) -> list[str]:
    events: list[str] = []
    principal_fingerprint = hashlib.sha256(
        b"mobius.azure.cleanup-principal.v1\0"
        + authorization.replacementPrincipalId.casefold().encode("ascii")
    ).hexdigest()
    contract: dict[str, JsonValue] = {
        "cleanupExecution": {
            "activeBindingId": authorization.bindingId,
            "authorizationParameter": authorization.authorizationParameter,
            "authorizationValue": authorization.authorizationParameterValue,
            "bindingContractVersion": authorization.bindingContractVersion,
            "cleanupContributorRoleDefinitionId": authorization.roleDefinitionId,
            "cleanupPrincipalFingerprintSha256": principal_fingerprint,
            "deadlineUtc": authorization.deadlineUtc,
            "publishedContentSha256": authorization.runbookContentSha256,
            "targetParameter": authorization.targetParameter,
            "targetResourceGroup": authorization.targetParameterValue,
        },
        "rbac": {"cleanupContributorRoleDefinitionId": authorization.roleDefinitionId},
    }
    monkeypatch.setattr(adapter_module, "load_managed_binding_contract", lambda: contract)
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_repository_state",
        lambda _head: events.append("repository"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_account_binding",
        lambda _now: SUBSCRIPTION_ID,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_group_exists",
        lambda _subscription, _group: True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_completed_prior_generation",
        lambda *_args: events.append("prior-proved"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_purge_generation_three_key_vault",
        lambda *_args: events.append("generation-three-vault-purged") or True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_prior_binding",
        lambda *_args, **_kwargs: events.append("prior-binding-removed") or True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_prior_schedule",
        lambda *_args: events.append("prior-schedule-removed") or True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_create_reprovision_schedule",
        lambda *_args: events.append("new-schedule-created") or True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: frozenset(),
    )
    monkeypatch.setattr(adapter_module, "_validate_cleanup_inventory", lambda *_a, **_k: None)
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verified_cost",
        lambda: (3_110, 20_607),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_compile_template",
        lambda _template: events.append("compiled"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_deploy_stage",
        lambda **kwargs: events.append(f"deploy-{kwargs['stage']}"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_configure_cleanup_runbook",
        lambda _subscription: events.append("runbook-published"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_replacement_cleanup_graph",
        lambda *_args, **_kwargs: authorization.replacementPrincipalId,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_target_role",
        lambda *_args: events.append("cleanup-role-proved"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_reconcile_container_apps_infrastructure_tags",
        lambda **_kwargs: events.append("infrastructure-tags-reconciled"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_preservable_pre_secret_state",
        lambda **_kwargs: {
            "cleanup-backstop-armed": True,
            "private-boundaries-preserved": True,
        },
    )

    def reconcile_foundation(**kwargs: object) -> dict[str, JsonValue]:
        assert kwargs["authorization"] is authorization
        assert kwargs["deployment_binding"] is not None
        events.append("scanner-foundation-authoritative")
        return {
            "foundation-integrity-sha256": "1" * 64,
            "scanner-proof-execution-count": 0,
            "status": "staging-foundation-authoritative",
        }

    monkeypatch.setattr(
        adapter_module,
        "reconcile_reprovision_scanner_foundation",
        reconcile_foundation,
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_generation_three_workspace_reconciled",
        lambda *_args: events.append("generation-three-workspace-reconciled"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_corrupted_evidence_graph",
        lambda *_args, **_kwargs: events.append("corrupted-inert"),
    )
    return events


def test_reprovision_adapter_consumes_once_and_orders_generation_before_foundation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _reprovision_authorization()
    events = _install_reprovision_execution_fakes(monkeypatch, authorization)
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: REPROVISION_NOW)
    result = adapter.execute_reprovision(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="a" * 40,
    )
    assert result["cleanup-marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["staging-marker"] == "STAGING_FOUNDATION_AUTHORITATIVE"
    assert result["foundation-proof"]["scanner-proof-execution-count"] == 0
    assert events.index("generation-three-vault-purged") < events.index("prior-schedule-removed")
    assert events.index("prior-schedule-removed") < events.index("prior-binding-removed")
    assert events.index("prior-binding-removed") < events.index("runbook-published")
    assert events.index("runbook-published") < events.index("new-schedule-created")
    assert events.index("new-schedule-created") < events.index("deploy-cleanup-job-binding")
    assert events.index("deploy-cleanup-job-binding") < events.index("deploy-cleanup-binding")
    assert events.index("deploy-cleanup-binding") < events.index("deploy-pre-secret")
    assert events.index("deploy-pre-secret") < events.index("scanner-foundation-authoritative")
    assert (tmp_path / adapter_module.POST_CLEANUP_REPROVISION_RECEIPT_FILE).is_file()
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-reprovision-authorization-already-consumed",
    ):
        adapter.execute_reprovision(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="a" * 40,
        )
    assert events.count("prior-binding-removed") == 1
    assert events.count("prior-schedule-removed") == 1
    assert events.count("generation-three-vault-purged") == 1


def test_reprovision_adapter_has_no_image_or_complete_ledger_path() -> None:
    names = ProductionCleanupControlRecoveryAdapter.execute_reprovision.__code__.co_names
    assert "build_authorization_ledger" not in names
    assert "docker" not in " ".join(names).casefold()
    assert "image" not in " ".join(names).casefold()


def test_reprovision_authorization_round_trips_and_entry_point_uses_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _reprovision_authorization()
    path = tmp_path / "reprovision-authorization.json"
    write_cleanup_control_recovery_authorization(path, authorization)
    loaded = cleanup_control_recovery.load_cleanup_control_recovery_authorization(path)
    assert loaded == authorization
    assert isinstance(loaded, CleanupControlReprovisionAuthorization)
    observed: dict[str, object] = {}

    def execute_reprovision(self: object, **kwargs: object) -> dict[str, JsonValue]:
        observed.update(kwargs)
        return {"status": "post-cleanup-reprovision-complete"}

    monkeypatch.setattr(
        ProductionCleanupControlRecoveryAdapter,
        "execute_reprovision",
        execute_reprovision,
    )
    result = cleanup_control_recovery.execute_cleanup_control_recovery(
        authorization=loaded,
        receipt_directory=tmp_path / "receipts",
        expected_repository_head="a" * 40,
    )
    assert result == {"status": "post-cleanup-reprovision-complete"}
    assert observed["authorization"] == authorization


def _reprovision_schedule_row(
    authorization: CleanupControlReprovisionAuthorization,
) -> dict[str, JsonValue]:
    return {
        "frequency": "OneTime",
        "id": (
            f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
        ),
        "isEnabled": True,
        "name": authorization.schedule,
        "startTime": authorization.deadlineUtc,
        "timeZone": "Etc/UTC",
    }


def test_reprovision_schedule_ambiguous_create_is_adopted_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _reprovision_authorization()
    rows = iter(([], [_reprovision_schedule_row(authorization)]))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(adapter_module, "_schedule_rows", lambda _authorization: next(rows))

    def ambiguous(argv: tuple[str, ...], **_kwargs: object) -> None:
        calls.append(argv)
        raise managed_binding_lifecycle.AzureCommandError("request-timeout")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", ambiguous)
    assert adapter_module._create_reprovision_schedule(authorization) is True
    assert len(calls) == 1
    assert calls[0][calls[0].index("--method") + 1] == "put"


def test_reprovision_schedule_rejects_duplicate_authoritative_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _reprovision_authorization()
    row = _reprovision_schedule_row(authorization)
    monkeypatch.setattr(
        adapter_module,
        "_schedule_rows",
        lambda _authorization: [row, row],
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-duplicate-schedule",
    ):
        adapter_module._create_reprovision_schedule(authorization)


def test_reprovision_deployment_timeout_reconciles_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_calls: list[str] = []
    reconciliation_calls: list[str] = []

    def timed_out(**kwargs: object) -> None:
        deploy_calls.append(str(kwargs["stage"]))
        raise managed_binding_lifecycle.LifecycleError("lifecycle-process-timed-out")

    monkeypatch.setattr(managed_binding_lifecycle, "_deploy_stage", timed_out)
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_reprovision_deployment_terminal",
        lambda **kwargs: reconciliation_calls.append(str(kwargs["stage"])),
    )

    adapter_module._deploy_reprovision_stage(
        template_path=Path("unused.json"),
        subscription_id=SUBSCRIPTION_ID,
        deployment_binding={},
        stage="pre-secret",
        cleanup_at=REPROVISION_NOW,
        expected_cost=3_110,
        maximum_cost=20_607,
    )

    assert deploy_calls == ["pre-secret"]
    assert reconciliation_calls == ["pre-secret"]
