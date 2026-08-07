from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT = REPO_ROOT / "infra" / "milestone_7_7"
SCRIPTS = ROOT / "scripts"
MANIFESTS = ROOT / "manifests"
POLICIES = ROOT / "policies"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


contract = _load_module("milestone_7_7_contract_validation", SCRIPTS / "contract_validation.py")


def _json(path: Path):
    return contract.load_json(path)


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _resolved_cost(expected: int = 8000, base_maximum: int = 8000):
    value = _json(MANIFESTS / "cost-envelope.template.json")
    contingency = (base_maximum * 2500 + 9999) // 10000
    value.update(
        {
            "resolutionStatus": "verified",
            "expectedUsdCents": expected,
            "baseMaximumUsdCents": base_maximum,
            "contingencyUsdCents": contingency,
            "maximumPlausibleUsdCents": base_maximum + contingency,
            "lineItems": [
                {
                    "name": "complete-isolated-environment",
                    "expectedUsdCents": expected,
                    "baseMaximumUsdCents": base_maximum,
                    "priceEvidenceStatus": "verified-official-retail",
                }
            ],
        }
    )
    return value


def _resolved_environment():
    value = _json(MANIFESTS / "environment.template.json")
    value["resolutionStatus"] = "verified"
    value["location"] = "verifiedregion"
    value["lifecycle"].update(
        {
            "provisioningStartedAtUtc": "2026-07-30T00:00:00Z",
            "leaseExpiresAtUtc": "2026-07-31T06:00:00Z",
            "cleanupReserveStartsAtUtc": "2026-07-31T04:30:00Z",
            "cleanupBindingSha256": "a" * 64,
            "cleanupTimerVerifiedAtUtc": "2026-07-29T23:59:00Z",
        }
    )
    return value


def _synthetic_scope(resource_group: str, subscription_int: int = 1) -> str:
    subscription = str(UUID(int=subscription_int))
    return f"/subscriptions/{subscription}/resourceGroups/{resource_group}"


def _run_script(path: Path, *args: str, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-B", str(path), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_bundle_contract_is_valid_and_deterministic():
    first = contract.validate_bundle(ROOT)
    second = contract.validate_bundle(ROOT)
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first["bundleSha256"])
    assert first["files"] == sorted(first["files"], key=lambda item: item["path"])


def test_container_apps_private_dns_uses_exact_arm_record_property_casing():
    module = (ROOT / "modules" / "container-apps-dns.bicep").read_text(encoding="utf-8")
    assert "    ttl: 60" in module
    assert "    aRecords: [" in module
    assert "    TTL:" not in module
    assert "    ARecords:" not in module


def test_dynamic_contract_loader_never_writes_inside_the_bundle(tmp_path: Path):
    source = SCRIPTS / "contract_validation.py"
    copied = tmp_path / source.name
    shutil.copy2(source, copied)
    module_name = "milestone_7_7_no_bytecode_probe"
    try:
        _load_module(module_name, copied)
    finally:
        sys.modules.pop(module_name, None)
    assert not (tmp_path / "__pycache__").exists()


def test_schema_inventory_is_exact_versioned_and_closed():
    schemas = sorted(path.name for path in MANIFESTS.glob("*.schema.json"))
    assert schemas == [
        "cost-envelope.schema.json",
        "environment.schema.json",
        "image-digests.schema.json",
        "managed-binding.schema.json",
        "scanner-result-bridge.schema.json",
    ]
    for path in MANIFESTS.glob("*.schema.json"):
        schema = _json(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].startswith("urn:solarplexus:mobius:milestone-7.7:")
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "schema_name",
    [
        "cost-envelope.schema.json",
        "environment.schema.json",
        "image-digests.schema.json",
    ],
)
def test_every_schema_is_checksum_closed(schema_name: str, tmp_path: Path):
    copied = tmp_path / "bundle"
    shutil.copytree(ROOT, copied)
    path = copied / "manifests" / schema_name
    value = _json(path)
    value["title"] += " mutated"
    _write_json(path, value)
    with pytest.raises(contract.ContractError, match="reviewed closed contract"):
        contract.validate_bundle(copied)


def test_schema_parser_rejects_duplicate_keys_unknown_fields_and_nonfinite_values():
    with pytest.raises(contract.ContractError, match="duplicate JSON key"):
        contract.loads_json('{"one":1,"one":2}')
    with pytest.raises(contract.ContractError, match="non-finite"):
        contract.loads_json('{"one":NaN}')
    schema = _json(MANIFESTS / "environment.schema.json")
    value = _json(MANIFESTS / "environment.template.json")
    value["unexpected"] = True
    with pytest.raises(contract.ContractError, match="unknown field"):
        contract.validate_schema_subset(value, schema)


def test_environment_is_unresolved_private_and_fixed():
    value = _json(MANIFESTS / "environment.template.json")
    assert value["resolutionStatus"] == "unresolved"
    assert value["location"] is None
    assert value["provisioningAuthorized"] is False
    assert value["dataClassification"] == "isolated-synthetic"
    assert value["compute"] == {
        "topology": "internal-azure-container-apps",
        "workloadProfile": "Consumption",
        "externalIngress": False,
        "fixedReplicaLimits": True,
        "infrastructureResourceGroupIntegritySha256": (
            "491ca1d28b3f8ce1f822f276f534a7b5a26a0215632d0e4324968d955e5a9d47"
        ),
        "infrastructureResourceGroupName": (
            "rg-solarplexus-mobius-77-containerapps-infrastructure"
        ),
        "publicIpAllowed": False,
    }
    assert value["network"]["defaultInbound"] == "deny"
    assert value["network"]["defaultOutbound"] == "deny"
    assert value["network"]["applicationAndDataPublicNetworkAccess"] is False
    assert value["capacity"]["mutableSkuSelection"] is False
    assert value["capacity"]["mutableReplicaSelection"] is False
    contract._validate_environment(value)


