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
    CLEANUP_BINDING_GENERATION,
    CLEANUP_RUNBOOK_PATH,
    CLEANUP_SCHEDULE,
    GENERATION_THREE_CLEANUP_BINDING_EPOCH_UTC,
    GENERATION_THREE_CLEANUP_SCHEDULE,
    LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
    REPOSITORY_ROOT,
    TOMBSTONED_DEADLINE_RECOVERY_BINDING_ID,
    TOMBSTONED_FIFTH_DEADLINE_RECOVERY_BINDING_ID,
    TOMBSTONED_FOURTH_DEADLINE_RECOVERY_BINDING_ID,
    TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC,
    TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_ID,
    TOMBSTONED_GENERATION_FOUR_COMPLETION_EXTENSION_BINDING_EPOCH_UTC,
    TOMBSTONED_GENERATION_FOUR_COMPLETION_EXTENSION_BINDING_ID,
    TOMBSTONED_GENERATION_FOUR_DEADLINE_EXTENSION_BINDING_EPOCH_UTC,
    TOMBSTONED_GENERATION_FOUR_DEADLINE_EXTENSION_BINDING_ID,
    TOMBSTONED_GENERATION_THREE_CLEANUP_BINDING_ID,
    TOMBSTONED_POST_FIRED_CLEANUP_BINDING_ID,
    TOMBSTONED_POST_V7_FINAL_COMPLETION_EXTENSION_BINDING_EPOCH_UTC,
    TOMBSTONED_POST_V7_FINAL_COMPLETION_EXTENSION_BINDING_ID,
    TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
    TOMBSTONED_THIRD_DEADLINE_RECOVERY_BINDING_ID,
    cleanup_binding_id_for_subscription,
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
DEADLINE_COMPLETION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v4"
)
DEADLINE_COMPLETION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v4\0"
)
POST_FIRED_RECOVERY_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v5"
)
POST_FIRED_RECOVERY_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v5\0"
)
GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v6"
)
GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v6\0"
)
GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v7"
)
GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v7\0"
)
POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v8"
)
POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v8\0"
)
CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery.v9"
)
CLEANUP_RECOVERY_V9_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery/v9\0"
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
DEADLINE_COMPLETION_OBSERVED_AZURE_UTC: Final = "2026-08-06T23:39:05Z"
DEADLINE_COMPLETION_DEADLINE_UTC: Final = "2026-08-07T11:45:00Z"
DEADLINE_COMPLETION_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-12-hours-after-observed"
)
DEADLINE_COMPLETION_ACTION: Final = (
    "extend-cleanup-deadline-for-image-five-proof-and-milestone-completion"
)
POST_FIRED_RECOVERY_OBSERVED_AZURE_UTC: Final = "2026-08-07T18:14:28Z"
POST_FIRED_RECOVERY_DEADLINE_UTC: Final = "2026-08-08T12:15:00Z"
POST_FIRED_RECOVERY_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-18-hours-after-observed"
)
POST_FIRED_RECOVERY_ACTION: Final = "post-fired-cleanup-recovery-and-rearm"
GENERATION_FOUR_DEADLINE_EXTENSION_OBSERVED_AZURE_UTC: Final = "2026-08-11T01:30:00Z"
GENERATION_FOUR_DEADLINE_EXTENSION_DEADLINE_UTC: Final = "2026-08-11T19:30:00Z"
GENERATION_FOUR_DEADLINE_EXTENSION_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-18-hours-after-observed"
)
GENERATION_FOUR_DEADLINE_EXTENSION_ACTION: Final = (
    "extend-generation-four-cleanup-for-pre-soak-recovery-and-completion"
)
GENERATION_FOUR_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC: Final = "2026-08-11T14:02:42Z"
GENERATION_FOUR_COMPLETION_EXTENSION_DEADLINE_UTC: Final = "2026-08-12T08:15:00Z"
GENERATION_FOUR_COMPLETION_EXTENSION_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-18-hours-after-observed"
)
GENERATION_FOUR_COMPLETION_EXTENSION_ACTION: Final = (
    "extend-generation-four-cleanup-for-terminal-evidence-and-completion"
)
POST_V7_FINAL_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC: Final = "2026-08-12T04:03:19Z"
POST_V7_FINAL_COMPLETION_EXTENSION_DEADLINE_UTC: Final = "2026-08-12T22:15:00Z"
POST_V7_FINAL_COMPLETION_EXTENSION_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-18-hours-after-observed"
)
POST_V7_FINAL_COMPLETION_EXTENSION_ACTION: Final = (
    "extend-generation-four-cleanup-for-final-live-completion"
)
POST_V7_FINAL_COMPLETION_MINIMUM_REMAINING_SECONDS: Final = 30_000
CLEANUP_RECOVERY_V9_OBSERVED_AZURE_UTC: Final = "2026-08-12T20:23:35Z"
CLEANUP_RECOVERY_V9_DEADLINE_UTC: Final = "2026-08-13T06:30:00Z"
CLEANUP_RECOVERY_V9_DERIVATION_RULE: Final = (
    "next-15-minute-utc-boundary-at-least-10-hours-after-observed"
)
CLEANUP_RECOVERY_V9_ACTION: Final = (
    "extend-generation-four-cleanup-for-post-secret-soak-completion"
)
CLEANUP_RECOVERY_V9_MINIMUM_REMAINING_SECONDS: Final = 30_000
POST_FIRED_RECOVERY_PURPOSE: Final = "POST_FIRED_CLEANUP_RECOVERY_AND_REARM"
POST_FIRED_PRIOR_JOB_NAME: Final = "3a0c2ace-79bc-4120-90b8-00bc8b6ff46d"
POST_FIRED_PRIOR_JOB_STATUS: Final = "Failed"
POST_FIRED_PRIOR_JOB_EXCEPTION: Final = (
    "cleanup-contract-role-scope-unproved (cleanup-contract-role-scope-unproved)"
)
POST_FIRED_PRIOR_JOB_CREATED_AT_UTC: Final = "2026-08-07T11:45:01Z"
POST_FIRED_DELETE_ACTIVITY_START_UTC: Final = "2026-08-07T11:44:00Z"
POST_FIRED_PRIOR_SCHEDULE_STATE: Final = "fired-expired"
POST_FIRED_PRIOR_BINDING_STATE: Final = "stale-expired"
POST_FIRED_TARGET_PRESERVATION_STATE: Final = "present-no-delete-activity"
POST_FIRED_REPLACEMENT_IDENTITY_STATE: Final = "present"
POST_FIRED_REPLACEMENT_AUTHORITY_STATE: Final = (
    "exact-direct-contributor-at-target-scope"
)
POST_FIRED_EXPECTED_TARGET_RESOURCE_COUNT: Final = 41
POST_FIRED_EXPECTED_DELETE_ACTIVITY_COUNT: Final = 0
POST_FIRED_EXPECTED_NONTERMINAL_JOB_COUNT: Final = 0
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
DEADLINE_COMPLETION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "0879e15468b475bb623f68b66d7e2b1d094f2f37c1a2ac92176ad7ce21f70b6f"
)
POST_FIRED_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "3e9bf90f433b01ec0d82d78f0e8cdde9b0cb919a4d8cd74ad4f85186cdc54748"
)
GENERATION_FOUR_DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "2bc41921d6a6d25d3a784139dfcd4dc8c551545bed5af01fc36a25ad57eb9916"
)
GENERATION_FOUR_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "2bc41921d6a6d25d3a784139dfcd4dc8c551545bed5af01fc36a25ad57eb9916"
)
POST_V7_FINAL_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "2bc41921d6a6d25d3a784139dfcd4dc8c551545bed5af01fc36a25ad57eb9916"
)
DEADLINE_RECOVERY_ALLOWED_OPERATIONS: Final = (
    "verify-preserved-cleanup-control",
    "remove-exact-prior-job-schedule-binding",
    "publish-deadline-adjusted-guarded-runbook",
    "replace-same-name-one-time-schedule",
    "create-exact-job-schedule-binding",
    "verify-cleanup-executable",
)
POST_FIRED_RECOVERY_ALLOWED_OPERATIONS: Final = (
    "verify-post-fired-fail-closed-state",
    "verify-preserved-cleanup-control",
    "remove-exact-prior-job-schedule-binding",
    "publish-principal-and-deadline-adjusted-guarded-runbook",
    "replace-expired-fired-one-time-schedule",
    "create-exact-job-schedule-binding",
    "verify-cleanup-executable",
)
POST_CLEANUP_REPROVISION_AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-reprovision.v2"
)
POST_CLEANUP_REPROVISION_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-reprovision/v2\0"
)
POST_CLEANUP_REPROVISION_ACTION: Final = "create-new-cleanup-generation-and-staging"
POST_CLEANUP_REPROVISION_PRIOR_JOB_NAME: Final = "8e632544-340a-4f4f-912c-a109de48ab3c"
POST_CLEANUP_REPROVISION_PRIOR_JOB_STATUS: Final = "Completed"
POST_CLEANUP_REPROVISION_PRIOR_RUNBOOK_CONTENT_SHA256: Final = (
    "2bc41921d6a6d25d3a784139dfcd4dc8c551545bed5af01fc36a25ad57eb9916"
)
POST_CLEANUP_REPROVISION_PRIOR_SOURCE_COMMIT: Final = (
    "bef0ae61cd467310ff9617dc77d28711bc150b5b"
)
POST_CLEANUP_REPROVISION_PRIOR_BINDING_SHA256: Final = (
    "e9136d31efd3e4cadadb34b3d8ba44301da7a234048bfc7df5c70d696fcbec1c"
)
POST_CLEANUP_REPROVISION_PRIOR_MANIFEST_SHA256: Final = (
    "d514f7cedcc1822881055e8d7a1db297c5a5d0a39545a55ef1dc0d925201a49b"
)
POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT: Final = "kv-mobius77-11564669"
POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_LOCATION: Final = "southcentralus"
POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_AT_UTC: Final = "2026-08-09T08:01:54Z"
POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_ACTION: Final = (
    "purge-exact-soft-deleted-key-vault"
)
POST_CLEANUP_REPROVISION_DELETED_WORKSPACE: Final = "law-mobius77-staging"
POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_LOCATION: Final = "southcentralus"
POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_AT_UTC: Final = (
    "2026-08-09T08:02:25.8464081Z"
)
POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_CUSTOMER_ID: Final = (
    "df2bb7a1-9504-4a8d-9d3d-de421ea1b409"
)
POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_ACTION: Final = (
    "recover-exact-workspace-after-cleanup-armed"
)
POST_CLEANUP_REPROVISION_FOUNDATION_STAGE: Final = "scanner-foundation"
POST_CLEANUP_REPROVISION_STORAGE_ACCOUNT: Final = "stmobius7711564669"
POST_CLEANUP_REPROVISION_WORKER_IDENTITY: Final = "id-mobius77-worker"
POST_CLEANUP_REPROVISION_PRIVATE_LINK_SCOPE: Final = "ampls-mobius77-staging"
POST_CLEANUP_REPROVISION_MONITOR_PRIVATE_ENDPOINT: Final = "pe-mobius77-azure-monitor"
POST_CLEANUP_REPROVISION_EXPIRATION_MINUTES: Final = 30
POST_CLEANUP_REPROVISION_ALLOWED_OPERATIONS: Final = (
    "verify-completed-prior-cleanup",
    "purge-exact-generation-three-soft-deleted-key-vault",
    "reconcile-exact-generation-three-deleted-workspace",
    "remove-exact-prior-job-schedule-binding",
    "remove-exact-prior-schedule",
    "adopt-exact-replacement-automation-account",
    "publish-deadline-adjusted-guarded-runbook",
    "create-new-one-time-schedule",
    "create-new-exact-job-schedule-binding",
    "create-exact-target-resource-group-and-cleanup-role",
    "deploy-established-private-staging-foundation",
    "verify-cleanup-and-private-foundation",
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
    postFiredRecoveryPurpose: str | None = None
    priorCleanupJobId: str | None = None
    priorCleanupJobStatus: str | None = None
    priorCleanupJobException: str | None = None
    priorCleanupJobCreatedAtUtc: str | None = None
    deleteActivityStartUtc: str | None = None
    priorScheduleState: str | None = None
    priorBindingState: str | None = None
    targetPreservationState: str | None = None
    replacementIdentityState: str | None = None
    replacementAuthorityState: str | None = None
    expectedTargetResourceCount: int | None = None
    expectedDeleteActivityCount: int | None = None
    expectedNonterminalCleanupJobCount: int | None = None


@dataclass(frozen=True)
class CleanupControlReprovisionAuthorization(CleanupControlRecoveryAuthorization):
    """One-use grant for a new cleanup generation after successful cleanup."""

    authorizationExpiresAtUtc: str
    bindingGeneration: int
    corruptedSchedule: str
    priorBindingId: str
    priorDeadlineUtc: str
    priorSchedule: str
    priorRunbookContentSha256: str
    replacementPrincipalId: str
    replacementRoleAssignmentId: str
    replacementLocation: str
    completedCleanupJobId: str
    completedCleanupJobStatus: str
    priorGenerationSourceCommit: str
    priorLifecycleBindingSha256: str
    priorManifestSha256: str
    deletedKeyVaultId: str
    deletedKeyVaultName: str
    deletedKeyVaultLocation: str
    deletedKeyVaultAtUtc: str
    deletedKeyVaultAction: str
    deletedWorkspaceId: str
    deletedWorkspaceName: str
    deletedWorkspaceLocation: str
    deletedWorkspaceAtUtc: str
    deletedWorkspaceCustomerId: str
    deletedWorkspaceAction: str
    reprovisionAction: str
    foundationStage: str
    storageAccountId: str
    logAnalyticsWorkspaceId: str
    workerIdentityId: str
    privateLinkScopeId: str
    monitorPrivateEndpointId: str
    imageRestorationAuthorized: bool
    scannerProofAuthorized: bool
    maximumScannerProofExecutions: int


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
    schedule: str
    binding_contract_version: str
    corrupted_schedule: str
    post_fired: bool


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
            schedule=SCHEDULE,
            binding_contract_version=LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
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
            schedule=SCHEDULE,
            binding_contract_version=LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
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
            binding_id=TOMBSTONED_FOURTH_DEADLINE_RECOVERY_BINDING_ID,
            prior_runbook_content_sha256=(
                DEADLINE_CONTINUATION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=SCHEDULE,
            binding_contract_version=LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
        )
    if authorization_version == DEADLINE_COMPLETION_AUTHORIZATION_VERSION:
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=DEADLINE_COMPLETION_AUTHORIZATION_DOMAIN,
            observed_azure_utc=DEADLINE_COMPLETION_OBSERVED_AZURE_UTC,
            deadline_utc=DEADLINE_COMPLETION_DEADLINE_UTC,
            derivation_rule=DEADLINE_COMPLETION_DERIVATION_RULE,
            minimum_lead_hours=12,
            recovery_action=DEADLINE_COMPLETION_ACTION,
            prior_deadline_utc=DEADLINE_CONTINUATION_DEADLINE_UTC,
            prior_binding_id=TOMBSTONED_FOURTH_DEADLINE_RECOVERY_BINDING_ID,
            binding_id=TOMBSTONED_FIFTH_DEADLINE_RECOVERY_BINDING_ID,
            prior_runbook_content_sha256=(
                DEADLINE_COMPLETION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=SCHEDULE,
            binding_contract_version=LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
        )
    if authorization_version == POST_FIRED_RECOVERY_AUTHORIZATION_VERSION:
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=POST_FIRED_RECOVERY_AUTHORIZATION_DOMAIN,
            observed_azure_utc=POST_FIRED_RECOVERY_OBSERVED_AZURE_UTC,
            deadline_utc=POST_FIRED_RECOVERY_DEADLINE_UTC,
            derivation_rule=POST_FIRED_RECOVERY_DERIVATION_RULE,
            minimum_lead_hours=18,
            recovery_action=POST_FIRED_RECOVERY_ACTION,
            prior_deadline_utc=DEADLINE_COMPLETION_DEADLINE_UTC,
            prior_binding_id=TOMBSTONED_FIFTH_DEADLINE_RECOVERY_BINDING_ID,
            binding_id=TOMBSTONED_POST_FIRED_CLEANUP_BINDING_ID,
            prior_runbook_content_sha256=(
                POST_FIRED_RECOVERY_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=SCHEDULE,
            binding_contract_version=LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=True,
        )
    if (
        authorization_version
        == GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_VERSION
    ):
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=(
                GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_DOMAIN
            ),
            observed_azure_utc=(GENERATION_FOUR_DEADLINE_EXTENSION_OBSERVED_AZURE_UTC),
            deadline_utc=GENERATION_FOUR_DEADLINE_EXTENSION_DEADLINE_UTC,
            derivation_rule=GENERATION_FOUR_DEADLINE_EXTENSION_DERIVATION_RULE,
            minimum_lead_hours=18,
            recovery_action=GENERATION_FOUR_DEADLINE_EXTENSION_ACTION,
            prior_deadline_utc=(TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC),
            prior_binding_id=TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_ID,
            binding_id=(TOMBSTONED_GENERATION_FOUR_DEADLINE_EXTENSION_BINDING_ID),
            prior_runbook_content_sha256=(
                GENERATION_FOUR_DEADLINE_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=CLEANUP_SCHEDULE,
            binding_contract_version=CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
        )
    if (
        authorization_version
        == GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION
    ):
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=(
                GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_DOMAIN
            ),
            observed_azure_utc=(
                GENERATION_FOUR_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC
            ),
            deadline_utc=GENERATION_FOUR_COMPLETION_EXTENSION_DEADLINE_UTC,
            derivation_rule=(GENERATION_FOUR_COMPLETION_EXTENSION_DERIVATION_RULE),
            minimum_lead_hours=18,
            recovery_action=GENERATION_FOUR_COMPLETION_EXTENSION_ACTION,
            prior_deadline_utc=(
                TOMBSTONED_GENERATION_FOUR_DEADLINE_EXTENSION_BINDING_EPOCH_UTC
            ),
            prior_binding_id=(TOMBSTONED_GENERATION_FOUR_DEADLINE_EXTENSION_BINDING_ID),
            binding_id=(TOMBSTONED_GENERATION_FOUR_COMPLETION_EXTENSION_BINDING_ID),
            prior_runbook_content_sha256=(
                GENERATION_FOUR_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=CLEANUP_SCHEDULE,
            binding_contract_version=CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
        )
    if (
        authorization_version
        == POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION
    ):
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=(
                POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_DOMAIN
            ),
            observed_azure_utc=(POST_V7_FINAL_COMPLETION_EXTENSION_OBSERVED_AZURE_UTC),
            deadline_utc=POST_V7_FINAL_COMPLETION_EXTENSION_DEADLINE_UTC,
            derivation_rule=(POST_V7_FINAL_COMPLETION_EXTENSION_DERIVATION_RULE),
            minimum_lead_hours=18,
            recovery_action=POST_V7_FINAL_COMPLETION_EXTENSION_ACTION,
            prior_deadline_utc=(
                TOMBSTONED_GENERATION_FOUR_COMPLETION_EXTENSION_BINDING_EPOCH_UTC
            ),
            prior_binding_id=(
                TOMBSTONED_GENERATION_FOUR_COMPLETION_EXTENSION_BINDING_ID
            ),
            binding_id=(
                TOMBSTONED_POST_V7_FINAL_COMPLETION_EXTENSION_BINDING_ID
            ),
            prior_runbook_content_sha256=(
                POST_V7_FINAL_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=CLEANUP_SCHEDULE,
            binding_contract_version=CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
        )
    if authorization_version == CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION:
        return _DeadlineRecoveryProfile(
            authorization_version=authorization_version,
            authorization_domain=CLEANUP_RECOVERY_V9_AUTHORIZATION_DOMAIN,
            observed_azure_utc=CLEANUP_RECOVERY_V9_OBSERVED_AZURE_UTC,
            deadline_utc=CLEANUP_RECOVERY_V9_DEADLINE_UTC,
            derivation_rule=CLEANUP_RECOVERY_V9_DERIVATION_RULE,
            minimum_lead_hours=10,
            recovery_action=CLEANUP_RECOVERY_V9_ACTION,
            prior_deadline_utc=(
                TOMBSTONED_POST_V7_FINAL_COMPLETION_EXTENSION_BINDING_EPOCH_UTC
            ),
            prior_binding_id=(
                TOMBSTONED_POST_V7_FINAL_COMPLETION_EXTENSION_BINDING_ID
            ),
            binding_id=ACTIVE_CLEANUP_BINDING_ID,
            prior_runbook_content_sha256=(
                POST_V7_FINAL_COMPLETION_EXTENSION_PRIOR_RUNBOOK_CONTENT_SHA256
            ),
            schedule=CLEANUP_SCHEDULE,
            binding_contract_version=CLEANUP_BINDING_CONTRACT_VERSION,
            corrupted_schedule=SCHEDULE,
            post_fired=False,
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
    if minimum_lead_hours not in {6, 10, 12, 18}:
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


def _expected_reprovision_residue_ids(subscription_id: str) -> tuple[str, str]:
    _, _, _, target_group, _ = _expected_resource_ids(subscription_id)
    return (
        f"/subscriptions/{subscription_id}/providers/Microsoft.KeyVault/locations/"
        f"{POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_LOCATION}/deletedVaults/"
        f"{POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT}",
        f"{target_group}/providers/Microsoft.OperationalInsights/workspaces/"
        f"{POST_CLEANUP_REPROVISION_DELETED_WORKSPACE}",
    )


def _expected_reprovision_foundation_ids(
    subscription_id: str,
) -> tuple[str, str, str, str, str]:
    _, _, _, target_group, _ = _expected_resource_ids(subscription_id)
    return (
        f"{target_group}/providers/Microsoft.Storage/storageAccounts/"
        f"{POST_CLEANUP_REPROVISION_STORAGE_ACCOUNT}",
        f"{target_group}/providers/Microsoft.OperationalInsights/workspaces/"
        f"{POST_CLEANUP_REPROVISION_DELETED_WORKSPACE}",
        f"{target_group}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        f"{POST_CLEANUP_REPROVISION_WORKER_IDENTITY}",
        f"{target_group}/providers/Microsoft.Insights/privateLinkScopes/"
        f"{POST_CLEANUP_REPROVISION_PRIVATE_LINK_SCOPE}",
        f"{target_group}/providers/Microsoft.Network/privateEndpoints/"
        f"{POST_CLEANUP_REPROVISION_MONITOR_PRIVATE_ENDPOINT}",
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
    body: dict[str, JsonValue] = {
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
    if _deadline_recovery_profile(authorization.authorizationVersion).post_fired:
        body.update(
            {
                "postFiredRecoveryPurpose": authorization.postFiredRecoveryPurpose,
                "priorCleanupJobId": authorization.priorCleanupJobId,
                "priorCleanupJobStatus": authorization.priorCleanupJobStatus,
                "priorCleanupJobException": authorization.priorCleanupJobException,
                "priorCleanupJobCreatedAtUtc": authorization.priorCleanupJobCreatedAtUtc,
                "deleteActivityStartUtc": authorization.deleteActivityStartUtc,
                "priorScheduleState": authorization.priorScheduleState,
                "priorBindingState": authorization.priorBindingState,
                "targetPreservationState": authorization.targetPreservationState,
                "replacementIdentityState": authorization.replacementIdentityState,
                "replacementAuthorityState": authorization.replacementAuthorityState,
                "expectedTargetResourceCount": authorization.expectedTargetResourceCount,
                "expectedDeleteActivityCount": authorization.expectedDeleteActivityCount,
                "expectedNonterminalCleanupJobCount": (
                    authorization.expectedNonterminalCleanupJobCount
                ),
            }
        )
    return body


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


def _reprovision_authorization_body(
    authorization: CleanupControlReprovisionAuthorization,
) -> dict[str, JsonValue]:
    return {
        **_authorization_body(authorization),
        "authorizationExpiresAtUtc": authorization.authorizationExpiresAtUtc,
        "bindingGeneration": authorization.bindingGeneration,
        "corruptedSchedule": authorization.corruptedSchedule,
        "priorBindingId": authorization.priorBindingId,
        "priorDeadlineUtc": authorization.priorDeadlineUtc,
        "priorSchedule": authorization.priorSchedule,
        "priorRunbookContentSha256": authorization.priorRunbookContentSha256,
        "replacementPrincipalId": authorization.replacementPrincipalId,
        "replacementRoleAssignmentId": authorization.replacementRoleAssignmentId,
        "replacementLocation": authorization.replacementLocation,
        "completedCleanupJobId": authorization.completedCleanupJobId,
        "completedCleanupJobStatus": authorization.completedCleanupJobStatus,
        "priorGenerationSourceCommit": authorization.priorGenerationSourceCommit,
        "priorLifecycleBindingSha256": authorization.priorLifecycleBindingSha256,
        "priorManifestSha256": authorization.priorManifestSha256,
        "deletedKeyVaultId": authorization.deletedKeyVaultId,
        "deletedKeyVaultName": authorization.deletedKeyVaultName,
        "deletedKeyVaultLocation": authorization.deletedKeyVaultLocation,
        "deletedKeyVaultAtUtc": authorization.deletedKeyVaultAtUtc,
        "deletedKeyVaultAction": authorization.deletedKeyVaultAction,
        "deletedWorkspaceId": authorization.deletedWorkspaceId,
        "deletedWorkspaceName": authorization.deletedWorkspaceName,
        "deletedWorkspaceLocation": authorization.deletedWorkspaceLocation,
        "deletedWorkspaceAtUtc": authorization.deletedWorkspaceAtUtc,
        "deletedWorkspaceCustomerId": authorization.deletedWorkspaceCustomerId,
        "deletedWorkspaceAction": authorization.deletedWorkspaceAction,
        "reprovisionAction": authorization.reprovisionAction,
        "foundationStage": authorization.foundationStage,
        "storageAccountId": authorization.storageAccountId,
        "logAnalyticsWorkspaceId": authorization.logAnalyticsWorkspaceId,
        "workerIdentityId": authorization.workerIdentityId,
        "privateLinkScopeId": authorization.privateLinkScopeId,
        "monitorPrivateEndpointId": authorization.monitorPrivateEndpointId,
        "imageRestorationAuthorized": authorization.imageRestorationAuthorized,
        "scannerProofAuthorized": authorization.scannerProofAuthorized,
        "maximumScannerProofExecutions": authorization.maximumScannerProofExecutions,
    }


def cleanup_control_reprovision_authorization_integrity(
    authorization: CleanupControlReprovisionAuthorization,
) -> str:
    digest = integrity_sha256(
        _reprovision_authorization_body(authorization),
        POST_CLEANUP_REPROVISION_AUTHORIZATION_DOMAIN,
    )
    if not isinstance(digest, str):
        raise CleanupControlRecoveryError(
            "cleanup-reprovision-authorization-integrity-malformed"
        )
    return digest


def build_cleanup_control_reprovision_authorization(
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
    prior_generation_source_commit: str,
    prior_lifecycle_binding_sha256: str,
    prior_manifest_sha256: str,
    deleted_key_vault_id: str,
    deleted_key_vault_name: str,
    deleted_key_vault_location: str,
    deleted_key_vault_at_utc: str,
    deleted_workspace_id: str,
    deleted_workspace_name: str,
    deleted_workspace_location: str,
    deleted_workspace_at_utc: str,
    deleted_workspace_customer_id: str,
    runbook_content_sha256: str,
    now_utc: datetime,
) -> CleanupControlReprovisionAuthorization:
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
    expected_deleted_key_vault, expected_deleted_workspace = (
        _expected_reprovision_residue_ids(subscription_id)
    )
    (
        expected_storage_account,
        expected_workspace,
        expected_worker_identity,
        expected_private_link_scope,
        expected_monitor_private_endpoint,
    ) = _expected_reprovision_foundation_ids(subscription_id)
    exact_resource_values = (
        (cleanup_resource_group_id, expected_cleanup),
        (corrupted_automation_account_id, expected_corrupted),
        (replacement_automation_account_id, expected_replacement),
        (target_resource_group_id, expected_target),
    )
    if any(observed != expected for observed, expected in exact_resource_values):
        raise CleanupControlRecoveryError("cleanup-reprovision-resource-scope-invalid")
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
            "cleanup-reprovision-replacement-principal-invalid"
        )
    if (
        replacement_role_assignment_id.casefold()
        != expected_replacement_assignment.casefold()
    ):
        raise CleanupControlRecoveryError(
            "cleanup-reprovision-replacement-assignment-invalid"
        )
    if replacement_location != DEADLINE_RECOVERY_REPLACEMENT_LOCATION:
        raise CleanupControlRecoveryError(
            "cleanup-reprovision-replacement-location-invalid"
        )
    expected_residue_values = (
        (prior_generation_source_commit, POST_CLEANUP_REPROVISION_PRIOR_SOURCE_COMMIT),
        (
            prior_lifecycle_binding_sha256,
            POST_CLEANUP_REPROVISION_PRIOR_BINDING_SHA256,
        ),
        (prior_manifest_sha256, POST_CLEANUP_REPROVISION_PRIOR_MANIFEST_SHA256),
        (deleted_key_vault_id, expected_deleted_key_vault),
        (deleted_key_vault_name, POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT),
        (
            deleted_key_vault_location,
            POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_LOCATION,
        ),
        (
            deleted_key_vault_at_utc,
            POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_AT_UTC,
        ),
        (deleted_workspace_id, expected_deleted_workspace),
        (deleted_workspace_name, POST_CLEANUP_REPROVISION_DELETED_WORKSPACE),
        (
            deleted_workspace_location,
            POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_LOCATION,
        ),
        (
            deleted_workspace_at_utc,
            POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_AT_UTC,
        ),
        (
            deleted_workspace_customer_id,
            POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_CUSTOMER_ID,
        ),
    )
    if any(observed != expected for observed, expected in expected_residue_values):
        raise CleanupControlRecoveryError("cleanup-reprovision-residue-scope-invalid")
    expected_runbook_hash = cleanup_runbook_sha256(
        CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
    )
    if runbook_content_sha256 != expected_runbook_hash:
        raise CleanupControlRecoveryError("cleanup-reprovision-runbook-content-invalid")
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise CleanupControlRecoveryError("cleanup-reprovision-current-time-invalid")
    authorized_at = now_utc.astimezone(UTC).replace(microsecond=0)
    deadline = _parse_utc(
        TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC,
        "cleanup-reprovision-deadline-invalid",
    )
    if not timedelta(minutes=90) < deadline - authorized_at <= timedelta(hours=30):
        raise CleanupControlRecoveryError(
            "cleanup-reprovision-deadline-outside-safe-window"
        )
    expires_at = authorized_at + timedelta(
        minutes=POST_CLEANUP_REPROVISION_EXPIRATION_MINUTES
    )
    binding_id = cleanup_binding_id_for_subscription(
        subscription_id,
        generation=CLEANUP_BINDING_GENERATION,
        binding_epoch_utc=TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC,
    )
    completed_cleanup_job_id = POST_CLEANUP_REPROVISION_PRIOR_JOB_NAME
    unsigned = CleanupControlReprovisionAuthorization(
        authorizationVersion=POST_CLEANUP_REPROVISION_AUTHORIZATION_VERSION,
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
        schedule=CLEANUP_SCHEDULE,
        targetParameter=TARGET_PARAMETER,
        targetParameterValue=TARGET_GROUP,
        authorizationParameter=AUTHORIZATION_PARAMETER,
        authorizationParameterValue=True,
        authorizedAtUtc=_utc(authorized_at),
        deadlineUtc=TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC,
        bindingId=binding_id,
        bindingContractVersion=CLEANUP_BINDING_CONTRACT_VERSION,
        runbookContentSha256=runbook_content_sha256,
        costCeilingUsdCents=COST_CEILING_CENTS,
        allowedOperations=POST_CLEANUP_REPROVISION_ALLOWED_OPERATIONS,
        authorizationIntegritySha256="",
        authorizationExpiresAtUtc=_utc(expires_at),
        bindingGeneration=CLEANUP_BINDING_GENERATION,
        corruptedSchedule=SCHEDULE,
        priorBindingId=TOMBSTONED_GENERATION_THREE_CLEANUP_BINDING_ID,
        priorDeadlineUtc=GENERATION_THREE_CLEANUP_BINDING_EPOCH_UTC,
        priorSchedule=GENERATION_THREE_CLEANUP_SCHEDULE,
        priorRunbookContentSha256=(
            POST_CLEANUP_REPROVISION_PRIOR_RUNBOOK_CONTENT_SHA256
        ),
        replacementPrincipalId=DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID,
        replacementRoleAssignmentId=expected_replacement_assignment,
        replacementLocation=DEADLINE_RECOVERY_REPLACEMENT_LOCATION,
        completedCleanupJobId=completed_cleanup_job_id,
        completedCleanupJobStatus=POST_CLEANUP_REPROVISION_PRIOR_JOB_STATUS,
        priorGenerationSourceCommit=prior_generation_source_commit,
        priorLifecycleBindingSha256=prior_lifecycle_binding_sha256,
        priorManifestSha256=prior_manifest_sha256,
        deletedKeyVaultId=deleted_key_vault_id,
        deletedKeyVaultName=deleted_key_vault_name,
        deletedKeyVaultLocation=deleted_key_vault_location,
        deletedKeyVaultAtUtc=deleted_key_vault_at_utc,
        deletedKeyVaultAction=POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_ACTION,
        deletedWorkspaceId=deleted_workspace_id,
        deletedWorkspaceName=deleted_workspace_name,
        deletedWorkspaceLocation=deleted_workspace_location,
        deletedWorkspaceAtUtc=deleted_workspace_at_utc,
        deletedWorkspaceCustomerId=deleted_workspace_customer_id,
        deletedWorkspaceAction=POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_ACTION,
        reprovisionAction=POST_CLEANUP_REPROVISION_ACTION,
        foundationStage=POST_CLEANUP_REPROVISION_FOUNDATION_STAGE,
        storageAccountId=expected_storage_account,
        logAnalyticsWorkspaceId=expected_workspace,
        workerIdentityId=expected_worker_identity,
        privateLinkScopeId=expected_private_link_scope,
        monitorPrivateEndpointId=expected_monitor_private_endpoint,
        imageRestorationAuthorized=False,
        scannerProofAuthorized=False,
        maximumScannerProofExecutions=0,
    )
    return replace(
        unsigned,
        authorizationIntegritySha256=(
            cleanup_control_reprovision_authorization_integrity(unsigned)
        ),
    )


def validate_cleanup_control_reprovision_authorization(
    authorization: CleanupControlReprovisionAuthorization,
    *,
    expected_repository_head: str,
    now_utc: datetime,
) -> CleanupControlReprovisionAuthorization:
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
    expected_deleted_key_vault, expected_deleted_workspace = (
        _expected_reprovision_residue_ids(authorization.subscriptionId)
    )
    (
        expected_storage_account,
        expected_workspace,
        expected_worker_identity,
        expected_private_link_scope,
        expected_monitor_private_endpoint,
    ) = _expected_reprovision_foundation_ids(authorization.subscriptionId)
    expected_completed_job = POST_CLEANUP_REPROVISION_PRIOR_JOB_NAME
    exact_values = {
        "authorizationVersion": POST_CLEANUP_REPROVISION_AUTHORIZATION_VERSION,
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
        "schedule": CLEANUP_SCHEDULE,
        "targetParameter": TARGET_PARAMETER,
        "targetParameterValue": TARGET_GROUP,
        "authorizationParameter": AUTHORIZATION_PARAMETER,
        "authorizationParameterValue": True,
        "deadlineUtc": TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC,
        "bindingId": cleanup_binding_id_for_subscription(
            authorization.subscriptionId,
            generation=CLEANUP_BINDING_GENERATION,
            binding_epoch_utc=TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC,
        ),
        "bindingContractVersion": CLEANUP_BINDING_CONTRACT_VERSION,
        "runbookContentSha256": cleanup_runbook_sha256(
            CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
        ),
        "costCeilingUsdCents": COST_CEILING_CENTS,
        "allowedOperations": POST_CLEANUP_REPROVISION_ALLOWED_OPERATIONS,
        "bindingGeneration": CLEANUP_BINDING_GENERATION,
        "corruptedSchedule": SCHEDULE,
        "priorBindingId": TOMBSTONED_GENERATION_THREE_CLEANUP_BINDING_ID,
        "priorDeadlineUtc": GENERATION_THREE_CLEANUP_BINDING_EPOCH_UTC,
        "priorSchedule": GENERATION_THREE_CLEANUP_SCHEDULE,
        "priorRunbookContentSha256": (
            POST_CLEANUP_REPROVISION_PRIOR_RUNBOOK_CONTENT_SHA256
        ),
        "replacementPrincipalId": DEADLINE_RECOVERY_REPLACEMENT_PRINCIPAL_ID,
        "replacementRoleAssignmentId": expected_replacement_assignment,
        "replacementLocation": DEADLINE_RECOVERY_REPLACEMENT_LOCATION,
        "completedCleanupJobId": expected_completed_job,
        "completedCleanupJobStatus": POST_CLEANUP_REPROVISION_PRIOR_JOB_STATUS,
        "priorGenerationSourceCommit": POST_CLEANUP_REPROVISION_PRIOR_SOURCE_COMMIT,
        "priorLifecycleBindingSha256": (POST_CLEANUP_REPROVISION_PRIOR_BINDING_SHA256),
        "priorManifestSha256": POST_CLEANUP_REPROVISION_PRIOR_MANIFEST_SHA256,
        "deletedKeyVaultId": expected_deleted_key_vault,
        "deletedKeyVaultName": POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT,
        "deletedKeyVaultLocation": (
            POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_LOCATION
        ),
        "deletedKeyVaultAtUtc": POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_AT_UTC,
        "deletedKeyVaultAction": POST_CLEANUP_REPROVISION_DELETED_KEY_VAULT_ACTION,
        "deletedWorkspaceId": expected_deleted_workspace,
        "deletedWorkspaceName": POST_CLEANUP_REPROVISION_DELETED_WORKSPACE,
        "deletedWorkspaceLocation": (
            POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_LOCATION
        ),
        "deletedWorkspaceAtUtc": POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_AT_UTC,
        "deletedWorkspaceCustomerId": (
            POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_CUSTOMER_ID
        ),
        "deletedWorkspaceAction": POST_CLEANUP_REPROVISION_DELETED_WORKSPACE_ACTION,
        "reprovisionAction": POST_CLEANUP_REPROVISION_ACTION,
        "foundationStage": POST_CLEANUP_REPROVISION_FOUNDATION_STAGE,
        "storageAccountId": expected_storage_account,
        "logAnalyticsWorkspaceId": expected_workspace,
        "workerIdentityId": expected_worker_identity,
        "privateLinkScopeId": expected_private_link_scope,
        "monitorPrivateEndpointId": expected_monitor_private_endpoint,
        "imageRestorationAuthorized": False,
        "scannerProofAuthorized": False,
        "maximumScannerProofExecutions": 0,
    }
    observed = asdict(authorization)
    if any(observed.get(key) != value for key, value in exact_values.items()):
        raise CleanupControlRecoveryError(
            "cleanup-reprovision-authorization-scope-invalid"
        )
    authorized_at = _parse_utc(
        authorization.authorizedAtUtc,
        "cleanup-reprovision-authorized-at-invalid",
    )
    expires_at = _parse_utc(
        authorization.authorizationExpiresAtUtc,
        "cleanup-reprovision-expires-at-invalid",
    )
    deadline = _parse_utc(
        authorization.deadlineUtc,
        "cleanup-reprovision-deadline-invalid",
    )
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise CleanupControlRecoveryError("cleanup-reprovision-current-time-invalid")
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    if (
        authorized_at > current
        or current > expires_at
        or expires_at - authorized_at
        != timedelta(minutes=POST_CLEANUP_REPROVISION_EXPIRATION_MINUTES)
        or deadline - current <= timedelta(minutes=90)
        or deadline - authorized_at > timedelta(hours=30)
    ):
        raise CleanupControlRecoveryError("cleanup-reprovision-authorization-expired")
    if authorization.authorizationIntegritySha256 != (
        cleanup_control_reprovision_authorization_integrity(authorization)
    ):
        raise CleanupControlRecoveryError(
            "cleanup-reprovision-authorization-integrity-invalid"
        )
    return authorization


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
    prior_cleanup_job_id: str | None = None,
    prior_cleanup_job_status: str | None = None,
    prior_cleanup_job_exception: str | None = None,
    target_resource_count: int | None = None,
    delete_activity_count: int | None = None,
    nonterminal_cleanup_job_count: int | None = None,
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
    expected_prior_job_id = (
        f"{expected_replacement}/jobs/{POST_FIRED_PRIOR_JOB_NAME}"
        if profile.post_fired
        else None
    )
    post_fired_inputs = (
        prior_cleanup_job_id,
        prior_cleanup_job_status,
        prior_cleanup_job_exception,
        target_resource_count,
        delete_activity_count,
        nonterminal_cleanup_job_count,
    )
    if profile.post_fired:
        if (
            prior_cleanup_job_id is None
            or prior_cleanup_job_id.casefold() != str(expected_prior_job_id).casefold()
            or prior_cleanup_job_status != POST_FIRED_PRIOR_JOB_STATUS
            or prior_cleanup_job_exception != POST_FIRED_PRIOR_JOB_EXCEPTION
            or target_resource_count != POST_FIRED_EXPECTED_TARGET_RESOURCE_COUNT
            or delete_activity_count != POST_FIRED_EXPECTED_DELETE_ACTIVITY_COUNT
            or nonterminal_cleanup_job_count
            != POST_FIRED_EXPECTED_NONTERMINAL_JOB_COUNT
        ):
            raise CleanupControlRecoveryError(
                "cleanup-post-fired-recovery-state-invalid"
            )
    elif any(value is not None for value in post_fired_inputs):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-post-fired-state-unexpected"
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
        schedule=profile.schedule,
        targetParameter=TARGET_PARAMETER,
        targetParameterValue=TARGET_GROUP,
        authorizationParameter=AUTHORIZATION_PARAMETER,
        authorizationParameterValue=True,
        authorizedAtUtc=_utc(observed),
        deadlineUtc=_utc(deadline),
        bindingId=profile.binding_id,
        bindingContractVersion=profile.binding_contract_version,
        runbookContentSha256=runbook_content_sha256,
        costCeilingUsdCents=COST_CEILING_CENTS,
        allowedOperations=(
            POST_FIRED_RECOVERY_ALLOWED_OPERATIONS
            if profile.post_fired
            else DEADLINE_RECOVERY_ALLOWED_OPERATIONS
        ),
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
        postFiredRecoveryPurpose=(
            POST_FIRED_RECOVERY_PURPOSE if profile.post_fired else None
        ),
        priorCleanupJobId=expected_prior_job_id,
        priorCleanupJobStatus=(
            POST_FIRED_PRIOR_JOB_STATUS if profile.post_fired else None
        ),
        priorCleanupJobException=(
            POST_FIRED_PRIOR_JOB_EXCEPTION if profile.post_fired else None
        ),
        priorCleanupJobCreatedAtUtc=(
            POST_FIRED_PRIOR_JOB_CREATED_AT_UTC if profile.post_fired else None
        ),
        deleteActivityStartUtc=(
            POST_FIRED_DELETE_ACTIVITY_START_UTC if profile.post_fired else None
        ),
        priorScheduleState=(
            POST_FIRED_PRIOR_SCHEDULE_STATE if profile.post_fired else None
        ),
        priorBindingState=(
            POST_FIRED_PRIOR_BINDING_STATE if profile.post_fired else None
        ),
        targetPreservationState=(
            POST_FIRED_TARGET_PRESERVATION_STATE if profile.post_fired else None
        ),
        replacementIdentityState=(
            POST_FIRED_REPLACEMENT_IDENTITY_STATE if profile.post_fired else None
        ),
        replacementAuthorityState=(
            POST_FIRED_REPLACEMENT_AUTHORITY_STATE if profile.post_fired else None
        ),
        expectedTargetResourceCount=(
            POST_FIRED_EXPECTED_TARGET_RESOURCE_COUNT if profile.post_fired else None
        ),
        expectedDeleteActivityCount=(
            POST_FIRED_EXPECTED_DELETE_ACTIVITY_COUNT if profile.post_fired else None
        ),
        expectedNonterminalCleanupJobCount=(
            POST_FIRED_EXPECTED_NONTERMINAL_JOB_COUNT if profile.post_fired else None
        ),
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
        bindingContractVersion=LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
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
        "bindingContractVersion": LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
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
    expected_prior_job_id = (
        f"{expected_replacement}/jobs/{POST_FIRED_PRIOR_JOB_NAME}"
        if profile.post_fired
        else None
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
        "schedule": profile.schedule,
        "targetParameter": TARGET_PARAMETER,
        "targetParameterValue": TARGET_GROUP,
        "authorizationParameter": AUTHORIZATION_PARAMETER,
        "authorizationParameterValue": True,
        "authorizedAtUtc": profile.observed_azure_utc,
        "deadlineUtc": profile.deadline_utc,
        "bindingId": profile.binding_id,
        "bindingContractVersion": profile.binding_contract_version,
        "costCeilingUsdCents": COST_CEILING_CENTS,
        "allowedOperations": (
            POST_FIRED_RECOVERY_ALLOWED_OPERATIONS
            if profile.post_fired
            else DEADLINE_RECOVERY_ALLOWED_OPERATIONS
        ),
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
        "postFiredRecoveryPurpose": (
            POST_FIRED_RECOVERY_PURPOSE if profile.post_fired else None
        ),
        "priorCleanupJobId": expected_prior_job_id,
        "priorCleanupJobStatus": (
            POST_FIRED_PRIOR_JOB_STATUS if profile.post_fired else None
        ),
        "priorCleanupJobException": (
            POST_FIRED_PRIOR_JOB_EXCEPTION if profile.post_fired else None
        ),
        "priorCleanupJobCreatedAtUtc": (
            POST_FIRED_PRIOR_JOB_CREATED_AT_UTC if profile.post_fired else None
        ),
        "deleteActivityStartUtc": (
            POST_FIRED_DELETE_ACTIVITY_START_UTC if profile.post_fired else None
        ),
        "priorScheduleState": (
            POST_FIRED_PRIOR_SCHEDULE_STATE if profile.post_fired else None
        ),
        "priorBindingState": (
            POST_FIRED_PRIOR_BINDING_STATE if profile.post_fired else None
        ),
        "targetPreservationState": (
            POST_FIRED_TARGET_PRESERVATION_STATE if profile.post_fired else None
        ),
        "replacementIdentityState": (
            POST_FIRED_REPLACEMENT_IDENTITY_STATE if profile.post_fired else None
        ),
        "replacementAuthorityState": (
            POST_FIRED_REPLACEMENT_AUTHORITY_STATE if profile.post_fired else None
        ),
        "expectedTargetResourceCount": (
            POST_FIRED_EXPECTED_TARGET_RESOURCE_COUNT if profile.post_fired else None
        ),
        "expectedDeleteActivityCount": (
            POST_FIRED_EXPECTED_DELETE_ACTIVITY_COUNT if profile.post_fired else None
        ),
        "expectedNonterminalCleanupJobCount": (
            POST_FIRED_EXPECTED_NONTERMINAL_JOB_COUNT if profile.post_fired else None
        ),
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
        or (profile.post_fired and deadline_observed_at <= prior_deadline)
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
    minimum_remaining_seconds = (
        CLEANUP_RECOVERY_V9_MINIMUM_REMAINING_SECONDS
        if authorization.authorizationVersion == CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION
        else POST_V7_FINAL_COMPLETION_MINIMUM_REMAINING_SECONDS
        if authorization.authorizationVersion
        == POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION
        else None
    )
    if (
        minimum_remaining_seconds is not None
        and (deadline - current).total_seconds() < minimum_remaining_seconds
    ):
        raise CleanupControlRecoveryError(
            "cleanup-deadline-recovery-completion-window-insufficient"
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
    post_fired_fields = {
        "postFiredRecoveryPurpose",
        "priorCleanupJobId",
        "priorCleanupJobStatus",
        "priorCleanupJobException",
        "priorCleanupJobCreatedAtUtc",
        "deleteActivityStartUtc",
        "priorScheduleState",
        "priorBindingState",
        "targetPreservationState",
        "replacementIdentityState",
        "replacementAuthorityState",
        "expectedTargetResourceCount",
        "expectedDeleteActivityCount",
        "expectedNonterminalCleanupJobCount",
    }
    post_fired = (
        value.get("authorizationVersion") == POST_FIRED_RECOVERY_AUTHORIZATION_VERSION
    )
    expected_fields = fields if post_fired else fields - post_fired_fields
    if set(value) != expected_fields:
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
        "expectedTargetResourceCount",
        "expectedDeleteActivityCount",
        "expectedNonterminalCleanupJobCount",
    }
    required_string_fields = (
        string_fields if post_fired else string_fields - post_fired_fields
    )
    if any(not isinstance(value.get(field), str) for field in required_string_fields):
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
    post_fired_counts = (
        value.get("expectedTargetResourceCount"),
        value.get("expectedDeleteActivityCount"),
        value.get("expectedNonterminalCleanupJobCount"),
    )
    if post_fired and any(
        not isinstance(item, int) or isinstance(item, bool)
        for item in post_fired_counts
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
        postFiredRecoveryPurpose=cast(
            str | None, value.get("postFiredRecoveryPurpose")
        ),
        priorCleanupJobId=cast(str | None, value.get("priorCleanupJobId")),
        priorCleanupJobStatus=cast(str | None, value.get("priorCleanupJobStatus")),
        priorCleanupJobException=cast(
            str | None, value.get("priorCleanupJobException")
        ),
        priorCleanupJobCreatedAtUtc=cast(
            str | None, value.get("priorCleanupJobCreatedAtUtc")
        ),
        deleteActivityStartUtc=cast(str | None, value.get("deleteActivityStartUtc")),
        priorScheduleState=cast(str | None, value.get("priorScheduleState")),
        priorBindingState=cast(str | None, value.get("priorBindingState")),
        targetPreservationState=cast(str | None, value.get("targetPreservationState")),
        replacementIdentityState=cast(
            str | None, value.get("replacementIdentityState")
        ),
        replacementAuthorityState=cast(
            str | None, value.get("replacementAuthorityState")
        ),
        expectedTargetResourceCount=cast(
            int | None, value.get("expectedTargetResourceCount")
        ),
        expectedDeleteActivityCount=cast(
            int | None, value.get("expectedDeleteActivityCount")
        ),
        expectedNonterminalCleanupJobCount=cast(
            int | None, value.get("expectedNonterminalCleanupJobCount")
        ),
    )


def cleanup_control_reprovision_authorization_from_mapping(
    value: JsonValue,
) -> CleanupControlReprovisionAuthorization:
    if not isinstance(value, dict):
        raise CleanupControlRecoveryError("cleanup-reprovision-authorization-malformed")
    fields = set(CleanupControlReprovisionAuthorization.__dataclass_fields__)
    if set(value) != fields:
        raise CleanupControlRecoveryError("cleanup-reprovision-authorization-malformed")
    operations = value.get("allowedOperations")
    if not isinstance(operations, list) or any(
        not isinstance(item, str) for item in operations
    ):
        raise CleanupControlRecoveryError("cleanup-reprovision-authorization-malformed")
    string_fields = fields - {
        "allowedOperations",
        "authorizationParameterValue",
        "bindingGeneration",
        "costCeilingUsdCents",
        "imageRestorationAuthorized",
        "maximumScannerProofExecutions",
        "scannerProofAuthorized",
    }
    if any(not isinstance(value.get(field), str) for field in string_fields):
        raise CleanupControlRecoveryError("cleanup-reprovision-authorization-malformed")
    authorization_value = value.get("authorizationParameterValue")
    binding_generation = value.get("bindingGeneration")
    cost_ceiling = value.get("costCeilingUsdCents")
    image_restoration_authorized = value.get("imageRestorationAuthorized")
    maximum_scanner_proof_executions = value.get("maximumScannerProofExecutions")
    scanner_proof_authorized = value.get("scannerProofAuthorized")
    if (
        not isinstance(authorization_value, bool)
        or not isinstance(binding_generation, int)
        or isinstance(binding_generation, bool)
        or not isinstance(cost_ceiling, int)
        or isinstance(cost_ceiling, bool)
        or not isinstance(image_restoration_authorized, bool)
        or not isinstance(maximum_scanner_proof_executions, int)
        or isinstance(maximum_scanner_proof_executions, bool)
        or not isinstance(scanner_proof_authorized, bool)
    ):
        raise CleanupControlRecoveryError("cleanup-reprovision-authorization-malformed")
    return CleanupControlReprovisionAuthorization(
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
        authorizationExpiresAtUtc=cast(str, value["authorizationExpiresAtUtc"]),
        bindingGeneration=binding_generation,
        corruptedSchedule=cast(str, value["corruptedSchedule"]),
        priorBindingId=cast(str, value["priorBindingId"]),
        priorDeadlineUtc=cast(str, value["priorDeadlineUtc"]),
        priorSchedule=cast(str, value["priorSchedule"]),
        priorRunbookContentSha256=cast(str, value["priorRunbookContentSha256"]),
        replacementPrincipalId=cast(str, value["replacementPrincipalId"]),
        replacementRoleAssignmentId=cast(str, value["replacementRoleAssignmentId"]),
        replacementLocation=cast(str, value["replacementLocation"]),
        completedCleanupJobId=cast(str, value["completedCleanupJobId"]),
        completedCleanupJobStatus=cast(str, value["completedCleanupJobStatus"]),
        priorGenerationSourceCommit=cast(str, value["priorGenerationSourceCommit"]),
        priorLifecycleBindingSha256=cast(str, value["priorLifecycleBindingSha256"]),
        priorManifestSha256=cast(str, value["priorManifestSha256"]),
        deletedKeyVaultId=cast(str, value["deletedKeyVaultId"]),
        deletedKeyVaultName=cast(str, value["deletedKeyVaultName"]),
        deletedKeyVaultLocation=cast(str, value["deletedKeyVaultLocation"]),
        deletedKeyVaultAtUtc=cast(str, value["deletedKeyVaultAtUtc"]),
        deletedKeyVaultAction=cast(str, value["deletedKeyVaultAction"]),
        deletedWorkspaceId=cast(str, value["deletedWorkspaceId"]),
        deletedWorkspaceName=cast(str, value["deletedWorkspaceName"]),
        deletedWorkspaceLocation=cast(str, value["deletedWorkspaceLocation"]),
        deletedWorkspaceAtUtc=cast(str, value["deletedWorkspaceAtUtc"]),
        deletedWorkspaceCustomerId=cast(str, value["deletedWorkspaceCustomerId"]),
        deletedWorkspaceAction=cast(str, value["deletedWorkspaceAction"]),
        reprovisionAction=cast(str, value["reprovisionAction"]),
        foundationStage=cast(str, value["foundationStage"]),
        storageAccountId=cast(str, value["storageAccountId"]),
        logAnalyticsWorkspaceId=cast(str, value["logAnalyticsWorkspaceId"]),
        workerIdentityId=cast(str, value["workerIdentityId"]),
        privateLinkScopeId=cast(str, value["privateLinkScopeId"]),
        monitorPrivateEndpointId=cast(str, value["monitorPrivateEndpointId"]),
        imageRestorationAuthorized=image_restoration_authorized,
        scannerProofAuthorized=scanner_proof_authorized,
        maximumScannerProofExecutions=maximum_scanner_proof_executions,
    )


def cleanup_control_recovery_authorization_from_mapping(
    value: JsonValue,
) -> CleanupControlRecoveryAuthorization:
    if (
        isinstance(value, dict)
        and value.get("authorizationVersion")
        == POST_CLEANUP_REPROVISION_AUTHORIZATION_VERSION
    ):
        return cleanup_control_reprovision_authorization_from_mapping(value)
    if isinstance(value, dict) and value.get("authorizationVersion") in {
        DEADLINE_RECOVERY_AUTHORIZATION_VERSION,
        DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
        DEADLINE_CONTINUATION_AUTHORIZATION_VERSION,
        DEADLINE_COMPLETION_AUTHORIZATION_VERSION,
        POST_FIRED_RECOVERY_AUTHORIZATION_VERSION,
        GENERATION_FOUR_DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
        GENERATION_FOUR_COMPLETION_EXTENSION_AUTHORIZATION_VERSION,
        POST_V7_FINAL_COMPLETION_EXTENSION_AUTHORIZATION_VERSION,
        CLEANUP_RECOVERY_V9_AUTHORIZATION_VERSION,
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
        _reprovision_authorization_body(authorization)
        if isinstance(authorization, CleanupControlReprovisionAuthorization)
        else _deadline_recovery_authorization_body(authorization)
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
    if isinstance(authorization, CleanupControlReprovisionAuthorization):
        return adapter.execute_reprovision(
            authorization=authorization,
            receipt_directory=receipt_directory,
            expected_repository_head=expected_repository_head,
        )
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
