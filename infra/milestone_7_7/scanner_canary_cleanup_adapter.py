"""Production adapter for one exact retained Image Eight canary cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn, cast

from infra.milestone_7_7 import scanner_bridge_recovery_adapter as scanner_adapter
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    load_managed_binding_contract,
)
from preflight.milestone_7_7.scanner_canary_cleanup import (
    CLEANUP_JOB,
    EXPECTED_PROVIDER_VERSION_SHA256,
    MANAGED_ENVIRONMENT,
    STORAGE_ACCOUNT,
    TARGET_RESOURCE_GROUP,
    WORKER_IDENTITY,
    ScannerCanaryCleanupAuthorization,
    validate_scanner_canary_cleanup_authorization,
)

RECEIPT_VERSION: Final = "mobius.milestone-7.7.scanner-canary-cleanup-receipt.v1"
RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup-receipt/v1\0"
)
RECEIPT_FILE: Final = "scanner-canary-cleanup.receipt.json"
EVIDENCE_VERSION: Final = "mobius.milestone-7.7.scanner-canary-cleanup-evidence.v1"
EVIDENCE_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup-evidence/v1\0"
)
JOB_MARKER_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup-job/v1\0"
)
JOB_API_VERSION: Final = "2025-01-01"
ROLE_API_VERSION: Final = "2022-04-01"
IDENTITY_API_VERSION: Final = "2024-11-30"
STORAGE_API_VERSION: Final = "2025-06-01"
MANAGED_ENVIRONMENT_API_VERSION: Final = "2026-01-01"
STAGING_LOCATION: Final = "southcentralus"
REGISTRY_HOST: Final = "acrmobius7711564669.azurecr.io"
CLEANUP_CONTAINER: Final = "image-eight-canary-cleanup"
CLEANUP_ROLE_NAME: Final = "Mobius77 Exact Image Eight Canary Cleanup"
WORKER_QUARANTINE_ROLE: Final = "292f18b2-0b41-4a86-a4af-46cd22d2e52e"
PROOF_ROLE_DEFINITION_NAME: Final = "7d78ed8f-4b48-4e74-bb95-f0fcfe811897"
PROOF_JOB: Final = "caj-mobius77-scanner-proof"
RESOURCE_POLL_SECONDS: Final = 5.0
RESOURCE_PROPAGATION_SECONDS: Final = 180.0
RBAC_POLL_SECONDS: Final = 15.0
RBAC_PROPAGATION_SECONDS: Final = 900.0
EXECUTION_POLL_SECONDS: Final = 15.0
EXECUTION_PROPAGATION_SECONDS: Final = 900.0

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODE = re.compile(r"^scanner-canary-cleanup-[a-z0-9-]+$")

_CLEANUP_ROLE_PERMISSIONS: Final[list[JsonValue]] = [
    {
        "actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/read"],
        "dataActions": [
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
            (
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/"
                "deleteBlobVersion/action"
            ),
            (
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/"
                "permanentDelete/action"
            ),
        ],
        "notActions": [],
        "notDataActions": [],
    }
]

_CLEANUP_PROGRAM: Final = r"""
import asyncio
import hashlib
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from opencanvas_api.services.documents.storage import (
    AzureBlobVersionedObjectStorage,
    AzureManagedIdentityTokenProvider,
)
from scripts.scanner_bridge_probe import _remove_exact_canary

DOMAIN = b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup-job/v1\0"


