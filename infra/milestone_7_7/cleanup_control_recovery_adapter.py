"""Production execution adapter for the narrow cleanup-control recovery grant."""

from __future__ import annotations

import hashlib
import json
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
    CORRUPTED_RUNBOOK_CONTENT_SHA256,
    DEADLINE_EXTENSION_AUTHORIZATION_VERSION,
    POST_FIRED_RECOVERY_AUTHORIZATION_VERSION,
    CleanupControlDeadlineRecoveryAuthorization,
    CleanupControlRecoveryAuthorization,
    validate_cleanup_control_deadline_recovery_authorization,
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
RECEIPT_DOMAIN: Final = b"solarplexus-mobius/milestone-7.7/cleanup-control-recovery-receipt/v1\0"
DEADLINE_RECOVERY_RECEIPT_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery-receipt.v1"
)
DEADLINE_RECOVERY_RECEIPT_FILE: Final = "cleanup-control-deadline-recovery.receipt.json"
DEADLINE_RECOVERY_RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery-receipt/v1\0"
)
DEADLINE_EXTENSION_RECEIPT_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery-receipt.v2"
)
DEADLINE_EXTENSION_RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery-receipt/v2\0"
)
POST_FIRED_RECOVERY_RECEIPT_VERSION: Final = (
    "mobius.milestone-7.7.cleanup-control-deadline-recovery-receipt.v3"
)
POST_FIRED_RECOVERY_RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-control-deadline-recovery-receipt/v3\0"
)
EXPECTED_COST_USD_CENTS: Final = 1
CORRUPTED_ROLE_PROPAGATION_SECONDS: Final = 120.0
CORRUPTED_ROLE_POLL_SECONDS: Final = 5.0
WEBHOOK_API_VERSION: Final = "2024-10-23"
TERMINAL_AUTOMATION_JOB_STATES: Final = frozenset({"Completed", "Failed", "Stopped"})
DEADLINE_RECOVERY_PROPAGATION_SECONDS: Final = 120.0
DEADLINE_RECOVERY_POLL_SECONDS: Final = 5.0


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


