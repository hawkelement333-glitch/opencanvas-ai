from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from infra.milestone_7_7 import cleanup_control_recovery_adapter as adapter_module
from infra.milestone_7_7.cleanup_control_recovery_adapter import (
    CleanupControlRecoveryExecutionError,
    ProductionCleanupControlRecoveryAdapter,
)
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import cleanup_control_recovery
from preflight.milestone_7_7.cleanup_control_recovery import (
    CleanupControlRecoveryAuthorization,
    CleanupControlRecoveryError,
    build_cleanup_control_recovery_authorization,
    cleanup_control_recovery_authorization_integrity,
    validate_cleanup_control_recovery_authorization,
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
PRINCIPAL_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CORRUPTED_PRINCIPAL_ID = "be0e6b8d-f742-4c8f-8df1-9f302559a6c8"
CORRUPTED_ASSIGNMENT_ID = (
    f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
    "5c1b559b-638a-5d58-b77b-b6291747f9d4"
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
    assert authorization.bindingId == "f61544fe-cd79-5247-ac8b-ee9697b6ffd6"
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
