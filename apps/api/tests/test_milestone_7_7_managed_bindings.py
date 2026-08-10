from __future__ import annotations

import base64
import hashlib
import inspect
import json
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_7 import acr_tag_finalization, api_image_publication
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from performance.milestone_7_7.framework import ContractError, JsonValue, canonical_bytes
from preflight.milestone_7_7 import framework as topology_framework
from preflight.milestone_7_7 import managed_binding_contracts, managed_binding_execution
from preflight.milestone_7_7.execution import _ProcessCapture
from preflight.milestone_7_7.framework import (
    EXPECTED_ACCOUNT_COMMAND,
    SUBSCRIPTION_FINGERPRINT,
    SUBSCRIPTION_FINGERPRINT_DOMAIN,
    TENANT_FINGERPRINT,
    TENANT_FINGERPRINT_DOMAIN,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    AUTHORIZATION_SOURCE_HEAD,
    EXPECTED_LIFECYCLE_OPERATIONS,
    HISTORICAL_MATRIX_SHA256,
    build_authorization_ledger,
    claim_operation_receipt,
    cleanup_runbook_sha256,
    load_managed_binding_contract,
    load_operation_overlay,
    managed_binding_integrity_sha256,
    operation_authorization_decision,
    operation_overlay_integrity_sha256,
    validate_authorization_ledger,
    validate_managed_binding_contract,
    validate_operation_overlay,
)
from preflight.milestone_7_7.managed_binding_execution import (
    ManagedBindingExecutionError,
    dry_run,
    execute_package_one,
)
from preflight.milestone_7_7.operation_contracts import OPERATION_IDS

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
INFRASTRUCTURE_ROOT = REPOSITORY_ROOT / "infra" / "milestone_7_7"
LIFECYCLE_SCRIPT = INFRASTRUCTURE_ROOT / "scripts" / "managed_binding_lifecycle.py"
IMAGE_PUBLICATION_SCRIPT = INFRASTRUCTURE_ROOT / "api_image_publication.py"
SYNTHETIC_SUBSCRIPTION = "synthetic-managed-binding-subscription"
SYNTHETIC_TENANT = "synthetic-managed-binding-tenant"
NOW = datetime(2026, 7, 31, 18, 0, tzinfo=UTC)
TEST_IMAGE_SOURCE_COMMIT = "7321e69b8296660c53015a05e5b01b9adf1e302f"


def _pending_image(source_commit: str = TEST_IMAGE_SOURCE_COMMIT) -> dict[str, JsonValue]:
    return {
        "imageSourceCommit": source_commit,
        "imageBuildInputSha256": "a" * 64,
        "localImageId": "sha256:" + "b" * 64,
        "configDigest": "sha256:" + "b" * 64,
        "platform": "linux/amd64",
        "repository": "opencanvas-api",
        "sourceTag": f"source-{source_commit}",
        "registryManifestDigest": None,
    }


def _synthetic_jwt(claims: Mapping[str, object]) -> bytearray:
    def encode(value: Mapping[str, object]) -> bytes:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    return bytearray(
        encode({"alg": "RS256", "typ": "JWT"}) + b"." + encode(claims) + b".synthetic-signature"
    )


def test_managed_binding_contract_is_exact_integrity_bound_and_default_deny() -> None:
    contract = load_managed_binding_contract()
    overlay = load_operation_overlay()

    assert contract["authorizationSourceHead"] == AUTHORIZATION_SOURCE_HEAD
    assert contract["defaultAuthority"] == {
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }
    assert overlay["historicalMatrixIntegritySha256"] == HISTORICAL_MATRIX_SHA256
    assert overlay["managedBindingIntegritySha256"] == managed_binding_integrity_sha256(contract)
    assert overlay["contractIntegritySha256"] == operation_overlay_integrity_sha256(overlay)
    assert tuple(overlay["operationOrder"]) == OPERATION_IDS
    assert tuple(item["id"] for item in overlay["operations"]) == OPERATION_IDS
    assert tuple(item["id"] for item in overlay["lifecycleOperations"]) == (
        EXPECTED_LIFECYCLE_OPERATIONS
    )
    operations = {item["id"]: item for item in overlay["operations"]}
    for operation_id in ("regional-service-availability", "regional-sku-capabilities"):
        assert operations[operation_id]["sanitizedInputs"][:2] == [
            "southcentralus",
            "westus-cleanup-automation-only",
        ]
    assert operation_authorization_decision(OPERATION_IDS[0]) == {
        "operationId": OPERATION_IDS[0],
        "decision": "deny",
        "reason": "one-run-authority-missing",
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }


def test_exact_names_scopes_secrets_runtime_and_private_source_are_closed() -> None:
    contract = load_managed_binding_contract()

    assert contract["providerRegistrationRequirements"] == [
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
    ]
    assert {
        key: contract["providerApiVersions"][key]
        for key in (
            "Microsoft.Cache/redisEnterprise",
            "Microsoft.Cache/redisEnterprise/databases",
            "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments",
            "Microsoft.DBforPostgreSQL/flexibleServers",
            "Microsoft.DBforPostgreSQL/flexibleServers/administrators",
            "Microsoft.DBforPostgreSQL/flexibleServers/databases",
            "Microsoft.Storage/storageAccounts",
            "Microsoft.Storage/storageAccounts/blobServices",
            "Microsoft.Storage/storageAccounts/blobServices/containers",
        )
    } == {
        "Microsoft.Cache/redisEnterprise": "2026-05-01-preview",
        "Microsoft.Cache/redisEnterprise/databases": "2026-05-01-preview",
        "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments": ("2026-05-01-preview"),
        "Microsoft.DBforPostgreSQL/flexibleServers": "2024-08-01",
        "Microsoft.DBforPostgreSQL/flexibleServers/administrators": "2024-08-01",
        "Microsoft.DBforPostgreSQL/flexibleServers/databases": "2024-08-01",
        "Microsoft.Storage/storageAccounts": "2025-06-01",
        "Microsoft.Storage/storageAccounts/blobServices": "2025-06-01",
        "Microsoft.Storage/storageAccounts/blobServices/containers": "2025-06-01",
    }

    assert contract["resourceGroups"] == {
        "cleanupControl": "rg-solarplexus-mobius-77-cleanup-control",
        "containerAppsInfrastructure": ("rg-solarplexus-mobius-77-containerapps-infrastructure"),
        "target": "rg-solarplexus-mobius-77-staging",
    }
    assert contract["location"] == "southcentralus"
    assert contract["cleanupLocation"] == "westus"
    assert contract["redisLocation"] == "australiacentral"
    assert contract["resources"]["keyVault"] == "kv-mobius77-11564669"
    assert contract["network"]["vnetCidr"] == "10.77.0.0/20"
    assert contract["network"]["privateEndpointsCidr"] == "10.77.2.0/24"
    assert contract["network"]["publicApplicationIngress"] is False
    assert contract["network"]["publicKeyVaultAccess"] is False
    assert contract["fixedSkus"]["vpnGateway"] == "VpnGw1AZ"
    assert contract["fixedSkus"]["redis"] == "Balanced_B0"
    assert contract["vpn"] == {
        "gatewaySku": "VpnGw1AZ",
        "gatewayGeneration": "Generation2",
        "publicIpSku": "Standard",
        "publicIpAllocation": "Static",
        "publicIpAvailabilityZoneMode": "explicit-zone-redundant",
        "publicIpZones": ["1", "2", "3"],
        "gatewayType": "Vpn",
        "vpnType": "RouteBased",
        "tunnelType": "OpenVPN",
        "authenticationType": "AAD",
        "microsoftRegisteredClientAudience": "c632b3df-fb67-4d84-bdcf-b95ad541b5c8",
    }
    assert [
        (item["keyVaultName"], item["environmentVariable"]) for item in contract["secrets"]
    ] == [
        ("openai-api-key", "OPENAI_API_KEY"),
        ("opencanvas-smtp-username", "OPENCANVAS_SMTP_USERNAME"),
        ("opencanvas-smtp-password", "OPENCANVAS_SMTP_PASSWORD"),
        ("opencanvas-session-secret", "OPENCANVAS_SESSION_SECRET"),
        ("opencanvas-invitation-secret", "OPENCANVAS_INVITATION_SECRET"),
        ("opencanvas-upload-capability-secret", "OPENCANVAS_UPLOAD_CAPABILITY_SECRET"),
        ("opencanvas-scanner-result-secret", "OPENCANVAS_SCANNER_RESULT_SECRET"),
        ("opencanvas-rate-limit-hmac-secret", "OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET"),
        ("opencanvas-telemetry-token", "OPENCANVAS_TELEMETRY_AUTH_TOKEN"),
        (
            "opencanvas-telemetry-pseudonymization-secret",
            "OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET",
        ),
        (
            "opencanvas-observability-operator-user-ids",
            "OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS",
        ),
    ]
    assert contract["providerRuntime"] == {
        "smtpHost": "sandbox.smtp.mailtrap.io",
        "smtpPort": 2525,
        "smtpStartTls": True,
        "smtpFromAddress": "mobius77-validation@example.invalid",
        "runtimeMode": "isolated-synthetic-private",
    }
    source = contract["privateAcrSource"]
    assert source["gitRemoteAccessAllowed"] is False
    assert source["publicRegistryAccess"] is False
    assert source["mutableTagsAllowed"] is False
    assert source["temporarySourceTagPreexistenceDecision"] == "deny"
    assert source["temporarySourceTagRemovedAfterDigestResolution"] is True
    assert source["deploymentReference"] == "digest-only"


def test_contract_tampering_fails_closed() -> None:
    contract = deepcopy(load_managed_binding_contract())
    contract["defaultAuthority"]["provisioningAuthorized"] = True
    with pytest.raises(ContractError, match=r"default authority|schema|closed contract"):
        validate_managed_binding_contract(contract)

    overlay = deepcopy(load_operation_overlay())
    overlay["operationOrder"][0] = "altered-operation"
    with pytest.raises(ContractError, match=r"operation order|integrity"):
        validate_operation_overlay(overlay)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("fixedSkus", "vpnGateway", "VpnGw1"),
        ("vpn", "gatewaySku", "VpnGw1"),
        ("vpn", "gatewayGeneration", "Generation1"),
        ("vpn", "publicIpSku", "Basic"),
        ("vpn", "publicIpAllocation", "Dynamic"),
        ("vpn", "publicIpAvailabilityZoneMode", "zonal-1"),
        ("vpn", "publicIpZones", ["1"]),
    ],
)
def test_vpn_gateway_compatibility_contract_fails_closed(
    section: str, field: str, value: str
) -> None:
    contract = deepcopy(load_managed_binding_contract())
    contract[section][field] = value
    with pytest.raises(ContractError, match="VPN"):
        validate_managed_binding_contract(contract)


@pytest.mark.parametrize("cleanup_location", [None, "", "southcentralus", "eastus"])
def test_cleanup_location_missing_or_outside_exact_allowlist_fails_closed(
    cleanup_location: str | None,
) -> None:
    contract = deepcopy(load_managed_binding_contract())
    if cleanup_location is None:
        contract.pop("cleanupLocation")
    else:
        contract["cleanupLocation"] = cleanup_location
    with pytest.raises(ContractError, match=r"cleanupLocation|closed contract"):
        validate_managed_binding_contract(contract)


@pytest.mark.parametrize("redis_location", [None, "", "southcentralus", "australiaeast"])
def test_redis_location_missing_or_outside_exact_allowlist_fails_closed(
    redis_location: str | None,
) -> None:
    contract = deepcopy(load_managed_binding_contract())
    if redis_location is None:
        contract.pop("redisLocation")
    else:
        contract["redisLocation"] = redis_location
    with pytest.raises(ContractError, match=r"redisLocation|Redis region|closed contract"):
        validate_managed_binding_contract(contract)


def test_redis_sku_change_fails_closed() -> None:
    contract = deepcopy(load_managed_binding_contract())
    contract["fixedSkus"]["redis"] = "Balanced_B1"
    with pytest.raises(ContractError, match="Redis SKU"):
        validate_managed_binding_contract(contract)


def test_one_run_ledger_expires_and_receipts_reject_replay(tmp_path: Path) -> None:
    head = TEST_IMAGE_SOURCE_COMMIT
    ledger = build_authorization_ledger(
        issued_at_utc=NOW,
        repository_head=head,
        pending_image=_pending_image(),
        maximum_lifetime_seconds=60,
    )
    allowed = operation_authorization_decision(
        OPERATION_IDS[0],
        ledger=ledger,
        now_utc=NOW,
        expected_repository_head=head,
    )
    assert allowed["decision"] == "allow-once"
    assert allowed["provisioningAuthorized"] is False
    assert allowed["secretAccessAuthorized"] is False

    receipt_directory = tmp_path / "receipts"
    claim_operation_receipt(
        ledger=ledger,
        operation_id=OPERATION_IDS[0],
        receipt_directory=receipt_directory,
        now_utc=NOW,
        expected_repository_head=head,
    )
    with pytest.raises(ContractError, match="already consumed"):
        claim_operation_receipt(
            ledger=ledger,
            operation_id=OPERATION_IDS[0],
            receipt_directory=receipt_directory,
            now_utc=NOW,
            expected_repository_head=head,
        )
    with pytest.raises(ContractError, match="not currently valid"):
        validate_authorization_ledger(
            ledger,
            now_utc=NOW + timedelta(seconds=60),
            expected_repository_head=head,
        )


def test_local_dry_run_never_authorizes_or_invokes_azure() -> None:
    result = dry_run()
    assert result["status"] == "valid-local-only"
    assert result["operationCount"] == 15
    assert result["lifecycleOperationCount"] == 8
    assert result["azureProcessInvocations"] == 0
    assert result["provisioningAuthorized"] is False
    assert result["secretAccessAuthorized"] is False


def test_provider_type_inventory_projection_is_bounded_to_names() -> None:
    overlay = load_operation_overlay()
    methods = overlay["methodDefinitions"]
    assert isinstance(methods, dict)
    assert "azure-provider-resource-inventory-v1" not in methods
    method = methods["azure-provider-resource-type-inventory-v1"]
    assert isinstance(method, dict)
    arguments = method["argumentVector"]
    assert isinstance(arguments, list)
    query = arguments[arguments.index("--query") + 1]
    assert query == (
        "{registrationState:registrationState,resourceTypes:resourceTypes[].resourceType}"
    )
    assert "apiVersions" not in query
    assert "locations" not in query


class ManagedBindingFakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.versions = load_managed_binding_contract()["providerApiVersions"]

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        del environment, timeout_seconds, maximum_output_bytes
        self.calls.append(argv)
        if argv == EXPECTED_ACCOUNT_COMMAND:
            payload: JsonValue = {
                "environmentName": "AzureCloud",
                "state": "Enabled",
                "isDefault": True,
                "userType": "user",
                "id": SYNTHETIC_SUBSCRIPTION,
                "tenantId": SYNTHETIC_TENANT,
            }
        elif argv[1:3] == ("provider", "show"):
            namespace = argv[argv.index("--namespace") + 1]
            query = argv[argv.index("--query") + 1]
            match = re.search(r"resourceType=='([^']+)'", query)
            assert match is not None
            resource_type = match.group(1)
            key = f"{namespace}/{resource_type}"
            payload = {
                "registrationState": (
                    "NotRegistered" if namespace == "Microsoft.App" else "Registered"
                ),
                "resourceType": resource_type,
                "apiVersions": [self.versions[key]],
                "locations": [
                    "West US"
                    if namespace == "Microsoft.Automation"
                    else "Australia Central"
                    if namespace == "Microsoft.Cache"
                    else "Central US"
                    if namespace == "Microsoft.DBforPostgreSQL"
                    else "South Central US"
                ],
            }
        else:
            raise AssertionError(f"unexpected fake command: {argv[:3]}")
        return _ProcessCapture(
            exit_code=0,
            timed_out=False,
            oversized=False,
            read_failed=False,
            stdout=bytearray(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()),
        )


def _automation_metadata_row(
    resource_type: str,
    *,
    api_versions: tuple[str, ...] = ("2024-10-23",),
    locations: tuple[str, ...] | None = None,
) -> dict[str, JsonValue]:
    if locations is None:
        locations = (
            ("West US",)
            if "automationaccounts" in resource_type.casefold()
            else ("South Central US",)
        )
    return {
        "resourceType": resource_type,
        "apiVersions": list(api_versions),
        "locations": list(locations),
    }


class ExactChildMetadataAdapter:
    def __init__(
        self,
        *,
        registration_state: str = "Registered",
        direct_child: dict[str, JsonValue] | None = None,
        inventory_rows: list[dict[str, JsonValue]] | None = None,
    ) -> None:
        self.registration_state = registration_state
        self.direct_child = direct_child
        self.inventory_rows = list(inventory_rows or [])
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        del environment, timeout_seconds, maximum_output_bytes
        self.calls.append(argv)
        assert argv[1:3] == ("provider", "show")
        query = argv[argv.index("--query") + 1]
        if "resourceTypes:resourceTypes[].resourceType" in query:
            payload: JsonValue = {
                "registrationState": self.registration_state,
                "resourceTypes": [row["resourceType"] for row in self.inventory_rows],
            }
        else:
            match = re.search(r"resourceType=='([^']+)'", query)
            assert match is not None
            requested_resource_type = match.group(1)
            if (
                self.direct_child is not None
                and self.direct_child["resourceType"] == requested_resource_type
            ):
                row = self.direct_child
            else:
                rows = [
                    row
                    for row in self.inventory_rows
                    if row["resourceType"] == requested_resource_type
                ]
                assert len(rows) <= 1
                row = None if not rows else rows[0]
            payload = {
                "registrationState": self.registration_state,
                "resourceType": None if row is None else row["resourceType"],
                "apiVersions": None if row is None else row["apiVersions"],
                "locations": None if row is None else row["locations"],
            }
        return _ProcessCapture(
            exit_code=0,
            timed_out=False,
            oversized=False,
            read_failed=False,
            stdout=bytearray(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()),
        )


class NetworkUsageAdapter:
    def __init__(self, payload: JsonValue) -> None:
        self.payload = payload

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        del environment, timeout_seconds, maximum_output_bytes
        assert argv[1:3] == ("network", "list-usages")
        return _ProcessCapture(
            exit_code=0,
            timed_out=False,
            oversized=False,
            read_failed=False,
            stdout=bytearray(
                json.dumps(self.payload, separators=(",", ":"), sort_keys=True).encode()
            ),
        )


class VnetIsolationAdapter:
    def __init__(self, payload: JsonValue) -> None:
        self.payload = payload

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        del environment, timeout_seconds, maximum_output_bytes
        assert argv[1:4] == ("network", "vnet", "list")
        query = argv[argv.index("--query") + 1]
        assert query == (
            "[].{name:name,resourceGroup:resourceGroup,location:location,"
            "prefixes:addressSpace.addressPrefixes}"
        )
        return _ProcessCapture(
            exit_code=0,
            timed_out=False,
            oversized=False,
            read_failed=False,
            stdout=bytearray(
                json.dumps(self.payload, separators=(",", ":"), sort_keys=True).encode()
            ),
        )


class AcrSourceAdapter:
    def __init__(
        self,
        *,
        available: bool,
        reason: str | None,
        current: JsonValue = None,
    ) -> None:
        self.available = available
        self.reason = reason
        self.current = current
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        del environment, timeout_seconds, maximum_output_bytes
        self.calls.append(argv)
        if argv[1:3] == ("acr", "check-name"):
            payload: JsonValue = {
                "available": self.available,
                "reason": self.reason,
            }
        else:
            assert argv[1:3] == ("acr", "show")
            assert argv[argv.index("--name") + 1] == "acrmobius7711564669"
            assert argv[argv.index("--resource-group") + 1] == "rg-solarplexus-mobius-77-staging"
            query = argv[argv.index("--query") + 1]
            assert "id:" not in query
            assert "loginServer:" not in query
            payload = self.current
        return _ProcessCapture(
            exit_code=0,
            timed_out=False,
            oversized=False,
            read_failed=False,
            stdout=bytearray(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()),
        )


def _exact_current_acr(**overrides: JsonValue) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {
        "name": "acrmobius7711564669",
        "resourceGroup": "rg-solarplexus-mobius-77-staging",
        "location": "southcentralus",
        "sku": "Premium",
        "adminUserEnabled": False,
        "anonymousPullEnabled": False,
        "dataEndpointEnabled": False,
        "networkRuleBypassOptions": "None",
        "publicNetworkAccess": "Disabled",
        "zoneRedundancy": "Disabled",
    }
    value.update(overrides)
    return value


def _vnet_row(
    *,
    name: str = "vnet-mobius77-staging",
    resource_group: str = "rg-solarplexus-mobius-77-staging",
    location: str = "southcentralus",
    prefixes: JsonValue = None,
) -> dict[str, JsonValue]:
    return {
        "name": name,
        "resourceGroup": resource_group,
        "location": location,
        "prefixes": ["10.77.0.0/20"] if prefixes is None else prefixes,
    }


def _network_usage_rows(
    overrides: Mapping[str, tuple[JsonValue, JsonValue]] | None = None,
) -> list[dict[str, JsonValue]]:
    values: dict[str, tuple[JsonValue, JsonValue]] = {
        "VirtualNetworks": ("0", "10"),
        "PublicIPAddresses": ("0", "10"),
        "IPv4StandardSkuPublicIpAddresses": ("0", "10"),
        "NetworkInterfaces": ("0", "20"),
        "PrivateEndpoints": ("0", "10"),
        "SubnetsPerVirtualNetwork": ("0", "100"),
        "IPConfigurationsPerVirtualNetwork": (0, 100),
    }
    values.update(overrides or {})
    return [
        {"name": name, "current": current, "limit": limit}
        for name, (current, limit) in values.items()
    ]


def _run_exact_child_check(
    monkeypatch: pytest.MonkeyPatch,
    adapter: ExactChildMetadataAdapter,
    *,
    provider_key: str = "Microsoft.Automation/automationAccounts/jobSchedules",
) -> tuple[str, str, dict[str, JsonValue]]:
    monkeypatch.setattr(
        managed_binding_execution,
        "_provider_keys",
        lambda operation_id: (provider_key,),
    )
    return managed_binding_execution._provider_checks(
        "provider-registration-api-versions",
        adapter=adapter,
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
        require_registration=True,
        require_region=True,
    )


