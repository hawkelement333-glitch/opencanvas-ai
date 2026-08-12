from __future__ import annotations

import hashlib
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
    CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION,
    CLEANUP_RECOVERY_V9_DEADLINE_UTC,
    CLEANUP_RECOVERY_V9_OBSERVED_AZURE_UTC,
    CORRUPTED_RUNBOOK_CONTENT_SHA256,
    DEADLINE_COMPLETION_AUTHORIZATION_VERSION,
    DEADLINE_COMPLETION_DEADLINE_UTC,
    DEADLINE_COMPLETION_OBSERVED_AZURE_UTC,
    DEADLINE_COMPLETION_PRIOR_RUNBOOK_CONTENT_SHA256,
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
    GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION,
    GENERATION_FOUR_COMPLETION_EXTENSION_DEADLINE_UTC,
    GENERATION_FOUR_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC,
    GENERATION_FOUR_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256,
    GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
    GENERATION_FOUR_DEADLINE_EXTENSION_DEADLINE_UTC,
    GENERATION_FOUR_DEADLINE_EXTENSION_OBSERVED_AZURE_UTC,
    GENERATION_FOUR_DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256,
    POST_FIRED_EXPECTED_TARGET_RESOURCE_COUNT,
    POST_FIRED_PRIOR_JOB_EXCEPTION,
    POST_FIRED_PRIOR_JOB_NAME,
    POST_FIRED_RECOVERY_AUTHORIZATION_VERSION,
    POST_FIRED_RECOVERY_DEADLINE_UTC,
    POST_FIRED_RECOVERY_OBSERVED_AZURE_UTC,
    POST_FIRED_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256,
    POST_FIRED_RECOVERY_PURPOSE,
    POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION,
    POST_V7_FINAL_COMPLETION_EXTENSION_DEADLINE_UTC,
    POST_V7_FINAL_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC,
    POST_V7_FINAL_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256,
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
CONTINUATION_OBSERVED = datetime(2026, 8, 6, 17, 23, 44, tzinfo=UTC)
COMPLETION_OBSERVED = datetime(2026, 8, 6, 23, 39, 5, tzinfo=UTC)
COMPLETION_NOW = datetime(2026, 8, 6, 23, 40, tzinfo=UTC)
POST_FIRED_OBSERVED = datetime(2026, 8, 7, 18, 14, 28, tzinfo=UTC)
POST_FIRED_NOW = datetime(2026, 8, 7, 18, 20, tzinfo=UTC)
GENERATION_FOUR_EXTENSION_OBSERVED = datetime(2026, 8, 11, 1, 30, tzinfo=UTC)
GENERATION_FOUR_EXTENSION_NOW = datetime(2026, 8, 11, 1, 35, tzinfo=UTC)
GENERATION_FOUR_COMPLETION_OBSERVED = datetime(2026, 8, 11, 14, 2, 42, tzinfo=UTC)
GENERATION_FOUR_COMPLETION_NOW = datetime(2026, 8, 11, 14, 10, tzinfo=UTC)
POST_V7_FINAL_COMPLETION_OBSERVED = datetime(2026, 8, 12, 4, 3, 19, tzinfo=UTC)
POST_V7_FINAL_COMPLETION_NOW = datetime(2026, 8, 12, 4, 10, tzinfo=UTC)
CLEANUP_RECOVERY_V9_OBSERVED = datetime(2026, 8, 12, 20, 23, 35, tzinfo=UTC)
CLEANUP_RECOVERY_V9_NOW = datetime(2026, 8, 12, 20, 30, tzinfo=UTC)


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


def _continuation_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
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
        observed_azure_utc=CONTINUATION_OBSERVED,
        authorization_version=DEADLINE_CONTINUATION_AUTHORIZATION_VERSION,
    )


def _completion_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
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
        prior_runbook_content_sha256=(DEADLINE_COMPLETION_PRIOR_RUNBOOK_CONTENT_SHA256),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=COMPLETION_OBSERVED,
        authorization_version=DEADLINE_COMPLETION_AUTHORIZATION_VERSION,
    )


def _post_fired_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    prior_job_id = (
        f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery/jobs/{POST_FIRED_PRIOR_JOB_NAME}"
    )
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="d" * 40,
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
        prior_runbook_content_sha256=(POST_FIRED_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=POST_FIRED_OBSERVED,
        authorization_version=POST_FIRED_RECOVERY_AUTHORIZATION_VERSION,
        prior_cleanup_job_id=prior_job_id,
        prior_cleanup_job_status="Failed",
        prior_cleanup_job_exception=POST_FIRED_PRIOR_JOB_EXCEPTION,
        target_resource_count=41,
        delete_activity_count=0,
        nonterminal_cleanup_job_count=0,
    )


def _generation_four_extension_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="e" * 40,
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
        prior_runbook_content_sha256=(
            GENERATION_FOUR_DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
        ),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=GENERATION_FOUR_EXTENSION_OBSERVED,
        authorization_version=(GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_VERSION),
    )


