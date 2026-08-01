from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from performance.milestone_7_7.framework import ContractError, JsonValue, canonical_bytes
from preflight.milestone_7_7 import framework as topology_framework
from preflight.milestone_7_7 import managed_binding_execution
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
SYNTHETIC_SUBSCRIPTION = "synthetic-managed-binding-subscription"
SYNTHETIC_TENANT = "synthetic-managed-binding-tenant"
NOW = datetime(2026, 7, 31, 18, 0, tzinfo=UTC)


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

    assert contract["resourceGroups"] == {
        "cleanupControl": "rg-solarplexus-mobius-77-cleanup-control",
        "target": "rg-solarplexus-mobius-77-staging",
    }
    assert contract["location"] == "southcentralus"
    assert contract["cleanupLocation"] == "westus"
    assert contract["resources"]["keyVault"] == "kv-mobius77-11564669"
    assert contract["network"]["vnetCidr"] == "10.77.0.0/20"
    assert contract["network"]["privateEndpointsCidr"] == "10.77.2.0/24"
    assert contract["network"]["publicApplicationIngress"] is False
    assert contract["network"]["publicKeyVaultAccess"] is False
    assert contract["fixedSkus"]["vpnGateway"] == "VpnGw1AZ"
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


def test_one_run_ledger_expires_and_receipts_reject_replay(tmp_path: Path) -> None:
    head = "a" * 40
    ledger = build_authorization_ledger(
        issued_at_utc=NOW,
        repository_head=head,
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
    assert result["lifecycleOperationCount"] == 6
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
                    "West US" if namespace == "Microsoft.Automation" else "South Central US"
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


def test_automation_fallback_rejects_every_other_child_type(
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
                repository_head=AUTHORIZATION_SOURCE_HEAD,
            )
        )
    )
    adapter = ManagedBindingFakeAdapter()
    result = execute_package_one(
        ledger_path=ledger_path,
        repository_head=AUTHORIZATION_SOURCE_HEAD,
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
    assert all(
        call == EXPECTED_ACCOUNT_COMMAND or call[1:3] == ("provider", "show")
        for call in adapter.calls
    )


def test_lifecycle_is_closed_private_digest_bound_and_secret_value_blind() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    assert "--runtime-config" not in text
    assert "OPENCANVAS_OPENAI_API_KEY" not in text
    assert "--expose-token" not in text
    assert "--password" not in text
    assert 'docker",\n                        "buildx' in text
    assert 'repository",\n                        "untag' in text
    assert "@sha256:" in text
    assert "private-endpoint-resolved-publicly" in text
    assert "temporary-authority-revocation-unproved" in text
    assert "repository-not-clean" in text

    compute = (INFRASTRUCTURE_ROOT / "modules" / "compute.bicep").read_text(encoding="utf-8")
    assert compute.count("secretRef:") == 3
    assert "OPENAI_API_KEY" in compute
    assert "OPENCANVAS_OPENAI_API_KEY" not in compute
    assert "external: false" in compute
    assert "keyVaultUrl:" in compute


def test_lifecycle_uses_supported_bicep_positional_input_contract() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    compile_template = text.split("def _compile_template", 1)[1].split("def _lifecycle_tags", 1)[0]

    assert '"bicep",\n            "build",\n            str(MAIN_TEMPLATE),' in compile_template
    assert '"--file",' not in compile_template
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
    observed = datetime(2026, 8, 1, 3, 5, 33, 987654, tzinfo=UTC)

    deadline = managed_binding_lifecycle._cleanup_deadline(observed)

    assert deadline == datetime(2026, 8, 2, 7, 0, tzinfo=UTC)
    assert deadline == managed_binding_lifecycle.AUTHORIZED_CLEANUP_AT_UTC
    assert deadline <= observed + timedelta(hours=30)

    with pytest.raises(managed_binding_lifecycle.LifecycleError, match="cleanup-time-invalid"):
        managed_binding_lifecycle._cleanup_deadline(observed.replace(tzinfo=None))
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-deadline-expired-or-reserve-active",
    ):
        managed_binding_lifecycle._cleanup_deadline(datetime(2026, 8, 2, 5, 30, tzinfo=UTC))
    with pytest.raises(
        managed_binding_lifecycle.LifecycleError,
        match="cleanup-deadline-outside-authorized-window",
    ):
        managed_binding_lifecycle._cleanup_deadline(datetime(2026, 7, 31, 0, 59, tzinfo=UTC))


def test_lifecycle_binds_split_regions_and_proves_cleanup_before_staging() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    assert 'STAGING_LOCATION: Final = "southcentralus"' in text
    assert 'CLEANUP_LOCATION: Final = "westus"' in text
    assert 'f"location={STAGING_LOCATION}"' in text
    assert 'f"cleanupLocation={CLEANUP_LOCATION}"' in text
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


