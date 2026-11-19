"""Compile only the changed pilot composition; never calls Azure."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def compiled() -> dict:
    installed = Path.home() / ".azure/bin/bicep.exe"
    compiler = os.environ.get("BICEP_EXECUTABLE") or (
        str(installed) if installed.is_file() else shutil.which("bicep")
    )
    assert compiler, "Local Bicep compiler is required for prepared execution inputs"
    result = subprocess.run(
        [compiler, "build", str(ROOT / "infra/milestone_7_8/pilot.bicep"), "--stdout"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def resource(template: dict, kind: str) -> dict:
    found = [item for item in template["resources"] if item["type"] == kind]
    assert len(found) == 1
    return found[0]


def nested(template: dict, suffix: str) -> dict:
    return next(
        item
        for item in template["resources"]
        if item["type"] == "Microsoft.Resources/deployments" and suffix in item["name"]
    )


def test_foundation_reuses_private_dependencies_without_replaying_closed_jobs(
    compiled: dict,
) -> None:
    foundation = nested(compiled, "foundation")
    inputs = foundation["properties"]["parameters"]
    assert inputs["deploymentStage"]["value"] == "foundation"
    assert inputs["postgresStorageGiB"]["value"] == 32
    assert inputs["applicationDatabaseName"]["value"] == "opencanvas"
    assert inputs["pilotDestinationPrivacy"]["value"] is True
    assert compiled["parameters"]["stage"]["defaultValue"] == "foundation"
    assert compiled["parameters"]["location"]["allowedValues"] == ["eastus", "canadacentral"]
    redis = resource(compiled, "Microsoft.Cache/redisEnterprise")
    assert redis["location"] == "[parameters('redisLocation')]"
    assert compiled["parameters"]["redisLocation"]["allowedValues"] == ["eastus", "canadacentral"]
    assert redis["sku"]["name"] == "Balanced_B0"
    assert redis["properties"]["highAvailability"] == "Enabled"
    assert redis["properties"]["publicNetworkAccess"] == "Disabled"


def test_scanner_cannot_query_application_telemetry_or_modify_scan_tags(compiled: dict) -> None:
    foundation = nested(compiled, "foundation")["properties"]["template"]
    roles = [
        item
        for item in foundation["resources"]
        if item["type"] == "Microsoft.Authorization/roleDefinitions"
    ]
    scanner = next(item for item in roles if "pilot-scanner-table-query" in item["name"])
    assert scanner["condition"] == "[parameters('pilotDestinationPrivacy')]"
    assert scanner["properties"]["permissions"][0]["actions"] == [
        "Microsoft.OperationalInsights/workspaces/read",
        "Microsoft.OperationalInsights/workspaces/query/StorageMalwareScanningResults/read",
    ]
    assert scanner["properties"]["permissions"][0]["dataActions"] == []
    assert "tags/write" not in str(foundation["variables"]["roleSpecs"])


def test_application_uses_exact_candidate_and_scanner_policy_without_public_ingress(
    compiled: dict,
) -> None:
    runtime = nested(compiled, "runtime")["properties"]["template"]
    common = {item["name"]: item["value"] for item in runtime["variables"]["commonBase"]}
    assert "variables('commonBase')" in runtime["variables"]["common"]
    assert common["OPENCANVAS_APP_MODE"] == "staging"
    assert common["OPENCANVAS_AUTH_TEST_BYPASS"] == "false"
    assert common["OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS"] == "900"
    assert common["OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS"] == "20"
    assert common["OPENCANVAS_UPLOAD_CAPABILITY_TTL_SECONDS"] == "300"
    assert common["OPENCANVAS_INDEXER_PUBLICATION_MODE"] == "private_clean"
    assert common["OPENCANVAS_JOB_PROVIDER"] == "database"
    assert common["OPENCANVAS_AI_PROVIDER"] == common["OPENCANVAS_EMBEDDING_PROVIDER"] == "openai"
    assert common["OPENCANVAS_TELEMETRY_EXPORT_TIMEOUT_SECONDS"] == "5"
    applications = [
        item for item in runtime["resources"] if item["type"] == "Microsoft.App/containerApps"
    ]
    assert len(applications) == 3  # API+worker copy, gateway, frontend.
    for application in applications:
        assert application["condition"] == "[parameters('applicationEnabled')]"
        assert "environmentId" in application["properties"]["managedEnvironmentId"]
        image = application["properties"]["template"]["containers"][0]["image"]
        assert "@{1}" in image
        assert "ImageDigest" in image
    # external=true is private-VNet ingress because the shared ACA environment is internal.
    foundation = nested(compiled, "foundation")["properties"]["template"]
    assert (
        resource(foundation, "Microsoft.App/managedEnvironments")["properties"][
            "vnetConfiguration"
        ]["internal"]
        is True
    )


def test_jobs_are_manual_and_secrets_are_bound_to_individual_consumers(compiled: dict) -> None:
    runtime = nested(compiled, "runtime")["properties"]["template"]
    job = resource(runtime, "Microsoft.App/jobs")
    configuration = job["properties"]["configuration"]
    assert configuration["triggerType"] == "Manual"
    assert configuration["replicaRetryLimit"] == 0
    assert configuration["manualTriggerConfig"] == {"parallelism": 1, "replicaCompletionCount": 1}
    assert [item["role"] for item in runtime["variables"]["jobSpecs"]] == [
        "artifact",
        "bootstrap",
        "migration",
        "evidence",
    ]
    assert compiled["parameters"]["applicationSecrets"]["type"] == "secureObject"
    grants = [
        item
        for item in compiled["resources"]
        if item["type"] == "Microsoft.Authorization/roleAssignments"
        and "secret-read" in item["name"]
    ]
    assert len(grants) == 1 and "Microsoft.KeyVault/vaults/secrets" in grants[0]["scope"]
    vault = resource(compiled, "Microsoft.KeyVault/vaults")["properties"]
    assert vault["publicNetworkAccess"] == "Disabled"
    assert vault["enableSoftDelete"] is True and vault.get("enablePurgeProtection", False) is False


def test_common_runtime_environment_names_are_typed_settings(compiled: dict) -> None:
    from opencanvas_api.core.config import Settings

    runtime = nested(compiled, "runtime")["properties"]["template"]
    for item in runtime["variables"]["commonBase"] + runtime["variables"]["secretEnvironment"]:
        name = item["name"]
        if name in {"OPENAI_API_KEY", "PGSSLROOTCERT", "OPENCANVAS_TELEMETRY_AUTH_TOKEN"}:
            continue
        assert name.startswith("OPENCANVAS_")
        assert name.removeprefix("OPENCANVAS_").lower() in Settings.model_fields, name


def test_optional_api_limit_and_migration_proof_preserve_explicit_authority(compiled: dict) -> None:
    runtime = nested(compiled, "runtime")["properties"]["template"]
    assert compiled["parameters"]["apiRequestConcurrencyLimit"]["defaultValue"] == 0
    assert "OPENCANVAS_API_REQUEST_CONCURRENCY_LIMIT" in runtime["variables"]["common"]
    assert "migration" in compiled["parameters"]["proofRole"]["allowedValues"]
    job = resource(runtime, "Microsoft.App/jobs")
    secrets = job["properties"]["configuration"]["secrets"]
    assert "not(equals(parameters('proofRole'), 'migration'))" in secrets
    env = job["properties"]["template"]["containers"][0]["env"]
    assert "if(equals(parameters('proofRole'), 'migration'), parameters('proofEnvironment')" in env
    assert compiled["parameters"]["openaiModel"]["allowedValues"] == ["gpt-5.6-terra"]