def _generation_four_completion_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="f" * 40,
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
        prior_runbook_content_sha256=(
            GENERATION_FOUR_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
        ),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=GENERATION_FOUR_COMPLETION_OBSERVED,
        authorization_version=(GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION),
    )


def _post_v7_final_completion_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="1" * 40,
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
        prior_runbook_content_sha256=(
            POST_V7_FINAL_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
        ),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=POST_V7_FINAL_COMPLETION_OBSERVED,
        authorization_version=(POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION),
    )


def _cleanup_recovery_v9_authorization() -> CleanupControlDeadlineRecoveryAuthorization:
    return build_cleanup_control_deadline_recovery_authorization(
        repository_head="2" * 40,
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
        prior_runbook_content_sha256=(
            POST_V7_FINAL_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
        ),
        runbook_content_sha256=_runbook_sha256(),
        observed_azure_utc=CLEANUP_RECOVERY_V9_OBSERVED,
        authorization_version=CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION,
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
    corrupted_schedule = (
        "schedule-mobius77-cleanup"
        if authorization.authorizationVersion
        in {
            GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
            GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION,
            POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION,
            CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION,
        }
        else authorization.schedule
    )
    return frozenset(
        {
            corrupted,
            f"{corrupted}/runbooks/{authorization.runbook.casefold()}",
            f"{corrupted}/schedules/{corrupted_schedule.casefold()}",
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
    historical_contract: dict[str, JsonValue] = {
        "cleanupExecution": {
            "activeBindingId": authorization.bindingId,
            "authorizationParameter": authorization.authorizationParameter,
            "authorizationValue": authorization.authorizationParameterValue,
            "bindingContractVersion": authorization.bindingContractVersion,
            "cleanupContributorRoleDefinitionId": authorization.roleDefinitionId,
            "cleanupPrincipalFingerprintSha256": hashlib.sha256(
                b"mobius.azure.cleanup-principal.v1\0"
                + authorization.replacementPrincipalId.casefold().encode("ascii")
            ).hexdigest(),
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
        lifecycle, "_verify_repository_state", lambda _head: calls.append("repository")
    )
    monkeypatch.setattr(lifecycle, "_account_binding", lambda _now: SUBSCRIPTION_ID)
    monkeypatch.setattr(lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(lifecycle, "_verified_cost", lambda: (3_110, 20_607))
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
        "_verify_post_fired_cleanup_state",
        lambda *_args, **_kwargs: calls.append("post-fired-state") or 41,
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_post_fired_target_preservation",
        lambda *_args, **_kwargs: calls.append("post-fired-preservation") or 41,
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_post_fired_rearmed_target_tags",
        lambda *_args, **_kwargs: calls.append("post-fired-tags"),
    )
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
    extension = _continuation_authorization()

    assert original.authorizationVersion != extension.authorizationVersion
    assert original.bindingId == extension.priorBindingId
    assert extension.bindingId == "5ffc55c1-7a88-5231-b0d1-e76ee95d057e"
    assert extension.deadlineUtc == DEADLINE_CONTINUATION_DEADLINE_UTC
    assert extension.priorRunbookContentSha256 == (
        DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256
    )


def test_continuation_deadline_is_exactly_twelve_hours_then_next_quarter() -> None:
    derived = derive_cleanup_control_recovery_deadline(CONTINUATION_OBSERVED, minimum_lead_hours=12)
    assert derived == datetime(2026, 8, 7, 5, 30, tzinfo=UTC)
    assert DEADLINE_CONTINUATION_OBSERVED_AZURE_UTC == "2026-08-06T17:23:44Z"
    assert DEADLINE_CONTINUATION_DEADLINE_UTC == "2026-08-07T05:30:00Z"


def test_completion_preserves_generation_two_and_uses_one_new_binding() -> None:
    continuation = _continuation_authorization()
    completion = _completion_authorization()

    assert continuation.authorizationVersion != completion.authorizationVersion
    assert continuation.bindingId == completion.priorBindingId
    assert completion.bindingId == "a5429a32-87e3-5963-8c3a-bef85e777ed5"
    assert completion.deadlineUtc == DEADLINE_COMPLETION_DEADLINE_UTC
    assert completion.priorRunbookContentSha256 == (
        DEADLINE_COMPLETION_PRIOR_RUNBOOK_CONTENT_SHA256
    )


def test_completion_deadline_is_exactly_twelve_hours_then_next_quarter() -> None:
    derived = derive_cleanup_control_recovery_deadline(COMPLETION_OBSERVED, minimum_lead_hours=12)
    assert derived == datetime(2026, 8, 7, 11, 45, tzinfo=UTC)
    assert DEADLINE_COMPLETION_OBSERVED_AZURE_UTC == "2026-08-06T23:39:05Z"
    assert DEADLINE_COMPLETION_DEADLINE_UTC == "2026-08-07T11:45:00Z"


def test_post_fired_deadline_is_exactly_eighteen_hours_then_next_quarter() -> None:
    derived = derive_cleanup_control_recovery_deadline(POST_FIRED_OBSERVED, minimum_lead_hours=18)
    assert derived == datetime(2026, 8, 8, 12, 15, tzinfo=UTC)
    assert POST_FIRED_RECOVERY_OBSERVED_AZURE_UTC == "2026-08-07T18:14:28Z"
    assert POST_FIRED_RECOVERY_DEADLINE_UTC == "2026-08-08T12:15:00Z"


def test_generation_four_extension_binds_exact_schedule_deadline_and_binding(
    tmp_path: Path,
) -> None:
    authorization = _generation_four_extension_authorization()
    path = tmp_path / "generation-four-extension.json"
    write_cleanup_control_recovery_authorization(path, authorization)

    assert authorization.schedule == "schedule-mobius77-cleanup-g4"
    assert authorization.priorDeadlineUtc == "2026-08-11T03:45:00Z"
    assert authorization.deadlineUtc == GENERATION_FOUR_DEADLINE_EXTENSION_DEADLINE_UTC
    assert authorization.priorBindingId == "34b1d170-652b-505a-9cc1-b8177b872ff0"
    assert authorization.bindingId == "57e1b300-a91a-5629-995e-d587fd0e0cdb"
    assert authorization.bindingContractVersion == "m7.7-automation-cleanup-binding-v4"
    assert GENERATION_FOUR_DEADLINE_EXTENSION_OBSERVED_AZURE_UTC == ("2026-08-11T01:30:00Z")
    assert derive_cleanup_control_recovery_deadline(
        GENERATION_FOUR_EXTENSION_OBSERVED, minimum_lead_hours=18
    ) == datetime(2026, 8, 11, 19, 30, tzinfo=UTC)
    assert load_cleanup_control_recovery_authorization(path) == authorization


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schedule", "schedule-mobius77-cleanup"),
        ("priorBindingId", "12f27fa6-2cd5-548d-be20-c6e03a5e19d3"),
        ("bindingId", "34b1d170-652b-505a-9cc1-b8177b872ff0"),
        ("bindingContractVersion", "m7.7-automation-cleanup-binding-v3"),
    ],
)
def test_generation_four_extension_rejects_transition_drift(field: str, value: object) -> None:
    authorization = _generation_four_extension_authorization()
    drifted = _resign(replace(authorization, **{field: value}))

    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-deadline-recovery-authorization-scope-invalid",
    ):
        validate_cleanup_control_deadline_recovery_authorization(
            drifted,
            expected_repository_head="e" * 40,
            now_utc=GENERATION_FOUR_EXTENSION_NOW,
        )


def test_generation_four_extension_executes_one_exact_transition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _generation_four_extension_authorization()
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)

    result = ProductionCleanupControlRecoveryAdapter(
        clock=lambda: GENERATION_FOUR_EXTENSION_NOW
    ).execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="e" * 40,
    )

    assert result["marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["deadline-utc"] == "2026-08-11T19:30:00Z"
    assert result["prior-binding-absent"] is True
    assert len(deployments) == 1
    assert calls.index("remove-binding") < calls.index("replace-schedule")
    assert calls.index("replace-schedule") < calls.index("deploy-binding")
    receipt = json.loads(
        (tmp_path / adapter_module.DEADLINE_RECOVERY_RECEIPT_FILE).read_text(encoding="utf-8")
    )
    assert receipt["receiptVersion"] == (
        adapter_module.GENERATION_FOUR_DEADLINE_EXTENSION_RECEIPT_VERSION
    )


def test_generation_four_completion_extension_executes_one_exact_transition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _generation_four_completion_authorization()
    authorization_path = tmp_path / "generation-four-completion-extension.json"
    write_cleanup_control_recovery_authorization(authorization_path, authorization)
    assert load_cleanup_control_recovery_authorization(authorization_path) == authorization
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)

    result = ProductionCleanupControlRecoveryAdapter(
        clock=lambda: GENERATION_FOUR_COMPLETION_NOW
    ).execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="f" * 40,
    )

    assert authorization.schedule == "schedule-mobius77-cleanup-g4"
    assert authorization.priorDeadlineUtc == "2026-08-11T19:30:00Z"
    assert authorization.deadlineUtc == GENERATION_FOUR_COMPLETION_EXTENSION_DEADLINE_UTC
    assert authorization.priorBindingId == "57e1b300-a91a-5629-995e-d587fd0e0cdb"
    assert authorization.bindingId == "e830f957-0b9b-5859-87ec-e0ac8ffc59c3"
    assert GENERATION_FOUR_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC == ("2026-08-11T14:02:42Z")
    assert derive_cleanup_control_recovery_deadline(
        GENERATION_FOUR_COMPLETION_OBSERVED, minimum_lead_hours=18
    ) == datetime(2026, 8, 12, 8, 15, tzinfo=UTC)
    assert result["marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["deadline-utc"] == "2026-08-12T08:15:00Z"
    assert result["prior-binding-absent"] is True
    assert len(deployments) == 1
    assert calls.index("remove-binding") < calls.index("replace-schedule")
    assert calls.index("replace-schedule") < calls.index("deploy-binding")
    receipt = json.loads(
        (tmp_path / adapter_module.DEADLINE_RECOVERY_RECEIPT_FILE).read_text(encoding="utf-8")
    )
    assert receipt["receiptVersion"] == (
        adapter_module.GENERATION_FOUR_COMPLETION_EXTENSION_RECEIPT_VERSION
    )


def test_post_v7_contract_preserves_v7_and_binds_exact_successor(
    tmp_path: Path,
) -> None:
    predecessor = _generation_four_completion_authorization()
    authorization = _post_v7_final_completion_authorization()
    path = tmp_path / "post-v7-final-completion-extension.json"
    write_cleanup_control_recovery_authorization(path, authorization)

    assert load_cleanup_control_recovery_authorization(path) == authorization
    assert predecessor.authorizationVersion == (
        GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION
    )
    assert predecessor.deadlineUtc == "2026-08-12T08:15:00Z"
    assert predecessor.bindingId == "e830f957-0b9b-5859-87ec-e0ac8ffc59c3"
    assert authorization.authorizationVersion == (
        "mobius.milestone-7.7.cleanup-control-deadline-recovery.v8"
    )
    assert authorization.priorDeadlineUtc == predecessor.deadlineUtc
    assert authorization.priorBindingId == predecessor.bindingId
    assert authorization.bindingId == "708810d2-d718-55c8-aac6-3baf75f18364"
    assert authorization.deadlineUtc == POST_V7_FINAL_COMPLETION_EXTENSION_DEADLINE_UTC
    assert authorization.schedule == "schedule-mobius77-cleanup-g4"
    assert authorization.bindingContractVersion == "m7.7-automation-cleanup-binding-v4"
    assert POST_V7_FINAL_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC == ("2026-08-12T04:03:19Z")
    assert derive_cleanup_control_recovery_deadline(
        POST_V7_FINAL_COMPLETION_OBSERVED,
        minimum_lead_hours=18,
    ) == datetime(2026, 8, 12, 22, 15, tzinfo=UTC)


def test_v7_receipt_remains_replay_denied_after_v8_is_introduced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = _generation_four_completion_authorization()
    _install_execution_fakes(monkeypatch, authorization)
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: GENERATION_FOUR_COMPLETION_NOW)
    adapter.execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="f" * 40,
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: _final_inventory(authorization),
    )

    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-authorization-already-consumed",
    ):
        adapter.execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="f" * 40,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repositoryHead", "2" * 40),
        ("priorDeadlineUtc", "2026-08-12T08:30:00Z"),
        ("priorBindingId", "57e1b300-a91a-5629-995e-d587fd0e0cdb"),
        ("bindingId", "e830f957-0b9b-5859-87ec-e0ac8ffc59c3"),
        ("schedule", "schedule-mobius77-cleanup"),
        ("replacementAutomationAccount", "other-account"),
        ("targetResourceGroupId", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("roleDefinitionId", "00000000-0000-0000-0000-000000000000"),
        ("roleScope", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("costCeilingUsdCents", 24_999),
        ("deadlineUtc", "2026-08-12T22:30:00Z"),
    ],
)
def test_post_v7_contract_rejects_head_predecessor_scope_cost_or_deadline_drift(
    field: str,
    value: object,
) -> None:
    authorization = _resign(replace(_post_v7_final_completion_authorization(), **{field: value}))

    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-deadline-recovery-authorization-scope-invalid",
    ):
        validate_cleanup_control_deadline_recovery_authorization(
            authorization,
            expected_repository_head="1" * 40,
            now_utc=POST_V7_FINAL_COMPLETION_NOW,
        )