def canonical(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def sha256_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


async def inventory(storage, blob_name):
    response = await storage._request(
        "GET",
        "quarantine",
        query={
            "restype": "container",
            "comp": "list",
            "prefix": blob_name,
            "include": "versions,deleted",
            "maxresults": "100",
        },
    )
    if response.status_code != 200 or len(response.content) > 131072:
        raise RuntimeError("scanner-canary-cleanup-inventory-invalid")
    root = ET.fromstring(response.content)
    continuation = any(
        (node.text or "")
        for node in root.iter()
        if local_name(node.tag) == "NextMarker"
    )
    rows = []
    for blob in root.iter():
        if local_name(blob.tag) != "Blob":
            continue
        values = {}
        for node in blob.iter():
            key = local_name(node.tag)
            if key in {"Name", "VersionId", "Deleted", "IsCurrentVersion"} and key not in values:
                values[key] = node.text or ""
        rows.append(values)
    return response, rows, continuation


async def run():
    authorization_integrity = os.environ["OPENCANVAS_CANARY_CLEANUP_AUTHORIZATION_SHA256"]
    cleanup_deadline = os.environ["OPENCANVAS_CANARY_CLEANUP_DEADLINE_UTC"]
    blob_name = os.environ["OPENCANVAS_CANARY_CLEANUP_BLOB_NAME"]
    object_id = os.environ["OPENCANVAS_CANARY_CLEANUP_OBJECT_ID"]
    object_version_id = os.environ["OPENCANVAS_CANARY_CLEANUP_OBJECT_VERSION_ID"]
    expected_provider_hash = os.environ["OPENCANVAS_CANARY_CLEANUP_PROVIDER_VERSION_SHA256"]
    if (
        re.fullmatch(r"[0-9a-f]{64}", authorization_integrity) is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_provider_hash) is None
        or re.fullmatch(r"[0-9a-f]{32}/[0-9a-f]{32}", blob_name) is None
        or "*" in blob_name
        or "?" in blob_name
        or uuid.UUID(object_id).hex != blob_name.split("/", 1)[0]
        or uuid.UUID(object_version_id).hex != blob_name.split("/", 1)[1]
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", cleanup_deadline) is None
    ):
        raise RuntimeError("scanner-canary-cleanup-binding-invalid")
    token_provider = AzureManagedIdentityTokenProvider(
        endpoint=os.environ["IDENTITY_ENDPOINT"],
        identity_header=os.environ["IDENTITY_HEADER"],
        client_id=os.environ["OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID"],
    )
    storage = AzureBlobVersionedObjectStorage(
        account_url=os.environ["OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL"],
        quarantine_container="quarantine",
        clean_container="clean",
        rejected_container="rejected",
        retained_container="retained",
        token_provider=token_provider,
    )
    before, rows, continuation_before = await inventory(storage, blob_name)
    if continuation_before or len(rows) != 1:
        raise RuntimeError("scanner-canary-cleanup-precondition-invalid")
    row = rows[0]
    provider_version_id = row.get("VersionId", "")
    if (
        row.get("Name") != blob_name
        or row.get("Deleted", "").casefold() == "true"
        or not provider_version_id
        or sha256_text(provider_version_id) != expected_provider_hash
    ):
        raise RuntimeError("scanner-canary-cleanup-precondition-invalid")
    await _remove_exact_canary(
        storage,
        SimpleNamespace(
            physical_key=f"quarantine/{blob_name}",
            provider_version_id=provider_version_id,
        ),
    )
    after, remaining, continuation_after = await inventory(storage, blob_name)
    if continuation_after or remaining:
        raise RuntimeError("scanner-canary-cleanup-residue-present")
    evidence = {
        "afterActiveVersionCount": 0,
        "afterDeletedVersionCount": 0,
        "authorizationIntegritySha256": authorization_integrity,
        "beforeActiveVersionCount": 1,
        "beforeDeletedVersionCount": 0,
        "cleanupDeadlineUtc": cleanup_deadline,
        "cleanupInvocationCount": 1,
        "containerDeletePerformed": False,
        "deterministicBlobNameSha256": sha256_text(blob_name),
        "deterministicObjectId": object_id,
        "deterministicObjectVersionId": object_version_id,
        "expectedProviderVersionSha256": expected_provider_hash,
        "httpStatusAfter": after.status_code,
        "httpStatusBefore": before.status_code,
        "marker": "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED",
        "multipleVersionDeletePerformed": False,
        "paginationAfter": continuation_after,
        "paginationBefore": continuation_before,
        "requestIdSha256After": sha256_text(after.headers.get("x-ms-request-id", "")),
        "requestIdSha256Before": sha256_text(before.headers.get("x-ms-request-id", "")),
        "responseBodySha256After": hashlib.sha256(after.content).hexdigest(),
        "responseBodySha256Before": hashlib.sha256(before.content).hexdigest(),
        "schemaVersion": "mobius.milestone-7.7.scanner-canary-cleanup-job.v1",
        "wildcardUsed": False,
    }
    evidence["integritySha256"] = hashlib.sha256(DOMAIN + canonical(evidence)).hexdigest()
    print(json.dumps(evidence, separators=(",", ":"), sort_keys=True), flush=True)
    return 0


