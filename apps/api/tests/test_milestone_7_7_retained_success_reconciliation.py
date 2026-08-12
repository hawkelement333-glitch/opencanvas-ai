from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_7 import scanner_bridge_recovery_adapter as adapter
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import scanner_bridge_recovery as recovery
from preflight.milestone_7_7.scanner_bridge_recovery import (
    PROOF_STAGE,
    ScannerBridgeRecoveryAuthorization,
    build_scanner_bridge_recovery_authorization,
)
from preflight.milestone_7_7.scanner_result_bridge import (
    deployment_evidence_from_mapping,
)

SUBSCRIPTION_ID = "9f7f5a53-95a6-469e-9b95-e4072f0fd226"
SUBSCRIPTION = f"/subscriptions/{SUBSCRIPTION_ID}"
TARGET = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-staging"
CLEANUP_ACCOUNT = (
    f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-cleanup-control/"
    "providers/Microsoft.Automation/automationAccounts/aa-mobius77-cleanup-recovery"
)
ASSIGNMENT_ID = (
    f"{TARGET}/providers/Microsoft.Storage/storageAccounts/stmobius7711564669/"
    "blobServices/default/containers/quarantine/providers/"
    "Microsoft.Authorization/roleAssignments/de0da5d7-5596-5f69-889d-42adb87c8fa6"
)
NOW = datetime(2026, 8, 12, 9, 10, tzinfo=UTC)
CORRECTION_HEAD = "d" * 40
FIXTURE = Path(__file__).parent / "fixtures" / "milestone_7_7" / "proof4-success-marker.json"


def _authorization() -> ScannerBridgeRecoveryAuthorization:
    authorization = build_scanner_bridge_recovery_authorization(
        stage=PROOF_STAGE,
        repository_head=adapter.RETAINED_SUCCESS_SOURCE_HEAD,
        subscription_id=SUBSCRIPTION_ID,
        target_resource_group_id=TARGET,
        cleanup_automation_account_id=CLEANUP_ACCOUNT,
        cleanup_deadline_utc="2026-08-12T22:15:00Z",
        now_utc=datetime(2026, 8, 12, 8, 26, 48, tzinfo=UTC),
        api_image_digest=adapter.RETAINED_SUCCESS_IMAGE,
        build_input_sha256=adapter.RETAINED_SUCCESS_BUILD_INPUT,
        proof_execution_ordinal=4,
    )
    assert (
        authorization.authorizationIntegritySha256
        == adapter.RETAINED_SUCCESS_AUTHORIZATION_INTEGRITY
    )
    return authorization


def _marker() -> dict[str, JsonValue]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, JsonValue], value)


def _typed(values: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: {"type": "String", "value": value} for key, value in values.items()}


