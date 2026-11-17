"""Only new offline operator-access boundaries; no cloud or prior suite replay."""

import copy
from xml.etree import ElementTree as ET

import pytest
from infra.milestone_7_8.operator_access_package import (
    ACCESS_COUNTERS,
    MICROSOFT_CLIENT,
    configure_client_profile,
    prepare,
    validate_address_plan,
    validate_audience,
    validate_cleanup,
    validate_query_authority,
)

TENANT = "11111111-1111-4111-8111-111111111111"
PRINCIPAL = "22222222-2222-4222-8222-222222222222"
SUBSCRIPTION = "33333333-3333-4333-8333-333333333333"
AUDIENCE = "44444444-4444-4444-8444-444444444444"


def audience_fixture():
    plan = prepare(SUBSCRIPTION, TENANT, PRINCIPAL, "a712b8c940")
    app = copy.deepcopy(plan["graphRequests"][0]["body"])
    app.update(id="application-object", appId=AUDIENCE, identifierUris=["api://" + AUDIENCE])
    app["api"]["oauth2PermissionScopes"][0]["userConsentDisplayName"] = None
    sp = {
        "id": "service-principal-object",
        "appId": AUDIENCE,
        "appRoleAssignmentRequired": True,
        "accountEnabled": True,
    }
    assignment = copy.deepcopy(plan["graphRequests"][3]["body"])
    assignment.update(id="assignment-id", resourceId=sp["id"])
    return plan, app, sp, [assignment]


def test_only_approved_operator_and_campaign_audience_are_admitted():
    plan, app, sp, assignments = audience_fixture()
    validate_audience(plan, app, sp, assignments)
    for changed in [
        [],
        assignments * 2,
        [{**assignments[0], "principalId": TENANT}],
        [{**assignments[0], "resourceId": "another-sp"}],
    ]:
        with pytest.raises(ValueError):
            validate_audience(plan, app, sp, changed)
    with pytest.raises(ValueError):
        validate_audience(plan, app, {**sp, "appRoleAssignmentRequired": False}, assignments)
    with pytest.raises(ValueError):
        validate_audience(plan, {**app, "appId": MICROSOFT_CLIENT}, sp, assignments)


def test_extra_scope_or_multitenant_audience_is_rejected():
    plan, app, sp, assignments = audience_fixture()
    with pytest.raises(ValueError):
        validate_audience(plan, {**app, "signInAudience": "AzureADMultipleOrgs"}, sp, assignments)
    app["api"]["oauth2PermissionScopes"] *= 2
    with pytest.raises(ValueError):
        validate_audience(plan, app, sp, assignments)


def test_route_overlap_is_not_hidden_by_default_route():
    validate_address_plan(["0.0.0.0/0", "192.168.1.0/24"])
    for route in ("10.0.0.0/8", "10.79.4.0/23", "172.31.240.12/32"):
        with pytest.raises(ValueError):
            validate_address_plan(["0.0.0.0/0", route])


def profile():
    return f"""<AzVpnProfile xmlns:i="http://www.w3.org/2001/XMLSchema-instance"><clientauth><aad>
      <audience>{AUDIENCE}</audience><tenant>https://login.microsoftonline.com/{TENANT}/</tenant>
      <issuer>https://sts.windows.net/{TENANT}/</issuer></aad></clientauth>
      <serverlist><ServerEntry><fqdn>fixture.vpn.azure.com</fqdn></ServerEntry></serverlist>
      <servervalidation><cert><hash>retained-native-pin</hash></cert></servervalidation>
      <clientconfig i:nil="true" /></AzVpnProfile>""".encode()


def test_native_profile_keeps_trust_and_binds_dns_split_route():
    raw = configure_client_profile(
        profile(),
        TENANT,
        AUDIENCE,
        "fixture.vpn.azure.com",
        [".fixture.azurecontainerapps.io", ".blob.core.windows.net"],
    )
    doc = ET.fromstring(raw)
    assert doc.findtext("servervalidation/cert/hash") == "retained-native-pin"
    assert doc.findtext("clientauth/aad/applicationid") == MICROSOFT_CLIENT
    assert doc.findtext("clientconfig/dnsservers/dnsserver") == "10.79.9.36"
    assert doc.findtext("clientconfig/includeroutes/route/destination") == "10.79.0.0"
    assert doc.findtext("clientconfig/includeroutes/route/mask") == "16"
    assert not doc.find("clientconfig").attrib


def test_profile_refuses_other_identity_gateway_and_entities():
    for tenant, audience, host in [
        (PRINCIPAL, AUDIENCE, "fixture.vpn.azure.com"),
        (TENANT, PRINCIPAL, "fixture.vpn.azure.com"),
        (TENANT, AUDIENCE, "other.vpn.azure.com"),
    ]:
        with pytest.raises(ValueError):
            configure_client_profile(profile(), tenant, audience, host, [".blob.core.windows.net"])
    with pytest.raises(ValueError):
        configure_client_profile(
            b"<!DOCTYPE bad>" + profile(),
            TENANT,
            AUDIENCE,
            "fixture.vpn.azure.com",
            [".blob.core.windows.net"],
        )
    with pytest.raises(ValueError):
        configure_client_profile(profile(), TENANT, AUDIENCE, "fixture.vpn.azure.com", ["."])


def test_cleanup_requires_each_observed_zero_including_tenant_and_client():
    zero = dict.fromkeys(ACCESS_COUNTERS, 0)
    validate_cleanup(zero)
    for invalid in [
        {},
        {**zero, "operatorVpnDeletedApplication": 1},
        {**zero, "operatorVpnClientNrptEntries": False},
    ]:
        with pytest.raises(ValueError):
            validate_cleanup(invalid)


def test_query_revocation_rejects_duplicate_or_inherited_administrator_grant():
    workspace = (
        "/subscriptions/fixture/resourceGroups/fixture/providers/"
        "Microsoft.OperationalInsights/workspaces/fixture"
    )
    role_prefix = "/providers/Microsoft.Authorization/roleDefinitions/"
    assignment = workspace + "/providers/Microsoft.Authorization/roleAssignments/fixture"
    reader = {
        "id": assignment,
        "scope": workspace,
        "roleDefinitionId": role_prefix + "73c42c96-874c-492b-b04d-ab87d138a893",
    }
    validate_query_authority([reader], assignment, workspace)
    owner = {
        **reader,
        "scope": "/subscriptions/fixture",
        "roleDefinitionId": role_prefix + "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
    }
    for grants in ([reader, owner], [reader, reader], [owner], []):
        with pytest.raises(ValueError):
            validate_query_authority(grants, assignment, workspace)