async def main():
    try:
        return await run()
    except BaseException as exc:
        candidate = str(exc)
        failure_code = (
            candidate
            if re.fullmatch(r"scanner-canary-cleanup-[a-z0-9-]+", candidate)
            else "scanner-canary-cleanup-execution-failed"
        )
        print(
            json.dumps(
                {
                    "failureCode": failure_code,
                    "marker": "IMAGE_EIGHT_CANARY_RESIDUE_CLEANUP_FAILED",
                    "rawCredentialsRetained": False,
                    "schemaVersion": "mobius.milestone-7.7.scanner-canary-cleanup-failure.v1",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


raise SystemExit(asyncio.run(main()))
""".strip()


class ScannerCanaryCleanupExecutionError(RuntimeError):
    """Raised when exact cleanup or authoritative reconciliation is unproved."""


def _fail(code: str) -> NoReturn:
    raise ScannerCanaryCleanupExecutionError(code)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(code)


def _outside_repository(path: Path, code: str) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        _fail(code)
    return resolved


def _same_resource_id(value: object, expected: str) -> bool:
    return isinstance(value, str) and value.casefold() == expected.casefold()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _claim_authorization(
    *,
    authorization: ScannerCanaryCleanupAuthorization,
    receipt_directory: Path,
    now_utc: datetime,
) -> Path:
    directory = _outside_repository(
        receipt_directory, "scanner-canary-cleanup-receipts-inside-repository"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECEIPT_FILE
    body: dict[str, JsonValue] = {
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "claimedAtUtc": _format_utc(now_utc),
        "oneUseDecision": "deny-replay",
        "receiptVersion": RECEIPT_VERSION,
        "repositoryHead": authorization.repositoryHead,
    }
    receipt: dict[str, JsonValue] = {
        **body,
        "receiptIntegritySha256": integrity_sha256(body, RECEIPT_DOMAIN),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-canary-cleanup-authorization-already-consumed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("scanner-canary-cleanup-receipt-write-failed")
    return path


def _write_json_exclusive(path: Path, value: dict[str, JsonValue], code: str) -> None:
    resolved = _outside_repository(
        path, "scanner-canary-cleanup-evidence-inside-repository"
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail(code)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("scanner-canary-cleanup-evidence-write-failed")


def _validate_managed_binding(authorization: ScannerCanaryCleanupAuthorization) -> None:
    contract = load_managed_binding_contract()
    groups = contract.get("resourceGroups")
    resources = contract.get("resources")
    cleanup = contract.get("cleanupExecution")
    if (
        not isinstance(groups, dict)
        or not isinstance(resources, dict)
        or not isinstance(cleanup, dict)
    ):
        _fail("scanner-canary-cleanup-managed-binding-malformed")
    exact = {
        "target": groups.get("target") == TARGET_RESOURCE_GROUP,
        "storage": STORAGE_ACCOUNT == "stmobius7711564669",
        "worker": WORKER_IDENTITY == "id-mobius77-worker",
        "environment": resources.get("containerAppsEnvironment") == MANAGED_ENVIRONMENT,
        "cleanup-account": (
            resources.get("cleanupAutomationAccount") == "aa-mobius77-cleanup-recovery"
        ),
        "cleanup-deadline": cleanup.get("deadlineUtc")
        == authorization.cleanupDeadlineUtc,
        "cleanup-target": cleanup.get("targetResourceGroup") == TARGET_RESOURCE_GROUP,
    }
    if not all(exact.values()):
        _fail("scanner-canary-cleanup-managed-binding-drift")


def _proof_resource_ids(
    authorization: ScannerCanaryCleanupAuthorization,
) -> tuple[str, str]:
    return (
        f"{authorization.targetResourceGroupId}/providers/Microsoft.App/jobs/{PROOF_JOB}",
        (
            f"{authorization.targetResourceGroupId}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{PROOF_ROLE_DEFINITION_NAME}"
        ),
    )


def _verify_proof_resources_absent(
    authorization: ScannerCanaryCleanupAuthorization,
) -> None:
    proof_job_id, proof_role_id = _proof_resource_ids(authorization)
    if not scanner_adapter._resource_absent(proof_job_id, JOB_API_VERSION):
        _fail("scanner-canary-cleanup-proof-job-present")
    if not scanner_adapter._resource_absent(proof_role_id, ROLE_API_VERSION):
        _fail("scanner-canary-cleanup-proof-role-present")
    rows = scanner_adapter._role_assignment_rows(
        authorization.subscriptionId, scope=authorization.quarantineContainerId
    )
    if any(_same_resource_id(row["roleDefinitionId"], proof_role_id) for row in rows):
        _fail("scanner-canary-cleanup-proof-assignment-present")


def _verify_temporary_resources_absent(
    authorization: ScannerCanaryCleanupAuthorization,
) -> None:
    for resource_id, api_version in (
        (authorization.cleanupRoleAssignmentId, ROLE_API_VERSION),
        (authorization.cleanupJobId, JOB_API_VERSION),
        (authorization.cleanupRoleDefinitionId, ROLE_API_VERSION),
    ):
        if not scanner_adapter._resource_absent(resource_id, api_version):
            _fail("scanner-canary-cleanup-temporary-resource-present")


def _verify_permanent_reader(authorization: ScannerCanaryCleanupAuthorization) -> str:
    identity = scanner_adapter._rest_get(
        authorization.workerIdentityId,
        IDENTITY_API_VERSION,
        "{id:id,clientId:properties.clientId,principalId:properties.principalId}",
    )
    client_id = identity.get("clientId")
    if (
        not _same_resource_id(identity.get("id"), authorization.workerIdentityId)
        or identity.get("principalId") != authorization.cleanupPrincipalId
        or not isinstance(client_id, str)
        or not client_id
    ):
        _fail("scanner-canary-cleanup-principal-readback-unproved")
    rows = scanner_adapter._role_assignment_rows(
        authorization.subscriptionId, scope=authorization.quarantineContainerId
    )
    worker_rows = [
        row
        for row in rows
        if row["principalId"].casefold() == authorization.cleanupPrincipalId.casefold()
    ]
    expected_role = (
        f"/subscriptions/{authorization.subscriptionId}/providers/"
        f"Microsoft.Authorization/roleDefinitions/{WORKER_QUARANTINE_ROLE}"
    )
    if (
        len(worker_rows) != 1
        or not _same_resource_id(worker_rows[0]["scope"], authorization.cleanupScope)
        or not _same_resource_id(worker_rows[0]["roleDefinitionId"], expected_role)
    ):
        _fail("scanner-canary-cleanup-permanent-reader-drift")
    role = scanner_adapter._rest_get(
        expected_role,
        ROLE_API_VERSION,
        "{actions:properties.permissions[0].actions,dataActions:properties.permissions[0].dataActions,notActions:properties.permissions[0].notActions,notDataActions:properties.permissions[0].notDataActions}",
    )
    if role != {
        "actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/read"],
        "dataActions": [
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read",
        ],
        "notActions": [],
        "notDataActions": [],
    }:
        _fail("scanner-canary-cleanup-permanent-reader-drift")
    container = scanner_adapter._rest_get(
        authorization.quarantineContainerId,
        STORAGE_API_VERSION,
        "{id:id,publicAccess:properties.publicAccess}",
    )
    if not _same_resource_id(
        container.get("id"), authorization.quarantineContainerId
    ) or container.get("publicAccess") not in (None, "None"):
        _fail("scanner-canary-cleanup-container-readback-unproved")
    environment = scanner_adapter._rest_get(
        authorization.managedEnvironmentId,
        MANAGED_ENVIRONMENT_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState}",
    )
    if (
        not _same_resource_id(environment.get("id"), authorization.managedEnvironmentId)
        or environment.get("provisioningState") != "Succeeded"
    ):
        _fail("scanner-canary-cleanup-environment-readback-unproved")
    return client_id


def _role_definition_body(
    authorization: ScannerCanaryCleanupAuthorization,
) -> dict[str, JsonValue]:
    return {
        "properties": {
            "assignableScopes": [authorization.targetResourceGroupId],
            "description": "Temporary authority to delete one exact retained Image Eight canary version.",
            "permissions": _CLEANUP_ROLE_PERMISSIONS,
            "roleName": CLEANUP_ROLE_NAME,
            "type": "CustomRole",
        }
    }


def _role_assignment_body(
    authorization: ScannerCanaryCleanupAuthorization,
) -> dict[str, JsonValue]:
    return {
        "properties": {
            "principalId": authorization.cleanupPrincipalId,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": authorization.cleanupRoleDefinitionId,
        }
    }


def _job_environment(
    authorization: ScannerCanaryCleanupAuthorization, worker_client_id: str
) -> list[JsonValue]:
    return [
        {
            "name": "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL",
            "value": f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/",
        },
        {
            "name": "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID",
            "value": worker_client_id,
        },
        {
            "name": "OPENCANVAS_CANARY_CLEANUP_AUTHORIZATION_SHA256",
            "value": authorization.authorizationIntegritySha256,
        },
        {
            "name": "OPENCANVAS_CANARY_CLEANUP_DEADLINE_UTC",
            "value": authorization.cleanupDeadlineUtc,
        },
        {
            "name": "OPENCANVAS_CANARY_CLEANUP_BLOB_NAME",
            "value": authorization.deterministicBlobName,
        },
        {
            "name": "OPENCANVAS_CANARY_CLEANUP_OBJECT_ID",
            "value": authorization.deterministicObjectId,
        },
        {
            "name": "OPENCANVAS_CANARY_CLEANUP_OBJECT_VERSION_ID",
            "value": authorization.deterministicObjectVersionId,
        },
        {
            "name": "OPENCANVAS_CANARY_CLEANUP_PROVIDER_VERSION_SHA256",
            "value": authorization.expectedProviderVersionSha256,
        },
    ]


def _job_tags(authorization: ScannerCanaryCleanupAuthorization) -> dict[str, str]:
    return {
        "mobius-authorization-sha256": authorization.authorizationIntegritySha256,
        "mobius-cleanup-deadline-utc": authorization.cleanupDeadlineUtc,
        "mobius-contract-version": "m7.7-exact-image-eight-canary-cleanup-v1",
        "mobius-control-plane-head": authorization.repositoryHead,
        "mobius-data-class": "isolated-synthetic",
        "mobius-public-access": "denied",
    }


def _job_body(
    authorization: ScannerCanaryCleanupAuthorization, worker_client_id: str
) -> dict[str, object]:
    return {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {authorization.workerIdentityId: {}},
        },
        "location": STAGING_LOCATION,
        "properties": {
            "configuration": {
                "manualTriggerConfig": {
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                },
                "registries": [
                    {
                        "identity": authorization.workerIdentityId,
                        "server": REGISTRY_HOST,
                    }
                ],
                "replicaRetryLimit": 0,
                "replicaTimeout": 600,
                "triggerType": "Manual",
            },
            "environmentId": authorization.managedEnvironmentId,
            "template": {
                "containers": [
                    {
                        "args": ["-c", _CLEANUP_PROGRAM],
                        "command": ["python"],
                        "env": _job_environment(authorization, worker_client_id),
                        "image": authorization.apiImageDigest,
                        "name": CLEANUP_CONTAINER,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ]
            },
            "workloadProfileName": "Consumption",
        },
        "tags": _job_tags(authorization),
    }


def _write_request_body(path: Path, value: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
        newline="\n",
    )


def _put_and_reconcile(
    *,
    resource_id: str,
    api_version: str,
    body_path: Path,
    query: str,
) -> dict[str, JsonValue]:
    error: lifecycle.AzureCommandError | None = None
    try:
        lifecycle._run(
            (
                "az",
                "rest",
                "--method",
                "put",
                "--url",
                f"https://management.azure.com{resource_id}?api-version={api_version}",
                "--body",
                f"@{body_path}",
                "--output",
                "none",
                "--only-show-errors",
            ),
            timeout_seconds=300,
        )
    except lifecycle.AzureCommandError as exc:
        error = exc
    deadline = time.monotonic() + RESOURCE_PROPAGATION_SECONDS
    while True:
        try:
            return scanner_adapter._rest_get(resource_id, api_version, query)
        except lifecycle.AzureCommandError as exc:
            if not scanner_adapter._not_found(exc) or time.monotonic() >= deadline:
                if error is not None:
                    raise error
                raise
            time.sleep(RESOURCE_POLL_SECONDS)


def _create_cleanup_graph(
    authorization: ScannerCanaryCleanupAuthorization,
    *,
    worker_client_id: str,
    request_directory: Path,
) -> None:
    role_path = request_directory / "role-definition.json"
    assignment_path = request_directory / "role-assignment.json"
    job_path = request_directory / "job.json"
    _write_request_body(role_path, _role_definition_body(authorization))
    _write_request_body(assignment_path, _role_assignment_body(authorization))
    _write_request_body(job_path, _job_body(authorization, worker_client_id))
    _put_and_reconcile(
        resource_id=authorization.cleanupRoleDefinitionId,
        api_version=ROLE_API_VERSION,
        body_path=role_path,
        query="{id:id}",
    )
    _put_and_reconcile(
        resource_id=authorization.cleanupRoleAssignmentId,
        api_version=ROLE_API_VERSION,
        body_path=assignment_path,
        query="{id:id}",
    )
    _put_and_reconcile(
        resource_id=authorization.cleanupJobId,
        api_version=JOB_API_VERSION,
        body_path=job_path,
        query="{id:id}",
    )


def _cleanup_graph_integrity(
    authorization: ScannerCanaryCleanupAuthorization, *, worker_client_id: str
) -> str:
    role = scanner_adapter._rest_get(
        authorization.cleanupRoleDefinitionId,
        ROLE_API_VERSION,
        "{id:id,roleName:properties.roleName,assignableScopes:properties.assignableScopes,permissions:properties.permissions}",
    )
    assignment = scanner_adapter._rest_get(
        authorization.cleanupRoleAssignmentId,
        ROLE_API_VERSION,
        "{id:id,principalId:properties.principalId,principalType:properties.principalType,roleDefinitionId:properties.roleDefinitionId}",
    )
    job = scanner_adapter._rest_get(
        authorization.cleanupJobId,
        JOB_API_VERSION,
        "{id:id,provisioningState:properties.provisioningState,triggerType:properties.configuration.triggerType,retryLimit:properties.configuration.replicaRetryLimit,replicaTimeout:properties.configuration.replicaTimeout,parallelism:properties.configuration.manualTriggerConfig.parallelism,completionCount:properties.configuration.manualTriggerConfig.replicaCompletionCount,registries:properties.configuration.registries[].{identity:identity,server:server},environmentId:properties.environmentId,image:properties.template.containers[0].image,container:properties.template.containers[0].name,command:properties.template.containers[0].command,args:properties.template.containers[0].args,environment:properties.template.containers[0].env[].{name:name,value:value},identityIds:keys(identity.userAssignedIdentities),tags:tags}",
    )
    if (
        not _same_resource_id(role.get("id"), authorization.cleanupRoleDefinitionId)
        or role.get("roleName") != CLEANUP_ROLE_NAME
        or role.get("assignableScopes") != [authorization.targetResourceGroupId]
        or role.get("permissions") != _CLEANUP_ROLE_PERMISSIONS
    ):
        _fail("scanner-canary-cleanup-role-readback-unproved")
    if (
        not _same_resource_id(
            assignment.get("id"), authorization.cleanupRoleAssignmentId
        )
        or assignment.get("principalId") != authorization.cleanupPrincipalId
        or assignment.get("principalType") != "ServicePrincipal"
        or not _same_resource_id(
            assignment.get("roleDefinitionId"), authorization.cleanupRoleDefinitionId
        )
    ):
        _fail("scanner-canary-cleanup-assignment-readback-unproved")
    identity_ids = job.get("identityIds")
    exact_job: dict[str, object] = {
        "provisioningState": "Succeeded",
        "triggerType": "Manual",
        "retryLimit": 0,
        "replicaTimeout": 600,
        "parallelism": 1,
        "completionCount": 1,
        "registries": [
            {"identity": authorization.workerIdentityId, "server": REGISTRY_HOST}
        ],
        "environmentId": authorization.managedEnvironmentId,
        "image": authorization.apiImageDigest,
        "container": CLEANUP_CONTAINER,
        "command": ["python"],
        "args": ["-c", _CLEANUP_PROGRAM],
        "environment": _job_environment(authorization, worker_client_id),
        "tags": _job_tags(authorization),
    }
    if (
        not _same_resource_id(job.get("id"), authorization.cleanupJobId)
        or any(job.get(key) != value for key, value in exact_job.items())
        or not isinstance(identity_ids, list)
        or len(identity_ids) != 1
        or not _same_resource_id(identity_ids[0], authorization.workerIdentityId)
    ):
        _fail("scanner-canary-cleanup-job-readback-unproved")
    return integrity_sha256(
        cast(JsonValue, {"assignment": assignment, "job": job, "role": role}),
        b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup-graph/v1\0",
    )


def _wait_for_cleanup_rbac(
    authorization: ScannerCanaryCleanupAuthorization, *, worker_client_id: str
) -> str:
    deadline = time.monotonic() + RBAC_PROPAGATION_SECONDS
    while True:
        try:
            integrity = _cleanup_graph_integrity(
                authorization, worker_client_id=worker_client_id
            )
        except (lifecycle.AzureCommandError, ScannerCanaryCleanupExecutionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(RBAC_POLL_SECONDS)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return integrity
        time.sleep(min(RBAC_POLL_SECONDS, remaining))


def _execution_rows(
    authorization: ScannerCanaryCleanupAuthorization,
) -> list[dict[str, str | None]]:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            CLEANUP_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "[].{name:name,status:properties.status,startTime:properties.startTime,endTime:properties.endTime}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("scanner-canary-cleanup-execution-readback-malformed")
    result: list[dict[str, str | None]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "name",
            "status",
            "startTime",
            "endTime",
        }:
            _fail("scanner-canary-cleanup-execution-readback-malformed")
        if not isinstance(row.get("name"), str) or not isinstance(
            row.get("status"), str
        ):
            _fail("scanner-canary-cleanup-execution-readback-malformed")
        if any(
            item is not None and not isinstance(item, str)
            for item in (row.get("startTime"), row.get("endTime"))
        ):
            _fail("scanner-canary-cleanup-execution-readback-malformed")
        result.append(cast(dict[str, str | None], row))
    return result


def _start_one_execution(authorization: ScannerCanaryCleanupAuthorization) -> str:
    if _execution_rows(authorization):
        _fail("scanner-canary-cleanup-duplicate-execution-present")
    requested_name: str | None = None
    with suppress(lifecycle.AzureCommandError):
        value = lifecycle._run(
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--name",
                CLEANUP_JOB,
                "--resource-group",
                TARGET_RESOURCE_GROUP,
                "--subscription",
                authorization.subscriptionId,
                "--query",
                "name",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if isinstance(value, str) and value:
            requested_name = value
    deadline = time.monotonic() + 120.0
    while True:
        rows = _execution_rows(authorization)
        if len(rows) == 1:
            name = rows[0]["name"]
            if isinstance(name, str) and (
                requested_name is None or requested_name == name
            ):
                return name
        if len(rows) > 1:
            _fail("scanner-canary-cleanup-duplicate-execution-created")
        if time.monotonic() >= deadline:
            _fail("scanner-canary-cleanup-execution-start-unproved")
        time.sleep(RESOURCE_POLL_SECONDS)


def _wait_for_execution(
    authorization: ScannerCanaryCleanupAuthorization, execution_name: str
) -> dict[str, str | None]:
    deadline = time.monotonic() + EXECUTION_PROPAGATION_SECONDS
    while True:
        rows = _execution_rows(authorization)
        matching = [row for row in rows if row["name"] == execution_name]
        if len(rows) != 1 or len(matching) != 1:
            _fail("scanner-canary-cleanup-execution-reconciliation-drift")
        row = matching[0]
        terminal = row["status"] in {
            "Succeeded",
            "Failed",
            "Degraded",
            "Stopped",
            "Cancelled",
        }
        if terminal and row["startTime"] is not None:
            return row
        if time.monotonic() >= deadline:
            _fail("scanner-canary-cleanup-execution-timeout")
        time.sleep(EXECUTION_POLL_SECONDS)


def _log_output(
    authorization: ScannerCanaryCleanupAuthorization, execution_name: str
) -> str:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "logs",
            "show",
            "--name",
            CLEANUP_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--execution",
            execution_name,
            "--container",
            CLEANUP_CONTAINER,
            "--tail",
            "100",
            "--format",
            "json",
            "--subscription",
            authorization.subscriptionId,
            "--only-show-errors",
        ),
        require_text=True,
    )
    if not isinstance(value, str) or len(value.encode()) > 1_048_576:
        _fail("scanner-canary-cleanup-log-output-malformed")
    return value


def _json_markers(value: object, marker_name: str) -> tuple[dict[str, object], ...]:
    found: list[dict[str, object]] = []
    if isinstance(value, Mapping):
        if value.get("marker") == marker_name:
            found.append(dict(value))
        for child in value.values():
            found.extend(_json_markers(child, marker_name))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found.extend(_json_markers(child, marker_name))
    elif isinstance(value, str):
        decoder = json.JSONDecoder()
        for offset, character in enumerate(value):
            if character != "{":
                continue
            with suppress(json.JSONDecodeError):
                parsed, _ = decoder.raw_decode(value, offset)
                found.extend(_json_markers(parsed, marker_name))
    return tuple(found)


def _cleanup_marker(
    authorization: ScannerCanaryCleanupAuthorization, execution_name: str
) -> dict[str, JsonValue]:
    output = _log_output(authorization, execution_name)
    markers = _json_markers(output, "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED")
    if len(markers) != 1:
        failures = _json_markers(output, "IMAGE_EIGHT_CANARY_RESIDUE_CLEANUP_FAILED")
        if len(failures) == 1:
            failure_code = failures[0].get("failureCode")
            if isinstance(failure_code, str) and _FAILURE_CODE.fullmatch(failure_code):
                _fail(failure_code)
        _fail("scanner-canary-cleanup-marker-unproved")
    marker = cast(dict[str, JsonValue], markers[0])
    expected_fields = {
        "afterActiveVersionCount",
        "afterDeletedVersionCount",
        "authorizationIntegritySha256",
        "beforeActiveVersionCount",
        "beforeDeletedVersionCount",
        "cleanupDeadlineUtc",
        "cleanupInvocationCount",
        "containerDeletePerformed",
        "deterministicBlobNameSha256",
        "deterministicObjectId",
        "deterministicObjectVersionId",
        "expectedProviderVersionSha256",
        "httpStatusAfter",
        "httpStatusBefore",
        "integritySha256",
        "marker",
        "multipleVersionDeletePerformed",
        "paginationAfter",
        "paginationBefore",
        "requestIdSha256After",
        "requestIdSha256Before",
        "responseBodySha256After",
        "responseBodySha256Before",
        "schemaVersion",
        "wildcardUsed",
    }
    if set(marker) != expected_fields:
        _fail("scanner-canary-cleanup-marker-malformed")
    integrity = marker.pop("integritySha256", None)
    calculated = hashlib.sha256(
        JOB_MARKER_DOMAIN
        + json.dumps(marker, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    marker["integritySha256"] = integrity
    exact: dict[str, JsonValue] = {
        "afterActiveVersionCount": 0,
        "afterDeletedVersionCount": 0,
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "beforeActiveVersionCount": 1,
        "beforeDeletedVersionCount": 0,
        "cleanupDeadlineUtc": authorization.cleanupDeadlineUtc,
        "cleanupInvocationCount": 1,
        "containerDeletePerformed": False,
        "deterministicBlobNameSha256": _hash_text(authorization.deterministicBlobName),
        "deterministicObjectId": authorization.deterministicObjectId,
        "deterministicObjectVersionId": authorization.deterministicObjectVersionId,
        "expectedProviderVersionSha256": EXPECTED_PROVIDER_VERSION_SHA256,
        "httpStatusAfter": 200,
        "httpStatusBefore": 200,
        "marker": "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED",
        "multipleVersionDeletePerformed": False,
        "paginationAfter": False,
        "paginationBefore": False,
        "schemaVersion": "mobius.milestone-7.7.scanner-canary-cleanup-job.v1",
        "wildcardUsed": False,
    }
    if (
        not isinstance(integrity, str)
        or integrity != calculated
        or any(marker.get(key) != expected for key, expected in exact.items())
    ):
        _fail("scanner-canary-cleanup-marker-integrity-unproved")
    hash_fields = {
        "requestIdSha256After",
        "requestIdSha256Before",
        "responseBodySha256After",
        "responseBodySha256Before",
    }
    if any(
        not isinstance(marker.get(key), str)
        or _SHA256.fullmatch(cast(str, marker[key])) is None
        for key in hash_fields
    ):
        _fail("scanner-canary-cleanup-marker-malformed")
    return marker


def _remove_cleanup_resources(
    authorization: ScannerCanaryCleanupAuthorization,
) -> str:
    try:
        lifecycle._delete_assignment(
            authorization.subscriptionId, authorization.cleanupRoleAssignmentId
        )
    except lifecycle.AzureCommandError:
        if not scanner_adapter._resource_absent(
            authorization.cleanupRoleAssignmentId, ROLE_API_VERSION
        ):
            raise
    scanner_adapter._wait_absent(
        authorization.cleanupRoleAssignmentId,
        ROLE_API_VERSION,
        "scanner-canary-cleanup-assignment-revocation-unproved",
    )
    scanner_adapter._delete_rest_resource(authorization.cleanupJobId, JOB_API_VERSION)
    scanner_adapter._wait_absent(
        authorization.cleanupJobId,
        JOB_API_VERSION,
        "scanner-canary-cleanup-job-deletion-unproved",
    )
    scanner_adapter._delete_rest_resource(
        authorization.cleanupRoleDefinitionId, ROLE_API_VERSION
    )
    scanner_adapter._wait_absent(
        authorization.cleanupRoleDefinitionId,
        ROLE_API_VERSION,
        "scanner-canary-cleanup-role-deletion-unproved",
    )
    return integrity_sha256(
        cast(
            JsonValue,
            {
                "job": "absent",
                "roleAssignment": "absent",
                "roleDefinition": "absent",
            },
        ),
        b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup-revocation/v1\0",
    )


def _build_evidence(
    *,
    authorization: ScannerCanaryCleanupAuthorization,
    execution_name: str,
    execution: Mapping[str, str | None],
    marker: Mapping[str, JsonValue],
    graph_integrity: str,
    revocation_integrity: str,
    observed_at: datetime,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "authorityRevoked": True,
        "authorizationConsumed": True,
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "cleanupControlExecutableAndArmed": True,
        "cleanupDeadlineUtc": authorization.cleanupDeadlineUtc,
        "cleanupGraphIntegritySha256": graph_integrity,
        "cleanupInvocationCount": 1,
        "deterministicBlobNameSha256": _hash_text(authorization.deterministicBlobName),
        "deterministicObjectId": authorization.deterministicObjectId,
        "deterministicObjectVersionId": authorization.deterministicObjectVersionId,
        "evidenceVersion": EVIDENCE_VERSION,
        "executionNameSha256": _hash_text(execution_name),
        "executionStartTimeSha256": _hash_text(cast(str, execution["startTime"])),
        "expectedProviderVersionSha256": authorization.expectedProviderVersionSha256,
        "jobEvidenceIntegritySha256": cast(str, marker["integritySha256"]),
        "marker": "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED",
        "observedAtUtc": _format_utc(observed_at),
        "proofResourcesAbsent": True,
        "repositoryHead": authorization.repositoryHead,
        "residueAbsent": True,
        "revocationIntegritySha256": revocation_integrity,
        "temporaryCleanupAuthorityAbsent": True,
    }
    return {
        **body,
        "evidenceIntegritySha256": integrity_sha256(body, EVIDENCE_DOMAIN),
    }


class ProductionScannerCanaryCleanupAdapter:
    """Consume one exact-version cleanup grant through existing Azure primitives."""

    def __init__(self, *, clock: Callable[[], datetime] = lifecycle._utc_now) -> None:
        self._clock = clock

    def execute(
        self,
        *,
        authorization: ScannerCanaryCleanupAuthorization,
        receipt_directory: Path,
        expected_repository_head: str,
        evidence_output: Path,
    ) -> dict[str, JsonValue]:
        now = self._clock().astimezone(UTC).replace(microsecond=0)
        validate_scanner_canary_cleanup_authorization(
            authorization,
            expected_repository_head=expected_repository_head,
            now_utc=now,
        )
        lifecycle._verify_repository_state(expected_repository_head)
        subscription_id = lifecycle._account_binding(now)
        if subscription_id != authorization.subscriptionId:
            _fail("scanner-canary-cleanup-subscription-mismatch")
        if not lifecycle._group_exists(subscription_id, TARGET_RESOURCE_GROUP):
            _fail("scanner-canary-cleanup-target-resource-group-missing")
        _validate_managed_binding(authorization)
        _, maximum_cost = lifecycle._verified_cost()
        if maximum_cost > authorization.maximumCostUsdCents:
            _fail("scanner-canary-cleanup-cost-ceiling-exceeded")
        cleanup_at = _parse_utc(
            authorization.cleanupDeadlineUtc,
            "scanner-canary-cleanup-deadline-invalid",
        )
        cleanup_principal = lifecycle._verify_cleanup_control(
            subscription_id, cleanup_at
        )
        lifecycle._verify_cleanup_target_role(
            subscription_id,
            cleanup_principal,
            "b24988ac-6180-42a0-ab88-20f7382dd24c",
        )
        _verify_proof_resources_absent(authorization)
        _verify_temporary_resources_absent(authorization)
        worker_client_id = _verify_permanent_reader(authorization)
        _claim_authorization(
            authorization=authorization,
            receipt_directory=receipt_directory,
            now_utc=now,
        )
        marker: dict[str, JsonValue]
        execution: dict[str, str | None]
        execution_name: str
        graph_integrity: str
        revocation_integrity: str
        with tempfile.TemporaryDirectory(
            prefix="mobius77-scanner-canary-cleanup-"
        ) as directory:
            try:
                _create_cleanup_graph(
                    authorization,
                    worker_client_id=worker_client_id,
                    request_directory=Path(directory),
                )
                graph_integrity = _wait_for_cleanup_rbac(
                    authorization, worker_client_id=worker_client_id
                )
                execution_name = _start_one_execution(authorization)
                execution = _wait_for_execution(authorization, execution_name)
                if execution["status"] != "Succeeded":
                    _cleanup_marker(authorization, execution_name)
                    _fail("scanner-canary-cleanup-execution-failed")
                marker = _cleanup_marker(authorization, execution_name)
            finally:
                revocation_integrity = _remove_cleanup_resources(authorization)
        _verify_temporary_resources_absent(authorization)
        _verify_proof_resources_absent(authorization)
        lifecycle._verify_cleanup_control(subscription_id, cleanup_at)
        lifecycle._verify_cleanup_target_role(
            subscription_id,
            cleanup_principal,
            "b24988ac-6180-42a0-ab88-20f7382dd24c",
        )
        evidence = _build_evidence(
            authorization=authorization,
            execution_name=execution_name,
            execution=execution,
            marker=marker,
            graph_integrity=graph_integrity,
            revocation_integrity=revocation_integrity,
            observed_at=self._clock().astimezone(UTC).replace(microsecond=0),
        )
        _write_json_exclusive(
            evidence_output,
            evidence,
            "scanner-canary-cleanup-evidence-already-exists",
        )
        return {
            "authorization-consumed": True,
            "authorization-integrity-sha256": authorization.authorizationIntegritySha256,
            "authority-revoked": True,
            "cleanup-executable-and-armed": True,
            "evidence-integrity-sha256": evidence["evidenceIntegritySha256"],
            "marker": "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED",
            "proof-resources-absent": True,
            "residue-absent": True,
            "status": "image-eight-canary-residue-cleaned",
            "temporary-cleanup-authority-absent": True,
        }


__all__ = [
    "ProductionScannerCanaryCleanupAdapter",
    "ScannerCanaryCleanupExecutionError",
]