def _history(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> dict[str, JsonValue]:
    top_outputs: dict[str, JsonValue] = {
        "deploymentStage": PROOF_STAGE,
        "deploymentEnabled": False,
        "managedBindingDeploymentEnabled": True,
        "targetResourceGroupName": "rg-solarplexus-mobius-77-staging",
        "scannerBridgeFoundationDeployed": True,
        "scannerBridgeTransport": adapter.TRANSPORT,
        "scannerBridgeStorageAccountId": authorization.storageAccountId,
        "scannerBridgePrivateLinkScopeId": authorization.privateLinkScopeId,
        "scannerBridgePrivateEndpointId": authorization.monitorPrivateEndpointId,
        "scannerBridgeWorkerIdentityId": authorization.workerIdentityId,
        "scannerBridgeWorkerPrincipalId": "b8a5e782-edca-4df8-930a-1f8e42fc4dbd",
        "scannerBridgeWorkerTagWriteAuthorized": False,
        "defaultProvisioningAuthorized": False,
        "secretValueAccessAuthorized": False,
        "storageAccountUrl": "https://stmobius7711564669.blob.core.windows.net/",
        "scannerBridgeProofJobName": adapter.PROOF_JOB,
        "scannerBridgeProofJobId": authorization.proofJobId,
        "scannerBridgeTemporaryRoleId": authorization.proofRoleDefinitionId,
        "scannerBridgeTemporaryRoleAssignmentId": ASSIGNMENT_ID,
        "scannerBridgeProofImageDigest": authorization.apiImageDigest,
    }
    lifecycle_tags: dict[str, JsonValue] = {
        "mobius-cleanup-binding-sha256": authorization.authorizationIntegritySha256,
        "mobius-expires-at-utc": authorization.cleanupDeadlineUtc,
        "mobius-source-commit": authorization.repositoryHead,
    }
    nested_parameters: dict[str, JsonValue] = {
        "proofCanarySeed": authorization.authorizationIntegritySha256,
        "apiImageDigest": authorization.apiImageDigest,
        "scannerProofDeploymentEnabled": True,
        "deploymentEnabled": False,
        "managedBindingDeploymentEnabled": True,
        "targetResourceGroupId": authorization.targetResourceGroupId,
        "workerIdentityId": authorization.workerIdentityId,
        "lifecycleTags": lifecycle_tags,
    }
    nested_outputs: dict[str, JsonValue] = {
        "proofJobId": authorization.proofJobId,
        "temporaryProofRoleId": authorization.proofRoleDefinitionId,
        "temporaryProofRoleAssignmentId": ASSIGNMENT_ID,
        "proofDeploymentEnabled": True,
        "workerTagWriteAuthorized": False,
    }
    correlation = "9b6f58d4-1317-4b63-84fa-b2a8bb10cdb5"
    operations: list[JsonValue] = [
        {
            "id": authorization.proofJobId,
            "type": "Microsoft.App/jobs",
            "operation": "Create",
            "state": "Succeeded",
            "status": "OK",
            "timestamp": "2026-08-12T08:33:39.456299Z",
            "trackingId": "7f0a7abf-1b0c-436d-9d4f-339a26295375",
        },
        {
            "id": authorization.proofRoleDefinitionId,
            "type": "Microsoft.Authorization/roleDefinitions",
            "operation": "Create",
            "state": "Succeeded",
            "status": "Created",
            "timestamp": "2026-08-12T08:32:32.903760Z",
            "trackingId": "cc64ae59-6b27-4b63-9679-922d46468338",
        },
        {
            "id": ASSIGNMENT_ID,
            "type": "Microsoft.Authorization/roleAssignments",
            "operation": "Create",
            "state": "Succeeded",
            "status": "Created",
            "timestamp": "2026-08-12T08:32:32.903760Z",
            "trackingId": "5d9340a6-864c-4db7-b1f9-60821c926c18",
        },
    ]

    def activity(
        operation: str,
        resource_id: str,
        status: str,
        at: str,
    ) -> dict[str, JsonValue]:
        return {
            "operation": operation,
            "resourceId": resource_id,
            "status": status,
            "subStatus": "OK",
            "time": at,
            "correlationId": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        }

    activity_rows: list[JsonValue] = [
        activity(
            "Microsoft.App/jobs/start/action",
            cast(str, authorization.proofJobId),
            "Succeeded",
            "2026-08-12T08:50:50.6183959Z",
        ),
        activity(
            "Microsoft.App/jobs/getAuthToken/action",
            cast(str, authorization.proofJobId),
            "Succeeded",
            "2026-08-12T09:00:42.1432197Z",
        ),
        activity(
            "Microsoft.Authorization/roleAssignments/delete",
            ASSIGNMENT_ID,
            "Started",
            "2026-08-12T09:00:46.7604785Z",
        ),
        activity(
            "Microsoft.Authorization/roleAssignments/delete",
            ASSIGNMENT_ID,
            "Succeeded",
            "2026-08-12T09:00:48.9167362Z",
        ),
        activity(
            "Microsoft.Authorization/roleDefinitions/delete",
            cast(str, authorization.proofRoleDefinitionId),
            "Succeeded",
            "2026-08-12T09:01:03.2348713Z",
        ),
        activity(
            "Microsoft.App/jobs/delete",
            cast(str, authorization.proofJobId),
            "Succeeded",
            "2026-08-12T09:01:07.2416561Z",
        ),
    ]
    group = f"{adapter.RETAINED_SUCCESS_PROOF_EXECUTION}-2tsmh"
    marker_log = "F " + json.dumps(_marker(), separators=(",", ":"), sort_keys=True)
    summary: dict[str, JsonValue] = {
        "ContainerGroupName": group,
        "ContainerImage": authorization.apiImageDigest,
        "Failure": 0,
        "First": "2026-08-12T08:51:20.3488524Z",
        "Groups": 1,
        "Images": 1,
        "JobName": adapter.PROOF_JOB,
        "Last": "2026-08-12T09:00:23.0988375Z",
        "Rows": 19,
        "Success": 1,
    }
    marker_row: dict[str, JsonValue] = {
        "TimeGenerated": "2026-08-12T09:00:23.0988375Z",
        "IngestedAt": "2026-08-12T09:08:53.2961887Z",
        "JobName": adapter.PROOF_JOB,
        "ContainerGroupName": group,
        "ContainerName": adapter.PROOF_CONTAINER,
        "ContainerImage": authorization.apiImageDigest,
        "Stream": "stdout",
        "_ResourceId": (
            f"{TARGET}/providers/Microsoft.App/managedEnvironments/{adapter.MANAGED_ENVIRONMENT}"
        ),
        "Log": marker_log,
    }
    return {
        "activity": activity_rows,
        "consoleSummary": [summary],
        "deployment": {
            "name": adapter.RETAINED_SUCCESS_DEPLOYMENT,
            "id": f"{SUBSCRIPTION}/providers/Microsoft.Resources/deployments/x",
            "location": adapter.STAGING_LOCATION,
            "state": "Succeeded",
            "timestamp": "2026-08-12T08:34:02.992139Z",
            "correlationId": correlation,
            "templateHash": adapter.RETAINED_SUCCESS_DEPLOYMENT_TEMPLATE_HASH,
            "parameters": _typed(
                {
                    "authorizationLedgerSha256": (authorization.authorizationIntegritySha256),
                    "deploymentStage": PROOF_STAGE,
                    "apiImageDigest": authorization.apiImageDigest,
                    "cleanupAtUtc": authorization.cleanupDeadlineUtc,
                }
            ),
            "outputs": _typed(top_outputs),
        },
        "deploymentOperations": operations,
        "markerRows": [marker_row],
        "nestedDeployment": {
            "name": adapter.RETAINED_SUCCESS_NESTED_DEPLOYMENT,
            "id": f"{TARGET}/providers/Microsoft.Resources/deployments/y",
            "state": "Succeeded",
            "timestamp": "2026-08-12T08:33:59.354455Z",
            "correlationId": correlation,
            "templateHash": adapter.RETAINED_SUCCESS_NESTED_TEMPLATE_HASH,
            "parameters": _typed(nested_parameters),
            "outputs": _typed(nested_outputs),
        },
    }


def _foundation() -> adapter._FoundationReadback:
    return adapter._FoundationReadback(
        api_principal_id="11111111-aaaa-4bbb-8ccc-222222222222",
        worker_principal_id="b8a5e782-edca-4df8-930a-1f8e42fc4dbd",
        worker_client_id="e794c905-c9e8-4c5d-a05e-3c5626ad8cec",
        workspace_customer_id="df2bb7a1-9504-4a8d-9d3d-de421ea1b409",
        provider_topic_id=f"{TARGET}/providers/Microsoft.EventGrid/systemTopics/provider",
        provider_proof_integrity="1" * 64,
        diagnostic_proof_integrity="2" * 64,
        rbac_proof_integrity="3" * 64,
        tag_write_denial_integrity="4" * 64,
        private_path_control_plane_integrity="5" * 64,
        inventory_integrity="6" * 64,
    )


def test_terminal_execution_accepts_immediately_available_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _marker()
    monkeypatch.setattr(adapter, "_proof_marker", lambda *_args: expected)

    assert adapter._wait_for_proof_marker(_authorization(), "execution") == expected


def test_terminal_execution_waits_for_delayed_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _marker()
    calls = 0
    elapsed = [0.0]

    def marker(*_args: object) -> dict[str, JsonValue]:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise adapter.ScannerBridgeRecoveryExecutionError(
                "scanner-proof-success-marker-not-yet-ingested"
            )
        return expected

    monkeypatch.setattr(adapter, "_proof_marker", marker)
    monkeypatch.setattr(adapter.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        adapter.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    monkeypatch.setattr(adapter, "PROOF_DIAGNOSTIC_PROPAGATION_SECONDS", 10.0)
    monkeypatch.setattr(adapter, "PROOF_DIAGNOSTIC_POLL_SECONDS", 1.0)

    assert adapter._wait_for_proof_marker(_authorization(), "execution") == expected
    assert calls == 3
    assert elapsed[0] == 2.0


def test_terminal_execution_without_marker_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed = [0.0]

    def missing(*_args: object) -> dict[str, JsonValue]:
        raise adapter.ScannerBridgeRecoveryExecutionError(
            "scanner-proof-success-marker-not-yet-ingested"
        )

    monkeypatch.setattr(adapter, "_proof_marker", missing)
    monkeypatch.setattr(adapter.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        adapter.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    monkeypatch.setattr(adapter, "PROOF_DIAGNOSTIC_PROPAGATION_SECONDS", 2.0)
    monkeypatch.setattr(adapter, "PROOF_DIAGNOSTIC_POLL_SECONDS", 1.0)

    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-diagnostic-ingestion-incomplete",
    ):
        adapter._wait_for_proof_marker(_authorization(), "execution")


def test_malformed_marker_fails_without_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        adapter,
        "_proof_marker",
        lambda *_args: (_ for _ in ()).throw(
            adapter.ScannerBridgeRecoveryExecutionError("scanner-proof-marker-malformed")
        ),
    )
    monkeypatch.setattr(adapter.time, "sleep", sleeps.append)

    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-marker-malformed",
    ):
        adapter._wait_for_proof_marker(_authorization(), "execution")
    assert sleeps == []


