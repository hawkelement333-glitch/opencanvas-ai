"""Bounded one-run executor for the Milestone 7.7 managed-binding overlay."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
    loads_json,
)
from preflight.milestone_7_7.execution import (
    AZURE_ENVIRONMENT,
    MANAGED_BINDING_OUTPUT_LIMIT_BYTES,
    PreflightExecutionError,
    _BoundedAzureRunner,
    _PopenProcessAdapter,
    _ProcessAdapter,
)
from preflight.milestone_7_7.framework import OPERATION_TIMEOUT_SECONDS
from preflight.milestone_7_7.managed_binding_contracts import (
    EXPECTED_SECRET_BINDINGS,
    INFRASTRUCTURE_ROOT,
    REPOSITORY_ROOT,
    build_authorization_ledger,
    claim_operation_receipt,
    load_managed_binding_contract,
    load_operation_overlay,
    operation_authorization_decision,
    validate_authorization_ledger,
)
from preflight.milestone_7_7.operation_contracts import OPERATION_IDS

RESULT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-operation-result/v1\0"
)
PACKAGE_RESULT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-package-one-result/v1\0"
)
RESULT_VERSION: Final = "mobius.milestone-7.7.managed-binding-operation-result.v1"
PACKAGE_RESULT_VERSION: Final = (
    "mobius.milestone-7.7.managed-binding-package-one-result.v1"
)
PROVIDER_METHOD = "azure-provider-resource-metadata-v1"
PROVIDER_TYPE_INVENTORY_METHOD = "azure-provider-resource-type-inventory-v1"
STAGING_REGION = "southcentralus"
CLEANUP_REGION = "westus"
POSTGRES_REGION = "centralus"
REDIS_REGION = "australiacentral"
METHOD_PLACEHOLDER: Final = re.compile(r"\{[A-Za-z][A-Za-z0-9]*\}")
USAGE_DECIMAL_INTEGER: Final = re.compile(r"(?:0|[1-9][0-9]{0,19})")

_EXACT_CHILD_METADATA_FALLBACKS: Final = {
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
    "Microsoft.Network/privateEndpoints/privateDnsZoneGroups": (
        "Microsoft.Network",
        "privateEndpoints/privateDnsZoneGroups",
        "privateEndpoints",
        "2025-07-01",
    ),
}
_EXACT_REGION_INDEPENDENT_BINDINGS: Final[
    dict[str, tuple[str, str, str, frozenset[str]]]
] = {
    "Microsoft.Authorization/roleAssignments": (
        "Microsoft.Authorization",
        "roleAssignments",
        "2022-04-01",
        frozenset(),
    ),
    "Microsoft.Network/privateDnsZones": (
        "Microsoft.Network",
        "privateDnsZones",
        "2024-06-01",
        frozenset({"global"}),
    ),
    "Microsoft.Network/privateDnsZones/virtualNetworkLinks": (
        "Microsoft.Network",
        "privateDnsZones/virtualNetworkLinks",
        "2024-06-01",
        frozenset({"global"}),
    ),
}
_EXACT_CLEANUP_REGION_BINDINGS: Final = frozenset(
    {
        "Microsoft.Automation/automationAccounts",
        "Microsoft.Automation/automationAccounts/jobSchedules",
        "Microsoft.Automation/automationAccounts/runbooks",
        "Microsoft.Automation/automationAccounts/schedules",
    }
)
_EXACT_POSTGRES_REGION_BINDINGS: Final = frozenset(
    {
        "Microsoft.DBforPostgreSQL/flexibleServers",
        "Microsoft.DBforPostgreSQL/flexibleServers/administrators",
        "Microsoft.DBforPostgreSQL/flexibleServers/databases",
    }
)
_EXACT_REDIS_REGION_BINDINGS: Final = frozenset(
    {
        "Microsoft.Cache/redisEnterprise",
        "Microsoft.Cache/redisEnterprise/databases",
        "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments",
    }
)

_PROVIDER_KEYS_BY_OPERATION: Final = {
    "regional-service-availability": (
        "Microsoft.App/containerApps",
        "Microsoft.App/managedEnvironments",
        "Microsoft.Automation/automationAccounts",
        "Microsoft.Cache/redisEnterprise",
        "Microsoft.ContainerRegistry/registries",
        "Microsoft.DBforPostgreSQL/flexibleServers",
        "Microsoft.EventGrid/systemTopics",
        "Microsoft.KeyVault/vaults",
        "Microsoft.ManagedIdentity/userAssignedIdentities",
        "Microsoft.Network/dnsResolvers",
        "Microsoft.Network/dnsResolvers/inboundEndpoints",
        "Microsoft.Network/privateEndpoints",
        "Microsoft.Network/publicIPAddresses",
        "Microsoft.Network/virtualNetworkGateways",
        "Microsoft.Network/virtualNetworks",
        "Microsoft.OperationalInsights/workspaces",
        "Microsoft.Storage/storageAccounts",
    ),
    "provider-registration-api-versions": (),
    "regional-sku-capabilities": (
        "Microsoft.App/containerApps",
        "Microsoft.App/managedEnvironments",
        "Microsoft.Automation/automationAccounts",
        "Microsoft.Cache/redisEnterprise",
        "Microsoft.DBforPostgreSQL/flexibleServers",
        "Microsoft.KeyVault/vaults",
        "Microsoft.Network/virtualNetworkGateways",
        "Microsoft.OperationalInsights/workspaces",
    ),
    "private-endpoint-network-support": (
        "Microsoft.Cache/redisEnterprise",
        "Microsoft.Network/privateEndpoints",
        "Microsoft.Network/virtualNetworks",
        "Microsoft.Storage/storageAccounts",
    ),
    "private-dns-prerequisites": (
        "Microsoft.Network/dnsResolvers",
        "Microsoft.Network/dnsResolvers/inboundEndpoints",
        "Microsoft.Network/privateDnsZones",
        "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
    ),
    "managed-identity-support": (
        "Microsoft.App/containerApps",
        "Microsoft.ManagedIdentity/userAssignedIdentities",
    ),
    "telemetry-diagnostic-prerequisites": (
        "Microsoft.App/managedEnvironments",
        "Microsoft.Insights/diagnosticSettings",
        "Microsoft.OperationalInsights/workspaces",
    ),
    "evidence-retention-prerequisites": ("Microsoft.OperationalInsights/workspaces",),
    "scanner-result-bridge-prerequisites": (
        "Microsoft.EventGrid/eventSubscriptions",
        "Microsoft.EventGrid/systemTopics",
        "Microsoft.Security/defenderForStorageSettings",
    ),
    "private-acr-source-prerequisites": ("Microsoft.ContainerRegistry/registries",),
}


class ManagedBindingExecutionError(RuntimeError):
    """Stable, non-sensitive managed-binding failure."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_object(value: JsonValue, error_code: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ManagedBindingExecutionError(error_code)
    return value


