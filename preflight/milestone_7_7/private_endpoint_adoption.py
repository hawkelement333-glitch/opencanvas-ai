"""Exact Generation 4 private-endpoint adoption projections."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Final, NoReturn

from performance.milestone_7_7.framework import JsonValue

PRIVATE_ENDPOINT_SUBNET_CIDR: Final = "10.77.2.0/24"
PRIVATE_ENDPOINT_LIST_QUERY: Final = (
    "[].{id:id,name:name,location:location,provisioningState:provisioningState,"
    "subnetId:subnet.id,networkInterfaceIds:networkInterfaces[].id,"
    "connections:privateLinkServiceConnections[].{name:name,"
    "serviceId:privateLinkServiceId,groupIds:groupIds,"
    "status:privateLinkServiceConnectionState.status,provisioningState:provisioningState}}"
)
PRIVATE_ENDPOINT_NIC_LIST_QUERY: Final = (
    "[?privateEndpoint.id != null].{id:id,location:location,"
    "provisioningState:provisioningState,privateEndpointId:privateEndpoint.id,"
    "ipConfigurations:ipConfigurations[].{privateIPAddress:privateIPAddress,"
    "provisioningState:provisioningState,subnetId:subnet.id}}"
)
PRIVATE_DNS_ZONE_GROUP_LIST_QUERY: Final = (
    "value[].{id:id,name:name,provisioningState:properties.provisioningState,"
    "configs:properties.privateDnsZoneConfigs[].{"
    "name:name,zoneId:properties.privateDnsZoneId}}"
)


@dataclass(frozen=True, slots=True)
class PrivateEndpointExpectation:
    name: str
    connection_name: str
    endpoint_id: str
    service_id: str
    group_id: str
    zone_configs: tuple[tuple[str, str], ...]


PRIVATE_ENDPOINT_GRAPH: Final = (
    (
        "pe-mobius77-acr",
        "plc-mobius77-acr",
        "Microsoft.ContainerRegistry/registries/acrmobius7711564669",
        "registry",
        (("registry", "privatelink.azurecr.io"),),
    ),
    (
        "pe-mobius77-keyvault",
        "plc-mobius77-keyvault",
        "Microsoft.KeyVault/vaults/kv-mobius77-11564669",
        "vault",
        (("vault", "privatelink.vaultcore.azure.net"),),
    ),
    (
        "pe-mobius77-storage",
        "blob",
        "Microsoft.Storage/storageAccounts/stmobius7711564669",
        "blob",
        (("blob", "privatelink.blob.core.windows.net"),),
    ),
    (
        "pe-mobius77-azure-monitor",
        "azuremonitor",
        "Microsoft.Insights/privateLinkScopes/ampls-mobius77-staging",
        "azuremonitor",
        (
            ("monitor", "privatelink.monitor.azure.com"),
            ("oms", "privatelink.oms.opinsights.azure.com"),
            ("ods", "privatelink.ods.opinsights.azure.com"),
            ("agent", "privatelink.agentsvc.azure-automation.net"),
            ("blob", "privatelink.blob.core.windows.net"),
        ),
    ),
)
PRIVATE_ENDPOINT_RESOURCE_LOCATIONS: Final = tuple(
    (
        f"microsoft.network/privateendpoints/{name}{suffix}",
        "southcentralus",
    )
    for name, _connection, _service, _group, _zones in PRIVATE_ENDPOINT_GRAPH
    for suffix in ("", "/privatednszonegroups/default")
)


class PrivateEndpointAdoptionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _malformed() -> NoReturn:
    raise PrivateEndpointAdoptionError("pre-secret-private-endpoint-output-malformed")


def _drift() -> NoReturn:
    raise PrivateEndpointAdoptionError("pre-secret-private-endpoint-drift")


def private_endpoint_expectations(
    target_scope: str,
) -> dict[str, PrivateEndpointExpectation]:
    return {
        name: PrivateEndpointExpectation(
            name=name,
            connection_name=connection_name,
            endpoint_id=(
                f"{target_scope}/providers/Microsoft.Network/privateEndpoints/{name}"
            ),
            service_id=f"{target_scope}/providers/{service_relative_id}",
            group_id=group_id,
            zone_configs=tuple(
                (
                    config_name,
                    f"{target_scope}/providers/Microsoft.Network/privateDnsZones/{zone_name}",
                )
                for config_name, zone_name in zone_configs
            ),
        )
        for (
            name,
            connection_name,
            service_relative_id,
            group_id,
            zone_configs,
        ) in PRIVATE_ENDPOINT_GRAPH
    }


def validate_private_endpoint_rows(
    rows: JsonValue | None,
    *,
    expectations: dict[str, PrivateEndpointExpectation],
    target_scope: str,
    private_subnet_id: str,
    location: str,
) -> dict[str, str]:
    if not isinstance(rows, list):
        _malformed()
    if len(rows) != len(expectations):
        _drift()
    observed_names: set[str] = set()
    observed_endpoint_ids: set[str] = set()
    network_interface_endpoints: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "connections",
            "id",
            "location",
            "name",
            "networkInterfaceIds",
            "provisioningState",
            "subnetId",
        }:
            _malformed()
        name = row["name"]
        endpoint_id = row["id"]
        connections = row["connections"]
        nics = row["networkInterfaceIds"]
        expectation = expectations.get(name) if isinstance(name, str) else None
        if (
            expectation is None
            or name in observed_names
            or not isinstance(endpoint_id, str)
            or endpoint_id.casefold() != expectation.endpoint_id.casefold()
            or endpoint_id.casefold() in observed_endpoint_ids
            or row["location"] != location
            or row["provisioningState"] != "Succeeded"
            or not isinstance(row["subnetId"], str)
            or row["subnetId"].casefold() != private_subnet_id.casefold()
            or not isinstance(connections, list)
            or len(connections) != 1
            or not isinstance(nics, list)
            or len(nics) != 1
            or not isinstance(nics[0], str)
        ):
            _drift()
        connection = connections[0]
        if not isinstance(connection, dict) or set(connection) != {
            "groupIds",
            "name",
            "provisioningState",
            "serviceId",
            "status",
        }:
            _malformed()
        service_id = connection["serviceId"]
        if (
            connection["name"] != expectation.connection_name
            or connection["groupIds"] != [expectation.group_id]
            or not isinstance(service_id, str)
            or service_id.casefold() != expectation.service_id.casefold()
            or connection["status"] != "Approved"
            or connection["provisioningState"] != "Succeeded"
        ):
            _drift()
        nic_id = nics[0]
        assert isinstance(nic_id, str)
        normalized_nic = nic_id.casefold()
        if (
            not normalized_nic.startswith(
                f"{target_scope.casefold()}/providers/microsoft.network/networkinterfaces/"
            )
            or normalized_nic in network_interface_endpoints
        ):
            _drift()
        network_interface_endpoints[normalized_nic] = endpoint_id.casefold()
        observed_names.add(expectation.name)
        observed_endpoint_ids.add(endpoint_id.casefold())
    if observed_names != set(expectations):
        _drift()
    return network_interface_endpoints


def validate_private_endpoint_network_interfaces(
    rows: JsonValue | None,
    *,
    network_interface_endpoints: dict[str, str],
    private_subnet_id: str,
    location: str,
) -> frozenset[str]:
    if not isinstance(rows, list):
        _malformed()
    if len(rows) != len(network_interface_endpoints):
        _drift()
    approved_network = ipaddress.ip_network(PRIVATE_ENDPOINT_SUBNET_CIDR)
    observed_nics: set[str] = set()
    observed_private_addresses: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "ipConfigurations",
            "location",
            "privateEndpointId",
            "provisioningState",
        }:
            _malformed()
        nic_id = row["id"]
        endpoint_id = row["privateEndpointId"]
        configurations = row["ipConfigurations"]
        if (
            not isinstance(nic_id, str)
            or nic_id.casefold() not in network_interface_endpoints
            or nic_id.casefold() in observed_nics
            or row["location"] != location
            or row["provisioningState"] != "Succeeded"
            or not isinstance(endpoint_id, str)
            or endpoint_id.casefold() != network_interface_endpoints[nic_id.casefold()]
            or not isinstance(configurations, list)
            or not configurations
        ):
            _drift()
        for configuration in configurations:
            if not isinstance(configuration, dict) or set(configuration) != {
                "privateIPAddress",
                "provisioningState",
                "subnetId",
            }:
                _malformed()
            address = configuration["privateIPAddress"]
            subnet_id = configuration["subnetId"]
            if (
                configuration["provisioningState"] != "Succeeded"
                or not isinstance(subnet_id, str)
                or subnet_id.casefold() != private_subnet_id.casefold()
                or not isinstance(address, str)
            ):
                _drift()
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError:
                _drift()
            normalized_address = str(parsed_address)
            if (
                parsed_address.version != 4
                or parsed_address not in approved_network
                or normalized_address in observed_private_addresses
            ):
                _drift()
            observed_private_addresses.add(normalized_address)
        observed_nics.add(nic_id.casefold())
    if observed_nics != set(network_interface_endpoints):
        _drift()
    return frozenset(network_interface_endpoints)


def validate_private_dns_zone_groups(
    rows: JsonValue | None, expectation: PrivateEndpointExpectation
) -> None:
    if not isinstance(rows, list):
        _malformed()
    if len(rows) != 1:
        _drift()
    zone_group = rows[0]
    if not isinstance(zone_group, dict) or set(zone_group) != {
        "configs",
        "id",
        "name",
        "provisioningState",
    }:
        _malformed()
    configs = zone_group["configs"]
    if (
        not isinstance(configs, list)
        or len(configs) != len(expectation.zone_configs)
        or zone_group["name"] != "default"
        or not isinstance(zone_group["id"], str)
        or zone_group["id"].casefold()
        != f"{expectation.endpoint_id}/privateDnsZoneGroups/default".casefold()
        or zone_group["provisioningState"] != "Succeeded"
    ):
        _drift()
    observed_configs: dict[str, str] = {}
    for config in configs:
        if (
            not isinstance(config, dict)
            or set(config) != {"name", "zoneId"}
            or not isinstance(config["name"], str)
            or not isinstance(config["zoneId"], str)
            or config["name"] in observed_configs
        ):
            _malformed()
        observed_configs[config["name"]] = config["zoneId"].casefold()
    if observed_configs != {
        name: zone_id.casefold() for name, zone_id in expectation.zone_configs
    }:
        _drift()
