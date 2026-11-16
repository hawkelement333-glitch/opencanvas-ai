"""D-002 deployment boundaries; local compilation only, never Azure access."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "infra/milestone_7_8/managed_redis.bicep"


@pytest.fixture(scope="module")
def compiled() -> dict[str, Any]:
    installed = Path.home() / ".azure/bin/bicep.exe"
    compiler = os.environ.get("BICEP_EXECUTABLE") or (
        str(installed) if installed.is_file() else shutil.which("bicep")
    )
    if compiler is None:
        pytest.skip("requires an already installed local Bicep compiler")
    path = str(TEMPLATE)
    if sys.platform != "win32" and compiler.endswith(".exe"):
        path = subprocess.check_output(["wslpath", "-w", path], text=True).strip()
    result = subprocess.run(
        [compiler, "build", path, "--stdout"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def one(compiled: dict[str, Any], kind: str) -> dict[str, Any]:
    found = [item for item in compiled["resources"] if item["type"] == kind]
    assert len(found) == 1
    return found[0]


def test_managed_redis_is_private_entra_only_ha_and_fixed_size(compiled):
    cache = one(compiled, "Microsoft.Cache/redisEnterprise")
    assert cache["sku"] == {"name": "Balanced_B0"}
    assert cache["properties"] == {
        "minimumTlsVersion": "1.2",
        "highAvailability": "Enabled",
        "publicNetworkAccess": "Disabled",
    }
    assert compiled["parameters"]["location"]["allowedValues"] == ["canadacentral"]
    assert one(compiled, "Microsoft.Cache/redisEnterprise/databases")["properties"] == {
        "accessKeysAuthentication": "Disabled",
        "clientProtocol": "Encrypted",
        "clusteringPolicy": "NoCluster",
        "evictionPolicy": "NoEviction",
        "modules": [],
        "port": 10000,
    }


def test_acl_matches_actual_limiter_keys_and_only_probe_commands(compiled):
    acl = compiled["variables"]["redisAccessString"]
    expected_commands = (
        "ping",
        "eval",
        "time",
        "hmget",
        "hset",
        "pexpire",
        "get",
        "set",
        "pttl",
        "exists",
    )
    assert set(re.findall(r"\+([a-z]+)", acl)) == set(expected_commands)
    assert "+@" not in acl and "~*" not in acl and "mobius:v1" not in acl
    assert ":rl:v1:{{limits}}:*" in acl and ":control:{{limits}}:*" in acl
    assignment = one(compiled, "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments")
    assert assignment["properties"]["accessString"] == "[variables('redisAccessString')]"
    assert "principalId" in assignment["properties"]["user"]["objectId"]
    assert compiled["variables"]["replicas"] == ["leader", "follower"]


def test_dependencies_exclude_closed_campaigns_and_external_telemetry(compiled):
    types = {resource["type"] for resource in compiled["resources"]}
    assert not any(
        resource_type.startswith(prefix)
        for resource_type in types
        for prefix in (
            "Microsoft.DBforPostgreSQL/",
            "Microsoft.Storage/",
            "Microsoft.Security/",
            "Microsoft.OperationalInsights/",
            "Microsoft.Automation/",
            "Microsoft.Authorization/roleDefinitions",
        )
    )
    environment = one(compiled, "Microsoft.App/managedEnvironments")["properties"]
    assert environment["appLogsConfiguration"] == {"destination": "none"}
    assert environment["vnetConfiguration"]["internal"] is True
    assert environment["workloadProfiles"] == [
        {"name": "Consumption", "workloadProfileType": "Consumption"}
    ]
    nsg = one(compiled, "Microsoft.Network/networkSecurityGroups")
    assert nsg["properties"]["securityRules"] == []
    subnets = one(compiled, "Microsoft.Network/virtualNetworks")["properties"]["subnets"]
    assert len(subnets) == 2
    assert "networkSecurityGroup" in subnets[0]["properties"]
    assert subnets[1]["properties"]["privateEndpointNetworkPolicies"] == "Disabled"
    assert compiled["variables"]["dnsNames"] == [
        "privatelink.redis.azure.net",
        "privatelink.azurecr.io",
    ]


def test_jobs_are_independent_manual_source_bound_and_have_no_shared_credentials(compiled):
    jobs = one(compiled, "Microsoft.App/jobs")
    assert jobs["condition"] == "[variables('workloadEnabled')]"
    assert jobs["copy"]["count"] == "[length(variables('replicas'))]"
    assert len(jobs["identity"]["userAssignedIdentities"]) == 1
    config = jobs["properties"]["configuration"]
    assert config["triggerType"] == "Manual" and config["replicaRetryLimit"] == 0
    assert config["manualTriggerConfig"] == {"parallelism": 1, "replicaCompletionCount": 1}
    assert config["replicaTimeout"] == 1200
    assert compiled["parameters"]["hmacSecret"]["type"].lower() == "securestring"
    assert config["secrets"] == [{"name": "rate-limit-hmac", "value": "[parameters('hmacSecret')]"}]
    container = jobs["properties"]["template"]["containers"][0]
    assert container["resources"] == {"cpu": "[json('0.5')]", "memory": "1Gi"}
    assert "@{1}" in container["image"] and "parameters('imageDigest')" in container["image"]
    assert container["command"] == ["python"]
    verifier = compiled["variables"]["sourceVerifier"]
    assert "hmac.compare_digest" in verifier and "hashlib.sha256" in verifier
    assert verifier.index("hmac.compare_digest") < verifier.index("exec(compile")
    env = container["env"]
    assert "OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_CLIENT_ID" in env
    assert "OPENCANVAS_REDIS_PROBE_REPLICA" in env
    assert "OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET" in env
    assert "secretRef" in env and "rate-limit-hmac" in env
    assert "rediss://" in env and "principalId" in env


def test_registry_private_pull_is_the_only_arm_workload_grant(compiled):
    registry = one(compiled, "Microsoft.ContainerRegistry/registries")
    assert registry["sku"] == {"name": "Premium"}
    assert registry["properties"]["publicNetworkAccess"] == "Disabled"
    assert registry["properties"]["adminUserEnabled"] is False
    role = one(compiled, "Microsoft.Authorization/roleAssignments")
    assert role["scope"].startswith("[resourceId('Microsoft.ContainerRegistry/registries',")
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in compiled["variables"]["acrPullRoleId"]
    assert role["properties"]["principalType"] == "ServicePrincipal"


def test_outputs_have_no_unbound_resource_loop_indices_or_secrets(compiled):
    def inspect(value, in_output_copy=False):
        if isinstance(value, str):
            for match in re.finditer(r"copyIndex\(([^)]*)\)", value, re.IGNORECASE):
                assert in_output_copy and not match[1].strip()
        elif isinstance(value, list):
            for item in value:
                inspect(item, in_output_copy)
        elif isinstance(value, dict):
            for item in value.values():
                inspect(item, in_output_copy)

    for output in compiled["outputs"].values():
        if "copy" in output:
            inspect(output["copy"]["count"])
            inspect(output["copy"]["input"], True)
        if "value" in output:
            inspect(output["value"])
    outputs = json.dumps(compiled["outputs"])
    assert "hmacSecret" not in outputs and "probeSource" not in outputs
    assert {
        "redisId",
        "identityBindings",
        "endpointIds",
        "privateDnsZoneIds",
        "nsgId",
        "environmentId",
    } <= compiled["outputs"].keys()
