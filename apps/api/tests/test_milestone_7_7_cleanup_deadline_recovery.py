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
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import cleanup_control_recovery
from preflight.milestone_7_7.cleanup_control_recovery import (
    CORRUPTED_RUNBOOK_CONTENT_SHA256,
    DEADLINE_CONTINUATION_AUTHORIZATION_VERSION,
    DEADLINE_CONTINUATION_DEADLINE_UTC,
    DEADLINE_CONTINUATION_OBSERVED_AZURE_UTC,
    DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256,
    DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
    DEADLINE_EXTENSION_DEADLINE_UTC,
    DEADLINE_EXTENSION_OBSERVED_AZURE_UTC,
    DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256,
    DEADLINE_RECOVERY_DEADLINE_UTC,
    DEADLINE_RECOVERY_OBSERVED_AZURE_UTC,
    DEADLINE_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256,
    CleanupControlDeadlineRecoveryAuthorization,
    CleanupControlRecoveryError,
    build_cleanup_control_deadline_recovery_authorization,
    cleanup_control_deadline_recovery_authorization_integrity,
    derive_cleanup_control_recovery_deadline,
    execute_cleanup_control_recovery,
    load_cleanup_control_recovery_authorization,
    validate_cleanup_control_deadline_recovery_authorization,
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
CORRUPTED_ASSIGNMENT_ID = (
    f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
    "5c1b559b-638a-5d58-b77b-b6291747f9d4"
)
REPLACEMENT_ASSIGNMENT_ID = (
    f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
    "b4acad78-f3f0-59d4-8e36-901644af1ff6"
)
OBSERVED = datetime(2026, 8, 6, 12, 23, 26, tzinfo=UTC)
NOW = datetime(2026, 8, 6, 12, 30, tzinfo=UTC)
PRIOR_EXTENSION_OBSERVED = datetime(2026, 8, 6, 14, 6, 2, tzinfo=UTC)
EXTENSION_OBSERVED = datetime(2026, 8, 6, 17, 23, 44, tzinfo=UTC)
EXTENSION_NOW = datetime(2026, 8, 6, 17, 30, tzinfo=UTC)


def _runbook_sha256() -> str:
    return cleanup_runbook_sha256(CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8"))


def _authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="b" * 40,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=(f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup"),
        corrupted_principal_id="be0e6b8d-f742-4c8f-8df1-9f302559a6c8",
        corrupted_role_assignment_id=CORRUPTED_ASSIGNMENT_ID,
        replacement_automation_account_id=(f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery"),
        replacement_principal_id="a47789c6-b8eb-40a1-898a-517a52d60a86",
        replacement_role_assignment_id=REPLACEMENT_ASSIGNMENT_ID,
        replacement_location="northeurope",
        target_resource_group_id=TARGET_GROUP,
        prior_runbook_content_sha256=(DEADLINE_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=OBSERVED,
    )


def _prior_extension_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="c" * 40,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        corrupted_principal_id="be0e6b8d-f742-4c8f-8df1-9f302559a6c8",
        corrupted_role_assignment_id=CORRUPTED_ASSIGNMENT_ID,
        replacement_automation_account_id=(f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery"),
        replacement_principal_id="a47789c6-b8eb-40a1-898a-517a52d60a86",
        replacement_role_assignment_id=REPLACEMENT_ASSIGNMENT_ID,
        replacement_location="northeurope",
        target_resource_group_id=TARGET_GROUP,
        prior_runbook_content_sha256=(DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=PRIOR_EXTENSION_OBSERVED,
        authorization_version=DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
    )


def _extension_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="c" * 40,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        corrupted_principal_id="be0e6b8d-f742-4c8f-8df1-9f302559a6c8",
        corrupted_role_assignment_id=CORRUPTED_ASSIGNMENT_ID,
        replacement_automation_account_id=(f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery"),
        replacement_principal_id="a47789c6-b8eb-40a1-898a-517a52d60a86",
        replacement_role_assignment_id=REPLACEMENT_ASSIGNMENT_ID,
        replacement_location="northeurope",
        target_resource_group_id=TARGET_GROUP,
        prior_runbook_content_sha256=(DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=EXTENSION_OBSERVED,
        authorization_version=DEADLINE_CONTINUATION_AUTHORIZATION_VERSION,
    )


def _resign(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> CleanupControlDeadlineRecoveryAuthorization:
    unsigned = replace(authorization, authorizationIntegritySha256="")
    return replace(
        unsigned,
        authorizationIntegritySha256=(
            cleanup_control_deadline_recovery_authorization_integrity(unsigned)
        ),
    )


def _final_inventory(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> frozenset[str]:
    corrupted = "microsoft.automation/automationaccounts/aa-mobius77-cleanup"
    replacement = "microsoft.automation/automationaccounts/aa-mobius77-cleanup-recovery"
    return frozenset(
        {
            corrupted,
            f"{corrupted}/runbooks/{authorization.runbook.casefold()}",
            f"{corrupted}/schedules/{authorization.schedule.casefold()}",
            replacement,
            f"{replacement}/runbooks/{authorization.runbook.casefold()}",
            f"{replacement}/schedules/{authorization.schedule.casefold()}",
            f"{replacement}/jobschedules/{authorization.bindingId.casefold()}",
        }
    )


def _install_execution_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    *,
    inventory: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    final_inventory = inventory or _final_inventory(authorization)
    initial_inventory = frozenset(
        item
        for item in final_inventory
        if not item.endswith(f"/jobschedules/{authorization.bindingId.casefold()}")
    )
    inventories = iter((initial_inventory, final_inventory))
    deployments: list[dict[str, Any]] = []
    calls: list[str] = []
    monkeypatch.setattr(
        lifecycle, "_verify_repository_state", lambda _head: calls.append("repository")
    )
    monkeypatch.setattr(lifecycle, "_account_binding", lambda _now: SUBSCRIPTION_ID)
    monkeypatch.setattr(lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: next(inventories),
    )

    def verify_corrupted(*_args: object, **kwargs: object) -> None:
        calls.append(f"corrupted-graph:{kwargs.get('expected_runbook_hash')}")

    monkeypatch.setattr(
        adapter_module,
        "_verify_corrupted_evidence_graph",
        verify_corrupted,
    )

    def verify_replacement(*_args: object, **kwargs: object) -> str:
        calls.append(f"replacement-graph:{kwargs['binding_required']}")
        return authorization.replacementPrincipalId

    monkeypatch.setattr(adapter_module, "_verify_replacement_cleanup_graph", verify_replacement)
    monkeypatch.setattr(
        adapter_module,
        "_remove_prior_binding",
        lambda _authorization: calls.append("remove-binding") or False,
    )
    monkeypatch.setattr(
        adapter_module,
        "_reconcile_deadline_runbook",
        lambda *_args: calls.append("publish-runbook") or True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_replace_cleanup_schedule",
        lambda _authorization: calls.append("replace-schedule") or True,
    )
    monkeypatch.setattr(lifecycle, "_compile_template", lambda _path: calls.append("compile"))

    def deploy(**kwargs: Any) -> None:
        calls.append("deploy-binding")
        deployments.append(kwargs)

    monkeypatch.setattr(lifecycle, "_deploy_stage", deploy)
    return deployments, calls


def test_deadline_is_the_exact_next_quarter_hour_after_six_hours() -> None:
    derived = derive_cleanup_control_recovery_deadline(OBSERVED)
    assert derived == datetime(2026, 8, 6, 18, 30, tzinfo=UTC)
    assert derived.isoformat().replace("+00:00", "Z") == (DEADLINE_RECOVERY_DEADLINE_UTC)
    assert DEADLINE_RECOVERY_OBSERVED_AZURE_UTC == "2026-08-06T12:23:26Z"


def test_extension_deadline_is_exactly_ten_hours_then_next_quarter() -> None:
    derived = derive_cleanup_control_recovery_deadline(
        PRIOR_EXTENSION_OBSERVED, minimum_lead_hours=10
    )
    assert derived == datetime(2026, 8, 7, 0, 15, tzinfo=UTC)
    assert DEADLINE_EXTENSION_OBSERVED_AZURE_UTC == "2026-08-06T14:06:02Z"
    assert DEADLINE_EXTENSION_DEADLINE_UTC == "2026-08-07T00:15:00Z"


def test_continuation_preserves_generation_two_and_uses_one_new_binding() -> None:
    original = _prior_extension_authorization()
    extension = _extension_authorization()

    assert original.authorizationVersion != extension.authorizationVersion
    assert original.bindingId == extension.priorBindingId
    assert extension.bindingId == "5ffc55c1-7a88-5231-b0d1-e76ee95d057e"
    assert extension.deadlineUtc == DEADLINE_CONTINUATION_DEADLINE_UTC
    assert extension.priorRunbookContentSha256 == (
        DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256
    )


def test_continuation_deadline_is_exactly_twelve_hours_then_next_quarter() -> None:
    derived = derive_cleanup_control_recovery_deadline(EXTENSION_OBSERVED, minimum_lead_hours=12)
    assert derived == datetime(2026, 8, 7, 5, 30, tzinfo=UTC)
    assert DEADLINE_CONTINUATION_OBSERVED_AZURE_UTC == "2026-08-06T17:23:44Z"
    assert DEADLINE_CONTINUATION_DEADLINE_UTC == "2026-08-07T05:30:00Z"


def test_deadline_authorization_is_exact_image_free_and_round_trips(
    tmp_path: Path,
) -> None:
    authorization = _authorization()
    path = tmp_path / "authorization.json"
    write_cleanup_control_recovery_authorization(path, authorization)
    loaded = load_cleanup_control_recovery_authorization(path)

    assert loaded == authorization
    assert isinstance(loaded, CleanupControlDeadlineRecoveryAuthorization)
    assert authorization.priorDeadlineUtc == "2026-08-06T12:00:00Z"
    assert authorization.deadlineUtc == "2026-08-06T18:30:00Z"
    assert authorization.priorBindingId == "f61544fe-cd79-5247-ac8b-ee9697b6ffd6"
    assert authorization.bindingId == "ecdbb32f-9134-5697-85f9-d569ba57454b"
    assert authorization.replacementRoleAssignmentId == REPLACEMENT_ASSIGNMENT_ID
    assert authorization.replacementLocation == "northeurope"
    serialized = asdict(authorization)
    assert all("image" not in key.casefold() for key in serialized)
    assert all("acr" not in operation for operation in authorization.allowedOperations)
    receipt_input = json.loads(path.read_text(encoding="utf-8"))
    assert receipt_input["deadlineObservedAtUtc"] == "2026-08-06T12:23:26Z"
    assert receipt_input["deadlineUtc"] == "2026-08-06T18:30:00Z"
    assert authorization.priorRunbookContentSha256 == (
        DEADLINE_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("replacementAutomationAccount", "other-account"),
        ("replacementPrincipalId", "00000000-0000-0000-0000-000000000000"),
        (
            "replacementRoleAssignmentId",
            f"{TARGET_GROUP}/providers/Microsoft.Authorization/roleAssignments/"
            "00000000-0000-0000-0000-000000000000",
        ),
        ("replacementLocation", "westus"),
        ("targetResourceGroupId", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("roleDefinitionId", "00000000-0000-0000-0000-000000000000"),
        ("roleScope", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("runbook", "OtherRunbook"),
        ("schedule", "other-schedule"),
        ("deadlineUtc", "2026-08-06T18:45:00Z"),
        ("priorBindingId", "00000000-0000-0000-0000-000000000000"),
        ("bindingId", "00000000-0000-0000-0000-000000000000"),
        ("targetParameterValue", "other-target"),
        ("authorizationParameterValue", False),
    ],
)
def test_deadline_authorization_rejects_every_scope_or_deadline_drift(
    field: str, value: object
) -> None:
    authorization = _resign(replace(_authorization(), **{field: value}))
    with pytest.raises(CleanupControlRecoveryError):
        validate_cleanup_control_deadline_recovery_authorization(
            authorization,
            expected_repository_head="b" * 40,
            now_utc=NOW,
        )


def test_production_adapter_consumes_deadline_authorization_and_maps_only_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _extension_authorization()
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)

    result = ProductionCleanupControlRecoveryAdapter(
        clock=lambda: EXTENSION_NOW
    ).execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="c" * 40,
    )

    assert result["marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["deadline-utc"] == "2026-08-07T05:30:00Z"
    assert result["binding-id"] == "5ffc55c1-7a88-5231-b0d1-e76ee95d057e"
    assert len(deployments) == 1
    assert deployments[0]["stage"] == "cleanup-job-binding"
    assert deployments[0]["cleanup_at"] == datetime(2026, 8, 7, 5, 30, tzinfo=UTC)
    assert deployments[0]["maximum_cost"] == 25_000
    assert calls.index("remove-binding") < calls.index("publish-runbook")
    assert calls.index("remove-binding") < calls.index("replace-schedule")
    assert calls.index("replace-schedule") < calls.index("deploy-binding")
    assert calls.count(f"corrupted-graph:{CORRUPTED_RUNBOOK_CONTENT_SHA256}") == 2
    receipt = json.loads(
        (tmp_path / adapter_module.DEADLINE_RECOVERY_RECEIPT_FILE).read_text(encoding="utf-8")
    )
    assert receipt["replayDecision"] == "deny"
    assert receipt["deadlineUtc"] == authorization.deadlineUtc
    assert receipt["priorBindingId"] == authorization.priorBindingId


def test_deadline_adapter_cannot_reach_application_image_or_lifecycle_operations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _extension_authorization()
    _install_execution_fakes(monkeypatch, authorization)

    def prohibited(*_args: object, **_kwargs: object) -> None:
        pytest.fail("prohibited image, application, migration, or cleanup operation reached")

    for symbol in (
        "_prebuild_api_image",
        "_publish_api_image",
        "_publish_api_image_stage",
        "_post_secret",
        "_private_path_stage",
        "_cleanup",
    ):
        monkeypatch.setattr(lifecycle, symbol, prohibited)
    monkeypatch.setattr(
        "preflight.milestone_7_7.managed_binding_contracts.build_authorization_ledger",
        prohibited,
    )

    result = ProductionCleanupControlRecoveryAdapter(
        clock=lambda: EXTENSION_NOW
    ).execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="c" * 40,
    )

    assert result["cleanup-executable"] is True
    annotations = ProductionCleanupControlRecoveryAdapter.execute_deadline_recovery.__annotations__
    assert "image" not in " ".join(annotations).casefold()


def test_ambiguous_binding_delete_reconciles_without_second_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _extension_authorization()
    row: JsonValue = {
        "id": (
            f"{authorization.replacementAutomationAccountId}/jobSchedules/"
            f"{authorization.priorBindingId}"
        ),
        "jobScheduleId": authorization.priorBindingId,
        "parameters": {
            "CleanupAuthorized": "true",
            "TargetResourceGroupName": "rg-solarplexus-mobius-77-staging",
        },
        "runbook": authorization.runbook,
        "schedule": authorization.schedule,
    }
    states = iter(([row], []))
    monkeypatch.setattr(adapter_module, "_job_schedule_rows", lambda _auth: next(states))
    deletes: list[tuple[str, ...]] = []

    def ambiguous(argv: tuple[str, ...], **_kwargs: object) -> None:
        deletes.append(argv)
        raise lifecycle.AzureCommandError("response-lost")

    monkeypatch.setattr(lifecycle, "_run", ambiguous)
    assert adapter_module._remove_prior_binding(authorization) is True
    assert len(deletes) == 1
    assert deletes[0][deletes[0].index("--method") + 1] == "delete"


def test_binding_readback_lists_identity_then_gets_exact_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _extension_authorization()
    resource_id = (
        f"{authorization.replacementAutomationAccountId}/jobSchedules/{authorization.bindingId}"
    )
    listed: JsonValue = {
        "id": resource_id,
        "jobScheduleId": authorization.bindingId,
        "runbook": authorization.runbook,
        "schedule": authorization.schedule,
    }
    detailed: JsonValue = {
        **listed,
        "parameters": {
            "CleanupAuthorized": "true",
            "TargetResourceGroupName": "rg-solarplexus-mobius-77-staging",
        },
    }
    monkeypatch.setattr(
        adapter_module,
        "_replacement_collection",
        lambda *_args, **_kwargs: [listed],
    )
    calls: list[tuple[str, ...]] = []

    def exact_get(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        calls.append(argv)
        return detailed

    monkeypatch.setattr(lifecycle, "_run", exact_get)

    assert adapter_module._job_schedule_rows(authorization) == [detailed]
    assert len(calls) == 1
    assert calls[0][calls[0].index("--url") + 1] == (
        f"https://management.azure.com{resource_id}?api-version=2024-10-23"
    )


def test_ambiguous_schedule_mutations_reconcile_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()

    def schedule_row(deadline: str) -> JsonValue:
        return {
            "frequency": "OneTime",
            "id": (
                f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
            ),
            "isEnabled": True,
            "name": authorization.schedule,
            "startTime": deadline,
            "timeZone": "Etc/UTC",
        }

    states = iter(
        (
            [schedule_row(authorization.priorDeadlineUtc)],
            [],
            [schedule_row(authorization.deadlineUtc)],
        )
    )
    monkeypatch.setattr(adapter_module, "_schedule_rows", lambda _auth: next(states))
    methods: list[str] = []

    def ambiguous(argv: tuple[str, ...], **_kwargs: object) -> None:
        methods.append(argv[argv.index("--method") + 1])
        raise lifecycle.AzureCommandError("response-lost")

    monkeypatch.setattr(lifecycle, "_run", ambiguous)
    assert adapter_module._replace_cleanup_schedule(authorization) is True
    assert methods == ["delete", "put"]


def test_duplicate_schedule_or_binding_is_rejected() -> None:
    authorization = _authorization()
    schedule: JsonValue = {
        "frequency": "OneTime",
        "id": f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}",
        "isEnabled": True,
        "name": authorization.schedule,
        "startTime": authorization.deadlineUtc,
        "timeZone": "Etc/UTC",
    }
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-duplicate-schedule",
    ):
        adapter_module._validated_schedule_deadline(
            authorization,
            [schedule, schedule],
            allowed_deadlines=frozenset({authorization.deadlineUtc}),
            required=True,
        )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-duplicate-binding",
    ):
        adapter_module._validate_job_schedule_rows(
            authorization,
            [{}, {}],
            required=None,
        )


def test_deadline_authorization_replay_is_denied_before_second_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _extension_authorization()
    deployments, calls = _install_execution_fakes(
        monkeypatch, authorization, inventory=_final_inventory(authorization)
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: _final_inventory(authorization),
    )
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: EXTENSION_NOW)
    adapter.execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="c" * 40,
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-authorization-already-consumed",
    ):
        adapter.execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="c" * 40,
        )
    assert len(deployments) == 1
    assert calls.count("remove-binding") == 1
    assert calls.count("replace-schedule") == 1


def test_existing_cleanup_recovery_entry_point_dispatches_deadline_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    observed: dict[str, object] = {}

    def execute_deadline_recovery(self: object, **kwargs: object) -> dict[str, JsonValue]:
        del self
        observed.update(kwargs)
        return {"status": "cleanup-control-deadline-recovery-executable"}

    monkeypatch.setattr(
        ProductionCleanupControlRecoveryAdapter,
        "execute_deadline_recovery",
        execute_deadline_recovery,
    )
    result = execute_cleanup_control_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="b" * 40,
    )
    assert result["status"] == "cleanup-control-deadline-recovery-executable"
    assert observed["authorization"] is authorization
    assert (
        "build_authorization_ledger"
        not in build_cleanup_control_deadline_recovery_authorization.__code__.co_names
    )
    assert cleanup_control_recovery.CleanupControlDeadlineRecoveryAuthorization is (
        CleanupControlDeadlineRecoveryAuthorization
    )