def test_contradictory_terminal_marker_fails_closed() -> None:
    log = json.dumps(
        [
            _marker(),
            {"marker": "SCANNER_RESULT_BRIDGE_FAILED"},
        ],
        separators=(",", ":"),
    )
    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-contradictory-terminal-marker",
    ):
        adapter._proof_marker_from_log_output(log)


def test_exact_retained_proof_four_marker_passes_production_parser() -> None:
    parsed = adapter._proof_marker_from_log_output(
        "F " + json.dumps(_marker(), separators=(",", ":"))
    )

    assert parsed["markerIntegritySha256"] == adapter.RETAINED_SUCCESS_MARKER_INTEGRITY
    assert parsed["decision"] == "clean"
    assert parsed["tlsVersion"] == "TLS1_3"
    assert (
        cast(dict[str, JsonValue], parsed["blobTagObservation"])["exactComparisonDecision"]
        == "accepted"
    )


def test_retained_success_rejects_wrong_execution() -> None:
    authorization = _authorization()
    history = _history(authorization)
    marker_row = cast(list[dict[str, JsonValue]], history["markerRows"])[0]
    summary = cast(list[dict[str, JsonValue]], history["consoleSummary"])[0]
    marker_row["ContainerGroupName"] = "caj-mobius77-scanner-proof-wrong-2tsmh"
    summary["ContainerGroupName"] = marker_row["ContainerGroupName"]

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        adapter._validate_retained_success_history(
            authorization=authorization,
            readback=history,
            proof_resources_absent=True,
        )