def test_post_v7_contract_rejects_insufficient_completion_headroom() -> None:
    authorization = _post_v7_final_completion_authorization()

    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-deadline-recovery-completion-window-insufficient",
    ):
        validate_cleanup_control_deadline_recovery_authorization(
            authorization,
            expected_repository_head="1" * 40,
            now_utc=datetime(2026, 8, 12, 14, 0, 1, tzinfo=UTC),
        )


def test_post_v7_contract_executes_one_transition_and_denies_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = _post_v7_final_completion_authorization()
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: POST_V7_FINAL_COMPLETION_NOW)

    result = adapter.execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="1" * 40,
    )

    assert result["marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["deadline-utc"] == "2026-08-12T22:15:00Z"
    assert result["binding-id"] == "708810d2-d718-55c8-aac6-3baf75f18364"
    assert result["prior-binding-absent"] is True
    assert len(deployments) == 1
    assert calls.index("remove-binding") < calls.index("replace-schedule")
    assert calls.index("replace-schedule") < calls.index("deploy-binding")
    receipt = json.loads(
        (tmp_path / adapter_module.DEADLINE_RECOVERY_RECEIPT_FILE).read_text(encoding="utf-8")
    )
    assert receipt["receiptVersion"] == (
        adapter_module.POST_V7_FINAL_COMPLETION_EXTENSION_RECEIPT_VERSION
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: _final_inventory(authorization),
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-authorization-already-consumed",
    ):
        adapter.execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="1" * 40,
        )
    assert len(deployments) == 1
    assert calls.count("remove-binding") == 1


