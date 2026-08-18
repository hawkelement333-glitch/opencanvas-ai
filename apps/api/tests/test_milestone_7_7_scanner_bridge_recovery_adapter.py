from __future__ import annotations

import inspect
import json
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from infra.milestone_7_7 import api_image_publication
from infra.milestone_7_7 import scanner_bridge_recovery_adapter as adapter_module
from infra.milestone_7_7.scanner_bridge_recovery_adapter import (
    ProductionScannerBridgeRecoveryAdapter,
    ScannerBridgeRecoveryExecutionError,
)
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from infra.milestone_7_7.scripts.scanner_bridge_deployment import (
    bicep_parameters,
    load_deployment_evidence,
)
from opencanvas_api.services.scanner_bridge import BlobTagReadObservation
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import scanner_bridge_recovery
from preflight.milestone_7_7.remaining_lifecycle_simulation import (
    DURABLE_MARKERS,
    Milestone77RemainingLifecycleSimulation,
    RemainingLifecycleSimulationInput,
)
from preflight.milestone_7_7.scanner_bridge_recovery import (
    FOUNDATION_ALLOWED_OPERATIONS,
    FOUNDATION_STAGE,
    PRIVATE_ENDPOINT_RECOVERY_ALLOWED_OPERATIONS,
    PRIVATE_ENDPOINT_RECOVERY_STAGE,
    PROOF_ALLOWED_OPERATIONS,
    PROOF_JOB,
    PROOF_STAGE,
    ScannerBridgeRecoveryAuthorization,
    ScannerBridgeRecoveryError,
    build_scanner_bridge_recovery_authorization,
    scanner_bridge_recovery_authorization_integrity,
    validate_scanner_bridge_recovery_authorization,
    write_scanner_bridge_recovery_authorization,
)
from preflight.milestone_7_7.scanner_result_bridge import (
    deployment_evidence_from_mapping,
)
from scripts import scanner_bridge_probe

SUBSCRIPTION_ID = "11111111-2222-4333-8444-555555555555"
SUBSCRIPTION = f"/subscriptions/{SUBSCRIPTION_ID}"
TARGET = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-staging"
CLEANUP_ACCOUNT = (
    f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-cleanup-control/"
    "providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery"
)
NOW = datetime(2026, 8, 6, 17, 30, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 13, 6, 30, tzinfo=UTC)
HEAD = "a" * 40
IMAGE = "acrmobius7711564669.azurecr.io/opencanvas-api@sha256:" + "b" * 64
BUILD_INPUT = "c" * 64
WORKER_PRINCIPAL = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DEFENDER_SCANNER_ROLE = "cd50fd1f-0421-46f2-8cce-afc587dbcc77"
REPOSITORY_HEAD = subprocess.run(
    ("git", "rev-parse", "HEAD"),
    check=True,
    capture_output=True,
    encoding="utf-8",
).stdout.strip()


def _authorization(stage: str = FOUNDATION_STAGE) -> ScannerBridgeRecoveryAuthorization:
    return build_scanner_bridge_recovery_authorization(
        stage=stage,
        repository_head=HEAD,
        subscription_id=SUBSCRIPTION_ID,
        target_resource_group_id=TARGET,
        cleanup_automation_account_id=CLEANUP_ACCOUNT,
        cleanup_deadline_utc="2026-08-13T06:30:00Z",
        now_utc=NOW,
        api_image_digest=IMAGE if stage == PROOF_STAGE else None,
        build_input_sha256=BUILD_INPUT if stage == PROOF_STAGE else None,
        proof_execution_ordinal=4 if stage == PROOF_STAGE else 0,
    )