def test_network_usage_accepts_canonical_decimal_strings() -> None:
    result = managed_binding_execution._network_usage(
        adapter=NetworkUsageAdapter(_network_usage_rows()),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result == (
        "proved",
        "network-capacity-bounded",
        {"dimension-count": 7, "every-current-below-limit": True},
    )


def test_network_usage_decimal_strings_preserve_limit_denial() -> None:
    result = managed_binding_execution._network_usage(
        adapter=NetworkUsageAdapter(_network_usage_rows({"PrivateEndpoints": ("9", "10")})),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result[0:2] == ("blocked", "network-capacity-not-available")


@pytest.mark.parametrize(
    "value",
    ["", "01", "+1", "-1", "1.0", " 1", "1 ", "9" * 21, None, True],
)
def test_network_usage_rejects_noncanonical_values(value: JsonValue) -> None:
    with pytest.raises(ManagedBindingExecutionError, match="network-usage-malformed"):
        managed_binding_execution._network_usage(
            adapter=NetworkUsageAdapter(_network_usage_rows({"VirtualNetworks": (value, "10")})),
            raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
        )


def test_network_usage_rejects_json_floats_before_quota_parsing() -> None:
    with pytest.raises(ManagedBindingExecutionError, match="azure-method-output-malformed"):
        managed_binding_execution._network_usage(
            adapter=NetworkUsageAdapter(_network_usage_rows({"VirtualNetworks": (1.0, "10")})),
            raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
        )


def test_network_usage_enforces_per_resource_minimum() -> None:
    result = managed_binding_execution._network_usage(
        adapter=NetworkUsageAdapter(_network_usage_rows({"SubnetsPerVirtualNetwork": ("0", "6")})),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result[0:2] == ("blocked", "network-capacity-not-available")


@pytest.mark.parametrize("shape", ["missing", "extra", "duplicate"])
def test_network_usage_requires_exact_closed_dimensions(shape: str) -> None:
    rows = _network_usage_rows()
    if shape == "missing":
        rows.pop()
    elif shape == "extra":
        rows.append({"name": "UnrelatedQuota", "current": "0", "limit": "10"})
    else:
        rows.append(dict(rows[0]))

    with pytest.raises(ManagedBindingExecutionError, match="network-usage-malformed"):
        managed_binding_execution._network_usage(
            adapter=NetworkUsageAdapter(rows),
            raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
        )


def test_network_usage_query_is_exactly_closed_to_manifest_dimensions() -> None:
    contract = load_managed_binding_contract()
    quota = contract["networkQuotaRequirements"]
    assert isinstance(quota, dict)
    required_names = set(quota["additiveHeadroom"]) | set(quota["perResourceMinimum"])
    assert required_names == {
        "VirtualNetworks",
        "PublicIPAddresses",
        "IPv4StandardSkuPublicIpAddresses",
        "NetworkInterfaces",
        "PrivateEndpoints",
        "SubnetsPerVirtualNetwork",
        "IPConfigurationsPerVirtualNetwork",
    }

    overlay = load_operation_overlay()
    methods = overlay["methodDefinitions"]
    assert isinstance(methods, dict)
    method = methods["azure-network-usage-v1"]
    assert isinstance(method, dict)
    arguments = method["argumentVector"]
    assert isinstance(arguments, list)
    query = arguments[arguments.index("--query") + 1]
    assert "[].{" not in query
    assert all(f"name.value=='{name}'" in query for name in required_names)


def test_vnet_isolation_accepts_only_the_exact_current_contract_vnet() -> None:
    result = managed_binding_execution._vnet_isolation(
        adapter=VnetIsolationAdapter([_vnet_row()]),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result == (
        "proved",
        "vnet-plan-isolated",
        {"prefix-count": 1, "overlap-count": 0},
    )


def test_vnet_isolation_accepts_an_unused_plan() -> None:
    result = managed_binding_execution._vnet_isolation(
        adapter=VnetIsolationAdapter([]),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result == (
        "proved",
        "vnet-plan-isolated",
        {"prefix-count": 0, "overlap-count": 0},
    )


@pytest.mark.parametrize(
    "row",
    [
        _vnet_row(resource_group="rg-solarplexus-mobius-77-other"),
        _vnet_row(name="vnet-mobius77-other"),
        _vnet_row(name="vnet-mobius77-other", prefixes=["10.77.8.0/21"]),
    ],
)
def test_vnet_isolation_rejects_every_other_overlap(
    row: dict[str, JsonValue],
) -> None:
    result = managed_binding_execution._vnet_isolation(
        adapter=VnetIsolationAdapter([row]),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result[0:2] == ("blocked", "vnet-plan-overlaps")
    assert result[2]["overlap-count"] == 1


@pytest.mark.parametrize(
    "row",
    [
        _vnet_row(location="westus"),
        _vnet_row(prefixes=["10.88.0.0/20"]),
        _vnet_row(prefixes=["10.77.0.0/20", "10.88.0.0/20"]),
    ],
)
def test_vnet_isolation_rejects_expected_resource_drift(
    row: dict[str, JsonValue],
) -> None:
    result = managed_binding_execution._vnet_isolation(
        adapter=VnetIsolationAdapter([row]),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result[0:2] == ("blocked", "vnet-plan-resource-drift")


def test_vnet_isolation_rejects_an_additional_overlap_beside_the_exact_vnet() -> None:
    result = managed_binding_execution._vnet_isolation(
        adapter=VnetIsolationAdapter([_vnet_row(), _vnet_row(name="vnet-mobius77-other")]),
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )

    assert result[0:2] == ("blocked", "vnet-plan-overlaps")
    assert result[2] == {"prefix-count": 2, "overlap-count": 1}


@pytest.mark.parametrize(
    "payload",
    [
        [_vnet_row(), _vnet_row()],
        [{"name": "vnet-mobius77-staging"}],
        [_vnet_row(prefixes=[])],
        [_vnet_row(prefixes=["not-a-cidr"])],
        [_vnet_row(prefixes=[None])],
    ],
)
def test_vnet_isolation_rejects_malformed_or_duplicate_rows(
    payload: list[dict[str, JsonValue]],
) -> None:
    with pytest.raises(ManagedBindingExecutionError, match="vnet-prefix-output-malformed"):
        managed_binding_execution._vnet_isolation(
            adapter=VnetIsolationAdapter(payload),
            raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
        )


def _run_acr_source(
    monkeypatch: pytest.MonkeyPatch,
    adapter: AcrSourceAdapter,
) -> tuple[str, str, dict[str, JsonValue]]:
    monkeypatch.setattr(
        managed_binding_execution,
        "_provider_checks",
        lambda *args, **kwargs: (
            "proved",
            "provider-prerequisites-proved",
            {"required-resource-count": 1},
        ),
    )
    return managed_binding_execution._acr_source(
        adapter=adapter,
        raw_subscription_id=SYNTHETIC_SUBSCRIPTION,
    )


def test_acr_source_accepts_an_available_initial_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AcrSourceAdapter(available=True, reason=None)

    result = _run_acr_source(monkeypatch, adapter)

    assert result[0:2] == ("proved", "private-acr-source-proved")
    assert result[2]["literal-name-available"] is True
    assert result[2]["exact-current-registry-proved"] is False
    assert len(adapter.calls) == 1


def test_acr_source_accepts_only_the_exact_current_private_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AcrSourceAdapter(
        available=False,
        reason="AlreadyExists",
        current=_exact_current_acr(),
    )

    result = _run_acr_source(monkeypatch, adapter)

    assert result[0:2] == ("proved", "private-acr-source-proved")
    assert result[2]["literal-name-available"] is False
    assert result[2]["exact-current-registry-proved"] is True
    assert len(adapter.calls) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "acrmobius77other"),
        ("resourceGroup", "rg-solarplexus-mobius-77-other"),
        ("location", "westus"),
        ("sku", "Basic"),
        ("adminUserEnabled", True),
        ("anonymousPullEnabled", True),
        ("dataEndpointEnabled", True),
        ("networkRuleBypassOptions", "AzureServices"),
        ("publicNetworkAccess", "Enabled"),
        ("zoneRedundancy", "Enabled"),
    ],
)
def test_acr_source_rejects_any_current_registry_drift(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: JsonValue,
) -> None:
    adapter = AcrSourceAdapter(
        available=False,
        reason="AlreadyExists",
        current=_exact_current_acr(**{field: value}),
    )

    result = _run_acr_source(monkeypatch, adapter)

    assert result[0:2] == ("blocked", "private-acr-source-unresolved")
    assert result[2]["exact-current-registry-proved"] is False


def test_acr_source_does_not_reconcile_an_unrelated_unavailable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AcrSourceAdapter(
        available=False,
        reason="Invalid",
        current=_exact_current_acr(),
    )

    result = _run_acr_source(monkeypatch, adapter)

    assert result[0:2] == ("blocked", "private-acr-source-unresolved")
    assert result[2]["exact-current-registry-proved"] is False
    assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    "current",
    [None, {}, {**_exact_current_acr(), "unexpected": True}],
)
def test_acr_source_rejects_malformed_current_registry_output(
    monkeypatch: pytest.MonkeyPatch,
    current: JsonValue,
) -> None:
    adapter = AcrSourceAdapter(
        available=False,
        reason="AlreadyExists",
        current=current,
    )

    with pytest.raises(ManagedBindingExecutionError, match="acr-current-output-malformed"):
        _run_acr_source(monkeypatch, adapter)


def test_exact_automation_job_schedules_parent_fallback_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ExactChildMetadataAdapter(
        inventory_rows=[_automation_metadata_row("automationAccounts")]
    )

    status, explanation, fields = _run_exact_child_check(monkeypatch, adapter)

    assert (status, explanation) == ("proved", "provider-prerequisites-proved")
    assert fields["parent-fallback-count"] == 1
    assert fields["pinned-api-version-count"] == 1
    assert fields["approved-region-count"] == 1


def test_exact_automation_schedules_parent_fallback_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, explanation, fields = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(inventory_rows=[_automation_metadata_row("automationAccounts")]),
        provider_key="Microsoft.Automation/automationAccounts/schedules",
    )

    assert (status, explanation) == ("proved", "provider-prerequisites-proved")
    assert fields["parent-fallback-count"] == 1
    assert fields["pinned-api-version-count"] == 1
    assert fields["approved-region-count"] == 1


def test_automation_cleanup_region_is_exact_and_staging_region_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(direct_child=_automation_metadata_row("automationAccounts")),
        provider_key="Microsoft.Automation/automationAccounts",
    )
    assert approved[0:2] == ("proved", "provider-prerequisites-proved")

    blocked = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "automationAccounts", locations=("South Central US",)
            )
        ),
        provider_key="Microsoft.Automation/automationAccounts",
    )
    assert blocked[0:2] == ("blocked", "approved-region-unavailable")


def test_redis_region_is_exact_and_staging_region_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "redisEnterprise",
                api_versions=("2026-05-01-preview",),
                locations=("Australia Central",),
            )
        ),
        provider_key="Microsoft.Cache/redisEnterprise",
    )
    assert approved[0:2] == ("proved", "provider-prerequisites-proved")

    blocked = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "redisEnterprise",
                api_versions=("2026-05-01-preview",),
                locations=("South Central US",),
            )
        ),
        provider_key="Microsoft.Cache/redisEnterprise",
    )
    assert blocked[0:2] == ("blocked", "approved-region-unavailable")


def test_exact_redis_access_policy_parent_fallback_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ExactChildMetadataAdapter(
        inventory_rows=[
            _automation_metadata_row(
                "redisEnterprise/databases",
                api_versions=("2026-05-01-preview",),
                locations=("Australia Central",),
            )
        ]
    )

    status, explanation, fields = _run_exact_child_check(
        monkeypatch,
        adapter,
        provider_key=("Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments"),
    )

    assert (status, explanation) == ("proved", "provider-prerequisites-proved")
    assert fields["parent-fallback-count"] == 1
    assert fields["pinned-api-version-count"] == 1
    assert fields["approved-region-count"] == 1
    assert all(call[1:3] == ("provider", "show") for call in adapter.calls)


def test_redis_access_policy_fallback_rejects_missing_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(inventory_rows=[]),
        provider_key=("Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments"),
    )

    assert result[0:2] == ("blocked", "required-resource-type-unavailable")


def test_redis_access_policy_fallback_rejects_parent_without_pinned_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            inventory_rows=[
                _automation_metadata_row(
                    "redisEnterprise/databases",
                    api_versions=("2025-07-01",),
                    locations=("Australia Central",),
                )
            ]
        ),
        provider_key=("Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments"),
    )

    assert result[0:2] == ("blocked", "pinned-api-version-unavailable")


def test_redis_access_policy_fallback_rejects_unrelated_redis_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated_key = "Microsoft.Cache/redisEnterprise/databases/unrelatedChild"
    original = managed_binding_execution._provider_binding

    def binding(key: str) -> tuple[str, str, str]:
        if key == unrelated_key:
            return (
                "Microsoft.Cache",
                "redisEnterprise/databases/unrelatedChild",
                "2026-05-01-preview",
            )
        return original(key)

    monkeypatch.setattr(managed_binding_execution, "_provider_binding", binding)
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            inventory_rows=[
                _automation_metadata_row(
                    "redisEnterprise/databases",
                    api_versions=("2026-05-01-preview",),
                    locations=("Australia Central",),
                )
            ]
        ),
        provider_key=unrelated_key,
    )

    assert result[0:2] == ("blocked", "required-resource-type-unavailable")


def test_exact_child_metadata_fallback_set_remains_closed() -> None:
    assert managed_binding_execution._EXACT_CHILD_METADATA_FALLBACKS == {
        "Microsoft.Automation/automationAccounts/jobSchedules": (
            "Microsoft.Automation",
            "automationAccounts/jobSchedules",
            "automationAccounts",
            "2024-10-23",
        ),
        "Microsoft.Automation/automationAccounts/schedules": (
            "Microsoft.Automation",
            "automationAccounts/schedules",
            "automationAccounts",
            "2024-10-23",
        ),
        "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments": (
            "Microsoft.Cache",
            "redisEnterprise/databases/accessPolicyAssignments",
            "redisEnterprise/databases",
            "2026-05-01-preview",
        ),
        "Microsoft.Network/privateEndpoints/privateDnsZoneGroups": (
            "Microsoft.Network",
            "privateEndpoints/privateDnsZoneGroups",
            "privateEndpoints",
            "2025-07-01",
        ),
    }


@pytest.mark.parametrize(
    ("registration_state", "rows", "explanation"),
    [
        (
            "NotRegistered",
            [_automation_metadata_row("automationAccounts")],
            "required-provider-not-registered",
        ),
        ("Registered", [], "required-resource-type-unavailable"),
        (
            "Registered",
            [_automation_metadata_row("automationAccounts", api_versions=("2023-11-01",))],
            "pinned-api-version-unavailable",
        ),
        (
            "Registered",
            [_automation_metadata_row("automationAccounts", locations=("East US",))],
            "approved-region-unavailable",
        ),
    ],
)
def test_automation_job_schedules_fallback_prerequisites_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    registration_state: str,
    rows: list[dict[str, JsonValue]],
    explanation: str,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            registration_state=registration_state,
            inventory_rows=rows,
        ),
    )

    assert result[0] == "blocked"
    assert result[1] == explanation


def test_exact_fallback_rejects_unrelated_provider_child_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(inventory_rows=[_automation_metadata_row("automationAccounts")]),
        provider_key="Microsoft.KeyVault/vaults/secrets",
    )

    assert result[0:2] == ("blocked", "required-resource-type-unavailable")


def test_automation_fallback_rejects_another_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = managed_binding_execution._provider_binding

    def altered_binding(key: str) -> tuple[str, str, str]:
        namespace, resource_type, version = original(key)
        if key == "Microsoft.Automation/automationAccounts/jobSchedules":
            version = "2023-11-01"
        return namespace, resource_type, version

    monkeypatch.setattr(managed_binding_execution, "_provider_binding", altered_binding)
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(inventory_rows=[_automation_metadata_row("automationAccounts")]),
    )

    assert result[0:2] == ("blocked", "required-resource-type-unavailable")


def test_automation_fallback_rejects_malformed_or_nearby_metadata_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ManagedBindingExecutionError, match="provider-metadata-malformed"):
        _run_exact_child_check(
            monkeypatch,
            ExactChildMetadataAdapter(
                inventory_rows=[
                    _automation_metadata_row("automationAccounts//jobSchedules"),
                    _automation_metadata_row("automationAccounts"),
                ]
            ),
        )


def test_automation_fallback_rejects_missing_committed_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = managed_binding_execution._provider_binding

    def missing_binding(key: str) -> tuple[str, str, str]:
        if key == "Microsoft.Automation/automationAccounts/jobSchedules":
            raise ManagedBindingExecutionError("provider-api-binding-missing")
        return original(key)

    monkeypatch.setattr(managed_binding_execution, "_provider_binding", missing_binding)
    with pytest.raises(ManagedBindingExecutionError, match="provider-api-binding-missing"):
        _run_exact_child_check(
            monkeypatch,
            ExactChildMetadataAdapter(
                inventory_rows=[_automation_metadata_row("automationAccounts")]
            ),
        )


def test_explicit_automation_child_metadata_overrides_parent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_child = _automation_metadata_row(
        "automationAccounts/jobSchedules",
        api_versions=("2023-11-01",),
    )
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=explicit_child,
            inventory_rows=[
                explicit_child,
                _automation_metadata_row("automationAccounts"),
            ],
        ),
    )

    assert result[0:2] == ("blocked", "pinned-api-version-unavailable")
    assert result[2]["parent-fallback-count"] == 0


def test_normalized_explicit_child_metadata_is_validated_without_parent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            inventory_rows=[
                _automation_metadata_row("MICROSOFT.AUTOMATION/AUTOMATIONACCOUNTS/JOBSCHEDULES"),
                _automation_metadata_row("automationAccounts"),
            ]
        ),
    )

    assert result[0:2] == ("proved", "provider-prerequisites-proved")
    assert result[2]["parent-fallback-count"] == 0


def test_exact_private_dns_zone_group_parent_fallback_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, explanation, fields = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            inventory_rows=[
                _automation_metadata_row("privateEndpoints", api_versions=("2025-07-01",))
            ]
        ),
        provider_key="Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
    )

    assert (status, explanation) == ("proved", "provider-prerequisites-proved")
    assert fields["parent-fallback-count"] == 1
    assert fields["pinned-api-version-count"] == 1
    assert fields["approved-region-count"] == 1


@pytest.mark.parametrize(
    ("registration_state", "rows", "explanation"),
    [
        (
            "NotRegistered",
            [_automation_metadata_row("privateEndpoints", api_versions=("2025-07-01",))],
            "required-provider-not-registered",
        ),
        ("Registered", [], "required-resource-type-unavailable"),
        (
            "Registered",
            [_automation_metadata_row("privateEndpoints", api_versions=("2024-05-01",))],
            "pinned-api-version-unavailable",
        ),
        (
            "Registered",
            [
                _automation_metadata_row(
                    "privateEndpoints",
                    api_versions=("2025-07-01",),
                    locations=("West US",),
                )
            ],
            "approved-region-unavailable",
        ),
    ],
)
def test_private_dns_zone_group_fallback_prerequisites_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    registration_state: str,
    rows: list[dict[str, JsonValue]],
    explanation: str,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            registration_state=registration_state,
            inventory_rows=rows,
        ),
        provider_key="Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
    )

    assert result[0:2] == ("blocked", explanation)


def test_private_dns_zone_group_fallback_rejects_old_or_other_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = managed_binding_execution._provider_binding

    def altered_binding(key: str) -> tuple[str, str, str]:
        namespace, resource_type, version = original(key)
        if key == "Microsoft.Network/privateEndpoints/privateDnsZoneGroups":
            version = "2026-01-01"
        return namespace, resource_type, version

    monkeypatch.setattr(managed_binding_execution, "_provider_binding", altered_binding)
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            inventory_rows=[
                _automation_metadata_row("privateEndpoints", api_versions=("2025-07-01",))
            ]
        ),
        provider_key="Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
    )
    assert result[0:2] == ("blocked", "required-resource-type-unavailable")

    with pytest.raises(ManagedBindingExecutionError, match="provider-api-binding-missing"):
        _run_exact_child_check(
            monkeypatch,
            ExactChildMetadataAdapter(
                inventory_rows=[
                    _automation_metadata_row("privateEndpoints", api_versions=("2025-07-01",))
                ]
            ),
            provider_key="Microsoft.Network/privateEndpoints/privateDnsZoneGroups/other",
        )


def test_explicit_private_dns_zone_group_metadata_overrides_parent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_child = _automation_metadata_row(
        "privateEndpoints/privateDnsZoneGroups",
        api_versions=("2024-05-01",),
    )
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=explicit_child,
            inventory_rows=[
                explicit_child,
                _automation_metadata_row("privateEndpoints", api_versions=("2025-07-01",)),
            ],
        ),
        provider_key="Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
    )

    assert result[0:2] == ("blocked", "pinned-api-version-unavailable")
    assert result[2]["parent-fallback-count"] == 0


def test_exact_role_assignment_binding_is_region_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "roleAssignments",
                api_versions=("2022-04-01",),
                locations=(),
            )
        ),
        provider_key="Microsoft.Authorization/roleAssignments",
    )

    assert result[0:2] == ("proved", "provider-prerequisites-proved")
    assert result[2]["approved-region-count"] == 1


@pytest.mark.parametrize(
    ("provider_key", "resource_type"),
    [
        ("Microsoft.Network/privateDnsZones", "privateDnsZones"),
        (
            "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
            "privateDnsZones/virtualNetworkLinks",
        ),
    ],
)
def test_exact_private_dns_bindings_require_global_metadata(
    monkeypatch: pytest.MonkeyPatch,
    provider_key: str,
    resource_type: str,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                resource_type,
                api_versions=("2024-06-01",),
                locations=("global",),
            )
        ),
        provider_key=provider_key,
    )

    assert result[0:2] == ("proved", "provider-prerequisites-proved")
    assert result[2]["approved-region-count"] == 1


def test_private_dns_global_exception_rejects_wrong_location_or_neighbor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "privateDnsZones",
                api_versions=("2024-06-01",),
                locations=("West US",),
            )
        ),
        provider_key="Microsoft.Network/privateDnsZones",
    )
    assert result[0:2] == ("blocked", "approved-region-unavailable")

    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "privateEndpoints",
                api_versions=("2026-01-01",),
                locations=("global",),
            )
        ),
        provider_key="Microsoft.Network/privateEndpoints",
    )
    assert result[0:2] == ("blocked", "approved-region-unavailable")