def test_post_v7_parallel_schedule_or_binding_is_rejected() -> None:
    authorization = _post_v7_final_completion_authorization()
    schedule: JsonValue = {
        "frequency": "OneTime",
        "id": (
            f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
        ),
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


def test_cleanup_recovery_v9_binds_exact_v8_predecessor_and_round_trips(
    tmp_path: Path,
) -> None:
    predecessor = _post_v7_final_completion_authorization()
    authorization = _cleanup_recovery_v9_authorization()
    path = tmp_path / "cleanup-recovery-v9.json"
    write_cleanup_control_recovery_authorization(path, authorization)

    assert load_cleanup_control_recovery_authorization(path) == authorization
    assert authorization.authorizationVersion == (
        "mobius.milestone-7.7.cleanup-control-deadline-recovery.v9"
    )
    assert authorization.priorDeadlineUtc == predecessor.deadlineUtc
    assert authorization.priorBindingId == predecessor.bindingId
    assert authorization.bindingId == "6a1caaa1-3b61-50e2-9ed6-44abb4a3a87a"
    assert authorization.deadlineUtc == CLEANUP_RECOVERY_V9_DEADLINE_UTC
    assert authorization.deadlineObservedAtUtc == CLEANUP_RECOVERY_V9_OBSERVED_AZURE_UTC
    assert authorization.schedule == "schedule-mobius77-cleanup-g4"
    assert authorization.runbook == "Remove-Mobius77Staging"
    assert authorization.roleDefinitionId == "b24988ac-6180-42a0-ab88-20f7382dd24c"
    assert authorization.roleScope == TARGET_GROUP
    assert authorization.targetParameterValue == "rg-solarplexus-mobius-77-staging"
    assert authorization.authorizationParameterValue is True
    assert all("image" not in operation for operation in authorization.allowedOperations)
    assert derive_cleanup_control_recovery_deadline(
        CLEANUP_RECOVERY_V9_OBSERVED,
        minimum_lead_hours=10,
    ) == datetime(2026, 8, 13, 6, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repositoryHead", "3" * 40),
        ("priorDeadlineUtc", "2026-08-12T22:30:00Z"),
        ("priorBindingId", "e830f957-0b9b-5859-87ec-e0ac8ffc59c3"),
        ("bindingId", "708810d2-d718-55c8-aac6-3baf75f18364"),
        ("schedule", "schedule-mobius77-cleanup"),
        ("replacementPrincipalId", "00000000-0000-0000-0000-000000000000"),
        ("targetResourceGroupId", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("roleDefinitionId", "00000000-0000-0000-0000-000000000000"),
        ("roleScope", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("deadlineUtc", "2026-08-13T06:45:00Z"),
        ("costCeilingUsdCents", 24_999),
    ],
)
def test_cleanup_recovery_v9_rejects_any_predecessor_scope_or_deadline_drift(
    field: str,
    value: object,
) -> None:
    authorization = _resign(replace(_cleanup_recovery_v9_authorization(), **{field: value}))

    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-deadline-recovery-authorization-scope-invalid",
    ):
        validate_cleanup_control_deadline_recovery_authorization(
            authorization,
            expected_repository_head="2" * 40,
            now_utc=CLEANUP_RECOVERY_V9_NOW,
        )


def test_cleanup_recovery_v9_rejects_less_than_thirty_thousand_seconds() -> None:
    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-deadline-recovery-completion-window-insufficient",
    ):
        validate_cleanup_control_deadline_recovery_authorization(
            _cleanup_recovery_v9_authorization(),
            expected_repository_head="2" * 40,
            now_utc=datetime(2026, 8, 12, 22, 10, 1, tzinfo=UTC),
        )