def _resign(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> ScannerBridgeRecoveryAuthorization:
    unsigned = replace(authorization, authorizationIntegritySha256="")
    return replace(
        unsigned,
        authorizationIntegritySha256=(scanner_bridge_recovery_authorization_integrity(unsigned)),
    )


def _readback() -> adapter_module._FoundationReadback:
    return adapter_module._FoundationReadback(
        api_principal_id="11111111-aaaa-4bbb-8ccc-222222222222",
        worker_principal_id=WORKER_PRINCIPAL,
        worker_client_id="33333333-aaaa-4bbb-8ccc-444444444444",
        workspace_customer_id="55555555-aaaa-4bbb-8ccc-666666666666",
        provider_topic_id=f"{TARGET}/providers/Microsoft.EventGrid/systemTopics/provider",
        provider_proof_integrity="1" * 64,
        diagnostic_proof_integrity="2" * 64,
        rbac_proof_integrity="3" * 64,
        tag_write_denial_integrity="4" * 64,
        private_path_control_plane_integrity="5" * 64,
        inventory_integrity="6" * 64,
    )


def _outputs(authorization: ScannerBridgeRecoveryAuthorization) -> dict[str, JsonValue]:
    base: dict[str, JsonValue] = {
        "deploymentStage": authorization.stage,
        "deploymentEnabled": False,
        "managedBindingDeploymentEnabled": True,
        "targetResourceGroupName": "rg-solarplexus-mobius-77-staging",
        "scannerBridgeFoundationDeployed": True,
        "scannerBridgeTransport": "private-blob-tags-plus-ampls-log-analytics-pull",
        "scannerBridgeStorageAccountId": authorization.storageAccountId,
        "scannerBridgePrivateLinkScopeId": authorization.privateLinkScopeId,
        "scannerBridgePrivateEndpointId": authorization.monitorPrivateEndpointId,
        "scannerBridgeWorkerIdentityId": authorization.workerIdentityId,
        "scannerBridgeWorkerPrincipalId": WORKER_PRINCIPAL,
        "scannerBridgeWorkerTagWriteAuthorized": False,
        "defaultProvisioningAuthorized": False,
        "secretValueAccessAuthorized": False,
        "storageAccountUrl": "https://stmobius7711564669.blob.core.windows.net/",
    }
    if authorization.stage == FOUNDATION_STAGE:
        return {
            **base,
            "scannerBridgeProofJobName": "",
            "scannerBridgeProofJobId": "",
            "scannerBridgeTemporaryRoleId": "",
            "scannerBridgeTemporaryRoleAssignmentId": "",
            "scannerBridgeProofImageDigest": "",
        }
    assignment = (
        f"{authorization.storageAccountId}/blobServices/default/containers/quarantine/"
        "providers/Microsoft.Authorization/roleAssignments/"
        "77777777-aaaa-4bbb-8ccc-888888888888"
    )
    return {
        **base,
        "scannerBridgeProofJobName": PROOF_JOB,
        "scannerBridgeProofJobId": authorization.proofJobId,
        "scannerBridgeTemporaryRoleId": authorization.proofRoleDefinitionId,
        "scannerBridgeTemporaryRoleAssignmentId": assignment,
        "scannerBridgeProofImageDigest": authorization.apiImageDigest,
    }


def _marker() -> dict[str, JsonValue]:
    completion = "2026-08-06T14:25:00Z"
    comparison = _scan_finished_terminal_evidence(equal=True)
    observation = _blob_tag_observation(
        decision="accepted",
        returned=(adapter_module.BLOB_RESULT_TAG, adapter_module.BLOB_SCAN_TIME_TAG),
    )
    values = {
        "accountNameSha256": "0" * 64,
        "blobEvidenceSha256": "1" * 64,
        "blobTagResultSha256": adapter_module._hash_text("No threats found"),
        "blobUriSha256": "6" * 64,
        "completionTimeSha256": adapter_module._hash_text(completion),
        "contentSha256": "7" * 64,
        "correlationIdSha256": "2" * 64,
        "dualSourceEvidenceSha256": "7" * 64,
        "etagSha256": "3" * 64,
        "logAnalyticsEvidenceSha256": "4" * 64,
        "logQuerySha256": "a" * 64,
        "privateDnsEvidenceSha256": "b" * 64,
        "providerVersionSha256": "5" * 64,
        "scanRequestIdSha256": "d" * 64,
        "storageResourceSha256": "e" * 64,
        "tlsEvidenceSha256": "f" * 64,
        "tlsHostnameSha256": "0" * 64,
    }
    body: dict[str, JsonValue] = {
        **values,
        "attemptCount": 3,
        "blobTagObservation": observation,
        "blobTagObservationCount": 3,
        "decision": "clean",
        "marker": "SCANNER_RESULT_BRIDGE_PROVED",
        "residue": "canary-version-deleted",
        "scanFinishedComparison": comparison,
        "schemaVersion": "mobius.scanner-result-bridge.proof.v2",
        "tlsVersion": "TLS1_3",
    }
    return {
        **body,
        "markerIntegritySha256": adapter_module._scanner_runtime_hash(
            body,
            "mobius.scanner-bridge.proof-success-marker.v2",
        ),
    }


def _failure_marker(
    code: str = "scanner-correlation-uri-mismatch",
) -> dict[str, JsonValue]:
    terminal: dict[str, JsonValue] | None = (
        _scan_finished_terminal_evidence()
        if code == "scanner-correlation-scan-finished-mismatch"
        else None
    )
    body: dict[str, JsonValue] = {
        "attemptCount": 120,
        "blobTagObservationCount": 120,
        "failureCode": code,
        "marker": "SCANNER_RESULT_BRIDGE_FAILED",
        "schemaVersion": "mobius.scanner-result-bridge.proof-failure.v2",
        "terminalEvidence": terminal,
    }
    return {
        **body,
        "markerIntegritySha256": adapter_module._scanner_runtime_hash(
            body,
            "mobius.scanner-bridge.proof-failure-marker.v2",
        ),
    }


@pytest.mark.asyncio
async def test_runtime_success_marker_feeds_production_evidence_and_post_secret_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _resign(replace(_authorization(PROOF_STAGE), repositoryHead=REPOSITORY_HEAD))
    tls_hosts = (
        "stmobius7711564669.blob.core.windows.net",
        "api.loganalytics.azure.com",
    )

    class ValidatedTls:
        def version(self) -> str:
            return "TLSv1.3"

    class Writer:
        def get_extra_info(self, _name: str) -> object:
            return ValidatedTls()

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def open_connection(*_args: object, **_kwargs: object) -> tuple[object, object]:
        return object(), Writer()

    monkeypatch.setattr(scanner_bridge_probe.asyncio, "open_connection", open_connection)
    tls_version, tls_integrity = await scanner_bridge_probe._prove_private_tls(tls_hosts)
    expected = _marker()
    body = {key: value for key, value in expected.items() if key != "markerIntegritySha256"}
    body["tlsEvidenceSha256"] = tls_integrity
    body["tlsHostnameSha256"] = adapter_module._hash_text("|".join(tls_hosts))
    body["tlsVersion"] = tls_version
    runtime_marker = cast(
        dict[str, JsonValue],
        scanner_bridge_probe._success_marker(cast(dict[str, object], body)),
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(runtime_marker, separators=(",", ":")),
    )
    parsed = adapter_module._proof_marker(authorization, "proof-execution")
    assert parsed == runtime_marker

    execution = {
        "name": "proof-execution",
        "status": "Succeeded",
        "startTime": "2026-08-06T14:20:00Z",
        "endTime": "2026-08-06T14:25:00Z",
    }
    produced = adapter_module._build_live_evidence(
        authorization=authorization,
        readback=_readback(),
        execution_name="proof-execution",
        execution=execution,
        marker=parsed,
        proof_graph_integrity="8" * 64,
        revocation_integrity="9" * 64,
        observed_at=NOW,
    )
    path = tmp_path / "scanner-deployment-evidence.json"
    adapter_module._write_evidence(path, produced)
    consumed = load_deployment_evidence(path, repository_head=REPOSITORY_HEAD, now=NOW)
    parameters = bicep_parameters(consumed, repository_head=REPOSITORY_HEAD, now=NOW)

    assert consumed == produced
    assert consumed.unresolved_reasons == ()
    assert consumed.private_address_sha256 == body["privateDnsEvidenceSha256"]
    assert consumed.tls_hostname_sha256 == body["tlsHostnameSha256"]
    assert consumed.tls_version == "TLS1_3"
    assert consumed.private_path_proof_integrity == adapter_module._canonical_hash(
        cast(
            JsonValue,
            {
                "controlPlane": _readback().private_path_control_plane_integrity,
                "dns": body["privateDnsEvidenceSha256"],
                "tls": tls_integrity,
            },
        ),
        "mobius.scanner-bridge.private-path-live-proof.v1",
    )
    assert "scannerResultBridgeUnresolvedReasonCount=0" in parameters
    assert ("scannerResultBridgeEvidenceIntegrity=" + produced.integrity_sha256()) in parameters

    monkeypatch.setattr(
        api_image_publication,
        "_api_image_build_input_sha256",
        lambda _head: BUILD_INPUT,
    )
    simulation = Milestone77RemainingLifecycleSimulation(
        RemainingLifecycleSimulationInput(
            operation_id_sha256="d" * 64,
            control_plane_head=REPOSITORY_HEAD,
            immutable_digest=IMAGE,
            migration_job_name="migration-job",
            migration_job_resource_id="opaque-resource-alias",
            bridge_evidence=consumed,
            cleanup_resources=("bridge", "runtime", "migration"),
            cleanup_generation=4,
        ),
        NOW,
    )
    assert simulation.run() == DURABLE_MARKERS
    assert simulation.operation_counts["scanner-evidence-producer-consumer"] == 1
    assert simulation.operation_counts["uninterrupted-soak"] == 1
    assert simulation.operation_counts["milestone-completion"] == 1


def _timestamp_representation(value: str) -> dict[str, JsonValue]:
    canonical = value
    body: dict[str, JsonValue] = {
        "canonicalUtc": canonical,
        "fractionalSecondDigits": (
            len(value.rsplit(".", maxsplit=1)[1].removesuffix("Z")) if "." in value else 0
        ),
        "parserNormalizationPath": adapter_module.SCAN_FINISHED_NORMALIZATION_PATH,
        "rawLengthBytes": len(value.encode()),
        "rawValue": value,
        "rawValueSha256": adapter_module._hash_text(value),
        "timezoneRepresentation": "Z",
    }
    return body


def _scan_finished_terminal_evidence(
    *,
    equal: bool = False,
) -> dict[str, JsonValue]:
    blob_timestamp = "2026-08-06T14:25:00Z" if equal else "2026-08-06T14:24:59.999999Z"
    body: dict[str, JsonValue] = {
        "blobEvidenceSha256": "1" * 64,
        "blobTagResult": "No threats found",
        "blobTagsCommonPrecisionUtc": ("2026-08-06T14:25:00Z" if equal else "2026-08-06T14:24:59Z"),
        "blobTagsTimestamp": _timestamp_representation(blob_timestamp),
        "commonPrecisionEqual": equal,
        "comparisonContract": adapter_module.SCAN_FINISHED_COMPARISON_CONTRACT,
        "comparisonDecision": ("equal-common-precision" if equal else "different-common-precision"),
        "comparisonPrecisionFractionalSecondDigits": 0,
        "correlationIdSha256": "2" * 64,
        "etagComparison": "matched",
        "etagSha256": "3" * 64,
        "exactInstantDeltaMicroseconds": 0 if equal else 1,
        "exactInstantEqual": equal,
        "logAnalyticsEvidenceSha256": "4" * 64,
        "logAnalyticsCommonPrecisionUtc": "2026-08-06T14:25:00Z",
        "logAnalyticsMinusBlobTagsMicroseconds": 0 if equal else 1,
        "logAnalyticsResult": "No threats found",
        "logAnalyticsTimestamp": _timestamp_representation("2026-08-06T14:25:00Z"),
        "providerVersionSha256": "5" * 64,
        "uriComparison": "matched",
        "uriSha256": "6" * 64,
    }
    return {
        **body,
        "integritySha256": adapter_module._scanner_runtime_hash(
            body,
            "mobius.scanner-bridge.scan-finished-comparison.v2",
        ),
    }


def _blob_tag_observation(
    *,
    decision: str = "rejected-required-key-missing",
    returned: tuple[str, ...] = (adapter_module.BLOB_RESULT_TAG,),
) -> dict[str, JsonValue]:
    required = (
        adapter_module.BLOB_RESULT_TAG,
        adapter_module.BLOB_SCAN_TIME_TAG,
    )
    body: dict[str, JsonValue] = {
        "differentBlobVersion": decision == "rejected-version-mismatch",
        "exactComparisonDecision": decision,
        "httpStatus": 200,
        "marker": "SCANNER_BLOB_TAG_OBSERVATION",
        "parserNormalizationPath": "azure-blob-tags-xml-local-name-v1",
        "queriedBlobUriSha256": "6" * 64,
        "queriedBlobVersionIdSha256": "5" * 64,
        "queriedEtagSha256": "3" * 64,
        "requestCorrelationId": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "requiredKeysFound": [key for key in required if key in returned],
        "requiredKeysMissing": [key for key in required if key not in returned],
        "responseEmpty": not returned,
        "responseEtagSha256": "3" * 64,
        "responseVersionIdSha256": "5" * 64,
        "returnedTagKeys": list(returned),
        "schemaVersion": "mobius.scanner-result-bridge.blob-tags-observation.v1",
        "tagCount": len(returned),
        "unexpectedKeys": [key for key in returned if key not in required],
        "versionIdentityPath": "response-version-id-and-etag",
    }
    return {
        **body,
        "integritySha256": adapter_module._blob_tag_observation_hash(body),
    }


def _install_common_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: ScannerBridgeRecoveryAuthorization,
    calls: list[str],
) -> list[dict[str, object]]:
    deployments: list[dict[str, object]] = []
    monkeypatch.setattr(managed_binding_lifecycle, "_verify_repository_state", lambda _head: None)
    monkeypatch.setattr(managed_binding_lifecycle, "_account_binding", lambda _now: SUBSCRIPTION_ID)
    monkeypatch.setattr(managed_binding_lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (3_110, 20_607))
    monkeypatch.setattr(
        adapter_module, "_verify_provider_api_versions", lambda _sub: calls.append("provider")
    )
    monkeypatch.setattr(
        adapter_module, "_verify_network_capacity", lambda _sub: calls.append("quota")
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_control",
        lambda *_args: "99999999-aaaa-4bbb-8ccc-000000000000",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle, "_verify_cleanup_target_role", lambda *_args: None
    )
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_compile_template",
        lambda _path: calls.append("compile"),
    )

    def deploy(**kwargs: object) -> None:
        calls.append("deploy")
        deployments.append(kwargs)

    monkeypatch.setattr(managed_binding_lifecycle, "_deploy_stage", deploy)
    monkeypatch.setattr(
        adapter_module,
        "_read_deployment_outputs",
        lambda **_kwargs: _outputs(authorization),
    )

    def verify_foundation(
        _authorization: ScannerBridgeRecoveryAuthorization,
        *,
        require_proof_console_diagnostic: bool = False,
    ) -> adapter_module._FoundationReadback:
        calls.append(f"foundation:{require_proof_console_diagnostic}")
        return _readback()

    monkeypatch.setattr(adapter_module, "_verify_foundation", verify_foundation)
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_proof_rbac_propagation",
        lambda *_args, **_kwargs: calls.append("rbac-propagation") or "7" * 64,
    )
    return deployments


@pytest.mark.parametrize(
    ("current", "limit"),
    [(2, 65_536), ("2", "65536")],
)
def test_network_capacity_accepts_canonical_azure_integer_values(
    monkeypatch: pytest.MonkeyPatch, current: JsonValue, limit: JsonValue
) -> None:
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda *_args, **_kwargs: [{"current": current, "limit": limit}],
    )

    adapter_module._verify_network_capacity(SUBSCRIPTION_ID)


@pytest.mark.parametrize("value", [True, -1, "", "01", "+1", "1.0", " 1"])
def test_network_capacity_rejects_noncanonical_values(
    monkeypatch: pytest.MonkeyPatch, value: JsonValue
) -> None:
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda *_args, **_kwargs: [{"current": value, "limit": "65536"}],
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-bridge-network-quota-malformed",
    ):
        adapter_module._verify_network_capacity(SUBSCRIPTION_ID)


def test_network_capacity_rejects_an_exhausted_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda *_args, **_kwargs: [{"current": "9", "limit": "10"}],
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-bridge-network-quota-insufficient",
    ):
        adapter_module._verify_network_capacity(SUBSCRIPTION_ID)


