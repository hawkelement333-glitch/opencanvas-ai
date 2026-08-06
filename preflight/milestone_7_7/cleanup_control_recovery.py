"""Narrow, image-independent authority for cleanup-control recovery only."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from performance.milestone_7_7.framework import canonical_bytes, integrity_sha256
from preflight.milestone_7_7.managed_binding_contracts import (
    ACTIVE_CLEANUP_BINDING_ID,
    CLEANUP_AUTOMATION_ACCOUNT,
    CLEANUP_BINDING_CONTRACT_VERSION,
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


class CleanupControlRecoveryError(ValueError):
    """Raised when a recovery authorization would expand its exact scope."""


@dataclass(frozen=True)
class CleanupControlRecoveryAuthorization:
    authorizationVersion: str
    repositoryHead: str
    subscriptionId: str
    cleanupResourceGroupId: str
    corruptedAutomationAccountId: str
    replacementAutomationAccount: str
    replacementAutomationAccountId: str
    targetResourceGroupId: str
    roleDefinitionId: str
    roleScope: str
    runbook: str
    schedule: str
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


def build_cleanup_control_recovery_authorization(
    *,
    repository_head: str,
    subscription_id: str,
    cleanup_resource_group_id: str,
    corrupted_automation_account_id: str,
    replacement_automation_account_id: str,
    target_resource_group_id: str,
    runbook_content_sha256: str,
    now_utc: datetime,
) -> CleanupControlRecoveryAuthorization:
    if len(repository_head) != 40 or any(
        c not in "0123456789abcdef" for c in repository_head
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-repository-head-invalid")
    expected_suffix = f"/resourceGroups/{CLEANUP_GROUP}/providers/Microsoft.Automation/automationAccounts/{CLEANUP_AUTOMATION_ACCOUNT}"
    if not replacement_automation_account_id.casefold().endswith(
        expected_suffix.casefold()
    ):
        raise CleanupControlRecoveryError(
            "cleanup-recovery-replacement-account-scope-invalid"
        )
    target_suffix = f"/resourceGroups/{TARGET_GROUP}"
    if not target_resource_group_id.casefold().endswith(target_suffix.casefold()):
        raise CleanupControlRecoveryError("cleanup-recovery-target-scope-invalid")
    if (
        CLEANUP_AUTOMATION_ACCOUNT.casefold()
        in corrupted_automation_account_id.casefold()
    ):
        raise CleanupControlRecoveryError("cleanup-recovery-corrupted-account-invalid")
    role_scope = target_resource_group_id
    body = {
        "authorizationVersion": AUTHORIZATION_VERSION,
        "repositoryHead": repository_head,
        "subscriptionId": subscription_id,
        "cleanupResourceGroupId": cleanup_resource_group_id,
        "corruptedAutomationAccountId": corrupted_automation_account_id,
        "replacementAutomationAccount": CLEANUP_AUTOMATION_ACCOUNT,
        "replacementAutomationAccountId": replacement_automation_account_id,
        "targetResourceGroupId": target_resource_group_id,
        "roleDefinitionId": ROLE_DEFINITION_ID,
        "roleScope": role_scope,
        "runbook": RUNBOOK,
        "schedule": SCHEDULE,
        "deadlineUtc": DEADLINE_UTC,
        "bindingId": ACTIVE_CLEANUP_BINDING_ID,
        "bindingContractVersion": CLEANUP_BINDING_CONTRACT_VERSION,
        "runbookContentSha256": runbook_content_sha256,
        "costCeilingUsdCents": COST_CEILING_CENTS,
        "allowedOperations": [
            "create-replacement-automation-account",
            "assign-exact-cleanup-role",
            "publish-guarded-runbook",
            "create-one-time-schedule",
            "create-exact-job-schedule-binding",
            "verify-cleanup-executable",
        ],
        "authorizedAtUtc": _utc(now_utc),
    }
    integrity = integrity_sha256(body, AUTHORIZATION_DOMAIN)
    return CleanupControlRecoveryAuthorization(
        **{
            **{key: value for key, value in body.items() if key != "authorizedAtUtc"},
            "allowedOperations": tuple(body["allowedOperations"]),
        },
        authorizationIntegritySha256=integrity,
    )


def write_cleanup_control_recovery_authorization(
    path: Path, authorization: CleanupControlRecoveryAuthorization
) -> None:
    if path.resolve().is_relative_to(Path.cwd().resolve()):
        raise CleanupControlRecoveryError(
            "cleanup-recovery-authorization-inside-repository"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(asdict(authorization)))