def test_region_independent_exception_rejects_another_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "vaults",
                api_versions=("2026-02-01",),
                locations=(),
            )
        ),
        provider_key="Microsoft.KeyVault/vaults",
    )

    assert result[0:2] == ("blocked", "approved-region-unavailable")


def test_region_independent_exception_rejects_another_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = managed_binding_execution._provider_binding

    def altered_binding(key: str) -> tuple[str, str, str]:
        namespace, resource_type, version = original(key)
        if key == "Microsoft.Authorization/roleAssignments":
            version = "2020-10-01-preview"
        return namespace, resource_type, version

    monkeypatch.setattr(managed_binding_execution, "_provider_binding", altered_binding)
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            direct_child=_automation_metadata_row(
                "roleAssignments",
                api_versions=("2020-10-01-preview",),
                locations=(),
            )
        ),
        provider_key="Microsoft.Authorization/roleAssignments",
    )

    assert result[0:2] == ("blocked", "approved-region-unavailable")


def test_region_independent_exception_still_requires_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_exact_child_check(
        monkeypatch,
        ExactChildMetadataAdapter(
            registration_state="NotRegistered",
            direct_child=_automation_metadata_row(
                "roleAssignments",
                api_versions=("2022-04-01",),
                locations=(),
            ),
        ),
        provider_key="Microsoft.Authorization/roleAssignments",
    )

    assert result[0:2] == ("blocked", "required-provider-not-registered")


def test_closed_package_blocks_on_unregistered_required_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fingerprint = topology_framework._identifier_fingerprint

    def fingerprint(identifier: str, *, domain: str) -> str:
        if identifier == SYNTHETIC_SUBSCRIPTION and domain == SUBSCRIPTION_FINGERPRINT_DOMAIN:
            return SUBSCRIPTION_FINGERPRINT
        if identifier == SYNTHETIC_TENANT and domain == TENANT_FINGERPRINT_DOMAIN:
            return TENANT_FINGERPRINT
        return real_fingerprint(identifier, domain=domain)

    monkeypatch.setattr(topology_framework, "_identifier_fingerprint", fingerprint)
    ledger_path = tmp_path / "authorization-ledger.json"
    ledger_path.write_bytes(
        canonical_bytes(
            build_authorization_ledger(
                issued_at_utc=NOW,
                repository_head=TEST_IMAGE_SOURCE_COMMIT,
                pending_image=_pending_image(),
            )
        )
    )
    adapter = ManagedBindingFakeAdapter()
    result = execute_package_one(
        ledger_path=ledger_path,
        repository_head=TEST_IMAGE_SOURCE_COMMIT,
        receipt_directory=tmp_path / "receipts",
        adapter=adapter,
        now_utc=NOW,
    )

    assert result["status"] == "blocked"
    assert result["operationCount"] == 2
    assert result["provedCount"] == 1
    assert result["blockedOperationId"] == "provider-registration-api-versions"
    assert result["blockedExplanationCode"] == "required-provider-not-registered"
    assert result["mutationPerformed"] is False
    assert result["provisioningPerformed"] is False
    assert not (tmp_path / "receipts" / "pre-secret-provisioning.receipt.json").exists()
    assert not (tmp_path / "receipts" / "publish-api-image.receipt.json").exists()
    assert all(
        call == EXPECTED_ACCOUNT_COMMAND or call[1:3] == ("provider", "show")
        for call in adapter.calls
    )


def test_lifecycle_is_closed_private_digest_bound_and_secret_value_blind() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    text += IMAGE_PUBLICATION_SCRIPT.read_text(encoding="utf-8")
    assert "--runtime-config" not in text
    assert "OPENCANVAS_OPENAI_API_KEY" not in text
    assert "--expose-token" not in text
    assert '"--password",' not in text
    assert '"--password-stdin"' in text
    assert '"buildx"' in text
    assert '"--load"' in text
    assert "push-by-digest=true" not in text
    assert '"docker", "push", image_reference' in text
    assert "/_tags/" in text
    assert '"get-access-token"' in text
    assert "@sha256:" in text
    assert "private-endpoint-resolved-publicly" in text
    assert "temporary-authority-revocation-unproved" in text
    assert "repository-not-clean" in text

    compute = (INFRASTRUCTURE_ROOT / "modules" / "compute.bicep").read_text(encoding="utf-8")
    assert compute.count("secretRef:") >= 12
    assert "OPENAI_API_KEY" in compute
    assert "OPENCANVAS_OPENAI_API_KEY" not in compute
    assert "external: false" in compute
    assert "keyVaultUrl:" in compute


def test_denial_probes_use_windows_safe_empty_projection() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    publish = IMAGE_PUBLICATION_SCRIPT.read_text(encoding="utf-8").split(
        "def _publish_api_image", 1
    )[1]
    revoke = text.split("def _revoke", 1)[1].split("def _current_resource_ids", 1)[0]

    assert '"[:0]"' not in publish
    assert revoke.count('"[:0]"') == 2
    assert '"length(@)"' not in publish
    assert '"length(@)"' not in revoke


def test_ephemeral_publisher_role_inventory_is_exact_and_default_deny() -> None:
    publisher_object_id = "00000000-0000-0000-0000-000000000071"
    role_id = "00000000-0000-0000-0000-000000000072"
    registry_scope = (
        "/subscriptions/opaque-subscription/resourceGroups/"
        "rg-solarplexus-mobius-77-staging/providers/"
        "Microsoft.ContainerRegistry/registries/acrmobius7711564669"
    )
    expected = {
        "principalId": publisher_object_id.casefold(),
        "roleDefinitionId": (
            "/subscriptions/opaque-subscription/providers/"
            f"Microsoft.Authorization/roleDefinitions/{role_id}"
        ).casefold(),
        "scope": registry_scope.casefold(),
    }

    managed_binding_lifecycle._validate_publisher_role_inventory(
        [],
        publisher_object_id=publisher_object_id,
        registry_scope=registry_scope,
        acr_push_role_id=role_id,
        assignment_required=False,
    )
    managed_binding_lifecycle._validate_publisher_role_inventory(
        [expected],
        publisher_object_id=publisher_object_id,
        registry_scope=registry_scope,
        acr_push_role_id=role_id,
        assignment_required=True,
    )

    inherited_or_persistent = [
        [expected],
        [{**expected, "scope": "/subscriptions/opaque-subscription"}],
        [{**expected, "roleDefinitionId": expected["roleDefinitionId"] + "-nearby"}],
        [{**expected, "principalId": "00000000-0000-0000-0000-000000000073"}],
        [expected, expected],
    ]
    for rows in inherited_or_persistent:
        with pytest.raises(managed_binding_lifecycle.LifecycleError):
            managed_binding_lifecycle._validate_publisher_role_inventory(
                rows,
                publisher_object_id=publisher_object_id,
                registry_scope=registry_scope,
                acr_push_role_id=role_id,
                assignment_required=False,
            )

    missing_nearby_duplicate_or_extra = [
        [],
        [{**expected, "scope": registry_scope + "-nearby"}],
        [{**expected, "roleDefinitionId": expected["roleDefinitionId"] + "-nearby"}],
        [expected, expected],
        [
            expected,
            {
                **expected,
                "roleDefinitionId": expected["roleDefinitionId"] + "-extra",
            },
        ],
    ]
    for rows in missing_nearby_duplicate_or_extra:
        with pytest.raises(
            managed_binding_lifecycle.LifecycleError,
            match="publisher-role-inventory-drift",
        ):
            managed_binding_lifecycle._validate_publisher_role_inventory(
                rows,
                publisher_object_id=publisher_object_id,
                registry_scope=registry_scope,
                acr_push_role_id=role_id,
                assignment_required=True,
            )


@pytest.mark.parametrize(
    "authority",
    [
        "owner",
        "contributor",
        "acr-push",
        "acr-tasks",
        "quick-build",
        "wildcard",
        "group-derived",
        "ancestor-scope",
    ],
)
def test_ephemeral_publisher_rejects_every_inherited_authority(authority: str) -> None:
    publisher_object_id = "00000000-0000-0000-0000-000000000081"
    registry_scope = (
        "/subscriptions/opaque-subscription/resourceGroups/"
        "rg-solarplexus-mobius-77-staging/providers/"
        "Microsoft.ContainerRegistry/registries/acrmobius7711564669"
    )
    row = {
        "principalId": publisher_object_id,
        "roleDefinitionId": (
            "/subscriptions/opaque-subscription/providers/"
            f"Microsoft.Authorization/roleDefinitions/{authority}"
        ),
        "scope": registry_scope,
    }
    if authority == "group-derived":
        row["principalId"] = "00000000-0000-0000-0000-000000000082"
    if authority == "ancestor-scope":
        row["scope"] = "/subscriptions/opaque-subscription"

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="publisher-inherited-authority",
    ):
        managed_binding_lifecycle._validate_publisher_role_inventory(
            [row],
            publisher_object_id=publisher_object_id,
            registry_scope=registry_scope,
            acr_push_role_id="8311e382-0749-4cb8-b61a-304f252e45ec",
            assignment_required=False,
        )


def test_ephemeral_publisher_role_inventory_normalizes_and_rejects_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row: JsonValue = {
        "principalId": "ABCDEF00-0000-0000-0000-000000000001",
        "roleDefinitionId": "/SUBSCRIPTIONS/OPAQUE/ROLE",
        "scope": "/SUBSCRIPTIONS/OPAQUE/SCOPE",
    }
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda *_args, **_kwargs: [row],
    )
    assert managed_binding_lifecycle._publisher_role_rows(
        subscription_id="opaque-subscription",
        publisher_app_id="opaque-application",
    ) == [
        {
            "principalId": "abcdef00-0000-0000-0000-000000000001",
            "roleDefinitionId": "/subscriptions/opaque/role",
            "scope": "/subscriptions/opaque/scope",
        }
    ]

    row = {"principalId": "opaque", "scope": "opaque"}
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="publisher-role-inventory-malformed",
    ):
        managed_binding_lifecycle._publisher_role_rows(
            subscription_id="opaque-subscription",
            publisher_app_id="opaque-application",
        )


def test_ephemeral_publisher_is_same_principal_and_finalizer_deletes_after_denial() -> None:
    publish = inspect.getsource(api_image_publication._publish_api_image)
    prebuilt = publish.index("_load_prebuilt_api_image_record(")
    path_admission = publish.index("verify_private_registry_publication_path(")
    create = publish.index("_create_ephemeral_publisher(")
    initial_denial = publish.index("_prove_initial_publisher_denial(", create)
    assignment = publish.index("_temporary_publisher_role_assignment(", initial_denial)
    access = publish.index("_wait_for_publisher_access(", assignment)
    push = publish.index("_docker_push_prebuilt_image(", assignment)
    revoke = publish.index("_delete_assignment(subscription_id, assignment_id)", push)
    cache_reset = publish.index("_reset_ephemeral_directory(docker_config)", revoke)
    post_revoke_denial = publish.index("_wait_for_publisher_denial(", cache_reset)
    denial_proved = publish.index("denial_proved = True", post_revoke_denial)
    identity_delete = publish.index("_delete_ephemeral_publisher(", denial_proved)
    finalizer = publish.index("finalize_current_publication(", identity_delete)

    assert prebuilt < path_admission < create < initial_denial < assignment < access < push < revoke
    assert revoke < cache_reset < post_revoke_denial < denial_proved < identity_delete < finalizer
    assert "_signed_in_user_object_id" not in publish
    assert '"--assignee-principal-type",\n            "ServicePrincipal"' in inspect.getsource(
        managed_binding_lifecycle._temporary_publisher_role_assignment
    )
    assert publish.count("environment_overrides=publisher_environment") >= 8
    assert '"docker", "pull"' in publish
    assert '"docker", "push"' in publish
    assert '"docker", "manifest", "inspect"' in publish
    assert '"acr",\n                "login"' not in publish
    assert '"acr",\n            "repository"' not in publish
    assert "_docker_login_with_refresh_token(" in publish
    assert "buildx" not in publish
    assert "_docker_push_prebuilt_image(" in publish
    assert publish.count("verify_private_registry_publication_path(") == 4
    first_path_probe = publish.index("verify_private_registry_publication_path(", access)
    second_path_probe = publish.index(
        "verify_private_registry_publication_path(", first_path_probe + 1
    )
    final_path_probe = publish.index(
        "verify_private_registry_publication_path(", second_path_probe + 1
    )
    assert first_path_probe < push < second_path_probe < final_path_probe < revoke
    assert "_remove_source_tag(" not in publish
    assert "_acr_manifest_digest(" in publish
    assert "_verify_cleanup_control(subscription_id, cleanup_at)" in publish
    assert publish.count("_verify_cleanup_control(subscription_id, cleanup_at)") == 2
    assert "--expose-token" not in publish


def test_ephemeral_publisher_identity_has_no_group_or_persistent_role_path() -> None:
    create = inspect.getsource(managed_binding_lifecycle._create_ephemeral_publisher)
    inventory = inspect.getsource(managed_binding_lifecycle._publisher_role_rows)
    deletion = inspect.getsource(managed_binding_lifecycle._delete_ephemeral_publisher)
    partial_deletion = inspect.getsource(
        managed_binding_lifecycle._delete_ephemeral_publisher_by_app_id
    )

    assert '"--skip-assignment"' in create
    assert '"--create-cert"' in create
    assert '"--all"' in inventory
    assert '"--include-groups"' in inventory
    assert '"ad",\n            "sp",\n            "delete"' in deletion
    assert '"ad",\n            "app",\n            "delete"' in deletion
    assert "publisher-identity-deletion-unproved" in deletion
    assert '"ad",\n            "app",\n            "delete"' in partial_deletion
    assert "publisher-partial-identity-inventory-malformed" in partial_deletion


def test_ephemeral_publisher_generates_certificate_only_in_restricted_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher_directory = tmp_path / "publisher"
    publisher_directory.mkdir(mode=0o700)
    management_azure_config = tmp_path / "management-azure-config"
    management_azure_config.mkdir(mode=0o700)
    certificate_path = publisher_directory / "generated-certificate.pem"
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(argv: tuple[str, ...], **kwargs: object) -> JsonValue:
        calls.append((argv, kwargs))
        if argv[1:4] == ("ad", "sp", "create-for-rbac"):
            assert "--create-cert" in argv
            assert "--cert" not in argv
            assert kwargs["working_directory"] == publisher_directory
            assert kwargs["environment_overrides"] == {
                "AZURE_CONFIG_DIR": str(management_azure_config),
                "USERPROFILE": str(publisher_directory),
            }
            certificate_path.write_text("synthetic-certificate", encoding="ascii")
            return {
                "appId": "00000000-0000-0000-0000-000000000091",
                "certificatePath": str(certificate_path),
                "tenant": "00000000-0000-0000-0000-000000000092",
            }
        if argv[1:4] == ("ad", "sp", "show"):
            return {
                "objectId": "00000000-0000-0000-0000-000000000093",
                "servicePrincipalType": "Application",
            }
        if argv[1:4] == ("ad", "sp", "get-member-groups"):
            return []
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_management_azure_config_directory",
        lambda: management_azure_config,
    )
    app_id, object_id, tenant_id, observed_certificate = (
        managed_binding_lifecycle._create_ephemeral_publisher(
            ledger={"ledgerIntegritySha256": "a" * 64},
            publisher_directory=publisher_directory,
        )
    )

    assert app_id.endswith("91")
    assert object_id.endswith("93")
    assert tenant_id.endswith("92")
    assert observed_certificate == certificate_path.resolve()
    assert len(calls) == 2


def test_ephemeral_publisher_principal_retries_bounded_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        nonlocal calls
        if argv[1:4] == ("ad", "sp", "show"):
            calls += 1
            if calls == 1:
                raise managed_binding_lifecycle.AzureCommandError("azure-command-nonzero")
            return {
                "objectId": "00000000-0000-0000-0000-000000000093",
                "servicePrincipalType": "Application",
            }
        if argv[1:4] == ("ad", "sp", "get-member-groups"):
            return []
        raise AssertionError(argv)

    monotonic_values = iter((0.0, 1.0, 2.0))
    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)
    monkeypatch.setattr(
        managed_binding_lifecycle.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(managed_binding_lifecycle.time, "sleep", lambda _value: None)

    assert managed_binding_lifecycle._wait_for_ephemeral_publisher_principal(
        "00000000-0000-0000-0000-000000000091"
    ).endswith("93")
    assert calls == 2


def test_publisher_access_probes_at_propagation_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    def session(**_kwargs: object) -> tuple[bytearray, bytearray | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return bytearray(b"refresh-token-value"), None
        return bytearray(b"refresh-token-value"), bytearray(b"access-token-value")

    monotonic_values = iter((0.0, 599.0))
    monkeypatch.setattr(managed_binding_lifecycle, "_publisher_repository_session", session)
    monkeypatch.setattr(
        managed_binding_lifecycle.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(managed_binding_lifecycle.time, "sleep", sleeps.append)

    refresh_token, access_token = managed_binding_lifecycle._wait_for_publisher_access(
        publisher_app_id="publisher-app",
        tenant_id="publisher-tenant",
        environment={},
    )

    assert calls == 2
    assert sleeps == [1.0]
    assert refresh_token == b"refresh-token-value"
    assert access_token == b"access-token-value"


def test_publisher_oauth_exchange_is_private_and_exact_repository_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = "00000000-0000-0000-0000-000000000101"
    expires = int((NOW + timedelta(hours=1)).timestamp())
    access_jwt = _synthetic_jwt(
        {
            "access": [
                {
                    "actions": ["pull", "push"],
                    "name": "opencanvas-api",
                    "type": "repository",
                }
            ],
            "aud": managed_binding_lifecycle.REGISTRY_HOST,
            "exp": expires,
            "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
            "tenant": tenant_id,
        }
    )
    calls: list[tuple[str, str, bytes]] = []

    def request(
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytearray | None = None,
    ) -> tuple[int, dict[str, str], bytearray]:
        assert headers == {"Content-Type": "application/x-www-form-urlencoded"}
        calls.append((method, path, bytes(body or b"")))
        if path == "/oauth2/exchange":
            return 200, {}, bytearray(json.dumps({"refresh_token": "r" * 64}).encode())
        return (
            200,
            {},
            bytearray(
                json.dumps(
                    {
                        "access_token": access_jwt.decode("ascii"),
                        "expires_in": 3600,
                        "issued_at": "synthetic",
                    }
                ).encode()
            ),
        )

    monkeypatch.setattr(managed_binding_lifecycle, "_private_registry_request", request)
    monkeypatch.setattr(managed_binding_lifecycle, "_utc_now", lambda: NOW)

    entra_token = bytearray(b"e" * 64)
    refresh_token = managed_binding_lifecycle._publisher_refresh_token(
        entra_token=entra_token,
        tenant_id=tenant_id,
        service=managed_binding_lifecycle.REGISTRY_HOST,
    )
    assert refresh_token is not None
    repository_token = managed_binding_lifecycle._publisher_repository_token(
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        service=managed_binding_lifecycle.REGISTRY_HOST,
    )

    assert repository_token is not None
    assert [call[:2] for call in calls] == [
        ("POST", "/oauth2/exchange"),
        ("POST", "/oauth2/token"),
    ]
    assert b"service=acrmobius7711564669.azurecr.io" in calls[0][2]
    assert b"tenant=00000000-0000-0000-0000-000000000101" in calls[0][2]
    assert b"scope=" not in calls[0][2]
    assert b"scope=repository%3Aopencanvas-api%3Apull%2Cpush" in calls[1][2]
    assert b"_catalog" not in b"".join(call[2] for call in calls)
    assert b"/subscriptions/" not in b"".join(call[2] for call in calls)
    entra_token.clear()
    refresh_token.clear()
    repository_token.clear()


def test_publisher_tokens_fail_closed_for_binding_time_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_id = "00000000-0000-0000-0000-000000000111"
    tenant_id = "00000000-0000-0000-0000-000000000112"
    valid_time = {
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
        "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
    }
    monkeypatch.setattr(managed_binding_lifecycle, "_utc_now", lambda: NOW)

    valid_entra = _synthetic_jwt(
        {
            **valid_time,
            "appid": app_id,
            "aud": managed_binding_lifecycle.ACR_TOKEN_RESOURCE,
            "tid": tenant_id,
        }
    )
    managed_binding_lifecycle._validate_entra_token(
        valid_entra, publisher_app_id=app_id, tenant_id=tenant_id
    )

    invalid_entra_claims = (
        {**valid_time, "appid": app_id, "aud": "wrong-audience", "tid": tenant_id},
        {
            **valid_time,
            "appid": app_id,
            "aud": managed_binding_lifecycle.ACR_TOKEN_RESOURCE,
            "tid": "wrong-tenant",
        },
        {
            "appid": app_id,
            "aud": managed_binding_lifecycle.ACR_TOKEN_RESOURCE,
            "exp": int((NOW - timedelta(minutes=1)).timestamp()),
            "nbf": int((NOW - timedelta(hours=1)).timestamp()),
            "tid": tenant_id,
        },
    )
    for claims in invalid_entra_claims:
        with pytest.raises(managed_binding_lifecycle.LifecycleError):
            managed_binding_lifecycle._validate_entra_token(
                _synthetic_jwt(claims),
                publisher_app_id=app_id,
                tenant_id=tenant_id,
            )
    with pytest.raises(managed_binding_lifecycle.LifecycleError):
        managed_binding_lifecycle._validate_entra_token(
            bytearray(b"not-a-jwt"),
            publisher_app_id=app_id,
            tenant_id=tenant_id,
        )

    def acr_token(*, audience: str, name: str, actions: list[str]) -> bytearray:
        return _synthetic_jwt(
            {
                **valid_time,
                "access": [{"actions": actions, "name": name, "type": "repository"}],
                "aud": audience,
                "tenant": tenant_id,
            }
        )

    assert managed_binding_lifecycle._acr_access_is_exact(
        acr_token(
            audience=managed_binding_lifecycle.REGISTRY_HOST,
            name="opencanvas-api",
            actions=["pull", "push"],
        ),
        tenant_id=tenant_id,
    )
    for token in (
        acr_token(
            audience="wrong.azurecr.io",
            name="opencanvas-api",
            actions=["pull", "push"],
        ),
        acr_token(
            audience=managed_binding_lifecycle.REGISTRY_HOST,
            name="wrong-repository",
            actions=["pull", "push"],
        ),
        acr_token(
            audience=managed_binding_lifecycle.REGISTRY_HOST,
            name="opencanvas-api",
            actions=["pull", "push", "delete"],
        ),
    ):
        with pytest.raises(managed_binding_lifecycle.LifecycleError):
            managed_binding_lifecycle._acr_access_is_exact(token, tenant_id=tenant_id)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v2/_catalog"),
        ("GET", "/v2/opencanvas-api/tags/list"),
        ("HEAD", "/v2/wrong/manifests/source-" + "a" * 40),
        ("HEAD", "/v2/opencanvas-api/manifests/wrong-tag"),
        ("DELETE", "/acr/v1/opencanvas-api/_tags/source-" + "a" * 40),
        ("DELETE", "/acr/v1/wrong/_tags/source-" + "a" * 40),
    ],
)
def test_publisher_registry_requests_reject_catalog_and_nearby_targets(
    method: str, path: str
) -> None:
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="publisher-registry-request-scope-invalid",
    ):
        managed_binding_lifecycle._validate_registry_request(method, path)


