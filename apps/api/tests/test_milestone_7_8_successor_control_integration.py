"""Regressions for native successor admission failures; no cloud calls."""

import json
import os
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from infra.milestone_7_8.operator_access_package import configure_client_profile
from opencanvas_api.core.config import DatabaseRole

NATIVE = "http://schemas.datacontract.org/2004/07/"
TENANT = "11111111-1111-4111-8111-111111111111"
AUDIENCE = "22222222-2222-4222-8222-222222222222"


def native_profile():
    return f"""<AzVpnProfile xmlns="{NATIVE}"
      xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <clientauth><aad><audience>{AUDIENCE}</audience>
      <tenant>https://login.microsoftonline.com/{TENANT}/</tenant>
      <issuer>https://sts.windows.net/{TENANT}/</issuer></aad></clientauth>
      <serverlist><ServerEntry><fqdn>fixture.vpn.azure.com</fqdn></ServerEntry></serverlist>
      <servervalidation><cert><hash>fixture-native-pin</hash></cert></servervalidation>
      <clientconfig i:nil="true" /></AzVpnProfile>""".encode()


def test_native_datacontract_namespace_and_server_trust_are_preserved():
    original = ET.fromstring(native_profile())
    configured = ET.fromstring(
        configure_client_profile(
            native_profile(), TENANT, AUDIENCE, "fixture.vpn.azure.com", [".blob.core.windows.net"]
        )
    )

    def path(value):
        return "/".join("{" + NATIVE + "}" + part for part in value.split("/"))

    assert configured.tag == original.tag
    for element in ("servervalidation", "serverlist"):
        assert ET.tostring(configured.find(path(element))) == ET.tostring(
            original.find(path(element))
        )
    assert configured.findtext(path("clientconfig/dnsservers/dnsserver")) == "10.79.9.36"
    assert configured.findtext(path("clientconfig/includeroutes/route/destination")) == "10.79.0.0"
    assert configured.findtext(path("clientconfig/includeroutes/route/mask")) == "16"
    assert not configured.find(path("clientconfig")).attrib
    for tenant, audience, host in [
        (AUDIENCE, AUDIENCE, "fixture.vpn.azure.com"),
        (TENANT, TENANT, "fixture.vpn.azure.com"),
        (TENANT, AUDIENCE, "wrong.vpn.azure.com"),
    ]:
        with pytest.raises(ValueError):
            configure_client_profile(
                native_profile(), tenant, audience, host, [".blob.core.windows.net"]
            )


def test_foreign_or_mixed_native_namespaces_are_rejected():
    for value in [
        native_profile().replace(NATIVE.encode(), b"https://untrusted.invalid/"),
        native_profile().replace(b"<audience>", b'<audience xmlns="https://untrusted.invalid/">'),
    ]:
        with pytest.raises(ValueError):
            configure_client_profile(
                value, TENANT, AUDIENCE, "fixture.vpn.azure.com", [".blob.core.windows.net"]
            )


def test_compiled_bootstrap_job_admits_the_existing_provisioning_entrypoint():
    root = Path(__file__).resolve().parents[3]
    compiler = os.environ.get("BICEP_EXECUTABLE") or str(Path.home() / ".azure/bin/bicep.exe")
    result = subprocess.run(
        [compiler, "build", str(root / "infra/milestone_7_8/pilot.bicep"), "--stdout"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    compiled = json.loads(result.stdout)
    runtime = next(
        r["properties"]["template"]
        for r in compiled["resources"]
        if r["type"] == "Microsoft.Resources/deployments" and "runtime" in r["name"]
    )
    specs = {row["role"]: row for row in runtime["variables"]["jobSpecs"]}
    assert specs["bootstrap"]["command"] == ["python", "-m", "scripts.bootstrap_postgres"]
    assert DatabaseRole(specs["bootstrap"]["databaseRole"]) is DatabaseRole.PROVISIONING
    assert specs["bootstrap"]["identityRole"] == "bootstrap"
    assert DatabaseRole(specs["migration"]["databaseRole"]) is DatabaseRole.MIGRATION
    assert specs["migration"]["identityRole"] == "migration"