def test_cleanup_recovery_v9_executes_once_with_verified_cost_and_denies_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = _cleanup_recovery_v9_authorization()
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: CLEANUP_RECOVERY_V9_NOW)

    result = adapter.execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="2" * 40,
    )

    assert result["marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["deadline-utc"] == "2026-08-13T06:30:00Z"
    assert result["binding-id"] == "6a1caaa1-3b61-50e2-9ed6-44abb4a3a87a"
    assert result["maximum-plausible-usd-cents"] == 20_607
    assert len(deployments) == 1
    assert deployments[0]["expected_cost"] == 3_110
    assert deployments[0]["maximum_cost"] == 20_607
    assert calls.index("remove-binding") < calls.index("replace-schedule")
    assert calls.index("replace-schedule") < calls.index("deploy-binding")
    receipt = json.loads(
        (tmp_path / adapter_module.DEADLINE_RECOVERY_RECEIPT_FILE).read_text(encoding="utf-8")
    )
    assert receipt["receiptVersion"] == adapter_module.CLEANUP_RECOVERY_V9_RECEIPT_VERSION

    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: _final_inventory(authorization),
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-authorization-already-consumed",
    ):
        adapter.execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="2" * 40,
        )
    assert len(deployments) == 1
    assert calls.count("remove-binding") == 1