def _as_array(value: JsonValue, error_code: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ManagedBindingExecutionError(error_code)
    return value


def _positive_integer_map(value: JsonValue, error_code: str) -> dict[str, int]:
    raw = _as_object(value, error_code)
    result: dict[str, int] = {}
    for name, item in raw.items():
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise ManagedBindingExecutionError(error_code)
        result[name] = item
    return result


def _normal_location(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _method_registry() -> dict[str, JsonValue]:
    overlay = load_operation_overlay()
    return _as_object(overlay["methodDefinitions"], "method-registry-invalid")


def _materialize_azure_method(
    method_id: str,
    *,
    raw_subscription_id: str,
    bindings: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    methods = _method_registry()
    method = _as_object(methods.get(method_id), "method-definition-missing")
    if method.get("executable") != "az" or method.get("controlPlaneOnly") is not True:
        raise ManagedBindingExecutionError("azure-method-not-control-plane")
    raw_arguments = _as_array(method["argumentVector"], "method-arguments-invalid")
    values = dict(bindings or {})
    arguments: list[str] = []
    for raw_argument in raw_arguments:
        if not isinstance(raw_argument, str):
            raise ManagedBindingExecutionError("method-arguments-invalid")
        argument = raw_argument
        for name, replacement in values.items():
            if not replacement or any(
                char in replacement for char in ("\x00", "\r", "\n")
            ):
                raise ManagedBindingExecutionError("method-binding-invalid")
            argument = argument.replace("{" + name + "}", replacement)
        if METHOD_PLACEHOLDER.search(argument) is not None:
            raise ManagedBindingExecutionError("method-binding-incomplete")
        arguments.append(argument)
    if "--subscription" in arguments:
        raise ManagedBindingExecutionError("method-subscription-binding-duplicated")
    arguments.extend(("--subscription", raw_subscription_id))
    return ("az", *arguments)


def _run_json_method(
    adapter: _ProcessAdapter,
    method_id: str,
    *,
    raw_subscription_id: str,
    bindings: Mapping[str, str] | None = None,
) -> JsonValue:
    argv = _materialize_azure_method(
        method_id,
        raw_subscription_id=raw_subscription_id,
        bindings=bindings,
    )
    capture = adapter.run(
        argv,
        environment={**os.environ, **AZURE_ENVIRONMENT},
        timeout_seconds=OPERATION_TIMEOUT_SECONDS,
        maximum_output_bytes=MANAGED_BINDING_OUTPUT_LIMIT_BYTES,
    )
    try:
        if capture.timed_out:
            raise ManagedBindingExecutionError("azure-method-timeout")
        if capture.oversized:
            raise ManagedBindingExecutionError("azure-method-output-oversized")
        if capture.read_failed:
            raise ManagedBindingExecutionError("azure-method-output-read-failed")
        if capture.exit_code != 0:
            raise ManagedBindingExecutionError("azure-method-nonzero-exit")
        try:
            text = bytes(capture.stdout).decode("utf-8", errors="strict")
        except UnicodeError:
            raise ManagedBindingExecutionError(
                "azure-method-output-malformed"
            ) from None
        if not text.strip():
            raise ManagedBindingExecutionError("azure-method-output-blank")
        try:
            return loads_json(text)
        except ContractError:
            raise ManagedBindingExecutionError(
                "azure-method-output-malformed"
            ) from None
    finally:
        capture.release()


def _provider_binding(key: str) -> tuple[str, str, str]:
    contract = load_managed_binding_contract()
    versions = _as_object(
        contract["providerApiVersions"], "provider-api-registry-invalid"
    )
    version = versions.get(key)
    if not isinstance(version, str):
        raise ManagedBindingExecutionError("provider-api-binding-missing")
    namespace, separator, resource_type = key.partition("/")
    if not separator or not namespace.startswith("Microsoft.") or not resource_type:
        raise ManagedBindingExecutionError("provider-api-binding-invalid")
    return namespace, resource_type, version


def _provider_keys(operation_id: str) -> tuple[str, ...]:
    if operation_id == "provider-registration-api-versions":
        contract = load_managed_binding_contract()
        versions = _as_object(
            contract["providerApiVersions"], "provider-api-registry-invalid"
        )
        return tuple(str(key) for key in versions)
    return _PROVIDER_KEYS_BY_OPERATION.get(operation_id, ())


def _normalized_provider_resource_type(namespace: str, value: JsonValue) -> str:
    if not isinstance(value, str) or not value:
        raise ManagedBindingExecutionError("provider-metadata-malformed")
    if (
        value != value.strip()
        or "\\" in value
        or "//" in value
        or value.startswith("/")
        or value.endswith("/")
    ):
        raise ManagedBindingExecutionError("provider-metadata-malformed")
    normalized = value.casefold()
    namespace_prefix = f"{namespace.casefold()}/"
    if normalized.startswith("microsoft."):
        if not normalized.startswith(namespace_prefix):
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        normalized = normalized[len(namespace_prefix) :]
    return normalized


def _exact_child_metadata_fallback(
    *,
    namespace: str,
    resource_type: str,
    pinned_version: str,
    adapter: _ProcessAdapter,
    raw_subscription_id: str,
) -> tuple[dict[str, JsonValue] | None, bool]:
    key = f"{namespace}/{resource_type}"
    fallback = _EXACT_CHILD_METADATA_FALLBACKS.get(key)
    if fallback is None:
        return None, False
    (
        expected_namespace,
        expected_resource_type,
        parent_resource_type,
        expected_version,
    ) = fallback
    if (namespace, resource_type, pinned_version) != (
        expected_namespace,
        expected_resource_type,
        expected_version,
    ):
        return None, False

    if _provider_binding(key) != (
        namespace,
        expected_resource_type,
        expected_version,
    ):
        raise ManagedBindingExecutionError("exact-child-fallback-binding-invalid")

    raw = _run_json_method(
        adapter,
        PROVIDER_TYPE_INVENTORY_METHOD,
        raw_subscription_id=raw_subscription_id,
        bindings={"providerNamespace": namespace},
    )
    inventory = _as_object(raw, "provider-metadata-malformed")
    if set(inventory) != {"registrationState", "resourceTypes"}:
        raise ManagedBindingExecutionError("provider-metadata-malformed")
    registration_state = inventory["registrationState"]
    resource_types = inventory["resourceTypes"]
    if not isinstance(registration_state, str) or not isinstance(resource_types, list):
        raise ManagedBindingExecutionError("provider-metadata-malformed")

    normalized_rows: list[tuple[str, str]] = []
    for raw_resource_type in resource_types:
        if not isinstance(raw_resource_type, str):
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        normalized = _normalized_provider_resource_type(namespace, raw_resource_type)
        normalized_rows.append((normalized, raw_resource_type))

    def exact_metadata(
        raw_resource_type: str, expected_normalized: str
    ) -> dict[str, JsonValue]:
        value = _as_object(
            _run_json_method(
                adapter,
                PROVIDER_METHOD,
                raw_subscription_id=raw_subscription_id,
                bindings={
                    "providerNamespace": namespace,
                    "resourceType": raw_resource_type,
                },
            ),
            "provider-metadata-malformed",
        )
        if set(value) != {
            "apiVersions",
            "locations",
            "registrationState",
            "resourceType",
        }:
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        if value["registrationState"] != registration_state:
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        if (
            _normalized_provider_resource_type(namespace, value["resourceType"])
            != expected_normalized
        ):
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        return value

    child_name = expected_resource_type.casefold()
    child_rows = [
        raw for normalized, raw in normalized_rows if normalized == child_name
    ]
    if len(child_rows) > 1:
        raise ManagedBindingExecutionError("provider-metadata-malformed")
    if child_rows:
        child = exact_metadata(child_rows[0], child_name)
        return (
            {
                "registrationState": registration_state,
                "resourceType": resource_type,
                "apiVersions": child["apiVersions"],
                "locations": child["locations"],
            },
            False,
        )

    parent_name = parent_resource_type.casefold()
    parent_rows = [
        raw for normalized, raw in normalized_rows if normalized == parent_name
    ]
    if len(parent_rows) > 1:
        raise ManagedBindingExecutionError("provider-metadata-malformed")
    if not parent_rows:
        return None, False
    parent = exact_metadata(parent_rows[0], parent_name)
    return (
        {
            "registrationState": registration_state,
            "resourceType": resource_type,
            "apiVersions": parent["apiVersions"],
            "locations": parent["locations"],
        },
        True,
    )


def _regional_metadata_approved(
    *,
    key: str,
    namespace: str,
    resource_type: str,
    pinned_version: str,
    normalized_locations: set[str],
    require_region: bool,
) -> bool:
    if not require_region:
        return True
    expected = _EXACT_REGION_INDEPENDENT_BINDINGS.get(key)
    if expected is None:
        required_region = (
            CLEANUP_REGION
            if key in _EXACT_CLEANUP_REGION_BINDINGS
            else REDIS_REGION
            if key in _EXACT_REDIS_REGION_BINDINGS
            else POSTGRES_REGION
            if key in _EXACT_POSTGRES_REGION_BINDINGS
            else STAGING_REGION
        )
        return required_region in normalized_locations
    (
        expected_namespace,
        expected_resource_type,
        expected_version,
        expected_locations,
    ) = expected
    return (namespace, resource_type, pinned_version) == (
        expected_namespace,
        expected_resource_type,
        expected_version,
    ) and normalized_locations == expected_locations


def _provider_checks(
    operation_id: str,
    *,
    adapter: _ProcessAdapter,
    raw_subscription_id: str,
    require_registration: bool,
    require_region: bool,
) -> tuple[str, str, dict[str, JsonValue]]:
    keys = _provider_keys(operation_id)
    if not keys:
        raise ManagedBindingExecutionError("provider-operation-binding-missing")
    provider_states: dict[str, str] = {}
    pinned_count = 0
    region_count = 0
    observed_count = 0
    parent_fallback_count = 0
    for key in keys:
        namespace, resource_type, pinned_version = _provider_binding(key)
        raw = _run_json_method(
            adapter,
            PROVIDER_METHOD,
            raw_subscription_id=raw_subscription_id,
            bindings={
                "providerNamespace": namespace,
                "resourceType": resource_type,
            },
        )
        value = _as_object(raw, "provider-metadata-malformed")
        if set(value) != {
            "apiVersions",
            "locations",
            "registrationState",
            "resourceType",
        }:
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        registration_state = value["registrationState"]
        actual_type = value["resourceType"]
        api_versions = value["apiVersions"]
        locations = value["locations"]
        if not isinstance(registration_state, str):
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        if actual_type != resource_type:
            fallback_value, parent_fallback_used = _exact_child_metadata_fallback(
                namespace=namespace,
                resource_type=resource_type,
                pinned_version=pinned_version,
                adapter=adapter,
                raw_subscription_id=raw_subscription_id,
            )
            if fallback_value is None:
                return (
                    "blocked",
                    "required-resource-type-unavailable",
                    {
                        "required-resource-count": len(keys),
                        "observed-resource-count": observed_count,
                        "parent-fallback-count": parent_fallback_count,
                    },
                )
            value = fallback_value
            fallback_registration_state = value["registrationState"]
            if not isinstance(fallback_registration_state, str):
                raise ManagedBindingExecutionError("provider-metadata-malformed")
            registration_state = fallback_registration_state
            actual_type = value["resourceType"]
            api_versions = value["apiVersions"]
            locations = value["locations"]
            if parent_fallback_used:
                parent_fallback_count += 1
        if actual_type != resource_type:
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        if not isinstance(api_versions, list) or not all(
            isinstance(item, str) for item in api_versions
        ):
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        if not isinstance(locations, list) or not all(
            isinstance(item, str) for item in locations
        ):
            raise ManagedBindingExecutionError("provider-metadata-malformed")
        location_values = [item for item in locations if isinstance(item, str)]
        observed_count += 1
        provider_states[namespace] = registration_state
        if pinned_version in api_versions:
            pinned_count += 1
        else:
            return (
                "blocked",
                "pinned-api-version-unavailable",
                {
                    "required-resource-count": len(keys),
                    "observed-resource-count": observed_count,
                    "pinned-api-version-count": pinned_count,
                    "parent-fallback-count": parent_fallback_count,
                },
            )
        if require_registration and registration_state != "Registered":
            return (
                "blocked",
                "required-provider-not-registered",
                {
                    "required-provider-count": len(
                        _as_array(
                            load_managed_binding_contract()[
                                "providerRegistrationRequirements"
                            ],
                            "providerRegistrationRequirements",
                        )
                    ),
                    "registered-provider-count": sum(
                        state == "Registered" for state in provider_states.values()
                    ),
                    "blocked-provider": namespace,
                    "pinned-api-version-count": pinned_count,
                    "parent-fallback-count": parent_fallback_count,
                },
            )
        normalized_locations = {_normal_location(item) for item in location_values}
        if _regional_metadata_approved(
            key=key,
            namespace=namespace,
            resource_type=resource_type,
            pinned_version=pinned_version,
            normalized_locations=normalized_locations,
            require_region=require_region,
        ):
            region_count += 1
        else:
            return (
                "blocked",
                "approved-region-unavailable",
                {
                    "required-resource-count": len(keys),
                    "observed-resource-count": observed_count,
                    "approved-region-count": region_count,
                    "parent-fallback-count": parent_fallback_count,
                },
            )
    return (
        "proved",
        "provider-prerequisites-proved",
        {
            "required-resource-count": len(keys),
            "observed-resource-count": observed_count,
            "registered-provider-count": sum(
                state == "Registered" for state in provider_states.values()
            ),
            "pinned-api-version-count": pinned_count,
            "approved-region-count": region_count,
            "parent-fallback-count": parent_fallback_count,
        },
    )


def _network_usage(
    *, adapter: _ProcessAdapter, raw_subscription_id: str
) -> tuple[str, str, dict[str, JsonValue]]:
    raw = _run_json_method(
        adapter,
        "azure-network-usage-v1",
        raw_subscription_id=raw_subscription_id,
    )
    rows = _as_array(raw, "network-usage-malformed")
    if not rows:
        return "blocked", "network-usage-unavailable", {"dimension-count": 0}
    quota_contract = _as_object(
        load_managed_binding_contract()["networkQuotaRequirements"],
        "network-quota-contract-malformed",
    )
    if set(quota_contract) != {"additiveHeadroom", "perResourceMinimum"}:
        raise ManagedBindingExecutionError("network-quota-contract-malformed")
    additive = _positive_integer_map(
        quota_contract["additiveHeadroom"], "network-quota-contract-malformed"
    )
    per_resource = _positive_integer_map(
        quota_contract["perResourceMinimum"], "network-quota-contract-malformed"
    )
    requirements = {**additive, **per_resource}
    if set(additive) & set(per_resource):
        raise ManagedBindingExecutionError("network-quota-contract-malformed")
    if not requirements:
        raise ManagedBindingExecutionError("network-quota-contract-malformed")

    observed: dict[str, tuple[int, int]] = {}
    for raw_row in rows:
        row = _as_object(raw_row, "network-usage-malformed")
        if set(row) != {"current", "limit", "name"}:
            raise ManagedBindingExecutionError("network-usage-malformed")
        name = row["name"]
        if not isinstance(name, str) or name not in requirements or name in observed:
            raise ManagedBindingExecutionError("network-usage-malformed")
        current = _network_usage_integer(row["current"])
        limit = _network_usage_integer(row["limit"])
        observed[name] = (current, limit)
    if set(observed) != set(requirements):
        raise ManagedBindingExecutionError("network-usage-malformed")

    capacity_available = all(
        observed[name][0] + required <= observed[name][1]
        for name, required in additive.items()
    ) and all(required <= observed[name][1] for name, required in per_resource.items())
    return (
        ("proved" if capacity_available else "blocked"),
        (
            "network-capacity-bounded"
            if capacity_available
            else "network-capacity-not-available"
        ),
        {
            "dimension-count": len(requirements),
            "every-current-below-limit": capacity_available,
        },
    )


def _vnet_isolation(
    *, adapter: _ProcessAdapter, raw_subscription_id: str
) -> tuple[str, str, dict[str, JsonValue]]:
    raw = _run_json_method(
        adapter,
        "azure-vnet-prefixes-v1",
        raw_subscription_id=raw_subscription_id,
    )
    rows = _as_array(raw, "vnet-prefix-output-malformed")
    contract = load_managed_binding_contract()
    resource_groups = _as_object(contract["resourceGroups"], "vnet-contract-malformed")
    resources = _as_object(contract["resources"], "vnet-contract-malformed")
    network = _as_object(contract["network"], "vnet-contract-malformed")
    expected_group = resource_groups.get("target")
    expected_name = resources.get("virtualNetwork")
    expected_location = contract.get("location")
    expected_cidr = network.get("vnetCidr")
    if not all(
        isinstance(value, str) and value
        for value in (
            expected_group,
            expected_name,
            expected_location,
            expected_cidr,
        )
    ):
        raise ManagedBindingExecutionError("vnet-contract-malformed")
    assert isinstance(expected_group, str)
    assert isinstance(expected_name, str)
    assert isinstance(expected_location, str)
    assert isinstance(expected_cidr, str)
    try:
        candidate = ipaddress.ip_network(expected_cidr, strict=True)
    except ValueError:
        raise ManagedBindingExecutionError("vnet-contract-malformed") from None

    prefix_count = 0
    overlaps = 0
    expected_current_count = 0
    expected_current_drift = False
    for raw_row in rows:
        row = _as_object(raw_row, "vnet-prefix-output-malformed")
        if set(row) != {"location", "name", "prefixes", "resourceGroup"}:
            raise ManagedBindingExecutionError("vnet-prefix-output-malformed")
        name = row["name"]
        resource_group = row["resourceGroup"]
        location = row["location"]
        raw_prefixes = row["prefixes"]
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(resource_group, str)
            or not resource_group
            or not isinstance(location, str)
            or not location
            or not isinstance(raw_prefixes, list)
            or not raw_prefixes
        ):
            raise ManagedBindingExecutionError("vnet-prefix-output-malformed")

        is_expected_identity = (
            name == expected_name and resource_group == expected_group
        )
        is_exact_expected_current = (
            is_expected_identity
            and location == expected_location
            and raw_prefixes == [expected_cidr]
        )
        if is_expected_identity:
            if is_exact_expected_current:
                expected_current_count += 1
            else:
                expected_current_drift = True

        for raw_prefix in raw_prefixes:
            if not isinstance(raw_prefix, str):
                raise ManagedBindingExecutionError("vnet-prefix-output-malformed")
            try:
                prefix = ipaddress.ip_network(raw_prefix, strict=True)
            except ValueError:
                raise ManagedBindingExecutionError(
                    "vnet-prefix-output-malformed"
                ) from None
            prefix_count += 1
            if (
                prefix.version == 4
                and candidate.overlaps(prefix)
                and not is_exact_expected_current
            ):
                overlaps += 1

    if expected_current_count > 1:
        raise ManagedBindingExecutionError("vnet-prefix-output-malformed")
    isolated = overlaps == 0 and not expected_current_drift
    return (
        ("proved" if isolated else "blocked"),
        (
            "vnet-plan-isolated"
            if isolated
            else (
                "vnet-plan-resource-drift"
                if expected_current_drift
                else "vnet-plan-overlaps"
            )
        ),
        {"prefix-count": prefix_count, "overlap-count": overlaps},
    )


def _role_definitions(
    *, adapter: _ProcessAdapter, raw_subscription_id: str
) -> tuple[str, str, dict[str, JsonValue]]:
    contract = load_managed_binding_contract()
    rbac = _as_object(contract["rbac"], "rbac-contract-invalid")
    role_ids = (
        str(rbac["acrPullRoleDefinitionId"]),
        str(rbac["acrPushRoleDefinitionId"]),
        str(rbac["keyVaultSecretsUserRoleDefinitionId"]),
        str(rbac["keyVaultSecretsOfficerRoleDefinitionId"]),
        str(rbac["cleanupContributorRoleDefinitionId"]),
    )
    matched = 0
    for role_id in role_ids:
        raw = _run_json_method(
            adapter,
            "azure-role-definition-v1",
            raw_subscription_id=raw_subscription_id,
            bindings={"roleDefinitionId": role_id},
        )
        value = _as_object(raw, "role-definition-output-malformed")
        if set(value) != {"name", "roleName", "roleType"}:
            raise ManagedBindingExecutionError("role-definition-output-malformed")
        if value["name"] == role_id and value["roleType"] == "BuiltInRole":
            matched += 1
    return (
        ("proved" if matched == len(role_ids) else "blocked"),
        (
            "least-privilege-role-definitions-proved"
            if matched == len(role_ids)
            else "required-role-definition-unavailable"
        ),
        {"required-role-count": len(role_ids), "matched-built-in-role-count": matched},
    )


def _network_usage_integer(value: JsonValue) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and USAGE_DECIMAL_INTEGER.fullmatch(value) is not None:
        return int(value)
    raise ManagedBindingExecutionError("network-usage-malformed")


def _workload_profiles(
    *, adapter: _ProcessAdapter, raw_subscription_id: str
) -> tuple[str, str, dict[str, JsonValue]]:
    raw = _run_json_method(
        adapter,
        "azure-container-app-workload-profiles-v1",
        raw_subscription_id=raw_subscription_id,
    )
    rows = _as_array(raw, "workload-profile-output-malformed")
    names: list[str] = []
    for raw_row in rows:
        row = _as_object(raw_row, "workload-profile-output-malformed")
        if set(row) != {"maximumCount", "minimumCount", "name"}:
            raise ManagedBindingExecutionError("workload-profile-output-malformed")
        name = row["name"]
        if not isinstance(name, str):
            raise ManagedBindingExecutionError("workload-profile-output-malformed")
        names.append(name)
    supported = any(name.casefold() == "consumption" for name in names)
    return (
        ("proved" if supported else "blocked"),
        (
            "fixed-workload-profile-supported"
            if supported
            else "fixed-workload-profile-unavailable"
        ),
        {"supported-profile-count": len(names), "consumption-supported": supported},
    )


def _managed_provider_binding_contract() -> tuple[str, str, dict[str, JsonValue]]:
    contract = load_managed_binding_contract()
    secrets = _as_array(contract["secrets"], "secret-binding-contract-malformed")
    compute_text = (INFRASTRUCTURE_ROOT / "modules" / "compute.bicep").read_text(
        encoding="utf-8"
    )
    required = tuple(
        (secret_name, environment_name)
        for secret_name, _reference, environment_name in EXPECTED_SECRET_BINDINGS
    )
    exact_bindings = []
    for raw_binding in secrets:
        binding = _as_object(raw_binding, "secret-binding-contract-malformed")
        exact_bindings.append(
            (str(binding["keyVaultName"]), str(binding["environmentVariable"]))
        )
    canonical_only = (
        "OPENCANVAS_OPENAI_API_KEY" not in compute_text
        and all(secret_name in compute_text for secret_name, _ in required)
        and all(environment_name in compute_text for _, environment_name in required)
    )
    proved = tuple(exact_bindings) == required and canonical_only
    return (
        "proved" if proved else "blocked",
        (
            "managed-provider-binding-contract-proved"
            if proved
            else "managed-provider-binding-contract-mismatch"
        ),
        {
            "required-binding-count": len(required),
            "defined-binding-count": len(exact_bindings),
            "canonical-openai-alias-only": canonical_only,
            "secret-value-accessed": False,
        },
    )


def _cost_contract() -> tuple[str, str, dict[str, JsonValue]]:
    value = _as_object(
        load_json(INFRASTRUCTURE_ROOT / "manifests" / "cost-envelope.template.json"),
        "cost-envelope-malformed",
    )
    if value.get("resolutionStatus") != "verified":
        return (
            "blocked",
            "cost-envelope-unresolved",
            {
                "expected-usd-cents": 0,
                "maximum-usd-cents": 0,
                "within-ceilings": False,
            },
        )
    expected = value.get("expectedUsdCents")
    maximum = value.get("maximumPlausibleUsdCents")
    if (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
    ):
        raise ManagedBindingExecutionError("cost-envelope-malformed")
    within = expected <= 12_000 and maximum <= 17_500
    return (
        ("proved" if within else "blocked"),
        ("cost-envelope-bounded" if within else "cost-envelope-exceeds-ceiling"),
        {
            "expected-usd-cents": expected,
            "maximum-usd-cents": maximum,
            "within-ceilings": within,
        },
    )


def _acr_source(
    *, adapter: _ProcessAdapter, raw_subscription_id: str
) -> tuple[str, str, dict[str, JsonValue]]:
    provider_status, provider_reason, provider_fields = _provider_checks(
        "private-acr-source-prerequisites",
        adapter=adapter,
        raw_subscription_id=raw_subscription_id,
        require_registration=True,
        require_region=True,
    )
    if provider_status != "proved":
        return provider_status, provider_reason, provider_fields
    raw = _run_json_method(
        adapter,
        "azure-acr-name-v1",
        raw_subscription_id=raw_subscription_id,
    )
    value = _as_object(raw, "acr-name-output-malformed")
    if set(value) != {"available", "reason"} or not isinstance(
        value["available"], bool
    ):
        raise ManagedBindingExecutionError("acr-name-output-malformed")
    reason = value["reason"]
    if reason is not None and not isinstance(reason, str):
        raise ManagedBindingExecutionError("acr-name-output-malformed")
    managed_binding = load_managed_binding_contract()
    resource_groups = _as_object(
        managed_binding["resourceGroups"], "private-acr-source-contract-malformed"
    )
    resources = _as_object(
        managed_binding["resources"], "private-acr-source-contract-malformed"
    )
    fixed_skus = _as_object(
        managed_binding["fixedSkus"], "private-acr-source-contract-malformed"
    )
    source = _as_object(
        managed_binding["privateAcrSource"], "private-acr-source-contract-malformed"
    )
    source_ready = (
        source.get("sourceCommitBinding") == "authorization-ledger-repository-head"
        and source.get("buildTool") == "docker-buildx"
        and source.get("pushPath") == "local-docker-over-p2s-vpn-to-private-acr"
        and source.get("publicRegistryAccess") is False
        and source.get("mutableTagsAllowed") is False
        and source.get("temporarySourceTagPreexistenceDecision") == "deny"
        and source.get("temporarySourceTagRemovedAfterDigestResolution") is True
        and source.get("deploymentReference") == "digest-only"
        and source.get("dockerCredentialDirectory") == "ephemeral-outside-repository"
        and source.get("dockerLogoutRequired") is True
        and source.get("gitRemoteAccessAllowed") is False
    )
    available = value["available"] is True
    exact_current = False
    if not available and reason == "AlreadyExists":
        raw_current = _run_json_method(
            adapter,
            "azure-acr-current-v1",
            raw_subscription_id=raw_subscription_id,
        )
        current = _as_object(raw_current, "acr-current-output-malformed")
        if set(current) != {
            "adminUserEnabled",
            "anonymousPullEnabled",
            "dataEndpointEnabled",
            "location",
            "name",
            "networkRuleBypassOptions",
            "publicNetworkAccess",
            "resourceGroup",
            "sku",
            "zoneRedundancy",
        }:
            raise ManagedBindingExecutionError("acr-current-output-malformed")
        exact_current = current == {
            "name": resources.get("containerRegistry"),
            "resourceGroup": resource_groups.get("target"),
            "location": managed_binding.get("location"),
            "sku": fixed_skus.get("containerRegistry"),
            "adminUserEnabled": False,
            "anonymousPullEnabled": False,
            "dataEndpointEnabled": False,
            "networkRuleBypassOptions": "None",
            "publicNetworkAccess": "Disabled",
            "zoneRedundancy": "Disabled",
        }
    proved = (available or exact_current) and source_ready
    return (
        ("proved" if proved else "blocked"),
        ("private-acr-source-proved" if proved else "private-acr-source-unresolved"),
        {
            "literal-name-available": available,
            "exact-current-registry-proved": exact_current,
            "source-contract-complete": source_ready,
            "acr-provider-supported": True,
        },
    )


def _aggregate(
    prior_results: Sequence[dict[str, JsonValue]],
) -> tuple[str, str, dict[str, JsonValue]]:
    required = 13
    relevant = prior_results[:required]
    proved = sum(result.get("status") == "proved" for result in relevant)
    blocked = sum(result.get("status") != "proved" for result in relevant)
    return (
        ("proved" if len(relevant) == required and proved == required else "blocked"),
        (
            "prior-prerequisites-proved"
            if len(relevant) == required and proved == required
            else "prior-prerequisite-blocked"
        ),
        {"required-count": required, "proved-count": proved, "blocked-count": blocked},
    )


def _local_lifecycle_dependencies() -> tuple[str, str, dict[str, JsonValue]]:
    bicep_present = (
        shutil.which("az") is not None
        and (Path.home() / ".azure" / "bin" / "bicep.exe").is_file()
    )
    docker_present = shutil.which("docker") is not None
    git_present = shutil.which("git") is not None
    automation_extension_present = (
        Path.home() / ".azure" / "cliextensions" / "automation"
    ).is_dir()
    lifecycle_script_present = (
        INFRASTRUCTURE_ROOT / "scripts" / "managed_binding_lifecycle.py"
    ).is_file()
    cleanup_runbook_present = (
        INFRASTRUCTURE_ROOT / "scripts" / "Remove-Mobius77Staging.ps1"
    ).is_file()
    all_present = all(
        (
            bicep_present,
            docker_present,
            git_present,
            automation_extension_present,
            lifecycle_script_present,
            cleanup_runbook_present,
        )
    )
    return (
        "proved" if all_present else "blocked",
        (
            "managed-lifecycle-dependencies-present"
            if all_present
            else "managed-lifecycle-dependency-missing"
        ),
        {
            "bicep-cli-present": bicep_present,
            "docker-cli-present": docker_present,
            "git-cli-present": git_present,
            "automation-extension-present": automation_extension_present,
            "lifecycle-script-present": lifecycle_script_present,
            "cleanup-runbook-present": cleanup_runbook_present,
        },
    )


def _combine(
    first: tuple[str, str, dict[str, JsonValue]],
    second: tuple[str, str, dict[str, JsonValue]],
) -> tuple[str, str, dict[str, JsonValue]]:
    fields = {**first[2], **second[2]}
    if first[0] != "proved":
        return first[0], first[1], fields
    return second[0], second[1], fields


def _evaluate_operation(
    operation_id: str,
    *,
    adapter: _ProcessAdapter,
    raw_subscription_id: str,
    prior_results: Sequence[dict[str, JsonValue]],
) -> tuple[str, str, dict[str, JsonValue]]:
    if operation_id == "regional-service-availability":
        return _provider_checks(
            operation_id,
            adapter=adapter,
            raw_subscription_id=raw_subscription_id,
            require_registration=False,
            require_region=True,
        )
    if operation_id == "provider-registration-api-versions":
        return _provider_checks(
            operation_id,
            adapter=adapter,
            raw_subscription_id=raw_subscription_id,
            require_registration=True,
            require_region=False,
        )
    if operation_id == "regional-sku-capabilities":
        provider = _provider_checks(
            operation_id,
            adapter=adapter,
            raw_subscription_id=raw_subscription_id,
            require_registration=True,
            require_region=True,
        )
        if provider[0] != "proved":
            return provider
        return _combine(
            provider,
            _workload_profiles(
                adapter=adapter, raw_subscription_id=raw_subscription_id
            ),
        )
    if operation_id == "subscription-quota-bounded-usage":
        return _network_usage(adapter=adapter, raw_subscription_id=raw_subscription_id)
    if operation_id == "private-endpoint-network-support":
        provider = _provider_checks(
            operation_id,
            adapter=adapter,
            raw_subscription_id=raw_subscription_id,
            require_registration=True,
            require_region=True,
        )
        if provider[0] != "proved":
            return provider
        return _combine(
            provider,
            _vnet_isolation(adapter=adapter, raw_subscription_id=raw_subscription_id),
        )
    if operation_id in {
        "private-dns-prerequisites",
        "managed-identity-support",
        "telemetry-diagnostic-prerequisites",
        "evidence-retention-prerequisites",
        "scanner-result-bridge-prerequisites",
    }:
        return _provider_checks(
            operation_id,
            adapter=adapter,
            raw_subscription_id=raw_subscription_id,
            require_registration=True,
            require_region=operation_id != "private-dns-prerequisites",
        )
    if operation_id == "scoped-rbac-prerequisites":
        return _role_definitions(
            adapter=adapter, raw_subscription_id=raw_subscription_id
        )
    if operation_id == "external-test-provider-prerequisites":
        return _managed_provider_binding_contract()
    if operation_id == "bounded-cost-budget-prerequisites":
        return _cost_contract()
    if operation_id == "provisioning-dependency-blockers":
        aggregate = _aggregate(prior_results)
        if aggregate[0] != "proved":
            return aggregate
        return _combine(aggregate, _local_lifecycle_dependencies())
    if operation_id == "private-acr-source-prerequisites":
        return _acr_source(adapter=adapter, raw_subscription_id=raw_subscription_id)
    raise ManagedBindingExecutionError("operation-dispatch-missing")


def _result_integrity(value: dict[str, JsonValue]) -> str:
    body = {key: item for key, item in value.items() if key != "resultIntegritySha256"}
    return integrity_sha256(body, RESULT_DOMAIN)


def _build_result(
    operation_id: str,
    *,
    status: str,
    explanation_code: str,
    fields: dict[str, JsonValue],
    observed_at_utc: datetime,
    ledger_integrity_sha256: str,
) -> dict[str, JsonValue]:
    if status not in {"proved", "blocked", "failed"}:
        raise ManagedBindingExecutionError("operation-result-status-invalid")
    body: dict[str, JsonValue] = {
        "resultVersion": RESULT_VERSION,
        "operationId": operation_id,
        "status": status,
        "explanationCode": explanation_code,
        "observedAtUtc": _format_utc(observed_at_utc),
        "fields": fields,
        "ledgerIntegritySha256": ledger_integrity_sha256,
        "rawOutputRetained": False,
        "rawIdentifiersRetained": False,
        "mutationPerformed": False,
        "provisioningPerformed": False,
        "secretValueAccessed": False,
    }
    return {**body, "resultIntegritySha256": integrity_sha256(body, RESULT_DOMAIN)}


def _write_exclusive(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb",
            dir=path.parent,
            prefix=".managed-binding-result-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(canonical_bytes(value))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_path, path)
        temporary_path.unlink()
    except FileExistsError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ManagedBindingExecutionError("operation-result-replay-denied") from None
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ManagedBindingExecutionError("operation-result-write-failed") from None


def _load_prior_results(
    receipt_directory: Path, operation_id: str
) -> list[dict[str, JsonValue]]:
    index = OPERATION_IDS.index(operation_id)
    results: list[dict[str, JsonValue]] = []
    for prior_id in OPERATION_IDS[:index]:
        path = receipt_directory / f"{prior_id}.result.json"
        if not path.is_file():
            raise ManagedBindingExecutionError("prior-operation-result-missing")
        value = _as_object(load_json(path), "prior-operation-result-malformed")
        if value.get("operationId") != prior_id:
            raise ManagedBindingExecutionError("prior-operation-result-malformed")
        if value.get("resultIntegritySha256") != _result_integrity(value):
            raise ManagedBindingExecutionError(
                "prior-operation-result-integrity-mismatch"
            )
        results.append(value)
    return results


def _execute_operation_with_context(
    operation_id: str,
    *,
    ledger: dict[str, JsonValue],
    repository_head: str,
    receipt_directory: Path,
    adapter: _ProcessAdapter,
    raw_subscription_id: str,
    now_utc: datetime,
) -> dict[str, JsonValue]:
    operation_authorization_decision(
        operation_id,
        ledger=ledger,
        now_utc=now_utc,
        expected_repository_head=repository_head,
    )
    prior_results = _load_prior_results(receipt_directory, operation_id)
    if prior_results and prior_results[-1].get("status") != "proved":
        raise ManagedBindingExecutionError("prior-operation-not-proved")
    claim_operation_receipt(
        ledger=ledger,
        operation_id=operation_id,
        receipt_directory=receipt_directory,
        now_utc=now_utc,
        expected_repository_head=repository_head,
    )
    try:
        status, explanation, fields = _evaluate_operation(
            operation_id,
            adapter=adapter,
            raw_subscription_id=raw_subscription_id,
            prior_results=prior_results,
        )
    except (ContractError, ManagedBindingExecutionError, PreflightExecutionError):
        status = "failed"
        explanation = "managed-binding-operation-failed-closed"
        fields = {"safe-failure": True}
    result = _build_result(
        operation_id,
        status=status,
        explanation_code=explanation,
        fields=fields,
        observed_at_utc=now_utc,
        ledger_integrity_sha256=str(ledger["ledgerIntegritySha256"]),
    )
    _write_exclusive(
        receipt_directory / f"{operation_id}.result.json",
        result,
    )
    return result


def execute_operation(
    operation_id: str,
    *,
    ledger_path: Path,
    repository_head: str,
    receipt_directory: Path,
    adapter: _ProcessAdapter | None = None,
    now_utc: datetime | None = None,
) -> dict[str, JsonValue]:
    now = _utc_now() if now_utc is None else now_utc
    ledger = validate_authorization_ledger(
        load_json(ledger_path),
        now_utc=now,
        expected_repository_head=repository_head,
    )
    process_adapter = _PopenProcessAdapter() if adapter is None else adapter
    account = _BoundedAzureRunner(
        adapter=process_adapter, clock=lambda: now
    ).run_account()
    try:
        return _execute_operation_with_context(
            operation_id,
            ledger=ledger,
            repository_head=repository_head,
            receipt_directory=receipt_directory,
            adapter=process_adapter,
            raw_subscription_id=account.subscription_id_for_materialization(),
            now_utc=now,
        )
    finally:
        account.release()


def execute_package_one(
    *,
    ledger_path: Path,
    repository_head: str,
    receipt_directory: Path,
    adapter: _ProcessAdapter | None = None,
    now_utc: datetime | None = None,
) -> dict[str, JsonValue]:
    now = _utc_now() if now_utc is None else now_utc
    ledger = validate_authorization_ledger(
        load_json(ledger_path),
        now_utc=now,
        expected_repository_head=repository_head,
    )
    process_adapter = _PopenProcessAdapter() if adapter is None else adapter
    account = _BoundedAzureRunner(
        adapter=process_adapter, clock=lambda: now
    ).run_account()
    results: list[dict[str, JsonValue]] = []
    try:
        raw_subscription_id = account.subscription_id_for_materialization()
        for operation_id in OPERATION_IDS:
            result = _execute_operation_with_context(
                operation_id,
                ledger=ledger,
                repository_head=repository_head,
                receipt_directory=receipt_directory,
                adapter=process_adapter,
                raw_subscription_id=raw_subscription_id,
                now_utc=now,
            )
            results.append(result)
            if result["status"] != "proved":
                break
    finally:
        account.release()
    status = (
        "proved"
        if len(results) == 15
        and all(result["status"] == "proved" for result in results)
        else "blocked"
    )
    body: dict[str, JsonValue] = {
        "resultVersion": PACKAGE_RESULT_VERSION,
        "status": status,
        "accountMatched": True,
        "operationCount": len(results),
        "provedCount": sum(result["status"] == "proved" for result in results),
        "blockedOperationId": (
            None if status == "proved" else str(results[-1]["operationId"])
        ),
        "blockedExplanationCode": (
            None if status == "proved" else str(results[-1]["explanationCode"])
        ),
        "ledgerIntegritySha256": ledger["ledgerIntegritySha256"],
        "rawOutputRetained": False,
        "rawIdentifiersRetained": False,
        "mutationPerformed": False,
        "provisioningPerformed": False,
        "secretValueAccessed": False,
    }
    return {
        **body,
        "resultIntegritySha256": integrity_sha256(body, PACKAGE_RESULT_DOMAIN),
    }


def materialize_ledger(
    *, ledger_path: Path, repository_head: str, now_utc: datetime | None = None
) -> dict[str, JsonValue]:
    resolved_path = ledger_path.resolve()
    resolved_repository = REPOSITORY_ROOT.resolve()
    if (
        resolved_path == resolved_repository
        or resolved_repository in resolved_path.parents
    ):
        raise ManagedBindingExecutionError("ledger-path-inside-repository")
    ledger = build_authorization_ledger(
        issued_at_utc=_utc_now() if now_utc is None else now_utc,
        repository_head=repository_head,
    )
    _write_exclusive(resolved_path, ledger)
    return {
        "status": "materialized",
        "ledgerVersion": ledger["ledgerVersion"],
        "authorizationId": ledger["authorizationId"],
        "expiresAtUtc": ledger["expiresAtUtc"],
        "ledgerIntegritySha256": ledger["ledgerIntegritySha256"],
        "operationCount": len(OPERATION_IDS),
        "secretValueAccessAuthorized": False,
        "provisioningAuthorizedByDefault": False,
    }


def dry_run() -> dict[str, JsonValue]:
    contract = load_managed_binding_contract()
    overlay = load_operation_overlay()
    return {
        "status": "valid-local-only",
        "managedBindingIntegritySha256": overlay["managedBindingIntegritySha256"],
        "operationOverlayIntegritySha256": overlay["contractIntegritySha256"],
        "operationCount": len(OPERATION_IDS),
        "lifecycleOperationCount": len(
            _as_array(overlay["lifecycleOperations"], "lifecycleOperations")
        ),
        "defaultAuthority": contract["defaultAuthority"],
        "azureProcessInvocations": 0,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the closed managed-binding executor."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--materialize-ledger", action="store_true")
    mode.add_argument("--execute-operation", choices=OPERATION_IDS)
    mode.add_argument("--execute-package-one", action="store_true")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--receipt-directory", type=Path)
    parser.add_argument("--repository-head")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dry_run:
            result = dry_run()
        else:
            if args.ledger is None or args.repository_head is None:
                raise ManagedBindingExecutionError("required-execution-binding-missing")
            if args.materialize_ledger:
                result = materialize_ledger(
                    ledger_path=args.ledger,
                    repository_head=args.repository_head,
                )
            else:
                if args.receipt_directory is None:
                    raise ManagedBindingExecutionError(
                        "required-execution-binding-missing"
                    )
                if args.execute_package_one:
                    result = execute_package_one(
                        ledger_path=args.ledger,
                        repository_head=args.repository_head,
                        receipt_directory=args.receipt_directory,
                    )
                else:
                    result = execute_operation(
                        str(args.execute_operation),
                        ledger_path=args.ledger,
                        repository_head=args.repository_head,
                        receipt_directory=args.receipt_directory,
                    )
    except (
        ContractError,
        ManagedBindingExecutionError,
        PreflightExecutionError,
    ) as exc:
        error_code = getattr(exc, "error_code", "managed-binding-contract-invalid")
        print(
            canonical_bytes({"status": "blocked", "errorCode": error_code}).decode(),
            end="",
        )
        return 2
    print(canonical_bytes(result).decode(), end="")
    if args.execute_operation or args.execute_package_one:
        return 0 if result.get("status") == "proved" else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
