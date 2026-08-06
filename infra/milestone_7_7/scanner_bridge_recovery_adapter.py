"""Production adapter for the two narrow private scanner-bridge stages."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn, cast

from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    load_managed_binding_contract,
    managed_binding_integrity_sha256,
)
from preflight.milestone_7_7.scanner_bridge_recovery import (
    FOUNDATION_STAGE,
    LOG_ANALYTICS_WORKSPACE,
    PROOF_JOB,
    PROOF_STAGE,
    STORAGE_ACCOUNT,
    TARGET_RESOURCE_GROUP,
    ScannerBridgeRecoveryAuthorization,
    validate_scanner_bridge_recovery_authorization,
)
from preflight.milestone_7_7.scanner_result_bridge import (
    PROVIDER,
    SCHEMA_VERSION,
    TRANSPORT,
    ScannerResultBridgeDeploymentEvidence,
    ScannerResultBridgeEvidence,
    build_scanner_result_bridge_deployment_evidence,
)

RECEIPT_VERSION: Final = "mobius.milestone-7.7.scanner-bridge-recovery-receipt.v1"
RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-bridge-recovery-receipt/v1\0"
)
FOUNDATION_RECEIPT_FILE: Final = "scanner-bridge-foundation.receipt.json"
PROOF_RECEIPT_FILE: Final = "scanner-bridge-proof.receipt.json"
EVIDENCE_DOMAIN: Final = b"mobius.milestone-7.7.scanner-bridge-live-proof/v1\0"

STORAGE_API_VERSION: Final = "2025-06-01"
DEFENDER_API_VERSION: Final = "2025-06-01"
DIAGNOSTIC_API_VERSION: Final = "2021-05-01-preview"
AMPLS_API_VERSION: Final = "2021-09-01"
PRIVATE_ENDPOINT_API_VERSION: Final = "2024-10-01"
PRIVATE_DNS_API_VERSION: Final = "2024-06-01"
IDENTITY_API_VERSION: Final = "2024-11-30"
ROLE_API_VERSION: Final = "2022-04-01"
JOB_API_VERSION: Final = "2025-01-01"
EVENT_GRID_API_VERSION: Final = "2025-02-15"

STAGING_LOCATION: Final = "southcentralus"
_USAGE_DECIMAL_INTEGER: Final = re.compile(r"(?:0|[1-9][0-9]{0,19})")
VIRTUAL_NETWORK: Final = "vnet-mobius77-staging"
PRIVATE_ENDPOINT_SUBNET: Final = "snet-mobius77-private-endpoints"
STORAGE_PRIVATE_ENDPOINT: Final = "pe-mobius77-storage"
API_IDENTITY: Final = "id-mobius77-api"
DEFENDER_SCANNER: Final = "StorageDataScanner"
DEFENDER_SCANNER_ROLE: Final = "cd50fd1f-0421-46f2-8cce-afc587dbcc77"
LOG_ANALYTICS_READER_ROLE: Final = "73c42c96-874c-492b-b04d-ab87d138a893"
API_QUARANTINE_ROLE: Final = "43c7bdad-b8f9-4d4b-9881-ae8af70cf269"
API_CLEAN_READER_ROLE: Final = "a59d0f11-7f62-4699-97d9-6c8565ba77a4"
WORKER_QUARANTINE_ROLE: Final = "292f18b2-0b41-4a86-a4af-46cd22d2e52e"
WORKER_CLEAN_ROLE: Final = "6ecfca2a-29a1-4802-a236-706d77995e21"
TAG_WRITE_ACTION: Final = (
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write"
)
PROOF_CONTAINER: Final = "scanner-bridge-proof"
FOUNDATION_POLL_SECONDS: Final = 15.0
FOUNDATION_PROPAGATION_SECONDS: Final = 900.0
EXECUTION_POLL_SECONDS: Final = 15.0
EXECUTION_PROPAGATION_SECONDS: Final = 3_900.0
PROOF_GRAPH_POLL_SECONDS: Final = 5.0
PROOF_GRAPH_PROPAGATION_SECONDS: Final = 300.0
DELETION_POLL_SECONDS: Final = 5.0
DELETION_PROPAGATION_SECONDS: Final = 180.0

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_REQUIREMENTS: Final = (
    ("Microsoft.Storage", "storageAccounts", STORAGE_API_VERSION, True),
    ("Microsoft.Security", "defenderForStorageSettings", DEFENDER_API_VERSION, False),
    ("Microsoft.Insights", "diagnosticSettings", DIAGNOSTIC_API_VERSION, False),
    ("Microsoft.Insights", "privateLinkScopes", AMPLS_API_VERSION, False),
    ("Microsoft.OperationalInsights", "workspaces", "2026-03-01", True),
    ("Microsoft.Network", "privateEndpoints", PRIVATE_ENDPOINT_API_VERSION, True),
    ("Microsoft.Network", "privateDnsZones", PRIVATE_DNS_API_VERSION, False),
    ("Microsoft.ManagedIdentity", "userAssignedIdentities", IDENTITY_API_VERSION, True),
    ("Microsoft.EventGrid", "systemTopics", EVENT_GRID_API_VERSION, True),
    ("Microsoft.App", "jobs", JOB_API_VERSION, True),
)


class ScannerBridgeRecoveryExecutionError(RuntimeError):
    """Raised when production mutation or authoritative reconciliation is unproved."""


@dataclass(frozen=True, slots=True)
class _FoundationReadback:
    api_principal_id: str
    worker_principal_id: str
    worker_client_id: str
    workspace_customer_id: str
    provider_topic_id: str
    provider_proof_integrity: str
    diagnostic_proof_integrity: str
    rbac_proof_integrity: str
    tag_write_denial_integrity: str
    private_path_control_plane_integrity: str
    inventory_integrity: str


def _fail(code: str) -> NoReturn:
    raise ScannerBridgeRecoveryExecutionError(code)


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


def _json_object(value: JsonValue | None, code: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        _fail(code)
    return value


def _canonical_hash(value: JsonValue, domain: str) -> str:
    return integrity_sha256(value, domain.encode() + b"\0")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _same_resource_id(value: JsonValue | None, expected: str) -> bool:
    return isinstance(value, str) and value.casefold() == expected.casefold()


def _claim_authorization(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    receipt_directory: Path,
    now_utc: datetime,
) -> Path:
    directory = _outside_repository(
        receipt_directory, "scanner-bridge-receipts-inside-repository"
    )
    directory.mkdir(parents=True, exist_ok=True)
    filename = (
        FOUNDATION_RECEIPT_FILE
        if authorization.stage == FOUNDATION_STAGE
        else PROOF_RECEIPT_FILE
    )
    path = directory / filename
    body: dict[str, JsonValue] = {
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "claimedAtUtc": _format_utc(now_utc),
        "receiptVersion": RECEIPT_VERSION,
        "replayDecision": "deny",
        "repositoryHead": authorization.repositoryHead,
        "stage": authorization.stage,
    }
    receipt: dict[str, JsonValue] = {
        **body,
        "receiptIntegritySha256": integrity_sha256(body, RECEIPT_DOMAIN),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-bridge-authorization-already-consumed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("scanner-bridge-receipt-write-failed")
    return path


def _write_evidence(
    path: Path, evidence: ScannerResultBridgeDeploymentEvidence
) -> None:
    resolved = _outside_repository(path, "scanner-bridge-evidence-inside-repository")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    value = cast(JsonValue, evidence.canonical())
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("scanner-bridge-evidence-already-exists")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("scanner-bridge-evidence-write-failed")


def _validate_managed_binding(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> dict[str, JsonValue]:
    contract = load_managed_binding_contract()
    resources = contract.get("resources")
    groups = contract.get("resourceGroups")
    cleanup = contract.get("cleanupExecution")
    if (
        not isinstance(resources, dict)
        or not isinstance(groups, dict)
        or not isinstance(cleanup, dict)
    ):
        _fail("scanner-bridge-managed-binding-malformed")
    exact = {
        "target-group": groups.get("target") == TARGET_RESOURCE_GROUP,
        "storage-account": STORAGE_ACCOUNT == "stmobius7711564669",
        "workspace": resources.get("logAnalyticsWorkspace") == LOG_ANALYTICS_WORKSPACE,
        "cleanup-account": resources.get("cleanupAutomationAccount")
        == "aa-mobius77-cleanup-recovery",
        "cleanup-deadline": cleanup.get("deadlineUtc")
        == authorization.cleanupDeadlineUtc,
        "cleanup-target": cleanup.get("targetResourceGroup") == TARGET_RESOURCE_GROUP,
    }
    if not all(exact.values()):
        _fail("scanner-bridge-managed-binding-drift")
    return contract


def _deployment_binding(
    authorization: ScannerBridgeRecoveryAuthorization,
    contract: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "authorizationId": (
            f"scanner-bridge-{authorization.stage}-"
            f"{authorization.authorizationIntegritySha256[:24]}"
        ),
        "ledgerIntegritySha256": authorization.authorizationIntegritySha256,
        "managedBindingIntegritySha256": managed_binding_integrity_sha256(contract),
        "repositoryHead": authorization.repositoryHead,
    }


def _verify_provider_api_versions(subscription_id: str) -> None:
    for namespace, resource_type, version, regional in _PROVIDER_REQUIREMENTS:
        value = lifecycle._run(
            (
                "az",
                "provider",
                "show",
                "--namespace",
                namespace,
                "--subscription",
                subscription_id,
                "--query",
                (
                    "{registrationState:registrationState,"
                    f"resourceType:resourceTypes[?resourceType=='{resource_type}']|[0]}}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        row = _json_object(value, "scanner-bridge-provider-metadata-malformed")
        metadata = row.get("resourceType")
        if row.get("registrationState") != "Registered" or not isinstance(
            metadata, dict
        ):
            _fail("scanner-bridge-provider-unavailable")
        versions = metadata.get("apiVersions")
        locations = metadata.get("locations")
        if (
            metadata.get("resourceType") != resource_type
            or not isinstance(versions, list)
            or version not in versions
            or not isinstance(locations, list)
        ):
            _fail("scanner-bridge-provider-api-version-unavailable")
        normalized_locations = {
            location.replace(" ", "").casefold()
            for location in locations
            if isinstance(location, str)
        }
        if regional and STAGING_LOCATION not in normalized_locations:
            _fail("scanner-bridge-provider-region-unavailable")


def _network_usage_integer(value: JsonValue) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and _USAGE_DECIMAL_INTEGER.fullmatch(value) is not None:
        return int(value)
    _fail("scanner-bridge-network-quota-malformed")


def _verify_network_capacity(subscription_id: str) -> None:
    value = lifecycle._run(
        (
            "az",
            "network",
            "list-usages",
            "--location",
            STAGING_LOCATION,
            "--subscription",
            subscription_id,
            "--query",
            "[?name.value=='PrivateEndpoints'].{current:currentValue,limit:limit}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        _fail("scanner-bridge-network-quota-malformed")
    current = _network_usage_integer(value[0].get("current"))
    limit = _network_usage_integer(value[0].get("limit"))
    if current + 2 > limit:
        _fail("scanner-bridge-network-quota-insufficient")


def _rest_get(resource_id: str, api_version: str, query: str) -> dict[str, JsonValue]:
    value = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={api_version}",
            "--query",
            query,
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    return _json_object(value, "scanner-bridge-resource-readback-malformed")


def _rest_collection(resource_id: str, api_version: str, query: str) -> JsonValue:
    return lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{resource_id}?api-version={api_version}",
            "--query",
            query,
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )


def _output_values(value: JsonValue | None) -> dict[str, JsonValue]:
    raw = _json_object(value, "scanner-bridge-deployment-output-malformed")
    result: dict[str, JsonValue] = {}
    for name, projection in raw.items():
        if not isinstance(projection, dict) or set(projection) - {"type", "value"}:
            _fail("scanner-bridge-deployment-output-malformed")
        result[name] = projection.get("value")
    return result


def _read_deployment_outputs(
    *, subscription_id: str, stage: str, binding: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    deployment_name = lifecycle._deployment_name(stage, binding)
    deadline = time.monotonic() + 120.0
    while True:
        try:
            raw = lifecycle._run(
                (
                    "az",
                    "deployment",
                    "sub",
                    "show",
                    "--name",
                    deployment_name,
                    "--subscription",
                    subscription_id,
                    "--query",
                    "properties.outputs",
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                require_json=True,
            )
            return _output_values(raw)
        except (lifecycle.AzureCommandError, ScannerBridgeRecoveryExecutionError):
            if time.monotonic() >= deadline:
                _fail("scanner-bridge-deployment-reconciliation-unproved")
            time.sleep(5.0)


def _validate_deployment_outputs(
    authorization: ScannerBridgeRecoveryAuthorization,
    outputs: Mapping[str, JsonValue],
) -> str | None:
    exact: dict[str, JsonValue] = {
        "deploymentStage": authorization.stage,
        "deploymentEnabled": False,
        "managedBindingDeploymentEnabled": True,
        "targetResourceGroupName": TARGET_RESOURCE_GROUP,
        "scannerBridgeFoundationDeployed": True,
        "scannerBridgeTransport": TRANSPORT,
        "scannerBridgeStorageAccountId": authorization.storageAccountId,
        "scannerBridgePrivateLinkScopeId": authorization.privateLinkScopeId,
        "scannerBridgePrivateEndpointId": authorization.monitorPrivateEndpointId,
        "scannerBridgeWorkerIdentityId": authorization.workerIdentityId,
        "scannerBridgeWorkerTagWriteAuthorized": False,
        "defaultProvisioningAuthorized": False,
        "secretValueAccessAuthorized": False,
        "storageAccountUrl": f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/",
    }
    if any(outputs.get(key) != value for key, value in exact.items()):
        _fail("scanner-bridge-deployment-output-drift")
    principal_id = outputs.get("scannerBridgeWorkerPrincipalId")
    if not isinstance(principal_id, str) or _UUID.fullmatch(principal_id) is None:
        _fail("scanner-bridge-worker-principal-unproved")
    if authorization.stage == FOUNDATION_STAGE:
        empty = {
            "scannerBridgeProofJobName": "",
            "scannerBridgeProofJobId": "",
            "scannerBridgeTemporaryRoleId": "",
            "scannerBridgeTemporaryRoleAssignmentId": "",
            "scannerBridgeProofImageDigest": "",
        }
        if any(outputs.get(key) != value for key, value in empty.items()):
            _fail("scanner-foundation-proof-authority-reachable")
        return None
    proof_exact: dict[str, JsonValue] = {
        "scannerBridgeProofJobName": PROOF_JOB,
        "scannerBridgeProofJobId": authorization.proofJobId,
        "scannerBridgeTemporaryRoleId": authorization.proofRoleDefinitionId,
        "scannerBridgeProofImageDigest": authorization.apiImageDigest,
    }
    if any(outputs.get(key) != value for key, value in proof_exact.items()):
        _fail("scanner-proof-deployment-output-drift")
    assignment_id = outputs.get("scannerBridgeTemporaryRoleAssignmentId")
    quarantine_scope = (
        f"{authorization.storageAccountId}/blobServices/default/containers/quarantine"
    )
    prefix = f"{quarantine_scope}/providers/Microsoft.Authorization/roleAssignments/"
    if not isinstance(assignment_id, str) or not assignment_id.casefold().startswith(
        prefix.casefold()
    ):
        _fail("scanner-proof-role-assignment-output-invalid")
    return assignment_id


def _role_assignment_rows(
    subscription_id: str,
    *,
    principal_id: str | None = None,
    scope: str | None = None,
) -> list[dict[str, str]]:
    argv: list[str] = ["az", "role", "assignment", "list"]
    if principal_id is not None:
        argv.extend(("--assignee-object-id", principal_id, "--all"))
    if scope is not None:
        argv.extend(("--scope", scope, "--include-inherited"))
    if principal_id is None and scope is None:
        argv.append("--all")
    argv.extend(
        (
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    value = lifecycle._run(tuple(argv), require_json=True)
    if not isinstance(value, list):
        _fail("scanner-bridge-role-assignment-readback-malformed")
    result: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "principalId",
            "roleDefinitionId",
            "scope",
        }:
            _fail("scanner-bridge-role-assignment-readback-malformed")
        if not all(isinstance(item, str) and item for item in row.values()):
            _fail("scanner-bridge-role-assignment-readback-malformed")
        result.append(cast(dict[str, str], row))
    return result


def _storage_role_assignment_rows(
    subscription_id: str, storage_account_id: str
) -> list[dict[str, str]]:
    """Return every assignment inherited by or nested below the storage account."""

    inherited = _role_assignment_rows(subscription_id, scope=storage_account_id)
    subscription_rows = _role_assignment_rows(subscription_id)
    normalized_storage = storage_account_id.rstrip("/").casefold()
    descendants = [
        row
        for row in subscription_rows
        if row["scope"].rstrip("/").casefold().startswith(f"{normalized_storage}/")
    ]
    by_id = {row["id"].casefold(): row for row in [*inherited, *descendants]}
    return sorted(by_id.values(), key=lambda row: row["id"].casefold())


def _role_permissions(
    role_definition_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    row = _rest_get(
        role_definition_id,
        ROLE_API_VERSION,
        "{permissions:properties.permissions}",
    )
    permissions = row.get("permissions")
    if not isinstance(permissions, list) or not permissions:
        _fail("scanner-bridge-role-definition-readback-malformed")
    data_actions: list[str] = []
    not_data_actions: list[str] = []
    for permission in permissions:
        if not isinstance(permission, dict):
            _fail("scanner-bridge-role-definition-readback-malformed")
        granted = permission.get("dataActions")
        denied = permission.get("notDataActions")
        if (
            not isinstance(granted, list)
            or not all(isinstance(value, str) for value in granted)
            or not isinstance(denied, list)
            or not all(isinstance(value, str) for value in denied)
        ):
            _fail("scanner-bridge-role-definition-readback-malformed")
        data_actions.extend(cast(list[str], granted))
        not_data_actions.extend(cast(list[str], denied))
    return tuple(data_actions), tuple(not_data_actions)


def _grants_tag_write(role_definition_id: str) -> bool:
    data_actions, denied = _role_permissions(role_definition_id)
    target = TAG_WRITE_ACTION.casefold()
    granted = any(
        fnmatch.fnmatchcase(target, action.casefold()) for action in data_actions
    )
    explicitly_denied = any(
        fnmatch.fnmatchcase(target, action.casefold()) for action in denied
    )
    return granted and not explicitly_denied


def _role_name(role_definition_id: str) -> str:
    return role_definition_id.rstrip("/").rsplit("/", 1)[-1].casefold()


def _verify_ordinary_identity_roles(
    *,
    subscription_id: str,
    principal_id: str,
    expected: frozenset[tuple[str, str]],
) -> tuple[list[dict[str, str]], str]:
    rows = _role_assignment_rows(subscription_id, principal_id=principal_id)
    projected = {
        (_role_name(row["roleDefinitionId"]), row["scope"].casefold()) for row in rows
    }
    if not expected.issubset(projected):
        _fail("scanner-bridge-required-role-assignment-absent")
    for row in rows:
        if _grants_tag_write(row["roleDefinitionId"]):
            _fail("scanner-bridge-ordinary-identity-tag-write-authorized")
    value = cast(JsonValue, sorted(rows, key=lambda row: row["id"].casefold()))
    return rows, _canonical_hash(value, "mobius.scanner-bridge.identity-rbac.v1")


def _identity_projection(resource_id: str) -> dict[str, JsonValue]:
    return _rest_get(
        resource_id,
        IDENTITY_API_VERSION,
        "{id:id,clientId:properties.clientId,principalId:properties.principalId}",
    )


def _verify_private_endpoint(
    *, resource_id: str, service_id: str, group_id: str, subnet_id: str
) -> dict[str, JsonValue]:
    row = _rest_get(
        resource_id,
        PRIVATE_ENDPOINT_API_VERSION,
        "{id:id,subnetId:properties.subnet.id,connections:"
        "properties.privateLinkServiceConnections[].{serviceId:properties.privateLinkServiceId,"
        "groupIds:properties.groupIds,status:properties.privateLinkServiceConnectionState.status}}",
    )
    connections = row.get("connections")
    if (
        row.get("id") != resource_id
        or row.get("subnetId") != subnet_id
        or not isinstance(connections, list)
        or len(connections) != 1
        or connections[0]
        != {"serviceId": service_id, "groupIds": [group_id], "status": "Approved"}
    ):
        _fail("scanner-bridge-private-endpoint-unproved")
    return row


def _verify_private_dns_zone_group(
    *, private_endpoint_id: str, expected_zone_ids: frozenset[str]
) -> dict[str, JsonValue]:
    group_id = f"{private_endpoint_id}/privateDnsZoneGroups/default"
    row = _rest_get(
        group_id,
        PRIVATE_ENDPOINT_API_VERSION,
        "{id:id,zoneIds:properties.privateDnsZoneConfigs[].properties.privateDnsZoneId}",
    )
    zone_ids = row.get("zoneIds")
    if (
        row.get("id") != group_id
        or not isinstance(zone_ids, list)
        or any(not isinstance(value, str) for value in zone_ids)
        or {cast(str, value).casefold() for value in zone_ids}
        != {value.casefold() for value in expected_zone_ids}
    ):
        _fail("scanner-bridge-private-dns-zone-group-unproved")
    return row


def _foundation_readback_once(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> _FoundationReadback:
    subscription_id = authorization.subscriptionId
    target = authorization.targetResourceGroupId
    vnet_id = f"{target}/providers/Microsoft.Network/virtualNetworks/{VIRTUAL_NETWORK}"
    subnet_id = f"{vnet_id}/subnets/{PRIVATE_ENDPOINT_SUBNET}"
    storage = _rest_get(
        authorization.storageAccountId,
        STORAGE_API_VERSION,
        "{id:id,location:location,kind:kind,sku:sku.name,"
        "publicNetworkAccess:properties.publicNetworkAccess,"
        "allowSharedKeyAccess:properties.allowSharedKeyAccess,"
        "allowBlobPublicAccess:properties.allowBlobPublicAccess,"
        "defaultToOAuthAuthentication:properties.defaultToOAuthAuthentication,"
        "minimumTlsVersion:properties.minimumTlsVersion,"
        "supportsHttpsTrafficOnly:properties.supportsHttpsTrafficOnly,"
        "networkDefaultAction:properties.networkAcls.defaultAction,"
        "networkBypass:properties.networkAcls.bypass,"
        "resourceAccessRules:properties.networkAcls.resourceAccessRules}",
    )
    scanner_resource_id = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Security/"
        f"dataScanners/{DEFENDER_SCANNER}"
    )
    expected_storage: dict[str, JsonValue] = {
        "id": authorization.storageAccountId,
        "location": STAGING_LOCATION,
        "kind": "StorageV2",
        "sku": "Standard_LRS",
        "publicNetworkAccess": "Disabled",
        "allowSharedKeyAccess": False,
        "allowBlobPublicAccess": False,
        "defaultToOAuthAuthentication": True,
        "minimumTlsVersion": "TLS1_2",
        "supportsHttpsTrafficOnly": True,
        "networkDefaultAction": "Deny",
        "networkBypass": "None",
    }
    if any(storage.get(key) != value for key, value in expected_storage.items()):
        _fail("scanner-bridge-storage-security-boundary-unproved")
    access_rules = storage.get("resourceAccessRules")
    if (
        not isinstance(access_rules, list)
        or len(access_rules) != 1
        or not isinstance(access_rules[0], dict)
        or set(access_rules[0]) != {"resourceId", "tenantId"}
        or not isinstance(access_rules[0].get("tenantId"), str)
        or _UUID.fullmatch(cast(str, access_rules[0]["tenantId"])) is None
        or not isinstance(access_rules[0].get("resourceId"), str)
        or cast(str, access_rules[0]["resourceId"]).casefold()
        != scanner_resource_id.casefold()
    ):
        _fail("scanner-bridge-storage-scanner-network-access-unproved")

    blob_service_id = f"{authorization.storageAccountId}/blobServices/default"
    blob_service = _rest_get(
        blob_service_id,
        STORAGE_API_VERSION,
        "{id:id,versioning:properties.isVersioningEnabled,"
        "softDeleteEnabled:properties.deleteRetentionPolicy.enabled,"
        "softDeleteDays:properties.deleteRetentionPolicy.days,"
        "permanentDeleteEnabled:properties.deleteRetentionPolicy.allowPermanentDelete}",
    )
    if blob_service != {
        "id": blob_service_id,
        "versioning": True,
        "softDeleteEnabled": True,
        "softDeleteDays": 7,
        "permanentDeleteEnabled": True,
    }:
        _fail("scanner-bridge-storage-versioning-unproved")
    container_rows: list[dict[str, JsonValue]] = []
    for container in ("quarantine", "clean", "rejected", "retained"):
        container_id = f"{blob_service_id}/containers/{container}"
        row = _rest_get(
            container_id,
            STORAGE_API_VERSION,
            "{id:id,publicAccess:properties.publicAccess,"
            "denyEncryptionScopeOverride:properties.denyEncryptionScopeOverride}",
        )
        if (
            row.get("id") != container_id
            or row.get("publicAccess") not in {None, "None"}
            or row.get("denyEncryptionScopeOverride") is not True
        ):
            _fail("scanner-bridge-container-security-boundary-unproved")
        container_rows.append(row)

    defender_id = (
        f"{authorization.storageAccountId}/providers/Microsoft.Security/"
        "defenderForStorageSettings/current"
    )
    defender = _rest_get(
        defender_id,
        DEFENDER_API_VERSION,
        "{id:id,isEnabled:properties.isEnabled,"
        "override:properties.overrideSubscriptionLevelSettings,"
        "malwareScanning:properties.malwareScanning,"
        "sensitiveDataDiscovery:properties.sensitiveDataDiscovery}",
    )
    malware = defender.get("malwareScanning")
    discovery = defender.get("sensitiveDataDiscovery")
    if (
        defender.get("id") != defender_id
        or defender.get("isEnabled") is not True
        or defender.get("override") is not True
        or not isinstance(malware, dict)
        or malware.get("blobScanResultsOptions") != "BlobIndexTags"
        or bool(malware.get("scanResultsEventGridTopicResourceId"))
        or not isinstance(malware.get("onUpload"), dict)
        or cast(dict[str, JsonValue], malware["onUpload"]).get("isEnabled") is not True
        or cast(dict[str, JsonValue], malware["onUpload"]).get("capGBPerMonth") != 1
        or not isinstance(discovery, dict)
        or discovery.get("isEnabled") is not False
    ):
        _fail("scanner-bridge-defender-setting-unproved")

    diagnostic_id = (
        f"{defender_id}/providers/Microsoft.Insights/diagnosticSettings/"
        "mobius77-defender-scan-results"
    )
    diagnostic = _rest_get(
        diagnostic_id,
        DIAGNOSTIC_API_VERSION,
        "{id:id,workspaceId:properties.workspaceId,logs:properties.logs}",
    )
    logs = diagnostic.get("logs")
    if (
        not _same_resource_id(diagnostic.get("id"), diagnostic_id)
        or not isinstance(diagnostic.get("workspaceId"), str)
        or cast(str, diagnostic["workspaceId"]).casefold()
        != authorization.logAnalyticsWorkspaceId.casefold()
        or not isinstance(logs, list)
        or not any(
            isinstance(log, dict)
            and log.get("category") == "ScanResults"
            and log.get("enabled") is True
            for log in logs
        )
    ):
        _fail("scanner-bridge-log-analytics-diagnostic-unproved")

    workspace = _rest_get(
        authorization.logAnalyticsWorkspaceId,
        "2026-03-01",
        "{id:id,customerId:properties.customerId,"
        "publicIngestion:properties.publicNetworkAccessForIngestion,"
        "publicQuery:properties.publicNetworkAccessForQuery,"
        "resourcePermissionsOnly:properties.features.enableLogAccessUsingOnlyResourcePermissions,"
        "retentionDays:properties.retentionInDays,dailyQuotaGb:properties.workspaceCapping.dailyQuotaGb}",
    )
    workspace_customer_id = workspace.get("customerId")
    if (
        workspace.get("id") != authorization.logAnalyticsWorkspaceId
        or not isinstance(workspace_customer_id, str)
        or _UUID.fullmatch(workspace_customer_id) is None
        or workspace.get("publicIngestion") != "Disabled"
        or workspace.get("publicQuery") != "Disabled"
        or workspace.get("resourcePermissionsOnly") is not True
        or workspace.get("retentionDays") != 30
        or workspace.get("dailyQuotaGb") != 2
    ):
        _fail("scanner-bridge-workspace-readback-unproved")

    ampls = _rest_get(
        authorization.privateLinkScopeId,
        AMPLS_API_VERSION,
        "{id:id,queryAccessMode:properties.accessModeSettings.queryAccessMode,"
        "ingestionAccessMode:properties.accessModeSettings.ingestionAccessMode,"
        "exclusions:properties.accessModeSettings.exclusions}",
    )
    if (
        not _same_resource_id(ampls.get("id"), authorization.privateLinkScopeId)
        or ampls.get("queryAccessMode") != "PrivateOnly"
        or ampls.get("ingestionAccessMode") != "PrivateOnly"
        or ampls.get("exclusions") != []
    ):
        _fail("scanner-bridge-ampls-private-only-unproved")
    scoped_id = (
        f"{authorization.privateLinkScopeId}/scopedResources/{LOG_ANALYTICS_WORKSPACE}"
    )
    scoped = _rest_get(
        scoped_id,
        AMPLS_API_VERSION,
        "{id:id,linkedResourceId:properties.linkedResourceId}",
    )
    if (
        not _same_resource_id(scoped.get("id"), scoped_id)
        or not isinstance(scoped.get("linkedResourceId"), str)
        or cast(str, scoped["linkedResourceId"]).casefold()
        != authorization.logAnalyticsWorkspaceId.casefold()
    ):
        _fail("scanner-bridge-ampls-workspace-association-unproved")

    storage_pe_id = f"{target}/providers/Microsoft.Network/privateEndpoints/{STORAGE_PRIVATE_ENDPOINT}"
    storage_pe = _verify_private_endpoint(
        resource_id=storage_pe_id,
        service_id=authorization.storageAccountId,
        group_id="blob",
        subnet_id=subnet_id,
    )
    monitor_pe = _verify_private_endpoint(
        resource_id=authorization.monitorPrivateEndpointId,
        service_id=authorization.privateLinkScopeId,
        group_id="azuremonitor",
        subnet_id=subnet_id,
    )
    required_zones = (
        "privatelink.blob.core.windows.net",
        "privatelink.monitor.azure.com",
        "privatelink.oms.opinsights.azure.com",
        "privatelink.ods.opinsights.azure.com",
        "privatelink.agentsvc.azure-automation.net",
    )
    zone_rows: list[dict[str, JsonValue]] = []
    for zone in required_zones:
        zone_id = f"{target}/providers/Microsoft.Network/privateDnsZones/{zone}"
        row = _rest_get(zone_id, PRIVATE_DNS_API_VERSION, "{id:id,location:location}")
        if row != {"id": zone_id, "location": "global"}:
            _fail("scanner-bridge-private-dns-zone-unproved")
        zone_rows.append(row)
    zone_ids = {
        zone: f"{target}/providers/Microsoft.Network/privateDnsZones/{zone}"
        for zone in required_zones
    }
    storage_zone_group = _verify_private_dns_zone_group(
        private_endpoint_id=storage_pe_id,
        expected_zone_ids=frozenset({zone_ids["privatelink.blob.core.windows.net"]}),
    )
    monitor_zone_group = _verify_private_dns_zone_group(
        private_endpoint_id=authorization.monitorPrivateEndpointId,
        expected_zone_ids=frozenset(zone_ids.values()),
    )

    worker = _identity_projection(authorization.workerIdentityId)
    api_identity_id = f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{API_IDENTITY}"
    api_identity = _identity_projection(api_identity_id)
    worker_principal = worker.get("principalId")
    worker_client = worker.get("clientId")
    api_principal = api_identity.get("principalId")
    if (
        not _same_resource_id(worker.get("id"), authorization.workerIdentityId)
        or not _same_resource_id(api_identity.get("id"), api_identity_id)
        or not isinstance(worker_principal, str)
        or _UUID.fullmatch(worker_principal) is None
        or not isinstance(worker_client, str)
        or _UUID.fullmatch(worker_client) is None
        or not isinstance(api_principal, str)
        or _UUID.fullmatch(api_principal) is None
    ):
        _fail("scanner-bridge-identity-readback-unproved")

    quarantine_scope = f"{blob_service_id}/containers/quarantine"
    clean_scope = f"{blob_service_id}/containers/clean"
    worker_expected = frozenset(
        {
            (WORKER_QUARANTINE_ROLE, quarantine_scope.casefold()),
            (WORKER_CLEAN_ROLE, clean_scope.casefold()),
            (
                LOG_ANALYTICS_READER_ROLE,
                authorization.logAnalyticsWorkspaceId.casefold(),
            ),
        }
    )
    api_expected = frozenset(
        {
            (API_QUARANTINE_ROLE, quarantine_scope.casefold()),
            (API_CLEAN_READER_ROLE, clean_scope.casefold()),
        }
    )
    worker_rows, worker_rbac = _verify_ordinary_identity_roles(
        subscription_id=subscription_id,
        principal_id=worker_principal,
        expected=worker_expected,
    )
    api_rows, api_rbac = _verify_ordinary_identity_roles(
        subscription_id=subscription_id,
        principal_id=api_principal,
        expected=api_expected,
    )

    scanner = lifecycle._run(
        (
            "az",
            "resource",
            "show",
            "--ids",
            scanner_resource_id,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id,principalId:identity.principalId}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    scanner_row = _json_object(scanner, "scanner-bridge-storage-scanner-malformed")
    scanner_principal = scanner_row.get("principalId")
    if (
        not isinstance(scanner_row.get("id"), str)
        or cast(str, scanner_row["id"]).casefold() != scanner_resource_id.casefold()
        or not isinstance(scanner_principal, str)
        or _UUID.fullmatch(scanner_principal) is None
    ):
        _fail("scanner-bridge-storage-scanner-identity-unproved")
    storage_rows = _storage_role_assignment_rows(
        subscription_id, authorization.storageAccountId
    )
    tag_writers = [
        row for row in storage_rows if _grants_tag_write(row["roleDefinitionId"])
    ]
    if len(tag_writers) != 1:
        _fail("scanner-bridge-tag-writer-boundary-unproved")
    writer = tag_writers[0]
    if (
        writer["principalId"].casefold() != scanner_principal.casefold()
        or _role_name(writer["roleDefinitionId"]) != DEFENDER_SCANNER_ROLE
        or writer["scope"].casefold() != authorization.storageAccountId.casefold()
    ):
        _fail("scanner-bridge-unauthorized-tag-writer-present")

    topics_collection = f"{target}/providers/Microsoft.EventGrid/systemTopics"
    topics = _rest_collection(
        topics_collection,
        EVENT_GRID_API_VERSION,
        "value[].{id:id,source:properties.source,topicType:properties.topicType}",
    )
    if not isinstance(topics, list):
        _fail("scanner-bridge-provider-topic-readback-malformed")
    provider_topics = [
        topic
        for topic in topics
        if isinstance(topic, dict)
        and isinstance(topic.get("source"), str)
        and cast(str, topic["source"]).casefold()
        == authorization.storageAccountId.casefold()
        and isinstance(topic.get("topicType"), str)
        and cast(str, topic["topicType"]).casefold()
        == "microsoft.storage.storageaccounts"
        and isinstance(topic.get("id"), str)
    ]
    if len(provider_topics) != 1:
        _fail("scanner-bridge-provider-topic-unproved")
    custom_topics = _rest_collection(
        f"{target}/providers/Microsoft.EventGrid/topics",
        EVENT_GRID_API_VERSION,
        "value[].id",
    )
    if custom_topics != []:
        _fail("scanner-bridge-custom-push-topic-present")

    private_projection = cast(
        JsonValue,
        {
            "ampls": ampls,
            "monitorPrivateEndpoint": monitor_pe,
            "monitorPrivateDnsZoneGroup": monitor_zone_group,
            "scopedWorkspace": scoped,
            "storagePrivateEndpoint": storage_pe,
            "storagePrivateDnsZoneGroup": storage_zone_group,
            "zones": zone_rows,
        },
    )
    rbac_projection = cast(
        JsonValue,
        {"api": api_rows, "worker": worker_rows, "storage": storage_rows},
    )
    inventory = cast(
        JsonValue,
        {
            "blobService": blob_service,
            "containers": container_rows,
            "customTopics": custom_topics,
            "providerTopics": topics,
            "storage": storage,
        },
    )
    return _FoundationReadback(
        api_principal_id=api_principal,
        worker_principal_id=worker_principal,
        worker_client_id=worker_client,
        workspace_customer_id=workspace_customer_id,
        provider_topic_id=cast(str, provider_topics[0]["id"]),
        provider_proof_integrity=_canonical_hash(
            cast(JsonValue, defender), "mobius.scanner-bridge.provider.v1"
        ),
        diagnostic_proof_integrity=_canonical_hash(
            cast(JsonValue, diagnostic), "mobius.scanner-bridge.diagnostic.v1"
        ),
        rbac_proof_integrity=_canonical_hash(
            rbac_projection, "mobius.scanner-bridge.rbac.v1"
        ),
        tag_write_denial_integrity=_canonical_hash(
            cast(
                JsonValue,
                {
                    "api": api_rbac,
                    "authorizedWriter": writer,
                    "worker": worker_rbac,
                },
            ),
            "mobius.scanner-bridge.tag-writer-boundary.v1",
        ),
        private_path_control_plane_integrity=_canonical_hash(
            private_projection, "mobius.scanner-bridge.private-path-control-plane.v1"
        ),
        inventory_integrity=_canonical_hash(
            inventory, "mobius.scanner-bridge.foundation-inventory.v1"
        ),
    )


def _verify_foundation(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> _FoundationReadback:
    deadline = time.monotonic() + FOUNDATION_PROPAGATION_SECONDS
    while True:
        try:
            return _foundation_readback_once(authorization)
        except (lifecycle.AzureCommandError, ScannerBridgeRecoveryExecutionError):
            if time.monotonic() >= deadline:
                _fail("scanner-bridge-foundation-readback-unproved")
            time.sleep(FOUNDATION_POLL_SECONDS)


def _proof_graph(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    assignment_id: str,
    worker_principal_id: str,
    worker_client_id: str,
    workspace_customer_id: str,
) -> str:
    if authorization.proofJobId is None or authorization.proofRoleDefinitionId is None:
        _fail("scanner-proof-authorization-incomplete")
    job = _rest_get(
        authorization.proofJobId,
        JOB_API_VERSION,
        "{id:id,triggerType:properties.configuration.triggerType,"
        "retryLimit:properties.configuration.replicaRetryLimit,"
        "parallelism:properties.configuration.manualTriggerConfig.parallelism,"
        "completionCount:properties.configuration.manualTriggerConfig.replicaCompletionCount,"
        "image:properties.template.containers[0].image,"
        "container:properties.template.containers[0].name,"
        "command:properties.template.containers[0].command,"
        "args:properties.template.containers[0].args,"
        "environment:properties.template.containers[0].env[].{name:name,value:value},"
        "identityIds:keys(identity.userAssignedIdentities)}",
    )
    expected_environment: list[JsonValue] = [
        {
            "name": "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL",
            "value": f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/",
        },
        {"name": "OPENCANVAS_AZURE_QUARANTINE_CONTAINER", "value": "quarantine"},
        {"name": "OPENCANVAS_AZURE_CLEAN_CONTAINER", "value": "clean"},
        {"name": "OPENCANVAS_AZURE_REJECTED_CONTAINER", "value": "rejected"},
        {"name": "OPENCANVAS_AZURE_RETAINED_CONTAINER", "value": "retained"},
        {
            "name": "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID",
            "value": worker_client_id,
        },
        {
            "name": "OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID",
            "value": workspace_customer_id,
        },
        {
            "name": "OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT",
            "value": "https://api.loganalytics.azure.com",
        },
        {
            "name": "OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED",
            "value": authorization.authorizationIntegritySha256,
        },
    ]
    job_projection = {
        key: value for key, value in job.items() if key not in {"id", "identityIds"}
    }
    identity_ids = job.get("identityIds")
    if (
        job_projection
        != {
            "triggerType": "Manual",
            "retryLimit": 0,
            "parallelism": 1,
            "completionCount": 1,
            "image": authorization.apiImageDigest,
            "container": PROOF_CONTAINER,
            "command": ["python"],
            "args": [
                "-m",
                "scripts.scanner_bridge_probe",
                "--max-attempts",
                "60",
                "--delay-seconds",
                "30",
            ],
            "environment": expected_environment,
        }
        or not _same_resource_id(job.get("id"), authorization.proofJobId)
        or not (
            isinstance(identity_ids, list)
            and len(identity_ids) == 1
            and _same_resource_id(identity_ids[0], authorization.workerIdentityId)
        )
    ):
        _fail("scanner-proof-job-readback-unproved")
    role = _rest_get(
        authorization.proofRoleDefinitionId,
        ROLE_API_VERSION,
        "{id:id,roleName:properties.roleName,assignableScopes:properties.assignableScopes,"
        "permissions:properties.permissions}",
    )
    permissions = role.get("permissions")
    assignable_scopes = role.get("assignableScopes")
    exact_permissions: list[JsonValue] = [
        {
            "actions": [
                "Microsoft.Storage/storageAccounts/blobServices/containers/read"
            ],
            "dataActions": [
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/deleteBlobVersion/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/permanentDelete/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read",
            ],
            "notActions": [],
            "notDataActions": [],
        }
    ]
    if (
        not _same_resource_id(role.get("id"), authorization.proofRoleDefinitionId)
        or role.get("roleName") != "Mobius77 Temporary Scanner Bridge Probe"
        or not (
            isinstance(assignable_scopes, list)
            and len(assignable_scopes) == 1
            and _same_resource_id(
                assignable_scopes[0], authorization.targetResourceGroupId
            )
        )
        or permissions != exact_permissions
        or _grants_tag_write(authorization.proofRoleDefinitionId)
    ):
        _fail("scanner-proof-role-definition-readback-unproved")
    assignment = _rest_get(
        assignment_id,
        ROLE_API_VERSION,
        "{id:id,principalId:properties.principalId,roleDefinitionId:properties.roleDefinitionId}",
    )
    quarantine_scope = (
        f"{authorization.storageAccountId}/blobServices/default/containers/quarantine"
    )
    assignment_principal = assignment.get("principalId")
    if (
        not _same_resource_id(assignment.get("id"), assignment_id)
        or not isinstance(assignment_principal, str)
        or assignment_principal.casefold() != worker_principal_id.casefold()
        or not isinstance(assignment.get("roleDefinitionId"), str)
        or cast(str, assignment["roleDefinitionId"]).casefold()
        != authorization.proofRoleDefinitionId.casefold()
        or not assignment_id.casefold().startswith(
            f"{quarantine_scope}/providers/Microsoft.Authorization/roleAssignments/".casefold()
        )
    ):
        _fail("scanner-proof-role-assignment-readback-unproved")
    return _canonical_hash(
        cast(JsonValue, {"assignment": assignment, "job": job, "role": role}),
        "mobius.scanner-bridge.proof-graph.v1",
    )


def _job_execution_rows(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> list[dict[str, str | None]]:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            PROOF_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "[].{name:name,status:properties.status,startTime:properties.startTime,"
            "endTime:properties.endTime}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("scanner-proof-execution-readback-malformed")
    result: list[dict[str, str | None]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "name",
            "status",
            "startTime",
            "endTime",
        }:
            _fail("scanner-proof-execution-readback-malformed")
        if not isinstance(row.get("name"), str) or not isinstance(
            row.get("status"), str
        ):
            _fail("scanner-proof-execution-readback-malformed")
        if any(
            item is not None and not isinstance(item, str)
            for item in (row.get("startTime"), row.get("endTime"))
        ):
            _fail("scanner-proof-execution-readback-malformed")
        result.append(cast(dict[str, str | None], row))
    return result


def _start_one_execution(authorization: ScannerBridgeRecoveryAuthorization) -> str:
    initial = _job_execution_rows(authorization)
    if initial:
        _fail("scanner-proof-duplicate-execution-present")
    requested_name: str | None = None
    try:
        value = lifecycle._run(
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--name",
                PROOF_JOB,
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
    except lifecycle.AzureCommandError:
        requested_name = None
    deadline = time.monotonic() + 120.0
    while True:
        rows = _job_execution_rows(authorization)
        if len(rows) == 1:
            name = rows[0]["name"]
            if isinstance(name, str) and (
                requested_name is None or requested_name == name
            ):
                return name
        if len(rows) > 1:
            _fail("scanner-proof-duplicate-execution-created")
        if time.monotonic() >= deadline:
            _fail("scanner-proof-execution-start-unproved")
        time.sleep(5.0)


def _wait_for_execution(
    authorization: ScannerBridgeRecoveryAuthorization, execution_name: str
) -> dict[str, str | None]:
    deadline = time.monotonic() + EXECUTION_PROPAGATION_SECONDS
    while True:
        rows = _job_execution_rows(authorization)
        matching = [row for row in rows if row["name"] == execution_name]
        if len(rows) != 1 or len(matching) != 1:
            _fail("scanner-proof-execution-reconciliation-drift")
        row = matching[0]
        status = row["status"]
        if status == "Succeeded":
            if row["startTime"] is None or row["endTime"] is None:
                _fail("scanner-proof-execution-terminal-time-unproved")
            return row
        if status in {"Failed", "Degraded", "Stopped", "Cancelled"}:
            _fail("scanner-proof-execution-failed")
        if time.monotonic() >= deadline:
            _fail("scanner-proof-execution-timeout")
        time.sleep(EXECUTION_POLL_SECONDS)


def _find_marker(value: object) -> dict[str, object] | None:
    if isinstance(value, Mapping):
        if value.get("marker") == "SCANNER_RESULT_BRIDGE_PROVED":
            return dict(value)
        for child in value.values():
            found = _find_marker(child)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found = _find_marker(child)
            if found is not None:
                return found
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return _find_marker(json.loads(stripped))
            except json.JSONDecodeError:
                return None
    return None


def _proof_marker(
    authorization: ScannerBridgeRecoveryAuthorization, execution_name: str
) -> dict[str, str]:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "logs",
            "show",
            "--name",
            PROOF_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--execution",
            execution_name,
            "--container",
            PROOF_CONTAINER,
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
    if not isinstance(value, str) or len(value.encode()) > 65_536:
        _fail("scanner-proof-log-output-malformed")
    marker = _find_marker(value)
    required = {
        "accountNameSha256",
        "blobEvidenceSha256",
        "blobTagResultSha256",
        "blobUriSha256",
        "completionTimeSha256",
        "contentSha256",
        "correlationIdSha256",
        "decision",
        "dualSourceEvidenceSha256",
        "etagSha256",
        "logAnalyticsEvidenceSha256",
        "logQuerySha256",
        "marker",
        "privateDnsEvidenceSha256",
        "providerVersionSha256",
        "residue",
        "scanRequestIdSha256",
        "schemaVersion",
        "storageResourceSha256",
        "tlsEvidenceSha256",
        "tlsHostnameSha256",
        "tlsVersion",
    }
    if marker is None or set(marker) != required:
        _fail("scanner-proof-marker-malformed")
    exact = {
        "decision": "clean",
        "marker": "SCANNER_RESULT_BRIDGE_PROVED",
        "residue": "canary-version-deleted",
        "schemaVersion": "mobius.scanner-result-bridge.proof.v1",
    }
    if any(marker.get(key) != expected for key, expected in exact.items()):
        _fail("scanner-proof-marker-unresolved")
    if marker.get("tlsVersion") not in {"TLS1_2", "TLS1_3"}:
        _fail("scanner-proof-tls-unproved")
    hashes = required - {*exact, "tlsVersion"}
    if any(
        not isinstance(marker.get(key), str)
        or _SHA256.fullmatch(cast(str, marker[key])) is None
        for key in hashes
    ):
        _fail("scanner-proof-marker-integrity-malformed")
    return cast(dict[str, str], marker)


def _not_found(exc: lifecycle.AzureCommandError) -> bool:
    return exc.sanitized_azure_error_code in {
        "notfound",
        "not-found",
        "roleassignmentnotfound",
        "role-assignment-not-found",
        "roledefinitiondoesnotexist",
        "role-definition-does-not-exist",
        "resourcenotfound",
        "resource-not-found",
    }


def _verify_proof_graph(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    assignment_id: str,
    worker_principal_id: str,
    worker_client_id: str,
    workspace_customer_id: str,
) -> str:
    deadline = time.monotonic() + PROOF_GRAPH_PROPAGATION_SECONDS
    while True:
        try:
            return _proof_graph(
                authorization,
                assignment_id=assignment_id,
                worker_principal_id=worker_principal_id,
                worker_client_id=worker_client_id,
                workspace_customer_id=workspace_customer_id,
            )
        except lifecycle.AzureCommandError as exc:
            if not (
                _not_found(exc)
                or exc.sanitized_azure_error_code == "azure-command-nonzero"
            ):
                raise
            if time.monotonic() >= deadline:
                _fail("scanner-proof-graph-propagation-timeout")
            time.sleep(PROOF_GRAPH_POLL_SECONDS)


def _resource_absent(resource_id: str, api_version: str) -> bool:
    try:
        _rest_get(resource_id, api_version, "{id:id}")
    except lifecycle.AzureCommandError as exc:
        if _not_found(exc):
            return True
        raise
    return False


def _wait_absent(resource_id: str, api_version: str, code: str) -> None:
    deadline = time.monotonic() + DELETION_PROPAGATION_SECONDS
    while True:
        if _resource_absent(resource_id, api_version):
            return
        if time.monotonic() >= deadline:
            _fail(code)
        time.sleep(DELETION_POLL_SECONDS)


def _delete_rest_resource(resource_id: str, api_version: str) -> None:
    try:
        lifecycle._run(
            (
                "az",
                "rest",
                "--method",
                "delete",
                "--url",
                f"https://management.azure.com{resource_id}?api-version={api_version}",
                "--output",
                "none",
                "--only-show-errors",
            )
        )
    except lifecycle.AzureCommandError:
        if not _resource_absent(resource_id, api_version):
            raise


def _remove_proof_residue(
    authorization: ScannerBridgeRecoveryAuthorization, assignment_id: str
) -> str:
    if authorization.proofJobId is None or authorization.proofRoleDefinitionId is None:
        _fail("scanner-proof-authorization-incomplete")
    try:
        lifecycle._delete_assignment(authorization.subscriptionId, assignment_id)
    except lifecycle.AzureCommandError:
        if not _resource_absent(assignment_id, ROLE_API_VERSION):
            raise
    _wait_absent(
        assignment_id,
        ROLE_API_VERSION,
        "scanner-proof-role-assignment-revocation-unproved",
    )
    _delete_rest_resource(authorization.proofJobId, JOB_API_VERSION)
    _wait_absent(
        authorization.proofJobId,
        JOB_API_VERSION,
        "scanner-proof-job-deletion-unproved",
    )
    _delete_rest_resource(authorization.proofRoleDefinitionId, ROLE_API_VERSION)
    _wait_absent(
        authorization.proofRoleDefinitionId,
        ROLE_API_VERSION,
        "scanner-proof-role-definition-deletion-unproved",
    )
    return _canonical_hash(
        cast(
            JsonValue,
            {
                "job": "absent",
                "roleAssignment": "absent",
                "roleDefinition": "absent",
            },
        ),
        "mobius.scanner-bridge.proof-residue.v1",
    )


def _build_live_evidence(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    readback: _FoundationReadback,
    execution_name: str,
    execution: Mapping[str, str | None],
    marker: Mapping[str, str],
    proof_graph_integrity: str,
    revocation_integrity: str,
    observed_at: datetime,
) -> ScannerResultBridgeDeploymentEvidence:
    completion_hash = marker["completionTimeSha256"]
    legacy = ScannerResultBridgeEvidence(
        observed_at_utc=_format_utc(observed_at),
        provider=PROVIDER,
        transport=TRANSPORT,
        schema_version=SCHEMA_VERSION,
        proofs={
            "provider": True,
            "resources": True,
            "identity": True,
            "rbac": True,
            "privatePath": True,
            "producer": True,
            "transport": True,
            "consumer": True,
            "schema": True,
            "correlation": True,
            "revocation": True,
        },
        correlation_id_sha256=marker["correlationIdSha256"],
        blob_tag_evidence_sha256=marker["blobEvidenceSha256"],
        log_analytics_evidence_sha256=marker["logAnalyticsEvidenceSha256"],
        object_version_or_etag_sha256=marker["etagSha256"],
        storage_resource_sha256=_hash_text(authorization.storageAccountId),
        completion_time_sha256=completion_hash,
        decision="clean",
    )
    environment = _canonical_hash(
        cast(
            JsonValue,
            {
                "subscription": _hash_text(authorization.subscriptionId),
                "target": _hash_text(authorization.targetResourceGroupId),
            },
        ),
        "mobius.scanner-bridge.environment.v1",
    )
    operation = _hash_text(authorization.authorizationIntegritySha256)
    execution_projection = cast(
        JsonValue,
        {"execution": dict(execution), "marker": dict(marker)},
    )
    consumer_proof = _canonical_hash(
        cast(
            JsonValue,
            {
                "apiImageDigest": authorization.apiImageDigest,
                "execution": execution_projection,
                "sourceHead": authorization.repositoryHead,
            },
        ),
        "mobius.scanner-bridge.consumer-live-proof.v1",
    )
    malicious_contract_proof = _canonical_hash(
        cast(
            JsonValue,
            {
                "proofType": "focused-local-contract-test",
                "repositoryHead": authorization.repositoryHead,
                "test": "private-scanner-bridge-malicious-idempotent-rejection",
            },
        ),
        "mobius.scanner-bridge.malicious-contract-proof.v1",
    )
    evidence = ScannerResultBridgeDeploymentEvidence(
        control_plane_head=authorization.repositoryHead,
        environment_sha256=environment,
        operation_id_sha256=operation,
        observed_at_utc=_format_utc(observed_at),
        legacy_evidence=legacy,
        provider_resource_id_sha256=_hash_text(
            f"{authorization.storageAccountId}/providers/Microsoft.Security/"
            "defenderForStorageSettings/current"
        ),
        provider_api_version=DEFENDER_API_VERSION,
        provider_enabled=True,
        provider_capability_proof_integrity=readback.provider_proof_integrity,
        diagnostic_setting_resource_id_sha256=_hash_text(
            f"{authorization.storageAccountId}/providers/Microsoft.Security/"
            "defenderForStorageSettings/current/providers/Microsoft.Insights/"
            "diagnosticSettings/mobius77-defender-scan-results"
        ),
        storage_resource_id_sha256=_hash_text(authorization.storageAccountId),
        quarantine_container="quarantine",
        blob_identity_sha256=marker["blobUriSha256"],
        content_sha256=marker["contentSha256"],
        scan_request_id_sha256=marker["scanRequestIdSha256"],
        producer_proof_integrity=_canonical_hash(
            cast(
                JsonValue,
                {
                    "account": marker["accountNameSha256"],
                    "blob": marker["blobUriSha256"],
                    "providerVersion": marker["providerVersionSha256"],
                },
            ),
            "mobius.scanner-bridge.producer-live-proof.v1",
        ),
        blob_tag_result_sha256=marker["blobTagResultSha256"],
        log_analytics_workspace_id_sha256=_hash_text(
            authorization.logAnalyticsWorkspaceId
        ),
        log_analytics_table="StorageMalwareScanningResults",
        log_query_sha256=marker["logQuerySha256"],
        dual_source_proof_integrity=marker["dualSourceEvidenceSha256"],
        consumer_identity_sha256=_hash_text(readback.worker_principal_id),
        consumer_entry_point="scripts.worker.DocumentWorker",
        consumer_proof_integrity=consumer_proof,
        blob_reader_role_definition_sha256=_hash_text(WORKER_QUARANTINE_ROLE),
        log_reader_role_definition_sha256=_hash_text(LOG_ANALYTICS_READER_ROLE),
        blob_reader_scope_sha256=_hash_text(
            f"{authorization.storageAccountId}/blobServices/default/containers/quarantine"
        ),
        log_reader_scope_sha256=_hash_text(authorization.logAnalyticsWorkspaceId),
        worker_tag_write_denied=True,
        tag_write_denial_proof_integrity=readback.tag_write_denial_integrity,
        assignment_proof_integrity=proof_graph_integrity,
        ampls_resource_id_sha256=_hash_text(authorization.privateLinkScopeId),
        private_endpoint_resource_id_sha256=_hash_text(
            authorization.monitorPrivateEndpointId
        ),
        private_dns_zone_set_sha256=readback.private_path_control_plane_integrity,
        private_address_sha256=marker["privateDnsEvidenceSha256"],
        tls_hostname_sha256=marker["tlsHostnameSha256"],
        tls_version=marker["tlsVersion"],
        private_path_proof_integrity=_canonical_hash(
            cast(
                JsonValue,
                {
                    "controlPlane": readback.private_path_control_plane_integrity,
                    "dns": marker["privateDnsEvidenceSha256"],
                    "tls": marker["tlsEvidenceSha256"],
                },
            ),
            "mobius.scanner-bridge.private-path-live-proof.v1",
        ),
        proof_job_resource_id_sha256=_hash_text(cast(str, authorization.proofJobId)),
        proof_execution_id_sha256=_hash_text(execution_name),
        clean_decision_proof_integrity=marker["dualSourceEvidenceSha256"],
        malicious_decision_proof_integrity=malicious_contract_proof,
        provider_owned_system_topic_preserved=True,
        revocation_proof_integrity=revocation_integrity,
        cleanup_inventory_integrity=readback.inventory_integrity,
        unresolved_reasons=(),
    )
    return build_scanner_result_bridge_deployment_evidence(evidence, now=observed_at)


class ProductionScannerBridgeRecoveryAdapter:
    """Consume one stage grant through the existing production lifecycle primitives."""

    def __init__(self, *, clock: Callable[[], datetime] = lifecycle._utc_now) -> None:
        self._clock = clock

    def execute(
        self,
        *,
        authorization: ScannerBridgeRecoveryAuthorization,
        receipt_directory: Path,
        expected_repository_head: str,
        evidence_output: Path | None = None,
    ) -> dict[str, JsonValue]:
        now = self._clock().astimezone(UTC).replace(microsecond=0)
        validate_scanner_bridge_recovery_authorization(
            authorization,
            expected_repository_head=expected_repository_head,
            now_utc=now,
        )
        if (authorization.stage == PROOF_STAGE) != (evidence_output is not None):
            _fail("scanner-bridge-evidence-output-contract-invalid")
        lifecycle._verify_repository_state(expected_repository_head)
        subscription_id = lifecycle._account_binding(now)
        if subscription_id != authorization.subscriptionId:
            _fail("scanner-bridge-subscription-mismatch")
        if not lifecycle._group_exists(subscription_id, TARGET_RESOURCE_GROUP):
            _fail("scanner-bridge-target-resource-group-missing")
        contract = _validate_managed_binding(authorization)
        expected_cost, maximum_cost = lifecycle._verified_cost()
        if maximum_cost > authorization.maximumCostUsdCents:
            _fail("scanner-bridge-cost-ceiling-exceeded")
        _verify_provider_api_versions(subscription_id)
        _verify_network_capacity(subscription_id)
        cleanup_at = _parse_utc(
            authorization.cleanupDeadlineUtc, "scanner-bridge-cleanup-deadline-invalid"
        )
        cleanup_principal = lifecycle._verify_cleanup_control(
            subscription_id, cleanup_at
        )
        cleanup_role = cast(dict[str, JsonValue], contract["cleanupExecution"]).get(
            "cleanupContributorRoleDefinitionId"
        )
        if not isinstance(cleanup_role, str):
            _fail("scanner-bridge-cleanup-role-contract-malformed")
        lifecycle._verify_cleanup_target_role(
            subscription_id, cleanup_principal, cleanup_role
        )

        binding = _deployment_binding(authorization, contract)
        if authorization.stage == PROOF_STAGE:
            _verify_foundation(authorization)
        _claim_authorization(
            authorization=authorization,
            receipt_directory=receipt_directory,
            now_utc=now,
        )
        with tempfile.TemporaryDirectory(
            prefix="mobius77-scanner-bridge-"
        ) as directory:
            template = Path(directory) / "main.json"
            lifecycle._compile_template(template)
            # A lost or failed response is reconciled from ARM before any retry.
            with suppress(lifecycle.AzureCommandError):
                lifecycle._deploy_stage(
                    template_path=template,
                    subscription_id=subscription_id,
                    ledger=binding,
                    stage=authorization.stage,
                    cleanup_at=cleanup_at,
                    expected_cost=expected_cost,
                    maximum_cost=maximum_cost,
                    runtime_config=(
                        {"apiImageDigest": cast(str, authorization.apiImageDigest)}
                        if authorization.stage == PROOF_STAGE
                        else None
                    ),
                )
        outputs = _read_deployment_outputs(
            subscription_id=subscription_id,
            stage=authorization.stage,
            binding=binding,
        )
        assignment_id = _validate_deployment_outputs(authorization, outputs)
        readback = _verify_foundation(authorization)
        if authorization.stage == FOUNDATION_STAGE:
            return {
                "authorization-consumed": True,
                "authorization-integrity-sha256": (
                    authorization.authorizationIntegritySha256
                ),
                "cleanup-executable-and-armed": True,
                "foundation-integrity-sha256": readback.inventory_integrity,
                "public-access-enabled": False,
                "scanner-bridge-foundation-deployed": True,
                "status": "scanner-bridge-foundation-reconciled",
                "tag-write-authorized-for-worker": False,
            }

        if assignment_id is None or evidence_output is None:
            _fail("scanner-proof-authorization-incomplete")
        try:
            proof_graph = _verify_proof_graph(
                authorization,
                assignment_id=assignment_id,
                worker_principal_id=readback.worker_principal_id,
                worker_client_id=readback.worker_client_id,
                workspace_customer_id=readback.workspace_customer_id,
            )
            execution_name = _start_one_execution(authorization)
            execution = _wait_for_execution(authorization, execution_name)
            marker = _proof_marker(authorization, execution_name)
        finally:
            revocation = _remove_proof_residue(authorization, assignment_id)
        final_readback = _verify_foundation(authorization)
        observed = self._clock().astimezone(UTC).replace(microsecond=0)
        evidence = _build_live_evidence(
            authorization=authorization,
            readback=final_readback,
            execution_name=execution_name,
            execution=execution,
            marker=marker,
            proof_graph_integrity=proof_graph,
            revocation_integrity=revocation,
            observed_at=observed,
        )
        _write_evidence(evidence_output, evidence)
        return {
            "authorization-consumed": True,
            "authorization-integrity-sha256": (
                authorization.authorizationIntegritySha256
            ),
            "cleanup-executable-and-armed": True,
            "evidence-integrity-sha256": evidence.integrity_sha256(),
            "immutable-image-digest": authorization.apiImageDigest,
            "marker": "SCANNER_RESULT_BRIDGE_PROVED",
            "proof-execution-count": 1,
            "proof-residue-absent": True,
            "provider-system-topic-preserved": True,
            "public-access-enabled": False,
            "status": "scanner-result-bridge-proved",
            "tag-write-authorized-for-worker": False,
        }


__all__ = [
    "ProductionScannerBridgeRecoveryAdapter",
    "ScannerBridgeRecoveryExecutionError",
]