def test_production_image_build_uses_one_owned_docker_container_builder_and_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_path = tmp_path / "prebuilt-image.json"
    temporary_root = tmp_path / "buildkit-state"
    temporary_root.mkdir()
    image_id = "sha256:" + "b" * 64
    build_input = "c" * 64
    commands: list[tuple[str, ...]] = []
    active_builder: str | None = None

    def inventory() -> list[dict[str, JsonValue]]:
        rows: list[dict[str, JsonValue]] = [
            {
                "Current": True,
                "Driver": "docker",
                "Name": "desktop-linux",
                "Nodes": [
                    {
                        "Name": "desktop-linux",
                        "Platforms": ["linux/amd64"],
                        "Status": "running",
                    }
                ],
            }
        ]
        if active_builder is not None:
            rows.append(
                {
                    "Current": False,
                    "Driver": "docker-container",
                    "Name": active_builder,
                    "Nodes": [
                        {
                            "Name": active_builder + "0",
                            "Platforms": ["linux/amd64"],
                            "Status": "running",
                        }
                    ],
                }
            )
        return rows

    def run(argv: tuple[str, ...], **_kwargs: object) -> str | None:
        nonlocal active_builder
        commands.append(argv)
        if argv[:3] == ("docker", "buildx", "create"):
            active_builder = argv[argv.index("--name") + 1]
            return active_builder
        if argv[:3] == ("docker", "buildx", "rm"):
            active_builder = None
        return None

    monkeypatch.setattr(api_image_publication, "_verify_repository_state", lambda _head: None)
    monkeypatch.setattr(api_image_publication, "_outside_repository", lambda path, _label: path)
    monkeypatch.setattr(api_image_publication, "_remove_stale_api_image_builders", lambda: None)
    monkeypatch.setattr(api_image_publication, "_buildx_inventory", inventory)
    monkeypatch.setattr(api_image_publication, "_run", run)
    monkeypatch.setattr(
        api_image_publication.tempfile, "mkdtemp", lambda **_kwargs: str(temporary_root)
    )
    monkeypatch.setattr(
        api_image_publication,
        "_api_image_build_input_sha256",
        lambda _head: build_input,
    )
    monkeypatch.setattr(
        api_image_publication,
        "_inspect_local_api_image",
        lambda _reference: (image_id, image_id),
    )

    record = api_image_publication._prebuild_api_image(
        repository_head="a" * 40, record_path=record_path
    )

    create = next(command for command in commands if command[:3] == ("docker", "buildx", "create"))
    build = next(command for command in commands if command[:3] == ("docker", "buildx", "build"))
    remove = next(command for command in commands if command[:3] == ("docker", "buildx", "rm"))
    builder_name = create[create.index("--name") + 1]
    assert create[create.index("--driver") + 1] == "docker-container"
    assert build[build.index("--builder") + 1] == builder_name
    assert build[build.index("--target") + 1] == "runner"
    assert build[build.index("--platform") + 1] == "linux/amd64"
    assert "--load" in build
    assert "--push" not in build
    assert not any("cache-to" in argument for argument in build)
    assert remove[-1] == builder_name
    assert active_builder is None
    assert not temporary_root.exists()
    assert record["buildInputSha256"] == build_input
    assert record["imageId"] == image_id
    assert record["configDigest"] == image_id
    assert record_path.is_file()


def test_lifecycle_and_publication_module_state_is_shared_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert (
        api_image_publication._LIFECYCLE_MODULE_IDENTITY
        is managed_binding_lifecycle._LIFECYCLE_MODULE_IDENTITY
    )
    lifecycle_source = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    assert "sys.modules[_CANONICAL_LIFECYCLE_MODULE] = sys.modules[__name__]" in (lifecycle_source)

    monkeypatch.setattr(api_image_publication, "_LIFECYCLE_MODULE_IDENTITY", object())
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="api-image-publication-module-state-mismatch",
    ):
        managed_binding_lifecycle._prebuild_api_image(
            repository_head="a" * 40,
            record_path=tmp_path / "must-not-be-created.json",
        )


def test_prebuilt_image_record_rejects_source_drift_and_image_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    head = TEST_IMAGE_SOURCE_COMMIT
    image_id = "sha256:" + "b" * 64
    build_input = "c" * 64
    unsigned = api_image_publication._prebuilt_record_unsigned(
        repository_head=head,
        build_input_sha256=build_input,
        image_id=image_id,
        config_digest=image_id,
    )
    record: dict[str, JsonValue] = {
        **unsigned,
        "integritySha256": hashlib.sha256(
            managed_binding_lifecycle.PREBUILT_IMAGE_RECORD_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest(),
    }
    path = tmp_path / "record.json"
    path.write_bytes(canonical_bytes(record))
    monkeypatch.setattr(api_image_publication, "_outside_repository", lambda value, _label: value)
    monkeypatch.setattr(
        api_image_publication,
        "_api_image_build_input_sha256",
        lambda _head: "d" * 64,
    )
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="prebuilt-api-image-source-drift",
    ):
        api_image_publication._load_prebuilt_api_image_record(
            path, image_source_commit=head, control_plane_head=head
        )

    monkeypatch.setattr(
        api_image_publication,
        "_api_image_build_input_sha256",
        lambda _head: build_input,
    )
    monkeypatch.setattr(
        api_image_publication,
        "_inspect_local_api_image",
        lambda _reference: ("sha256:" + "e" * 64, "sha256:" + "e" * 64),
    )
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="prebuilt-api-image-identity-mismatch",
    ):
        api_image_publication._load_prebuilt_api_image_record(
            path, image_source_commit=head, control_plane_head=head
        )


def test_mutable_tag_removal_preserves_immutable_manifest() -> None:
    source = inspect.getsource(acr_tag_finalization.finalize_current_publication)
    assert '"DELETE"' in source
    assert "_tags/{source_tag}" in source
    assert "source-tag-remains-after-delete" in source
    assert "immutable-manifest-changed-during-untag" in source
    assert "repository-tag-inventory-changed-outside-target" in source
    assert "_catalog" not in source


def test_ordinary_docker_push_is_exact_isolated_and_returns_only_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_reference = f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api:source-" + "a" * 40
    digest = "sha256:" + "b" * 64
    observed: dict[str, object] = {}
    isolated_environment = {
        "AZURE_CONFIG_DIR": str(tmp_path / "azure"),
        "DOCKER_CONFIG": str(tmp_path / "docker"),
    }

    evidence_path = tmp_path / "docker-push-evidence.json"

    class Process:
        returncode = 0

        def __init__(self, *args: object, **kwargs: object) -> None:
            observed["args"] = args
            observed["kwargs"] = kwargs
            started = json.loads(evidence_path.read_text(encoding="utf-8"))
            assert started["status"] == "STARTED"
            assert started["actualExitCode"] is None

        def communicate(self, *, timeout: int) -> tuple[bytes, bytes]:
            assert timeout == managed_binding_lifecycle.DEPLOYMENT_TIMEOUT_SECONDS
            return (
                f"source-{'a' * 40}: digest: {digest} size: 1234\n".encode(),
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("successful push must not be killed")

    monkeypatch.setattr(
        api_image_publication,
        "_begin_process_attribution",
        lambda *_args, **_kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        api_image_publication,
        "_publisher_environment",
        lambda environment: dict(environment),
    )
    monkeypatch.setattr(
        api_image_publication,
        "_docker_runtime_metadata",
        lambda *_args, **_kwargs: {
            "clientVersion": "29.6.2",
            "context": "desktop-linux",
            "endpointClass": "windows-npipe",
            "endpointSha256": "c" * 64,
            "serverOs": "linux",
            "serverVersion": "29.6.2",
        },
    )
    monkeypatch.setattr(api_image_publication, "_resolved_executable", lambda value: value)
    monkeypatch.setattr(api_image_publication.subprocess, "Popen", Process)

    assert (
        api_image_publication._docker_push_once(
            image_reference,
            environment=isolated_environment,
            evidence_path=evidence_path,
        )
        == digest
    )
    assert observed["args"] == (("docker", "push", image_reference),)
    kwargs = cast(dict[str, object], observed["kwargs"])
    assert kwargs["env"] == isolated_environment
    assert kwargs["stdin"] is managed_binding_lifecycle.subprocess.DEVNULL
    assert kwargs["stdout"] is managed_binding_lifecycle.subprocess.PIPE
    assert kwargs["stderr"] is managed_binding_lifecycle.subprocess.PIPE
    assert kwargs["shell"] is False
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "SUCCEEDED"
    assert evidence["actualExitCode"] == 0
    assert evidence["stdoutComplete"] is True
    assert evidence["stderrComplete"] is True
    assert managed_binding_lifecycle.REGISTRY_HOST not in json.dumps(evidence)


def test_docker_push_runtime_metadata_records_context_versions_and_hashed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"
    responses = iter(
        (
            managed_binding_lifecycle.subprocess.CompletedProcess(
                args=(), returncode=0, stdout=b"desktop-linux\n", stderr=b""
            ),
            managed_binding_lifecycle.subprocess.CompletedProcess(
                args=(), returncode=0, stdout=json.dumps(endpoint).encode(), stderr=b""
            ),
            managed_binding_lifecycle.subprocess.CompletedProcess(
                args=(),
                returncode=0,
                stdout=json.dumps(
                    {
                        "Client": {"Version": "29.6.2"},
                        "Server": {"Version": "29.6.2", "Os": "linux"},
                    }
                ).encode(),
                stderr=b"",
            ),
        )
    )
    observed: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **_kwargs: object) -> object:
        observed.append(command)
        return next(responses)

    monkeypatch.setattr(api_image_publication.subprocess, "run", run)
    result = api_image_publication._docker_runtime_metadata(
        "docker", environment={"DOCKER_CONFIG": "opaque"}
    )
    assert result == {
        "clientVersion": "29.6.2",
        "context": "desktop-linux",
        "endpointClass": "windows-npipe",
        "endpointSha256": hashlib.sha256(endpoint.encode()).hexdigest(),
        "serverOs": "linux",
        "serverVersion": "29.6.2",
    }
    assert observed == [
        ("docker", "context", "show"),
        ("docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"),
        ("docker", "version", "--format", "{{json .}}"),
    ]


def test_docker_push_has_no_wrapper_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_reference = f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api:source-" + "a" * 40
    attempts = 0

    def push_once(_image: str, *, environment: Mapping[str, str], evidence_path: Path) -> str:
        nonlocal attempts
        assert environment == {"DOCKER_CONFIG": "opaque"}
        assert evidence_path == tmp_path / "push.json"
        attempts += 1
        raise managed_binding_lifecycle.LifecycleError("publisher-docker-push-transient")

    monkeypatch.setattr(api_image_publication, "_docker_push_once", push_once)
    with pytest.raises(managed_binding_lifecycle.LifecycleError) as captured:
        api_image_publication._docker_push_prebuilt_image(
            image_reference,
            source_tag="source-" + "a" * 40,
            environment={"DOCKER_CONFIG": "opaque"},
            access_token=bytearray(b"x" * 64),
            evidence_path=tmp_path / "push.json",
        )
    assert str(captured.value) == "publisher-docker-push-transient"
    assert attempts == 1
    assert (
        api_image_publication._docker_push_error_code(
            bytearray(), bytearray(b"only one connection allowed")
        )
        == "publisher-docker-push-failed"
    )


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected_first"),
    [
        (b"", b"denied: repository scope rejected\n", "denied: repository scope rejected"),
        (b"error: transport reset\n", b"", "error: transport reset"),
    ],
)
def test_failed_docker_push_preserves_exact_exit_and_separate_sanitized_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdout: bytes,
    stderr: bytes,
    expected_first: str,
) -> None:
    image_reference = f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api:source-" + "a" * 40
    evidence_path = tmp_path / "docker-push-evidence.json"

    class Process:
        returncode = 23

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def communicate(self, *, timeout: int) -> tuple[bytes, bytes]:
            assert timeout == managed_binding_lifecycle.DEPLOYMENT_TIMEOUT_SECONDS
            return stdout, stderr

        def kill(self) -> None:
            raise AssertionError("non-timeout failure must not be killed")

    monkeypatch.setattr(
        api_image_publication,
        "_begin_process_attribution",
        lambda *_args, **_kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        api_image_publication,
        "_publisher_environment",
        lambda environment: dict(environment),
    )
    monkeypatch.setattr(api_image_publication, "_resolved_executable", lambda value: value)
    monkeypatch.setattr(
        api_image_publication,
        "_docker_runtime_metadata",
        lambda *_args, **_kwargs: {
            "clientVersion": "29.6.2",
            "context": "desktop-linux",
            "endpointClass": "windows-npipe",
            "endpointSha256": "c" * 64,
            "serverOs": "linux",
            "serverVersion": "29.6.2",
        },
    )
    monkeypatch.setattr(api_image_publication.subprocess, "Popen", Process)

    with pytest.raises(managed_binding_lifecycle.LifecycleError):
        api_image_publication._docker_push_once(
            image_reference,
            environment={"DOCKER_CONFIG": "opaque"},
            evidence_path=evidence_path,
        )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "FAILED"
    assert evidence["actualExitCode"] == 23
    assert evidence["stdoutSanitized"] == stdout.decode()
    assert evidence["stderrSanitized"] == stderr.decode()
    assert evidence["firstMaterialError"] == expected_first
    assert evidence["finalMaterialError"] == expected_first


def test_docker_push_evidence_sanitizes_sensitive_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_reference = f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api:source-" + "a" * 40
    evidence_path = tmp_path / "docker-push-evidence.json"
    raw = (
        b"Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345\n"
        b"error at C:\\Users\\private-user\\secret.txt from 10.77.2.4\n"
    )

    class Process:
        returncode = 1

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def communicate(self, *, timeout: int) -> tuple[bytes, bytes]:
            return b"", raw

        def kill(self) -> None:
            raise AssertionError("non-timeout failure must not be killed")

    monkeypatch.setattr(
        api_image_publication,
        "_begin_process_attribution",
        lambda *_args, **_kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        api_image_publication,
        "_publisher_environment",
        lambda environment: dict(environment),
    )
    monkeypatch.setattr(api_image_publication, "_resolved_executable", lambda value: value)
    monkeypatch.setattr(
        api_image_publication,
        "_docker_runtime_metadata",
        lambda *_args, **_kwargs: {
            "clientVersion": "29.6.2",
            "context": "desktop-linux",
            "endpointClass": "windows-npipe",
            "endpointSha256": "c" * 64,
            "serverOs": "linux",
            "serverVersion": "29.6.2",
        },
    )
    monkeypatch.setattr(api_image_publication.subprocess, "Popen", Process)

    with pytest.raises(managed_binding_lifecycle.LifecycleError):
        api_image_publication._docker_push_once(
            image_reference,
            environment={"DOCKER_CONFIG": "opaque"},
            evidence_path=evidence_path,
        )
    encoded = evidence_path.read_text(encoding="utf-8")
    assert "abcdefghijklmnopqrstuvwxyz012345" not in encoded
    assert "private-user" not in encoded
    assert "10.77.2.4" not in encoded
    assert encoded.count("[redacted]") >= 3


def test_docker_push_timeout_kills_exact_process_and_preserves_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_reference = f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api:source-" + "a" * 40
    evidence_path = tmp_path / "docker-push-evidence.json"

    class Process:
        returncode: int | None = None
        killed = False
        calls = 0

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def communicate(self, *, timeout: int | None = None) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                assert timeout == managed_binding_lifecycle.DEPLOYMENT_TIMEOUT_SECONDS
                raise api_image_publication.subprocess.TimeoutExpired("docker push", timeout)
            assert timeout is None
            assert self.killed is True
            return b"partial output\n", b"error: timed out\n"

        def kill(self) -> None:
            self.killed = True
            self.returncode = 137

    monkeypatch.setattr(
        api_image_publication,
        "_begin_process_attribution",
        lambda *_args, **_kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        api_image_publication,
        "_publisher_environment",
        lambda environment: dict(environment),
    )
    monkeypatch.setattr(api_image_publication, "_resolved_executable", lambda value: value)
    monkeypatch.setattr(
        api_image_publication,
        "_docker_runtime_metadata",
        lambda *_args, **_kwargs: {
            "clientVersion": "29.6.2",
            "context": "desktop-linux",
            "endpointClass": "windows-npipe",
            "endpointSha256": "c" * 64,
            "serverOs": "linux",
            "serverVersion": "29.6.2",
        },
    )
    monkeypatch.setattr(api_image_publication.subprocess, "Popen", Process)

    with pytest.raises(managed_binding_lifecycle.LifecycleError) as captured:
        api_image_publication._docker_push_once(
            image_reference,
            environment={"DOCKER_CONFIG": "opaque"},
            evidence_path=evidence_path,
        )
    assert str(captured.value) == "publisher-docker-push-process-timed-out"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "TIMED_OUT"
    assert evidence["actualExitCode"] == 137
    assert evidence["timedOut"] is True
    assert evidence["processKilled"] is True
    assert evidence["azureMutationBegan"] is None
    assert evidence["azureMutationState"] == "UNKNOWN_PENDING_REGISTRY_RECONCILIATION"


def test_publisher_failure_cannot_use_the_finalizer_delete_path() -> None:
    publish = inspect.getsource(api_image_publication._publish_api_image)
    assert "failure-publication-tag-cleanup" not in publish
    assert "_remove_source_tag" not in publish
    assert publish.index("finalize_current_publication(") > publish.index(
        "_delete_ephemeral_publisher("
    )


def test_downstream_receipt_claim_does_not_reopen_completed_publication_path() -> None:
    for operation in (
        "pre-secret-provisioning",
        "private-path-verification",
        "post-secret-provisioning",
    ):
        managed_binding_lifecycle._verify_publication_path_before_claim(
            operation=operation, repository_head="a" * 40
        )
    managed_binding_lifecycle._verify_publication_path_before_claim(
        operation="cleanup", repository_head="a" * 40
    )

    main_source = inspect.getsource(managed_binding_lifecycle.main)
    assert "_verify_publication_path_before_claim(" in main_source


def test_live_publisher_cannot_build_and_fails_closed_on_digest_mismatch() -> None:
    publish = inspect.getsource(api_image_publication._publish_api_image)
    push = inspect.getsource(api_image_publication._docker_push_once)
    assert "buildx" not in publish
    assert "docker build" not in publish
    assert '(docker_executable, "push", image_reference)' in push
    assert "registry-pushed-digest-mismatch" in publish
    assert publish.index("_load_prebuilt_api_image_record(") < publish.index(
        "_create_ephemeral_publisher("
    )
    assert publish.index("finalize_current_publication(") > publish.index(
        "_delete_assignment(subscription_id, assignment_id)"
    )


def test_docker_login_uses_secret_stdin_and_isolated_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    azure_config = tmp_path / "azure"
    docker_config = tmp_path / "docker"
    azure_config.mkdir()
    docker_config.mkdir()
    environment = {
        "AZURE_CONFIG_DIR": str(azure_config),
        "DOCKER_CONFIG": str(docker_config),
    }
    observed: dict[str, object] = {}

    def run(argv: tuple[str, ...], **kwargs: object) -> object:
        observed["argv"] = argv
        observed["payload"] = kwargs["input"]
        observed["payloadCopy"] = bytes(cast(bytearray, kwargs["input"]))
        observed["environment"] = kwargs["env"]
        return managed_binding_lifecycle.subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=b"Login Succeeded", stderr=b""
        )

    monkeypatch.setattr(managed_binding_lifecycle, "_resolved_executable", lambda _name: "docker")
    monkeypatch.setattr(managed_binding_lifecycle.subprocess, "run", run)
    refresh_token = bytearray(b"r" * 64)

    managed_binding_lifecycle._docker_login_with_refresh_token(
        refresh_token, environment=environment
    )

    assert refresh_token == b"r" * 64
    assert observed["payloadCopy"] == b"r" * 64 + b"\n"
    assert observed["payload"] == bytearray()
    assert b"r" * 64 not in " ".join(cast(tuple[str, ...], observed["argv"])).encode()
    assert b"r" * 64 not in json.dumps(observed["environment"], default=str).encode()
    assert cast(tuple[str, ...], observed["argv"])[-1] == "--password-stdin"


def test_entra_token_uses_certificate_session_without_argument_or_environment_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = "00000000-0000-0000-0000-000000000121"
    tenant_id = "00000000-0000-0000-0000-000000000122"
    azure_config = tmp_path / "azure"
    docker_config = tmp_path / "docker"
    azure_config.mkdir()
    docker_config.mkdir()
    environment = {
        "AZURE_CONFIG_DIR": str(azure_config),
        "DOCKER_CONFIG": str(docker_config),
    }
    token = _synthetic_jwt(
        {
            "appid": app_id,
            "aud": managed_binding_lifecycle.ACR_TOKEN_RESOURCE,
            "exp": int((NOW + timedelta(hours=1)).timestamp()),
            "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
            "tid": tenant_id,
        }
    )
    observed: dict[str, object] = {}

    class Launch:
        argv = ("az.exe", "account", "get-access-token")

    def run(argv: tuple[str, ...], **kwargs: object) -> object:
        observed["argv"] = argv
        observed["environment"] = kwargs["env"]
        return managed_binding_lifecycle.subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=bytes(token) + b"\r\n",
            stderr=b"",
        )

    monkeypatch.setattr(
        managed_binding_lifecycle, "_resolve_authorized_process_launch", lambda _argv: Launch()
    )
    monkeypatch.setattr(managed_binding_lifecycle.subprocess, "run", run)
    monkeypatch.setattr(managed_binding_lifecycle, "_utc_now", lambda: NOW)

    observed_token = managed_binding_lifecycle._publisher_entra_token(
        publisher_app_id=app_id,
        tenant_id=tenant_id,
        environment_overrides=environment,
    )

    assert observed_token == token
    assert bytes(token) not in " ".join(cast(tuple[str, ...], observed["argv"])).encode()
    assert bytes(token) not in json.dumps(observed["environment"], default=str).encode()
    assert observed["argv"] == Launch.argv


