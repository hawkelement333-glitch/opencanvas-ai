"""Narrow, image-independent authority for cleanup-control recovery only."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    ACTIVE_CLEANUP_BINDING_ID,
    CLEANUP_AUTOMATION_ACCOUNT,
    CLEANUP_BINDING_CONTRACT_VERSION,
    CLEANUP_RUNBOOK_PATH,
    REPOSITORY_ROOT,
    cleanup_runbook_sha256,
)

AUTHORIZATION_VERSION: Final = "mobius.milestone-7.7.cleanup-control-recovery.v1"
AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-recovery/v1\0"
)
TARGET_GROUP: Final = "rg-solarplexus-mobius-77-staging"
CLEANUP_GROUP: Final = "rg-solarplexus-mobius-77-cleanup-control"
RUNBOOK: Final = "Remove-Mobius77Staging"
SCHEDULE: Final = "schedule-mobius77-cleanup"
ROLE_DEFINITION_ID: Final = "b24988ac-6180-42a0-ab88-20f7382dd24c"
DEADLINE_UTC: Final = "2026-08-06T12:00:00Z"
COST_CEILING_CENTS: Final = 25_000
CORRUPTED_AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup"
CORRUPTED_PRINCIPAL_ID: Final = "be0e6b8d-f742-4c8f-8df1-9f302559a6c8"
CORRUPTED_ROLE_ASSIGNMENT_NAME: Final = "5c1b559b-638a-5d58-b77b-b6291747f9d4"
CORRUPTED_ROLE_ASSIGNMENT_ACTION: Final = "delete-exact-role-assignment"
TARGET_PARAMETER: Final = "TargetResourceGroupName"
AUTHORIZATION_PARAMETER: Final = "CleanupAuthorized"
ALLOWED_OPERATIONS: Final = (
    "revoke-exact-corrupted-cleanup-role-assignment",
    "create-replacement-automation-account",
    "assign-exact-cleanup-role",
    "publish-guarded-runbook",
    "create-one-time-schedule",
    "create-exact-job-schedule-binding",
    "verify-cleanup-executable",
)


class CleanupControlRecoveryError(ValueError):
    """Raised when a recovery authorization would expand its exact scope."""


@dataclass(frozen=True)
class CleanupControlRecoveryAuthorization:
    authorizationVersion: str
    repositoryHead: str
    subscriptionId: str
    cleanupResourceGroupId: str
    corruptedAutomationAccountId: str
    corruptedPrincipalId: str
    corruptedRoleAssignmentId: str
    corruptedRoleAssignmentAction: str
    replacementAutomationAccount: str
    replacementAutomationAccountId: str
    targetResourceGroupId: str
    roleDefinitionId: str
    roleScope: str
    runbook: str
    schedule: str
    targetParameter: str
    targetParameterValue: str
    authorizationParameter: str
    authorizationParameterValue: bool
    authorizedAtUtc: str
    deadlineUtc: str
    bindingId: str
    bindingContractVersion: str
    runbookContentSha256: str
    costCeilingUsdCents: int
    allowedOperations: tuple[str, ...]
    authorizationIntegritySha256: str


def _utc(value: datetime) -> str:
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _parse_utc(value: str, error_code: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise CleanupControlRecoveryError(error_code) from None
    return parsed


def _expected_resource_ids(subscription_id: str) -> tuple[str, str, str, str, str]:
    if (
        not isinstance(subscription_id, str)
        or not subscription_id
        or subscription_id.strip() != subscription_id
        or "/" in subscription_id
        or "\\" in subscription_id
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-subscription-invalid")
    root = f"/subscriptions/{subscription_id}/resourceGroups"
    cleanup_group = f"{root}/{CLEANUP_GROUP}"
    account_prefix = (
        f"{cleanup_group}/providers/Microsoft.Automation/automationAccounts"
    )
    target_group = f"{root}/{TARGET_GROUP}"
    return (
        cleanup_group,
        f"{account_prefix}/{CORRUPTED_AUTOMATION_ACCOUNT}",
        f"{account_prefix}/{CLEANUP_AUTOMATION_ACCOUNT}",
        target_group,
        (
            f"{target_group}/providers/Microsoft.Authorization/roleAssignments/"
            f"{CORRUPTED_ROLE_ASSIGNMENT_NAME}"
        ),
    )


def cleanup_control_recovery_authorization_integrity(
    authorization: CleanupControlRecoveryAuthorization,
) -> str:
    return integrity_sha256(_authorization_body(authorization), AUTHORIZATION_DOMAIN)


def _authorization_body(
    authorization: CleanupControlRecoveryAuthorization,
) -> dict[str, JsonValue]:
    return {
        "authorizationVersion": authorization.authorizationVersion,
        "repositoryHead": authorization.repositoryHead,
        "subscriptionId": authorization.subscriptionId,
        "cleanupResourceGroupId": authorization.cleanupResourceGroupId,
        "corruptedAutomationAccountId": authorization.corruptedAutomationAccountId,
        "corruptedPrincipalId": authorization.corruptedPrincipalId,
        "corruptedRoleAssignmentId": authorization.corruptedRoleAssignmentId,
        "corruptedRoleAssignmentAction": authorization.corruptedRoleAssignmentAction,
        "replacementAutomationAccount": authorization.replacementAutomationAccount,
        "replacementAutomationAccountId": authorization.replacementAutomationAccountId,
        "targetResourceGroupId": authorization.targetResourceGroupId,
        "roleDefinitionId": authorization.roleDefinitionId,
        "roleScope": authorization.roleScope,
        "runbook": authorization.runbook,
        "schedule": authorization.schedule,
        "targetParameter": authorization.targetParameter,
        "targetParameterValue": authorization.targetParameterValue,
        "authorizationParameter": authorization.authorizationParameter,
        "authorizationParameterValue": authorization.authorizationParameterValue,
        "authorizedAtUtc": authorization.authorizedAtUtc,
        "deadlineUtc": authorization.deadlineUtc,
        "bindingId": authorization.bindingId,
        "bindingContractVersion": authorization.bindingContractVersion,
        "runbookContentSha256": authorization.runbookContentSha256,
        "costCeilingUsdCents": authorization.costCeilingUsdCents,
        "allowedOperations": list(authorization.allowedOperations),
    }


def build_cleanup_control_recovery_authorization(
    *,
    repository_head: str,
    subscription_id: str,
    cleanup_resource_group_id: str,
    corrupted_automation_account_id: str,
    corrupted_principal_id: str,
    corrupted_role_assignment_id: str,
    replacement_automation_account_id: str,
    target_resource_group_id: str,
    runbook_content_sha256: str,
    now_utc: datetime,
) -> CleanupControlRecoveryAuthorization:
    if len(repository_head) != 40 or any(
        c not in "0123456789abcdef" for c in repository_head
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-repository-head-invalid")
    (
        expected_cleanup,
        expected_corrupted,
        expected_replacement,
        expected_target,
        expected_corrupted_assignment,
    ) = _expected_resource_ids(subscription_id)
    if cleanup_resource_group_id != expected_cleanup:
        raise CleanupControlRecoveryError("cleanup-recovery-cleanup-scope-invalid")
    if corrupted_automation_account_id != expected_corrupted:
        raise CleanupControlRecoveryError("cleanup-recovery-corrupted-account-invalid")
    if corrupted_principal_id != CORRUPTED_PRINCIPAL_ID:
        raise CleanupControlRecoveryError(
            "cleanup-recovery-corrupted-principal-invalid"
        )
    if (
        corrupted_role_assignment_id.casefold()
        != expected_corrupted_assignment.casefold()
    ):
        raise CleanupControlRecoveryError(
            "cleanup-recovery-corrupted-assignment-invalid"
        )
    if replacement_automation_account_id != expected_replacement:
        raise CleanupControlRecoveryError(
            "cleanup-recovery-replacement-account-scope-invalid"
        )
    if target_resource_group_id != expected_target:
        raise CleanupControlRecoveryError("cleanup-recovery-target-scope-invalid")
    if not isinstance(
        runbook_content_sha256, str
    ) or runbook_content_sha256 != cleanup_runbook_sha256(
        CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-runbook-content-invalid")
    authorized_at = now_utc.astimezone(UTC).replace(microsecond=0)
    if authorized_at > _parse_utc(DEADLINE_UTC, "cleanup-recovery-deadline-invalid"):
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-expired")
    role_scope = target_resource_group_id
    unsigned = CleanupControlRecoveryAuthorization(
        authorizationVersion=AUTHORIZATION_VERSION,
        repositoryHead=repository_head,
        subscriptionId=subscription_id,
        cleanupResourceGroupId=cleanup_resource_group_id,
        corruptedAutomationAccountId=corrupted_automation_account_id,
        corruptedPrincipalId=corrupted_principal_id,
        corruptedRoleAssignmentId=expected_corrupted_assignment,
        corruptedRoleAssignmentAction=CORRUPTED_ROLE_ASSIGNMENT_ACTION,
        replacementAutomationAccount=CLEANUP_AUTOMATION_ACCOUNT,
        replacementAutomationAccountId=replacement_automation_account_id,
        targetResourceGroupId=target_resource_group_id,
        roleDefinitionId=ROLE_DEFINITION_ID,
        roleScope=role_scope,
        runbook=RUNBOOK,
        schedule=SCHEDULE,
        targetParameter=TARGET_PARAMETER,
        targetParameterValue=TARGET_GROUP,
        authorizationParameter=AUTHORIZATION_PARAMETER,
        authorizationParameterValue=True,
        authorizedAtUtc=_utc(authorized_at),
        deadlineUtc=DEADLINE_UTC,
        bindingId=ACTIVE_CLEANUP_BINDING_ID,
        bindingContractVersion=CLEANUP_BINDING_CONTRACT_VERSION,
        runbookContentSha256=runbook_content_sha256,
        costCeilingUsdCents=COST_CEILING_CENTS,
        allowedOperations=ALLOWED_OPERATIONS,
        authorizationIntegritySha256="",
    )
    return CleanupControlRecoveryAuthorization(
        authorizationVersion=unsigned.authorizationVersion,
        repositoryHead=unsigned.repositoryHead,
        subscriptionId=unsigned.subscriptionId,
        cleanupResourceGroupId=unsigned.cleanupResourceGroupId,
        corruptedAutomationAccountId=unsigned.corruptedAutomationAccountId,
        corruptedPrincipalId=unsigned.corruptedPrincipalId,
        corruptedRoleAssignmentId=unsigned.corruptedRoleAssignmentId,
        corruptedRoleAssignmentAction=unsigned.corruptedRoleAssignmentAction,
        replacementAutomationAccount=unsigned.replacementAutomationAccount,
        replacementAutomationAccountId=unsigned.replacementAutomationAccountId,
        targetResourceGroupId=unsigned.targetResourceGroupId,
        roleDefinitionId=unsigned.roleDefinitionId,
        roleScope=unsigned.roleScope,
        runbook=unsigned.runbook,
        schedule=unsigned.schedule,
        targetParameter=unsigned.targetParameter,
        targetParameterValue=unsigned.targetParameterValue,
        authorizationParameter=unsigned.authorizationParameter,
        authorizationParameterValue=unsigned.authorizationParameterValue,
        authorizedAtUtc=unsigned.authorizedAtUtc,
        deadlineUtc=unsigned.deadlineUtc,
        bindingId=unsigned.bindingId,
        bindingContractVersion=unsigned.bindingContractVersion,
        runbookContentSha256=unsigned.runbookContentSha256,
        costCeilingUsdCents=unsigned.costCeilingUsdCents,
        allowedOperations=unsigned.allowedOperations,
        authorizationIntegritySha256=(
            cleanup_control_recovery_authorization_integrity(unsigned)
        ),
    )


def validate_cleanup_control_recovery_authorization(
    authorization: CleanupControlRecoveryAuthorization,
    *,
    expected_repository_head: str,
    now_utc: datetime,
) -> CleanupControlRecoveryAuthorization:
    (
        expected_cleanup,
        expected_corrupted,
        expected_replacement,
        expected_target,
        expected_corrupted_assignment,
    ) = _expected_resource_ids(authorization.subscriptionId)
    exact_values = {
        "authorizationVersion": AUTHORIZATION_VERSION,
        "repositoryHead": expected_repository_head,
        "cleanupResourceGroupId": expected_cleanup,
        "corruptedAutomationAccountId": expected_corrupted,
        "corruptedPrincipalId": CORRUPTED_PRINCIPAL_ID,
        "corruptedRoleAssignmentId": expected_corrupted_assignment,
        "corruptedRoleAssignmentAction": CORRUPTED_ROLE_ASSIGNMENT_ACTION,
        "replacementAutomationAccount": CLEANUP_AUTOMATION_ACCOUNT,
        "replacementAutomationAccountId": expected_replacement,
        "targetResourceGroupId": expected_target,
        "roleDefinitionId": ROLE_DEFINITION_ID,
        "roleScope": expected_target,
        "runbook": RUNBOOK,
        "schedule": SCHEDULE,
        "targetParameter": TARGET_PARAMETER,
        "targetParameterValue": TARGET_GROUP,
        "authorizationParameter": AUTHORIZATION_PARAMETER,
        "authorizationParameterValue": True,
        "deadlineUtc": DEADLINE_UTC,
        "bindingId": ACTIVE_CLEANUP_BINDING_ID,
        "bindingContractVersion": CLEANUP_BINDING_CONTRACT_VERSION,
        "costCeilingUsdCents": COST_CEILING_CENTS,
        "allowedOperations": ALLOWED_OPERATIONS,
    }
    observed = asdict(authorization)
    if any(observed.get(key) != value for key, value in exact_values.items()):
        raise CleanupControlRecoveryError(
            "cleanup-recovery-authorization-scope-invalid"
        )
    if len(authorization.repositoryHead) != 40 or any(
        c not in "0123456789abcdef" for c in authorization.repositoryHead
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-repository-head-invalid")
    if authorization.runbookContentSha256 != cleanup_runbook_sha256(
        CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-runbook-content-invalid")
    authorized_at = _parse_utc(
        authorization.authorizedAtUtc, "cleanup-recovery-authorized-at-invalid"
    )
    deadline = _parse_utc(
        authorization.deadlineUtc, "cleanup-recovery-deadline-invalid"
    )
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    if authorized_at > current or current > deadline or authorized_at > deadline:
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-expired")
    if authorization.authorizationIntegritySha256 != (
        cleanup_control_recovery_authorization_integrity(authorization)
    ):
        raise CleanupControlRecoveryError(
            "cleanup-recovery-authorization-integrity-invalid"
        )
    return authorization


def cleanup_control_recovery_authorization_from_mapping(
    value: JsonValue,
) -> CleanupControlRecoveryAuthorization:
    if not isinstance(value, dict):
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-malformed")
    fields = set(CleanupControlRecoveryAuthorization.__dataclass_fields__)
    if set(value) != fields:
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-malformed")
    operations = value.get("allowedOperations")
    if not isinstance(operations, list) or any(
        not isinstance(item, str) for item in operations
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-malformed")
    string_fields = fields - {
        "allowedOperations",
        "authorizationParameterValue",
        "costCeilingUsdCents",
    }
    if any(not isinstance(value.get(field), str) for field in string_fields):
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-malformed")
    authorization_value = value.get("authorizationParameterValue")
    cost_ceiling = value.get("costCeilingUsdCents")
    if not isinstance(authorization_value, bool) or (
        not isinstance(cost_ceiling, int) or isinstance(cost_ceiling, bool)
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-authorization-malformed")
    return CleanupControlRecoveryAuthorization(
        authorizationVersion=cast(str, value["authorizationVersion"]),
        repositoryHead=cast(str, value["repositoryHead"]),
        subscriptionId=cast(str, value["subscriptionId"]),
        cleanupResourceGroupId=cast(str, value["cleanupResourceGroupId"]),
        corruptedAutomationAccountId=cast(str, value["corruptedAutomationAccountId"]),
        corruptedPrincipalId=cast(str, value["corruptedPrincipalId"]),
        corruptedRoleAssignmentId=cast(str, value["corruptedRoleAssignmentId"]),
        corruptedRoleAssignmentAction=cast(str, value["corruptedRoleAssignmentAction"]),
        replacementAutomationAccount=cast(str, value["replacementAutomationAccount"]),
        replacementAutomationAccountId=cast(
            str, value["replacementAutomationAccountId"]
        ),
        targetResourceGroupId=cast(str, value["targetResourceGroupId"]),
        roleDefinitionId=cast(str, value["roleDefinitionId"]),
        roleScope=cast(str, value["roleScope"]),
        runbook=cast(str, value["runbook"]),
        schedule=cast(str, value["schedule"]),
        targetParameter=cast(str, value["targetParameter"]),
        targetParameterValue=cast(str, value["targetParameterValue"]),
        authorizationParameter=cast(str, value["authorizationParameter"]),
        authorizationParameterValue=authorization_value,
        authorizedAtUtc=cast(str, value["authorizedAtUtc"]),
        deadlineUtc=cast(str, value["deadlineUtc"]),
        bindingId=cast(str, value["bindingId"]),
        bindingContractVersion=cast(str, value["bindingContractVersion"]),
        runbookContentSha256=cast(str, value["runbookContentSha256"]),
        costCeilingUsdCents=cost_ceiling,
        allowedOperations=tuple(cast(list[str], operations)),
        authorizationIntegritySha256=cast(str, value["authorizationIntegritySha256"]),
    )


def load_cleanup_control_recovery_authorization(
    path: Path,
) -> CleanupControlRecoveryAuthorization:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise CleanupControlRecoveryError(
            "cleanup-recovery-authorization-inside-repository"
        )
    return cleanup_control_recovery_authorization_from_mapping(load_json(resolved))


def write_cleanup_control_recovery_authorization(
    path: Path, authorization: CleanupControlRecoveryAuthorization
) -> None:
    repository = REPOSITORY_ROOT.resolve()
    if path.resolve() == repository or repository in path.resolve().parents:
        raise CleanupControlRecoveryError(
            "cleanup-recovery-authorization-inside-repository"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        **_authorization_body(authorization),
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
    }
    path.write_bytes(canonical_bytes(body))


def execute_cleanup_control_recovery(
    *,
    authorization: CleanupControlRecoveryAuthorization,
    receipt_directory: Path,
    expected_repository_head: str,
) -> dict[str, JsonValue]:
    """Use the production adapter without importing the complete lifecycle entry point."""

    from infra.milestone_7_7.cleanup_control_recovery_adapter import (
        ProductionCleanupControlRecoveryAdapter,
    )

    return ProductionCleanupControlRecoveryAdapter().execute(
        authorization=authorization,
        receipt_directory=receipt_directory,
        expected_repository_head=expected_repository_head,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute only the authorized Milestone 7.7 cleanup-control recovery."
    )
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--receipt-directory", required=True, type=Path)
    parser.add_argument("--repository-head", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        authorization = load_cleanup_control_recovery_authorization(args.authorization)
        result = execute_cleanup_control_recovery(
            authorization=authorization,
            receipt_directory=args.receipt_directory,
            expected_repository_head=args.repository_head,
        )
    except (CleanupControlRecoveryError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "blocked"},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