def test_authoritative_arm_resource_ids_are_compared_case_insensitively() -> None:
    assert adapter_module._same_resource_id(TARGET.swapcase(), TARGET) is True
    assert adapter_module._same_resource_id(TARGET, TARGET) is True
    assert adapter_module._same_resource_id(None, TARGET) is False
    assert adapter_module._same_resource_id(f"{TARGET}-other", TARGET) is False


def test_foundation_authorization_is_image_free_and_denies_broader_authority() -> None:
    authorization = _authorization()
    assert adapter_module.DEFENDER_SCANNER_ROLE == DEFENDER_SCANNER_ROLE
    assert authorization.stage == FOUNDATION_STAGE
    assert authorization.apiImageDigest is None
    assert authorization.buildInputSha256 is None
    assert authorization.allowedOperations == FOUNDATION_ALLOWED_OPERATIONS
    assert authorization.maximumProofExecutions == 0
    assert authorization.proofExecutionOrdinal == 0
    assert authorization.publicAccessAuthorized is False
    assert authorization.tagWriteAuthorized is False
    assert authorization.applicationDeploymentAuthorized is False
    assert authorization.migrationAuthorized is False
    assert authorization.cleanupExecutionAuthorized is False
    assert (
        validate_scanner_bridge_recovery_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW,
        )
        is authorization
    )


def test_private_endpoint_recovery_authorization_is_exact_and_image_free() -> None:
    authorization = _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE)
    assert authorization.stage == PRIVATE_ENDPOINT_RECOVERY_STAGE
    assert authorization.monitorPrivateEndpointId == (
        f"{TARGET}/providers/Microsoft.Network/privateEndpoints/pe-mobius77-azure-monitor"
    )
    assert authorization.allowedOperations == PRIVATE_ENDPOINT_RECOVERY_ALLOWED_OPERATIONS
    assert authorization.apiImageDigest is None
    assert authorization.buildInputSha256 is None
    assert authorization.maximumProofExecutions == 0
    assert authorization.proofExecutionOrdinal == 0
    assert authorization.publicAccessAuthorized is False
    assert authorization.tagWriteAuthorized is False
    assert authorization.applicationDeploymentAuthorized is False
    assert authorization.migrationAuthorized is False
    assert authorization.cleanupExecutionAuthorized is False
    assert (
        validate_scanner_bridge_recovery_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW,
        )
        is authorization
    )


def test_private_endpoint_recovery_rejects_broader_foundation_operations() -> None:
    authorization = _resign(
        replace(
            _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE),
            allowedOperations=FOUNDATION_ALLOWED_OPERATIONS,
        )
    )
    with pytest.raises(
        ScannerBridgeRecoveryError,
        match="scanner-bridge-authorization-scope-invalid",
    ):
        validate_scanner_bridge_recovery_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW,
        )


def test_private_endpoint_recovery_maps_only_the_exact_endpoint_and_dns_child() -> None:
    authorization = _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE)
    tags: dict[str, JsonValue] = {"mobius-environment": "milestone-7.7-staging"}
    endpoint_body = adapter_module._monitor_private_endpoint_write_body(
        authorization,
        {"endpointTags": tags},
    )
    subnet_id = (
        f"{TARGET}/providers/Microsoft.Network/virtualNetworks/vnet-mobius77-staging/"
        "subnets/snet-mobius77-private-endpoints"
    )
    assert endpoint_body == {
        "location": "southcentralus",
        "properties": {
            "privateLinkServiceConnections": [
                {
                    "name": "azuremonitor",
                    "properties": {
                        "groupIds": ["azuremonitor"],
                        "privateLinkServiceId": authorization.privateLinkScopeId,
                    },
                }
            ],
            "subnet": {"id": subnet_id},
        },
        "tags": tags,
    }
    zone_group_body = adapter_module._monitor_private_dns_zone_group_write_body(authorization)
    configs = zone_group_body["properties"]
    assert isinstance(configs, dict)
    assert configs["privateDnsZoneConfigs"] == [
        {
            "name": name,
            "properties": {
                "privateDnsZoneId": (f"{TARGET}/providers/Microsoft.Network/privateDnsZones/{zone}")
            },
        }
        for zone, _link, name in adapter_module.MONITOR_PRIVATE_DNS_BINDINGS
    ]


def test_proof_authorization_binds_one_exact_immutable_image_and_execution() -> None:
    authorization = _authorization(PROOF_STAGE)
    assert PROOF_JOB == "caj-mobius77-scanner-proof"
    assert len(PROOF_JOB) <= 32
    assert authorization.allowedOperations == PROOF_ALLOWED_OPERATIONS
    assert authorization.apiImageDigest == IMAGE
    assert authorization.buildInputSha256 == BUILD_INPUT
    assert authorization.maximumProofExecutions == 1
    assert authorization.proofExecutionOrdinal == 4
    assert authorization.proofJobId == f"{TARGET}/providers/Microsoft.App/jobs/{PROOF_JOB}"
    assert authorization.proofRoleDefinitionId == (
        f"{TARGET}/providers/Microsoft.Authorization/roleDefinitions/"
        "7d78ed8f-4b48-4e74-bb95-f0fcfe811897"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subscriptionId", "00000000-0000-4000-8000-000000000000"),
        ("targetResourceGroupId", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("cleanupAutomationAccountId", f"{SUBSCRIPTION}/resourceGroups/other"),
        ("storageAccountId", f"{TARGET}/providers/Microsoft.Storage/storageAccounts/other"),
        (
            "logAnalyticsWorkspaceId",
            f"{TARGET}/providers/Microsoft.OperationalInsights/workspaces/other",
        ),
        (
            "workerIdentityId",
            f"{TARGET}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/other",
        ),
        ("privateLinkScopeId", f"{TARGET}/providers/Microsoft.Insights/privateLinkScopes/other"),
        (
            "monitorPrivateEndpointId",
            f"{TARGET}/providers/Microsoft.Network/privateEndpoints/other",
        ),
        ("publicAccessAuthorized", True),
        ("tagWriteAuthorized", True),
        ("applicationDeploymentAuthorized", True),
        ("migrationAuthorized", True),
        ("cleanupExecutionAuthorized", True),
        ("maximumProofExecutions", 2),
        ("proofExecutionOrdinal", 3),
    ],
)
def test_exact_scope_and_prohibited_authority_drift_is_rejected(field: str, value: object) -> None:
    authorization = _resign(replace(_authorization(PROOF_STAGE), **{field: value}))
    with pytest.raises(ScannerBridgeRecoveryError):
        validate_scanner_bridge_recovery_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW,
        )


def test_foundation_rejects_any_image_binding() -> None:
    with pytest.raises(
        ScannerBridgeRecoveryError,
        match="scanner-foundation-image-authority-prohibited",
    ):
        build_scanner_bridge_recovery_authorization(
            stage=FOUNDATION_STAGE,
            repository_head=HEAD,
            subscription_id=SUBSCRIPTION_ID,
            target_resource_group_id=TARGET,
            cleanup_automation_account_id=CLEANUP_ACCOUNT,
            cleanup_deadline_utc="2026-08-12T22:15:00Z",
            now_utc=NOW,
            api_image_digest=IMAGE,
        )


def test_proof_five_is_rejected_before_authorization() -> None:
    with pytest.raises(
        ScannerBridgeRecoveryError,
        match="scanner-proof-execution-ceiling-exceeded",
    ):
        build_scanner_bridge_recovery_authorization(
            stage=PROOF_STAGE,
            repository_head=HEAD,
            subscription_id=SUBSCRIPTION_ID,
            target_resource_group_id=TARGET,
            cleanup_automation_account_id=CLEANUP_ACCOUNT,
            cleanup_deadline_utc="2026-08-12T22:15:00Z",
            now_utc=NOW,
            api_image_digest=IMAGE,
            build_input_sha256=BUILD_INPUT,
            proof_execution_ordinal=5,
        )


def test_short_cleanup_window_is_rejected_before_authorization() -> None:
    with pytest.raises(
        ScannerBridgeRecoveryError,
        match="scanner-bridge-cleanup-window-insufficient",
    ):
        build_scanner_bridge_recovery_authorization(
            stage=FOUNDATION_STAGE,
            repository_head=HEAD,
            subscription_id=SUBSCRIPTION_ID,
            target_resource_group_id=TARGET,
            cleanup_automation_account_id=CLEANUP_ACCOUNT,
            cleanup_deadline_utc="2026-08-06T19:00:00Z",
            now_utc=NOW,
        )


def test_foundation_adapter_consumes_authorization_and_maps_only_foundation_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    deployments = _install_common_fakes(monkeypatch, authorization, calls)

    result = ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
    )

    assert result["status"] == "scanner-bridge-foundation-reconciled"
    assert result["authorization-consumed"] is True
    assert result["public-access-enabled"] is False
    assert result["tag-write-authorized-for-worker"] is False
    assert len(deployments) == 1
    deployment = deployments[0]
    assert deployment["stage"] == FOUNDATION_STAGE
    assert deployment["runtime_config"] is None
    assert deployment["cleanup_at"] == DEADLINE
    assert deployment["expected_cost"] == 3_110
    assert deployment["maximum_cost"] == 20_607
    assert deployment["ledger"]["ledgerIntegritySha256"] == (
        authorization.authorizationIntegritySha256
    )
    receipt = json.loads(
        (tmp_path / adapter_module.FOUNDATION_RECEIPT_FILE).read_text(encoding="utf-8")
    )
    assert receipt["replayDecision"] == "deny"
    assert receipt["stage"] == FOUNDATION_STAGE


def test_foundation_output_cannot_reach_proof_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)
    values = _outputs(authorization)
    values["scannerBridgeProofJobName"] = "unexpected-proof"
    monkeypatch.setattr(adapter_module, "_read_deployment_outputs", lambda **_kwargs: values)
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-foundation-proof-authority-reachable",
    ):
        ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head=HEAD,
        )


def test_ambiguous_foundation_deployment_reconciles_without_duplicate_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    deployments = _install_common_fakes(monkeypatch, authorization, calls)

    def ambiguous(**kwargs: object) -> None:
        deployments.append(kwargs)
        raise managed_binding_lifecycle.AzureCommandError("azure-command-nonzero")

    monkeypatch.setattr(managed_binding_lifecycle, "_deploy_stage", ambiguous)
    result = ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
    )
    assert result["status"] == "scanner-bridge-foundation-reconciled"
    assert len(deployments) == 1