def test_publisher_oauth_path_never_logs_or_uses_arm_registry_lookup() -> None:
    publish = inspect.getsource(api_image_publication._publish_api_image)
    entra = inspect.getsource(managed_binding_lifecycle._publisher_entra_token)
    oauth = inspect.getsource(managed_binding_lifecycle._publisher_refresh_token)
    oauth += inspect.getsource(managed_binding_lifecycle._publisher_repository_token)
    data_plane = inspect.getsource(managed_binding_lifecycle._private_registry_request)

    assert '"acr"' not in publish
    assert 'repository", "list' not in publish
    assert "_catalog" not in publish + oauth + data_plane
    assert "management.azure.com" not in publish + oauth + data_plane
    assert '"account",\n        "get-access-token"' in entra
    assert '"--resource",\n        ACR_TOKEN_RESOURCE' in entra
    assert "print(" not in entra + oauth + data_plane
    assert "logger" not in entra + oauth + data_plane
    assert "os.environ" not in entra + oauth + data_plane
    assert "--expose-token" not in entra + oauth + data_plane
    assert publish.index("refresh_token.clear()") < publish.index("_docker_push_prebuilt_image(")
    assert publish.count("_reset_ephemeral_directory(docker_config)") >= 3


def test_lifecycle_working_directory_must_be_outside_repository() -> None:
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="lifecycle-working-directory-inside-repository",
    ):
        managed_binding_lifecycle._run(
            ("git", "status"),
            working_directory=managed_binding_lifecycle.REPOSITORY_ROOT,
        )


def test_denial_probe_requires_remote_authorization_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Launch:
        argv = ("az", "acr", "repository", "list")

    returncode = 0
    stderr = b""

    def run(*_args: object, **_kwargs: object) -> object:
        return managed_binding_lifecycle.subprocess.CompletedProcess(
            args=Launch.argv,
            returncode=returncode,
            stdout=b"",
            stderr=stderr,
        )

    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_resolve_authorized_process_launch",
        lambda _argv: Launch(),
    )
    monkeypatch.setattr(managed_binding_lifecycle.subprocess, "run", run)

    probe = ("az", "acr", "repository", "list")
    assert managed_binding_lifecycle._denial_probe(probe) == "allowed"

    returncode = 1
    stderr = b"Forbidden"
    assert managed_binding_lifecycle._denial_probe(probe) == "denied"

    stderr = b"unclassified transport failure"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="denial-probe-result-ambiguous",
    ):
        managed_binding_lifecycle._denial_probe(probe)


def test_image_reconciliation_uses_ledger_bound_immutable_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api@sha256:" + "a" * 64
    ledger: dict[str, JsonValue] = {
        "publishedImage": {
            "repository": "opencanvas-api",
            "publicationState": "pending",
        }
    }
    state: dict[str, JsonValue] = {
        "publishedManifestDigest": "sha256:" + "a" * 64,
        "publisherRevocationProved": True,
        "publicationEvidenceIntegritySha256": "b" * 64,
    }

    result = managed_binding_lifecycle._reconcile_published_api_image(
        ledger=ledger,
        state=state,
    )

    assert result == published


def test_image_reconciliation_rejects_missing_immutable_ledger_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del tmp_path, monkeypatch
    ledger: dict[str, JsonValue] = {"repositoryHead": AUTHORIZATION_SOURCE_HEAD}
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="published-image-ledger-binding-missing",
    ):
        managed_binding_lifecycle._reconcile_published_api_image(
            ledger=ledger,
            state={},
        )


def test_image_reconciliation_has_no_owner_acr_data_plane_path() -> None:
    reconcile = inspect.getsource(managed_binding_lifecycle._reconcile_published_api_image)

    assert "_publish_api_image(" not in reconcile
    assert '"acr"' not in reconcile
    assert "_run(" not in reconcile
    assert "_private_registry_request(" not in reconcile
    assert "_signed_in_user_object_id" not in reconcile


def test_pending_image_ledger_rejects_historical_identity() -> None:
    with pytest.raises(ContractError, match="pending image identity is invalid"):
        managed_binding_contracts.pending_image_identity(
            control_plane_head=TEST_IMAGE_SOURCE_COMMIT,
            value=_pending_image("948e81b5bf34f5c2f5069ee40568beb09cb997d3"),
        )


def test_publication_is_a_required_lifecycle_transition_before_post_secret() -> None:
    overlay = load_operation_overlay()
    lifecycle = cast(list[dict[str, JsonValue]], overlay["lifecycleOperations"])
    ids = [str(item["id"]) for item in lifecycle]
    pre_secret = next(item for item in lifecycle if item["id"] == "pre-secret-provisioning")
    assert pre_secret["authorizationPredicate"] == [
        "all-fifteen-prerequisites-proved",
        "valid-unconsumed-one-run-ledger",
        "approved-cost-ceiling",
    ]
    assert ids.index("pre-secret-provisioning") < ids.index("private-path-verification")
    assert ids.index("private-path-verification") < ids.index("publish-api-image")
    assert ids.index("publish-api-image") < ids.index("post-secret-provisioning")
    definition = cast(
        dict[str, JsonValue],
        cast(dict[str, JsonValue], overlay["methodDefinitions"])["lifecycle-publish-api-image-v1"],
    )
    arguments = cast(list[str], definition["argumentVector"])
    assert "--prebuilt-image-record" in arguments
    assert "publish-api-image" in arguments


def test_publication_stage_persists_digest_and_revocation_before_post_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = _test_lifecycle_ledger()
    ledger["publishedImage"] = {
        "repository": "opencanvas-api",
        "publicationState": "pending",
        "imageBuildInputSha256": "a" * 64,
        "imageSourceCommit": TEST_IMAGE_SOURCE_COMMIT,
        "localImageId": "sha256:" + "b" * 64,
        "imageConfigDigest": "sha256:" + "b" * 64,
        "platform": "linux/amd64",
        "sourceTag": f"source-{TEST_IMAGE_SOURCE_COMMIT}",
        "registryManifestDigest": None,
    }
    state = _test_preservation_state(ledger)
    state["privatePathProved"] = True
    state["resumableCheckpoint"] = "secure-manual-entry"
    state["temporaryKeyVaultAssignmentId"] = (
        "/subscriptions/opaque/providers/Microsoft.Authorization/roleAssignments/opaque"
    )
    state["temporaryKeyVaultAuthorityLedgerSha256"] = "a" * 64
    state["temporaryKeyVaultAuthorityProved"] = True
    state_path = managed_binding_lifecycle._state_path(tmp_path)
    managed_binding_lifecycle._write_state(state_path, state)
    digest = "sha256:" + "c" * 64
    from infra.milestone_7_7 import api_image_publication

    monkeypatch.setattr(
        api_image_publication,
        "_publish_api_image",
        lambda **_kwargs: f"{managed_binding_lifecycle.REGISTRY_HOST}/opencanvas-api@{digest}",
    )

    result = managed_binding_lifecycle._publish_api_image_stage(
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
        prebuilt_image_record=tmp_path / "prebuilt-image.json",
    )

    persisted = managed_binding_lifecycle._read_current_transient_state(state_path, ledger=ledger)
    assert result["status"] == "image-published-and-revoked"
    assert persisted["publishedManifestDigest"] == digest
    assert persisted["publisherRevocationProved"] is True
    assert isinstance(persisted["publicationEvidenceIntegritySha256"], str)


def test_lifecycle_uses_supported_cached_azure_cli_bicep_contract() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    compile_template = text.split("def _compile_template", 1)[1].split("def _lifecycle_tags", 1)[0]

    assert (
        '"az",\n            "bicep",\n            "build",\n            "--file",'
        in compile_template
    )
    assert "str(MAIN_TEMPLATE)," in compile_template
    assert '"--outfile",\n            str(output_path),' in compile_template


def test_lifecycle_deployment_names_preserve_prior_azure_history() -> None:
    first = {"ledgerIntegritySha256": "a" * 64}
    second = {"ledgerIntegritySha256": "b" * 64}

    first_name = managed_binding_lifecycle._deployment_name("cleanup-control", first)
    second_name = managed_binding_lifecycle._deployment_name("cleanup-control", second)

    assert first_name == "mobius77-managed-binding-cleanup-control-aaaaaaaaaaaaaaaa"
    assert second_name == "mobius77-managed-binding-cleanup-control-bbbbbbbbbbbbbbbb"
    assert first_name != second_name
    assert len(managed_binding_lifecycle._deployment_name("cleanup-job-binding", first)) <= 64

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="deployment-history-binding-invalid",
    ):
        managed_binding_lifecycle._deployment_name("unknown-stage", first)
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="deployment-history-binding-invalid",
    ):
        managed_binding_lifecycle._deployment_name(
            "cleanup-control", {"ledgerIntegritySha256": "not-a-sha256"}
        )


def test_lifecycle_cleanup_deadline_matches_azure_minute_precision() -> None:
    observed = datetime(2026, 8, 9, 22, 10, 0, tzinfo=UTC)

    deadline = managed_binding_lifecycle._cleanup_deadline(observed)

    assert deadline == datetime(2026, 8, 11, 3, 45, tzinfo=UTC)
    assert deadline == managed_binding_lifecycle.AUTHORIZED_CLEANUP_AT_UTC
    assert deadline <= observed + timedelta(hours=30)

    with pytest.raises(managed_binding_lifecycle.LifecycleError, match="cleanup-time-invalid"):
        managed_binding_lifecycle._cleanup_deadline(observed.replace(tzinfo=None))
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-deadline-expired-or-reserve-active",
    ):
        managed_binding_lifecycle._cleanup_deadline(datetime(2026, 8, 11, 2, 15, tzinfo=UTC))
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-deadline-outside-authorized-window",
    ):
        managed_binding_lifecycle._cleanup_deadline(datetime(2026, 8, 9, 21, 44, tzinfo=UTC))


def test_lifecycle_binds_split_regions_and_proves_cleanup_before_staging() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    assert 'STAGING_LOCATION: Final = "southcentralus"' in text
    assert 'CLEANUP_LOCATION: Final = "westus"' in text
    assert text.count('"northeurope"') == 3
    bridge_parameters = (LIFECYCLE_SCRIPT.parent / "scanner_bridge_deployment.py").read_text(
        encoding="utf-8"
    )
    assert '"location=southcentralus"' in bridge_parameters
    assert '"redisLocation=australiacentral"' in bridge_parameters
    assert '"cleanupLocation=westus"' in bridge_parameters
    assert '"state": "Ok"' in text
    assert '"runbookType": "PowerShell72"' in text
    assert 'schedule["timeZone"] != "Etc/UTC"' in text
    assert 'stage="cleanup-binding"' in text
    assert '"--assignee-object-id",\n                principal_id,' in text
    assert '"--all",' in text
    assert '"cleanup-role-scope-not-exact"' in text

    pre_secret = text.split("def _pre_secret", 1)[1].split("def _private_tls_endpoint", 1)[0]
    cleanup_deploy = pre_secret.index('stage="cleanup-control"')
    configure = pre_secret.index("_configure_cleanup_runbook(subscription_id)")
    job_binding = pre_secret.index('stage="cleanup-job-binding"')
    verify_control = pre_secret.index("_verify_cleanup_control(")
    cleanup_binding = pre_secret.index('stage="cleanup-binding"')
    verify_role = pre_secret.index("_verify_cleanup_target_role(")
    staging_deploy = pre_secret.index("stage=PRE_SECRET_PRESERVABLE_STAGE")
    assert (
        cleanup_deploy
        < configure
        < job_binding
        < verify_control
        < cleanup_binding
        < verify_role
        < staging_deploy
    )


def _job_schedule_list_response(
    subscription_id: str = "opaque-subscription",
) -> dict[str, JsonValue]:
    job_schedule_id = managed_binding_contracts.cleanup_binding_id_for_subscription(subscription_id)
    return {
        "nextLink": None,
        "value": [
            {
                "id": (
                    f"/subscriptions/{subscription_id}/resourceGroups/"
                    "rg-solarplexus-mobius-77-cleanup-control/providers/"
                    "Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery/"
                    f"jobSchedules/{job_schedule_id}"
                ),
                "jobScheduleId": job_schedule_id,
                "runbook": "Remove-Mobius77Staging",
                "schedule": "schedule-mobius77-cleanup-g4",
                "type": "Microsoft.Automation/automationAccounts/jobSchedules",
            }
        ],
    }


def _job_schedule_get_response(
    subscription_id: str = "opaque-subscription",
) -> dict[str, JsonValue]:
    row = cast(list[dict[str, JsonValue]], _job_schedule_list_response(subscription_id)["value"])[0]
    return {
        **row,
        "parameters": {
            "CleanupAuthorized": "true",
            "TargetResourceGroupName": "rg-solarplexus-mobius-77-staging",
        },
    }


def test_cleanup_binding_generation_two_is_stable_distinct_and_normalized() -> None:
    account = (
        "/subscriptions/synthetic/resourceGroups/rg-solarplexus-mobius-77-cleanup-control/"
        "providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery"
    )
    kwargs = {
        "automation_account_id": account,
        "runbook_resource_id": f"{account}/runbooks/Remove-Mobius77Staging",
        "schedule_resource_id": f"{account}/schedules/schedule-mobius77-cleanup",
        "target_resource_group_id": (
            "/subscriptions/synthetic/resourceGroups/rg-solarplexus-mobius-77-staging"
        ),
        "cleanup_authorized": True,
    }
    first = managed_binding_contracts.deterministic_cleanup_binding_id(generation=2, **kwargs)
    normalized = managed_binding_contracts.deterministic_cleanup_binding_id(
        generation=2,
        **{
            key: value.upper() + "/" if isinstance(value, str) else value
            for key, value in kwargs.items()
        },
    )
    generation_one = managed_binding_contracts.deterministic_cleanup_binding_id(
        generation=1, **kwargs
    )

    assert first == normalized
    assert first != generation_one
    assert first == managed_binding_contracts.deterministic_cleanup_binding_id(
        generation=2, **kwargs
    )
    source = inspect.getsource(managed_binding_contracts.deterministic_cleanup_binding_id)
    assert "uuid4" not in source
    assert "datetime" not in source
    assert managed_binding_contracts.cleanup_binding_id_for_subscription(
        "synthetic"
    ) == managed_binding_contracts.deterministic_cleanup_binding_id(
        generation=4,
        automation_account_id=account,
        runbook_resource_id=f"{account}/runbooks/Remove-Mobius77Staging",
        schedule_resource_id=f"{account}/schedules/schedule-mobius77-cleanup-g4",
        target_resource_group_id=(
            "/subscriptions/synthetic/resourceGroups/"
            "rg-solarplexus-mobius-77-cleanup-control/providers/"
            "Microsoft.Resources/resourceGroups/rg-solarplexus-mobius-77-staging"
        ),
        cleanup_authorized=True,
        binding_epoch_utc=managed_binding_contracts.ACTIVE_CLEANUP_BINDING_EPOCH_UTC,
    )


def test_post_cleanup_reprovision_uses_generation_four_and_tombstones_prior() -> None:
    subscription_id = "9f7f5a53-95a6-469e-9b95-e4072f0fd226"
    contract = load_managed_binding_contract()
    cleanup = cast(dict[str, JsonValue], contract["cleanupExecution"])
    tombstones = cast(list[dict[str, JsonValue]], cleanup["tombstonedBindingIds"])

    assert cleanup["bindingGeneration"] == 4
    assert cleanup["activeBindingId"] == "34b1d170-652b-505a-9cc1-b8177b872ff0"
    assert (
        managed_binding_contracts.cleanup_binding_id_for_subscription(subscription_id)
        == cleanup["activeBindingId"]
    )
    assert tombstones[-1]["bindingId"] == (
        managed_binding_contracts.TOMBSTONED_GENERATION_THREE_CLEANUP_BINDING_ID
    )
    assert tombstones[-1]["recreationStatus"] == "not-attempted"
    assert tombstones[-1]["bindingGeneration"] == 3


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("runbook_resource_id", "DifferentRunbook"),
        ("schedule_resource_id", "different-schedule"),
        ("target_resource_group_id", "rg-other"),
    ],
)
def test_cleanup_binding_generation_two_fails_closed_on_identity_input_drift(
    field: str, replacement: str
) -> None:
    account = (
        "/subscriptions/synthetic/resourceGroups/rg-solarplexus-mobius-77-cleanup-control/"
        "providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery"
    )
    kwargs = {
        "automation_account_id": account,
        "runbook_resource_id": f"{account}/runbooks/Remove-Mobius77Staging",
        "schedule_resource_id": f"{account}/schedules/schedule-mobius77-cleanup",
        "target_resource_group_id": (
            "/subscriptions/synthetic/resourceGroups/rg-solarplexus-mobius-77-staging"
        ),
        "cleanup_authorized": True,
    }
    baseline = managed_binding_contracts.deterministic_cleanup_binding_id(generation=2, **kwargs)
    changed = dict(kwargs)
    changed[field] = f"{str(changed[field]).rsplit('/', 1)[0]}/{replacement}"

    assert (
        managed_binding_contracts.deterministic_cleanup_binding_id(generation=2, **changed)
        != baseline
    )
    authorization_changed = {**kwargs, "cleanup_authorized": False}
    assert (
        managed_binding_contracts.deterministic_cleanup_binding_id(
            generation=2, **authorization_changed
        )
        != baseline
    )


def test_cleanup_binding_generation_one_preserves_legacy_guid_and_contract_tombstone() -> None:
    account = (
        "/subscriptions/synthetic/resourceGroups/rg-solarplexus-mobius-77-cleanup-control/"
        "providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup"
    )
    generation_one = managed_binding_contracts.deterministic_cleanup_binding_id(
        generation=1,
        automation_account_id=account,
        runbook_resource_id=f"{account}/runbooks/Remove-Mobius77Staging",
        schedule_resource_id=f"{account}/schedules/schedule-mobius77-cleanup",
        target_resource_group_id=(
            "/subscriptions/synthetic/resourceGroups/rg-solarplexus-mobius-77-staging"
        ),
        cleanup_authorized=True,
    )
    contract = load_managed_binding_contract()
    cleanup = cast(dict[str, JsonValue], contract["cleanupExecution"])
    tombstone = cast(list[dict[str, JsonValue]], cleanup["tombstonedBindingIds"])[0]

    assert cleanup["bindingGeneration"] == 4
    assert cleanup["corruptedAutomationAccount"] == "aa-mobius77-cleanup"
    assert cleanup["activeBindingId"] != generation_one
    assert tombstone["bindingId"] == managed_binding_contracts.TOMBSTONED_CLEANUP_BINDING_ID
    body = {key: value for key, value in tombstone.items() if key != "evidenceIntegritySha256"}
    assert tombstone[
        "evidenceIntegritySha256"
    ] == managed_binding_contracts.cleanup_binding_tombstone_integrity(body)


@pytest.mark.parametrize("generation", [0, 5, 99])
def test_cleanup_binding_rejects_unapproved_generation(generation: int) -> None:
    with pytest.raises(ContractError, match="cleanup binding generation is not authorized"):
        managed_binding_contracts.cleanup_binding_id_for_subscription(
            "synthetic", generation=generation
        )


def test_cleanup_job_schedule_verification_discovers_then_gets_exact_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    observed: list[tuple[str, ...]] = []

    def exact_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        observed.append(argv)
        if argv[1:4] == ("rest", "--method", "get"):
            endpoint = argv[argv.index("--url") + 1]
            if endpoint.endswith("jobSchedules?api-version=2024-10-23"):
                return _job_schedule_list_response()
            return _job_schedule_get_response()
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", exact_run)

    managed_binding_lifecycle._verify_cleanup_job_schedule(subscription_id)

    assert len(observed) == 2
    assert observed[0][1:4] == ("rest", "--method", "get")
    assert observed[0][observed[0].index("--url") + 1] == (
        "https://management.azure.com/subscriptions/opaque-subscription/"
        "resourceGroups/rg-solarplexus-mobius-77-cleanup-control/providers/"
        "Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery/"
        "jobSchedules?api-version=2024-10-23"
    )
    assert "--subscription" not in observed[0]
    assert observed[1][observed[1].index("--url") + 1] == (
        "https://management.azure.com/subscriptions/opaque-subscription/"
        "resourceGroups/rg-solarplexus-mobius-77-cleanup-control/providers/"
        "Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery/"
        f"jobSchedules/{managed_binding_contracts.cleanup_binding_id_for_subscription(subscription_id)}"
        "?api-version=2024-10-23"
    )
    source = inspect.getsource(managed_binding_lifecycle._verify_cleanup_job_schedule)
    assert "uuid5" not in source
    assert '"resource",\n                    "show"' not in source