def test_environment_resolution_fails_closed():
    value = _json(MANIFESTS / "environment.template.json")
    value["location"] = "assumedregion"
    with pytest.raises(contract.ContractError, match="must not select"):
        contract._validate_environment(value)
    value["resolutionStatus"] = "verified"
    value["location"] = None
    with pytest.raises(contract.ContractError, match="requires one explicit"):
        contract._validate_environment(value)


def test_environment_rejects_non_rfc1918_or_drifting_address_plan():
    value = _json(MANIFESTS / "environment.template.json")
    value["network"].update(
        {
            "vnetCidr": "8.0.0.0/8",
            "containerAppsCidr": "8.0.0.0/23",
            "privateEndpointsCidr": "8.0.2.0/24",
            "managementCleanupCidr": "8.0.3.0/28",
            "gatewayCidr": "8.0.3.32/27",
            "azureFirewallCidr": "8.0.4.0/26",
            "azureFirewallManagementCidr": "8.0.4.64/26",
        }
    )
    with pytest.raises(contract.ContractError, match="address plan differs"):
        contract._validate_environment(value)


def test_verified_environment_requires_exact_bounded_lease():
    contract._validate_environment(_resolved_environment())
    value = _resolved_environment()
    value["lifecycle"]["leaseExpiresAtUtc"] = "2026-07-31T06:00:01Z"
    with pytest.raises(contract.ContractError, match="30-hour"):
        contract._validate_environment(value)
    value = _resolved_environment()
    value["lifecycle"]["cleanupReserveStartsAtUtc"] = "2026-07-31T04:30:01Z"
    with pytest.raises(contract.ContractError, match="90-minute"):
        contract._validate_environment(value)
    value = _resolved_environment()
    value["lifecycle"]["cleanupTimerVerifiedAtUtc"] = "2026-07-30T00:00:00Z"
    with pytest.raises(contract.ContractError, match="before provisioning"):
        contract._validate_environment(value)


def test_bicep_preserves_inert_defaults_and_gates_one_run_resources():
    bicep_files = sorted(ROOT.rglob("*.bicep"))
    assert len(bicep_files) == 14
    combined = "\n".join(path.read_text(encoding="utf-8") for path in bicep_files)
    assert not re.search(r"\b(?:utcNow|newGuid|uniqueString)\s*\(", combined)
    assert not re.search(r"\b(?:subscription|resourceGroup)\s*\(\s*\)", combined)
    declarations = re.findall(r"(?m)^\s*(?:resource|module)\s+[^\n]+", combined)
    assert declarations
    assert all("= if (" in declaration for declaration in declarations)
    for name in ("policy.bicep",):
        text = (ROOT / "modules" / name).read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*(?:resource|module)\s+", text)
    for name in (
        "postgres.bicep",
        "redis.bicep",
        "storage-scanner.bicep",
    ):
        text = (ROOT / "modules" / name).read_text(encoding="utf-8")
        declarations = re.findall(r"(?m)^\s*(?:resource|module)\s+[^\n]+", text)
        assert declarations
        assert all("= if (enabled)" in declaration for declaration in declarations)
    scanner_bridge = (ROOT / "modules" / "scanner-result-bridge.bicep").read_text(encoding="utf-8")
    scanner_declarations = re.findall(r"(?m)^\s*(?:resource|module)\s+[^\n]+", scanner_bridge)
    assert scanner_declarations
    assert all(
        "= if (enabled)" in declaration or "= if (proofEnabled)" in declaration
        for declaration in scanner_declarations
    )
    main = (ROOT / "main.bicep").read_text(encoding="utf-8")
    assert "param checkpointMode string = 'contract-only'" in main
    assert "param deploymentEnabled bool = false" in main
    assert "param managedBindingDeploymentEnabled bool = false" in main
    assert "var oneRunEnabled = managedBindingMode == 'managed-binding-one-run'" in main
    assert "output defaultProvisioningAuthorized bool = false" in main
    assert "output secretValueAccessAuthorized bool = false" in main
    assert "output deploymentEnabled bool = postSecretEnabled" in main
    assert "output moduleCount int = length(moduleBoundaries)" in main
    assert "@maxValue(25000)\nparam maximumPlausibleUsdCents int = 1" in main


def test_scanner_foundation_precedes_resolution_and_post_secret_stays_gated():
    main = (ROOT / "main.bicep").read_text(encoding="utf-8")
    storage = (ROOT / "modules" / "storage-scanner.bicep").read_text(encoding="utf-8")

    assert "param scannerResultBridgeResolved bool = false" not in main
    assert "param scannerResultBridgeProviderProofIntegrity string = ''" in main
    assert "param scannerResultBridgeUnresolvedReasonCount int = 32" in main
    assert "deploymentStage == 'scanner-foundation'" in main
    assert "deploymentStage == 'scanner-proof'" in main
    assert (
        "module storage './modules/storage-scanner.bicep' = if (scannerFoundationEnabled)" in main
    )
    assert (
        "module scannerResultBridge './modules/scanner-result-bridge.bicep' "
        "= if (scannerFoundationEnabled)"
    ) in main
    assert (
        "var postSecretEnabled = oneRunEnabled && deploymentStage == 'post-secret' "
        "&& scannerResultBridgeResolved"
    ) in main
    assert "applicationDeploymentEnabled: postSecretEnabled" in main
    assert "scannerResultBridgeResolved" not in storage


def test_module_inventory_and_safe_outputs_are_exact():
    names = sorted(path.name for path in (ROOT / "modules").glob("*.bicep"))
    assert names == [
        "cleanup-supervisor.bicep",
        "compute.bicep",
        "container-apps-dns.bicep",
        "identities.bicep",
        "key-vault.bicep",
        "network.bicep",
        "observability.bicep",
        "policy.bicep",
        "postgres.bicep",
        "redis.bicep",
        "registry.bicep",
        "scanner-result-bridge.bicep",
        "storage-scanner.bicep",
    ]
    for path in (ROOT / "modules").glob("*.bicep"):
        text = path.read_text(encoding="utf-8")
        assert "@allowed([\n  false\n])\nparam deploymentEnabled bool = false" in text
        assert not re.search(
            r"(?mi)^output\s+\w+\s+\w+\s*=\s*(?:validatedRegion|"
            r"targetResourceGroupName|cleanupResourceGroupName|imageDigests|"
            r"immutableBindings)\s*$",
            text,
        )