def test_private_endpoint_recovery_consumes_one_grant_without_foundation_redeploy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE)
    calls: list[str] = []
    deployments = _install_common_fakes(monkeypatch, authorization, calls)
    state: dict[str, JsonValue] = {
        "endpointProvisioningState": "Failed",
        "integritySha256": "8" * 64,
    }
    monkeypatch.setattr(
        adapter_module,
        "_exact_monitor_private_endpoint_recovery_state",
        lambda _authorization: calls.append("endpoint-preflight") or state,
    )
    monkeypatch.setattr(
        adapter_module,
        "_repair_exact_monitor_private_endpoint",
        lambda _authorization: (
            calls.append("endpoint-repair")
            or {
                "endpointMutationIssued": True,
                "preRecoveryIntegritySha256": "8" * 64,
                "postRecoveryIntegritySha256": "9" * 64,
                "zoneGroupMutationIssued": True,
            }
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_monitor_private_tls_path",
        lambda _workspace: calls.append("private-tls") or "a" * 64,
    )

    result = ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
    )

    assert result["marker"] == "STAGING_FOUNDATION_AUTHORITATIVE"
    assert result["authorization-consumed"] is True
    assert result["scanner-proof-execution-count"] == 0
    assert result["cost-envelope-unchanged"] is True
    assert result["dns-resolution-private"] is True
    assert result["tls-path-proved"] is True
    assert deployments == []
    assert "compile" not in calls
    assert "deploy" not in calls
    assert calls.index("endpoint-preflight") < calls.index("endpoint-repair")
    assert calls.index("endpoint-repair") < calls.index("foundation:True")
    assert calls.index("foundation:True") < calls.index("private-tls")
    receipt = json.loads(
        (tmp_path / adapter_module.PRIVATE_ENDPOINT_RECOVERY_RECEIPT_FILE).read_text(
            encoding="utf-8"
        )
    )
    assert receipt["stage"] == PRIVATE_ENDPOINT_RECOVERY_STAGE
    assert receipt["replayDecision"] == "deny"


def test_private_endpoint_recovery_cannot_reach_unrelated_mutation_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE)
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)
    monkeypatch.setattr(
        adapter_module,
        "_exact_monitor_private_endpoint_recovery_state",
        lambda _authorization: {"integritySha256": "8" * 64},
    )
    monkeypatch.setattr(
        adapter_module,
        "_repair_exact_monitor_private_endpoint",
        lambda _authorization: {
            "endpointMutationIssued": True,
            "preRecoveryIntegritySha256": "8" * 64,
            "postRecoveryIntegritySha256": "9" * 64,
            "zoneGroupMutationIssued": True,
        },
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_monitor_private_tls_path",
        lambda _workspace: "a" * 64,
    )

    def prohibited(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unrelated mutation path was reachable")

    for symbol in (
        "_deploy_stage",
        "_post_secret",
        "_prebuild_api_image",
        "_publish_api_image",
        "_publish_api_image_stage",
        "_cleanup",
    ):
        monkeypatch.setattr(managed_binding_lifecycle, symbol, prohibited)
    monkeypatch.setattr(adapter_module, "_start_one_execution", prohibited)

    result = ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
    )
    assert result["scanner-proof-execution-count"] == 0


def test_exact_private_endpoint_repair_reconciles_ambiguous_write_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE)
    failed: dict[str, JsonValue] = {
        "endpointProvisioningState": "Failed",
        "endpointTags": {},
        "integritySha256": "1" * 64,
        "networkInterfaceProvisioningState": "Succeeded",
        "pendingConnectionCount": 0,
        "privateDnsZoneGroupProvisioningState": None,
    }
    endpoint_recovered = {
        **failed,
        "endpointProvisioningState": "Succeeded",
        "integritySha256": "2" * 64,
    }
    fully_recovered = {
        **endpoint_recovered,
        "integritySha256": "3" * 64,
        "privateDnsZoneGroupProvisioningState": "Succeeded",
    }
    states = iter((failed, endpoint_recovered, fully_recovered))
    monkeypatch.setattr(
        adapter_module,
        "_exact_monitor_private_endpoint_recovery_state",
        lambda _authorization: next(states),
    )
    monkeypatch.setattr(
        adapter_module,
        "_monitor_private_endpoint_write_body",
        lambda *_args: {"endpoint": "body"},
    )
    monkeypatch.setattr(
        adapter_module,
        "_monitor_private_dns_zone_group_write_body",
        lambda *_args: {"zoneGroup": "body"},
    )
    writes: list[tuple[str, Mapping[str, JsonValue]]] = []

    def write(
        resource_id: str,
        _api_version: str,
        body: Mapping[str, JsonValue],
    ) -> dict[str, JsonValue]:
        writes.append((resource_id, body))
        if len(writes) == 1:
            raise managed_binding_lifecycle.AzureCommandError("internalservererror")
        return {"id": resource_id, "provisioningState": "Succeeded"}

    waits: list[str | None] = []
    monkeypatch.setattr(adapter_module, "_rest_put", write)
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_monitor_private_endpoint",
        lambda _authorization, *, ambiguous_error_code: waits.append(ambiguous_error_code),
    )
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_monitor_private_dns_zone_group",
        lambda _authorization, *, ambiguous_error_code: waits.append(ambiguous_error_code),
    )

    result = adapter_module._repair_exact_monitor_private_endpoint(authorization)

    assert len(writes) == 2
    assert writes[0] == (authorization.monitorPrivateEndpointId, {"endpoint": "body"})
    assert writes[1] == (
        f"{authorization.monitorPrivateEndpointId}/privateDnsZoneGroups/default",
        {"zoneGroup": "body"},
    )
    assert waits == ["internalservererror", None]
    assert result["endpointMutationIssued"] is True
    assert result["zoneGroupMutationIssued"] is True


def test_exact_private_endpoint_repair_safely_adopts_authoritative_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PRIVATE_ENDPOINT_RECOVERY_STAGE)
    succeeded: dict[str, JsonValue] = {
        "endpointProvisioningState": "Succeeded",
        "integritySha256": "3" * 64,
        "networkInterfaceProvisioningState": "Succeeded",
        "pendingConnectionCount": 0,
        "privateDnsZoneGroupProvisioningState": "Succeeded",
    }
    monkeypatch.setattr(
        adapter_module,
        "_exact_monitor_private_endpoint_recovery_state",
        lambda _authorization: succeeded,
    )
    monkeypatch.setattr(
        adapter_module,
        "_rest_put",
        lambda *_args, **_kwargs: pytest.fail("adoption must not issue a write"),
    )

    result = adapter_module._repair_exact_monitor_private_endpoint(authorization)

    assert result["endpointMutationIssued"] is False
    assert result["zoneGroupMutationIssued"] is False


def test_proof_executes_once_then_removes_residue_and_writes_typed_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PROOF_STAGE)
    calls: list[str] = []
    deployments = _install_common_fakes(monkeypatch, authorization, calls)
    monkeypatch.setattr(
        adapter_module,
        "_proof_graph",
        lambda *_args, **_kwargs: calls.append("proof-graph") or "7" * 64,
    )
    monkeypatch.setattr(
        adapter_module,
        "_start_one_execution",
        lambda _authorization: calls.append("start") or "proof-execution",
    )
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_execution",
        lambda *_args, **_kwargs: (
            calls.append("wait")
            or {
                "name": "proof-execution",
                "status": "Succeeded",
                "startTime": "2026-08-06T14:20:00Z",
                "endTime": "2026-08-06T14:25:00Z",
            }
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_marker",
        lambda *_args: calls.append("marker") or _marker(),
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_proof_residue",
        lambda *_args: calls.append("residue") or "8" * 64,
    )
    evidence_path = tmp_path.parent / f"{tmp_path.name}-bridge-evidence.json"

    result = ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
        evidence_output=evidence_path,
    )

    assert result["marker"] == "SCANNER_RESULT_BRIDGE_PROVED"
    assert result["proof-execution-count"] == 1
    assert result["proof-residue-absent"] is True
    assert len(deployments) == 1
    assert deployments[0]["stage"] == PROOF_STAGE
    assert deployments[0]["runtime_config"] == {"apiImageDigest": IMAGE}
    assert calls.index("deploy") < calls.index("proof-graph")
    assert calls.index("proof-graph") < calls.index("rbac-propagation")
    assert calls.index("rbac-propagation") < calls.index("start")
    assert calls.index("start") < calls.index("marker")
    assert calls.index("marker") < calls.index("residue")
    assert calls.count("foundation:False") == 1
    assert calls.count("foundation:True") == 2
    decoded = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = deployment_evidence_from_mapping(decoded, now=NOW)
    assert evidence.control_plane_head == HEAD
    assert evidence.worker_tag_write_denied is True
    assert evidence.provider_owned_system_topic_preserved is True
    assert evidence.legacy_evidence.decision == "clean"


def test_failed_execution_preserves_exact_marker_before_residue_removal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PROOF_STAGE)
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)
    monkeypatch.setattr(adapter_module, "_proof_graph", lambda *_args, **_kwargs: "7" * 64)
    monkeypatch.setattr(adapter_module, "_start_one_execution", lambda _authorization: "proof")
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_execution",
        lambda *_args: {
            "name": "proof",
            "status": "Failed",
            "startTime": "2026-08-06T14:20:00Z",
            "endTime": "2026-08-06T14:25:00Z",
        },
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_failure_marker",
        lambda *_args, **_kwargs: (
            calls.append("failure-marker") or _failure_marker("scanner-blob-tags-key-missing")
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: calls.append("bounded-terminal-log") or "[]",
    )
    observation = _blob_tag_observation()
    monkeypatch.setattr(
        adapter_module,
        "_proof_blob_tag_observation",
        lambda *_args, **_kwargs: calls.append("blob-tag-observation") or observation,
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_marker",
        lambda *_args: pytest.fail("success marker must remain unreachable"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_proof_residue",
        lambda *_args: calls.append("residue") or "8" * 64,
    )
    evidence_path = tmp_path.parent / f"{tmp_path.name}-failure-evidence.json"

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-blob-tags-key-missing",
    ):
        ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head=HEAD,
            evidence_output=evidence_path,
        )

    assert calls.index("failure-marker") < calls.index("residue")
    assert calls.index("blob-tag-observation") < calls.index("residue")
    decoded = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert decoded["failureCode"] == "scanner-blob-tags-key-missing"
    assert decoded["executionStatus"] == "Failed"
    assert decoded["marker"] == "SCANNER_RESULT_BRIDGE_FAILED"
    assert decoded["blobTagObservation"] == observation
    assert decoded["schemaVersion"] == "mobius.scanner-result-bridge.failure-evidence.v3"
    assert decoded["blobTagObservationCount"] == 120
    assert decoded["proofExecutionCount"] == 1
    assert decoded["terminalEdge"] == "scanner-blob-tags-key-missing"
    assert decoded["finalBoundedErrorCode"] == "scanner-blob-tags-key-missing"
    assert decoded["scanFinishedComparison"] is None
    assert decoded["terminalLogSummary"] == {
        "maximumSerializedBytes": adapter_module.PROOF_LOG_OUTPUT_MAX_BYTES,
        "rawHistoryRetained": False,
        "retentionDecision": "final-integrity-bound-markers-only",
        "tailLineLimit": adapter_module.PROOF_LOG_TAIL_LINES,
    }
    assert len(evidence_path.read_bytes()) < adapter_module.FAILURE_EVIDENCE_MAX_BYTES
    assert decoded["failureEvidenceIntegritySha256"]