def test_retained_success_rejects_wrong_image() -> None:
    authorization = _authorization()
    history = _history(authorization)
    wrong = adapter.RETAINED_SUCCESS_IMAGE.replace("f4cf", "0000", 1)
    cast(list[dict[str, JsonValue]], history["markerRows"])[0]["ContainerImage"] = wrong
    cast(list[dict[str, JsonValue]], history["consoleSummary"])[0]["ContainerImage"] = wrong

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        adapter._validate_retained_success_history(
            authorization=authorization,
            readback=history,
            proof_resources_absent=True,
        )


@pytest.mark.parametrize(
    "authorization",
    [
        replace(_authorization(), authorizationIntegritySha256="0" * 64),
        replace(_authorization(), proofExecutionOrdinal=3),
    ],
)
def test_retained_reconciliation_rejects_wrong_authorization_or_ordinal(
    authorization: ScannerBridgeRecoveryAuthorization,
    tmp_path: Path,
) -> None:
    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-retained-authorization-invalid",
    ):
        adapter.reconcile_retained_successful_scanner_proof(
            authorization=authorization,
            authorization_receipt_directory=tmp_path,
            lifecycle_ledger_path=tmp_path / "ledger.json",
            finalization_evidence_path=tmp_path / "finalization.json",
            correction_repository_head=CORRECTION_HEAD,
            binding_output=tmp_path / "binding.json",
            deployment_evidence_output=tmp_path / "deployment.json",
            now_utc=NOW,
        )


