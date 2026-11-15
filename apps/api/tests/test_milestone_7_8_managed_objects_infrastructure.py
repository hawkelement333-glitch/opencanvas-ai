"""Focused D-001 deployment boundaries; compilation is local and never calls Azure."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "infra/milestone_7_8/managed_objects.bicep"


@pytest.fixture(scope="module")
def compiled() -> dict[str, Any]:
    installed = Path.home() / ".azure/bin/bicep.exe"
    compiler = os.environ.get("BICEP_EXECUTABLE") or (
        str(installed) if installed.is_file() else shutil.which("bicep")
    )
    if compiler is None:
        pytest.skip("requires an already installed local Bicep compiler")
    template_path = str(TEMPLATE)
    if sys.platform != "win32" and compiler.endswith(".exe"):
        template_path = subprocess.check_output(
            ["wslpath", "-w", template_path],
            text=True,
        ).strip()
    result = subprocess.run(
        [compiler, "build", template_path, "--stdout"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def resources(compiled: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    return [item for item in compiled["resources"] if item["type"] == resource_type]


def one(compiled: dict[str, Any], resource_type: str) -> dict[str, Any]:
    matches = resources(compiled, resource_type)
    assert len(matches) == 1
    return matches[0]


def test_storage_stays_private_and_preserves_recoverable_exact_versions(
    compiled: dict[str, Any],
) -> None:
    storage = one(compiled, "Microsoft.Storage/storageAccounts")
    assert storage["sku"] == {"name": "Standard_LRS"}
    props = storage["properties"]
    assert props["publicNetworkAccess"] == "Disabled"
    assert props["allowSharedKeyAccess"] is False
    assert props["allowBlobPublicAccess"] is False
    assert props["minimumTlsVersion"] == "TLS1_2"
    assert props["supportsHttpsTrafficOnly"] is True
    acl = props["networkAcls"]
    assert acl["bypass"] == "None" and acl["defaultAction"] == "Deny"
    assert acl["ipRules"] == acl["virtualNetworkRules"] == []
    assert "storageDataScannerResourceId" in acl["resourceAccessRules"]
    blobs = one(compiled, "Microsoft.Storage/storageAccounts/blobServices")["properties"]
    assert blobs["isVersioningEnabled"] is True
    assert blobs["deleteRetentionPolicy"] == {
        "enabled": True,
        "days": 7,
        "allowPermanentDelete": True,
    }
    assert blobs["containerDeleteRetentionPolicy"] == {"enabled": True, "days": 7}
    assert compiled["variables"]["containerNames"] == [
        "quarantine",
        "clean",
        "rejected",
        "retained",
    ]
    assert (
        one(compiled, "Microsoft.Storage/storageAccounts/blobServices/containers")["properties"][
            "publicAccess"
        ]
        == "None"
    )


def test_defender_is_account_scoped_and_private_dual_source_scanner_is_bound(
    compiled: dict[str, Any],
) -> None:
    defender = one(compiled, "Microsoft.Security/defenderForStorageSettings")
    assert "Microsoft.Storage/storageAccounts" in defender["scope"]
    props = defender["properties"]
    assert props["isEnabled"] is True and props["overrideSubscriptionLevelSettings"] is True
    assert props["sensitiveDataDiscovery"] == {"isEnabled": False}
    assert props["malwareScanning"] == {
        "blobScanResultsOptions": "blobIndexTags",
        "onUpload": {"isEnabled": True, "capGBPerMonth": 1},
    }
    assert resources(compiled, "Microsoft.Security/pricings") == []
    diagnostic = one(compiled, "Microsoft.Insights/diagnosticSettings")["properties"]
    assert diagnostic["logs"] == [{"category": "ScanResults", "enabled": True}]
    assert "Microsoft.OperationalInsights/workspaces" in diagnostic["workspaceId"]
    workspace = one(compiled, "Microsoft.OperationalInsights/workspaces")["properties"]
    assert (
        workspace["publicNetworkAccessForQuery"]
        == workspace["publicNetworkAccessForIngestion"]
        == "Disabled"
    )
    scope = one(compiled, "Microsoft.Insights/privateLinkScopes")["properties"][
        "accessModeSettings"
    ]
    assert scope == {
        "exclusions": [],
        "ingestionAccessMode": "PrivateOnly",
        "queryAccessMode": "PrivateOnly",
    }
    zones = str(compiled["variables"]["dnsNames"])
    for suffix in (
        "blob.",
        "monitor.azure.com",
        "oms.opinsights.azure.com",
        "ods.opinsights.azure.com",
        "agentsvc.azure-automation.net",
    ):
        assert suffix in zones


def test_api_worker_and_probe_use_distinct_container_scoped_permissions(
    compiled: dict[str, Any],
) -> None:
    variables = compiled["variables"]
    assert variables["identityNames"] == ["bootstrap", "api", "worker", "probe"]
    roles = {role["key"]: role["actions"] for role in variables["roleSpecs"]}
    assert len(roles["api-upload"]) == 3
    assert len(roles["api-download"]) == 1
    assert len(roles["worker-quarantine"]) == 4
    assert len(roles["worker-promote"]) == 5
    # Neither service identity can author the provider's scanner decision.
    assert not any(
        "tags/write" in action or action == "*" for values in roles.values() for action in values
    )
    assert all(
        "delete" not in action.lower()
        for key, values in roles.items()
        if key.startswith("api-")
        for action in values
    )
    assert all(
        "permanentDelete" not in action
        for key, values in roles.items()
        if key.startswith("worker-")
        for action in values
    )
    assert any("permanentDelete/action" in action for action in roles["probe-lifecycle"])
    definitions = one(compiled, "Microsoft.Authorization/roleDefinitions")
    assert definitions["properties"]["assignableScopes"] == ["[resourceGroup().id]"]
    assert "resourceGroup().id" in definitions["name"]
    assignments = resources(compiled, "Microsoft.Authorization/roleAssignments")
    blob_assignments = [item for item in assignments if "containers" in item["scope"]]
    assert len(blob_assignments) == 5  # Four service grants plus a four-container proof loop.
    assert not any("Microsoft.Storage/storageAccounts'," in item["scope"] for item in assignments)


def test_transaction_dependency_is_minimal_private_and_passwordless(
    compiled: dict[str, Any],
) -> None:
    postgres = one(compiled, "Microsoft.DBforPostgreSQL/flexibleServers")
    assert postgres["sku"] == {"name": "Standard_D2ds_v4", "tier": "GeneralPurpose"}
    props = postgres["properties"]
    assert props["version"] == "17"
    assert props["highAvailability"] == {"mode": "Disabled"}
    assert props["storage"] == {"storageSizeGB": 64, "autoGrow": "Disabled", "tier": "P6"}
    assert props["authConfig"]["passwordAuth"] == "Disabled"
    assert props["authConfig"]["activeDirectoryAuth"] == "Enabled"
    assert props["network"]["publicNetworkAccess"] == "Disabled"
    assert resources(compiled, "Microsoft.DBforPostgreSQL/flexibleServers/firewallRules") == []
    assert (
        one(compiled, "Microsoft.DBforPostgreSQL/flexibleServers/administrators")["condition"]
        == "[variables('workloadEnabled')]"
    )


def test_jobs_are_manual_private_retained_digest_and_separate_admin(
    compiled: dict[str, Any],
) -> None:
    assert compiled["parameters"]["deploymentStage"]["defaultValue"] == "foundation"
    registry = one(compiled, "Microsoft.ContainerRegistry/registries")
    assert registry["sku"] == {"name": "Premium"}
    assert registry["properties"]["adminUserEnabled"] is False
    assert registry["properties"]["publicNetworkAccess"] == "Disabled"
    environment = one(compiled, "Microsoft.App/managedEnvironments")["properties"]
    assert environment["vnetConfiguration"]["internal"] is True
    assert environment["workloadProfiles"] == [
        {"name": "Consumption", "workloadProfileType": "Consumption"}
    ]
    jobs = resources(compiled, "Microsoft.App/jobs")
    assert len(jobs) == 2
    for job in jobs:
        assert job["condition"] == "[variables('workloadEnabled')]"
        props = job["properties"]
        assert props["workloadProfileName"] == "Consumption"
        assert props["configuration"]["triggerType"] == "Manual"
        assert props["configuration"]["replicaRetryLimit"] == 0
        container = props["template"]["containers"][0]
        assert container["command"] == ["python"] and container["args"][0] == "-c"
        assert "@{1}" in container["image"] and "parameters('imageDigest')" in container["image"]
        assert container["resources"] == {"cpu": "[json('0.5')]", "memory": "1Gi"}
    bootstrap = next(job for job in jobs if "-bootstrap" in job["name"])
    probe = next(job for job in jobs if "-probe" in job["name"])
    assert len(bootstrap["identity"]["userAssignedIdentities"]) == 1
    assert len(probe["identity"]["userAssignedIdentities"]) == 3
    assert not set(bootstrap["identity"]["userAssignedIdentities"]) & set(
        probe["identity"]["userAssignedIdentities"]
    )


@pytest.mark.parametrize("tamper", [False, True])
def test_external_source_is_hash_checked_before_execution(
    compiled: dict[str, Any], tamper: bool
) -> None:
    source = 'print("bound source executed")'
    env = dict(
        os.environ,
        M78_EXECUTION_SOURCE=source + ("# changed" if tamper else ""),
        M78_EXECUTION_SHA256=hashlib.sha256(source.encode()).hexdigest(),
    )
    result = subprocess.run(
        [sys.executable, "-c", compiled["variables"]["sourceVerifier"]],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert (result.returncode == 0) is not tamper
    assert ("bound source executed" in result.stdout) is not tamper


def test_outputs_support_cleanup_readback_without_credentials_or_raw_probe(
    compiled: dict[str, Any],
) -> None:
    outputs = compiled["outputs"]
    for name in (
        "storageAccountId",
        "defenderSettingsId",
        "workspaceId",
        "registryId",
        "identityBindings",
        "customRoleDefinitionIds",
        "privateEndpointIds",
        "privateDnsZoneIds",
        "bootstrapJobName",
        "probeJobName",
    ):
        assert name in outputs
    serialized = json.dumps(outputs).lower()
    assert not any(
        term in serialized
        for term in ("listkeys", "sharedkey", "password", "token", "pythonsource")
    )
    assert compiled["parameters"]["location"]["allowedValues"] == ["canadacentral"]
    assert not any(
        resource["type"].startswith(("Microsoft.Cache/", "Microsoft.Automation/"))
        for resource in compiled["resources"]
    )


def test_compiled_outputs_have_no_unbound_copy_index(compiled: dict[str, Any]) -> None:
    def inspect(value: Any, *, output_copy_input: bool = False) -> None:
        if isinstance(value, str):
            for match in re.finditer(r"copyIndex\(([^)]*)\)", value, re.IGNORECASE):
                assert output_copy_input, "copyIndex escaped its output copy input"
                assert not match[1].strip(), "output copyIndex refers to another named loop"
        elif isinstance(value, list):
            for item in value:
                inspect(item, output_copy_input=output_copy_input)
        elif isinstance(value, dict):
            for item in value.values():
                inspect(item, output_copy_input=output_copy_input)

    for output in compiled["outputs"].values():
        if "copy" in output:
            inspect(output["copy"]["count"])
            inspect(output["copy"]["input"], output_copy_input=True)
        if "value" in output:
            inspect(output["value"])
    assignments = compiled["outputs"]["serviceStorageRoleAssignmentIds"]["value"]
    assert len(assignments) == 4
    for expression, index in zip(assignments, (0, 1, 0, 1), strict=True):
        assert expression.startswith("[extensionResourceId(")
        assert f"variables('containerNames')[{index}]" in expression


def test_workload_dependencies_do_not_inherit_container_copy_scope(
    compiled: dict[str, Any],
) -> None:
    for resource in compiled["resources"]:
        if "copy" not in resource:
            assert not any("copyIndex(" in value for value in resource.get("dependsOn", []))
    assignments = [
        assignment
        for assignment in resources(compiled, "Microsoft.Authorization/roleAssignments")
        if "copy" not in assignment
    ]
    assert len(assignments) == 4
    for assignment, container in zip(
        assignments, ("quarantine", "clean", "quarantine", "clean"), strict=True
    ):
        assert "copyIndex(" not in assignment["scope"]
        assert f"'default', '{container}'" in assignment["scope"]
        assert any(
            "Microsoft.Storage/storageAccounts/blobServices/containers" in value
            for value in assignment.get("dependsOn", [])
        )


def bootstrap_environment() -> dict[str, str]:
    return {
        "OPENCANVAS_DATABASE_URL": "postgresql+asyncpg://id-m78o-1234567890-bootstrap@pg-m78o-1234567890.postgres.database.azure.com:5432/opencanvas_objects",
        "OPENCANVAS_DATABASE_HOST": "pg-m78o-1234567890.postgres.database.azure.com",
        "OPENCANVAS_DATABASE_NAME": "opencanvas_objects",
        "OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL": "id-m78o-1234567890-probe",
        "OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID": "11111111-1111-4111-8111-111111111111",
        "OPENCANVAS_OBJECT_PROBE_BOOTSTRAP_PRINCIPAL_ID": "22222222-2222-4222-8222-222222222222",
        "OPENCANVAS_DATABASE_AUTH_MODE": "entra",
        "OPENCANVAS_DATABASE_TLS_MODE": "verify-full",
        "OPENCANVAS_DATABASE_ROLE": "migration",
        "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
    }


def test_bootstrap_exact_target_is_validated_before_network_access() -> None:
    from infra.milestone_7_8.managed_objects_bootstrap import bound_configuration

    binding = bound_configuration(bootstrap_environment())
    assert binding["principal"] == "id-m78o-1234567890-probe"
    assert binding["administrator"] == "id-m78o-1234567890-bootstrap"
    for key, wrong in (
        ("OPENCANVAS_DATABASE_HOST", "old-campaign.postgres.database.azure.com"),
        ("OPENCANVAS_DATABASE_TLS_MODE", "require"),
        ("OPENCANVAS_DATABASE_AUTH_MODE", "password"),
        ("PGSSLROOTCERT", "/tmp/unreviewed-ca.pem"),
        ("OPENCANVAS_DATABASE_NAME", "opencanvas"),
        ("OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL", "id-other-campaign-probe"),
        ("OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID", "22222222-2222-4222-8222-222222222222"),
    ):
        with pytest.raises(RuntimeError):
            bound_configuration(dict(bootstrap_environment(), **{key: wrong}))


def test_probe_secrets_use_secure_parameter_and_job_secret_configuration(
    compiled: dict[str, Any],
) -> None:
    assert compiled["parameters"]["probeSecrets"] == {"type": "secureObject", "defaultValue": {}}
    jobs = resources(compiled, "Microsoft.App/jobs")
    probe = next(job for job in jobs if "-probe" in job["name"])
    bootstrap = next(job for job in jobs if "-bootstrap" in job["name"])
    configuration = probe["properties"]["configuration"]
    copies = configuration["copy"]
    secret_copy = next(copy for copy in copies if copy["name"] == "secrets")
    assert "items(parameters('probeSecrets'))" in secret_copy["count"]
    assert "items(parameters('probeSecrets'))" in secret_copy["input"]["value"]
    container = probe["properties"]["template"]["containers"][0]
    # Caller-supplied secretRef entries are preserved as objects by concat;
    # the secret values only occur in secure parameters and job configuration.
    assert "parameters('probeEnvironment')" in container["env"]
    assert "probeSecrets" not in container["env"]
    assert "probeSecrets" not in json.dumps(bootstrap)
    assert "probeSecrets" not in json.dumps(compiled["outputs"])


def test_bootstrap_grants_runtime_only_existing_table_inventory_and_append_only_journal() -> None:
    from infra.milestone_7_8.managed_objects_bootstrap import fixture_grants

    statements = fixture_grants("id-m78o-1234567890-probe")
    grants = [statement for statement in statements if statement.startswith("GRANT")]
    assert not any("GRANT ALL" in statement or "GRANT CREATE" in statement for statement in grants)
    assert not any("ON ALL TABLES" in statement for statement in grants)
    journal = [statement for statement in grants if "receipts" in statement]
    assert journal == [
        'GRANT SELECT, INSERT ON m78_object_probe.receipts TO "id-m78o-1234567890-probe"'
    ]
    assert any('public."object_deletion_requests"' in statement for statement in grants)
    assert not any("application_errors" in statement for statement in grants)


def test_bootstrap_rejects_public_and_loopback_dns_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.milestone_7_8 import managed_objects_bootstrap as bootstrap

    for address in ("8.8.8.8", "127.0.0.1", "169.254.169.254"):
        monkeypatch.setattr(
            bootstrap.socket,
            "getaddrinfo",
            lambda *a, address=address, **kw: [(None, None, None, None, (address, 5432))],
        )
        with pytest.raises(RuntimeError, match="DNS is not private"):
            bootstrap.require_private_host("pg-m78o-1234567890.postgres.database.azure.com")


def test_retained_image_composes_external_sources_without_network(
    compiled: dict[str, Any],
) -> None:
    image = os.environ.get("M78_COMPOSITION_IMAGE")
    if image is None:
        pytest.skip("explicit retained local image required for the focused composition check")
    assert image.startswith("sha256:") and len(image) == 71
    docker = os.environ.get("DOCKER_EXECUTABLE") or shutil.which("docker")
    assert docker is not None, "already installed Docker is required"
    source_directory = str(ROOT / "infra/milestone_7_8")
    if sys.platform != "win32" and docker.endswith(".exe"):
        source_directory = subprocess.check_output(
            ["wslpath", "-w", source_directory],
            text=True,
        ).strip()
    binding_path = os.environ.get("M78_COMPOSITION_BINDINGS")
    prepared_environment = {}
    if binding_path is not None:
        prepared = json.loads(Path(binding_path).read_text())
        prepared_environment = {
            item["name"]: item["value"] for item in prepared["probeEnvironment"] if "value" in item
        }
        assert {
            item["secretRef"] for item in prepared["probeEnvironment"] if "secretRef" in item
        } == {"upload-capability", "scanner-result"}
    program = textwrap.dedent("""
        import asyncio, hashlib, json, os, pathlib, runpy, secrets, subprocess, sys
        env = {
            "OPENCANVAS_APP_MODE": "development",
            "OPENCANVAS_AI_PROVIDER": "mock", "OPENCANVAS_EMBEDDING_PROVIDER": "mock",
            "OPENCANVAS_DATABASE_URL": "postgresql+asyncpg://id-m78o-1234567890-probe@pg-m78o-1234567890.postgres.database.azure.com:5432/opencanvas_objects",
            "OPENCANVAS_DATABASE_HOST": "pg-m78o-1234567890.postgres.database.azure.com",
            "OPENCANVAS_DATABASE_NAME": "opencanvas_objects",
            "OPENCANVAS_DATABASE_ROLE": "api", "OPENCANVAS_DATABASE_AUTH_MODE": "entra",
            "OPENCANVAS_DATABASE_TLS_MODE": "verify-full",
            "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID":
                "33333333-3333-4333-8333-333333333333",
            "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
            "OPENCANVAS_STORAGE_PROVIDER": "azure",
            "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL": "https://stm78o1234567890.blob.core.windows.net",
            "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID": "33333333-3333-4333-8333-333333333333",
            "OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID": "44444444-4444-4444-8444-444444444444",
            "IDENTITY_ENDPOINT": "http://127.0.0.1:42356/msi/token",
            "IDENTITY_HEADER": "synthetic-network-disabled-composition",
            "OPENCANVAS_OBJECT_INGESTION_MODE": "trusted",
            "OPENCANVAS_SCANNER_RESULT_BRIDGE_MODE": "private_pull",
            "OPENCANVAS_MALWARE_SCANNER_IDENTITY": "azure-defender-for-storage",
            "OPENCANVAS_MALWARE_SCANNER_VERSION": "defender-storage-dual-source-v1",
            "OPENCANVAS_UPLOAD_CAPABILITY_SECRET": secrets.token_hex(32),
            "OPENCANVAS_SCANNER_RESULT_SECRET": secrets.token_hex(32),
            "OPENCANVAS_OBJECT_PROBE_CAMPAIGN": "55555555-5555-4555-8555-555555555555",
            "OPENCANVAS_OBJECT_PROBE_API_CLIENT_ID": "11111111-1111-4111-8111-111111111111",
            "OPENCANVAS_OBJECT_PROBE_WORKER_CLIENT_ID": "22222222-2222-4222-8222-222222222222",
            "OPENCANVAS_OBJECT_PROBE_RECOVERY_CLIENT_ID": "33333333-3333-4333-8333-333333333333",
            "OPENCANVAS_OBJECT_PROBE_IMAGE_DIGEST": "sha256:" + "a" * 64,
            "OPENCANVAS_OBJECT_PROBE_SOURCE_COMMIT": "b" * 40,
            "OPENCANVAS_OBJECT_PROBE_PHASE": "setup",
            "CONTAINER_APP_JOB_EXECUTION_NAME": "local-network-disabled-composition",
        }
        source = pathlib.Path("/m78-source/managed_object_probe.py").read_text()
        env["OPENCANVAS_OBJECT_PROBE_SHA256"] = hashlib.sha256(source.encode()).hexdigest()
        os.environ.update(env)
        probe_module = runpy.run_path("/m78-source/managed_object_probe.py", run_name="composition")
        bootstrap_module = runpy.run_path(
            "/m78-source/managed_objects_bootstrap.py", run_name="composition")
        settings = probe_module["Settings"]()
        database = probe_module["Database"].from_settings(
            settings, expected_role=probe_module["DatabaseRole"].API)
        probe = probe_module["Probe"](settings, database)
        assert probe.api is not probe.worker
        assert settings.malware_scan_timeout_seconds == 300
        assert settings.database_tls_mode == "verify-full"
        asyncio.run(database.dispose())
    """)
    program = program.replace(
        "os.environ.update(env)",
        "env.update(" + repr(prepared_environment) + ")\nos.environ.update(env)",
    )
    program += "\nbootstrap_module['bound_configuration'](" + repr(bootstrap_environment()) + ")\n"
    program += "verifier = " + repr(compiled["variables"]["sourceVerifier"]) + "\n"
    program += textwrap.dedent("""
        for path in ("managed_object_probe.py", "managed_objects_bootstrap.py"):
            source = pathlib.Path("/m78-source", path).read_text()
            execution_env = dict(os.environ, M78_EXECUTION_SOURCE=source,
                                 M78_EXECUTION_SHA256=hashlib.sha256(source.encode()).hexdigest())
            subprocess.run([sys.executable, "-c", "__name__='composition_hash_bound';" + verifier],
                           env=execution_env, check=True)
        print("M78_RETAINED_COMPOSITION accepted")
    """)
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "-i",
            "--mount",
            f"type=bind,source={source_directory},target=/m78-source,readonly",
            "--entrypoint",
            "python",
            image,
            "-",
        ],
        input=program,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "M78_RETAINED_COMPOSITION accepted"