def test_bicep_module_contracts_reflect_closed_policy_values():
    expected_tokens = {
        "cleanup-supervisor.bicep": [
            "param expectedUsdCents int",
            "@maxValue(25000)",
            "param maximumPlausibleUsdCents int",
            "param uncertaintyContingencyBasisPoints int = 2500",
            "param hardMaximumHours int = 30",
            "param minimumCleanupReserveMinutes int = 90",
            "param cleanupLocation string = 'westus'",
            "param cleanupControlDeploymentEnabled bool = false",
            "param cleanupJobScheduleDeploymentEnabled bool = false",
            "param cleanupBindingGeneration int = 2",
            "param cleanupBindingContractVersion string = 'm7.7-automation-cleanup-binding-v2'",
            (
                "var generationOneBindingId = guid(existingAutomationAccount.id, "
                "existingCleanupRunbook.name, existingCleanupSchedule.name)"
            ),
            "name: generationTwoBindingId",
        ],
        "compute.bicep": [
            "param computeTopology string = 'internal-azure-container-apps'",
            "param workloadProfile string = 'Consumption'",
            "param logAnalyticsWorkspaceId string = ''",
            "Microsoft.Insights/diagnosticSettings@2021-05-01-preview",
            "category: 'ContainerAppConsoleLogs'",
            "sharedWorkerPool:",
            "cpuMilli: 500",
            "maxReplicas: 4",
        ],
        "container-apps-dns.bicep": [
            "param defaultDomain string = ''",
            "param staticIp string = ''",
            "param virtualNetworkId string = ''",
            "name: 'link-mobius77-containerapps'",
            "registrationEnabled: false",
            "name: '*'",
            "ttl: 60",
            "aRecords: [",
        ],
        "network.bicep": [
            "param vnetCidr string = '10.77.0.0/20'",
            "param managementCleanupCidr string = '10.77.3.0/28'",
            "param infrastructurePublicIpCount int = 3",
            "param generalInternetEgressEnabled bool = false",
            "serviceName: 'Microsoft.App/environments'",
            "name: 'VpnGw1AZ'",
            "tier: 'VpnGw1AZ'",
            "vpnGatewayGeneration: 'Generation2'",
            "zones: [\n    '1'\n    '2'\n    '3'\n  ]",
        ],
        "policy.bicep": [
            "param deploymentRegion string",
            "param regionVerified bool = false",
            "output regionSupplied bool = !empty(deploymentRegion)",
        ],
        "observability.bicep": [
            "param absoluteExerciseIngestionCapMiB int = 2560",
            "param sanitizedEvidenceCapMiB int = 100",
            "param retentionResolved bool = false",
            "publicNetworkAccessForIngestion: 'Disabled'",
            "publicNetworkAccessForQuery: 'Disabled'",
        ],
        "postgres.bicep": [
            "param majorVersion int = 17",
            "param serverSku string = 'Standard_D2ds_v5'",
            "param storageGiB int = 64",
            "param highAvailability string = 'ZoneRedundant'",
        ],
        "redis.bicep": [
            "param proposedSku string = 'Balanced_B0'",
            "param nodeCount int = 2",
            "param providerContractResolved bool = true",
            "param cacheLocation string",
            "param privateEndpointLocation string",
            "sku: { name: proposedSku }",
            "location: cacheLocation",
            "location: privateEndpointLocation",
        ],
        "registry.bicep": [
            "param registrySku string = 'Premium'",
            "param administratorAccountEnabled bool = false",
        ],
        "storage-scanner.bicep": [
            "param storageSku string = 'Standard_LRS'",
            "param defenderMonthlyCapGiB int = 1",
            "param scannerExerciseObjectCap int = 25",
            "param totalSyntheticUploadBytesCap int = 134217728",
        ],
        "scanner-result-bridge.bicep": [
            "Microsoft.Insights/privateLinkScopes@2021-09-01",
            "queryAccessMode: 'PrivateOnly'",
            "ingestionAccessMode: 'PrivateOnly'",
            "privatelink.monitor.azure.com",
            "privatelink.oms.opinsights.azure.com",
            "privatelink.ods.opinsights.azure.com",
            "caj-mobius77-scanner-proof",
        ],
    }
    for name, tokens in expected_tokens.items():
        text = (ROOT / "modules" / name).read_text(encoding="utf-8")
        assert all(token in text for token in tokens)

    key_vault_text = (ROOT / "modules" / "key-vault.bicep").read_text(encoding="utf-8")
    assert "enablePurgeProtection:" not in key_vault_text
    assert "enableSoftDelete: true" in key_vault_text
    assert "softDeleteRetentionInDays: 7" in key_vault_text


def test_scanner_proof_console_diagnostic_is_narrow_and_private() -> None:
    compute = (ROOT / "modules" / "compute.bicep").read_text(encoding="utf-8")
    main = (ROOT / "main.bicep").read_text(encoding="utf-8")
    diagnostic = compute[compute.index("resource proofConsoleDiagnostic") :]
    diagnostic = diagnostic[: diagnostic.index("resource telemetryContainerApp")]

    assert "scope: managedEnvironment" in diagnostic
    assert "name: 'mobius77-scanner-proof-console'" in diagnostic
    assert "logAnalyticsDestinationType: 'Dedicated'" in diagnostic
    assert diagnostic.count("category: 'ContainerAppConsoleLogs'") == 1
    assert "ContainerAppSystemLogs" not in diagnostic
    assert "metrics: []" in diagnostic
    assert "workspaceId: logAnalyticsWorkspaceId" in diagnostic
    assert "logAnalyticsWorkspaceId: observability.outputs.workspaceId" in main
    assert "publicNetworkAccess: 'Disabled'" in compute