def test_cleanup_recovery_v9_rejects_cost_above_ceiling_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = _cleanup_recovery_v9_authorization()
    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "_verify_repository_state", lambda _head: None)
    monkeypatch.setattr(lifecycle, "_account_binding", lambda _now: SUBSCRIPTION_ID)
    monkeypatch.setattr(lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(lifecycle, "_verified_cost", lambda: (3_110, 25_001))
    monkeypatch.setattr(
        adapter_module,
        "_remove_prior_binding",
        lambda _authorization: calls.append("remove-binding") or True,
    )

    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-cost-ceiling-exceeded",
    ):
        ProductionCleanupControlRecoveryAdapter(
            clock=lambda: CLEANUP_RECOVERY_V9_NOW
        ).execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="2" * 40,
        )
    assert calls == []
    assert not (tmp_path / adapter_module.DEADLINE_RECOVERY_RECEIPT_FILE).exists()


def test_cleanup_recovery_unknown_authorization_version_remains_rejected() -> None:
    with pytest.raises(
        CleanupControlRecoveryError,
        match="cleanup-deadline-recovery-authorization-version-invalid",
    ):
        build_cleanup_control_deadline_recovery_authorization(
            repository_head="2" * 40,
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
            prior_runbook_content_sha256=_runbook_sha256(),
            runbook_content_sha256=_runbook_sha256(),
            observed_azure_utc=CLEANUP_RECOVERY_V9_OBSERVED,
            authorization_version=("mobius.milestone-7.7.cleanup-control-deadline-recovery.v10"),
        )


def test_post_fired_authorization_binds_exact_failed_preserved_state_and_round_trips(
    tmp_path: Path,
) -> None:
    authorization = _post_fired_authorization()
    path = tmp_path / "post-fired-authorization.json"
    write_cleanup_control_recovery_authorization(path, authorization)

    loaded = load_cleanup_control_recovery_authorization(path)

    assert loaded == authorization
    assert authorization.postFiredRecoveryPurpose == POST_FIRED_RECOVERY_PURPOSE
    assert authorization.priorCleanupJobId is not None
    assert authorization.priorCleanupJobId.endswith(POST_FIRED_PRIOR_JOB_NAME)
    assert authorization.priorCleanupJobStatus == "Failed"
    assert authorization.priorCleanupJobException == POST_FIRED_PRIOR_JOB_EXCEPTION
    assert authorization.priorScheduleState == "fired-expired"
    assert authorization.priorBindingState == "stale-expired"
    assert authorization.targetPreservationState == "present-no-delete-activity"
    assert authorization.replacementIdentityState == "present"
    assert authorization.replacementAuthorityState == ("exact-direct-contributor-at-target-scope")
    assert authorization.expectedTargetResourceCount == (POST_FIRED_EXPECTED_TARGET_RESOURCE_COUNT)
    assert authorization.expectedDeleteActivityCount == 0
    assert authorization.expectedNonterminalCleanupJobCount == 0
    assert authorization.priorBindingId == "a5429a32-87e3-5963-8c3a-bef85e777ed5"
    assert authorization.bindingId == "f29ca20d-cd14-57d9-b99b-fd6b04406166"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("priorCleanupJobId", f"{AUTOMATION_PREFIX}/other/jobs/{POST_FIRED_PRIOR_JOB_NAME}"),
        ("priorCleanupJobStatus", "Completed"),
        ("priorCleanupJobException", "other-failure"),
        ("priorScheduleState", "future"),
        ("priorBindingState", "active"),
        ("targetPreservationState", "unknown"),
        ("replacementIdentityState", "absent"),
        ("replacementAuthorityState", "subscription-contributor"),
        ("expectedTargetResourceCount", 40),
        ("expectedDeleteActivityCount", 1),
        ("expectedNonterminalCleanupJobCount", 1),
        ("replacementPrincipalId", "00000000-0000-0000-0000-000000000000"),
        ("roleScope", f"{SUBSCRIPTION}/resourceGroups/other"),
    ],
)
def test_post_fired_authorization_rejects_any_failed_state_or_scope_drift(
    field: str, value: object
) -> None:
    authorization = _resign(replace(_post_fired_authorization(), **{field: value}))
    with pytest.raises(CleanupControlRecoveryError):
        validate_cleanup_control_deadline_recovery_authorization(
            authorization,
            expected_repository_head="d" * 40,
            now_utc=POST_FIRED_NOW,
        )


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
    authorization = _post_fired_authorization()
    deployments, calls = _install_execution_fakes(monkeypatch, authorization)

    result = ProductionCleanupControlRecoveryAdapter(
        clock=lambda: POST_FIRED_NOW
    ).execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="d" * 40,
    )

    assert result["marker"] == "CLEANUP_EXECUTABLE_AND_ARMED"
    assert result["deadline-utc"] == "2026-08-08T12:15:00Z"
    assert result["binding-id"] == "f29ca20d-cd14-57d9-b99b-fd6b04406166"
    assert result["post-fired-recovery"] is True
    assert result["post-fired-target-resource-count"] == 41
    assert len(deployments) == 2
    assert deployments[0]["stage"] == "cleanup-job-binding"
    assert deployments[0]["cleanup_at"] == datetime(2026, 8, 8, 12, 15, tzinfo=UTC)
    assert deployments[1]["stage"] == "cleanup-binding"
    assert deployments[0]["maximum_cost"] == 25_000
    assert calls.index("post-fired-state") < calls.index("remove-binding")
    assert calls.index("remove-binding") < calls.index("publish-runbook")
    assert calls.index("remove-binding") < calls.index("replace-schedule")
    assert calls.index("replace-schedule") < calls.index("deploy-binding")
    assert calls.index("deploy-binding") < calls.index("post-fired-tags")
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
    authorization = _post_fired_authorization()
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
        clock=lambda: POST_FIRED_NOW
    ).execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="d" * 40,
    )

    assert result["cleanup-executable"] is True
    annotations = ProductionCleanupControlRecoveryAdapter.execute_deadline_recovery.__annotations__
    assert "image" not in " ".join(annotations).casefold()


