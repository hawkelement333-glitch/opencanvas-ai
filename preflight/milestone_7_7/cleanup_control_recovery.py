"""Narrow, image-independent authority for cleanup-control recovery only."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
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
    TOMBSTONED_DEADLINE_RECOVERY_BINDING_ID,
    TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
    TOMBSTONED_THIRD_DEADLINE_RECOVERY_BINDING_ID,
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
DEADLINE_RECOVERY_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v1"
)
DEADLINE_RECOVERY_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v1\0"
)
DEADLINE_EXTENSION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v2"
)
DEADLINE_EXTENSION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v2\0"
)
DEADLINE_CONTINUATION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v3"
)
DEADLINE_CONTINUATION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v3\0"
)
DEADLINE_RECOVERY_OBSERVED_AZURE_UTC: Final = "2026-08-06T12:23:26Z"
DEADLINE_RECOVERY_DEADLINE_UTC: Final = "2026-08-06T18:30:00Z"
DEADLINE_RECOVERY_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-6-hours-after-observed"
)
DEADLINE_RECOVERY_ACTION: Final = "recover-expired-cleanup-deadline"
DEADLINE_EXTENSION_OBSERVED_AZURE_UTC: Final = "2026-08-06T14:06:02Z"
DEADLINE_EXTENSION_DEADLINE_UTC: Final = "2026-08-07T00:15:00Z"
DEADLINE_EXTENSION_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-10-hours-after-observed"
)
DEADLINE_EXTENSION_ACTION: Final = (
    "extend-cleanup-deadline-for-private-scanner-bridge-proof"
)
DEADLINE_CONTINUATION_OBSERVED_AZURE_UTC: Final = "2026-08-06T17:23:44Z"
DEADLINE_CONTINUATION_DEADLINE_UTC: Final = "2026-08-07T05:30:00Z"
DEADLINE_CONTINUATION_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-12-hours-after-observed"
)
DEADLINE_CONTINUATION_ACTION: Final = (
    "extend-cleanup-deadline-for-private-scanner-bridge-execution"
)
DEADLINE_RECOVERY_CORRUPTED_ROLE_ACTION: Final = "verify-exact-assignment-absent"
DEADLINE_RECOVERY_SCHEDULE_ACTION: Final = "replace-same-name-one-time-schedule"
DEADLINE_RECOVERY_BINDING_ACTION: Final = "reconcile-remove-and-recreate-exact-binding"
DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID: Final = (
    "a47789c6-b8eb-40a1-898a-517a52d60a86"
)
DEADLINE_RECOVERY_REPLACEMENT_ROLE_ASSIGNMENT_NAME: Final = (
    "b4acad78-f3f0-59d4-8e36-901644af1ff6"
)
DEADLINE_RECOVERY_REPLACEMENT_LOCATION: Final = "northeurope"
DEADLINE_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "23d074e8508ca0cbc7b56634f70c5b3cd9d59bfe0d274d47d9aaa340941b9fd9"
)
CORRUPTED_RUNBOOK_CONTENT_SHA256: Final = DEADLINE_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256
DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "5283fef0c32b1fdc63e0aef00e9d488b8113848cd0ea7edb18bd4231c83b2a7d"
)
DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "36da98c94fb213bd279792ef828da50522d081365b6c30190058c250688a81fd"
)
DEADLINE_RECOVERY_ALLOWED_OPERATIONS: Final = (
    "verify-preserved-cleanup-control",
    "remove-exact-prior-job-schedule-binding",
    "publish-deadline-adjusted-guarded-runbook",
    "replace-same-name-one-time-schedule",
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


@dataclass(frozen=True)
class CleanupControlDeadlineRecoveryAuthorization(CleanupControlRecoveryAuthorization):
    """One replay-denying grant to replace only the expired cleanup deadline."""

    recoveryAction: str
    deadlineObservedAtUtc: str
    deadlineDerivationRule: str
    priorDeadlineUtc: str
    priorBindingId: str
    priorRunbookContentSha256: str
    replacementPrincipalId: str
    replacementRoleAssignmentId: str
    replacementLocation: str
    scheduleAction: str
    bindingAction: str


@dataclass(frozen=True)
class _DeadlineRecoveryProfile:
    authorization_version: str
    authorization_domain: bytes
    observed_azure_utc: str
    deadline_utc: str
    derivation_rule: str
    minimum_lead_hours: int
    recovery_action: str
    prior_deadline_utc: str
    prior_binding_id: str
    binding_id: str
    prior_runbook_content_sha256: str


def _deadline_recovery_profile(authorization_version: str) -> _DeadlineRecoveryProfile:
    if authorization_version == DEADLINE_RECOVERY_AUTHORIZATION_VERSION:
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=DEADLINE_RECOVERY_AUTHORIZATION_DOMAIN,
            observed_azure_utc=DEADLINE_RECOVERY_OBSERVED_AZURE_UTC,
            deadline_utc=DEADLINE_RECOVERY_DEADLINE_UTC,
            derivation_rule=DEADLINE_RECOVERY_DERIVATION_RULE,
            minimum_lead_hours=6,
            recovery_action=DEADLINE_RECOVERY_ACTION,
            prior_deadline_utc=DEADLINE_UTC,
            prior_binding_id=TOMBSTONED_DEADLINE_RECOVERY_BINDING_ID,
            binding_id=TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
            prior_runbook_content_sha256=DEADLINE_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256,
        )
    if authorization_version == DEADLINE_EXTENSION_AUTHORIZATION_VERSION:
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=DEADLINE_EXTENSION_AUTHORIZATION_DOMAIN,
            observed_azure_utc=DEADLINE_EXTENSION_OBSERVED_AZURE_UTC,
            deadline_utc=DEADLINE_EXTENSION_DEADLINE_UTC,
            derivation_rule=DEADLINE_EXTENSION_DERIVATION_RULE,
            minimum_lead_hours=10,
            recovery_action=DEADLINE_EXTENSION_ACTION,
            prior_deadline_utc=DEADLINE_RECOVERY_DEADLINE_UTC,
            prior_binding_id=TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
            binding_id=TOMBSTONED_THIRD_DEADLINE_RECOVERY_BINDING_ID,
            prior_runbook_content_sha256=(
                DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
        )
    if authorization_version == DEADLINE_CONTINUATION_AUTHORIZATION_VERSION:
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=DEADLINE_CONTINUATION_AUTHORIZATION_DOMAIN,
            observed_azure_utc=DEADLINE_CONTINUATION_OBSERVED_AZURE_UTC,
            deadline_utc=DEADLINE_CONTINUATION_DEADLINE_UTC,
            derivation_rule=DEADLINE_CONTINUATION_DERIVATION_RULE,
            minimum_lead_hours=12,
            recovery_action=DEADLINE_CONTINUATION_ACTION,
            prior_deadline_utc=DEADLINE_EXTENSION_DEADLINE_UTC,
            prior_binding_id=TOMBSTONED_THIRD_DEADLINE_RECOVERY_BINDING_ID,
            binding_id=ACTIVE_CLEANUP_BINDING_ID,
            prior_runbook_content_sha256=(
                DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
        )
    raise CleanupControlRecoveryError(
        "cleanup-deadline-recovery-authorization-version-invalid"
    )


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


def derive_cleanup_control_recovery_deadline(
    observed_azure_utc: datetime, *, minimum_lead_hours: int = 6
) -> datetime:
    """Return the first quarter-hour boundary after the authorized lead time."""

    if observed_azure_utc.tzinfo is None or observed_azure_utc.utcoffset() is None:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-observed-at-invalid"
        )
    if minimum_lead_hours not in {6, 10, 12}:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-minimum-lead-invalid"
        )
    threshold = observed_azure_utc.astimezone(UTC) + timedelta(hours=minimum_lead_hours)
    candidate = threshold.replace(second=0, microsecond=0)
    remainder = candidate.minute % 15
    if remainder:
        candidate += timedelta(minutes=15 - remainder)
    if candidate < threshold:
        candidate += timedelta(minutes=15)
    return candidate


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
    digest = integrity_sha256(_authorization_body(authorization), AUTHORIZATION_DOMAIN)
    if not isinstance(digest, str):
        raise CleanupControlRecoveryError(
            "cleanup-recovery-authorization-integrity-malformed"
        )
    return digest


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


def _expected_replacement_role_assignment_id(subscription_id: str) -> str:
    _, _, _, target_group, _ = _expected_resource_ids(subscription_id)
    return (
        f"{target_group}/providers/Microsoft.Authorization/roleAssignments/"
        f"{DEADLINE_RECOVERY_REPLACEMENT_ROLE_ASSIGNMENT_NAME}"
    )


def _deadline_recovery_authorization_body(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> dict[str, JsonValue]:
    return {
        **_authorization_body(authorization),
        "recoveryAction": authorization.recoveryAction,
        "deadlineObservedAtUtc": authorization.deadlineObservedAtUtc,
        "deadlineDerivationRule": authorization.deadlineDerivationRule,
        "priorDeadlineUtc": authorization.priorDeadlineUtc,
        "priorBindingId": authorization.priorBindingId,
        "priorRunbookContentSha256": authorization.priorRunbookContentSha256,
        "replacementPrincipalId": authorization.replacementPrincipalId,
        "replacementRoleAssignmentId": authorization.replacementRoleAssignmentId,
        "replacementLocation": authorization.replacementLocation,
        "scheduleAction": authorization.scheduleAction,
        "bindingAction": authorization.bindingAction,
    }


def cleanup_control_deadline_recovery_authorization_integrity(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> str:
    profile = _deadline_recovery_profile(authorization.authorizationVersion)
    digest = integrity_sha256(
        _deadline_recovery_authorization_body(authorization),
        profile.authorization_domain,
    )
    if not isinstance(digest, str):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-integrity-malformed"
        )
    return digest


def build_cleanup_control_deadline_recovery_authorization(
    *,
    repository_head: str,
    subscription_id: str,
    cleanup_resource_group_id: str,
    corrupted_automation_account_id: str,
    corrupted_principal_id: str,
    corrupted_role_assignment_id: str,
    replacement_automation_account_id: str,
    replacement_principal_id: str,
    replacement_role_assignment_id: str,
    replacement_location: str,
    target_resource_group_id: str,
    prior_runbook_content_sha256: str,
    runbook_content_sha256: str,
    observed_azure_utc: datetime,
    authorization_version: str = DEADLINE_RECOVERY_AUTHORIZATION_VERSION,
) -> CleanupControlDeadlineRecoveryAuthorization:
    profile = _deadline_recovery_profile(authorization_version)
    if len(repository_head) != 40 or any(
        character not in "0123456789abcdef" for character in repository_head
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-repository-head-invalid")
    (
        expected_cleanup,
        expected_corrupted,
        expected_replacement,
        expected_target,
        expected_corrupted_assignment,
    ) = _expected_resource_ids(subscription_id)
    expected_replacement_assignment = _expected_replacement_role_assignment_id(
        subscription_id
    )
    exact_resource_values = (
        (cleanup_resource_group_id, expected_cleanup),
        (corrupted_automation_account_id, expected_corrupted),
        (replacement_automation_account_id, expected_replacement),
        (target_resource_group_id, expected_target),
    )
    if any(observed != expected for observed, expected in exact_resource_values):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-resource-scope-invalid"
        )
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
    if replacement_principal_id != DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-replacement-principal-invalid"
        )
    if (
        replacement_role_assignment_id.casefold()
        != expected_replacement_assignment.casefold()
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-replacement-assignment-invalid"
        )
    if replacement_location != DEADLINE_RECOVERY_REPLACEMENT_LOCATION:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-replacement-location-invalid"
        )
    if prior_runbook_content_sha256 != profile.prior_runbook_content_sha256:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-prior-runbook-content-invalid"
        )
    expected_runbook_hash = cleanup_runbook_sha256(
        CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
    )
    if runbook_content_sha256 != expected_runbook_hash:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-runbook-content-invalid"
        )
    if observed_azure_utc.tzinfo is None or observed_azure_utc.utcoffset() is None:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-observed-at-invalid"
        )
    observed = observed_azure_utc.astimezone(UTC).replace(microsecond=0)
    if _utc(observed) != profile.observed_azure_utc:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-observed-at-invalid"
        )
    deadline = derive_cleanup_control_recovery_deadline(
        observed, minimum_lead_hours=profile.minimum_lead_hours
    )
    if _utc(deadline) != profile.deadline_utc:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-derived-deadline-invalid"
        )
    unsigned = CleanupControlDeadlineRecoveryAuthorization(
        authorizationVersion=profile.authorization_version,
        repositoryHead=repository_head,
        subscriptionId=subscription_id,
        cleanupResourceGroupId=expected_cleanup,
        corruptedAutomationAccountId=expected_corrupted,
        corruptedPrincipalId=CORRUPTED_PRINCIPAL_ID,
        corruptedRoleAssignmentId=expected_corrupted_assignment,
        corruptedRoleAssignmentAction=DEADLINE_RECOVERY_CORRUPTED_ROLE_ACTION,
        replacementAutomationAccount=CLEANUP_AUTOMATION_ACCOUNT,
        replacementAutomationAccountId=expected_replacement,
        targetResourceGroupId=expected_target,
        roleDefinitionId=ROLE_DEFINITION_ID,
        roleScope=expected_target,
        runbook=RUNBOOK,
        schedule=SCHEDULE,
        targetParameter=TARGET_PARAMETER,
        targetParameterValue=TARGET_GROUP,
        authorizationParameter=AUTHORIZATION_PARAMETER,
        authorizationParameterValue=True,
        authorizedAtUtc=_utc(observed),
        deadlineUtc=_utc(deadline),
        bindingId=profile.binding_id,
        bindingContractVersion=CLEANUP_BINDING_CONTRACT_VERSION,
        runbookContentSha256=runbook_content_sha256,
        costCeilingUsdCents=COST_CEILING_CENTS,
        allowedOperations=DEADLINE_RECOVERY_ALLOWED_OPERATIONS,
        authorizationIntegritySha256="",
        recoveryAction=profile.recovery_action,
        deadlineObservedAtUtc=_utc(observed),
        deadlineDerivationRule=profile.derivation_rule,
        priorDeadlineUtc=profile.prior_deadline_utc,
        priorBindingId=profile.prior_binding_id,
        priorRunbookContentSha256=prior_runbook_content_sha256,
        replacementPrincipalId=DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID,
        replacementRoleAssignmentId=expected_replacement_assignment,
        replacementLocation=DEADLINE_RECOVERY_REPLACEMENT_LOCATION,
        scheduleAction=DEADLINE_RECOVERY_SCHEDULE_ACTION,
        bindingAction=DEADLINE_RECOVERY_BINDING_ACTION,
    )
    return replace(
        unsigned,
        authorizationIntegritySha256=(
            cleanup_control_deadline_recovery_authorization_integrity(unsigned)
        ),
    )


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
        bindingId=TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
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
        "bindingId": TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
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


def validate_cleanup_control_deadline_recovery_authorization(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    *,
    expected_repository_head: str,
    now_utc: datetime,
) -> CleanupControlDeadlineRecoveryAuthorization:
    profile = _deadline_recovery_profile(authorization.authorizationVersion)
    (
        expected_cleanup,
        expected_corrupted,
        expected_replacement,
        expected_target,
        expected_corrupted_assignment,
    ) = _expected_resource_ids(authorization.subscriptionId)
    expected_replacement_assignment = _expected_replacement_role_assignment_id(
        authorization.subscriptionId
    )
    exact_values = {
        "authorizationVersion": profile.authorization_version,
        "repositoryHead": expected_repository_head,
        "cleanupResourceGroupId": expected_cleanup,
        "corruptedAutomationAccountId": expected_corrupted,
        "corruptedPrincipalId": CORRUPTED_PRINCIPAL_ID,
        "corruptedRoleAssignmentId": expected_corrupted_assignment,
        "corruptedRoleAssignmentAction": DEADLINE_RECOVERY_CORRUPTED_ROLE_ACTION,
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
        "authorizedAtUtc": profile.observed_azure_utc,
        "deadlineUtc": profile.deadline_utc,
        "bindingId": profile.binding_id,
        "bindingContractVersion": CLEANUP_BINDING_CONTRACT_VERSION,
        "costCeilingUsdCents": COST_CEILING_CENTS,
        "allowedOperations": DEADLINE_RECOVERY_ALLOWED_OPERATIONS,
        "recoveryAction": profile.recovery_action,
        "deadlineObservedAtUtc": profile.observed_azure_utc,
        "deadlineDerivationRule": profile.derivation_rule,
        "priorDeadlineUtc": profile.prior_deadline_utc,
        "priorBindingId": profile.prior_binding_id,
        "priorRunbookContentSha256": profile.prior_runbook_content_sha256,
        "replacementPrincipalId": DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID,
        "replacementRoleAssignmentId": expected_replacement_assignment,
        "replacementLocation": DEADLINE_RECOVERY_REPLACEMENT_LOCATION,
        "scheduleAction": DEADLINE_RECOVERY_SCHEDULE_ACTION,
        "bindingAction": DEADLINE_RECOVERY_BINDING_ACTION,
    }
    observed = asdict(authorization)
    if any(observed.get(key) != value for key, value in exact_values.items()):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-scope-invalid"
        )
    if len(authorization.repositoryHead) != 40 or any(
        character not in "0123456789abcdef"
        for character in authorization.repositoryHead
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-repository-head-invalid")
    if authorization.runbookContentSha256 != cleanup_runbook_sha256(
        CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-runbook-content-invalid"
        )
    authorized_at = _parse_utc(
        authorization.authorizedAtUtc,
        "cleanup-deadline-recovery-authorized-at-invalid",
    )
    deadline_observed_at = _parse_utc(
        authorization.deadlineObservedAtUtc,
        "cleanup-deadline-recovery-observed-at-invalid",
    )
    deadline = _parse_utc(
        authorization.deadlineUtc,
        "cleanup-deadline-recovery-deadline-invalid",
    )
    prior_deadline = _parse_utc(
        authorization.priorDeadlineUtc,
        "cleanup-deadline-recovery-prior-deadline-invalid",
    )
    if (
        authorized_at != deadline_observed_at
        or derive_cleanup_control_recovery_deadline(
            deadline_observed_at,
            minimum_lead_hours=profile.minimum_lead_hours,
        )
        != deadline
        or prior_deadline >= deadline
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-derivation-invalid"
        )
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-current-time-invalid"
        )
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    if current < authorized_at or current > deadline:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-expired"
        )
    if authorization.authorizationIntegritySha256 != (
        cleanup_control_deadline_recovery_authorization_integrity(authorization)
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-integrity-invalid"
        )
    return authorization


def cleanup_control_deadline_recovery_authorization_from_mapping(
    value: JsonValue,
) -> CleanupControlDeadlineRecoveryAuthorization:
    if not isinstance(value, dict):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-malformed"
        )
    fields = set(CleanupControlDeadlineRecoveryAuthorization.__dataclass_fields__)
    if set(value) != fields:
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-malformed"
        )
    operations = value.get("allowedOperations")
    if not isinstance(operations, list) or any(
        not isinstance(item, str) for item in operations
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-malformed"
        )
    string_fields = fields - {
        "allowedOperations",
        "authorizationParameterValue",
        "costCeilingUsdCents",
    }
    if any(not isinstance(value.get(field), str) for field in string_fields):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-malformed"
        )
    authorization_value = value.get("authorizationParameterValue")
    cost_ceiling = value.get("costCeilingUsdCents")
    if not isinstance(authorization_value, bool) or (
        not isinstance(cost_ceiling, int) or isinstance(cost_ceiling, bool)
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-authorization-malformed"
        )
    return CleanupControlDeadlineRecoveryAuthorization(
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
        recoveryAction=cast(str, value["recoveryAction"]),
        deadlineObservedAtUtc=cast(str, value["deadlineObservedAtUtc"]),
        deadlineDerivationRule=cast(str, value["deadlineDerivationRule"]),
        priorDeadlineUtc=cast(str, value["priorDeadlineUtc"]),
        priorBindingId=cast(str, value["priorBindingId"]),
        priorRunbookContentSha256=cast(str, value["priorRunbookContentSha256"]),
        replacementPrincipalId=cast(str, value["replacementPrincipalId"]),
        replacementRoleAssignmentId=cast(str, value["replacementRoleAssignmentId"]),
        replacementLocation=cast(str, value["replacementLocation"]),
        scheduleAction=cast(str, value["scheduleAction"]),
        bindingAction=cast(str, value["bindingAction"]),
    )


def cleanup_control_recovery_authorization_from_mapping(
    value: JsonValue,
) -> CleanupControlRecoveryAuthorization:
    if isinstance(value, dict) and value.get("authorizationVersion") in {
        DEADLINE_RECOVERY_AUTHORIZATION_VERSION,
        DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
        DEADLINE_CONTINUATION_AUTHORIZATION_VERSION,
    }:
        return cleanup_control_deadline_recovery_authorization_from_mapping(value)
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
    authorization_body = (
        _deadline_recovery_authorization_body(authorization)
        if isinstance(authorization, CleanupControlDeadlineRecoveryAuthorization)
        else _authorization_body(authorization)
    )
    body = {
        **authorization_body,
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

    adapter = ProductionCleanupControlRecoveryAdapter()
    if isinstance(authorization, CleanupControlDeadlineRecoveryAuthorization):
        return adapter.execute_deadline_recovery(
            authorization=authorization,
            receipt_directory=receipt_directory,
            expected_repository_head=expected_repository_head,
        )
    return adapter.execute(
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
