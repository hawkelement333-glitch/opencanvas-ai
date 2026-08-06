from __future__ import annotations

import inspect
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infra.milestone_7_7 import scanner_bridge_recovery_adapter as adapter_module
from infra.milestone_7_7.scanner_bridge_recovery_adapter import (
    ProductionScannerBridgeRecoveryAdapter,
    ScannerBridgeRecoveryExecutionError,
)
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import scanner_bridge_recovery
from preflight.milestone_7_7.scanner_bridge_recovery import (
    FOUNDATION_ALLOWED_OPERATIONS,
    FOUNDATION_STAGE,
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

SUBSCRIPTION_ID = "11111111-2222-4333-8444-555555555555"
SUBSCRIPTION = f"/subscriptions/{SUBSCRIPTION_ID}"
TARGET = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-staging"
CLEANUP_ACCOUNT = (
    f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-cleanup-control/"
    "providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery"
)
NOW = datetime(2026, 8, 6, 17, 30, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 7, 5, 30, tzinfo=UTC)
HEAD = "a" * 40
IMAGE = "acrmobius7711564669.azurecr.io/opencanvas-api@sha256:" + "b" * 64
BUILD_INPUT = "c" * 64
WORKER_PRINCIPAL = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DEFENDER_SCANNER_ROLE = "cd50fd1f-0421-46f2-8cce-afc587dbcc77"


def _authorization(stage: str = FOUNDATION_STAGE) -> ScannerBridgeRecoveryAuthorization:
    return build_scanner_bridge_recovery_authorization(
        stage=stage,
        repository_head=HEAD,
        subscription_id=SUBSCRIPTION_ID,
        target_resource_group_id=TARGET,
        cleanup_automation_account_id=CLEANUP_ACCOUNT,
        cleanup_deadline_utc="2026-08-07T05:30:00Z",
        now_utc=NOW,
        api_image_digest=IMAGE if stage == PROOF_STAGE else None,
        build_input_sha256=BUILD_INPUT if stage == PROOF_STAGE else None,
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


def _marker() -> dict[str, str]:
    values = {
        "accountNameSha256": "0" * 64,
        "blobEvidenceSha256": "1" * 64,
        "blobTagResultSha256": "2" * 64,
        "blobUriSha256": "3" * 64,
        "completionTimeSha256": "4" * 64,
        "contentSha256": "5" * 64,
        "correlationIdSha256": "6" * 64,
        "dualSourceEvidenceSha256": "7" * 64,
        "etagSha256": "8" * 64,
        "logAnalyticsEvidenceSha256": "9" * 64,
        "logQuerySha256": "a" * 64,
        "privateDnsEvidenceSha256": "b" * 64,
        "providerVersionSha256": "c" * 64,
        "scanRequestIdSha256": "d" * 64,
        "storageResourceSha256": "e" * 64,
        "tlsEvidenceSha256": "f" * 64,
        "tlsHostnameSha256": "0" * 64,
    }
    return {
        **values,
        "decision": "clean",
        "marker": "SCANNER_RESULT_BRIDGE_PROVED",
        "residue": "canary-version-deleted",
        "schemaVersion": "mobius.scanner-result-bridge.proof.v1",
        "tlsVersion": "TLS1_3",
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
    monkeypatch.setattr(
        adapter_module,
        "_verify_foundation",
        lambda _authorization: calls.append("foundation") or _readback(),
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


def test_proof_authorization_binds_one_exact_immutable_image_and_execution() -> None:
    authorization = _authorization(PROOF_STAGE)
    assert PROOF_JOB == "caj-mobius77-scanner-proof"
    assert len(PROOF_JOB) <= 32
    assert authorization.allowedOperations == PROOF_ALLOWED_OPERATIONS
    assert authorization.apiImageDigest == IMAGE
    assert authorization.buildInputSha256 == BUILD_INPUT
    assert authorization.maximumProofExecutions == 1
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
            cleanup_deadline_utc="2026-08-07T05:30:00Z",
            now_utc=NOW,
            api_image_digest=IMAGE,
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
        lambda *_args: (
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
    assert calls.index("proof-graph") < calls.index("start")
    assert calls.index("start") < calls.index("marker")
    assert calls.index("marker") < calls.index("residue")
    decoded = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = deployment_evidence_from_mapping(decoded, now=NOW)
    assert evidence.control_plane_head == HEAD
    assert evidence.worker_tag_write_denied is True
    assert evidence.provider_owned_system_topic_preserved is True
    assert evidence.legacy_evidence.decision == "clean"


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
        "parallelism": 1,
        "completionCount": 1,
        "image": authorization.apiImageDigest,
        "container": adapter_module.PROOF_CONTAINER,
        "command": ["python"],
        "args": [
            "-m",
            "scripts.scanner_bridge_probe",
            "--max-attempts",
            "60",
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
    assert adapter_module._find_marker(payload) == marker
    assert adapter_module._find_marker('{"marker":"wrong"}') is None


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
        lambda *_args: {"id": group, "zoneIds": sorted(expected)},
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
        lambda *_args: {"id": group, "zoneIds": [sorted(expected)[0]]},
    )
    with pytest.raises(
        ScannerBridgeRecoveryExecutionError,
        match="scanner-bridge-private-dns-zone-group-unproved",
    ):
        adapter_module._verify_private_dns_zone_group(
            private_endpoint_id=endpoint,
            expected_zone_ids=expected,
        )


def test_scanner_bridge_entry_point_invokes_production_consumer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    authorization_path = tmp_path / "authorization.json"
    receipt_directory = tmp_path / "receipts"
    write_scanner_bridge_recovery_authorization(authorization_path, _authorization())
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