@pytest.mark.parametrize(
    "drift",
    [
        "wrong-prefix",
        "malformed-id",
        "wrong-job-id",
        "tombstoned-id",
        "wrong-runbook",
        "wrong-schedule",
        "wrong-target",
        "wrong-parameter",
        "missing-authorization",
        "false-authorization",
        "null-authorization",
        "extra-parameter",
        "wrong-type",
        "next-link",
        "duplicate",
    ],
)
def test_cleanup_job_schedule_verification_fails_closed_on_drift(
    monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    subscription_id = "opaque-subscription"

    def drift_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        if argv[1:4] == ("rest", "--method", "get"):
            endpoint = argv[argv.index("--url") + 1]
            if endpoint.endswith("jobSchedules?api-version=2024-10-23"):
                response = _job_schedule_list_response()
                rows = cast(list[dict[str, JsonValue]], response["value"])
                row = rows[0]
            else:
                row = _job_schedule_get_response()
                response = row
            parameters = cast(dict[str, JsonValue], row.get("parameters", {}))
            if drift == "wrong-prefix":
                row["id"] = str(row["id"]).replace(
                    "rg-solarplexus-mobius-77-cleanup-control", "unexpected-group"
                )
            elif drift == "malformed-id":
                row["id"] = str(row["id"]).rsplit("/", 1)[0] + "/not-a-guid"
            elif drift == "wrong-job-id":
                row["jobScheduleId"] = "00000000-0000-4000-8000-000000000002"
            elif drift == "tombstoned-id":
                row["id"] = (
                    str(row["id"]).rsplit("/", 1)[0] + "/158cac88-5679-5804-9f4d-854520bbb635"
                )
                row["jobScheduleId"] = "158cac88-5679-5804-9f4d-854520bbb635"
            elif drift == "wrong-runbook":
                row["runbook"] = "unexpected-runbook"
            elif drift == "wrong-schedule":
                row["schedule"] = "unexpected-schedule"
            elif drift == "wrong-target":
                parameters["TargetResourceGroupName"] = "unexpected-group"
            elif drift == "wrong-parameter":
                row["parameters"] = {"TargetResourceGroup": "rg-solarplexus-mobius-77-staging"}
            elif drift == "missing-authorization":
                parameters.pop("CleanupAuthorized", None)
            elif drift == "false-authorization":
                parameters["CleanupAuthorized"] = "false"
            elif drift == "null-authorization":
                parameters["CleanupAuthorized"] = None
            elif drift == "extra-parameter":
                parameters["Unexpected"] = "value"
            elif drift == "wrong-type":
                row["type"] = "Microsoft.Automation/automationAccounts/jobs"
            elif drift == "next-link":
                if "nextLink" in response:
                    response["nextLink"] = "https://management.azure.com/next"
            else:
                if "value" in response:
                    cast(list[dict[str, JsonValue]], response["value"]).append(dict(row))
            return response
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", drift_run)

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match=r"cleanup-job-schedule-(?:not-ready|output-malformed)",
    ):
        managed_binding_lifecycle._verify_cleanup_job_schedule(subscription_id)


@pytest.mark.parametrize(
    "malformed",
    [None, [], {"nextLink": None}, {"nextLink": None, "value": [{}]}],
)
def test_cleanup_job_schedule_verification_rejects_malformed_output(
    monkeypatch: pytest.MonkeyPatch, malformed: JsonValue
) -> None:
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda _argv, **_kwargs: malformed,
    )

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-job-schedule-output-malformed",
    ):
        managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")


def test_cleanup_job_schedule_verification_retries_not_found_and_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def eventual_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        nonlocal attempts
        if argv[1:4] == ("rest", "--method", "get"):
            endpoint = argv[argv.index("--url") + 1]
            if not endpoint.endswith("jobSchedules?api-version=2024-10-23"):
                return _job_schedule_get_response()
            attempts += 1
            if attempts == 1:
                raise managed_binding_lifecycle.AzureCommandError("resource-not-found")
            if attempts == 2:
                return {"nextLink": None, "value": []}
            return _job_schedule_list_response()
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", eventual_run)
    monkeypatch.setattr(managed_binding_lifecycle.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(managed_binding_lifecycle.time, "sleep", lambda delay: sleeps.append(delay))

    managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")

    assert attempts == 3
    assert sleeps == [5.0, 5.0]


def test_cleanup_job_schedule_verification_retries_exact_get_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_attempts = 0
    sleeps: list[float] = []

    def eventual_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        nonlocal exact_attempts
        endpoint = argv[argv.index("--url") + 1]
        if endpoint.endswith("jobSchedules?api-version=2024-10-23"):
            return _job_schedule_list_response()
        exact_attempts += 1
        if exact_attempts == 1:
            raise managed_binding_lifecycle.AzureCommandError("resource-not-found")
        return _job_schedule_get_response()

    monkeypatch.setattr(managed_binding_lifecycle, "_run", eventual_run)
    monkeypatch.setattr(managed_binding_lifecycle.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(managed_binding_lifecycle.time, "sleep", lambda delay: sleeps.append(delay))

    managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")

    assert exact_attempts == 2
    assert sleeps == [5.0]


@pytest.mark.parametrize(
    "parameters",
    [
        None,
        {},
        {
            "CleanupAuthorized": "true",
            "TargetResourceGroupName": "unexpected-group",
        },
    ],
)
def test_cleanup_job_schedule_verification_rejects_unproved_exact_parameters(
    monkeypatch: pytest.MonkeyPatch, parameters: JsonValue
) -> None:
    def unproved_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        endpoint = argv[argv.index("--url") + 1]
        if endpoint.endswith("jobSchedules?api-version=2024-10-23"):
            return _job_schedule_list_response()
        response = _job_schedule_get_response()
        response["parameters"] = parameters
        return response

    monkeypatch.setattr(managed_binding_lifecycle, "_run", unproved_run)

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-job-schedule-not-ready",
    ):
        managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")


def test_cleanup_job_schedule_verification_times_out_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((0.0, 121.0))
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda _argv, **_kwargs: {"nextLink": None, "value": []},
    )
    monkeypatch.setattr(managed_binding_lifecycle.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(managed_binding_lifecycle.time, "sleep", lambda _delay: None)

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-job-schedule-propagation-timeout",
    ):
        managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")


def test_cleanup_job_schedule_verification_times_out_exact_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((0.0, 121.0))

    def missing_run(_argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        raise managed_binding_lifecycle.AzureCommandError("notfound")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", missing_run)
    monkeypatch.setattr(managed_binding_lifecycle.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(managed_binding_lifecycle.time, "sleep", lambda _delay: None)

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-job-schedule-propagation-timeout",
    ):
        managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")


def test_cleanup_job_schedule_verification_rejects_nontransient_azure_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_run(_argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        raise managed_binding_lifecycle.AzureCommandError("authorizationfailed")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", denied_run)

    with pytest.raises(
        managed_binding_lifecycle.AzureCommandError,
        match="lifecycle-command-nonzero",
    ) as error:
        managed_binding_lifecycle._verify_cleanup_job_schedule("opaque-subscription")

    assert error.value.sanitized_azure_error_code == "authorizationfailed"


def test_only_cleanup_automation_module_allows_west_us() -> None:
    main = (INFRASTRUCTURE_ROOT / "main.bicep").read_text(encoding="utf-8")
    cleanup = (INFRASTRUCTURE_ROOT / "modules" / "cleanup-supervisor.bicep").read_text(
        encoding="utf-8"
    )
    assert "param location string = 'southcentralus'" in main
    assert "param cleanupLocation string = 'westus'" in main
    assert "param redisLocation string = 'australiacentral'" in main
    assert "cacheLocation: redisLocation" in main
    assert "privateEndpointLocation: location" in main
    assert "var cleanupBindingEnabled" in main
    assert "var cleanupJobScheduleEnabled" in main
    assert "'cleanup-job-binding'" in main
    assert "cleanupControlDeploymentEnabled: true" in main
    assert "cleanupJobScheduleDeploymentEnabled: true" in main
    assert "var workloadEnabled" in main
    assert "module identities './modules/identities.bicep' = if (targetEnabled)" in main
    assert "workloadIdentityDeploymentEnabled: workloadEnabled" in main
    identities = (INFRASTRUCTURE_ROOT / "modules" / "identities.bicep").read_text(encoding="utf-8")
    assert (
        "var workloadIdentityEnabled = enabled && workloadIdentityDeploymentEnabled" in identities
    )
    assert "if (workloadIdentityEnabled)" in identities
    for module_name in (
        "network",
        "observability",
        "registry",
        "keyVault",
        "compute",
        "containerAppsDns",
    ):
        assert re.search(
            rf"module {module_name} '\./modules/[^']+' = if \(workloadEnabled\) \{{",
            main,
        )
    assert main.count("= if (workloadEnabled) {") == 6
    assert "param cleanupLocation string = 'westus'" in cleanup
    assert "if (cleanupControlEnabled)" in cleanup
    assert "if (jobScheduleEnabled)" in cleanup
    assert "parent: existingAutomationAccount" in cleanup
    assert "parent: automationAccount\n  name: 'Remove-Mobius77Staging'" in cleanup
    for path in (INFRASTRUCTURE_ROOT / "modules").glob("*.bicep"):
        if path.name != "cleanup-supervisor.bicep":
            assert "westus" not in path.read_text(encoding="utf-8")


def test_lifecycle_method_definitions_use_repository_module_import() -> None:
    overlay = load_operation_overlay()
    definitions = overlay["methodDefinitions"]

    for operation in overlay["lifecycleOperations"]:
        definition = definitions[operation["methodDefinition"]]
        expected_module = (
            "infra.milestone_7_7.scripts.reconcile_already_pushed_publication"
            if operation["id"] == "reconcile-already-pushed-publication"
            else "infra.milestone_7_7.scripts.managed_binding_lifecycle"
        )
        assert definition["argumentVector"][:3] == ["-B", "-m", expected_module]
        assert (
            "infra/milestone_7_7/scripts/managed_binding_lifecycle.py"
            not in definition["argumentVector"]
        )


def _test_lifecycle_ledger(marker: str = "a") -> dict[str, JsonValue]:
    return {
        "authorizationId": "m7.7-managed-binding-closeout-20260731",
        "ledgerIntegritySha256": marker * 64,
        "managedBindingIntegritySha256": marker * 64,
        "repositoryHead": marker * 40,
    }


def _write_cleanup_authorization(
    directory: Path,
    ledger: Mapping[str, JsonValue],
    *,
    successful: bool = True,
) -> Path:
    issued = managed_binding_lifecycle._utc_now()
    stage_names = (
        "deployment",
        "evidenceCapture",
        "providerValidation",
        "secureKeyEntry",
        "soak90Minutes",
        "temporaryAccessRevocation",
    )
    value: dict[str, JsonValue] = {
        "authorizationEvidenceSha256": "e" * 64,
        "authorizationId": ledger["authorizationId"],
        "authorizationMode": "successful-closeout" if successful else "explicit-user",
        "expiresAtUtc": managed_binding_lifecycle._format_utc(issued + timedelta(minutes=30)),
        "issuedAtUtc": managed_binding_lifecycle._format_utc(issued),
        "lifecycleState": ("READY_FOR_FINAL_CLEANUP" if successful else "PAUSED_PRESERVED"),
        "repositoryHead": ledger["repositoryHead"],
        "requiredStages": {name: successful for name in stage_names},
        "resourceGroups": [
            managed_binding_lifecycle.TARGET_GROUP,
            managed_binding_lifecycle.CLEANUP_GROUP,
            managed_binding_lifecycle.INFRASTRUCTURE_GROUP,
        ],
        "schemaVersion": "mobius.milestone-7.7.cleanup-authorization.v1",
    }
    value["authorizationIntegritySha256"] = hashlib.sha256(
        managed_binding_lifecycle.CLEANUP_AUTHORIZATION_DOMAIN + canonical_bytes(value)
    ).hexdigest()
    path = managed_binding_lifecycle._cleanup_authorization_path(directory)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _test_preservation_state(
    ledger: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "activeStage": "pre-secret",
        "cleanupAtUtc": "2026-08-11T03:45:00Z",
        "disposition": "RUNNING",
        "failedStage": None,
        "lastCompletedStage": "cleanup-role-verification",
        "preSecretDeploymentName": managed_binding_lifecycle._deployment_name("pre-secret", ledger),
        "privatePathProved": False,
        "publicationEvidenceIntegritySha256": None,
        "publishedManifestDigest": None,
        "publisherRevocationProved": False,
        "repositoryHead": ledger["repositoryHead"],
        "resumableCheckpoint": "pre-secret",
        "secretValueAccessed": False,
        "temporaryKeyVaultAssignmentId": None,
        "temporaryKeyVaultAuthorityLedgerSha256": None,
        "temporaryKeyVaultAuthorityProved": False,
        "temporaryRegistryAssignmentId": None,
    }


def _test_preservation_proof() -> dict[str, JsonValue]:
    return {
        "cleanup-backstop-armed": True,
        "cleanup-deadline-active": True,
        "cost-within-ceiling": True,
        "known-state": True,
        "least-privilege-exact": True,
        "no-protected-data-exposure": True,
        "private-boundaries-preserved": True,
        "scope-inventory-exact": True,
        "cleanup-resource-count": 4,
        "infrastructure-resource-count": 1,
        "private-endpoint-count": 2,
        "target-resource-count": 18,
    }


def _verify_container_apps_infrastructure_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    group_name: str = managed_binding_lifecycle.INFRASTRUCTURE_GROUP,
    group_tags: JsonValue = None,
    environment: JsonValue = None,
    resources: JsonValue = None,
    assignments: JsonValue = None,
    changed_inputs: str = "",
    allow_prior_binding_with_changed_inputs: bool = False,
) -> int:
    subscription = SYNTHETIC_SUBSCRIPTION
    expected_tags = _test_recovered_cleanup_tags()
    expected_tags["mobius-expires-at-utc"] = "2026-08-11T03:45:00Z"
    expected_environment_id = (
        f"/subscriptions/{subscription}/resourceGroups/"
        f"{managed_binding_lifecycle.TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging"
    )
    if group_tags is None:
        group_tags = {
            **expected_tags,
            "aca-managed-env-id": expected_environment_id,
        }
    if environment is None:
        environment = {
            "infrastructureResourceGroup": managed_binding_lifecycle.INFRASTRUCTURE_GROUP,
            "internal": True,
            "public": "Disabled",
        }
    group_scope = (
        f"/subscriptions/{subscription}/resourceGroups/"
        f"{managed_binding_lifecycle.INFRASTRUCTURE_GROUP}"
    )
    if resources is None:
        resources = [
            {
                "id": f"{group_scope}/providers/Microsoft.Network/loadBalancers/lb-managed",
                "location": managed_binding_lifecycle.STAGING_LOCATION,
                "type": "Microsoft.Network/loadBalancers",
            }
        ]
    if assignments is None:
        assignments = []

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        if argv[0:3] == ("git", "merge-base", "--is-ancestor"):
            return None
        if argv[1:3] == ("group", "show"):
            return {
                "id": group_scope.replace(
                    managed_binding_lifecycle.INFRASTRUCTURE_GROUP, group_name
                ),
                "location": managed_binding_lifecycle.STAGING_LOCATION,
                "tags": group_tags,
            }
        if argv[1:3] == ("resource", "list"):
            return resources
        if argv[1:4] == ("role", "assignment", "list"):
            return assignments
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    monkeypatch.setattr(managed_binding_lifecycle, "_run_text", lambda _argv: changed_inputs)
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: environment,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_lifecycle_tags",
        lambda **_kwargs: expected_tags,
    )
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (1, 2))
    return managed_binding_lifecycle._verify_container_apps_infrastructure(
        subscription_id=subscription,
        ledger=_test_lifecycle_ledger(),
        cleanup_at=datetime(2026, 8, 3, 11, 0, tzinfo=UTC),
        allow_prior_binding_with_changed_inputs=allow_prior_binding_with_changed_inputs,
    )


def test_exact_container_apps_infrastructure_group_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _verify_container_apps_infrastructure_fixture(monkeypatch) == 1


def test_container_apps_infrastructure_accepts_only_prior_ledger_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_tags = _test_recovered_cleanup_tags()
    prior_tags["mobius-cleanup-binding-sha256"] = "d" * 64
    prior_tags["mobius-expires-at-utc"] = "08/03/2026 11:00:00"
    prior_tags["aca-managed-env-id"] = (
        f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}/resourceGroups/"
        f"{managed_binding_lifecycle.TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging"
    )
    assert _verify_container_apps_infrastructure_fixture(monkeypatch, group_tags=prior_tags) == 1

    prior_tags["mobius-run-id"] = "altered"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-group-drift",
    ):
        _verify_container_apps_infrastructure_fixture(monkeypatch, group_tags=prior_tags)

    prior_tags["mobius-run-id"] = "run-recovered-cleanup-seed"
    expected_environment_id = prior_tags["aca-managed-env-id"]
    prior_tags["aca-managed-env-id"] = f"{expected_environment_id}-nearby"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-group-drift",
    ):
        _verify_container_apps_infrastructure_fixture(monkeypatch, group_tags=prior_tags)

    prior_tags["aca-managed-env-id"] = expected_environment_id
    prior_tags["mobius-expires-at-utc"] = "08/03/2026 12:00:00"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-group-drift",
    ):
        _verify_container_apps_infrastructure_fixture(monkeypatch, group_tags=prior_tags)


def test_container_apps_infrastructure_accepts_ancestor_source_only_without_input_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_tags = _test_recovered_cleanup_tags()
    prior_tags["mobius-source-commit"] = "d" * 40
    prior_tags["mobius-expires-at-utc"] = "08/03/2026 11:00:00"
    prior_tags["aca-managed-env-id"] = (
        f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}/resourceGroups/"
        f"{managed_binding_lifecycle.TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging"
    )

    assert _verify_container_apps_infrastructure_fixture(monkeypatch, group_tags=prior_tags) == 1

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-group-drift",
    ):
        _verify_container_apps_infrastructure_fixture(
            monkeypatch,
            group_tags=prior_tags,
            changed_inputs="infra/milestone_7_7/main.bicep",
        )

    prior_tags["mobius-source-commit"] = "not-a-commit"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-group-drift",
    ):
        _verify_container_apps_infrastructure_fixture(monkeypatch, group_tags=prior_tags)


def test_container_apps_infrastructure_reconciles_only_lower_prior_cost_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_tags = _test_recovered_cleanup_tags()
    prior_tags["mobius-cost-ceiling-usd-cents"] = "1"
    prior_tags["mobius-source-commit"] = "d" * 40
    prior_tags["mobius-expires-at-utc"] = "2026-08-02T07:00:00Z"
    prior_tags["aca-managed-env-id"] = (
        f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}/resourceGroups/"
        f"{managed_binding_lifecycle.TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging"
    )

    assert (
        _verify_container_apps_infrastructure_fixture(
            monkeypatch,
            group_tags=prior_tags,
            changed_inputs="infra/milestone_7_7/main.bicep",
            allow_prior_binding_with_changed_inputs=True,
        )
        == 1
    )

    for invalid_cost in ("999999", "-1", "1.0", "one", "\u0661"):
        prior_tags["mobius-cost-ceiling-usd-cents"] = invalid_cost
        with pytest.raises(
            managed_binding_lifecycle.LifecycleError,
            match="container-apps-infrastructure-group-drift",
        ):
            _verify_container_apps_infrastructure_fixture(
                monkeypatch,
                group_tags=prior_tags,
                changed_inputs="infra/milestone_7_7/main.bicep",
                allow_prior_binding_with_changed_inputs=True,
            )


def _reconcile_container_apps_infrastructure_tags_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate: Callable[[dict[str, str]], None] | None = None,
    update_matches: bool = True,
) -> list[tuple[str, ...]]:
    subscription = SYNTHETIC_SUBSCRIPTION
    group_scope = (
        f"/subscriptions/{subscription}/resourceGroups/"
        f"{managed_binding_lifecycle.INFRASTRUCTURE_GROUP}"
    )
    environment_id = (
        f"/subscriptions/{subscription}/resourceGroups/"
        f"{managed_binding_lifecycle.TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging"
    )
    expected = _test_recovered_cleanup_tags()
    expected["mobius-cleanup-binding-sha256"] = "e" * 64
    expected["mobius-expires-at-utc"] = "2026-08-11T03:45:00Z"
    expected["mobius-manifest-sha256"] = "f" * 64
    expected["mobius-run-id"] = "m7.7-managed-binding-closeout-20260731"
    expected["mobius-source-commit"] = "c" * 40
    observed = {
        **expected,
        "aca-managed-env-id": environment_id,
        "mobius-cleanup-binding-sha256": "a" * 64,
        "mobius-expires-at-utc": "08/01/2026 07:00:00",
        "mobius-manifest-sha256": "b" * 64,
        "mobius-run-id": "m7.7-managed-binding-closeout-20260731",
        "mobius-source-commit": "d" * 40,
    }
    if mutate is not None:
        mutate(observed)
    desired = {**expected, "aca-managed-env-id": environment_id}
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        calls.append(argv)
        if argv[0:3] == ("git", "merge-base", "--is-ancestor"):
            return None
        if argv[1:3] == ("group", "show"):
            return {
                "id": group_scope,
                "location": managed_binding_lifecycle.STAGING_LOCATION,
                "tags": observed,
            }
        if argv[1:3] == ("group", "update"):
            return {
                "id": group_scope,
                "location": managed_binding_lifecycle.STAGING_LOCATION,
                "tags": desired if update_matches else observed,
            }
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    monkeypatch.setattr(managed_binding_lifecycle, "_lifecycle_tags", lambda **_kwargs: expected)
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (1, 2))
    managed_binding_lifecycle._reconcile_container_apps_infrastructure_tags(
        subscription_id=subscription,
        ledger=_test_lifecycle_ledger(),
        cleanup_at=datetime(2026, 8, 3, 11, 0, tzinfo=UTC),
    )
    return calls


def test_container_apps_infrastructure_tags_reconcile_exact_prior_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _reconcile_container_apps_infrastructure_tags_fixture(monkeypatch)
    assert sum(argv[1:3] == ("group", "update") for argv in calls) == 1


@pytest.mark.parametrize(
    "mutate",
    (
        lambda tags: tags.update({"mobius-run-id": "bad"}),
        lambda tags: tags.update({"mobius-source-commit": "not-a-commit"}),
        lambda tags: tags.update({"mobius-expires-at-utc": "08/03/2026 12:00:00"}),
        lambda tags: tags.update({"mobius-public-access": "allowed"}),
        lambda tags: tags.update({"aca-managed-env-id": "nearby"}),
        lambda tags: tags.update({"unexpected": "tag"}),
    ),
)
def test_container_apps_infrastructure_tag_reconciliation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, str]], None],
) -> None:
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-tag-reconciliation-denied",
    ):
        _reconcile_container_apps_infrastructure_tags_fixture(monkeypatch, mutate=mutate)


def test_container_apps_infrastructure_tag_reconciliation_requires_exact_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-tag-reconciliation-unproved",
    ):
        _reconcile_container_apps_infrastructure_tags_fixture(monkeypatch, update_matches=False)