def test_private_pull_scanner_has_no_push_transport_or_tag_write_authority() -> None:
    storage = (ROOT / "modules" / "storage-scanner.bicep").read_text(encoding="utf-8")
    bridge = (ROOT / "modules" / "scanner-result-bridge.bicep").read_text(encoding="utf-8")
    combined = storage + bridge
    assert "defenderForStorageSettings" in storage
    assert "Microsoft.Security/defenderForStorageSettings@2025-06-01" in storage
    assert "blobScanResultsOptions: 'BlobIndexTags'" in storage
    assert "category: 'ScanResults'" in storage
    assert "Storage Blob Data Contributor" not in storage
    assert "/blobs/tags/read" in combined
    assert "/blobs/tags/write" not in combined
    assert "Microsoft.EventGrid/topics" not in combined
    assert "eventSubscriptions" not in combined
    assert "queueServices/queues" not in combined
    assert "publicNetworkAccess: 'Disabled'" in storage
    assert "allowPermanentDelete: true" in storage
    assert "/blobs/delete'" in bridge
    assert "/blobs/deleteBlobVersion/action" in bridge
    assert "/blobs/permanentDelete/action" in bridge
    main = (ROOT / "main.bicep").read_text(encoding="utf-8")
    assert "'Microsoft.Security/dataScanners'" in main
    assert "'Microsoft.Security/storageDataScanners'" not in main
    assert "proofCanarySeed: authorizationLedgerSha256" in main
    assert "OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED" in bridge


def test_container_apps_subnet_has_exact_exclusive_delegation() -> None:
    text = (ROOT / "modules" / "network.bicep").read_text(encoding="utf-8")
    container_subnet = text.split("name: containerAppsSubnetName", 1)[1].split(
        "name: privateEndpointSubnetName", 1
    )[0]

    assert container_subnet.count("delegations:") == 1
    assert container_subnet.count("name: 'container-apps-environment'") == 1
    assert container_subnet.count("serviceName: 'Microsoft.App/environments'") == 1
    assert text.count("serviceName: 'Microsoft.App/environments'") == 1


