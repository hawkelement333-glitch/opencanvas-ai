"""Offline preparation of the selected, campaign-only operator access option.

No network client or execution entry point. Native identifiers are bound only
after separately approved creation; unresolved writes must be reconciled first.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from xml.etree import ElementTree as ET

MICROSOFT_CLIENT = "c632b3df-fb67-4d84-bdcf-b95ad541b5c8"
VNET = "10.79.0.0/16"
CLIENT_POOL = "172.31.240.0/24"
DNS_SERVER = "10.79.9.36"
ACCESS_COUNTERS = (
    "operatorVpnGateway",
    "operatorPublicIp",
    "operatorDnsResolver",
    "operatorDnsInboundEndpoint",
    "operatorGatewaySubnet",
    "operatorDnsSubnet",
    "operatorGatewayDiagnosticSetting",
    "operatorEvidenceReaderGrant",
    "operatorVpnUserAssignment",
    "operatorVpnServicePrincipal",
    "operatorVpnApplication",
    "operatorVpnDeletedServicePrincipal",
    "operatorVpnDeletedApplication",
    "operatorVpnClientProfile",
    "operatorVpnClientRoutes",
    "operatorVpnClientNrptEntries",
    "operatorRestrictedQueryUser",
    "operatorDeletedRestrictedQueryUser",
    "operatorRestrictedBrowserProfile",
)


def validate_address_plan(route_prefixes: list[str]) -> None:
    """Ignore the default internet route, never a competing private route."""
    candidates = [ipaddress.ip_network(VNET), ipaddress.ip_network(CLIENT_POOL)]
    for text in route_prefixes:
        route = ipaddress.ip_network(text)
        if route.version == 4 and route.prefixlen:
            if any(route.overlaps(candidate) for candidate in candidates):
                raise ValueError("operator address plan overlaps a workstation route")


def prepare(subscription: str, tenant: str, principal: str, suffix: str) -> dict:
    for value in (subscription, tenant, principal):
        uuid.UUID(value)
    if len(suffix) != 10 or any(c not in "0123456789abcdef" for c in suffix):
        raise ValueError("exact campaign suffix required")
    prefix = f"m78p-{suffix}"
    group = f"/subscriptions/{subscription}/resourceGroups/rg-m78-{suffix}-target"

    def resource(tail: str) -> str:
        return group + "/providers/" + tail

    scope_id = str(uuid.uuid5(uuid.NAMESPACE_URL, group + "/operator-vpn-scope"))
    role_id = str(uuid.uuid5(uuid.NAMESPACE_URL, group + "/operator-vpn-role"))
    app = {
        "displayName": f"{prefix}-operator-vpn",
        "signInAudience": "AzureADMyOrg",
        "tags": [prefix, "temporary-m78-operator-access"],
        "api": {
            "oauth2PermissionScopes": [
                {
                    "id": scope_id,
                    "value": "m78-operator-vpn",
                    "type": "Admin",
                    "isEnabled": True,
                    "adminConsentDisplayName": "Temporary M78 operator VPN",
                    "adminConsentDescription": "Connect to this isolated campaign VPN only",
                }
            ],
            "preAuthorizedApplications": [
                {
                    "appId": MICROSOFT_CLIENT,
                    "delegatedPermissionIds": [scope_id],
                }
            ],
        },
        "appRoles": [
            {
                "id": role_id,
                "allowedMemberTypes": ["User"],
                "isEnabled": True,
                "value": "M78.Operator",
                "displayName": "M78 operator",
                "description": "The one approved temporary campaign operator",
            }
        ],
    }
    return {
        "schema": "m78-operator-access-v1",
        "approved": False,
        "tenantId": tenant,
        "principalId": principal,
        "resourceGroupId": group,
        "networkId": resource(f"Microsoft.Network/virtualNetworks/vnet-m78o-{suffix}"),
        "gatewayId": resource(
            f"Microsoft.Network/virtualNetworkGateways/vpngw-{prefix}"
        ),
        "publicIpId": resource(f"Microsoft.Network/publicIPAddresses/pip-{prefix}-vpn"),
        "resolverId": resource(f"Microsoft.Network/dnsResolvers/dnsr-{prefix}"),
        "workspaceId": resource(
            f"Microsoft.OperationalInsights/workspaces/law-m78o-{suffix}"
        ),
        "clientPool": CLIENT_POOL,
        "dnsServer": DNS_SERVER,
        "routePrefix": VNET,
        "microsoftClientAppId": MICROSOFT_CLIENT,
        "graphRequests": [
            {
                "step": "create-audience",
                "method": "POST",
                "url": "https://graph.microsoft.com/v1.0/applications",
                "body": app,
            },
            {
                "step": "expose-audience",
                "method": "PATCH",
                "url": "https://graph.microsoft.com/v1.0/applications/${applicationObjectId}",
                "body": {"identifierUris": ["api://${applicationClientId}"]},
            },
            {
                "step": "create-service-principal",
                "method": "POST",
                "url": "https://graph.microsoft.com/v1.0/servicePrincipals",
                "body": {
                    "appId": "${applicationClientId}",
                    "appRoleAssignmentRequired": True,
                    "accountEnabled": True,
                    "tags": [prefix],
                },
            },
            {
                "step": "assign-only-operator",
                "method": "POST",
                "url": "https://graph.microsoft.com/v1.0/servicePrincipals/${servicePrincipalObjectId}/appRoleAssignedTo",
                "body": {
                    "principalId": principal,
                    "resourceId": "${servicePrincipalObjectId}",
                    "appRoleId": role_id,
                },
            },
        ],
        "cleanupCounters": list(ACCESS_COUNTERS),
        "queryUser": {
            "mode": "temporary-restricted-user",
            "displayName": f"M78 {suffix} restricted query operator",
            "mailNickname": f"m78-{suffix}-reader",
            "userPrincipalName": f"m78-{suffix}-reader@${{verifiedInitialTenantDomain}}",
            "accountEnabled": True,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": "${privateTemporaryUserPassword}",
            },
            "assignedLicenses": [],
            "directoryRoles": [],
            "azureAuthority": "one campaign workspace Log Analytics Reader grant",
            "cleanup": "disable, delete and purge this native user ID only",
        },
        "readyByHours": 2,
        "stopProofHours": 10,
        "cleanupByHours": 12,
        "additionalForecastUsd": 5.5389,
        "totalForecastUsd": 36.6423,
        "incrementalCeilingUsd": 50,
        "nativeBindingsRequired": [
            "applicationObjectId",
            "applicationClientId",
            "servicePrincipalObjectId",
            "operatorAssignmentId",
            "gatewayFqdn",
            "profileSha256",
        ],
    }


def validate_audience(
    plan: dict, application: dict, service_principal: dict, assignments: list[dict]
) -> None:
    """Reject tenant-wide audience or unexpected assignees before gateway admission."""
    expected = plan["graphRequests"][0]["body"]
    if not application.get("id") or not application.get("appId"):
        raise ValueError("native application identifiers required")
    if application["appId"] == MICROSOFT_CLIENT:
        raise ValueError("shared Microsoft audience is not the campaign audience")

    def matches(actual: object, expected: object) -> bool:
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                matches(actual.get(k), v) for k, v in expected.items()
            )
        if isinstance(expected, list):
            return (
                isinstance(actual, list)
                and len(actual) == len(expected)
                and all(matches(a, b) for a, b in zip(actual, expected, strict=True))
            )
        return actual == expected

    for key in ("displayName", "signInAudience", "api", "appRoles"):
        actual = application.get(key)
        if key == "api":
            actual = {k: actual.get(k) for k in expected[key]} if actual else None
        if not matches(actual, expected[key]):
            raise ValueError(
                "native application differs from approved audience contract"
            )
    if application.get("identifierUris") != ["api://" + application["appId"]]:
        raise ValueError("audience URI does not bind native application")
    if (
        not service_principal.get("id")
        or service_principal.get("appId") != application["appId"]
        or service_principal.get("appRoleAssignmentRequired") is not True
        or service_principal.get("accountEnabled") is not True
    ):
        raise ValueError("native service principal is not restricted")
    if len(assignments) != 1 or not assignments[0].get("id"):
        raise ValueError("exactly one native operator assignment required")
    expected_assignment = plan["graphRequests"][3]["body"]
    for key in ("principalId", "appRoleId"):
        if assignments[0].get(key) != expected_assignment[key]:
            raise ValueError("unexpected operator assignment")
    if assignments[0].get("resourceId") != service_principal["id"]:
        raise ValueError("assignment belongs to another service principal")


def configure_client_profile(
    raw: bytes, tenant: str, audience: str, gateway_fqdn: str, dns_suffixes: list[str]
) -> bytes:
    """Patch only a native, identity-bound profile; preserve server trust material."""
    if (
        len(raw) > 1_000_000
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
    ):
        raise ValueError("bounded native profile without entities required")
    if not dns_suffixes or any(
        re.fullmatch(r"\.[a-z0-9-]+(?:\.[a-z0-9-]+)+", s) is None for s in dns_suffixes
    ):
        raise ValueError("exact private service DNS suffixes required")
    root = ET.fromstring(raw)
    if root.tag != "AzVpnProfile":
        raise ValueError("native Azure VPN profile required")
    aad = root.find("clientauth/aad")
    if aad is None or aad.findtext("audience") != audience:
        raise ValueError("profile audience mismatch")
    if (
        aad.findtext("tenant", "").rstrip("/")
        != f"https://login.microsoftonline.com/{tenant}"
    ):
        raise ValueError("profile tenant mismatch")
    if aad.findtext("issuer") != f"https://sts.windows.net/{tenant}/":
        raise ValueError("profile issuer mismatch")
    servers = root.findall("serverlist/ServerEntry/fqdn")
    if not servers or any(s.text != gateway_fqdn for s in servers):
        raise ValueError("profile gateway mismatch")
    if root.find("servervalidation") is None:
        raise ValueError("native server trust configuration required")
    client_app = aad.find("applicationid")
    if client_app is None:
        client_app = ET.SubElement(aad, "applicationid")
    client_app.text = MICROSOFT_CLIENT
    config = root.find("clientconfig")
    if config is None:
        config = ET.SubElement(root, "clientconfig")
    config.attrib.clear()
    for name in ("dnsservers", "dnssuffixes", "includeroutes", "excluderoutes"):
        for old in list(config.findall(name)):
            config.remove(old)
    ET.SubElement(ET.SubElement(config, "dnsservers"), "dnsserver").text = DNS_SERVER
    suffixes = ET.SubElement(config, "dnssuffixes")
    for suffix in dns_suffixes:
        ET.SubElement(suffixes, "dnssuffix").text = suffix
    route = ET.SubElement(ET.SubElement(config, "includeroutes"), "route")
    ET.SubElement(route, "destination").text = "10.79.0.0"
    ET.SubElement(route, "mask").text = "16"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def validate_cleanup(counters: dict[str, int]) -> None:
    if set(counters) != set(ACCESS_COUNTERS) or any(
        type(v) is not int or v != 0 for v in counters.values()
    ):
        raise ValueError("every selected access residue counter must be observed zero")


def validate_query_authority(
    assignments: list[dict], query_assignment_id: str, workspace_id: str
) -> None:
    """Complete direct/inherited query-principal assignment set, not a filtered subset.

    The human proof user has only the one workspace Log Analytics Reader grant.
    Export is performed by the separately entitled campaign administration user.
    A new user must also be checked for dynamic/transitive group assignments.
    """
    if len(assignments) != 1:
        raise ValueError(
            "query principal has additional or missing inherited authority"
        )
    grant = assignments[0]
    if (
        grant.get("id", "").lower() != query_assignment_id.lower()
        or grant.get("scope", "").lower() != workspace_id.lower()
        or grant.get("roleDefinitionId", "").rsplit("/", 1)[-1]
        != "73c42c96-874c-492b-b04d-ab87d138a893"
        or grant.get("condition")
    ):
        raise ValueError(
            "query principal does not have the exact revocable workspace grant"
        )