def test_container_apps_private_dns_requires_exact_private_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    domain = "synthetic.southcentralus.azurecontainerapps.io"
    static_ip = "10.77.8.9"
    expected_vnet = (
        f"/subscriptions/{subscription_id}/resourceGroups/"
        f"{managed_binding_lifecycle.TARGET_GROUP}/providers/Microsoft.Network/"
        "virtualNetworks/vnet-mobius77-staging"
    )
    projections: dict[str, JsonValue] = {
        "zone": {"name": domain},
        "link": {"registration": False, "virtualNetwork": expected_vnet},
        "record": {"records": [{"ipv4Address": static_ip}], "ttl": 60},
    }

    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: {"domain": domain, "staticIp": static_ip},
    )

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        if argv[1:5] == ("network", "private-dns", "zone", "show"):
            return projections["zone"]
        if argv[1:6] == ("network", "private-dns", "link", "vnet", "show"):
            return projections["link"]
        if argv[1:6] == ("network", "private-dns", "record-set", "a", "show"):
            return projections["record"]
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    managed_binding_lifecycle._verify_container_apps_private_dns(subscription_id)

    projections["record"] = {"records": [{"ipv4Address": "10.77.8.10"}], "ttl": 60}
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-container-apps-dns-drift",
    ):
        managed_binding_lifecycle._verify_container_apps_private_dns(subscription_id)

    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: {"domain": domain, "staticIp": "203.0.113.10"},
    )
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-container-apps-dns-drift",
    ):
        managed_binding_lifecycle._verify_container_apps_private_dns(subscription_id)


def test_private_revision_ready_requires_healthy_running_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = {
        "latest": "ca-mobius77-api--synthetic",
        "ready": "ca-mobius77-api--synthetic",
        "state": "Succeeded",
    }
    revision: JsonValue = {
        "health": "Healthy",
        "provisioning": "Provisioned",
        "running": "Running",
    }

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        if argv[1:3] == ("resource", "show"):
            return app
        if argv[1:4] == ("containerapp", "revision", "show"):
            return revision
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    managed_binding_lifecycle._container_app_revision_ready(
        "opaque-subscription", "ca-mobius77-api"
    )

    revision = {
        "health": "Unhealthy",
        "provisioning": "Provisioned",
        "running": "ActivationFailed",
    }
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-app-revision-failed",
    ):
        managed_binding_lifecycle._container_app_revision_ready(
            "opaque-subscription", "ca-mobius77-api"
        )


def test_migration_job_starts_once_and_requires_matching_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_name = "caj-mobius77-migration-synthetic"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        calls.append(argv)
        if argv[1:4] == ("containerapp", "job", "start"):
            return {"name": execution_name}
        if argv[1:5] == ("containerapp", "job", "execution", "show"):
            return {"name": execution_name, "status": "Succeeded"}
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    managed_binding_lifecycle._migration_job_ready("opaque-subscription")

    assert sum(call[1:4] == ("containerapp", "job", "start") for call in calls) == 1
    assert sum(call[1:5] == ("containerapp", "job", "execution", "show") for call in calls) == 1


def test_migration_job_fails_closed_on_execution_identity_or_status_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_name = "caj-mobius77-migration-synthetic"
    status: JsonValue = {"name": "unexpected-execution", "status": "Succeeded"}

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        if argv[1:4] == ("containerapp", "job", "start"):
            return {"name": execution_name}
        if argv[1:5] == ("containerapp", "job", "execution", "show"):
            return status
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="migration-job-status-output-malformed",
    ):
        managed_binding_lifecycle._migration_job_ready("opaque-subscription")

    status = {"name": execution_name, "status": "Failed"}
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="migration-job-failed",
    ):
        managed_binding_lifecycle._migration_job_ready("opaque-subscription")


def test_lifecycle_compiler_uses_existing_azure_cli_bicep_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".azure" / "bin").mkdir(parents=True)
    (home / ".azure" / "bin" / "bicep.exe").write_bytes(b"synthetic-cache")
    (home / ".azure" / "cliextensions" / "automation").mkdir(parents=True)
    calls: list[tuple[str, ...]] = []
    output = tmp_path / "main.json"

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> None:
        calls.append(argv)
        output.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(managed_binding_lifecycle.Path, "home", lambda: home)
    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)
    managed_binding_lifecycle._compile_template(output)

    assert calls == [
        (
            "az",
            "bicep",
            "build",
            "--file",
            str(managed_binding_lifecycle.MAIN_TEMPLATE),
            "--outfile",
            str(output),
        )
    ]


def test_lifecycle_compiler_fails_when_azure_cli_bicep_cache_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".azure" / "cliextensions" / "automation").mkdir(parents=True)
    monkeypatch.setattr(managed_binding_lifecycle.Path, "home", lambda: home)
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="azure-cli-bicep-cache-missing",
    ):
        managed_binding_lifecycle._compile_template(tmp_path / "main.json")


def test_dependency_gate_accepts_only_cached_azure_cli_bicep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".azure" / "bin").mkdir(parents=True)
    (home / ".azure" / "bin" / "bicep.exe").write_bytes(b"synthetic-cache")
    (home / ".azure" / "cliextensions" / "automation").mkdir(parents=True)
    monkeypatch.setattr(managed_binding_execution.Path, "home", lambda: home)
    monkeypatch.setattr(
        managed_binding_execution.shutil,
        "which",
        lambda name: f"synthetic-{name}" if name in {"az", "docker", "git"} else None,
    )

    status, code, fields = managed_binding_execution._local_lifecycle_dependencies()
    assert status == "proved"
    assert code == "managed-lifecycle-dependencies-present"
    assert fields["bicep-cli-present"] is True

    (home / ".azure" / "bin" / "bicep.exe").unlink()
    status, code, fields = managed_binding_execution._local_lifecycle_dependencies()
    assert status == "blocked"
    assert code == "managed-lifecycle-dependency-missing"
    assert fields["bicep-cli-present"] is False


@pytest.mark.parametrize(
    "field",
    ["group-name", "group-tags", "environment-binding", "public-resource", "extra-resource"],
)
def test_container_apps_infrastructure_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    kwargs: dict[str, JsonValue] = {}
    if field == "group-name":
        kwargs["group_name"] = "rg-solarplexus-mobius-77-containerapps-infrastructure-nearby"
    elif field == "group-tags":
        kwargs["group_tags"] = {"mobius-run-id": "altered"}
    elif field == "environment-binding":
        kwargs["environment"] = {
            "infrastructureResourceGroup": "rg-solarplexus-mobius-77-other",
            "internal": True,
            "public": "Disabled",
        }
    else:
        group_scope = (
            f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}/resourceGroups/"
            f"{managed_binding_lifecycle.INFRASTRUCTURE_GROUP}"
        )
        rows: list[JsonValue] = [
            {
                "id": f"{group_scope}/providers/Microsoft.Network/loadBalancers/lb-managed",
                "location": managed_binding_lifecycle.STAGING_LOCATION,
                "type": "Microsoft.Network/loadBalancers",
            },
            {
                "id": f"{group_scope}/providers/Microsoft.Network/publicIPAddresses/pip-forbidden",
                "location": managed_binding_lifecycle.STAGING_LOCATION,
                "type": "Microsoft.Network/publicIPAddresses",
            },
        ]
        kwargs["resources"] = rows if field == "extra-resource" else rows[1:]
    with pytest.raises(managed_binding_lifecycle.LifecycleError):
        _verify_container_apps_infrastructure_fixture(monkeypatch, **kwargs)


@pytest.mark.parametrize("field", ["principal", "role", "scope"])
def test_container_apps_infrastructure_role_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    assignment = {
        "principalType": "ServicePrincipal",
        "roleDefinitionId": (
            f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}/providers/"
            "Microsoft.Authorization/roleDefinitions/4d97b98b-1d4f-4787-a291-c67834d212e7"
        ),
        "scope": (
            f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}/resourceGroups/"
            f"{managed_binding_lifecycle.INFRASTRUCTURE_GROUP}"
        ),
    }
    if field == "principal":
        assignment["principalType"] = "User"
    elif field == "role":
        assignment["roleDefinitionId"] = assignment["roleDefinitionId"].replace(
            "4d97b98b-1d4f-4787-a291-c67834d212e7",
            "b24988ac-6180-42a0-ab88-20f7382dd24c",
        )
    else:
        assignment["scope"] = f"/subscriptions/{SYNTHETIC_SUBSCRIPTION}"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="container-apps-infrastructure-role-drift",
    ):
        _verify_container_apps_infrastructure_fixture(monkeypatch, assignments=[assignment])


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_azure_code"),
    [
        (
            managed_binding_lifecycle.AzureCommandError("bad-request"),
            "lifecycle-command-nonzero",
            "bad-request",
        ),
        (
            RuntimeError("private provider response must never be retained"),
            "managed-binding-lifecycle-failed-closed",
            None,
        ),
    ],
)
def test_safe_pre_secret_failures_are_preserved_from_resulting_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected_code: str,
    expected_azure_code: str | None,
) -> None:
    ledger = _test_lifecycle_ledger()
    state_path = managed_binding_lifecycle._state_path(tmp_path)
    managed_binding_lifecycle._write_state(state_path, _test_preservation_state(ledger))
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_utc_now",
        lambda: datetime(2026, 8, 7, 18, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_terminal_pre_secret_deployment",
        lambda **_kwargs: "Failed",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_preservable_pre_secret_state",
        lambda **_kwargs: _test_preservation_proof(),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup",
        lambda *_args: cleanup_calls.append("cleanup") or {},
    )

    result = managed_binding_lifecycle._handle_failure(
        error=error,
        operation="pre-secret-provisioning",
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert result == {
        "cleanup-status": "preserved-safe-pre-secret-state",
        "disposition": "PAUSED_PRESERVED",
        "error": expected_code,
        "provisioning-authorized": False,
        "resumable-checkpoint": "pre-secret",
        "sanitized-azure-error-code": expected_azure_code,
        "secret-value-accessed": False,
        "status": "blocked",
    }
    assert cleanup_calls == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["disposition"] == "PAUSED_PRESERVED"
    assert state["failedStage"] == "pre-secret"
    record_path = managed_binding_lifecycle._disposition_path(tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    integrity = record.pop("dispositionIntegritySha256")
    assert (
        integrity
        == hashlib.sha256(
            managed_binding_lifecycle.DISPOSITION_DOMAIN + canonical_bytes(record)
        ).hexdigest()
    )
    serialized = json.dumps(record, separators=(",", ":"), sort_keys=True)
    assert "/subscriptions/" not in serialized.casefold()
    assert "opaque-subscription" not in serialized
    assert "private provider response" not in serialized
    assert record["preservationProof"]["deployment-terminal-state"] == "Failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("activeStage", "cleanup-control"),
        ("secretValueAccessed", True),
        ("temporaryKeyVaultAssignmentId", "unexpected-assignment"),
        ("cleanupAtUtc", "2026-08-01T02:30:00Z"),
    ],
)
def test_unsafe_pre_secret_state_pauses_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: JsonValue,
) -> None:
    ledger = _test_lifecycle_ledger()
    state = _test_preservation_state(ledger)
    state[field] = value
    managed_binding_lifecycle._write_state(managed_binding_lifecycle._state_path(tmp_path), state)
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_utc_now",
        lambda: datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup",
        lambda *_args: cleanup_calls.append("cleanup") or {},
    )

    result = managed_binding_lifecycle._handle_failure(
        error=RuntimeError("unknown failure"),
        operation="pre-secret-provisioning",
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert result["disposition"] == "PAUSED_PRESERVED"
    assert result["cleanup-status"] == "not-authorized-preserved"
    assert cleanup_calls == []


@pytest.mark.parametrize("terminal_state", ["Canceled", "Running"])
def test_nonterminal_or_canceled_deployment_pauses_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_state: str,
) -> None:
    ledger = _test_lifecycle_ledger()
    managed_binding_lifecycle._write_state(
        managed_binding_lifecycle._state_path(tmp_path),
        _test_preservation_state(ledger),
    )
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_utc_now",
        lambda: datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )
    if terminal_state == "Running":
        monkeypatch.setattr(
            managed_binding_lifecycle,
            "_verify_terminal_pre_secret_deployment",
            lambda **_kwargs: (_ for _ in ()).throw(
                managed_binding_lifecycle.LifecycleError("pre-secret-deployment-not-terminal")
            ),
        )
    else:
        monkeypatch.setattr(
            managed_binding_lifecycle,
            "_verify_terminal_pre_secret_deployment",
            lambda **_kwargs: terminal_state,
        )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup",
        lambda *_args: cleanup_calls.append("cleanup") or {},
    )

    result = managed_binding_lifecycle._handle_failure(
        error=RuntimeError("unknown failure"),
        operation="pre-secret-provisioning",
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert result["disposition"] == "PAUSED_PRESERVED"
    assert cleanup_calls == []


def test_incomplete_preservation_proof_and_interrupt_pause_without_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _test_lifecycle_ledger()
    managed_binding_lifecycle._write_state(
        managed_binding_lifecycle._state_path(tmp_path),
        _test_preservation_state(ledger),
    )
    proof = _test_preservation_proof()
    proof["least-privilege-exact"] = False
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_utc_now",
        lambda: datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_terminal_pre_secret_deployment",
        lambda **_kwargs: "Failed",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_preservable_pre_secret_state",
        lambda **_kwargs: proof,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup",
        lambda *_args: cleanup_calls.append("cleanup") or {},
    )

    first = managed_binding_lifecycle._handle_failure(
        error=RuntimeError("unknown failure"),
        operation="pre-secret-provisioning",
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )
    assert first["disposition"] == "PAUSED_PRESERVED"
    assert cleanup_calls == []

    second_directory = tmp_path / "interrupt"
    second_directory.mkdir()
    managed_binding_lifecycle._write_state(
        managed_binding_lifecycle._state_path(second_directory),
        _test_preservation_state(ledger),
    )
    second = managed_binding_lifecycle._handle_failure(
        error=KeyboardInterrupt(),
        operation="pre-secret-provisioning",
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=second_directory,
    )
    assert second["disposition"] == "PAUSED_PRESERVED"
    assert cleanup_calls == []


def test_fresh_pre_secret_resume_is_idempotent_and_skips_cleanup_recreation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed: list[str] = []
    reconciled: list[str] = []
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (1928, 8508))
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup_deadline",
        lambda _now: managed_binding_lifecycle.AUTHORIZED_CLEANUP_AT_UTC,
    )
    monkeypatch.setattr(managed_binding_lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_compile_template",
        lambda path: path.write_text("{}", encoding="utf-8"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_preservable_pre_secret_state",
        lambda **_kwargs: reconciled.append("proved") or _test_preservation_proof(),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_deploy_stage",
        lambda **kwargs: deployed.append(str(kwargs["stage"])),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_reconcile_container_apps_infrastructure_tags",
        lambda **_kwargs: reconciled.append("tags-reconciled"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle, "_signed_in_user_object_id", lambda: "opaque-user"
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_temporary_role_assignment",
        lambda **_kwargs: "opaque-assignment",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_wait_for_key_vault_metadata_authority",
        lambda _subscription: None,
    )

    for index, marker in enumerate(("a", "b")):
        receipt_directory = tmp_path / str(index)
        receipt_directory.mkdir()
        result = managed_binding_lifecycle._pre_secret(
            ledger=_test_lifecycle_ledger(marker),
            subscription_id="opaque-subscription",
            receipt_directory=receipt_directory,
        )
        assert result["status"] == "ready-for-secure-manual-entry"
        assert result["disposition"] == "COMPLETED"
        state = json.loads(
            managed_binding_lifecycle._state_path(receipt_directory).read_text(encoding="utf-8")
        )
        assert state["resumableCheckpoint"] == "secure-manual-entry"
        assert state["disposition"] == "COMPLETED"

    assert deployed == ["pre-secret", "pre-secret"]
    assert reconciled == [
        "proved",
        "tags-reconciled",
        "proved",
        "proved",
        "tags-reconciled",
        "proved",
    ]


def _test_recovered_cleanup_tags() -> dict[str, JsonValue]:
    return {
        "mobius-cleanup-binding-sha256": "a" * 64,
        "mobius-contract-version": "m7.7-managed-binding-v1",
        "mobius-cost-ceiling-usd-cents": "4254",
        "mobius-data-class": "isolated-synthetic",
        "mobius-environment": "milestone-7.7-staging",
        "mobius-expires-at-utc": "08/02/2026 05:33:00",
        "mobius-manifest-sha256": "b" * 64,
        "mobius-public-access": "denied",
        "mobius-run-id": "run-recovered-cleanup-seed",
        "mobius-source-commit": "c" * 40,
        "mobius-teardown-state": "preservation-only",
    }


def test_exact_cleanup_only_recovery_seed_is_reconciled_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed: list[str] = []
    ordered: list[str] = []
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (1928, 8508))
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup_deadline",
        lambda _now: managed_binding_lifecycle.AUTHORIZED_CLEANUP_AT_UTC,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_group_exists",
        lambda _subscription, group: group == managed_binding_lifecycle.CLEANUP_GROUP,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_recovered_cleanup_seed_state",
        lambda _subscription: ordered.append("seed-proved"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_compile_template",
        lambda path: path.write_text("{}", encoding="utf-8"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_deploy_stage",
        lambda **kwargs: deployed.append(str(kwargs["stage"])),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_reconcile_container_apps_infrastructure_tags",
        lambda **_kwargs: ordered.append("tags-reconciled"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_configure_cleanup_runbook",
        lambda _subscription: ordered.append("runbook"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_control",
        lambda _subscription, _deadline: "00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_target_role",
        lambda *_args: ordered.append("role-proved"),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_preservable_pre_secret_state",
        lambda **_kwargs: _test_preservation_proof(),
    )
    monkeypatch.setattr(
        managed_binding_lifecycle, "_signed_in_user_object_id", lambda: "opaque-user"
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_temporary_role_assignment",
        lambda **_kwargs: "opaque-assignment",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_wait_for_key_vault_metadata_authority",
        lambda _subscription: None,
    )

    result = managed_binding_lifecycle._pre_secret(
        ledger=_test_lifecycle_ledger(),
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert result["status"] == "ready-for-secure-manual-entry"
    assert deployed == [
        "cleanup-control",
        "cleanup-job-binding",
        "cleanup-binding",
        "pre-secret",
    ]
    assert ordered == ["seed-proved", "runbook", "role-proved", "tags-reconciled"]


def test_staging_only_recovery_state_fails_before_any_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (1928, 8508))
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup_deadline",
        lambda _now: managed_binding_lifecycle.AUTHORIZED_CLEANUP_AT_UTC,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_group_exists",
        lambda _subscription, group: group == managed_binding_lifecycle.TARGET_GROUP,
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_deploy_stage",
        lambda **_kwargs: pytest.fail("deployment must remain blocked"),
    )

    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-authorized-scope-incomplete",
    ):
        managed_binding_lifecycle._pre_secret(
            ledger=_test_lifecycle_ledger(),
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
        )


def test_recovered_cleanup_seed_requires_exact_reconcilable_private_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    group_scope = (
        "/subscriptions/opaque-subscription/resourceGroups/rg-solarplexus-mobius-77-cleanup-control"
    )
    account_scope = (
        f"{group_scope}/providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup"
    )
    tags = _test_recovered_cleanup_tags()
    account_teardown_state = "armed"

    def exact_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        if argv[1:3] == ("group", "show"):
            return {
                "id": group_scope,
                "location": "southcentralus",
                "tags": _test_recovered_cleanup_tags(),
            }
        if argv[1:4] == ("automation", "account", "show"):
            account_tags = tags.copy()
            account_tags["mobius-teardown-state"] = account_teardown_state
            return {
                "id": account_scope,
                "identityType": None,
                "linkedWorkspaceId": None,
                "localAuthDisabled": True,
                "location": "westus",
                "principalId": None,
                "publicNetworkAccess": False,
                "state": "Ok",
                "tags": account_tags,
            }
        if argv[1:3] == ("resource", "list"):
            return [
                {
                    "id": account_scope,
                    "location": "westus",
                    "type": "Microsoft.Automation/automationAccounts",
                }
            ]
        if argv[1:4] == ("role", "assignment", "list"):
            return []
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", exact_run)
    monkeypatch.setattr(managed_binding_lifecycle, "_run_text", lambda _argv: "")

    managed_binding_lifecycle._verify_recovered_cleanup_seed_state(subscription_id)

    tags["mobius-public-access"] = "allowed"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="recovered-cleanup-tags-drift",
    ):
        managed_binding_lifecycle._verify_recovered_cleanup_seed_state(subscription_id)

    tags["mobius-public-access"] = "denied"
    account_teardown_state = "unexpected"
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="recovered-cleanup-tags-drift",
    ):
        managed_binding_lifecycle._verify_recovered_cleanup_seed_state(subscription_id)

    exact_scope_role_source = inspect.getsource(managed_binding_lifecycle._exact_scope_role_rows)
    assert '"--scope"' in exact_scope_role_source
    assert '"--all"' not in exact_scope_role_source


def test_recovered_cleanup_seed_rejects_resource_or_role_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    group_scope = (
        "/subscriptions/opaque-subscription/resourceGroups/rg-solarplexus-mobius-77-cleanup-control"
    )
    account_scope = (
        f"{group_scope}/providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup"
    )
    resource_drift = False
    role_drift = False

    def drift_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        nonlocal resource_drift, role_drift
        if argv[1:3] == ("group", "show"):
            return {"id": group_scope, "location": "southcentralus", "tags": None}
        if argv[1:4] == ("automation", "account", "show"):
            return {
                "id": account_scope,
                "identityType": None,
                "linkedWorkspaceId": None,
                "localAuthDisabled": True,
                "location": "westus",
                "principalId": None,
                "publicNetworkAccess": False,
                "state": "Ok",
                "tags": _test_recovered_cleanup_tags(),
            }
        if argv[1:3] == ("resource", "list"):
            rows: list[JsonValue] = [
                {
                    "id": account_scope,
                    "location": "westus",
                    "type": "Microsoft.Automation/automationAccounts",
                }
            ]
            if resource_drift:
                rows.append(
                    {
                        "id": f"{group_scope}/providers/Microsoft.Storage/storageAccounts/drift",
                        "location": "westus",
                        "type": "Microsoft.Storage/storageAccounts",
                    }
                )
            return rows
        if argv[1:4] == ("role", "assignment", "list"):
            if not role_drift:
                return []
            scope_index = argv.index("--scope") + 1
            observed_scope = argv[scope_index]
            return [
                {
                    "principalId": "00000000-0000-0000-0000-000000000001",
                    "roleDefinitionId": "00000000-0000-0000-0000-000000000002",
                    "scope": observed_scope,
                }
            ]
        raise AssertionError(argv)

    monkeypatch.setattr(managed_binding_lifecycle, "_run", drift_run)
    monkeypatch.setattr(managed_binding_lifecycle, "_run_text", lambda _argv: "")

    resource_drift = True
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-resource-inventory-drift",
    ):
        managed_binding_lifecycle._verify_recovered_cleanup_seed_state(subscription_id)

    resource_drift = False
    role_drift = True
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="recovered-cleanup-role-drift",
    ):
        managed_binding_lifecycle._verify_recovered_cleanup_seed_state(subscription_id)