def test_retained_success_rejects_wrong_deployment_authorization_binding() -> None:
    authorization = _authorization()
    history = _history(authorization)
    nested = cast(dict[str, JsonValue], history["nestedDeployment"])
    parameters = cast(dict[str, dict[str, JsonValue]], nested["parameters"])
    parameters["proofCanarySeed"]["value"] = "0" * 64

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        adapter._validate_retained_success_history(
            authorization=authorization,
            readback=history,
            proof_resources_absent=True,
        )


def test_consumed_authorization_receipt_denies_replay(tmp_path: Path) -> None:
    authorization = _authorization()
    adapter._claim_authorization(
        authorization=authorization,
        receipt_directory=tmp_path,
        now_utc=datetime(2026, 8, 12, 8, 27, 1, tzinfo=UTC),
    )

    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-bridge-authorization-already-consumed",
    ):
        adapter._claim_authorization(
            authorization=authorization,
            receipt_directory=tmp_path,
            now_utc=datetime(2026, 8, 12, 8, 27, 2, tzinfo=UTC),
        )


def _install_reconciliation_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: ScannerBridgeRecoveryAuthorization,
) -> None:
    monkeypatch.setattr(adapter.lifecycle, "_verify_repository_state", lambda _head: None)
    monkeypatch.setattr(adapter.lifecycle, "_account_binding", lambda _now: SUBSCRIPTION_ID)
    monkeypatch.setattr(adapter.lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(adapter.lifecycle, "_verified_cost", lambda: (100, 200))
    monkeypatch.setattr(adapter.lifecycle, "_verify_cleanup_control", lambda *_args: "principal")
    monkeypatch.setattr(adapter.lifecycle, "_verify_cleanup_target_role", lambda *_args: None)
    monkeypatch.setattr(
        adapter,
        "_validate_managed_binding",
        lambda _authorization: {"cleanupExecution": {"cleanupContributorRoleDefinitionId": "role"}},
    )
    monkeypatch.setattr(adapter, "_verify_foundation", lambda *_args, **_kwargs: _foundation())
    monkeypatch.setattr(
        adapter,
        "_retained_success_readback",
        lambda *_args, **_kwargs: _history(authorization),
    )
    monkeypatch.setattr(adapter, "_resource_absent", lambda *_args: True)
    monkeypatch.setattr(
        adapter,
        "_validate_consumed_proof_receipt",
        lambda **_kwargs: {"receiptIntegritySha256": "7" * 64},
    )
    monkeypatch.setattr(
        adapter,
        "_validate_retained_publication_binding",
        lambda **_kwargs: {
            "finalizationEvidenceIntegritySha256": "8" * 64,
            "ledgerIntegritySha256": "9" * 64,
        },
    )


def test_retained_proof_four_builds_serializes_and_loads_real_deployment_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = _authorization()
    _install_reconciliation_fakes(monkeypatch, authorization)
    binding = tmp_path / "proof4-retained-success.json"
    evidence_path = tmp_path / "scanner-deployment-evidence-v2.json"

    result = adapter.reconcile_retained_successful_scanner_proof(
        authorization=authorization,
        authorization_receipt_directory=tmp_path,
        lifecycle_ledger_path=tmp_path / "ledger.json",
        finalization_evidence_path=tmp_path / "finalization.json",
        correction_repository_head=CORRECTION_HEAD,
        binding_output=binding,
        deployment_evidence_output=evidence_path,
        now_utc=NOW,
    )

    decoded = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = deployment_evidence_from_mapping(decoded, now=NOW)
    assert result["marker"] == "PROOF_4_RETAINED_SUCCESS_EVIDENCE_BOUND"
    assert result["scanner-marker"] == "SCANNER_RESULT_BRIDGE_PROVED"
    assert evidence.control_plane_head == CORRECTION_HEAD
    assert evidence.proof_execution_id_sha256 == adapter._hash_text(
        adapter.RETAINED_SUCCESS_PROOF_EXECUTION
    )
    assert evidence.legacy_evidence.decision == "clean"
    assert binding.is_file()


def test_retained_success_reconciliation_is_one_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = _authorization()
    _install_reconciliation_fakes(monkeypatch, authorization)
    kwargs = {
        "authorization": authorization,
        "authorization_receipt_directory": tmp_path,
        "lifecycle_ledger_path": tmp_path / "ledger.json",
        "finalization_evidence_path": tmp_path / "finalization.json",
        "correction_repository_head": CORRECTION_HEAD,
        "binding_output": tmp_path / "proof4-retained-success.json",
        "deployment_evidence_output": tmp_path / "scanner-deployment-evidence-v2.json",
        "now_utc": NOW,
    }
    adapter.reconcile_retained_successful_scanner_proof(**kwargs)

    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-retained-success-already-reconciled",
    ):
        adapter.reconcile_retained_successful_scanner_proof(**kwargs)