def test_compiled_key_vault_omits_irreversible_purge_protection(
    tmp_path: Path,
) -> None:
    bicep = shutil.which("bicep")
    if bicep is None:
        bundled = Path.home() / ".azure" / "bin" / "bicep.exe"
        assert bundled.is_file(), "the existing approved Bicep compiler is required"
        bicep = str(bundled)
    compiled = tmp_path / "main.json"
    result = subprocess.run(
        [bicep, "build", str(ROOT / "main.bicep"), "--outfile", str(compiled)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    vaults: list[dict] = []

    def collect(value) -> None:
        if isinstance(value, dict):
            if value.get("type") == "Microsoft.KeyVault/vaults":
                vaults.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    deployment = json.loads(compiled.read_text(encoding="utf-8"))
    collect(deployment)
    assert len(vaults) == 1
    properties = vaults[0]["properties"]
    assert "enablePurgeProtection" not in properties
    assert properties["enableSoftDelete"] is True
    assert properties["softDeleteRetentionInDays"] == 7


@pytest.mark.parametrize(
    "policy_name",
    [
        "dependency-order.json",
        "lifecycle-policy.json",
        "network-policy.json",
        "resource-policy.json",
        "unresolved-gates.json",
    ],
)
def test_every_policy_is_checksum_closed(policy_name: str, tmp_path: Path):
    copied = tmp_path / "bundle"
    shutil.copytree(ROOT, copied)
    path = copied / "policies" / policy_name
    value = _json(path)
    value["mutationForTest"] = True
    _write_json(path, value)
    with pytest.raises(contract.ContractError, match="reviewed closed contract"):
        contract.validate_bundle(copied)


def test_unresolved_gate_inventory_is_exact():
    gates = _json(POLICIES / "unresolved-gates.json")
    assert gates["allResolved"] is False
    assert tuple(item["id"] for item in gates["gates"]) == contract.EXPECTED_GATES
    assert {item["status"] for item in gates["gates"]} == {"unresolved"}
    assert gates["provisioningAuthorized"] is False


def test_resource_policy_has_fixed_topology_and_provider_blocks():
    resource = _json(POLICIES / "resource-policy.json")
    assert resource["defaultEffect"] == "deny"
    assert resource["mutableSkuSelectionAllowed"] is False
    assert resource["mutableReplicaSelectionAllowed"] is False
    services = resource["fixedSkus"]["containerApps"]["services"]
    assert services["web"] == {
        "cpuMilli": 250,
        "memoryMiB": 512,
        "minReplicas": 1,
        "normalReplicas": 1,
        "maxReplicas": 2,
    }
    assert services["api"]["minReplicas"] == 2
    assert services["api"]["maxReplicas"] == 4
    assert services["sharedWorkerPool"]["workKinds"] == [
        "indexer",
        "scan",
        "workflow",
        "agent",
    ]
    assert resource["fixedSkus"]["postgresql"]["name"] == "Standard_D2ds_v5"
    assert resource["fixedSkus"]["containerRegistry"]["name"] == "Premium"
    assert resource["fixedSkus"]["redis"]["providerClusteringEnum"] is None
    assert resource["fixedSkus"]["redis"]["location"] == "australiacentral"
    assert resource["fixedSkus"]["redis"]["privateEndpointLocation"] == ("southcentralus")
    assert resource["fixedSkus"]["vpnGateway"] == {
        "name": "VpnGw1AZ",
        "maximumLifetimeHours": 12,
        "maximumInstances": 1,
        "publicIpAvailabilityZoneMode": "explicit-zone-redundant",
        "publicIpZones": ["1", "2", "3"],
    }
    assert "Microsoft.Authorization/policyAssignments" in resource["allowedResourceTypes"]
    assert "Microsoft.Authorization/roleAssignments" in resource["allowedResourceTypes"]
    assert "Microsoft.Authorization/policyDefinitions" not in resource["allowedResourceTypes"]
    assert "Microsoft.Authorization/roleDefinitions" not in resource["allowedResourceTypes"]
    blocked = {item["logicalCapability"] for item in resource["blockedCandidateResourceTypes"]}
    assert blocked == {
        "defender-malware-scanning",
        "scanner-result-subscription",
        "scanner-result-system-topic",
    }


def test_network_policy_has_exact_private_topology_and_public_ip_exceptions():
    network = _json(POLICIES / "network-policy.json")
    assert network["defaultInboundAction"] == "deny"
    assert network["defaultOutboundAction"] == "deny"
    assert network["publicNetworkAccessAllowed"] is False
    address_plan = dict(network["addressPlan"])
    address_plan.pop("selectionStatus")
    assert address_plan == contract.EXPECTED_ADDRESS_PLAN
    assert network["routing"]["defaultRouteNextHop"] == "AzureFirewall"
    assert network["routing"]["broadVirtualNetworkServiceTagOutboundAllowed"] is False
    assert network["maximumInfrastructurePublicIpCount"] == 3
    assert [item["purpose"] for item in network["infrastructurePublicIpExceptions"]] == [
        "azure-firewall-data",
        "azure-firewall-management",
        "point-to-site-vpn-gateway",
    ]


def test_cost_thresholds_are_fixed_and_verified_values_reconcile():
    value = _json(MANIFESTS / "cost-envelope.template.json")
    assert value["targetUsdCents"] == 10000
    assert value["provisioningBlockAboveUsdCents"] == 12000
    assert value["absoluteCeilingUsdCents"] == 25000
    assert value["uncertaintyContingencyBasisPoints"] == 2500
    assert value["budgetAlertsAreEnforcement"] is False
    assert value["resolutionStatus"] == "verified"
    assert value["expectedUsdCents"] == 3110
    assert value["baseMaximumUsdCents"] == 16485
    assert value["contingencyUsdCents"] == 4122
    assert value["maximumPlausibleUsdCents"] == 20607
    assert sum(item["expectedUsdCents"] for item in value["lineItems"]) == 3110
    assert sum(item["baseMaximumUsdCents"] for item in value["lineItems"]) == 16485
    required_lines = {
        "postgresql-zone-redundant-compute",
        "postgresql-storage-and-backup",
        "managed-redis-balanced-b0-two-node",
        "redis-intercontinental-private-link-data",
        "object-storage-capacity-and-transactions",
        "defender-malware-scanning",
        "additional-private-connectivity-and-data",
        "failed-cleanup-six-hour-exposure",
        "cleanup-extension-thirty-hour-exposure",
    }
    assert required_lines.issubset({item["name"] for item in value["lineItems"]})
    assert all(
        item["priceEvidenceStatus"] == "verified-official-retail" for item in value["lineItems"]
    )
    contract._validate_cost(value)


def test_verified_cost_reconciles_base_contingency_and_maximum():
    value = _resolved_cost(expected=12000, base_maximum=12000)
    contract._validate_cost(value)
    assert value["contingencyUsdCents"] == 3000
    assert value["maximumPlausibleUsdCents"] == 15000


def test_cost_rejects_zero_empty_over_block_at_ceiling_and_bad_contingency():
    zero = _resolved_cost()
    zero.update(
        {
            "expectedUsdCents": 0,
            "baseMaximumUsdCents": 0,
            "contingencyUsdCents": 0,
            "maximumPlausibleUsdCents": 0,
            "lineItems": [],
        }
    )
    with pytest.raises(contract.ContractError, match="requires priced line items"):
        contract._validate_cost(zero)
    boolean_total = _resolved_cost()
    boolean_total["expectedUsdCents"] = True
    with pytest.raises(contract.ContractError, match="integer totals"):
        contract._validate_cost(boolean_total)
    over_block = _resolved_cost(expected=12001, base_maximum=12001)
    with pytest.raises(contract.ContractError, match="provisioning block"):
        contract._validate_cost(over_block)
    at_ceiling = _resolved_cost(expected=12000, base_maximum=20000)
    contract._validate_cost(at_ceiling)
    over_ceiling = _resolved_cost(expected=12000, base_maximum=20001)
    with pytest.raises(contract.ContractError, match="absolute ceiling"):
        contract._validate_cost(over_ceiling)
    bad_contingency = _resolved_cost()
    bad_contingency["contingencyUsdCents"] -= 1
    with pytest.raises(contract.ContractError, match="bounded cent calculation"):
        contract._validate_cost(bad_contingency)

    unrelated_rounding = _resolved_cost(expected=8000, base_maximum=11358)
    unrelated_rounding["contingencyUsdCents"] += 1
    unrelated_rounding["maximumPlausibleUsdCents"] += 1
    with pytest.raises(contract.ContractError, match="bounded cent calculation"):
        contract._validate_cost(unrelated_rounding)


def test_cost_lines_must_be_unique_reconcile_and_have_verified_evidence():
    value = _resolved_cost()
    value["lineItems"][0]["baseMaximumUsdCents"] -= 1
    with pytest.raises(contract.ContractError, match="do not reconcile"):
        contract._validate_cost(value)
    value = _resolved_cost()
    value["lineItems"][0]["priceEvidenceStatus"] = "unresolved"
    with pytest.raises(contract.ContractError, match="unresolved evidence"):
        contract._validate_cost(value)
    value = _resolved_cost()
    value["lineItems"].append(dict(value["lineItems"][0]))
    with pytest.raises(contract.ContractError, match="not unique"):
        contract._validate_cost(value)


def test_image_contract_is_source_bound_and_unresolved():
    value = _json(MANIFESTS / "image-digests.template.json")
    assert value["sourceCommit"] == contract.AUTHORITATIVE_SOURCE_COMMIT
    assert tuple(item["role"] for item in value["images"]) == contract.EXPECTED_IMAGE_ROLES
    assert value["mutableTagsAllowed"] is False
    assert value["buildManifestSha256"] is None
    assert value["registryBindingSha256"] is None
    assert all(item["digest"] is None for item in value["images"])
    contract._validate_images(value)


def test_image_contract_rejects_wrong_source_and_partial_resolution():
    value = _json(MANIFESTS / "image-digests.template.json")
    value["sourceCommit"] = "0" * 40
    with pytest.raises(contract.ContractError, match="source commit differs"):
        contract._validate_images(value)
    value = _json(MANIFESTS / "image-digests.template.json")
    value["resolutionStatus"] = "verified"
    with pytest.raises(contract.ContractError, match="build manifest"):
        contract._validate_images(value)


def test_verified_images_require_build_registry_and_each_digest():
    value = _json(MANIFESTS / "image-digests.template.json")
    value["resolutionStatus"] = "verified"
    value["buildManifestSha256"] = "a" * 64
    value["registryBindingSha256"] = "b" * 64
    for item in value["images"]:
        item["digest"] = "sha256:" + ("c" * 64)
    contract._validate_images(value)
    value["registryBindingSha256"] = None
    with pytest.raises(contract.ContractError, match="registry binding"):
        contract._validate_images(value)


def test_canonicalization_is_order_stable_nfc_array_sensitive_and_domain_separated():
    left = {"z": "e\u0301", "a": [2, 1]}
    right = {"a": [2, 1], "z": "\u00e9"}
    reordered_array = {"a": [1, 2], "z": "\u00e9"}
    assert contract.canonical_json_bytes(left) == contract.canonical_json_bytes(right)
    assert contract.manifest_sha256("test", "v1", left) == contract.manifest_sha256(
        "test", "v1", right
    )
    assert contract.manifest_sha256("test", "v1", left) != contract.manifest_sha256(
        "test", "v1", reordered_array
    )
    assert contract.manifest_sha256("environment", "v1", left) != (
        contract.manifest_sha256("cost-envelope", "v1", left)
    )
    assert contract.canonical_json_bytes(left).endswith(b"\n")


def test_canonicalization_rejects_floats_and_unapproved_manifest_domains():
    with pytest.raises(contract.ContractError, match="floating-point"):
        contract.canonical_json_bytes({"cost": 1.25})
    with pytest.raises(contract.ContractError, match="not approved"):
        contract.manifest_identity({"contractVersion": "unknown"})


def test_canonicalizer_derives_domain_from_contract_version():
    result = _run_script(
        SCRIPTS / "canonicalize_manifest.py",
        "--input",
        str(MANIFESTS / "environment.template.json"),
        "--bundle-root",
        str(ROOT),
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    value = _json(MANIFESTS / "environment.template.json")
    assert output["sha256"] == contract.manifest_sha256("environment", "v1", value)
    assert "--kind" not in (SCRIPTS / "canonicalize_manifest.py").read_text(encoding="utf-8")


def test_canonicalizer_rejects_known_domain_with_invalid_payload(tmp_path: Path):
    path = tmp_path / "invalid.json"
    _write_json(
        path,
        {
            "contractVersion": "m7.7-environment-v1",
            "unexpected": True,
        },
    )
    result = _run_script(
        SCRIPTS / "canonicalize_manifest.py",
        "--input",
        str(path),
        "--bundle-root",
        str(ROOT),
    )
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "blocked"
    assert "sha256" not in output


def test_canonicalizer_rejects_caller_weakened_schema_root(tmp_path: Path):
    copied = tmp_path / "bundle"
    shutil.copytree(ROOT, copied)
    schema_path = copied / "manifests" / "environment.schema.json"
    schema = _json(schema_path)
    schema["additionalProperties"] = True
    _write_json(schema_path, schema)
    manifest_path = tmp_path / "invalid.json"
    _write_json(
        manifest_path,
        {
            "contractVersion": "m7.7-environment-v1",
            "unexpected": True,
        },
    )
    result = _run_script(
        SCRIPTS / "canonicalize_manifest.py",
        "--input",
        str(manifest_path),
        "--bundle-root",
        str(copied),
    )
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "blocked"
    assert "reviewed closed contract" in output["error"]
    assert "sha256" not in output


def test_exact_scope_guard_accepts_root_provider_children_and_extensions():
    target = _synthetic_scope("rg-mobius77-target")
    cleanup = _synthetic_scope("rg-mobius77-control")
    normal_target, normal_cleanup = contract.assert_exact_resource_group_roots(target, cleanup)
    assert normal_target.endswith("/resourcegroups/rg-mobius77-target")
    assert normal_cleanup.endswith("/resourcegroups/rg-mobius77-control")
    child = f"{target}/providers/Microsoft.Storage/storageAccounts/synthetic"
    assert contract.assert_within_exact_root(child, target).endswith(
        "/providers/microsoft.storage/storageaccounts/synthetic"
    )
    extension = (
        child + "/blobServices/default/providers/Microsoft.Insights/diagnosticSettings/synthetic"
    )
    assert contract.assert_within_exact_root(extension, target).endswith(
        "/providers/microsoft.insights/diagnosticsettings/synthetic"
    )


@pytest.mark.parametrize(
    "case",
    [
        "subscription-parent",
        "sibling",
        "prefix-confusion",
        "query",
        "fragment",
        "encoded",
        "backslash",
        "double-slash",
        "dot-segment",
        "terminal-dot",
        "terminal-dotdot",
        "cross-subscription",
        "missing-resource-name",
        "missing-namespace-dot",
        "malformed-namespace",
        "internal-whitespace",
        "trailing-provider",
        "trailing-child-slash",
    ],
)
def test_exact_scope_guard_rejects_ambiguous_or_cross_scope(case: str):
    target = _synthetic_scope("rg-mobius77-target")
    cases = {
        "subscription-parent": target.rsplit("/resourceGroups/", 1)[0],
        "sibling": _synthetic_scope("rg-mobius77-sibling"),
        "prefix-confusion": f"{target}-evil",
        "query": f"{target}?api-version=x",
        "fragment": f"{target}#fragment",
        "encoded": target.replace("resourceGroups", "resource%47roups"),
        "backslash": target.replace("/resourceGroups/", "\\resourceGroups\\"),
        "double-slash": target.replace("/resourceGroups/", "//resourceGroups/"),
        "dot-segment": f"{target}/../sibling",
        "terminal-dot": f"{target}/.",
        "terminal-dotdot": f"{target}/..",
        "cross-subscription": _synthetic_scope("rg-mobius77-target", 2),
        "missing-resource-name": f"{target}/providers/Microsoft.Storage/storageAccounts",
        "missing-namespace-dot": f"{target}/providers/storage/storageAccounts/name",
        "malformed-namespace": (f"{target}/providers/Microsoft..Storage/storageAccounts/name"),
        "internal-whitespace": (f"{target}/providers/Microsoft.Storage/storageAccounts/bad name"),
        "trailing-provider": (
            f"{target}/providers/Microsoft.Storage/storageAccounts/name/providers"
        ),
        "trailing-child-slash": (f"{target}/providers/Microsoft.Storage/storageAccounts/name/"),
    }
    with pytest.raises(contract.ContractError):
        contract.assert_within_exact_root(cases[case], target)


def test_scope_roots_reject_noncanonical_uuid_and_terminal_dot_group():
    target = _synthetic_scope("rg-mobius77-target")
    canonical = target.split("/")[2]
    noncanonical = target.replace(canonical, canonical.replace("-", ""))
    with pytest.raises(contract.ContractError, match="subscription segment"):
        contract.assert_exact_resource_group_roots(
            noncanonical, _synthetic_scope("rg-mobius77-control")
        )
    with pytest.raises(contract.ContractError, match="resource-group name"):
        contract.assert_exact_resource_group_roots(
            target + ".", _synthetic_scope("rg-mobius77-control")
        )


def test_scope_binding_rejects_same_or_cross_subscription_roots():
    target = _synthetic_scope("rg-mobius77-target")
    with pytest.raises(contract.ContractError, match="must be separate"):
        contract.scope_binding_sha256(target, target)
    with pytest.raises(contract.ContractError, match="cross subscriptions"):
        contract.scope_binding_sha256(target, _synthetic_scope("rg-mobius77-control", 2))


@pytest.mark.parametrize(
    "field_parts",
    [
        ("api", "Key"),
        ("access", "Token"),
        ("authori", "zation"),
        ("private", "Key"),
        ("sas", "Uri"),
        ("api_", "key"),
        ("client_", "secret"),
        ("private-", "key"),
        ("connection_", "string"),
        ("subscription_", "id"),
        ("resource-", "id"),
    ],
)
def test_private_material_scan_rejects_secret_field_families(field_parts):
    field_name = "".join(field_parts)
    sensitive_value = "sensitive-" + ("x" * 32)
    with pytest.raises(contract.ContractError) as captured:
        contract.scan_private_material({field_name: sensitive_value})
    assert sensitive_value not in str(captured.value)


def test_private_material_scan_rejects_any_uuid_shape():
    identifier = "-".join(("0" * 8, "0" * 4, "0" * 4, "0" * 4, "0" * 11 + "1"))
    with pytest.raises(contract.ContractError, match="private identifier"):
        contract.scan_private_material({"opaque": f"prefix-{identifier}-suffix"})


def test_policies_are_deny_public_fixed_and_non_authorizing():
    environment = _json(MANIFESTS / "environment.template.json")
    contract._validate_policies(ROOT, environment)
    network = _json(POLICIES / "network-policy.json")
    lifecycle = _json(POLICIES / "lifecycle-policy.json")
    assert network["bootstrapEgress"]["enabledByDefault"] is False
    assert network["bootstrapEgress"]["generalInternetAllowed"] is False
    assert lifecycle["lease"]["hardMaximumHours"] == 30
    assert lifecycle["cleanup"]["targetZeroResidueBeforeControlDeletion"] is True


def test_dependency_order_is_exact_and_preserves_cleanup_until_residue_proof():
    order = _json(POLICIES / "dependency-order.json")
    assert tuple(order["deployment"]) == contract.EXPECTED_DEPLOYMENT_ORDER
    assert tuple(order["teardown"]) == contract.EXPECTED_TEARDOWN_ORDER
    assert order["deployment"].index("create-private-telemetry") < order["deployment"].index(
        "create-private-data-services"
    )
    assert order["teardown"].index("prove-target-zero-residue") < order["teardown"].index(
        "delete-cleanup-controls"
    )


@pytest.mark.parametrize(
    ("script_name", "operation"),
    [
        ("what_if.py", "what-if"),
        ("deploy.py", "deploy"),
        ("teardown.py", "teardown"),
        ("verify_zero_residue.py", "zero-residue"),
    ],
)
def test_lifecycle_scripts_require_scopes_and_remain_inert(script_name: str, operation: str):
    missing = _run_script(
        SCRIPTS / script_name,
        "--bundle-root",
        str(ROOT),
    )
    assert missing.returncode != 0
    target = _synthetic_scope("rg-mobius77-target")
    cleanup = _synthetic_scope("rg-mobius77-control")
    result = _run_script(
        SCRIPTS / script_name,
        "--bundle-root",
        str(ROOT),
        "--target-scope",
        target,
        "--cleanup-control-scope",
        cleanup,
    )
    assert result.returncode == 4
    output = json.loads(result.stdout)
    assert output["operation"] == operation
    assert output["executionAuthorized"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", output["scopeBindingSha256"])


def test_lifecycle_scripts_have_no_execution_dependencies():
    forbidden_imports = ("azure", "requests", "socket", "subprocess", "urllib")
    for path in SCRIPTS.glob("*.py"):
        if path.name == "managed_binding_lifecycle.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in forbidden_imports:
            assert not re.search(rf"(?m)^\s*(?:from|import)\s+{name}\b", text)


def test_preflight_malformed_bundle_fails_as_bounded_json_without_paths(
    tmp_path: Path,
):
    copied = tmp_path / "bundle"
    shutil.copytree(ROOT, copied)
    (copied / "policies" / "network-policy.json").unlink()
    result = _run_script(
        SCRIPTS / "preflight.py",
        "--bundle-root",
        str(copied),
    )
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "blocked"
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in (result.stdout + result.stderr)


def test_preflight_list_valued_policy_fails_as_bounded_json_without_traceback(
    tmp_path: Path,
):
    copied = tmp_path / "bundle"
    shutil.copytree(ROOT, copied)
    _write_json(copied / "policies" / "network-policy.json", [])
    result = _run_script(
        SCRIPTS / "preflight.py",
        "--bundle-root",
        str(copied),
    )
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "blocked"
    assert "must be a JSON object" in output["error"]
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in (result.stdout + result.stderr)


@pytest.mark.parametrize(
    ("relative", "is_directory"),
    [
        ("generated", True),
        (".azure", True),
        ("out", True),
        ("__pycache__", True),
        ("compiled.pyc", False),
    ],
)
def test_bundle_rejects_forbidden_generated_material(
    relative: str, is_directory: bool, tmp_path: Path
):
    copied = tmp_path / "bundle"
    shutil.copytree(ROOT, copied)
    path = copied / relative
    if is_directory:
        path.mkdir()
    else:
        path.write_bytes(b"synthetic")
    with pytest.raises(contract.ContractError, match=r"forbidden|compiled"):
        contract.validate_bundle(copied)


def test_infra_tree_contains_no_generated_or_sensitive_outputs():
    forbidden_suffixes = {
        ".cer",
        ".crt",
        ".deployment.json",
        ".evidence.json",
        ".key",
        ".log",
        ".outputs.json",
        ".pem",
        ".pfx",
        ".pyc",
        ".pyo",
        ".tfstate",
        ".what-if.json",
        ".zip",
    }
    forbidden_names = {
        ".azure",
        ".env",
        ".pytest_cache",
        "__pycache__",
        "generated",
        "main.json",
        "out",
    }
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        assert not any(part in forbidden_names for part in relative.parts)
        if path.is_file():
            assert not any(path.name.endswith(suffix) for suffix in forbidden_suffixes)


def test_tracked_contract_text_has_no_private_arm_id_guid_or_user_path():
    guid = re.compile(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}\b"
    )
    arm = re.compile(r"(?i)/subscriptions/[0-9a-f-]{36}/")
    user_path = re.compile(r"(?i)(?:[A-Z]:\\U" r"sers\\|/U" r"sers/|/ho" r"me/)")
    public_guids = {
        "manifests/managed-binding.contract.json": {
            "2efddaa5-3f1f-4df3-97df-af3f13818f4c",
            "4d97b98b-1d4f-4787-a291-c67834d212e7",
            "4633458b-17de-408a-b874-0445c86b69e6",
            "7f951dda-4ed3-4680-a7ca-43fe172d538d",
            "8311e382-0749-4cb8-b61a-304f252e45ec",
            "b24988ac-6180-42a0-ab88-20f7382dd24c",
            "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",
            "c2f4ef07-c644-48eb-af81-4b1b4947fb11",
            "c632b3df-fb67-4d84-bdcf-b95ad541b5c8",
            "b74c6cfe-995e-5107-9e42-4f7f76b76742",
            "f61544fe-cd79-5247-ac8b-ee9697b6ffd6",
            "5ffc55c1-7a88-5231-b0d1-e76ee95d057e",
            "a5429a32-87e3-5963-8c3a-bef85e777ed5",
            "d83b4107-54e0-57a4-b650-fe0b556132d2",
            "ecdbb32f-9134-5697-85f9-d569ba57454b",
            "158cac88-5679-5804-9f4d-854520bbb635",
        },
        "manifests/managed-binding.schema.json": {
            "b24988ac-6180-42a0-ab88-20f7382dd24c",
            "b74c6cfe-995e-5107-9e42-4f7f76b76742",
            "f61544fe-cd79-5247-ac8b-ee9697b6ffd6",
            "5ffc55c1-7a88-5231-b0d1-e76ee95d057e",
            "d83b4107-54e0-57a4-b650-fe0b556132d2",
            "ecdbb32f-9134-5697-85f9-d569ba57454b",
            "158cac88-5679-5804-9f4d-854520bbb635",
        },
        "modules/identities.bicep": {"b24988ac-6180-42a0-ab88-20f7382dd24c"},
        "modules/key-vault.bicep": {"4633458b-17de-408a-b874-0445c86b69e6"},
        "modules/network.bicep": {"c632b3df-fb67-4d84-bdcf-b95ad541b5c8"},
        "modules/registry.bicep": {"7f951dda-4ed3-4680-a7ca-43fe172d538d"},
        "modules/storage-scanner.bicep": {
            "43c7bdad-b8f9-4d4b-9881-ae8af70cf269",
            "a59d0f11-7f62-4699-97d9-6c8565ba77a4",
            "292f18b2-0b41-4a86-a4af-46cd22d2e52e",
            "6ecfca2a-29a1-4802-a236-706d77995e21",
        },
        "modules/scanner-result-bridge.bicep": {
            "73c42c96-874c-492b-b04d-ab87d138a893",
            "7d78ed8f-4b48-4e74-bb95-f0fcfe811897",
        },
        "acr_tag_finalization.py": {
            "2efddaa5-3f1f-4df3-97df-af3f13818f4c",
            "7f951dda-4ed3-4680-a7ca-43fe172d538d",
            "c2f4ef07-c644-48eb-af81-4b1b4947fb11",
        },
        "scanner_bridge_recovery_adapter.py": {
            "cd50fd1f-0421-46f2-8cce-afc587dbcc77",
            "43c7bdad-b8f9-4d4b-9881-ae8af70cf269",
            "a59d0f11-7f62-4699-97d9-6c8565ba77a4",
            "292f18b2-0b41-4a86-a4af-46cd22d2e52e",
            "6ecfca2a-29a1-4802-a236-706d77995e21",
            "73c42c96-874c-492b-b04d-ab87d138a893",
        },
        "scripts/managed_binding_lifecycle.py": {
            "00000000-0000-0000-0000-000000000000",
            "4d97b98b-1d4f-4787-a291-c67834d212e7",
        },
        "scripts/Remove-Mobius77Staging.ps1": {"b24988ac-6180-42a0-ab88-20f7382dd24c"},
    }
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        observed = {match.group(0).lower() for match in guid.finditer(text)}
        assert observed <= public_guids.get(relative, set())
        assert arm.search(text) is None
        assert user_path.search(text) is None


def test_source_files_are_utf8_lf_terminated_and_bounded():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        assert len(raw) < 256_000
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" not in raw
        assert raw.endswith(b"\n")