def test_cleanup_inventory_accepts_only_exact_preserved_recovery_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    group_scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{managed_binding_lifecycle.CLEANUP_GROUP}"
    )
    provider = f"{group_scope}/providers/Microsoft.Automation/automationAccounts"
    rows: list[JsonValue] = [
        {
            "id": f"{provider}/{managed_binding_lifecycle.RETIRED_ACCOUNT}",
            "location": managed_binding_lifecycle.CLEANUP_LOCATION,
            "type": "Microsoft.Automation/automationAccounts",
        },
        {
            "id": (
                f"{provider}/{managed_binding_lifecycle.RETIRED_ACCOUNT}/"
                f"runbooks/{managed_binding_lifecycle.RUNBOOK}"
            ),
            "location": managed_binding_lifecycle.CLEANUP_LOCATION,
            "type": "Microsoft.Automation/automationAccounts/runbooks",
        },
        {
            "id": f"{provider}/{managed_binding_lifecycle.AUTOMATION_ACCOUNT}",
            "location": "northeurope",
            "type": "Microsoft.Automation/automationAccounts",
        },
        {
            "id": (
                f"{provider}/{managed_binding_lifecycle.AUTOMATION_ACCOUNT}/"
                f"runbooks/{managed_binding_lifecycle.RUNBOOK}"
            ),
            "location": "northeurope",
            "type": "Microsoft.Automation/automationAccounts/runbooks",
        },
    ]
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda *_args, **_kwargs: rows,
    )

    observed = managed_binding_lifecycle._resource_group_inventory(
        subscription_id=subscription_id,
        group=managed_binding_lifecycle.CLEANUP_GROUP,
    )
    assert observed == frozenset(
        str(row["id"]).casefold().split(f"{group_scope.casefold()}/providers/", maxsplit=1)[1]
        for row in rows
    )

    rows.append(
        {
            "id": (f"{provider}/{managed_binding_lifecycle.RETIRED_ACCOUNT}/runbooks/Unexpected"),
            "location": managed_binding_lifecycle.CLEANUP_LOCATION,
            "type": "Microsoft.Automation/automationAccounts/runbooks",
        }
    )
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-resource-inventory-drift",
    ):
        managed_binding_lifecycle._resource_group_inventory(
            subscription_id=subscription_id,
            group=managed_binding_lifecycle.CLEANUP_GROUP,
        )


def test_target_inventory_accepts_only_exact_managed_binding_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    group_scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{managed_binding_lifecycle.TARGET_GROUP}"
    )
    names = (
        "id-mobius77-worker",
        "id-mobius77-telemetry",
        "id-mobius77-db-admin",
    )

    def inventory_rows(observed_names: tuple[str, ...]) -> list[JsonValue]:
        return [
            {
                "id": (
                    f"{group_scope}/providers/Microsoft.ManagedIdentity/"
                    f"userAssignedIdentities/{name}"
                ),
                "location": "southcentralus",
                "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
            }
            for name in observed_names
        ]

    rows = inventory_rows(names)
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_container_apps_private_dns_projection",
        lambda *_args: ("private.example.invalid", "10.0.0.1"),
    )
    monkeypatch.setattr(managed_binding_lifecycle, "_run", lambda *_args, **_kwargs: rows)

    assert managed_binding_lifecycle._resource_group_inventory(
        subscription_id=subscription_id,
        group=managed_binding_lifecycle.TARGET_GROUP,
    ) == frozenset(f"microsoft.managedidentity/userassignedidentities/{name}" for name in names)

    rows = inventory_rows(("id-mobius77-worker-nearby",))
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-resource-inventory-drift",
    ):
        managed_binding_lifecycle._resource_group_inventory(
            subscription_id=subscription_id,
            group=managed_binding_lifecycle.TARGET_GROUP,
        )


def test_pre_secret_role_inventory_requires_exact_managed_identity_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_id = "opaque-subscription"
    target_scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{managed_binding_lifecycle.TARGET_GROUP}"
    )
    cleanup_scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{managed_binding_lifecycle.CLEANUP_GROUP}"
    )
    key_vault_scope = (
        f"{target_scope}/providers/Microsoft.KeyVault/vaults/{managed_binding_lifecycle.KEY_VAULT}"
    )
    registry_scope = (
        f"{target_scope}/providers/Microsoft.ContainerRegistry/registries/"
        f"{managed_binding_lifecycle.REGISTRY}"
    )
    principal_ids = {
        name: f"00000000-0000-0000-0000-{index:012d}"
        for index, name in enumerate(
            sorted(managed_binding_lifecycle.MANAGED_BINDING_IDENTITY_NAMES), start=1
        )
    }
    contract = managed_binding_lifecycle.load_managed_binding_contract()
    rbac = contract["rbac"]
    assert isinstance(rbac, dict)
    role_prefix = (
        f"/subscriptions/{subscription_id}/providers/microsoft.authorization/roledefinitions/"
    )
    cleanup_principal = "00000000-0000-0000-0000-999999999999"

    expected_by_scope: dict[str, list[dict[str, str]]] = {
        target_scope.casefold(): [
            {
                "principalId": cleanup_principal,
                "roleDefinitionId": (
                    role_prefix + str(rbac["cleanupContributorRoleDefinitionId"])
                ).casefold(),
                "scope": target_scope.casefold(),
            }
        ],
        cleanup_scope.casefold(): [],
        (
            f"{cleanup_scope}/providers/Microsoft.Automation/automationAccounts/"
            f"{managed_binding_lifecycle.AUTOMATION_ACCOUNT}"
        ).casefold(): [],
    }
    for scope, role_id, identity_names in (
        (
            key_vault_scope,
            str(rbac["keyVaultSecretsUserRoleDefinitionId"]),
            ("id-mobius77-api", "id-mobius77-worker", "id-mobius77-telemetry"),
        ),
        (
            registry_scope,
            str(rbac["acrPullRoleDefinitionId"]),
            (
                "id-mobius77-api",
                "id-mobius77-worker",
                "id-mobius77-telemetry",
                "id-mobius77-db-admin",
            ),
        ),
    ):
        expected_by_scope[scope.casefold()] = [
            {
                "principalId": principal_ids[name],
                "roleDefinitionId": (role_prefix + role_id).casefold(),
                "scope": scope.casefold(),
            }
            for name in identity_names
        ]

    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_managed_identity_principal",
        lambda _subscription_id, name: principal_ids[name],
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_exact_scope_role_rows",
        lambda _subscription_id, scope: expected_by_scope[scope.casefold()],
    )
    target_resources = frozenset(
        {
            "microsoft.keyvault/vaults/kv-mobius77-11564669",
            "microsoft.containerregistry/registries/acrmobius7711564669",
            *(
                "microsoft.managedidentity/userassignedidentities/" + name
                for name in managed_binding_lifecycle.MANAGED_BINDING_IDENTITY_NAMES
            ),
        }
    )

    managed_binding_lifecycle._verify_pre_secret_role_inventory(
        subscription_id=subscription_id,
        cleanup_principal_id=cleanup_principal,
        target_resources=target_resources,
    )

    expected_by_scope[key_vault_scope.casefold()] = expected_by_scope[key_vault_scope.casefold()][
        :-1
    ]
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="pre-secret-role-inventory-drift",
    ):
        managed_binding_lifecycle._verify_pre_secret_role_inventory(
            subscription_id=subscription_id,
            cleanup_principal_id=cleanup_principal,
            target_resources=target_resources,
        )


def test_managed_secret_states_use_only_exact_metadata_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: JsonValue = [
        {"enabled": True, "name": "opencanvas-session-secret"},
        {"enabled": True, "name": "openai-api-key"},
    ]
    observed_argv: tuple[str, ...] | None = None

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        nonlocal observed_argv
        observed_argv = argv
        return rows

    monkeypatch.setattr(managed_binding_lifecycle, "_run", fake_run)

    assert managed_binding_lifecycle._managed_secret_states("opaque-subscription") == {
        "openai-api-key": True,
        "opencanvas-session-secret": True,
    }
    assert observed_argv is not None
    assert observed_argv[1:4] == ("keyvault", "secret", "list")
    assert "--query" in observed_argv
    assert "value" not in " ".join(observed_argv).casefold()

    for malformed in (
        [{"enabled": True, "name": "duplicate"}, {"enabled": True, "name": "duplicate"}],
        [{"enabled": "true", "name": "wrong-type"}],
        [{"enabled": True, "name": "extra", "value": "forbidden"}],
        {"enabled": True, "name": "not-a-list"},
    ):
        rows = malformed
        with pytest.raises(
            managed_binding_lifecycle.LifecycleError,
            match="managed-secret-presence-or-state-unproved",
        ):
            managed_binding_lifecycle._managed_secret_states("opaque-subscription")


def test_cleanup_is_idempotent_without_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(managed_binding_lifecycle, "_group_exists", lambda *_args: False)
    monkeypatch.setattr(managed_binding_lifecycle, "_deleted_vault_present", lambda *_args: False)

    ledger = _test_lifecycle_ledger()
    _write_cleanup_authorization(tmp_path, ledger)
    first = managed_binding_lifecycle._cleanup("opaque-subscription", tmp_path, ledger=ledger)
    second = managed_binding_lifecycle._cleanup("opaque-subscription", tmp_path, ledger=ledger)

    assert first == second
    assert first["status"] == "cleanup-completed"
    assert first["temporary-authority-cleanup-path"] == "no-transient-state"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "stale-evidence",
        "wrong-execution",
        "wrong-head",
        "wrong-state",
        "incomplete-stages",
        "altered-integrity",
    ],
)
def test_cleanup_guard_rejects_missing_stale_or_altered_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    ledger = _test_lifecycle_ledger()
    if mutation != "missing":
        path = _write_cleanup_authorization(tmp_path, ledger)
        value = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "stale-evidence":
            value["issuedAtUtc"] = "2020-01-01T00:00:00Z"
            value["expiresAtUtc"] = "2020-01-01T00:30:00Z"
        elif mutation == "wrong-execution":
            value["authorizationId"] = "another-execution"
        elif mutation == "wrong-head":
            value["repositoryHead"] = "b" * 40
        elif mutation == "wrong-state":
            value["lifecycleState"] = "RUNNING"
        elif mutation == "incomplete-stages":
            value["requiredStages"]["soak90Minutes"] = False
        elif mutation == "altered-integrity":
            value["authorizationIntegritySha256"] = "0" * 64
        if mutation != "altered-integrity":
            value["authorizationIntegritySha256"] = hashlib.sha256(
                managed_binding_lifecycle.CLEANUP_AUTHORIZATION_DOMAIN
                + canonical_bytes(
                    {
                        key: item
                        for key, item in value.items()
                        if key != "authorizationIntegritySha256"
                    }
                )
            ).hexdigest()
        path.write_text(json.dumps(value), encoding="utf-8")
    delete_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_group_exists",
        lambda *_args: delete_calls.append("group-check") or False,
    )

    with pytest.raises(managed_binding_lifecycle.LifecycleError):
        managed_binding_lifecycle._cleanup("opaque-subscription", tmp_path, ledger=ledger)

    assert delete_calls == []


@pytest.mark.parametrize(
    ("offset_seconds", "expected"),
    [
        (-1, False),
        (0, True),
        (1, True),
        (300, True),
        (900, True),
        (1800, True),
        (1801, False),
    ],
)
def test_cleanup_launch_window_boundaries(offset_seconds: int, expected: bool) -> None:
    contract = load_managed_binding_contract()
    cleanup = cast(dict[str, JsonValue], contract["cleanupExecution"])
    scheduled = datetime.strptime(cast(str, cleanup["deadlineUtc"]), "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    execution_started = scheduled + timedelta(seconds=offset_seconds)
    latest = scheduled + timedelta(seconds=cast(int, cleanup["launchGraceSeconds"]))

    assert (scheduled <= execution_started <= latest) is expected


def test_timer_runbook_is_bounded_guarded_and_deletion_capable() -> None:
    text = managed_binding_lifecycle.CLEANUP_RUNBOOK.read_text(encoding="utf-8")

    assert "[bool] $CleanupAuthorized" in text
    assert text.count("$ExecutionStartedAtUtc = [DateTimeOffset]::UtcNow") == 1
    assert "$CleanupLaunchGrace = [TimeSpan]::FromMinutes(30)" in text
    assert "$LatestCleanupLaunchAtUtc = $ScheduledCleanupAtUtc.Add(" in text
    assert "$ExecutionStartedAtUtc -lt $ScheduledCleanupAtUtc" in text
    assert "$ExecutionStartedAtUtc -gt $LatestCleanupLaunchAtUtc" in text
    assert 'Stop-Cleanup "outside-launch-window"' in text
    assert "AuthorizedCleanupDeadlineUtc" not in text
    assert "if ($CleanupAuthorized -ne $true)" in text
    assert "[Parameter(Mandatory = $true)]" in text
    assert 'Stop-Cleanup "target-missing"' in text
    assert "$TargetResourceGroupName -cne $ExactTargetResourceGroup" in text
    assert '"rg-solarplexus-mobius-77-staging"' in text
    assert '"rg-solarplexus-mobius-73-staging"' in text
    assert '"rg-solarplexus-mobius-77-cleanup-control"' in text
    assert '"rg-solarplexus-mobius-77-containerapps-infrastructure"' in text
    assert "Get-AzRoleAssignment" not in text
    assert "Invoke-AzRestMethod" in text
    assert "Microsoft.Authorization/roleAssignments" in text
    assert "api-version=2022-04-01" in text
    assert "`$filter=atScope()" in text
    assert "$scope.ToLowerInvariant() -ceq $targetScope.ToLowerInvariant()" in text
    assert "$ExpectedCleanupPrincipalFingerprint" in text
    assert "$CleanupPrincipalFingerprintDomain" in text
    assert "if ($assignments.Count -ne 1)" in text
    assert "Connect-AzAccount -Identity" in text
    assert "Remove-AzResourceGroup" in text
    assert "-AsJob" in text
    assert "Wait-Job -Job $deleteJob -Timeout 2700" in text
    assert 'deletionResult = "ALREADY_ABSENT"' in text
    assert 'deletionResult = "DELETED"' in text
    assert "Remove-AzKeyVault" not in text
    assert "Remove-AzRoleAssignment" not in text

    launch_guard = text.index("$ExecutionStartedAtUtc -lt $ScheduledCleanupAtUtc")
    identity = text.index("Connect-AzAccount -Identity")
    role_scope = text.index("Invoke-AzRestMethod")
    already_absent = text.index('deletionResult = "ALREADY_ABSENT"')
    deletion = text.index("Remove-AzResourceGroup")
    assert launch_guard < identity < role_scope < already_absent < deletion
    assert "$LatestCleanupLaunchAtUtc" not in text[deletion:]
    assert 'Stop-Cleanup "deletion-timeout"' in text
    assert "finally" in text
    assert "Remove-Job -Job $deleteJob -Force" in text
    assert "Write-Host" not in text
    assert "Write-Verbose" not in text
    assert "*mobius77*" not in text
    assert "Get-AzKeyVaultSecret" not in text


def test_timer_runbook_fingerprints_the_live_replacement_cleanup_identity() -> None:
    text = managed_binding_lifecycle.CLEANUP_RUNBOOK.read_text(encoding="utf-8")
    replacement_principal = "a47789c6-b8eb-40a1-898a-517a52d60a86"
    corrupted_principal = "be0e6b8d-f742-4c8f-8df1-9f302559a6c8"
    domain = b"mobius.azure.cleanup-principal.v1\0"
    replacement_fingerprint = hashlib.sha256(
        domain + replacement_principal.encode("ascii")
    ).hexdigest()
    corrupted_fingerprint = hashlib.sha256(domain + corrupted_principal.encode("ascii")).hexdigest()
    cleanup = cast(dict[str, JsonValue], load_managed_binding_contract()["cleanupExecution"])

    assert replacement_fingerprint == (
        "7bae422a2ef6a418379af13fc19f53a195ccc80be0504c531391e6e46f048be3"
    )
    assert cleanup["cleanupPrincipalFingerprintSha256"] == replacement_fingerprint
    assert f'$ExpectedCleanupPrincipalFingerprint = "{replacement_fingerprint}"' in text
    assert corrupted_fingerprint not in text


@pytest.mark.parametrize(
    "field",
    [
        "authorizationParameter",
        "authorizationValue",
        "targetParameter",
        "targetResourceGroup",
        "deadlineUtc",
        "launchGraceSeconds",
        "cleanupPrincipalFingerprintSha256",
    ],
)
def test_cleanup_execution_required_fields_fail_closed_when_missing(
    field: str,
) -> None:
    contract = deepcopy(load_managed_binding_contract())
    cleanup = cast(dict[str, JsonValue], contract["cleanupExecution"])
    del cleanup[field]

    with pytest.raises(ContractError, match=r"cleanup execution|schema|required"):
        validate_managed_binding_contract(contract)


def test_cleanup_publication_and_evidence_are_content_bound() -> None:
    configure = inspect.getsource(managed_binding_lifecycle._configure_cleanup_runbook)
    verify = inspect.getsource(managed_binding_lifecycle._verify_cleanup_control)
    contract = load_managed_binding_contract()

    assert '"rest"' in configure
    assert '"put"' in configure
    assert '"post"' in configure
    assert "/draft/content" in configure
    assert "/publish" in configure
    assert "replace-content" not in configure
    assert "/content" in verify
    assert "cleanup_runbook_sha256(published_content)" in verify
    assert contract["cleanupExecution"]["publishedContentSha256"] == (
        cleanup_runbook_sha256(
            managed_binding_lifecycle.CLEANUP_RUNBOOK.read_text(encoding="utf-8")
        )
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorizationValue", False),
        ("targetResourceGroup", "rg-solarplexus-mobius-77-cleanup-control"),
        ("deadlineUtc", "2026-08-04T00:31:00Z"),
        ("deadlineUtc", "2026-08-03T19:30:00-05:00"),
        ("launchGraceSeconds", 0),
        ("launchGraceSeconds", 1801),
        ("deletionWaitSeconds", 0),
        ("cleanupPrincipalFingerprintSha256", "0" * 64),
        ("publishedContentSha256", "0" * 64),
    ],
)
def test_cleanup_execution_contract_tampering_fails_closed(field: str, value: JsonValue) -> None:
    contract = deepcopy(load_managed_binding_contract())
    cast(dict[str, JsonValue], contract["cleanupExecution"])[field] = value

    with pytest.raises(ContractError, match=r"cleanup execution|closed contract|schema"):
        validate_managed_binding_contract(contract)


@pytest.mark.parametrize(
    "operation",
    [
        "private-path-verification",
        "post-secret-provisioning",
        "temporary-authority-revocation",
        "cleanup",
        "zero-residue-verification",
    ],
)
@pytest.mark.parametrize(
    "error",
    [
        managed_binding_lifecycle.AzureCommandError("timeout"),
        TimeoutError("timeout"),
        RuntimeError("unknown provider failure"),
        KeyboardInterrupt(),
    ],
)
def test_every_non_pre_secret_failure_pauses_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error: BaseException,
) -> None:
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup",
        lambda *_args, **_kwargs: cleanup_calls.append("cleanup") or {},
    )

    result = managed_binding_lifecycle._handle_failure(
        error=error,
        operation=operation,
        ledger=_test_lifecycle_ledger(),
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert result["disposition"] == "PAUSED_PRESERVED"
    assert result["cleanup-status"] == "not-authorized-preserved"
    assert cleanup_calls == []


@pytest.mark.parametrize(
    "error_code",
    sorted(managed_binding_lifecycle.SECURITY_CONTAINMENT_ERROR_CODES),
)
def test_verified_security_failures_contain_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
) -> None:
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_cleanup",
        lambda *_args, **_kwargs: cleanup_calls.append("cleanup") or {},
    )

    result = managed_binding_lifecycle._handle_failure(
        error=managed_binding_lifecycle.LifecycleError(error_code),
        operation="post-secret-provisioning",
        ledger=_test_lifecycle_ledger(),
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert result["disposition"] == "CONTAINED_PRESERVED"
    assert cleanup_calls == []


def test_no_failure_timer_or_runner_exit_path_can_bypass_cleanup_guard() -> None:
    lifecycle_text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    handler = lifecycle_text.split("def _handle_failure", 1)[1].split("def _parser", 1)[0]
    cleanup = lifecycle_text.split("def _cleanup(", 1)[1].split("def _zero_residue", 1)[0]
    deploy = lifecycle_text.split("def _deploy_stage", 1)[1].split(
        "def _signed_in_user_object_id", 1
    )[0]

    assert "_cleanup(" not in handler
    assert "_validate_cleanup_authorization(" in cleanup
    assert '"--mode"' not in deploy
    assert "deployment stack" not in lifecycle_text.casefold()


def test_main_delegates_terminal_handling_and_finally_paths_remain_strict() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    main = text.split("def main()", 1)[1]
    failure_boundary = main.split("except (Exception, KeyboardInterrupt) as exc:", 1)[1]
    publish = IMAGE_PUBLICATION_SCRIPT.read_text(encoding="utf-8").split(
        "def _publish_api_image", 1
    )[1]

    assert "except (Exception, KeyboardInterrupt) as exc:" in main
    assert "_handle_failure(" in main
    assert "_cleanup(subscription_id, receipt_directory)" not in failure_boundary
    assert "finally:" in publish
    assert "_delete_assignment(subscription_id, assignment_id)" in publish
    assert "_wait_for_denial(" in publish
