from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
    assert contract["resources"]["keyVault"] == "kv-mobius77-11564669"
    assert contract["network"]["vnetCidr"] == "10.77.0.0/20"
    assert contract["network"]["privateEndpointsCidr"] == "10.77.2.0/24"
    assert contract["network"]["publicApplicationIngress"] is False
    assert contract["network"]["publicKeyVaultAccess"] is False
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
                "locations": ["South Central US"],
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
    locations: tuple[str, ...] = ("South Central US",),
) -> dict[str, JsonValue]:
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
            [_automation_metadata_row("automationAccounts", locations=("West US",))],
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