def test_failed_proof_still_revokes_all_temporary_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PROOF_STAGE)
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)
    monkeypatch.setattr(adapter_module, "_proof_graph", lambda *_args, **_kwargs: "7" * 64)
    monkeypatch.setattr(adapter_module, "_start_one_execution", lambda _authorization: "proof")
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_execution",
        lambda *_args: {
            "name": "proof",
            "status": "Succeeded",
            "startTime": "2026-08-06T14:20:00Z",
            "endTime": "2026-08-06T14:25:00Z",
        },
    )

    def marker_failure(*_args: object) -> dict[str, str]:
        raise ScannerBridgeRecoveryExecutionError("scanner-proof-marker-malformed")

    monkeypatch.setattr(adapter_module, "_proof_marker", marker_failure)
    monkeypatch.setattr(
        adapter_module,
        "_remove_proof_residue",
        lambda *_args: calls.append("residue") or "8" * 64,
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-marker-malformed",
    ):
        ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head=HEAD,
            evidence_output=tmp_path.parent / f"{tmp_path.name}-evidence.json",
        )

    assert calls.count("residue") == 1


def test_failed_proof_graph_still_revokes_all_temporary_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PROOF_STAGE)
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)

    def graph_failure(*_args: object, **_kwargs: object) -> str:
        raise ScannerBridgeRecoveryExecutionError("scanner-proof-job-readback-unproved")

    monkeypatch.setattr(adapter_module, "_verify_proof_graph", graph_failure)
    monkeypatch.setattr(
        adapter_module,
        "_start_one_execution",
        lambda _authorization: pytest.fail("proof execution must remain unreachable"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_proof_residue",
        lambda *_args: calls.append("residue") or "8" * 64,
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-job-readback-unproved",
    ):
        ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head=HEAD,
            evidence_output=tmp_path.parent / f"{tmp_path.name}-evidence.json",
        )

    assert calls.count("residue") == 1


def test_graph_azure_error_is_attributed_after_temporary_authority_revocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization(PROOF_STAGE)
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)
    monkeypatch.setattr(
        adapter_module,
        "_verify_proof_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            managed_binding_lifecycle.AzureCommandError("authorizationfailed")
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_proof_residue",
        lambda *_args: calls.append("residue") or "8" * 64,
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-graph-azure-authorizationfailed",
    ):
        ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head=HEAD,
            evidence_output=tmp_path.parent / f"{tmp_path.name}-evidence.json",
        )

    assert calls.count("residue") == 1


def test_proof_graph_accepts_only_resource_id_casing_differences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    readback = _readback()
    assignment_id = _outputs(authorization)["scannerBridgeTemporaryRoleAssignmentId"]
    assert isinstance(assignment_id, str)
    role_definition_name = str(authorization.proofRoleDefinitionId).rsplit("/", 1)[-1]
    expected_permissions: list[JsonValue] = [
        {
            "actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/read"],
            "dataActions": [
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/deleteBlobVersion/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/permanentDelete/action",
                "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read",
            ],
            "condition": None,
            "conditionVersion": None,
            "notActions": [],
            "notDataActions": [],
        }
    ]
    job: dict[str, JsonValue] = {
        "id": str(authorization.proofJobId).replace("/resourceGroups/", "/resourcegroups/"),
        "triggerType": "Manual",
        "retryLimit": 0,
        "replicaTimeout": adapter_module.PROOF_REPLICA_TIMEOUT_SECONDS,
        "parallelism": 1,
        "completionCount": 1,
        "image": authorization.apiImageDigest,
        "container": adapter_module.PROOF_CONTAINER,
        "command": ["python"],
        "args": [
            "-m",
            "scripts.scanner_bridge_probe",
            "--max-attempts",
            "120",
            "--delay-seconds",
            "30",
        ],
        "environment": [
            {
                "name": "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL",
                "value": "https://stmobius7711564669.blob.core.windows.net/",
            },
            {
                "name": "OPENCANVAS_AZURE_QUARANTINE_CONTAINER",
                "value": "quarantine",
            },
            {"name": "OPENCANVAS_AZURE_CLEAN_CONTAINER", "value": "clean"},
            {
                "name": "OPENCANVAS_AZURE_REJECTED_CONTAINER",
                "value": "rejected",
            },
            {
                "name": "OPENCANVAS_AZURE_RETAINED_CONTAINER",
                "value": "retained",
            },
            {
                "name": "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID",
                "value": readback.worker_client_id,
            },
            {
                "name": "OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID",
                "value": readback.workspace_customer_id,
            },
            {
                "name": "OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT",
                "value": "https://api.loganalytics.azure.com",
            },
            {
                "name": "OPENCANVAS_SCANNER_BRIDGE_PROOF_SEED",
                "value": authorization.authorizationIntegritySha256,
            },
        ],
        "identityIds": [
            authorization.workerIdentityId.replace("/resourceGroups/", "/resourcegroups/")
        ],
    }
    role: dict[str, JsonValue] = {
        "id": (
            f"{SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/"
            f"{role_definition_name}"
        ),
        "roleName": "Mobius77 Temporary Scanner Bridge Probe",
        "assignableScopes": [
            authorization.targetResourceGroupId.replace("/resourceGroups/", "/resourcegroups/")
        ],
        "permissions": expected_permissions,
    }
    assignment: dict[str, JsonValue] = {
        "id": assignment_id.replace("/resourceGroups/", "/resourcegroups/"),
        "principalId": readback.worker_principal_id.upper(),
        "roleDefinitionId": (
            f"{SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/"
            f"{role_definition_name}"
        ),
    }

    def read_resource(resource_id: str, *_args: object) -> dict[str, JsonValue]:
        if resource_id.casefold() == str(authorization.proofJobId).casefold():
            return job
        if resource_id.casefold() == str(authorization.proofRoleDefinitionId).casefold():
            return role
        if resource_id.casefold() == assignment_id.casefold():
            return assignment
        pytest.fail("unexpected proof resource readback")

    monkeypatch.setattr(adapter_module, "_rest_get", read_resource)
    monkeypatch.setattr(adapter_module, "_grants_tag_write", lambda _role: False)

    integrity = adapter_module._proof_graph(
        authorization,
        assignment_id=assignment_id,
        worker_principal_id=readback.worker_principal_id,
        worker_client_id=readback.worker_client_id,
        workspace_customer_id=readback.workspace_customer_id,
    )
    assert len(integrity) == 64

    permission = role["permissions"]
    assert isinstance(permission, list) and isinstance(permission[0], dict)
    permission[0]["condition"] = "@Resource[Microsoft.Storage/storageAccounts:name]"
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-role-definition-readback-unproved",
    ):
        adapter_module._proof_graph(
            authorization,
            assignment_id=assignment_id,
            worker_principal_id=readback.worker_principal_id,
            worker_client_id=readback.worker_client_id,
            workspace_customer_id=readback.workspace_customer_id,
        )
    permission[0]["condition"] = None

    job["identityIds"] = [f"{TARGET}/providers/Microsoft.ManagedIdentity/other"]
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-job-readback-unproved",
    ):
        adapter_module._proof_graph(
            authorization,
            assignment_id=assignment_id,
            worker_principal_id=readback.worker_principal_id,
            worker_client_id=readback.worker_client_id,
            workspace_customer_id=readback.workspace_customer_id,
        )


def test_proof_graph_retries_only_ambiguous_or_absent_azure_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    attempts = 0

    def read_graph(*_args: object, **_kwargs: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise managed_binding_lifecycle.AzureCommandError("roledefinitiondoesnotexist")
        return "7" * 64

    monkeypatch.setattr(adapter_module, "_proof_graph", read_graph)
    monkeypatch.setattr(adapter_module.time, "sleep", lambda _delay: None)
    assert (
        adapter_module._verify_proof_graph(
            authorization,
            assignment_id="assignment",
            worker_principal_id=WORKER_PRINCIPAL,
            worker_client_id="client",
            workspace_customer_id="workspace",
        )
        == "7" * 64
    )
    assert attempts == 2

    monkeypatch.setattr(
        adapter_module,
        "_proof_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            managed_binding_lifecycle.AzureCommandError("authorizationfailed")
        ),
    )
    with pytest.raises(managed_binding_lifecycle.AzureCommandError) as error:
        adapter_module._verify_proof_graph(
            authorization,
            assignment_id="assignment",
            worker_principal_id=WORKER_PRINCIPAL,
            worker_client_id="client",
            workspace_customer_id="workspace",
        )
    assert error.value.sanitized_azure_error_code == "authorizationfailed"


