"""Production execution adapter for the narrow cleanup-control recovery grant."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn

from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue, canonical_bytes, integrity_sha256
from preflight.milestone_7_7.cleanup_control_recovery import (
    CLEANUP_GROUP,
    CORRUPTED_AUTOMATION_ACCOUNT,
    CleanupControlRecoveryAuthorization,
    validate_cleanup_control_recovery_authorization,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    load_managed_binding_contract,
    managed_binding_integrity_sha256,
)

RECEIPT_VERSION: Final = "mobius.milestone-7.7.cleanup-control-recovery-receipt.v1"
RECEIPT_FILE: Final = "cleanup-control-recovery.receipt.json"
RECEIPT_DOMAIN: Final = b"solarplexus-mobius/milestone-7.7/cleanup-control-recovery-receipt/v1\0"
EXPECTED_COST_USD_CENTS: Final = 1


class CleanupControlRecoveryExecutionError(RuntimeError):
    """Raised when the narrow production execution boundary cannot be proved."""


def _fail(code: str) -> NoReturn:
    raise CleanupControlRecoveryExecutionError(code)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deadline(authorization: CleanupControlRecoveryAuthorization) -> datetime:
    try:
        return datetime.strptime(authorization.deadlineUtc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        _fail("cleanup-recovery-deadline-invalid")


def _outside_repository(path: Path) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        _fail("cleanup-recovery-receipts-inside-repository")
    return resolved


def _claim_authorization(
    *,
    authorization: CleanupControlRecoveryAuthorization,
    receipt_directory: Path,
    now_utc: datetime,
) -> Path:
    directory = _outside_repository(receipt_directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECEIPT_FILE
    body: dict[str, JsonValue] = {
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "claimedAtUtc": _format_utc(now_utc),
        "receiptVersion": RECEIPT_VERSION,
        "replayDecision": "deny",
        "repositoryHead": authorization.repositoryHead,
    }
    receipt: dict[str, JsonValue] = {
        **body,
        "receiptIntegritySha256": integrity_sha256(body, RECEIPT_DOMAIN),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("cleanup-recovery-authorization-already-consumed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("cleanup-recovery-receipt-write-failed")
    return path


def _validate_contract_mapping(
    authorization: CleanupControlRecoveryAuthorization,
    contract: Mapping[str, JsonValue],
) -> None:
    cleanup = contract.get("cleanupExecution")
    rbac = contract.get("rbac")
    if not isinstance(cleanup, dict) or not isinstance(rbac, dict):
        _fail("cleanup-recovery-managed-binding-contract-malformed")
    expected_cleanup = {
        "activeBindingId": authorization.bindingId,
        "authorizationParameter": authorization.authorizationParameter,
        "authorizationValue": authorization.authorizationParameterValue,
        "bindingContractVersion": authorization.bindingContractVersion,
        "cleanupContributorRoleDefinitionId": authorization.roleDefinitionId,
        "deadlineUtc": authorization.deadlineUtc,
        "publishedContentSha256": authorization.runbookContentSha256,
        "targetParameter": authorization.targetParameter,
        "targetResourceGroup": authorization.targetParameterValue,
    }
    if any(cleanup.get(key) != value for key, value in expected_cleanup.items()):
        _fail("cleanup-recovery-managed-binding-contract-drift")
    if rbac.get("cleanupContributorRoleDefinitionId") != authorization.roleDefinitionId:
        _fail("cleanup-recovery-role-contract-drift")


def _deployment_binding(
    authorization: CleanupControlRecoveryAuthorization,
    contract: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "authorizationId": (
            f"cleanup-control-recovery-{authorization.authorizationIntegritySha256[:32]}"
        ),
        "ledgerIntegritySha256": authorization.authorizationIntegritySha256,
        "managedBindingIntegritySha256": managed_binding_integrity_sha256(contract),
        "repositoryHead": authorization.repositoryHead,
    }


def _validate_cleanup_inventory(
    resources: frozenset[str],
    *,
    authorization: CleanupControlRecoveryAuthorization,
    require_complete: bool,
) -> None:
    account = (
        "microsoft.automation/automationaccounts/"
        f"{authorization.replacementAutomationAccount.casefold()}"
    )
    corrupted_account = (
        f"microsoft.automation/automationaccounts/{CORRUPTED_AUTOMATION_ACCOUNT.casefold()}"
    )
    runbook = f"{account}/runbooks/{authorization.runbook.casefold()}"
    schedule = f"{account}/schedules/{authorization.schedule.casefold()}"
    binding = f"{account}/jobschedules/{authorization.bindingId.casefold()}"
    deployments = {
        "microsoft.resources/deployments/mobius77-cleanup-control",
        "microsoft.resources/deployments/mobius77-cleanup-job-binding",
    }
    permitted = {account, corrupted_account, runbook, schedule, binding, *deployments}
    if resources - permitted:
        _fail("cleanup-recovery-resource-inventory-drift")
    account_rows = {
        item
        for item in resources
        if item.startswith("microsoft.automation/automationaccounts/")
        and item.count("/") == 2
        and item != corrupted_account
    }
    schedule_rows = {item for item in resources if "/schedules/" in item}
    binding_rows = {item for item in resources if "/jobschedules/" in item}
    if len(account_rows) > 1 or len(schedule_rows) > 1 or len(binding_rows) > 1:
        _fail("cleanup-recovery-duplicate-resource")
    if require_complete and not {account, runbook, schedule, binding}.issubset(resources):
        _fail("cleanup-recovery-resource-proof-incomplete")


class ProductionCleanupControlRecoveryAdapter:
    """Map one typed recovery grant to the existing cleanup-only Azure stages."""

    def __init__(self, *, clock: Callable[[], datetime] = lifecycle._utc_now) -> None:
        self._clock = clock

    def execute(
        self,
        *,
        authorization: CleanupControlRecoveryAuthorization,
        receipt_directory: Path,
        expected_repository_head: str,
    ) -> dict[str, JsonValue]:
        now = self._clock().astimezone(UTC).replace(microsecond=0)
        validate_cleanup_control_recovery_authorization(
            authorization,
            expected_repository_head=expected_repository_head,
            now_utc=now,
        )
        lifecycle._verify_repository_state(expected_repository_head)
        subscription_id = lifecycle._account_binding(now)
        if subscription_id != authorization.subscriptionId:
            _fail("cleanup-recovery-subscription-mismatch")
        if not lifecycle._group_exists(subscription_id, CLEANUP_GROUP):
            _fail("cleanup-recovery-cleanup-resource-group-missing")

        contract = load_managed_binding_contract()
        _validate_contract_mapping(authorization, contract)
        initial_resources = lifecycle._resource_group_inventory(
            subscription_id=subscription_id,
            group=CLEANUP_GROUP,
        )
        _validate_cleanup_inventory(
            initial_resources,
            authorization=authorization,
            require_complete=False,
        )
        corrupted = (
            f"microsoft.automation/automationaccounts/{CORRUPTED_AUTOMATION_ACCOUNT.casefold()}"
        )
        if initial_resources == frozenset({corrupted}):
            lifecycle._verify_recovered_cleanup_seed_state(subscription_id)

        _claim_authorization(
            authorization=authorization,
            receipt_directory=receipt_directory,
            now_utc=now,
        )
        cleanup_at = _deadline(authorization)
        deployment_binding = _deployment_binding(authorization, contract)
        with tempfile.TemporaryDirectory(prefix="mobius77-cleanup-recovery-") as directory:
            template = Path(directory) / "main.json"
            lifecycle._compile_template(template)
            lifecycle._deploy_stage(
                template_path=template,
                subscription_id=subscription_id,
                ledger=deployment_binding,
                stage="cleanup-control",
                cleanup_at=cleanup_at,
                expected_cost=EXPECTED_COST_USD_CENTS,
                maximum_cost=authorization.costCeilingUsdCents,
            )
            lifecycle._configure_cleanup_runbook(subscription_id)
            lifecycle._deploy_stage(
                template_path=template,
                subscription_id=subscription_id,
                ledger=deployment_binding,
                stage="cleanup-job-binding",
                cleanup_at=cleanup_at,
                expected_cost=EXPECTED_COST_USD_CENTS,
                maximum_cost=authorization.costCeilingUsdCents,
            )
            principal_id = lifecycle._verify_cleanup_control(subscription_id, cleanup_at)
            lifecycle._deploy_stage(
                template_path=template,
                subscription_id=subscription_id,
                ledger=deployment_binding,
                stage="cleanup-binding",
                cleanup_at=cleanup_at,
                expected_cost=EXPECTED_COST_USD_CENTS,
                maximum_cost=authorization.costCeilingUsdCents,
            )

        lifecycle._verify_cleanup_target_role(
            subscription_id,
            principal_id,
            authorization.roleDefinitionId,
        )
        proved_principal_id = lifecycle._verify_cleanup_control(subscription_id, cleanup_at)
        if proved_principal_id.casefold() != principal_id.casefold():
            _fail("cleanup-recovery-principal-reconciliation-drift")
        lifecycle._verify_cleanup_target_role(
            subscription_id,
            proved_principal_id,
            authorization.roleDefinitionId,
        )
        final_resources = lifecycle._resource_group_inventory(
            subscription_id=subscription_id,
            group=CLEANUP_GROUP,
        )
        _validate_cleanup_inventory(
            final_resources,
            authorization=authorization,
            require_complete=True,
        )
        return {
            "authorization-consumed": True,
            "authorization-integrity-sha256": (authorization.authorizationIntegritySha256),
            "cleanup-executable": True,
            "cleanup-parameter": authorization.authorizationParameter,
            "cleanup-parameter-value": authorization.authorizationParameterValue,
            "principal-fingerprint-sha256": hashlib.sha256(
                proved_principal_id.casefold().encode("ascii")
            ).hexdigest(),
            "replacement-automation-account": (authorization.replacementAutomationAccount),
            "role-definition-id": authorization.roleDefinitionId,
            "role-scope": authorization.roleScope,
            "runbook": authorization.runbook,
            "schedule": authorization.schedule,
            "status": "cleanup-control-recovery-executable",
            "target-parameter": authorization.targetParameter,
            "target-parameter-value": authorization.targetParameterValue,
        }


__all__ = [
    "CleanupControlRecoveryExecutionError",
    "ProductionCleanupControlRecoveryAdapter",
]