def test_ambiguous_binding_delete_reconciles_without_second_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _completion_authorization()
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
    authorization = _completion_authorization()
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


def test_post_fired_state_requires_exact_failed_job_expired_schedule_and_stale_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _post_fired_authorization()
    monkeypatch.setattr(
        adapter_module,
        "_verify_post_fired_target_preservation",
        lambda *_args, **_kwargs: 41,
    )
    list_job: JsonValue = {
        "id": (
            f"{authorization.replacementAutomationAccountId}/jobs/"
            f"SCH_{authorization.priorBindingId}_live-scheduled-name"
        ),
        "jobId": POST_FIRED_PRIOR_JOB_NAME,
        "status": "Failed",
    }
    job: JsonValue = {
        "creationTime": "2026-08-07T06:45:01.0790464-05:00",
        "endTime": "2026-08-07T06:45:58.562934-05:00",
        "exception": POST_FIRED_PRIOR_JOB_EXCEPTION,
        "id": authorization.priorCleanupJobId,
        "jobId": POST_FIRED_PRIOR_JOB_NAME,
        "provisioningState": "Failed",
        "runbook": authorization.runbook,
        "startTime": "2026-08-07T06:45:58.5629339-05:00",
        "status": "Failed",
    }
    schedule: JsonValue = {
        "expiryTime": "2026-08-07T06:45:00-05:00",
        "frequency": "OneTime",
        "id": (
            f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
        ),
        "isEnabled": True,
        "name": authorization.schedule,
        "nextRun": None,
        "startTime": "2026-08-07T06:45:00-05:00",
        "timeZone": "Etc/UTC",
    }

    def collection(
        _authorization: CleanupControlDeadlineRecoveryAuthorization,
        *,
        collection: str,
        query: str,
    ) -> list[JsonValue]:
        del query
        if collection == "jobs":
            return [list_job]
        if collection == "schedules":
            return [schedule]
        raise AssertionError(collection)

    monkeypatch.setattr(adapter_module, "_replacement_collection", collection)
    direct_get_calls: list[tuple[str, ...]] = []

    def direct_get(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        direct_get_calls.append(argv)
        return job

    monkeypatch.setattr(lifecycle, "_run", direct_get)
    monkeypatch.setattr(
        adapter_module,
        "_job_schedule_rows",
        lambda _authorization: [
            {
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
        ],
    )

    assert (
        adapter_module._verify_post_fired_cleanup_state(
            authorization,
            SUBSCRIPTION_ID,
            now_utc=POST_FIRED_NOW,
        )
        == 41
    )
    assert direct_get_calls[0][direct_get_calls[0].index("--url") + 1] == (
        f"https://management.azure.com{authorization.priorCleanupJobId}"
        f"?api-version={lifecycle.AUTOMATION_API_VERSION}"
    )

    assert isinstance(list_job, dict)
    list_job["status"] = "Running"
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-post-fired-job-not-terminal",
    ):
        adapter_module._verify_post_fired_cleanup_state(
            authorization,
            SUBSCRIPTION_ID,
            now_utc=POST_FIRED_NOW,
        )

    list_job["status"] = "Failed"
    assert isinstance(job, dict)
    job["exception"] = "different-live-failure"
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-post-fired-failed-job-drift",
    ):
        adapter_module._verify_post_fired_cleanup_state(
            authorization,
            SUBSCRIPTION_ID,
            now_utc=POST_FIRED_NOW,
        )