def test_proof_execution_waits_for_bounded_rbac_propagation_while_graph_stays_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    readback = _readback()
    assignment_id = _outputs(authorization)["scannerBridgeTemporaryRoleAssignmentId"]
    assert isinstance(assignment_id, str)
    monotonic = iter((0.0, 0.0, 0.0, 900.0, 900.0))
    graph_calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(adapter_module.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(adapter_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        adapter_module,
        "_proof_graph",
        lambda *_args, **_kwargs: graph_calls.append("readback") or "7" * 64,
    )

    integrity = adapter_module._wait_for_proof_rbac_propagation(
        authorization,
        assignment_id=assignment_id,
        worker_principal_id=readback.worker_principal_id,
        worker_client_id=readback.worker_client_id,
        workspace_customer_id=readback.workspace_customer_id,
    )

    assert integrity == "7" * 64
    assert graph_calls == ["readback", "readback"]
    assert sleeps == [adapter_module.PROOF_RBAC_POLL_SECONDS]


def test_prohibited_lifecycle_image_application_migration_and_cleanup_operations_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    _install_common_fakes(monkeypatch, authorization, calls)

    def prohibited(*_args: object, **_kwargs: object) -> None:
        pytest.fail("prohibited lifecycle operation was reached")

    for symbol in (
        "_prebuild_api_image",
        "_publish_api_image",
        "_publish_api_image_stage",
        "_post_secret",
        "_private_path_stage",
        "_cleanup",
    ):
        monkeypatch.setattr(managed_binding_lifecycle, symbol, prohibited)
    monkeypatch.setattr(
        "preflight.milestone_7_7.managed_binding_contracts.build_authorization_ledger",
        prohibited,
    )
    ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW).execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
    )


def test_authorization_replay_is_rejected_before_second_deployment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    deployments = _install_common_fakes(monkeypatch, authorization, calls)
    adapter = ProductionScannerBridgeRecoveryAdapter(clock=lambda: NOW)
    adapter.execute(
        authorization=authorization,
        receipt_directory=tmp_path,
        expected_repository_head=HEAD,
    )
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-bridge-authorization-already-consumed",
    ):
        adapter.execute(
            authorization=authorization,
            receipt_directory=tmp_path,
            expected_repository_head=HEAD,
        )
    assert len(deployments) == 1


def test_ambiguous_job_start_reconciles_without_second_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    rows = iter(
        (
            [],
            [
                {
                    "name": "proof-execution",
                    "status": "Running",
                    "startTime": "2026-08-06T14:20:00Z",
                    "endTime": None,
                }
            ],
        )
    )
    attempts: list[tuple[str, ...]] = []
    monkeypatch.setattr(adapter_module, "_job_execution_rows", lambda _auth: next(rows))

    def ambiguous(argv: tuple[str, ...], **_kwargs: object) -> JsonValue:
        attempts.append(argv)
        raise managed_binding_lifecycle.AzureCommandError("azure-command-nonzero")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", ambiguous)
    assert adapter_module._start_one_execution(authorization) == "proof-execution"
    assert len(attempts) == 1


def test_proof_residue_removal_never_deletes_role_definition_as_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    assignment = (
        f"{authorization.storageAccountId}/blobServices/default/containers/quarantine/"
        "providers/Microsoft.Authorization/roleAssignments/"
        "77777777-aaaa-4bbb-8ccc-888888888888"
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_delete_assignment",
        lambda _sub, value: calls.append(("assignment", value)),
    )
    monkeypatch.setattr(
        adapter_module,
        "_delete_rest_resource",
        lambda value, _api: calls.append(("resource", value)),
    )
    monkeypatch.setattr(adapter_module, "_wait_absent", lambda *_args: None)
    adapter_module._remove_proof_residue(authorization, assignment)
    assert calls == [
        ("assignment", assignment),
        ("resource", authorization.proofJobId),
        ("resource", authorization.proofRoleDefinitionId),
    ]
    assert "/roleDefinitions/" not in calls[0][1]


def test_exact_resource_delete_retries_after_ambiguous_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def delete(_argv: tuple[str, ...], **_kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise managed_binding_lifecycle.AzureCommandError("roledefinitionhasassignments")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", delete)
    monkeypatch.setattr(adapter_module, "_resource_absent", lambda *_args: False)
    monkeypatch.setattr(adapter_module.time, "sleep", lambda _delay: None)
    adapter_module._delete_rest_resource("exact-resource", adapter_module.ROLE_API_VERSION)
    assert attempts == 2


def test_embedded_role_assignment_not_found_is_authoritative_absence() -> None:
    stderr = bytearray(
        b'ERROR: Not Found({"error":{"code":"RoleAssignmentNotFound","message":"absent"}})'
    )
    code = managed_binding_lifecycle._sanitized_azure_error_code(bytearray(), stderr)
    assert code == "roleassignmentnotfound"
    assert adapter_module._not_found(managed_binding_lifecycle.AzureCommandError(code))
    role_stderr = bytearray(
        b'ERROR: Bad Request({"error":{"code":"RoleDefinitionDoesNotExist","message":"absent"}})'
    )
    role_code = managed_binding_lifecycle._sanitized_azure_error_code(bytearray(), role_stderr)
    assert role_code == "roledefinitiondoesnotexist"
    assert adapter_module._not_found(managed_binding_lifecycle.AzureCommandError(role_code))
    job_stderr = bytearray(
        b'ERROR: Not Found({"error":{"code":"ContainerAppsJobNotFound","message":"absent"}})'
    )
    job_code = managed_binding_lifecycle._sanitized_azure_error_code(bytearray(), job_stderr)
    assert job_code == "containerappsjobnotfound"
    assert adapter_module._not_found(managed_binding_lifecycle.AzureCommandError(job_code))
    assert not adapter_module._not_found(
        managed_binding_lifecycle.AzureCommandError("authorizationfailed")
    )


def test_log_parser_accepts_only_one_complete_sanitized_marker() -> None:
    marker = _marker()
    payload = json.dumps([{"TimeStamp": "redacted", "Log": json.dumps(marker)}])
    assert adapter_module._find_marker(payload, "SCANNER_RESULT_BRIDGE_PROVED") == marker
    assert adapter_module._find_marker('{"marker":"wrong"}', "SCANNER_RESULT_BRIDGE_PROVED") is None


def test_log_envelope_accepts_direct_object_array_and_exact_azure_prefix() -> None:
    marker = _marker()
    serialized = json.dumps(marker, separators=(",", ":"), sort_keys=True)

    assert adapter_module._find_marker(serialized, "SCANNER_RESULT_BRIDGE_PROVED") == marker
    assert adapter_module._find_marker(f"[{serialized}]", "SCANNER_RESULT_BRIDGE_PROVED") == marker
    assert adapter_module._find_marker(f"F {serialized}", "SCANNER_RESULT_BRIDGE_PROVED") == marker


@pytest.mark.parametrize(
    "prefix",
    [
        "garbage ",
        "F F ",
        "I ",
        "FF ",
        "F  ",
    ],
)
def test_log_envelope_rejects_arbitrary_or_multiple_prefixes(prefix: str) -> None:
    marker = json.dumps(_marker(), separators=(",", ":"), sort_keys=True)

    assert adapter_module._find_marker(f"{prefix}{marker}", "SCANNER_RESULT_BRIDGE_PROVED") is None


def test_log_envelope_rejects_invalid_or_oversized_json_boundedly() -> None:
    assert adapter_module._find_marker("F {invalid", "SCANNER_RESULT_BRIDGE_PROVED") is None
    oversized = "F " + "[" + (" " * adapter_module.PROOF_LOG_OUTPUT_MAX_BYTES) + "]"
    assert adapter_module._find_marker(oversized, "SCANNER_RESULT_BRIDGE_PROVED") is None


def test_success_marker_parser_preserves_exact_bounded_terminal_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker()
    payload = json.dumps([{"TimeStamp": "redacted", "Log": json.dumps(marker)}])
    monkeypatch.setattr(adapter_module, "_proof_log_output", lambda *_args: payload)

    parsed = adapter_module._proof_marker(
        _authorization(PROOF_STAGE),
        "proof-execution",
    )

    comparison = cast(dict[str, JsonValue], parsed["scanFinishedComparison"])
    blob_timestamp = cast(dict[str, JsonValue], comparison["blobTagsTimestamp"])
    log_timestamp = cast(dict[str, JsonValue], comparison["logAnalyticsTimestamp"])
    observation = cast(dict[str, JsonValue], parsed["blobTagObservation"])
    assert parsed == marker
    assert parsed["schemaVersion"] == "mobius.scanner-result-bridge.proof.v2"
    assert comparison["comparisonDecision"] == "equal-common-precision"
    assert comparison["exactInstantEqual"] is True
    assert comparison["commonPrecisionEqual"] is True
    assert comparison["logAnalyticsMinusBlobTagsMicroseconds"] == 0
    assert blob_timestamp["rawValue"] == "2026-08-06T14:25:00Z"
    assert blob_timestamp["canonicalUtc"] == "2026-08-06T14:25:00Z"
    assert log_timestamp["rawValue"] == "2026-08-06T14:25:00Z"
    assert log_timestamp["canonicalUtc"] == "2026-08-06T14:25:00Z"
    assert observation["exactComparisonDecision"] == "accepted"
    assert observation["requiredKeysMissing"] == []
    assert observation["unexpectedKeys"] == []
    assert observation["differentBlobVersion"] is False
    assert len(json.dumps(parsed, separators=(",", ":"), sort_keys=True).encode()) < (
        adapter_module.PROOF_LOG_OUTPUT_MAX_BYTES
    )


def test_runtime_success_marker_is_consumed_by_the_production_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import scanner_bridge_probe

    expected = _marker()
    body = {key: value for key, value in expected.items() if key != "markerIntegritySha256"}
    runtime_marker = scanner_bridge_probe._success_marker(cast(dict[str, object], body))
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(runtime_marker),
    )

    assert runtime_marker == expected
    assert adapter_module._proof_marker(_authorization(PROOF_STAGE), "proof-execution") == expected


def test_success_marker_rejects_missing_raw_timestamp_even_with_recomputed_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker()
    comparison = dict(cast(dict[str, JsonValue], marker["scanFinishedComparison"]))
    blob_timestamp = dict(cast(dict[str, JsonValue], comparison["blobTagsTimestamp"]))
    blob_timestamp.pop("rawValue")
    comparison["blobTagsTimestamp"] = blob_timestamp
    comparison_body = {key: value for key, value in comparison.items() if key != "integritySha256"}
    comparison["integritySha256"] = adapter_module._scanner_runtime_hash(
        comparison_body,
        "mobius.scanner-bridge.scan-finished-comparison.v2",
    )
    marker["scanFinishedComparison"] = comparison
    marker_body = {key: value for key, value in marker.items() if key != "markerIntegritySha256"}
    marker["markerIntegritySha256"] = adapter_module._scanner_runtime_hash(
        marker_body,
        "mobius.scanner-bridge.proof-success-marker.v2",
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(marker),
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-scan-finished-evidence-malformed",
    ):
        adapter_module._proof_marker(_authorization(PROOF_STAGE), "proof-execution")


