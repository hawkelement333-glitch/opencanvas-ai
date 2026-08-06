"""Production execution adapter for the narrow cleanup-control recovery grant."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn

from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
)
from preflight.milestone_7_7.cleanup_control_recovery import (
    CLEANUP_GROUP,
    CORRUPTED_AUTOMATION_ACCOUNT,
    CleanupControlRecoveryAuthorization,
    validate_cleanup_control_recovery_authorization,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    cleanup_runbook_sha256,
    load_managed_binding_contract,
    managed_binding_integrity_sha256,
)

RECEIPT_VERSION: Final = "mobius.milestone-7.7.cleanup-control-recovery-receipt.v1"
RECEIPT_FILE: Final = "cleanup-control-recovery.receipt.json"
RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-recovery-receipt/v1\0"
)
EXPECTED_COST_USD_CENTS: Final = 1
CORRUPTED_ROLE_PROPAGATION_SECONDS: Final = 120.0
CORRUPTED_ROLE_POLL_SECONDS: Final = 5.0
WEBHOOK_API_VERSION: Final = "2024-10-23"
TERMINAL_AUTOMATION_JOB_STATES: Final = frozenset({"Completed", "Failed", "Stopped"})


class CleanupControlRecoveryExecutionError(RuntimeError):
    """Raised when the narrow production execution boundary cannot be proved."""


def _fail(code: str) -> NoReturn:
    raise CleanupControlRecoveryExecutionError(code)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deadline(authorization: CleanupControlRecoveryAuthorization) -> datetime:
    try:
        return datetime.strptime(
            authorization.deadlineUtc, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
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


def _automation_collection(
    *,
    authorization: CleanupControlRecoveryAuthorization,
    subscription_id: str,
    collection: str,
    query: str,
) -> list[JsonValue]:
    return _automation_account_collection(
        account_id=authorization.corruptedAutomationAccountId,
        collection=collection,
        query=query,
    )


def _automation_account_collection(
    *,
    account_id: str,
    collection: str,
    query: str,
) -> list[JsonValue]:
    api_version = (
        WEBHOOK_API_VERSION
        if collection == "webhooks"
        else lifecycle.AUTOMATION_API_VERSION
    )
    value = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (
                f"https://management.azure.com{account_id}/{collection}"
                f"?api-version={api_version}"
            ),
            "--query",
            f"{{nextLink:nextLink,value:{query}}}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if (
        not isinstance(value, dict)
        or set(value) != {"nextLink", "value"}
        or value["nextLink"] not in (None, "")
        or not isinstance(value["value"], list)
    ):
        _fail("cleanup-recovery-corrupted-graph-output-malformed")
    return value["value"]


def _corrupted_role_rows(
    authorization: CleanupControlRecoveryAuthorization,
    subscription_id: str,
) -> list[dict[str, str]]:
    value = lifecycle._run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            authorization.corruptedPrincipalId,
            "--all",
            "--subscription",
            subscription_id,
            "--query",
            (
                "[].{id:id,principalId:principalId,"
                "roleDefinitionId:roleDefinitionId,scope:scope}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("cleanup-recovery-corrupted-role-output-malformed")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "principalId",
            "roleDefinitionId",
            "scope",
        }:
            _fail("cleanup-recovery-corrupted-role-output-malformed")
        if any(not isinstance(item[key], str) for key in item):
            _fail("cleanup-recovery-corrupted-role-output-malformed")
        rows.append({key: str(item[key]).casefold() for key in item})
    return rows


def _expected_corrupted_role_row(
    authorization: CleanupControlRecoveryAuthorization,
) -> dict[str, str]:
    role_definition_id = (
        f"/subscriptions/{authorization.subscriptionId}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{authorization.roleDefinitionId}"
    )
    return {
        "id": authorization.corruptedRoleAssignmentId.casefold(),
        "principalId": authorization.corruptedPrincipalId.casefold(),
        "roleDefinitionId": role_definition_id.casefold(),
        "scope": authorization.roleScope.casefold(),
    }


def _verify_corrupted_evidence_graph(
    authorization: CleanupControlRecoveryAuthorization,
    subscription_id: str,
    *,
    assignment_required: bool,
) -> None:
    account = lifecycle._run(
        (
            "az",
            "automation",
            "account",
            "show",
            "--resource-group",
            CLEANUP_GROUP,
            "--automation-account-name",
            CORRUPTED_AUTOMATION_ACCOUNT,
            "--subscription",
            subscription_id,
            "--query",
            (
                "{id:id,identityType:identity.type,"
                "localAuthDisabled:disableLocalAuth,location:location,"
                "principalId:identity.principalId,"
                "publicNetworkAccess:publicNetworkAccess,state:state}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected_account: dict[str, JsonValue] = {
        "id": authorization.corruptedAutomationAccountId,
        "identityType": "SystemAssigned",
        "localAuthDisabled": True,
        "location": lifecycle.CLEANUP_LOCATION,
        "principalId": authorization.corruptedPrincipalId,
        "publicNetworkAccess": False,
        "state": "Ok",
    }
    if not isinstance(account, dict) or {
        key: value.casefold() if key == "id" and isinstance(value, str) else value
        for key, value in account.items()
    } != {
        key: value.casefold() if key == "id" and isinstance(value, str) else value
        for key, value in expected_account.items()
    }:
        _fail("cleanup-recovery-corrupted-account-drift")

    runbook_id = (
        f"{authorization.corruptedAutomationAccountId}/runbooks/{authorization.runbook}"
    )
    runbooks = _automation_collection(
        authorization=authorization,
        subscription_id=subscription_id,
        collection="runbooks",
        query=(
            "value[].{id:id,name:name,runbookType:properties.runbookType,"
            "state:properties.state}"
        ),
    )
    if len(runbooks) != 1 or not isinstance(runbooks[0], dict):
        _fail("cleanup-recovery-corrupted-runbook-drift")
    observed_runbook = runbooks[0]
    if (
        set(observed_runbook) != {"id", "name", "runbookType", "state"}
        or not isinstance(observed_runbook.get("id"), str)
        or str(observed_runbook["id"]).casefold() != runbook_id.casefold()
        or observed_runbook.get("name") != authorization.runbook
        or observed_runbook.get("runbookType") != "PowerShell72"
        or observed_runbook.get("state") != "Published"
    ):
        _fail("cleanup-recovery-corrupted-runbook-drift")
    content = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (
                f"https://management.azure.com{runbook_id}/content"
                f"?api-version={lifecycle.AUTOMATION_API_VERSION}"
            ),
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        require_text=True,
    )
    if (
        not isinstance(content, str)
        or cleanup_runbook_sha256(content) != authorization.runbookContentSha256
    ):
        _fail("cleanup-recovery-corrupted-runbook-content-drift")

    schedule_id = f"{authorization.corruptedAutomationAccountId}/schedules/{authorization.schedule}"
    schedules = _automation_collection(
        authorization=authorization,
        subscription_id=subscription_id,
        collection="schedules",
        query="value[].{id:id,name:name}",
    )
    if (
        len(schedules) != 1
        or not isinstance(schedules[0], dict)
        or set(schedules[0]) != {"id", "name"}
        or not isinstance(schedules[0].get("id"), str)
        or str(schedules[0]["id"]).casefold() != schedule_id.casefold()
        or schedules[0].get("name") != authorization.schedule
    ):
        _fail("cleanup-recovery-corrupted-schedule-drift")

    empty_collections = {
        "jobSchedules": (
            "value[].{id:id,jobScheduleId:properties.jobScheduleId,"
            "runbook:properties.runbook.name,schedule:properties.schedule.name}"
        ),
        "webhooks": "value[].{id:id,name:name}",
        "variables": "value[].{id:id,name:name}",
        "credentials": "value[].{id:id,name:name}",
        "certificates": "value[].{id:id,name:name}",
        "connections": "value[].{id:id,name:name}",
        "hybridRunbookWorkerGroups": "value[].{id:id,name:name}",
        "sourceControls": "value[].{id:id,name:name}",
    }
    for collection, query in empty_collections.items():
        if _automation_collection(
            authorization=authorization,
            subscription_id=subscription_id,
            collection=collection,
            query=query,
        ):
            _fail("cleanup-recovery-corrupted-execution-edge-present")

    jobs = _automation_collection(
        authorization=authorization,
        subscription_id=subscription_id,
        collection="jobs",
        query="value[].{id:id,status:properties.status,runbook:properties.runbook.name}",
    )
    job_prefix = f"{authorization.corruptedAutomationAccountId}/jobs/".casefold()
    for job in jobs:
        if (
            not isinstance(job, dict)
            or set(job) != {"id", "runbook", "status"}
            or not isinstance(job.get("id"), str)
            or not str(job["id"]).casefold().startswith(job_prefix)
            or job.get("runbook") != authorization.runbook
            or job.get("status") not in TERMINAL_AUTOMATION_JOB_STATES
        ):
            _fail("cleanup-recovery-corrupted-job-not-terminal")

    role_rows = _corrupted_role_rows(authorization, subscription_id)
    expected_roles = (
        [_expected_corrupted_role_row(authorization)] if assignment_required else []
    )
    if role_rows != expected_roles:
        _fail("cleanup-recovery-corrupted-role-drift")


def _revoke_corrupted_role_assignment(
    authorization: CleanupControlRecoveryAuthorization,
    subscription_id: str,
) -> None:
    try:
        lifecycle._delete_assignment(
            subscription_id,
            authorization.corruptedRoleAssignmentId,
        )
    except lifecycle.AzureCommandError:
        # The delete response can be lost after Azure commits it.  Reconcile the
        # exact assignment rather than issuing a second delete.
        pass
    deadline = time.monotonic() + CORRUPTED_ROLE_PROPAGATION_SECONDS
    expected = [_expected_corrupted_role_row(authorization)]
    while True:
        rows = _corrupted_role_rows(authorization, subscription_id)
        if not rows:
            return
        if rows != expected:
            _fail("cleanup-recovery-corrupted-role-drift")
        if time.monotonic() >= deadline:
            _fail("cleanup-recovery-corrupted-role-revocation-unproved")
        time.sleep(CORRUPTED_ROLE_POLL_SECONDS)


def _cleanup_resource_group_inventory(subscription_id: str) -> frozenset[str]:
    scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{CLEANUP_GROUP}/providers/"
    ).casefold()
    value = lifecycle._run(
        (
            "az",
            "resource",
            "list",
            "--resource-group",
            CLEANUP_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id,type:type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("cleanup-recovery-resource-inventory-malformed")
    resources: set[str] = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "type"}
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("type"), str)
        ):
            _fail("cleanup-recovery-resource-inventory-malformed")
        normalized_id = str(item["id"]).casefold()
        if not normalized_id.startswith(scope):
            _fail("cleanup-recovery-resource-inventory-scope-drift")
        relative = normalized_id[len(scope) :]
        normalized_type = str(item["type"]).casefold()
        if normalized_type == "microsoft.authorization/roleassignments":
            continue
        type_parts = normalized_type.split("/")
        relative_parts = relative.split("/")
        if (
            len(type_parts) < 2
            or len(relative_parts) != (2 * len(type_parts)) - 1
            or relative_parts[0] != type_parts[0]
            or any(
                relative_parts[(index * 2) - 1] != type_parts[index]
                for index in range(1, len(type_parts))
            )
        ):
            _fail("cleanup-recovery-resource-inventory-type-drift")
        resources.add(relative)

    account_root = (
        "microsoft.automation/automationaccounts/"
        f"{CORRUPTED_AUTOMATION_ACCOUNT.casefold()}"
    )
    replacement_root = (
        "microsoft.automation/automationaccounts/"
        f"{lifecycle.AUTOMATION_ACCOUNT.casefold()}"
    )
    for relative_account in (account_root, replacement_root):
        if relative_account not in resources:
            continue
        account_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{CLEANUP_GROUP}/"
            f"providers/{relative_account}"
        )
        for collection in (
            "runbooks",
            "schedules",
            "jobSchedules",
            "webhooks",
            "variables",
            "credentials",
            "certificates",
            "connections",
            "hybridRunbookWorkerGroups",
            "sourceControls",
        ):
            rows = _automation_account_collection(
                account_id=account_id,
                collection=collection,
                query="value[].{id:id}",
            )
            child_prefix = f"{account_id}/{collection}/".casefold()
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or set(row) != {"id"}
                    or not isinstance(row.get("id"), str)
                    or not str(row["id"]).casefold().startswith(child_prefix)
                ):
                    _fail("cleanup-recovery-resource-inventory-malformed")
                child_id = str(row["id"]).casefold()
                resources.add(child_id[len(scope) :])
    return frozenset(resources)


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
    corrupted_account = f"microsoft.automation/automationaccounts/{CORRUPTED_AUTOMATION_ACCOUNT.casefold()}"
    corrupted_runbook = (
        f"{corrupted_account}/runbooks/{authorization.runbook.casefold()}"
    )
    corrupted_schedule = (
        f"{corrupted_account}/schedules/{authorization.schedule.casefold()}"
    )
    runbook = f"{account}/runbooks/{authorization.runbook.casefold()}"
    schedule = f"{account}/schedules/{authorization.schedule.casefold()}"
    binding = f"{account}/jobschedules/{authorization.bindingId.casefold()}"
    deployments = {
        "microsoft.resources/deployments/mobius77-cleanup-control",
        "microsoft.resources/deployments/mobius77-cleanup-job-binding",
    }
    permitted = {
        account,
        corrupted_account,
        corrupted_runbook,
        corrupted_schedule,
        runbook,
        schedule,
        binding,
        *deployments,
    }
    if resources - permitted:
        _fail("cleanup-recovery-resource-inventory-drift")
    account_rows = {
        item
        for item in resources
        if item.startswith("microsoft.automation/automationaccounts/")
        and item.count("/") == 2
        and item != corrupted_account
    }
    schedule_rows = {
        item for item in resources if item.startswith(f"{account}/schedules/")
    }
    binding_rows = {
        item for item in resources if item.startswith(f"{account}/jobschedules/")
    }
    if len(account_rows) > 1 or len(schedule_rows) > 1 or len(binding_rows) > 1:
        _fail("cleanup-recovery-duplicate-resource")
    if require_complete and not {account, runbook, schedule, binding}.issubset(
        resources
    ):
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
        initial_resources = _cleanup_resource_group_inventory(subscription_id)
        _validate_cleanup_inventory(
            initial_resources,
            authorization=authorization,
            require_complete=False,
        )
        _verify_corrupted_evidence_graph(
            authorization,
            subscription_id,
            assignment_required=True,
        )

        _claim_authorization(
            authorization=authorization,
            receipt_directory=receipt_directory,
            now_utc=now,
        )
        _revoke_corrupted_role_assignment(authorization, subscription_id)
        _verify_corrupted_evidence_graph(
            authorization,
            subscription_id,
            assignment_required=False,
        )
        cleanup_at = _deadline(authorization)
        deployment_binding = _deployment_binding(authorization, contract)
        with tempfile.TemporaryDirectory(
            prefix="mobius77-cleanup-recovery-"
        ) as directory:
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
            principal_id = lifecycle._verify_cleanup_control(
                subscription_id, cleanup_at
            )
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
        proved_principal_id = lifecycle._verify_cleanup_control(
            subscription_id, cleanup_at
        )
        if proved_principal_id.casefold() != principal_id.casefold():
            _fail("cleanup-recovery-principal-reconciliation-drift")
        lifecycle._verify_cleanup_target_role(
            subscription_id,
            proved_principal_id,
            authorization.roleDefinitionId,
        )
        final_resources = _cleanup_resource_group_inventory(subscription_id)
        _validate_cleanup_inventory(
            final_resources,
            authorization=authorization,
            require_complete=True,
        )
        return {
            "authorization-consumed": True,
            "authorization-integrity-sha256": (
                authorization.authorizationIntegritySha256
            ),
            "cleanup-executable": True,
            "cleanup-parameter": authorization.authorizationParameter,
            "cleanup-parameter-value": authorization.authorizationParameterValue,
            "principal-fingerprint-sha256": hashlib.sha256(
                proved_principal_id.casefold().encode("ascii")
            ).hexdigest(),
            "replacement-automation-account": (
                authorization.replacementAutomationAccount
            ),
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