def _claim_deadline_recovery_authorization(
    *,
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    receipt_directory: Path,
    now_utc: datetime,
) -> Path:
    directory = _outside_repository(receipt_directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DEADLINE_RECOVERY_RECEIPT_FILE
    if authorization.authorizationVersion == POST_FIRED_RECOVERY_AUTHORIZATION_VERSION:
        receipt_version, receipt_domain = (
            POST_FIRED_RECOVERY_RECEIPT_VERSION,
            POST_FIRED_RECOVERY_RECEIPT_DOMAIN,
        )
    elif authorization.authorizationVersion == DEADLINE_EXTENSION_AUTHORIZATION_VERSION:
        receipt_version, receipt_domain = (
            DEADLINE_EXTENSION_RECEIPT_VERSION,
            DEADLINE_EXTENSION_RECEIPT_DOMAIN,
        )
    else:
        receipt_version, receipt_domain = (
            DEADLINE_RECOVERY_RECEIPT_VERSION,
            DEADLINE_RECOVERY_RECEIPT_DOMAIN,
        )
    body: dict[str, JsonValue] = {
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "bindingId": authorization.bindingId,
        "claimedAtUtc": _format_utc(now_utc),
        "deadlineDerivationRule": authorization.deadlineDerivationRule,
        "deadlineObservedAtUtc": authorization.deadlineObservedAtUtc,
        "deadlineUtc": authorization.deadlineUtc,
        "priorBindingId": authorization.priorBindingId,
        "priorDeadlineUtc": authorization.priorDeadlineUtc,
        "receiptVersion": receipt_version,
        "replayDecision": "deny",
        "repositoryHead": authorization.repositoryHead,
    }
    if authorization.authorizationVersion == POST_FIRED_RECOVERY_AUTHORIZATION_VERSION:
        body.update(
            {
                "postFiredRecoveryPurpose": authorization.postFiredRecoveryPurpose,
                "priorCleanupJobId": authorization.priorCleanupJobId,
                "priorCleanupJobStatus": authorization.priorCleanupJobStatus,
                "priorCleanupJobException": authorization.priorCleanupJobException,
                "targetPreservationState": authorization.targetPreservationState,
            }
        )
    receipt: dict[str, JsonValue] = {
        **body,
        "receiptIntegritySha256": integrity_sha256(body, receipt_domain),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("cleanup-deadline-recovery-authorization-already-consumed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("cleanup-deadline-recovery-receipt-write-failed")
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
        "cleanupPrincipalFingerprintSha256": hashlib.sha256(
            b"mobius.azure.cleanup-principal.v1\0"
            + authorization.replacementPrincipalId.casefold().encode("ascii")
        ).hexdigest()
        if isinstance(authorization, CleanupControlDeadlineRecoveryAuthorization)
        else cleanup.get("cleanupPrincipalFingerprintSha256"),
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
        WEBHOOK_API_VERSION if collection == "webhooks" else lifecycle.AUTOMATION_API_VERSION
    )
    value = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (f"https://management.azure.com{account_id}/{collection}?api-version={api_version}"),
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
            ("[].{id:id,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}"),
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
    expected_runbook_hash: str | None = None,
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

    runbook_id = f"{authorization.corruptedAutomationAccountId}/runbooks/{authorization.runbook}"
    runbooks = _automation_collection(
        authorization=authorization,
        subscription_id=subscription_id,
        collection="runbooks",
        query=(
            "value[].{id:id,name:name,runbookType:properties.runbookType,state:properties.state}"
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
    if not isinstance(content, str) or cleanup_runbook_sha256(content) != (
        authorization.runbookContentSha256
        if expected_runbook_hash is None
        else expected_runbook_hash
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
    expected_roles = [_expected_corrupted_role_row(authorization)] if assignment_required else []
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
        f"microsoft.automation/automationaccounts/{CORRUPTED_AUTOMATION_ACCOUNT.casefold()}"
    )
    replacement_root = (
        f"microsoft.automation/automationaccounts/{lifecycle.AUTOMATION_ACCOUNT.casefold()}"
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
    permitted_binding_ids: frozenset[str] | None = None,
) -> None:
    account = (
        "microsoft.automation/automationaccounts/"
        f"{authorization.replacementAutomationAccount.casefold()}"
    )
    corrupted_account = (
        f"microsoft.automation/automationaccounts/{CORRUPTED_AUTOMATION_ACCOUNT.casefold()}"
    )
    corrupted_runbook = f"{corrupted_account}/runbooks/{authorization.runbook.casefold()}"
    corrupted_schedule = f"{corrupted_account}/schedules/{authorization.schedule.casefold()}"
    runbook = f"{account}/runbooks/{authorization.runbook.casefold()}"
    schedule = f"{account}/schedules/{authorization.schedule.casefold()}"
    binding_ids = permitted_binding_ids or frozenset({authorization.bindingId})
    bindings = {f"{account}/jobschedules/{binding_id.casefold()}" for binding_id in binding_ids}
    active_binding = f"{account}/jobschedules/{authorization.bindingId.casefold()}"
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
        *bindings,
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
    schedule_rows = {item for item in resources if item.startswith(f"{account}/schedules/")}
    binding_rows = {item for item in resources if item.startswith(f"{account}/jobschedules/")}
    if len(account_rows) > 1 or len(schedule_rows) > 1 or len(binding_rows) > 1:
        _fail("cleanup-recovery-duplicate-resource")
    if require_complete and not {account, runbook, schedule, active_binding}.issubset(resources):
        _fail("cleanup-recovery-resource-proof-incomplete")


def _replacement_collection(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    *,
    collection: str,
    query: str,
) -> list[JsonValue]:
    return _automation_account_collection(
        account_id=authorization.replacementAutomationAccountId,
        collection=collection,
        query=query,
    )


def _replacement_role_rows(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    subscription_id: str,
) -> list[dict[str, str]]:
    value = lifecycle._run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            authorization.replacementPrincipalId,
            "--all",
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("cleanup-deadline-recovery-role-output-malformed")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "principalId",
            "roleDefinitionId",
            "scope",
        }:
            _fail("cleanup-deadline-recovery-role-output-malformed")
        if any(not isinstance(item[key], str) for key in item):
            _fail("cleanup-deadline-recovery-role-output-malformed")
        rows.append({key: str(item[key]).casefold() for key in item})
    return rows


def _expected_replacement_role_row(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> dict[str, str]:
    role_definition_id = (
        f"/subscriptions/{authorization.subscriptionId}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{authorization.roleDefinitionId}"
    )
    return {
        "id": authorization.replacementRoleAssignmentId.casefold(),
        "principalId": authorization.replacementPrincipalId.casefold(),
        "roleDefinitionId": role_definition_id.casefold(),
        "scope": authorization.roleScope.casefold(),
    }


def _published_runbook_hash(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> str:
    runbook_id = f"{authorization.replacementAutomationAccountId}/runbooks/{authorization.runbook}"
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
    if not isinstance(content, str):
        _fail("cleanup-deadline-recovery-runbook-content-malformed")
    return cleanup_runbook_sha256(content)


def _schedule_rows(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> list[JsonValue]:
    return _replacement_collection(
        authorization,
        collection="schedules",
        query=(
            "value[].{frequency:properties.frequency,id:id,"
            "isEnabled:properties.isEnabled,name:name,"
            "startTime:properties.startTime,timeZone:properties.timeZone}"
        ),
    )


def _validated_schedule_deadline(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    rows: list[JsonValue],
    *,
    allowed_deadlines: frozenset[str],
    required: bool,
) -> str | None:
    if not rows:
        if required:
            _fail("cleanup-deadline-recovery-schedule-missing")
        return None
    if len(rows) != 1 or not isinstance(rows[0], dict):
        _fail("cleanup-deadline-recovery-duplicate-schedule")
    row = rows[0]
    expected_fields = {
        "frequency",
        "id",
        "isEnabled",
        "name",
        "startTime",
        "timeZone",
    }
    if set(row) != expected_fields or not isinstance(row.get("startTime"), str):
        _fail("cleanup-deadline-recovery-schedule-output-malformed")
    expected_id = (
        f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
    )
    try:
        observed_start = datetime.fromisoformat(str(row["startTime"]).replace("Z", "+00:00"))
    except ValueError:
        _fail("cleanup-deadline-recovery-schedule-output-malformed")
    if observed_start.tzinfo is None or observed_start.utcoffset() is None:
        _fail("cleanup-deadline-recovery-schedule-output-malformed")
    observed_deadline = _format_utc(observed_start)
    if (
        not isinstance(row.get("id"), str)
        or str(row["id"]).casefold() != expected_id.casefold()
        or row.get("name") != authorization.schedule
        or row.get("frequency") != "OneTime"
        or row.get("isEnabled") is not True
        or row.get("timeZone") != "Etc/UTC"
        or observed_deadline not in allowed_deadlines
    ):
        _fail("cleanup-deadline-recovery-schedule-drift")
    return observed_deadline


def _job_schedule_rows(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> list[JsonValue]:
    listed = _replacement_collection(
        authorization,
        collection="jobSchedules",
        query=(
            "value[].{id:id,jobScheduleId:properties.jobScheduleId,"
            "runbook:properties.runbook.name,schedule:properties.schedule.name}"
        ),
    )
    permitted_ids = {
        authorization.bindingId.casefold(),
        authorization.priorBindingId.casefold(),
    }
    detailed: list[JsonValue] = []
    for row in listed:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "jobScheduleId",
            "runbook",
            "schedule",
        }:
            _fail("cleanup-deadline-recovery-binding-output-malformed")
        job_schedule_id = row.get("jobScheduleId")
        if not isinstance(job_schedule_id, str) or job_schedule_id.casefold() not in permitted_ids:
            _fail("cleanup-deadline-recovery-binding-drift")
        expected_id = (
            f"{authorization.replacementAutomationAccountId}/jobSchedules/{job_schedule_id}"
        )
        if (
            not isinstance(row.get("id"), str)
            or str(row["id"]).casefold() != expected_id.casefold()
        ):
            _fail("cleanup-deadline-recovery-binding-drift")
        detail = lifecycle._run(
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                (
                    f"https://management.azure.com{expected_id}"
                    f"?api-version={lifecycle.AUTOMATION_API_VERSION}"
                ),
                "--query",
                (
                    "{id:id,jobScheduleId:properties.jobScheduleId,"
                    "parameters:properties.parameters,"
                    "runbook:properties.runbook.name,"
                    "schedule:properties.schedule.name}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        detailed.append(detail)
    return detailed


def _validate_job_schedule_rows(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    rows: list[JsonValue],
    *,
    required: bool | None,
    allowed_binding_ids: frozenset[str] | None = None,
) -> bool:
    if not rows:
        if required is True:
            _fail("cleanup-deadline-recovery-binding-missing")
        return False
    if required is False:
        _fail("cleanup-deadline-recovery-binding-still-present")
    if len(rows) != 1 or not isinstance(rows[0], dict):
        _fail("cleanup-deadline-recovery-duplicate-binding")
    row = rows[0]
    if set(row) != {"id", "jobScheduleId", "parameters", "runbook", "schedule"}:
        _fail("cleanup-deadline-recovery-binding-output-malformed")
    parameters = row.get("parameters")
    if not isinstance(parameters, dict) or len(parameters) != 2:
        _fail("cleanup-deadline-recovery-binding-drift")
    normalized_parameters = {str(name).casefold(): value for name, value in parameters.items()}
    permitted_ids = {
        binding_id.casefold()
        for binding_id in (allowed_binding_ids or frozenset({authorization.bindingId}))
    }
    observed_job_schedule_id = row.get("jobScheduleId")
    expected_id = (
        f"{authorization.replacementAutomationAccountId}/jobSchedules/{observed_job_schedule_id}"
    )
    if (
        not isinstance(row.get("id"), str)
        or str(row["id"]).casefold() != expected_id.casefold()
        or not isinstance(observed_job_schedule_id, str)
        or observed_job_schedule_id.casefold() not in permitted_ids
        or row.get("runbook") != authorization.runbook
        or row.get("schedule") != authorization.schedule
        or normalized_parameters
        != {
            authorization.authorizationParameter.casefold(): "true",
            authorization.targetParameter.casefold(): (authorization.targetParameterValue),
        }
    ):
        _fail("cleanup-deadline-recovery-binding-drift")
    return True


def _verify_replacement_cleanup_graph(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    subscription_id: str,
    *,
    allowed_deadlines: frozenset[str],
    allowed_runbook_hashes: frozenset[str],
    binding_required: bool | None,
    allowed_binding_ids: frozenset[str] | None = None,
) -> str:
    account = lifecycle._run(
        (
            "az",
            "automation",
            "account",
            "show",
            "--resource-group",
            CLEANUP_GROUP,
            "--automation-account-name",
            authorization.replacementAutomationAccount,
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
        "id": authorization.replacementAutomationAccountId,
        "identityType": "SystemAssigned",
        "localAuthDisabled": True,
        "location": authorization.replacementLocation,
        "principalId": authorization.replacementPrincipalId,
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
        _fail("cleanup-deadline-recovery-account-drift")

    runbook_id = f"{authorization.replacementAutomationAccountId}/runbooks/{authorization.runbook}"
    runbooks = _replacement_collection(
        authorization,
        collection="runbooks",
        query=(
            "value[].{id:id,location:location,name:name,"
            "runbookType:properties.runbookType,state:properties.state}"
        ),
    )
    if len(runbooks) != 1 or not isinstance(runbooks[0], dict):
        _fail("cleanup-deadline-recovery-runbook-drift")
    runbook = runbooks[0]
    if (
        set(runbook) != {"id", "location", "name", "runbookType", "state"}
        or not isinstance(runbook.get("id"), str)
        or str(runbook["id"]).casefold() != runbook_id.casefold()
        or runbook.get("location") != authorization.replacementLocation
        or runbook.get("name") != authorization.runbook
        or runbook.get("runbookType") != "PowerShell72"
        or runbook.get("state") != "Published"
        or _published_runbook_hash(authorization) not in allowed_runbook_hashes
    ):
        _fail("cleanup-deadline-recovery-runbook-drift")

    _validated_schedule_deadline(
        authorization,
        _schedule_rows(authorization),
        allowed_deadlines=allowed_deadlines,
        required=True,
    )
    _validate_job_schedule_rows(
        authorization,
        _job_schedule_rows(authorization),
        required=binding_required,
        allowed_binding_ids=allowed_binding_ids,
    )

    empty_collections = {
        "webhooks": "value[].{id:id,name:name}",
        "variables": "value[].{id:id,name:name}",
        "credentials": "value[].{id:id,name:name}",
        "certificates": "value[].{id:id,name:name}",
        "connections": "value[].{id:id,name:name}",
        "hybridRunbookWorkerGroups": "value[].{id:id,name:name}",
        "sourceControls": "value[].{id:id,name:name}",
    }
    for collection, query in empty_collections.items():
        if _replacement_collection(authorization, collection=collection, query=query):
            _fail("cleanup-deadline-recovery-execution-edge-present")

    jobs = _replacement_collection(
        authorization,
        collection="jobs",
        query="value[].{id:id,status:properties.status,runbook:properties.runbook.name}",
    )
    job_prefix = f"{authorization.replacementAutomationAccountId}/jobs/".casefold()
    for job in jobs:
        if (
            not isinstance(job, dict)
            or set(job) != {"id", "runbook", "status"}
            or not isinstance(job.get("id"), str)
            or not str(job["id"]).casefold().startswith(job_prefix)
            or job.get("runbook") != authorization.runbook
            or job.get("status") not in TERMINAL_AUTOMATION_JOB_STATES
        ):
            _fail("cleanup-deadline-recovery-job-not-terminal")

    if _replacement_role_rows(authorization, subscription_id) != [
        _expected_replacement_role_row(authorization)
    ]:
        _fail("cleanup-deadline-recovery-role-drift")
    return authorization.replacementPrincipalId


def _normalized_azure_utc(value: JsonValue, error_code: str) -> str:
    if not isinstance(value, str):
        _fail(error_code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(error_code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(error_code)
    return _format_utc(parsed)


def _verify_post_fired_target_preservation(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    subscription_id: str,
    *,
    now_utc: datetime,
) -> int:
    expected_count = authorization.expectedTargetResourceCount
    expected_delete_count = authorization.expectedDeleteActivityCount
    activity_start = authorization.deleteActivityStartUtc
    if (
        authorization.authorizationVersion != POST_FIRED_RECOVERY_AUTHORIZATION_VERSION
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 1
        or expected_delete_count != 0
        or not isinstance(activity_start, str)
    ):
        _fail("cleanup-post-fired-recovery-state-malformed")
    resources = lifecycle._run(
        (
            "az",
            "resource",
            "list",
            "--resource-group",
            authorization.targetParameterValue,
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    target_prefix = f"{authorization.targetResourceGroupId}/providers/".casefold()
    if (
        not isinstance(resources, list)
        or len(resources) != expected_count
        or any(
            not isinstance(row, dict)
            or set(row) != {"id"}
            or not isinstance(row.get("id"), str)
            or not str(row["id"]).casefold().startswith(target_prefix)
            for row in resources
        )
    ):
        _fail("cleanup-post-fired-target-preservation-unproved")
    activity = lifecycle._run(
        (
            "az",
            "monitor",
            "activity-log",
            "list",
            "--resource-group",
            authorization.targetParameterValue,
            "--subscription",
            subscription_id,
            "--start-time",
            activity_start,
            "--end-time",
            _format_utc(now_utc),
            "--max-events",
            "1000",
            "--query",
            ("[].{operationName:operationName.value,resourceId:resourceId,status:status.value}"),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(activity, list):
        _fail("cleanup-post-fired-delete-activity-output-malformed")
    delete_count = 0
    for row in activity:
        if (
            not isinstance(row, dict)
            or set(row) != {"operationName", "resourceId", "status"}
            or not isinstance(row.get("operationName"), str)
            or not isinstance(row.get("resourceId"), str)
            or not isinstance(row.get("status"), str)
            or not str(row["resourceId"])
            .casefold()
            .startswith(authorization.targetResourceGroupId.casefold())
        ):
            _fail("cleanup-post-fired-delete-activity-output-malformed")
        operation = str(row["operationName"]).casefold()
        if operation.endswith("/delete") or "/delete/" in operation:
            delete_count += 1
    if delete_count != expected_delete_count:
        _fail("cleanup-post-fired-delete-activity-present")
    return len(resources)


def _verify_post_fired_cleanup_state(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    subscription_id: str,
    *,
    now_utc: datetime,
) -> int:
    target_resource_count = _verify_post_fired_target_preservation(
        authorization,
        subscription_id,
        now_utc=now_utc,
    )
    jobs = _replacement_collection(
        authorization,
        collection="jobs",
        query=(
            "value[].{creationTime:properties.creationTime,endTime:properties.endTime,"
            "exception:properties.exception,id:id,"
            "provisioningState:properties.provisioningState,"
            "runbook:properties.runbook.name,startTime:properties.startTime,"
            "status:properties.status}"
        ),
    )
    expected_job_id = authorization.priorCleanupJobId
    expected_nonterminal = authorization.expectedNonterminalCleanupJobCount
    if not isinstance(expected_job_id, str) or expected_nonterminal != 0:
        _fail("cleanup-post-fired-recovery-state-malformed")
    matching_jobs: list[dict[str, JsonValue]] = []
    nonterminal_count = 0
    expected_job_fields = {
        "creationTime",
        "endTime",
        "exception",
        "id",
        "provisioningState",
        "runbook",
        "startTime",
        "status",
    }
    for job in jobs:
        if (
            not isinstance(job, dict)
            or set(job) != expected_job_fields
            or not isinstance(job.get("id"), str)
            or not isinstance(job.get("status"), str)
        ):
            _fail("cleanup-post-fired-job-output-malformed")
        if job["status"] not in TERMINAL_AUTOMATION_JOB_STATES:
            nonterminal_count += 1
        if str(job["id"]).casefold() == expected_job_id.casefold():
            matching_jobs.append(job)
    if nonterminal_count != expected_nonterminal:
        _fail("cleanup-post-fired-job-not-terminal")
    if len(matching_jobs) != 1:
        _fail("cleanup-post-fired-failed-job-unproved")
    failed_job = matching_jobs[0]
    if (
        failed_job.get("status") != authorization.priorCleanupJobStatus
        or failed_job.get("provisioningState") != "Failed"
        or failed_job.get("exception") != authorization.priorCleanupJobException
        or failed_job.get("runbook") != authorization.runbook
        or _normalized_azure_utc(
            failed_job.get("creationTime"),
            "cleanup-post-fired-job-output-malformed",
        )
        != authorization.priorCleanupJobCreatedAtUtc
        or not isinstance(failed_job.get("startTime"), str)
        or not isinstance(failed_job.get("endTime"), str)
    ):
        _fail("cleanup-post-fired-failed-job-drift")

    schedules = _replacement_collection(
        authorization,
        collection="schedules",
        query=(
            "value[].{expiryTime:properties.expiryTime,frequency:properties.frequency,"
            "id:id,isEnabled:properties.isEnabled,name:name,"
            "nextRun:properties.nextRun,startTime:properties.startTime,"
            "timeZone:properties.timeZone}"
        ),
    )
    if len(schedules) != 1 or not isinstance(schedules[0], dict):
        _fail("cleanup-post-fired-expired-schedule-unproved")
    schedule = schedules[0]
    expected_schedule_id = (
        f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
    )
    if (
        set(schedule)
        != {
            "expiryTime",
            "frequency",
            "id",
            "isEnabled",
            "name",
            "nextRun",
            "startTime",
            "timeZone",
        }
        or not isinstance(schedule.get("id"), str)
        or str(schedule["id"]).casefold() != expected_schedule_id.casefold()
        or schedule.get("name") != authorization.schedule
        or schedule.get("frequency") != "OneTime"
        or schedule.get("isEnabled") is not True
        or schedule.get("timeZone") != "Etc/UTC"
        or schedule.get("nextRun") is not None
        or _normalized_azure_utc(
            schedule.get("startTime"),
            "cleanup-post-fired-schedule-output-malformed",
        )
        != authorization.priorDeadlineUtc
        or _normalized_azure_utc(
            schedule.get("expiryTime"),
            "cleanup-post-fired-schedule-output-malformed",
        )
        != authorization.priorDeadlineUtc
    ):
        _fail("cleanup-post-fired-expired-schedule-drift")
    _validate_job_schedule_rows(
        authorization,
        _job_schedule_rows(authorization),
        required=True,
        allowed_binding_ids=frozenset({authorization.priorBindingId}),
    )
    return target_resource_count


def _verify_post_fired_rearmed_target_tags(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    subscription_id: str,
    *,
    deployment_binding: dict[str, JsonValue],
) -> None:
    observed = lifecycle._run(
        (
            "az",
            "group",
            "show",
            "--name",
            authorization.targetParameterValue,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected = {
        "id": authorization.targetResourceGroupId,
        "tags": lifecycle._lifecycle_tags(
            ledger=deployment_binding,
            cleanup_at=_deadline(authorization),
            maximum_cost=authorization.costCeilingUsdCents,
        ),
    }
    if (
        not isinstance(observed, dict)
        or set(observed) != {"id", "tags"}
        or not isinstance(observed.get("id"), str)
        or str(observed["id"]).casefold() != authorization.targetResourceGroupId.casefold()
        or observed.get("tags") != expected["tags"]
    ):
        _fail("cleanup-post-fired-target-lease-rearm-unproved")


def _remove_prior_binding(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> bool:
    rows = _job_schedule_rows(authorization)
    if not _validate_job_schedule_rows(
        authorization,
        rows,
        required=None,
        allowed_binding_ids=frozenset({authorization.priorBindingId}),
    ):
        return False
    endpoint = (
        "https://management.azure.com"
        f"{authorization.replacementAutomationAccountId}/jobSchedules/"
        f"{authorization.priorBindingId}"
        f"?api-version={lifecycle.AUTOMATION_API_VERSION}"
    )
    try:
        lifecycle._run(
            (
                "az",
                "rest",
                "--method",
                "delete",
                "--url",
                endpoint,
                "--output",
                "none",
                "--only-show-errors",
            )
        )
    except lifecycle.AzureCommandError:
        # A committed DELETE can lose its response.  Reconcile read-only and
        # never issue a second delete for the consumed authorization.
        pass
    deadline = time.monotonic() + DEADLINE_RECOVERY_PROPAGATION_SECONDS
    while True:
        rows = _job_schedule_rows(authorization)
        if not rows:
            return True
        _validate_job_schedule_rows(authorization, rows, required=None)
        if time.monotonic() >= deadline:
            _fail("cleanup-deadline-recovery-binding-removal-unproved")
        time.sleep(DEADLINE_RECOVERY_POLL_SECONDS)


def _reconcile_deadline_runbook(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
    subscription_id: str,
) -> bool:
    observed_hash = _published_runbook_hash(authorization)
    if observed_hash == authorization.runbookContentSha256:
        return False
    if observed_hash != authorization.priorRunbookContentSha256:
        _fail("cleanup-deadline-recovery-runbook-drift")
    try:
        lifecycle._configure_cleanup_runbook(subscription_id)
    except lifecycle.AzureCommandError:
        # Publishing is a two-step Azure operation.  Reconcile the published
        # content rather than replaying either step after an ambiguous response.
        pass
    deadline = time.monotonic() + DEADLINE_RECOVERY_PROPAGATION_SECONDS
    while True:
        observed_hash = _published_runbook_hash(authorization)
        if observed_hash == authorization.runbookContentSha256:
            return True
        if observed_hash != authorization.priorRunbookContentSha256:
            _fail("cleanup-deadline-recovery-runbook-drift")
        if time.monotonic() >= deadline:
            _fail("cleanup-deadline-recovery-runbook-publication-unproved")
        time.sleep(DEADLINE_RECOVERY_POLL_SECONDS)


def _replace_cleanup_schedule(
    authorization: CleanupControlDeadlineRecoveryAuthorization,
) -> bool:
    rows = _schedule_rows(authorization)
    observed_deadline = _validated_schedule_deadline(
        authorization,
        rows,
        allowed_deadlines=frozenset({authorization.priorDeadlineUtc, authorization.deadlineUtc}),
        required=False,
    )
    if observed_deadline == authorization.deadlineUtc:
        return False
    schedule_endpoint = (
        "https://management.azure.com"
        f"{authorization.replacementAutomationAccountId}/schedules/"
        f"{authorization.schedule}"
        f"?api-version={lifecycle.AUTOMATION_API_VERSION}"
    )
    if observed_deadline == authorization.priorDeadlineUtc:
        try:
            lifecycle._run(
                (
                    "az",
                    "rest",
                    "--method",
                    "delete",
                    "--url",
                    schedule_endpoint,
                    "--output",
                    "none",
                    "--only-show-errors",
                )
            )
        except lifecycle.AzureCommandError:
            # Do not replay an ambiguous exact delete.
            pass
        deadline = time.monotonic() + DEADLINE_RECOVERY_PROPAGATION_SECONDS
        while True:
            rows = _schedule_rows(authorization)
            if not rows:
                break
            current = _validated_schedule_deadline(
                authorization,
                rows,
                allowed_deadlines=frozenset(
                    {authorization.priorDeadlineUtc, authorization.deadlineUtc}
                ),
                required=False,
            )
            if current == authorization.deadlineUtc:
                return False
            if time.monotonic() >= deadline:
                _fail("cleanup-deadline-recovery-schedule-removal-unproved")
            time.sleep(DEADLINE_RECOVERY_POLL_SECONDS)

    schedule_body = {
        "properties": {
            "description": "One-time Milestone 7.7 hard cleanup failsafe.",
            "frequency": "OneTime",
            "interval": 1,
            "startTime": authorization.deadlineUtc,
            "timeZone": "Etc/UTC",
        }
    }
    try:
        lifecycle._run(
            (
                "az",
                "rest",
                "--method",
                "put",
                "--url",
                schedule_endpoint,
                "--headers",
                "Content-Type=application/json",
                "--body",
                json.dumps(schedule_body, separators=(",", ":"), sort_keys=True),
                "--output",
                "none",
                "--only-show-errors",
            )
        )
    except lifecycle.AzureCommandError:
        # Reconcile an ambiguous create instead of creating a second schedule.
        pass
    deadline = time.monotonic() + DEADLINE_RECOVERY_PROPAGATION_SECONDS
    while True:
        rows = _schedule_rows(authorization)
        if rows:
            current = _validated_schedule_deadline(
                authorization,
                rows,
                allowed_deadlines=frozenset({authorization.deadlineUtc}),
                required=True,
            )
            if current == authorization.deadlineUtc:
                return True
        if time.monotonic() >= deadline:
            _fail("cleanup-deadline-recovery-schedule-creation-unproved")
        time.sleep(DEADLINE_RECOVERY_POLL_SECONDS)


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
        final_resources = _cleanup_resource_group_inventory(subscription_id)
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

    def execute_deadline_recovery(
        self,
        *,
        authorization: CleanupControlDeadlineRecoveryAuthorization,
        receipt_directory: Path,
        expected_repository_head: str,
    ) -> dict[str, JsonValue]:
        """Re-arm only the preserved generation-2 cleanup execution edge."""

        now = self._clock().astimezone(UTC).replace(microsecond=0)
        validate_cleanup_control_deadline_recovery_authorization(
            authorization,
            expected_repository_head=expected_repository_head,
            now_utc=now,
        )
        lifecycle._verify_repository_state(expected_repository_head)
        subscription_id = lifecycle._account_binding(now)
        if subscription_id != authorization.subscriptionId:
            _fail("cleanup-deadline-recovery-subscription-mismatch")
        if not lifecycle._group_exists(subscription_id, CLEANUP_GROUP):
            _fail("cleanup-deadline-recovery-cleanup-resource-group-missing")
        if not lifecycle._group_exists(subscription_id, authorization.targetParameterValue):
            _fail("cleanup-deadline-recovery-target-resource-group-missing")

        contract = load_managed_binding_contract()
        _validate_contract_mapping(authorization, contract)
        transition_binding_ids = frozenset({authorization.priorBindingId, authorization.bindingId})
        initial_resources = _cleanup_resource_group_inventory(subscription_id)
        _validate_cleanup_inventory(
            initial_resources,
            authorization=authorization,
            require_complete=False,
            permitted_binding_ids=transition_binding_ids,
        )
        _verify_corrupted_evidence_graph(
            authorization,
            subscription_id,
            assignment_required=False,
            expected_runbook_hash=CORRUPTED_RUNBOOK_CONTENT_SHA256,
        )
        prior_or_recovered_deadlines = frozenset(
            {authorization.priorDeadlineUtc, authorization.deadlineUtc}
        )
        prior_or_recovered_runbooks = frozenset(
            {
                authorization.priorRunbookContentSha256,
                authorization.runbookContentSha256,
            }
        )
        _verify_replacement_cleanup_graph(
            authorization,
            subscription_id,
            allowed_deadlines=prior_or_recovered_deadlines,
            allowed_runbook_hashes=prior_or_recovered_runbooks,
            binding_required=None,
            allowed_binding_ids=transition_binding_ids,
        )
        post_fired = authorization.authorizationVersion == POST_FIRED_RECOVERY_AUTHORIZATION_VERSION
        post_fired_resource_count: int | None = None
        if post_fired:
            post_fired_resource_count = _verify_post_fired_cleanup_state(
                authorization,
                subscription_id,
                now_utc=now,
            )

        _claim_deadline_recovery_authorization(
            authorization=authorization,
            receipt_directory=receipt_directory,
            now_utc=now,
        )
        binding_delete_issued = _remove_prior_binding(authorization)
        _verify_replacement_cleanup_graph(
            authorization,
            subscription_id,
            allowed_deadlines=prior_or_recovered_deadlines,
            allowed_runbook_hashes=prior_or_recovered_runbooks,
            binding_required=False,
        )

        runbook_published = _reconcile_deadline_runbook(authorization, subscription_id)
        schedule_replaced = _replace_cleanup_schedule(authorization)
        _verify_replacement_cleanup_graph(
            authorization,
            subscription_id,
            allowed_deadlines=frozenset({authorization.deadlineUtc}),
            allowed_runbook_hashes=frozenset({authorization.runbookContentSha256}),
            binding_required=False,
        )

        cleanup_at = _deadline(authorization)
        deployment_binding = _deployment_binding(authorization, contract)
        with tempfile.TemporaryDirectory(prefix="mobius77-cleanup-deadline-recovery-") as directory:
            template = Path(directory) / "main.json"
            lifecycle._compile_template(template)
            try:
                lifecycle._deploy_stage(
                    template_path=template,
                    subscription_id=subscription_id,
                    ledger=deployment_binding,
                    stage="cleanup-job-binding",
                    cleanup_at=cleanup_at,
                    expected_cost=EXPECTED_COST_USD_CENTS,
                    maximum_cost=authorization.costCeilingUsdCents,
                )
            except lifecycle.AzureCommandError:
                # Adopt only an exact binding after an ambiguous deployment.
                _validate_job_schedule_rows(
                    authorization,
                    _job_schedule_rows(authorization),
                    required=True,
                )
            if post_fired:
                try:
                    lifecycle._deploy_stage(
                        template_path=template,
                        subscription_id=subscription_id,
                        ledger=deployment_binding,
                        stage="cleanup-binding",
                        cleanup_at=cleanup_at,
                        expected_cost=EXPECTED_COST_USD_CENTS,
                        maximum_cost=authorization.costCeilingUsdCents,
                    )
                except lifecycle.AzureCommandError:
                    # Adopt only the exact target-group role and lifecycle tags
                    # after an ambiguous deployment response.
                    pass

        proved_principal_id = _verify_replacement_cleanup_graph(
            authorization,
            subscription_id,
            allowed_deadlines=frozenset({authorization.deadlineUtc}),
            allowed_runbook_hashes=frozenset({authorization.runbookContentSha256}),
            binding_required=True,
        )
        _verify_corrupted_evidence_graph(
            authorization,
            subscription_id,
            assignment_required=False,
            expected_runbook_hash=CORRUPTED_RUNBOOK_CONTENT_SHA256,
        )
        final_resources = _cleanup_resource_group_inventory(subscription_id)
        _validate_cleanup_inventory(
            final_resources,
            authorization=authorization,
            require_complete=True,
        )
        if post_fired:
            _verify_post_fired_rearmed_target_tags(
                authorization,
                subscription_id,
                deployment_binding=deployment_binding,
            )
            post_fired_resource_count = _verify_post_fired_target_preservation(
                authorization,
                subscription_id,
                now_utc=self._clock().astimezone(UTC).replace(microsecond=0),
            )
        schedule_resource_id = (
            f"{authorization.replacementAutomationAccountId}/schedules/{authorization.schedule}"
        )
        binding_resource_id = (
            f"{authorization.replacementAutomationAccountId}/jobSchedules/{authorization.bindingId}"
        )
        return {
            "authorization-consumed": True,
            "authorization-integrity-sha256": (authorization.authorizationIntegritySha256),
            "binding-id": authorization.bindingId,
            "binding-resource-id": binding_resource_id,
            "cleanup-executable": True,
            "cleanup-parameter": authorization.authorizationParameter,
            "cleanup-parameter-value": authorization.authorizationParameterValue,
            "deadline-observed-at-utc": authorization.deadlineObservedAtUtc,
            "deadline-utc": authorization.deadlineUtc,
            "marker": "CLEANUP_EXECUTABLE_AND_ARMED",
            "maximum-plausible-usd-cents": authorization.costCeilingUsdCents,
            "principal-fingerprint-sha256": hashlib.sha256(
                proved_principal_id.casefold().encode("ascii")
            ).hexdigest(),
            "prior-binding-absent": True,
            "prior-binding-delete-issued": binding_delete_issued,
            "post-fired-recovery": post_fired,
            "post-fired-recovery-purpose": authorization.postFiredRecoveryPurpose,
            "post-fired-target-resource-count": post_fired_resource_count,
            "replacement-automation-account": (authorization.replacementAutomationAccount),
            "replacement-role-assignment-id": (authorization.replacementRoleAssignmentId),
            "role-definition-id": authorization.roleDefinitionId,
            "role-scope": authorization.roleScope,
            "runbook": authorization.runbook,
            "runbook-published": runbook_published,
            "schedule": authorization.schedule,
            "schedule-replaced": schedule_replaced,
            "schedule-resource-id": schedule_resource_id,
            "status": "cleanup-control-deadline-recovery-executable",
            "target-parameter": authorization.targetParameter,
            "target-parameter-value": authorization.targetParameterValue,
        }


__all__ = [
    "CleanupControlRecoveryExecutionError",
    "ProductionCleanupControlRecoveryAdapter",
]