def test_success_marker_rejects_nonzero_delta_without_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _marker()
    comparison = dict(cast(dict[str, JsonValue], marker["scanFinishedComparison"]))
    comparison["comparisonDecision"] = "different-common-precision"
    comparison["logAnalyticsMinusBlobTagsMicroseconds"] = 1
    comparison_body = {key: value for key, value in comparison.items() if key != "integritySha256"}
    comparison["integritySha256"] = adapter_module._scanner_runtime_hash(
        comparison_body,
        "mobius.scanner-bridge.scan-finished-comparison.v2",
    )
    marker["scanFinishedComparison"] = comparison
    marker_body = {key: value for key, value in marker.items() if key != "markerIntegritySha256"}
    marker["markerIntegritySha256"] = adapter_module._scanner_runtime_hash(
        marker_body,
        "mobius.scanner-bridge.proof-success-marker.v2",
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(marker),
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-scan-finished-evidence-malformed",
    ):
        adapter_module._proof_marker(_authorization(PROOF_STAGE), "proof-execution")


def test_success_marker_integrity_is_deterministic_and_history_free() -> None:
    first = _marker()
    second = _marker()

    assert first == second
    assert first["blobTagObservationCount"] == 3
    assert "blobTagObservationHistory" not in first
    body = {key: value for key, value in first.items() if key != "markerIntegritySha256"}
    assert first["markerIntegritySha256"] == adapter_module._scanner_runtime_hash(
        body,
        "mobius.scanner-bridge.proof-success-marker.v2",
    )


def test_large_repeated_history_is_reduced_to_one_bounded_terminal_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = _blob_tag_observation(
        decision="accepted",
        returned=(adapter_module.BLOB_RESULT_TAG, adapter_module.BLOB_SCAN_TIME_TAG),
    )
    failure = _failure_marker("scanner-correlation-scan-finished-mismatch")
    full_history = [
        {"Log": json.dumps(accepted, separators=(",", ":"), sort_keys=True)} for _ in range(5_000)
    ]
    full_history.append({"Log": json.dumps(failure, separators=(",", ":"), sort_keys=True)})
    bounded = json.dumps(full_history[-adapter_module.PROOF_LOG_TAIL_LINES :])
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> str:
        calls.append(argv)
        return bounded

    monkeypatch.setattr(managed_binding_lifecycle, "_run", run)
    output = adapter_module._proof_log_output(_authorization(PROOF_STAGE), "proof-execution")

    assert len(json.dumps(full_history).encode()) > managed_binding_lifecycle.MAXIMUM_OUTPUT_BYTES
    assert len(output.encode()) < adapter_module.PROOF_LOG_OUTPUT_MAX_BYTES
    assert calls[0][calls[0].index("--tail") + 1] == str(adapter_module.PROOF_LOG_TAIL_LINES)
    assert (
        adapter_module._proof_failure_marker(
            _authorization(PROOF_STAGE),
            "proof-execution",
            log_output=output,
        )
        == failure
    )
    assert (
        adapter_module._proof_blob_tag_observation(
            _authorization(PROOF_STAGE),
            "proof-execution",
            failure_code="scanner-correlation-scan-finished-mismatch",
            log_output=output,
        )
        == accepted
    )
    assert len(calls) == 1


def test_failure_log_parser_accepts_only_sanitized_exact_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _failure_marker("scanner-blob-tag-scan-time-invalid")
    payload = json.dumps([{"TimeStamp": "redacted", "Log": json.dumps(marker)}])
    monkeypatch.setattr(adapter_module, "_proof_log_output", lambda *_args: payload)
    assert adapter_module._proof_failure_marker(_authorization(PROOF_STAGE), "proof") == marker

    malformed = {**marker, "failureCode": "secret bearing failure"}
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(malformed),
    )
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-failure-marker-malformed",
    ):
        adapter_module._proof_failure_marker(_authorization(PROOF_STAGE), "proof")


def test_timestamp_mismatch_artifact_is_bounded_complete_and_deterministic(
    tmp_path: Path,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    marker = _failure_marker("scanner-correlation-scan-finished-mismatch")
    observation = _blob_tag_observation(
        decision="accepted",
        returned=(adapter_module.BLOB_RESULT_TAG, adapter_module.BLOB_SCAN_TIME_TAG),
    )
    execution = {
        "name": "proof",
        "status": "Failed",
        "startTime": "2026-08-06T14:20:00Z",
        "endTime": "2026-08-06T14:25:00Z",
    }
    first = tmp_path.parent / f"{tmp_path.name}-first.json"
    second = tmp_path.parent / f"{tmp_path.name}-second.json"

    for path in (first, second):
        adapter_module._write_failure_evidence(
            path,
            authorization=authorization,
            execution_name="proof",
            execution=execution,
            marker=marker,
            blob_tag_observation=observation,
            observed_at=NOW,
        )

    assert first.read_bytes() == second.read_bytes()
    assert len(first.read_bytes()) < adapter_module.FAILURE_EVIDENCE_MAX_BYTES
    decoded = json.loads(first.read_text(encoding="utf-8"))
    comparison = decoded["scanFinishedComparison"]
    assert comparison["blobTagsTimestamp"]["rawValue"] == ("2026-08-06T14:24:59.999999Z")
    assert comparison["logAnalyticsTimestamp"]["rawValue"] == ("2026-08-06T14:25:00Z")
    assert comparison["logAnalyticsMinusBlobTagsMicroseconds"] == 1
    assert comparison["correlationIdSha256"] == "2" * 64
    assert comparison["uriComparison"] == "matched"
    assert comparison["etagComparison"] == "matched"
    assert decoded["blobTagObservationCount"] == 120
    assert decoded["finalBoundedErrorCode"] == ("scanner-correlation-scan-finished-mismatch")
    body = {key: value for key, value in decoded.items() if key != "failureEvidenceIntegritySha256"}
    assert decoded["failureEvidenceIntegritySha256"] == adapter_module._canonical_hash(
        body,
        "mobius.scanner-bridge.failure-evidence.v3",
    )


def test_timestamp_diagnostic_cannot_drop_the_raw_value_needed_for_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _failure_marker("scanner-correlation-scan-finished-mismatch")
    terminal = dict(cast(dict[str, JsonValue], marker["terminalEvidence"]))
    blob_timestamp = dict(cast(dict[str, JsonValue], terminal["blobTagsTimestamp"]))
    blob_timestamp.pop("rawValue")
    terminal["blobTagsTimestamp"] = blob_timestamp
    terminal_body = {key: value for key, value in terminal.items() if key != "integritySha256"}
    terminal["integritySha256"] = adapter_module._scanner_runtime_hash(
        terminal_body,
        "mobius.scanner-bridge.scan-finished-comparison.v2",
    )
    marker["terminalEvidence"] = terminal
    marker_body = {key: value for key, value in marker.items() if key != "markerIntegritySha256"}
    marker["markerIntegritySha256"] = adapter_module._scanner_runtime_hash(
        marker_body,
        "mobius.scanner-bridge.proof-failure-marker.v2",
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(marker),
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-scan-finished-evidence-malformed",
    ):
        adapter_module._proof_failure_marker(_authorization(PROOF_STAGE), "proof-execution")


def test_blob_tag_observation_parser_retains_latest_integrity_bound_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = _blob_tag_observation(
        decision="accepted",
        returned=(
            adapter_module.BLOB_RESULT_TAG,
            adapter_module.BLOB_SCAN_TIME_TAG,
        ),
    )
    failed = _blob_tag_observation()
    payload = json.dumps(
        [
            {"TimeStamp": "redacted", "Log": json.dumps(accepted)},
            {"TimeStamp": "redacted", "Log": json.dumps(failed)},
        ]
    )
    monkeypatch.setattr(adapter_module, "_proof_log_output", lambda *_args: payload)

    assert (
        adapter_module._proof_blob_tag_observation(
            _authorization(PROOF_STAGE),
            "proof",
            failure_code="scanner-blob-tags-key-missing",
        )
        == failed
    )


def test_blob_tag_observation_parser_accepts_exact_producer_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_keys = (
        adapter_module.BLOB_RESULT_TAG,
        adapter_module.BLOB_SCAN_TIME_TAG,
    )
    marker = BlobTagReadObservation(
        queried_blob_version_id_sha256="2" * 64,
        queried_blob_uri_sha256="1" * 64,
        queried_etag_sha256="3" * 64,
        http_status=200,
        request_correlation_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        returned_tag_keys=expected_keys,
        required_keys_found=expected_keys,
        required_keys_missing=(),
        unexpected_keys=(),
        parser_normalization_path=adapter_module.BLOB_TAG_NORMALIZATION_PATH,
        exact_comparison_decision="accepted",
        response_empty=False,
        different_blob_version=False,
        response_version_id_sha256="5" * 64,
        response_etag_sha256="4" * 64,
        version_identity_path="response-version-id-and-etag",
    ).canonical()
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(marker),
    )

    assert (
        adapter_module._proof_blob_tag_observation(
            _authorization(PROOF_STAGE),
            "proof",
            failure_code="scanner-correlation-uri-mismatch",
        )
        == marker
    )


def test_blob_tag_observation_parser_rejects_newline_canonical_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _blob_tag_observation()
    body = {key: value for key, value in marker.items() if key != "integritySha256"}
    marker["integritySha256"] = adapter_module._canonical_hash(
        body,
        "mobius.scanner-bridge.blob-tag-observation.v1",
    )
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(marker),
    )

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-blob-tag-observation-integrity-unproved",
    ):
        adapter_module._proof_blob_tag_observation(
            _authorization(PROOF_STAGE),
            "proof",
            failure_code="scanner-blob-tags-key-missing",
        )


