"""Versioned, default-deny managed-binding contracts for Milestone 7.7.

The historical Checkpoint 7 matrix remains immutable.  This module validates a
separate one-run overlay, binds it to the historical integrity value, and
provides replay-resistant authorization receipts.  Loading a contract never
grants execution or mutation authority.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
    validate_schema,
)
from preflight.milestone_7_7.operation_contracts import (
    OPERATION_IDS,
    load_operation_contract_matrix,
)

ROOT: Final = Path(__file__).resolve().parent
REPOSITORY_ROOT: Final = ROOT.parents[1]
INFRASTRUCTURE_ROOT: Final = REPOSITORY_ROOT / "infra" / "milestone_7_7"
MANIFEST_PATH: Final = (
    INFRASTRUCTURE_ROOT / "manifests" / "managed-binding.contract.json"
)
MANIFEST_SCHEMA_PATH: Final = (
    INFRASTRUCTURE_ROOT / "manifests" / "managed-binding.schema.json"
)
CLEANUP_RUNBOOK_PATH: Final = (
    INFRASTRUCTURE_ROOT / "scripts" / "Remove-Mobius77Staging.ps1"
)
OVERLAY_PATH: Final = ROOT / "managed-binding-operation-contracts.json"
OVERLAY_SCHEMA_PATH: Final = ROOT / "managed-binding-operation-contracts.schema.json"

AUTHORIZATION_SOURCE_HEAD: Final = "11564669bd5b40a88fdbf434c8137b063305eb4b"
HISTORICAL_MATRIX_SHA256: Final = (
    "100293931dcc71bb069e4f6fe06228360e0953b3b756544a555941d81bf8d6bc"
)
MANAGED_BINDING_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-resource-contract/v1\0"
)
OPERATION_OVERLAY_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-operation-overlay/v1\0"
)
AUTHORIZATION_LEDGER_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-one-run-ledger/v1\0"
)
AUTHORIZATION_RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-operation-receipt/v1\0"
)
CONTRACT_VERSION: Final = "m7.7-managed-binding-v1"
OVERLAY_VERSION: Final = "mobius.milestone-7.7.managed-binding-operation-overlay.v1"
LEDGER_VERSION: Final = "mobius.milestone-7.7.managed-binding-one-run-ledger.v1"
AUTHORIZATION_ID: Final = "m7.7-managed-binding-closeout-20260731"
STAGING_LOCATION: Final = "southcentralus"
CLEANUP_LOCATION: Final = "westus"
MAXIMUM_LEDGER_LIFETIME_SECONDS: Final = 86_400
MAXIMUM_CONTRACT_BYTES: Final = 524_288
HEX_SHA40 = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PUBLISHED_IMAGE_SOURCE_COMMIT: Final = "948e81b5bf34f5c2f5069ee40568beb09cb997d3"
PUBLISHED_IMAGE_BUILD_INPUT_SHA256: Final = (
    "16758013417d703a9ebe661511ff1fc305653372286909cdbbc6e9c29a6e613c"
)
PUBLISHED_REGISTRY_MANIFEST_DIGEST: Final = (
    "sha256:6aceb88fbf4564c621d8553e461b2e496ec543b48d1a59080958d937eddec99c"
)
PUBLISHED_IMAGE_CONFIG_DIGEST: Final = (
    "sha256:c43be0285f3399d893d796397f9895a552f8504e61ce61dfac3ba95dd64d2b41"
)
PUBLISHED_IMAGE_LOCAL_ID: Final = PUBLISHED_REGISTRY_MANIFEST_DIGEST
PUBLISHED_IMAGE_PLATFORM: Final = "linux/amd64"
PUBLISHED_IMAGE_REPOSITORY: Final = "opencanvas-api"
PUBLISHED_PUBLICATION_EVIDENCE_SHA256: Final = (
    "9e9f93b9e6587b7bd8c2814e424ddbc177e1d4f42d59cde1321ad3872f9c2ef1"
)
PUBLISHED_REVOCATION_EVIDENCE_SHA256: Final = (
    "c634ff8e4f45888d05318682838ebe7c629211a74287ff38c8c7240a676139f6"
)
API_IMAGE_BUILD_INPUTS: Final = (
    "apps/api/Dockerfile",
    "apps/api/Dockerfile.dockerignore",
    "apps/api/pyproject.toml",
    "apps/api/build-requirements.lock",
    "apps/api/requirements.lock",
    "apps/api/opencanvas_api",
    "apps/api/alembic.ini",
    "apps/api/alembic",
    "apps/api/scripts",
    "LICENSE",
    "COPYRIGHT",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
)

EXPECTED_RESOURCE_GROUPS: Final = {
    "cleanupControl": "rg-solarplexus-mobius-77-cleanup-control",
    "containerAppsInfrastructure": (
        "rg-solarplexus-mobius-77-containerapps-infrastructure"
    ),
    "target": "rg-solarplexus-mobius-77-staging",
}
EXPECTED_SECRET_BINDINGS: Final = (
    ("openai-api-key", "openai-api-key", "OPENAI_API_KEY"),
    (
        "opencanvas-smtp-username",
        "opencanvas-smtp-username",
        "OPENCANVAS_SMTP_USERNAME",
    ),
    (
        "opencanvas-smtp-password",
        "opencanvas-smtp-password",
        "OPENCANVAS_SMTP_PASSWORD",
    ),
    (
        "opencanvas-session-secret",
        "opencanvas-session-secret",
        "OPENCANVAS_SESSION_SECRET",
    ),
    (
        "opencanvas-invitation-secret",
        "opencanvas-invitation-secret",
        "OPENCANVAS_INVITATION_SECRET",
    ),
    (
        "opencanvas-upload-capability-secret",
        "opencanvas-upload-capability-secret",
        "OPENCANVAS_UPLOAD_CAPABILITY_SECRET",
    ),
    (
        "opencanvas-scanner-result-secret",
        "opencanvas-scanner-result-secret",
        "OPENCANVAS_SCANNER_RESULT_SECRET",
    ),
    (
        "opencanvas-rate-limit-hmac-secret",
        "opencanvas-rate-limit-hmac-secret",
        "OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET",
    ),
    (
        "opencanvas-telemetry-token",
        "opencanvas-telemetry-token",
        "OPENCANVAS_TELEMETRY_AUTH_TOKEN",
    ),
    (
        "opencanvas-telemetry-pseudonymization-secret",
        "opencanvas-telemetry-pseudonymization-secret",
        "OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET",
    ),
    (
        "opencanvas-observability-operator-user-ids",
        "opencanvas-observability-operator-user-ids",
        "OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS",
    ),
)
EXPECTED_PROVIDER_REGISTRATIONS: Final = (
    "Microsoft.App",
    "Microsoft.Authorization",
    "Microsoft.Automation",
    "Microsoft.Cache",
    "Microsoft.ContainerRegistry",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.EventGrid",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.OperationalInsights",
    "Microsoft.Resources",
    "Microsoft.Security",
    "Microsoft.Storage",
)
EXPECTED_LIFECYCLE_OPERATIONS: Final = (
    "pre-secret-provisioning",
    "private-path-verification",
    "post-secret-provisioning",
    "temporary-authority-revocation",
    "cleanup",
    "zero-residue-verification",
)


def _copy_json(value: JsonValue) -> JsonValue:
    return copy.deepcopy(value)


def _as_object(value: JsonValue, location: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ContractError(f"{location}: value must be an object")
    return value


def _as_array(value: JsonValue, location: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ContractError(f"{location}: value must be an array")
    return value


def _parse_utc(value: JsonValue, location: str) -> datetime:
    if not isinstance(value, str) or RFC3339_UTC.fullmatch(value) is None:
        raise ContractError(f"{location}: exact RFC3339 UTC timestamp required")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ContractError(f"{location}: timestamp is invalid") from None


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ContractError("UTC timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_no_private_material(value: JsonValue) -> None:
    serialized = canonical_bytes(value).decode("utf-8")
    lowered = serialized.casefold()
    forbidden = (
        "/subscriptions/",
        "opencanvas_openai_api_key",
        "-----begin ",
        "bearer ",
        "c:\\users\\",
        "/home/",
        "@gmail.",
        "sharedaccesssignature=",
        "accountkey=",
    )
    for marker in forbidden:
        if marker in lowered:
            raise ContractError("managed-binding contract contains prohibited material")


def managed_binding_integrity_sha256(value: JsonValue) -> str:
    return integrity_sha256(value, MANAGED_BINDING_DOMAIN)


def cleanup_runbook_sha256(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def operation_overlay_integrity_sha256(value: dict[str, JsonValue]) -> str:
    body = {
        key: _copy_json(item)
        for key, item in value.items()
        if key != "contractIntegritySha256"
    }
    return integrity_sha256(body, OPERATION_OVERLAY_DOMAIN)


def authorization_ledger_integrity_sha256(value: dict[str, JsonValue]) -> str:
    body = {
        key: _copy_json(item)
        for key, item in value.items()
        if key != "ledgerIntegritySha256"
    }
    return integrity_sha256(body, AUTHORIZATION_LEDGER_DOMAIN)


def validate_managed_binding_contract(value: JsonValue) -> dict[str, JsonValue]:
    contract = _as_object(_copy_json(value), "$")
    schema = _as_object(load_json(MANIFEST_SCHEMA_PATH), "$schema")
    validate_schema(contract, schema)
    if len(canonical_bytes(contract)) > MAXIMUM_CONTRACT_BYTES:
        raise ContractError("managed-binding contract exceeds its byte limit")
    _assert_no_private_material(contract)

    if contract["contractVersion"] != CONTRACT_VERSION:
        raise ContractError("managed-binding contract version differs")
    if contract["authorizationSourceHead"] != AUTHORIZATION_SOURCE_HEAD:
        raise ContractError("managed-binding authorization source differs")
    if contract["location"] != STAGING_LOCATION:
        raise ContractError("managed-binding region differs")
    if contract["cleanupLocation"] != CLEANUP_LOCATION:
        raise ContractError("managed-binding cleanup region differs")
    if contract["redisLocation"] != "australiacentral":
        raise ContractError("managed-binding Redis region differs")
    if contract["resourceGroups"] != EXPECTED_RESOURCE_GROUPS:
        raise ContractError("managed-binding resource groups differ")
    cleanup_execution = _as_object(contract["cleanupExecution"], "$.cleanupExecution")
    expected_cleanup_execution = {
        "absenceVerificationSeconds": 300,
        "authorizationParameter": "CleanupAuthorized",
        "authorizationValue": True,
        "cleanupContributorRoleDefinitionId": ("b24988ac-6180-42a0-ab88-20f7382dd24c"),
        "cleanupPrincipalFingerprintSha256": (
            "19a9f97779cd2eb9acfdc04797f1fc5339316ee1a424ca79b70661beffa33260"
        ),
        "deadlineUtc": "2026-08-05T11:00:00Z",
        "deletionWaitSeconds": 2700,
        "launchGraceSeconds": 1800,
        "publishedContentSha256": cleanup_runbook_sha256(
            CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
        ),
        "subscriptionFingerprint": (
            "f4493115ce6375cf0e5d0616bede57126075fdb27ac78ea0ba7e0085252a7028"
        ),
        "targetParameter": "TargetResourceGroupName",
        "targetResourceGroup": "rg-solarplexus-mobius-77-staging",
    }
    if cleanup_execution != expected_cleanup_execution:
        raise ContractError("managed-binding cleanup execution contract differs")
    authority = _as_object(contract["defaultAuthority"], "$.defaultAuthority")
    if authority != {
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }:
        raise ContractError("managed-binding default authority is not deny-all")

    account = _as_object(contract["accountBinding"], "$.accountBinding")
    if account.get("cloud") != "AzureCloud":
        raise ContractError("managed-binding Azure cloud differs")
    for field in ("subscriptionFingerprint", "tenantFingerprint"):
        fingerprint = account.get(field)
        if not isinstance(fingerprint, str) or HEX_SHA64.fullmatch(fingerprint) is None:
            raise ContractError("managed-binding account fingerprint is invalid")
    if account.get("requiredState") != "Enabled":
        raise ContractError("managed-binding account state differs")
    if account.get("requiredDefault") is not True:
        raise ContractError("managed-binding account must remain the active default")
    if account.get("requiredUserType") != "user":
        raise ContractError("managed-binding account user type differs")

    scope = _as_object(contract["scopeBinding"], "$.scopeBinding")
    if scope.get("materialization") != "matched-subscription-relative-resource-id":
        raise ContractError("managed-binding scope materialization differs")
    for name, relative_id in scope.items():
        if name == "materialization":
            continue
        if not isinstance(relative_id, str) or not relative_id.startswith(
            "/resourceGroups/"
        ):
            raise ContractError("managed-binding relative resource scope is invalid")
        if ".." in relative_id or "//" in relative_id or "\\" in relative_id:
            raise ContractError("managed-binding relative resource scope is ambiguous")
        if not any(
            f"/resourceGroups/{resource_group}" in relative_id
            for resource_group in EXPECTED_RESOURCE_GROUPS.values()
        ):
            raise ContractError(
                "managed-binding resource scope escapes approved groups"
            )

    provider_registrations = tuple(
        str(item)
        for item in _as_array(
            contract["providerRegistrationRequirements"],
            "$.providerRegistrationRequirements",
        )
    )
    if provider_registrations != EXPECTED_PROVIDER_REGISTRATIONS:
        raise ContractError("managed-binding provider registry differs")

    fixed_skus = _as_object(contract["fixedSkus"], "$.fixedSkus")
    if fixed_skus.get("vpnGateway") != "VpnGw1AZ":
        raise ContractError("managed-binding VPN gateway SKU differs")
    if fixed_skus.get("redis") != "Balanced_B0":
        raise ContractError("managed-binding Redis SKU differs")

    network = _as_object(contract["network"], "$.network")
    vnet = ipaddress.ip_network(str(network["vnetCidr"]), strict=True)
    if not isinstance(vnet, ipaddress.IPv4Network):
        raise ContractError("managed-binding VNet must be IPv4")
    if vnet != ipaddress.ip_network("10.77.0.0/20"):
        raise ContractError("managed-binding VNet differs")
    child_names = (
        "containerAppsCidr",
        "privateEndpointsCidr",
        "managementCleanupCidr",
        "gatewayCidr",
        "azureFirewallCidr",
        "azureFirewallManagementCidr",
        "dnsResolverInboundCidr",
    )
    children: list[ipaddress.IPv4Network] = []
    for name in child_names:
        child = ipaddress.ip_network(str(network[name]), strict=True)
        if not isinstance(child, ipaddress.IPv4Network):
            raise ContractError("managed-binding subnets must be IPv4")
        children.append(child)
    if any(not child.subnet_of(vnet) for child in children):
        raise ContractError("managed-binding subnet escapes the exact VNet")
    for index, left in enumerate(children):
        if any(left.overlaps(right) for right in children[index + 1 :]):
            raise ContractError("managed-binding subnets overlap")
    resolver_address = ipaddress.ip_address(str(network["dnsResolverInboundAddress"]))
    resolver_subnet = ipaddress.ip_network(
        str(network["dnsResolverInboundCidr"]), strict=True
    )
    if (
        not isinstance(resolver_address, ipaddress.IPv4Address)
        or not isinstance(resolver_subnet, ipaddress.IPv4Network)
        or resolver_address not in resolver_subnet
    ):
        raise ContractError("managed-binding resolver address escapes its subnet")
    if network.get("publicApplicationIngress") is not False:
        raise ContractError("managed-binding public application ingress is forbidden")
    if network.get("publicKeyVaultAccess") is not False:
        raise ContractError("managed-binding public Key Vault access is forbidden")

    vpn = _as_object(contract["vpn"], "$.vpn")
    if vpn != {
        "authenticationType": "AAD",
        "gatewayGeneration": "Generation2",
        "gatewaySku": "VpnGw1AZ",
        "gatewayType": "Vpn",
        "microsoftRegisteredClientAudience": ("c632b3df-fb67-4d84-bdcf-b95ad541b5c8"),
        "publicIpAllocation": "Static",
        "publicIpAvailabilityZoneMode": "explicit-zone-redundant",
        "publicIpSku": "Standard",
        "publicIpZones": ["1", "2", "3"],
        "tunnelType": "OpenVPN",
        "vpnType": "RouteBased",
    }:
        raise ContractError("managed-binding VPN compatibility contract differs")

    secrets = _as_array(contract["secrets"], "$.secrets")
    actual_secrets = tuple(
        (
            str(_as_object(item, "$.secrets[]")["keyVaultName"]),
            str(_as_object(item, "$.secrets[]")["containerAppReference"]),
            str(_as_object(item, "$.secrets[]")["environmentVariable"]),
        )
        for item in secrets
    )
    if actual_secrets != EXPECTED_SECRET_BINDINGS:
        raise ContractError("managed-binding secret names or runtime mappings differ")

    provider_runtime = _as_object(contract["providerRuntime"], "$.providerRuntime")
    if provider_runtime != {
        "runtimeMode": "isolated-synthetic-private",
        "smtpFromAddress": "mobius77-validation@example.invalid",
        "smtpHost": "sandbox.smtp.mailtrap.io",
        "smtpPort": 2525,
        "smtpStartTls": True,
    }:
        raise ContractError("managed-binding provider runtime differs")

    rbac = _as_object(contract["rbac"], "$.rbac")
    expected_role_ids = {
        "acrDeleteRoleDefinitionId": "c2f4ef07-c644-48eb-af81-4b1b4947fb11",
        "acrPullRoleDefinitionId": "7f951dda-4ed3-4680-a7ca-43fe172d538d",
        "acrPushRoleDefinitionId": "8311e382-0749-4cb8-b61a-304f252e45ec",
        "acrRepositoryContributorRoleDefinitionId": (
            "2efddaa5-3f1f-4df3-97df-af3f13818f4c"
        ),
        "cleanupContributorRoleDefinitionId": ("b24988ac-6180-42a0-ab88-20f7382dd24c"),
        "containerAppsNetworkContributorRoleDefinitionId": (
            "4d97b98b-1d4f-4787-a291-c67834d212e7"
        ),
        "keyVaultSecretsOfficerRoleDefinitionId": (
            "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
        ),
        "keyVaultSecretsUserRoleDefinitionId": ("4633458b-17de-408a-b874-0445c86b69e6"),
    }
    for field, expected in expected_role_ids.items():
        if rbac.get(field) != expected:
            raise ContractError("managed-binding stable role definition differs")
    if rbac.get("workloadRoleScope") != "key-vault-resource":
        raise ContractError("workload secret role is not scoped to the Key Vault")
    if rbac.get("temporaryOperatorRoleScope") != "key-vault-resource":
        raise ContractError("temporary operator role is not scoped to the Key Vault")
    if rbac.get("cleanupRoleScope") != "target-resource-group":
        raise ContractError("cleanup role is not scoped to the target resource group")
    if (
        rbac.get("containerAppsInfrastructureRoleScope")
        != "exact-infrastructure-group-or-delegated-subnet"
        or rbac.get("containerAppsInfrastructureRolePrincipalType")
        != "ServicePrincipal"
    ):
        raise ContractError("Container Apps platform role boundary differs")
    if rbac.get("workloadRegistryRoleScope") != "container-registry-resource":
        raise ContractError("workload registry role is not scoped to the registry")
    if rbac.get("temporaryRegistryOperatorRoleScope") != "container-registry-resource":
        raise ContractError("temporary registry role is not scoped to the registry")
    if rbac.get("temporaryOperatorAssignmentRemovedAfterEntry") is not True:
        raise ContractError("temporary operator revocation is not mandatory")
    if rbac.get("temporaryRegistryOperatorAssignmentRemovedAfterPublish") is not True:
        raise ContractError("temporary registry operator revocation is not mandatory")
    if (
        rbac.get("temporaryRegistryDeleteRoleScope")
        != "container-registry-resource-or-exact-repository-abac-condition"
        or rbac.get("temporaryRegistryDeleteAssignmentRemovedAfterUntag") is not True
    ):
        raise ContractError("temporary registry delete boundary differs")

    source = _as_object(contract["privateAcrSource"], "$.privateAcrSource")
    expected_source: dict[str, JsonValue] = {
        "buildContext": "repository-root",
        "dockerfile": "apps/api/Dockerfile",
        "dockerfileIgnore": "apps/api/Dockerfile.dockerignore",
        "imageRepository": "opencanvas-api",
        "sourceCommitBinding": "published-image-source-commit",
        "buildTool": "docker-buildx",
        "pushPath": "local-docker-over-p2s-vpn-to-private-acr",
        "registryAuthentication": "entra-current-user-temporary-acr-push",
        "uploadRepositoryScope": "repository:opencanvas-api:pull,push",
        "finalizationRepositoryScope": "repository:opencanvas-api:pull,delete",
        "classicFinalizerRoles": "AcrPull+AcrDelete",
        "abacFinalizerRole": "Container Registry Repository Contributor",
        "abacRepositoryCondition": "StringEqualsIgnoreCase:opencanvas-api",
        "catalogPermissionAllowed": False,
        "deleteAuthorityTiming": "after-independent-digest-match-only",
        "finalizationIdentity": "separate-ephemeral-certificate-finalizer",
        "finalizationOperation": "exact-source-tag-untag-only",
        "manifestDeleteAllowed": False,
        "repositoryDeleteAllowed": False,
        "controlPlaneAndImageSourceCommitSeparated": True,
        "workloadPullAuthentication": "user-assigned-managed-identity-acr-pull",
        "publicRegistryAccess": False,
        "mutableTagsAllowed": False,
        "temporarySourceTagPattern": ("source-{published-image-source-commit}"),
        "temporarySourceTagPreexistenceDecision": "deny",
        "temporarySourceTagRemovedAfterDigestResolution": True,
        "deploymentReference": "digest-only",
        "dockerCredentialDirectory": "ephemeral-outside-repository",
        "dockerLogoutRequired": True,
        "gitRemoteAccessAllowed": False,
        "temporaryPushRoleRevocationRequired": True,
    }
    if source != expected_source:
        raise ContractError("managed-binding private ACR source contract differs")
    for relative_path in ("dockerfile", "dockerfileIgnore"):
        candidate = (REPOSITORY_ROOT / str(source[relative_path])).resolve()
        if (
            REPOSITORY_ROOT.resolve() not in candidate.parents
            or not candidate.is_file()
        ):
            raise ContractError(
                "managed-binding private ACR source file is unavailable"
            )

    one_run = _as_object(contract["oneRunPolicy"], "$.oneRunPolicy")
    if one_run != {
        "authorizationId": AUTHORIZATION_ID,
        "maximumLedgerLifetimeSeconds": MAXIMUM_LEDGER_LIFETIME_SECONDS,
        "maximumAttemptsPerOperation": 1,
        "retryCount": 0,
        "receiptRequiredBeforeFirstEffect": True,
        "replayDecision": "deny",
        "safePreSecretPreservationAllowed": True,
        "cleanupAuthorizedOnlyAfterCompletionOrExplicitUserApproval": True,
        "preservedResumeRequiresFreshLedger": True,
        "postRunProvisioningAuthorized": False,
    }:
        raise ContractError("managed-binding one-run policy differs")
    lifecycle = _as_object(contract["lifecycle"], "$.lifecycle")
    if lifecycle.get("failureDispositionModel") != [
        "RUNNING",
        "PAUSED_PRESERVED",
        "CONTAINED_PRESERVED",
        "READY_FOR_FINAL_CLEANUP",
        "COMPLETED",
    ]:
        raise ContractError("managed-binding failure dispositions differ")
    if (
        lifecycle.get("preSecretFailureDecision")
        != "reconcile-resulting-state-and-pause-preserved"
        or lifecycle.get("rollbackDecision")
        != "preserve-unless-final-cleanup-authorized"
    ):
        raise ContractError("managed-binding failure decision differs")
    return contract


def load_managed_binding_contract() -> dict[str, JsonValue]:
    return validate_managed_binding_contract(load_json(MANIFEST_PATH))


def validate_operation_overlay(value: JsonValue) -> dict[str, JsonValue]:
    overlay = _as_object(_copy_json(value), "$")
    schema = _as_object(load_json(OVERLAY_SCHEMA_PATH), "$schema")
    validate_schema(overlay, schema)
    if len(canonical_bytes(overlay)) > MAXIMUM_CONTRACT_BYTES:
        raise ContractError("managed-binding operation overlay exceeds its byte limit")
    _assert_no_private_material(overlay)

    if overlay["contractVersion"] != OVERLAY_VERSION:
        raise ContractError("managed-binding operation overlay version differs")
    if overlay["authorizationSourceHead"] != AUTHORIZATION_SOURCE_HEAD:
        raise ContractError("managed-binding operation authorization source differs")
    if overlay["historicalMatrixIntegritySha256"] != HISTORICAL_MATRIX_SHA256:
        raise ContractError("managed-binding historical matrix binding differs")
    historical = load_operation_contract_matrix()
    if historical["matrixIntegritySha256"] != HISTORICAL_MATRIX_SHA256:
        raise ContractError("historical operation matrix changed")
    managed_binding = load_managed_binding_contract()
    expected_binding_integrity = managed_binding_integrity_sha256(managed_binding)
    if overlay["managedBindingIntegritySha256"] != expected_binding_integrity:
        raise ContractError("managed-binding resource contract binding differs")

    authority = _as_object(overlay["defaultAuthority"], "$.defaultAuthority")
    if any(authority.values()):
        raise ContractError("managed-binding operation defaults must deny authority")
    policy = _as_object(overlay["executionPolicy"], "$.executionPolicy")
    if policy.get("maximumAttempts") != 1 or policy.get("retryCount") != 0:
        raise ContractError("managed-binding execution is not single-attempt")
    if policy.get("maximumTimeoutSeconds") != 30:
        raise ContractError("managed-binding timeout differs")
    if policy.get("rawOutputRetentionAllowed") is not False:
        raise ContractError("managed-binding raw output retention is forbidden")

    methods = _as_object(overlay["methodDefinitions"], "$.methodDefinitions")
    parsers = _as_object(overlay["parserDefinitions"], "$.parserDefinitions")
    order = tuple(
        str(item) for item in _as_array(overlay["operationOrder"], "$.operationOrder")
    )
    if order != OPERATION_IDS:
        raise ContractError("managed-binding operation order differs")
    operations = _as_array(overlay["operations"], "$.operations")
    operation_ids: list[str] = []
    for index, raw_operation in enumerate(operations):
        operation = _as_object(raw_operation, f"$.operations[{index}]")
        operation_id = str(operation["id"])
        operation_ids.append(operation_id)
        if operation.get("definitionStatus") != "defined":
            raise ContractError("managed-binding operation is not fully defined")
        if operation.get("proofStatus") != "unproved":
            raise ContractError("contract definition cannot claim execution proof")
        method_ids = _as_array(
            operation["methodDefinitions"],
            f"$.operations[{index}].methodDefinitions",
        )
        if any(str(method_id) not in methods for method_id in method_ids):
            raise ContractError(
                "managed-binding operation references an unknown method"
            )
        parser_id = str(operation["parserDefinition"])
        if parser_id not in parsers:
            raise ContractError(
                "managed-binding operation references an unknown parser"
            )
        if operation.get("cleanupOperation") != "none-read-only":
            raise ContractError(
                "read-only prerequisite operation has a mutation cleanup"
            )
    if tuple(operation_ids) != OPERATION_IDS or len(set(operation_ids)) != 15:
        raise ContractError("managed-binding operation registry differs")

    lifecycle = _as_array(overlay["lifecycleOperations"], "$.lifecycleOperations")
    lifecycle_ids = tuple(
        str(_as_object(item, "$.lifecycleOperations[]")["id"]) for item in lifecycle
    )
    if lifecycle_ids != EXPECTED_LIFECYCLE_OPERATIONS:
        raise ContractError("managed-binding lifecycle operation registry differs")
    for raw_lifecycle in lifecycle:
        item = _as_object(raw_lifecycle, "$.lifecycleOperations[]")
        if str(item["methodDefinition"]) not in methods:
            raise ContractError("managed-binding lifecycle method is unknown")
        expected_disposition_policy = (
            "reconcile-and-pause-preserved"
            if item["id"] == "pre-secret-provisioning"
            else "pause-preserved"
        )
        if item.get("failureDispositionPolicy") != expected_disposition_policy:
            raise ContractError("managed-binding failure disposition differs")
        terminal_states = item.get("terminalStates")
        if not isinstance(terminal_states, list) or any(
            not isinstance(state, str) for state in terminal_states
        ):
            raise ContractError("managed-binding terminal states are malformed")
        if (
            item["id"] == "pre-secret-provisioning"
            and "paused-preserved" not in terminal_states
        ):
            raise ContractError("managed-binding preserved terminal state is missing")
        if item.get("replayDecision") != "deny":
            raise ContractError("managed-binding lifecycle permits replay")

    expected_integrity = operation_overlay_integrity_sha256(overlay)
    if overlay["contractIntegritySha256"] != expected_integrity:
        raise ContractError("managed-binding operation overlay integrity mismatch")
    return overlay


def load_operation_overlay() -> dict[str, JsonValue]:
    return validate_operation_overlay(load_json(OVERLAY_PATH))


def published_image_identity(*, control_plane_head: str) -> dict[str, JsonValue]:
    """Bind a proved immutable image independently from orchestration HEAD."""

    if HEX_SHA40.fullmatch(control_plane_head) is None:
        raise ContractError("published image control plane HEAD is invalid")
    completed = subprocess.run(
        (
            "git",
            "diff",
            "--quiet",
            PUBLISHED_IMAGE_SOURCE_COMMIT,
            control_plane_head,
            "--",
            *API_IMAGE_BUILD_INPUTS,
        ),
        cwd=REPOSITORY_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        shell=False,
        timeout=30,
    )
    if completed.returncode == 1:
        raise ContractError("published image build inputs changed")
    if completed.returncode != 0:
        raise ContractError("published image input comparison failed")
    return {
        "controlPlaneHead": control_plane_head,
        "imageSourceCommit": PUBLISHED_IMAGE_SOURCE_COMMIT,
        "imageBuildInputSha256": PUBLISHED_IMAGE_BUILD_INPUT_SHA256,
        "registryManifestDigest": PUBLISHED_REGISTRY_MANIFEST_DIGEST,
        "imageConfigDigest": PUBLISHED_IMAGE_CONFIG_DIGEST,
        "localImageId": PUBLISHED_IMAGE_LOCAL_ID,
        "platform": PUBLISHED_IMAGE_PLATFORM,
        "repository": PUBLISHED_IMAGE_REPOSITORY,
        "publicationEvidenceIntegritySha256": PUBLISHED_PUBLICATION_EVIDENCE_SHA256,
        "publisherRevocationEvidenceIntegritySha256": PUBLISHED_REVOCATION_EVIDENCE_SHA256,
    }


def build_authorization_ledger(
    *,
    issued_at_utc: datetime,
    repository_head: str,
    maximum_lifetime_seconds: int = MAXIMUM_LEDGER_LIFETIME_SECONDS,
) -> dict[str, JsonValue]:
    if HEX_SHA40.fullmatch(repository_head) is None:
        raise ContractError("authorization ledger repository HEAD is invalid")
    if not 1 <= maximum_lifetime_seconds <= MAXIMUM_LEDGER_LIFETIME_SECONDS:
        raise ContractError("authorization ledger lifetime is outside the closed bound")
    issued = issued_at_utc.astimezone(UTC).replace(microsecond=0)
    expires = issued + timedelta(seconds=maximum_lifetime_seconds)
    managed_binding = load_managed_binding_contract()
    overlay = load_operation_overlay()
    account = _as_object(managed_binding["accountBinding"], "$.accountBinding")
    ledger_without_integrity: dict[str, JsonValue] = {
        "ledgerVersion": LEDGER_VERSION,
        "authorizationId": AUTHORIZATION_ID,
        "issuedAtUtc": _format_utc(issued),
        "expiresAtUtc": _format_utc(expires),
        "repositoryHead": repository_head,
        "publishedImage": published_image_identity(control_plane_head=repository_head),
        "authorizationSourceHead": AUTHORIZATION_SOURCE_HEAD,
        "historicalMatrixIntegritySha256": HISTORICAL_MATRIX_SHA256,
        "managedBindingIntegritySha256": managed_binding_integrity_sha256(
            managed_binding
        ),
        "operationOverlayIntegritySha256": overlay["contractIntegritySha256"],
        "accountBinding": {
            "cloud": account["cloud"],
            "subscriptionFingerprint": account["subscriptionFingerprint"],
            "tenantFingerprint": account["tenantFingerprint"],
        },
        "resourceGroups": _copy_json(managed_binding["resourceGroups"]),
        "operationOrder": list(OPERATION_IDS),
        "authorityTransition": {
            "readOnlyOperationExecutionAuthorized": True,
            "lifecycleMutationConditionallyAuthorized": True,
            "provisioningConditionallyAuthorized": True,
            "secretValueAccessAuthorized": False,
            "maximumAttemptsPerOperation": 1,
            "retryCount": 0,
            "receiptRequired": True,
            "replayDecision": "deny",
        },
        "cleanupPolicy": {
            "safePreSecretPreservationAllowed": True,
            "unsafeTerminalCleanupRequired": True,
            "preservedResumeRequiresFreshLedger": True,
            "postRunProvisioningAuthorized": False,
            "zeroResidueRequired": True,
        },
    }
    ledger = {
        **ledger_without_integrity,
        "ledgerIntegritySha256": integrity_sha256(
            ledger_without_integrity, AUTHORIZATION_LEDGER_DOMAIN
        ),
    }
    return validate_authorization_ledger(
        ledger,
        now_utc=issued,
        expected_repository_head=repository_head,
    )


def validate_authorization_ledger(
    value: JsonValue,
    *,
    now_utc: datetime,
    expected_repository_head: str,
) -> dict[str, JsonValue]:
    ledger = _as_object(_copy_json(value), "$")
    exact_fields = {
        "accountBinding",
        "authorizationId",
        "authorizationSourceHead",
        "authorityTransition",
        "cleanupPolicy",
        "expiresAtUtc",
        "historicalMatrixIntegritySha256",
        "issuedAtUtc",
        "ledgerIntegritySha256",
        "ledgerVersion",
        "managedBindingIntegritySha256",
        "operationOrder",
        "operationOverlayIntegritySha256",
        "publishedImage",
        "repositoryHead",
        "resourceGroups",
    }
    if set(ledger) != exact_fields:
        raise ContractError("authorization ledger fields differ")
    if ledger["ledgerVersion"] != LEDGER_VERSION:
        raise ContractError("authorization ledger version differs")
    if ledger["authorizationId"] != AUTHORIZATION_ID:
        raise ContractError("authorization ledger identity differs")
    if ledger["repositoryHead"] != expected_repository_head:
        raise ContractError("authorization ledger repository binding differs")
    if ledger["publishedImage"] != published_image_identity(
        control_plane_head=expected_repository_head
    ):
        raise ContractError("authorization ledger published image binding differs")
    if ledger["authorizationSourceHead"] != AUTHORIZATION_SOURCE_HEAD:
        raise ContractError("authorization ledger source binding differs")
    if ledger["historicalMatrixIntegritySha256"] != HISTORICAL_MATRIX_SHA256:
        raise ContractError("authorization ledger historical binding differs")
    if tuple(_as_array(ledger["operationOrder"], "$.operationOrder")) != OPERATION_IDS:
        raise ContractError("authorization ledger operation order differs")

    managed_binding = load_managed_binding_contract()
    overlay = load_operation_overlay()
    if ledger["managedBindingIntegritySha256"] != managed_binding_integrity_sha256(
        managed_binding
    ):
        raise ContractError("authorization ledger resource contract binding differs")
    if ledger["operationOverlayIntegritySha256"] != overlay["contractIntegritySha256"]:
        raise ContractError("authorization ledger operation contract binding differs")
    if ledger["resourceGroups"] != EXPECTED_RESOURCE_GROUPS:
        raise ContractError("authorization ledger resource groups differ")
    expected_account = _as_object(managed_binding["accountBinding"], "$.accountBinding")
    if ledger["accountBinding"] != {
        "cloud": expected_account["cloud"],
        "subscriptionFingerprint": expected_account["subscriptionFingerprint"],
        "tenantFingerprint": expected_account["tenantFingerprint"],
    }:
        raise ContractError("authorization ledger account binding differs")

    authority = _as_object(ledger["authorityTransition"], "$.authorityTransition")
    if authority != {
        "readOnlyOperationExecutionAuthorized": True,
        "lifecycleMutationConditionallyAuthorized": True,
        "provisioningConditionallyAuthorized": True,
        "secretValueAccessAuthorized": False,
        "maximumAttemptsPerOperation": 1,
        "retryCount": 0,
        "receiptRequired": True,
        "replayDecision": "deny",
    }:
        raise ContractError("authorization ledger transition differs")
    cleanup = _as_object(ledger["cleanupPolicy"], "$.cleanupPolicy")
    if cleanup != {
        "safePreSecretPreservationAllowed": True,
        "unsafeTerminalCleanupRequired": True,
        "preservedResumeRequiresFreshLedger": True,
        "postRunProvisioningAuthorized": False,
        "zeroResidueRequired": True,
    }:
        raise ContractError("authorization ledger cleanup policy differs")

    issued = _parse_utc(ledger["issuedAtUtc"], "$.issuedAtUtc")
    expires = _parse_utc(ledger["expiresAtUtc"], "$.expiresAtUtc")
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if expires <= issued or expires - issued > timedelta(
        seconds=MAXIMUM_LEDGER_LIFETIME_SECONDS
    ):
        raise ContractError("authorization ledger lifetime differs")
    if now < issued or now >= expires:
        raise ContractError("authorization ledger is not currently valid")
    if ledger["ledgerIntegritySha256"] != authorization_ledger_integrity_sha256(ledger):
        raise ContractError("authorization ledger integrity mismatch")
    _assert_no_private_material(ledger)
    return ledger


def operation_authorization_decision(
    operation_id: str,
    *,
    ledger: JsonValue | None = None,
    now_utc: datetime | None = None,
    expected_repository_head: str | None = None,
) -> dict[str, JsonValue]:
    if operation_id not in OPERATION_IDS:
        raise ContractError("unknown managed-binding operation")
    if ledger is None or now_utc is None or expected_repository_head is None:
        return {
            "operationId": operation_id,
            "decision": "deny",
            "reason": "one-run-authority-missing",
            "executionAuthorized": False,
            "mutationAuthorized": False,
            "provisioningAuthorized": False,
            "secretAccessAuthorized": False,
        }
    validate_authorization_ledger(
        ledger,
        now_utc=now_utc,
        expected_repository_head=expected_repository_head,
    )
    return {
        "operationId": operation_id,
        "decision": "allow-once",
        "reason": "exact-one-run-authority-valid",
        "executionAuthorized": True,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }


def claim_operation_receipt(
    *,
    ledger: JsonValue,
    operation_id: str,
    receipt_directory: Path,
    now_utc: datetime,
    expected_repository_head: str,
) -> Path:
    valid_ledger = validate_authorization_ledger(
        ledger,
        now_utc=now_utc,
        expected_repository_head=expected_repository_head,
    )
    if (
        operation_id not in OPERATION_IDS
        and operation_id not in EXPECTED_LIFECYCLE_OPERATIONS
    ):
        raise ContractError("unknown receipt operation")
    resolved_directory = receipt_directory.resolve()
    resolved_repository = REPOSITORY_ROOT.resolve()
    if (
        resolved_directory == resolved_repository
        or resolved_repository in resolved_directory.parents
    ):
        raise ContractError("authorization receipts must remain outside the repository")
    resolved_directory.mkdir(parents=True, exist_ok=True)
    receipt_path = resolved_directory / f"{operation_id}.receipt.json"
    receipt_body: dict[str, JsonValue] = {
        "authorizationId": AUTHORIZATION_ID,
        "ledgerIntegritySha256": valid_ledger["ledgerIntegritySha256"],
        "operationId": operation_id,
        "claimedAtUtc": _format_utc(now_utc),
        "replayDecision": "deny",
    }
    receipt: dict[str, JsonValue] = {
        **receipt_body,
        "receiptIntegritySha256": integrity_sha256(
            receipt_body, AUTHORIZATION_RECEIPT_DOMAIN
        ),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(receipt_path, flags, 0o600)
    except FileExistsError:
        raise ContractError("authorization receipt already consumed") from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        receipt_path.unlink(missing_ok=True)
        raise ContractError("authorization receipt write failed") from None
    return receipt_path