def test_post_fired_target_preservation_rejects_resource_loss_or_delete_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _post_fired_authorization()
    resources: list[JsonValue] = [
        {"id": f"{TARGET_GROUP}/providers/Example.Type/items/{index}"} for index in range(41)
    ]
    delete_activity: list[JsonValue] = [
        {
            "operationName": "Microsoft.Example/items/delete",
            "resourceId": f"{TARGET_GROUP}/providers/Example.Type/items/0",
            "status": "Succeeded",
        }
    ]
    responses = iter((resources, delete_activity))
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-post-fired-delete-activity-present",
    ):
        adapter_module._verify_post_fired_target_preservation(
            authorization,
            SUBSCRIPTION_ID,
            now_utc=POST_FIRED_NOW,
        )

    responses = iter((resources[:-1], []))
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-post-fired-target-preservation-unproved",
    ):
        adapter_module._verify_post_fired_target_preservation(
            authorization,
            SUBSCRIPTION_ID,
            now_utc=POST_FIRED_NOW,
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


@pytest.mark.parametrize("drift", ["duplicate", "scope"])
def test_replacement_graph_rejects_duplicate_or_non_target_contributor_assignment(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    authorization = _post_fired_authorization()
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda *_args, **_kwargs: {
            "id": authorization.replacementAutomationAccountId,
            "identityType": "SystemAssigned",
            "localAuthDisabled": True,
            "location": "northeurope",
            "principalId": authorization.replacementPrincipalId,
            "publicNetworkAccess": False,
            "state": "Ok",
        },
    )

    def collection(
        _authorization: CleanupControlDeadlineRecoveryAuthorization,
        *,
        collection: str,
        query: str,
    ) -> list[JsonValue]:
        del query
        if collection == "runbooks":
            return [
                {
                    "id": (
                        f"{authorization.replacementAutomationAccountId}/runbooks/"
                        f"{authorization.runbook}"
                    ),
                    "location": "northeurope",
                    "name": authorization.runbook,
                    "runbookType": "PowerShell72",
                    "state": "Published",
                }
            ]
        if collection == "jobs":
            return []
        return []

    monkeypatch.setattr(adapter_module, "_replacement_collection", collection)
    monkeypatch.setattr(
        adapter_module,
        "_published_runbook_hash",
        lambda _authorization: authorization.runbookContentSha256,
    )
    monkeypatch.setattr(
        adapter_module,
        "_schedule_rows",
        lambda _authorization: [
            {
                "frequency": "OneTime",
                "id": (
                    f"{authorization.replacementAutomationAccountId}/schedules/"
                    f"{authorization.schedule}"
                ),
                "isEnabled": True,
                "name": authorization.schedule,
                "startTime": authorization.deadlineUtc,
                "timeZone": "Etc/UTC",
            }
        ],
    )
    monkeypatch.setattr(
        adapter_module,
        "_job_schedule_rows",
        lambda _authorization: [
            {
                "id": (
                    f"{authorization.replacementAutomationAccountId}/jobSchedules/"
                    f"{authorization.bindingId}"
                ),
                "jobScheduleId": authorization.bindingId,
                "parameters": {
                    "CleanupAuthorized": "true",
                    "TargetResourceGroupName": "rg-solarplexus-mobius-77-staging",
                },
                "runbook": authorization.runbook,
                "schedule": authorization.schedule,
            }
        ],
    )
    expected = adapter_module._expected_replacement_role_row(authorization)
    observed_roles = (
        [expected, expected]
        if drift == "duplicate"
        else [{**expected, "scope": SUBSCRIPTION.casefold()}]
    )
    monkeypatch.setattr(
        adapter_module,
        "_replacement_role_rows",
        lambda *_args: observed_roles,
    )

    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-role-drift",
    ):
        adapter_module._verify_replacement_cleanup_graph(
            authorization,
            SUBSCRIPTION_ID,
            allowed_deadlines=frozenset({authorization.deadlineUtc}),
            allowed_runbook_hashes=frozenset({authorization.runbookContentSha256}),
            binding_required=True,
        )


def test_deadline_authorization_replay_is_denied_before_second_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _post_fired_authorization()
    deployments, calls = _install_execution_fakes(
        monkeypatch, authorization, inventory=_final_inventory(authorization)
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_resource_group_inventory",
        lambda _subscription: _final_inventory(authorization),
    )
    adapter = ProductionCleanupControlRecoveryAdapter(clock=lambda: POST_FIRED_NOW)
    adapter.execute_deadline_recovery(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head="d" * 40,
    )
    with pytest.raises(
        CleanupControlRecoveryExecutionError,
        match="cleanup-deadline-recovery-authorization-already-consumed",
    ):
        adapter.execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head="d" * 40,
        )
    assert len(deployments) == 2
    assert calls.count("remove-binding") == 1
    assert calls.count("replace-schedule") == 1


def test_existing_cleanup_recovery_entry_point_dispatches_deadline_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _post_fired_authorization()
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
        expected_repository_head="d" * 40,
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