def test_blob_tag_observation_parser_rejects_missing_tampered_or_mismatched_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    monkeypatch.setattr(adapter_module, "_proof_log_output", lambda *_args: "[]")
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-blob-tag-observation-missing",
    ):
        adapter_module._proof_blob_tag_observation(
            authorization,
            "proof",
            failure_code="scanner-blob-tags-key-missing",
        )

    tampered = {**_blob_tag_observation(), "tagCount": 2}
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(tampered),
    )
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-blob-tag-observation-integrity-unproved",
    ):
        adapter_module._proof_blob_tag_observation(
            authorization,
            "proof",
            failure_code="scanner-blob-tags-key-missing",
        )

    mismatch = _blob_tag_observation()
    monkeypatch.setattr(
        adapter_module,
        "_proof_log_output",
        lambda *_args: json.dumps(mismatch),
    )
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-blob-tag-observation-failure-mismatch",
    ):
        adapter_module._proof_blob_tag_observation(
            authorization,
            "proof",
            failure_code="scanner-blob-tags-version-mismatch",
        )


def test_non_blob_failure_does_not_invent_blob_tag_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter_module, "_proof_log_output", lambda *_args: "[]")
    assert (
        adapter_module._proof_blob_tag_observation(
            _authorization(PROOF_STAGE),
            "proof",
            failure_code="scanner-correlation-uri-mismatch",
        )
        is None
    )


def test_private_dns_zone_group_requires_the_exact_authorized_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = f"{TARGET}/providers/Microsoft.Network/privateEndpoints/private"
    expected = frozenset(
        {
            f"{TARGET}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com",
            f"{TARGET}/providers/Microsoft.Network/privateDnsZones/"
            "privatelink.oms.opinsights.azure.com",
        }
    )
    group = f"{endpoint}/privateDnsZoneGroups/default"
    monkeypatch.setattr(
        adapter_module,
        "_rest_get",
        lambda *_args: {
            "id": group,
            "provisioningState": "Succeeded",
            "zoneIds": sorted(expected),
        },
    )
    assert (
        adapter_module._verify_private_dns_zone_group(
            private_endpoint_id=endpoint,
            expected_zone_ids=expected,
        )["id"]
        == group
    )

    monkeypatch.setattr(
        adapter_module,
        "_rest_get",
        lambda *_args: {
            "id": group,
            "provisioningState": "Succeeded",
            "zoneIds": [sorted(expected)[0]],
        },
    )
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-bridge-private-dns-zone-group-unproved",
    ):
        adapter_module._verify_private_dns_zone_group(
            private_endpoint_id=endpoint,
            expected_zone_ids=expected,
        )


@pytest.mark.parametrize("stage", [FOUNDATION_STAGE, PRIVATE_ENDPOINT_RECOVERY_STAGE])
def test_scanner_bridge_entry_point_invokes_production_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stage: str,
) -> None:
    authorization_path = tmp_path / "authorization.json"
    receipt_directory = tmp_path / "receipts"
    write_scanner_bridge_recovery_authorization(authorization_path, _authorization(stage))
    observed: dict[str, object] = {}

    def execute(**kwargs: object) -> dict[str, JsonValue]:
        observed.update(kwargs)
        return {"status": "scanner-bridge-foundation-reconciled"}

    monkeypatch.setattr(scanner_bridge_recovery, "execute_scanner_bridge_recovery", execute)
    assert (
        scanner_bridge_recovery.main(
            [
                "--authorization",
                str(authorization_path),
                "--receipt-directory",
                str(receipt_directory),
                "--repository-head",
                HEAD,
            ]
        )
        == 0
    )
    assert isinstance(observed["authorization"], ScannerBridgeRecoveryAuthorization)
    assert observed["authorization"].stage == stage
    assert observed["receipt_directory"] == receipt_directory
    assert json.loads(capsys.readouterr().out) == {"status": "scanner-bridge-foundation-reconciled"}


def test_authorization_serialization_contains_no_secret_or_complete_lifecycle_ledger() -> None:
    value = asdict(_authorization(PROOF_STAGE))
    serialized = json.dumps(value, sort_keys=True).casefold()
    assert "password" not in serialized
    assert "connectionstring" not in serialized
    assert "secretvalue" not in serialized
    assert "build_authorization_ledger" not in (
        build_scanner_bridge_recovery_authorization.__code__.co_names
    )


def test_authoritative_readback_uses_the_provider_data_scanner_resource_type() -> None:
    source = inspect.getsource(adapter_module._foundation_readback_once)
    assert "dataScanners/{DEFENDER_SCANNER}" in source
    assert "storageDataScanners" not in source


def test_authoritative_readback_requires_exact_proof_console_diagnostic() -> None:
    source = inspect.getsource(adapter_module._foundation_readback_once)
    assert "require_proof_console_diagnostic" in source
    assert "authorization.logAnalyticsWorkspaceId" in source
    assert "_validate_proof_console_diagnostic" in source


def test_proof_console_diagnostic_accepts_azure_canonical_readback() -> None:
    diagnostic_id = f"{TARGET}/providers/Microsoft.Insights/diagnosticSettings/proof"
    adapter_module._validate_proof_console_diagnostic(
        {
            "id": diagnostic_id.upper(),
            "workspaceId": f"{TARGET}/providers/Microsoft.OperationalInsights/workspaces/law",
            "destinationType": None,
            "logs": [
                {"category": "ContainerAppConsoleLogs", "enabled": True},
                {"category": "ContainerAppSystemLogs", "enabled": False},
            ],
        },
        diagnostic_id=diagnostic_id,
        workspace_id=f"{TARGET}/providers/Microsoft.OperationalInsights/workspaces/law",
    )


@pytest.mark.parametrize(
    ("destination_type", "logs"),
    [
        (
            "AzureDiagnostics",
            [{"category": "ContainerAppConsoleLogs", "enabled": True}],
        ),
        (
            None,
            [
                {"category": "ContainerAppConsoleLogs", "enabled": True},
                {"category": "ContainerAppSystemLogs", "enabled": True},
            ],
        ),
        (
            None,
            [
                {"category": "ContainerAppConsoleLogs", "enabled": True},
                {"category": "ContainerAppConsoleLogs", "enabled": False},
            ],
        ),
        (None, [{"category": "ContainerAppConsoleLogs", "enabled": "true"}]),
    ],
    ids=("wrong-destination", "extra-enabled", "duplicate-category", "malformed-row"),
)
def test_proof_console_diagnostic_rejects_semantic_drift(
    destination_type: JsonValue,
    logs: list[JsonValue],
) -> None:
    diagnostic_id = f"{TARGET}/providers/Microsoft.Insights/diagnosticSettings/proof"
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-console-diagnostic-unproved",
    ):
        adapter_module._validate_proof_console_diagnostic(
            {
                "id": diagnostic_id,
                "workspaceId": (f"{TARGET}/providers/Microsoft.OperationalInsights/workspaces/law"),
                "destinationType": destination_type,
                "logs": logs,
            },
            diagnostic_id=diagnostic_id,
            workspace_id=f"{TARGET}/providers/Microsoft.OperationalInsights/workspaces/law",
        )


def test_wait_for_execution_accepts_omitted_terminal_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    monkeypatch.setattr(
        adapter_module,
        "_job_execution_rows",
        lambda _authorization: [
            {
                "name": "proof",
                "status": "Failed",
                "startTime": "2026-08-07T04:34:41Z",
                "endTime": None,
            }
        ],
    )
    monkeypatch.setattr(adapter_module.time, "monotonic", lambda: 0.0)

    result = adapter_module._wait_for_execution(authorization, "proof")

    assert result["status"] == "Failed"
    assert result["startTime"] == "2026-08-07T04:34:41Z"
    assert result["endTime"] is None


def test_wait_for_execution_fails_closed_without_terminal_start_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(PROOF_STAGE)
    monotonic = iter([0.0, adapter_module.EXECUTION_PROPAGATION_SECONDS + 1.0])
    monkeypatch.setattr(
        adapter_module,
        "_job_execution_rows",
        lambda _authorization: [
            {
                "name": "proof",
                "status": "Failed",
                "startTime": None,
                "endTime": None,
            }
        ],
    )
    monkeypatch.setattr(adapter_module.time, "monotonic", lambda: next(monotonic))

    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-execution-terminal-time-unproved",
    ):
        adapter_module._wait_for_execution(authorization, "proof")


def test_proof_job_bounds_match_the_extended_service_window() -> None:
    module = Path("infra/milestone_7_7/modules/scanner-result-bridge.bicep").read_text(
        encoding="utf-8"
    )
    assert "replicaTimeout: 4200" in module
    assert "            '120'" in module
    assert adapter_module.PROOF_MAX_ATTEMPTS == 120
    assert adapter_module.PROOF_DELAY_SECONDS == 30
    assert adapter_module.PROOF_REPLICA_TIMEOUT_SECONDS == 4_200
    assert adapter_module.EXECUTION_PROPAGATION_SECONDS == 4_500.0


def test_storage_tag_writer_inventory_includes_inherited_and_nested_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = f"{TARGET}/providers/Microsoft.Storage/storageAccounts/stmobius7711564669"
    inherited = {
        "id": f"{SUBSCRIPTION}/providers/Microsoft.Authorization/roleAssignments/inherited",
        "principalId": "principal-inherited",
        "roleDefinitionId": f"{SUBSCRIPTION}/providers/Microsoft.Authorization/roles/reader",
        "scope": TARGET,
    }
    nested = {
        "id": f"{storage}/blobServices/default/containers/quarantine/providers/"
        "Microsoft.Authorization/roleAssignments/nested",
        "principalId": "principal-nested",
        "roleDefinitionId": f"{SUBSCRIPTION}/providers/Microsoft.Authorization/roles/custom",
        "scope": f"{storage}/blobServices/default/containers/quarantine",
    }
    unrelated = {
        "id": f"{TARGET}/providers/Microsoft.Authorization/roleAssignments/unrelated",
        "principalId": "principal-unrelated",
        "roleDefinitionId": f"{SUBSCRIPTION}/providers/Microsoft.Authorization/roles/reader",
        "scope": f"{TARGET}/providers/Microsoft.Storage/storageAccounts/other",
    }

    def rows(
        _subscription_id: str,
        *,
        principal_id: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, str]]:
        assert principal_id is None
        return [inherited] if scope == storage else [inherited, nested, unrelated]

    monkeypatch.setattr(adapter_module, "_role_assignment_rows", rows)
    assert adapter_module._storage_role_assignment_rows(SUBSCRIPTION_ID, storage) == [
        inherited,
        nested,
    ]