def test_only_cleanup_automation_module_allows_west_us() -> None:
    main = (INFRASTRUCTURE_ROOT / "main.bicep").read_text(encoding="utf-8")
    cleanup = (INFRASTRUCTURE_ROOT / "modules" / "cleanup-supervisor.bicep").read_text(
        encoding="utf-8"
    )
    assert "param location string = 'southcentralus'" in main
    assert "param cleanupLocation string = 'westus'" in main
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
    for module_name in ("network", "observability", "registry", "keyVault", "compute"):
        assert re.search(
            rf"module {module_name} '\./modules/[^']+' = if \(workloadEnabled\) \{{",
            main,
        )
    assert main.count("= if (workloadEnabled) {") == 5
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
        assert definition["argumentVector"][:3] == [
            "-B",
            "-m",
            "infra.milestone_7_7.scripts.managed_binding_lifecycle",
        ]
        assert (
            "infra/milestone_7_7/scripts/managed_binding_lifecycle.py"
            not in definition["argumentVector"]
        )


def _test_lifecycle_ledger(marker: str = "a") -> dict[str, JsonValue]:
    return {
        "ledgerIntegritySha256": marker * 64,
        "repositoryHead": marker * 40,
    }


def _test_preservation_state(
    ledger: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return {
        "activeStage": "pre-secret",
        "cleanupAtUtc": "2026-08-02T07:00:00Z",
        "disposition": "RUNNING",
        "failedStage": None,
        "lastCompletedStage": "cleanup-role-verification",
        "preSecretDeploymentName": managed_binding_lifecycle._deployment_name("pre-secret", ledger),
        "repositoryHead": ledger["repositoryHead"],
        "resumableCheckpoint": "pre-secret",
        "secretValueAccessed": False,
        "temporaryKeyVaultAssignmentId": None,
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
        "private-endpoint-count": 2,
        "target-resource-count": 18,
    }


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
        "disposition": "BLOCKED_PRESERVED",
        "error": expected_code,
        "provisioning-authorized": False,
        "resumable-checkpoint": "pre-secret",
        "sanitized-azure-error-code": expected_azure_code,
        "secret-value-accessed": False,
        "status": "blocked",
    }
    assert cleanup_calls == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["disposition"] == "BLOCKED_PRESERVED"
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
def test_unsafe_pre_secret_state_requires_cleanup(
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

    assert result["disposition"] == "CLEANUP_REQUIRED"
    assert result["cleanup-status"] == "completed"
    assert cleanup_calls == ["cleanup"]


@pytest.mark.parametrize("terminal_state", ["Canceled", "Running"])
def test_nonterminal_or_canceled_deployment_requires_cleanup(
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

    assert result["disposition"] == "CLEANUP_REQUIRED"
    assert cleanup_calls == ["cleanup"]


def test_incomplete_preservation_proof_and_interrupt_require_cleanup(
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
    assert first["disposition"] == "CLEANUP_REQUIRED"
    assert cleanup_calls == ["cleanup"]

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
    assert second["disposition"] == "CLEANUP_REQUIRED"
    assert cleanup_calls == ["cleanup", "cleanup"]


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
        managed_binding_lifecycle, "_signed_in_user_object_id", lambda: "opaque-user"
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_temporary_role_assignment",
        lambda **_kwargs: "opaque-assignment",
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
    assert reconciled == ["proved", "proved", "proved", "proved"]


def test_cleanup_is_idempotent_without_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(managed_binding_lifecycle, "_group_exists", lambda *_args: False)
    monkeypatch.setattr(managed_binding_lifecycle, "_deleted_vault_present", lambda *_args: False)

    first = managed_binding_lifecycle._cleanup("opaque-subscription", tmp_path)
    second = managed_binding_lifecycle._cleanup("opaque-subscription", tmp_path)

    assert first == second
    assert first["status"] == "cleanup-completed"
    assert first["temporary-authority-cleanup-path"] == "no-transient-state"


def test_main_delegates_terminal_handling_and_finally_paths_remain_strict() -> None:
    text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    main = text.split("def main()", 1)[1]
    failure_boundary = main.split("except (Exception, KeyboardInterrupt) as exc:", 1)[1]
    publish = text.split("def _publish_api_image", 1)[1].split("def _private_revision_ready", 1)[0]

    assert "except (Exception, KeyboardInterrupt) as exc:" in main
    assert "_handle_failure(" in main
    assert "_cleanup(subscription_id, receipt_directory)" not in failure_boundary
    assert "finally:" in publish
    assert "_delete_assignment(subscription_id, assignment_id)" in publish
    assert "_wait_for_denial(" in publish