def test_retained_success_is_wired_to_existing_scanner_recovery_entry_point(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization = _authorization()
    recovery.write_scanner_bridge_recovery_authorization(
        tmp_path / "authorization.json",
        authorization,
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        recovery,
        "reconcile_successful_scanner_bridge_recovery",
        lambda **kwargs: (
            calls.append(kwargs) or {"marker": "PROOF_4_RETAINED_SUCCESS_EVIDENCE_BOUND"}
        ),
    )

    exit_code = recovery.main(
        [
            "--authorization",
            str(tmp_path / "authorization.json"),
            "--receipt-directory",
            str(tmp_path / "receipts"),
            "--repository-head",
            CORRECTION_HEAD,
            "--evidence-output",
            str(tmp_path / "deployment.json"),
            "--retained-success",
            "--lifecycle-ledger",
            str(tmp_path / "ledger.json"),
            "--finalization-evidence",
            str(tmp_path / "finalization.json"),
            "--binding-output",
            str(tmp_path / "binding.json"),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0]["authorization"] == authorization
    assert calls[0]["correction_repository_head"] == CORRECTION_HEAD
    assert json.loads(capsys.readouterr().out)["marker"] == (
        "PROOF_4_RETAINED_SUCCESS_EVIDENCE_BOUND"
    )
