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


def _runbook_sha256() -> str:
    return cleanup_runbook_sha256(CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8"))


def _authorization() -> CleanupControlRecoveryAuthorization:
    return build_cleanup_control_recovery_authorization(
        repository_head="a" * 40,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
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
        {"microsoft.automation/automationaccounts/aa-mobius77-cleanup"}
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
        managed_binding_lifecycle,
        "_resource_group_inventory",
        lambda **kwargs: next(inventories),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_recovered_cleanup_seed_state",
        lambda subscription: calls.append(("seed", (subscription,))),
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


def test_cleanup_recovery_authorization_is_image_free_and_exact() -> None:
    authorization = _authorization()
    serialized = asdict(authorization)
    assert authorization.replacementAutomationAccount == "aa-mobius77-cleanup-recovery"
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
        managed_binding_lifecycle,
        "_resource_group_inventory",
        lambda **kwargs: next(inventories),
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
