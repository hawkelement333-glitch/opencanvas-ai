from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from infra.milestone_7_7 import scanner_canary_cleanup_adapter as adapter_module
from infra.milestone_7_7.scanner_canary_cleanup_adapter import (
    ProductionScannerCanaryCleanupAdapter,
    ScannerCanaryCleanupExecutionError,
)
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import managed_binding_execution
from preflight.milestone_7_7 import scanner_canary_cleanup as cleanup_preflight
from preflight.milestone_7_7.scanner_canary_cleanup import (
    ALLOWED_OPERATIONS,
    CLEANUP_DEADLINE_UTC,
    DETERMINISTIC_BLOB_NAME,
    DETERMINISTIC_OBJECT_ID,
    DETERMINISTIC_OBJECT_VERSION_ID,
    EXPECTED_PROVIDER_VERSION_SHA256,
    IMAGE_EIGHT_DIGEST,
    WORKER_PRINCIPAL_ID,
    ScannerCanaryCleanupAuthorization,
    ScannerCanaryCleanupError,
    build_scanner_canary_cleanup_authorization,
    load_scanner_canary_cleanup_authorization,
    scanner_canary_cleanup_authorization_integrity,
    validate_scanner_canary_cleanup_authorization,
    write_scanner_canary_cleanup_authorization,
)

SUBSCRIPTION_ID = "11111111-2222-4333-8444-555555555555"
HEAD = "a" * 40
NOW = datetime(2026, 8, 8, 5, 30, tzinfo=UTC)


def _authorization() -> ScannerCanaryCleanupAuthorization:
    return build_scanner_canary_cleanup_authorization(
        repository_head=HEAD,
        subscription_id=SUBSCRIPTION_ID,
        cleanup_deadline_utc=CLEANUP_DEADLINE_UTC,
        cleanup_principal_id=WORKER_PRINCIPAL_ID,
        now_utc=NOW,
    )


def _resign(
    authorization: ScannerCanaryCleanupAuthorization,
) -> ScannerCanaryCleanupAuthorization:
    unsigned = replace(authorization, authorizationIntegritySha256="")
    return replace(
        unsigned,
        authorizationIntegritySha256=(scanner_canary_cleanup_authorization_integrity(unsigned)),
    )


def _job_marker(
    authorization: ScannerCanaryCleanupAuthorization,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "afterActiveVersionCount": 0,
        "afterDeletedVersionCount": 0,
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "beforeActiveVersionCount": 1,
        "beforeDeletedVersionCount": 0,
        "cleanupDeadlineUtc": authorization.cleanupDeadlineUtc,
        "cleanupInvocationCount": 1,
        "containerDeletePerformed": False,
        "deterministicBlobNameSha256": hashlib.sha256(
            authorization.deterministicBlobName.encode()
        ).hexdigest(),
        "deterministicObjectId": authorization.deterministicObjectId,
        "deterministicObjectVersionId": authorization.deterministicObjectVersionId,
        "expectedProviderVersionSha256": authorization.expectedProviderVersionSha256,
        "httpStatusAfter": 200,
        "httpStatusBefore": 200,
        "marker": "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED",
        "multipleVersionDeletePerformed": False,
        "paginationAfter": False,
        "paginationBefore": False,
        "requestIdSha256After": "1" * 64,
        "requestIdSha256Before": "2" * 64,
        "responseBodySha256After": "3" * 64,
        "responseBodySha256Before": "4" * 64,
        "schemaVersion": "mobius.milestone-7.7.scanner-canary-cleanup-job.v1",
        "wildcardUsed": False,
    }
    return {
        **body,
        "integritySha256": hashlib.sha256(
            adapter_module.JOB_MARKER_DOMAIN
            + json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
    }


def test_exact_canary_cleanup_authorization_is_single_use_and_exact() -> None:
    authorization = _authorization()

    assert cleanup_preflight.CLEANUP_JOB == "caj-mobius77-i8-canary-cleanup"
    assert len(cleanup_preflight.CLEANUP_JOB) <= 32
    assert authorization.deterministicBlobName == DETERMINISTIC_BLOB_NAME
    assert authorization.deterministicObjectId == DETERMINISTIC_OBJECT_ID
    assert authorization.deterministicObjectVersionId == DETERMINISTIC_OBJECT_VERSION_ID
    assert authorization.expectedProviderVersionSha256 == EXPECTED_PROVIDER_VERSION_SHA256
    assert authorization.apiImageDigest == IMAGE_EIGHT_DIGEST
    assert authorization.cleanupPrincipalId == WORKER_PRINCIPAL_ID
    assert authorization.cleanupScope == authorization.quarantineContainerId
    assert authorization.maximumExecutions == 1
    assert authorization.allowedOperations == ALLOWED_OPERATIONS
    assert authorization.wildcardDeleteAuthorized is False
    assert authorization.containerDeleteAuthorized is False
    assert authorization.multipleVersionDeleteAuthorized is False
    assert authorization.blobWriteAuthorized is False
    assert authorization.scannerProofAuthorized is False
    assert authorization.applicationDeploymentAuthorized is False
    assert authorization.migrationAuthorized is False
    assert authorization.resourceGroupCleanupAuthorized is False
    assert (
        validate_scanner_canary_cleanup_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW,
        )
        is authorization
    )


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"deterministicBlobName": "*"}, "authorization-scope-invalid"),
        (
            {"deterministicObjectVersionId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
            "authorization-scope-invalid",
        ),
        ({"expectedProviderVersionSha256": "0" * 64}, "authorization-scope-invalid"),
        (
            {"cleanupPrincipalId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
            "authorization-scope-invalid",
        ),
        ({"cleanupScope": "/subscriptions/wrong"}, "authorization-scope-invalid"),
        ({"cleanupDeadlineUtc": "2026-08-08T12:30:00Z"}, "authorization-scope-invalid"),
        ({"storageAccountId": "/subscriptions/wrong"}, "authorization-scope-invalid"),
        ({"cleanupRoleDefinitionId": "/subscriptions/wrong"}, "authorization-scope-invalid"),
        ({"cleanupRoleAssignmentId": "/subscriptions/wrong"}, "authorization-scope-invalid"),
        ({"cleanupJobId": "/subscriptions/wrong"}, "authorization-scope-invalid"),
        ({"apiImageDigest": IMAGE_EIGHT_DIGEST[:-1] + "0"}, "authorization-scope-invalid"),
        ({"repositoryHead": "b" * 40}, "authorization-scope-invalid"),
        ({"maximumExecutions": 2}, "authorization-scope-invalid"),
        ({"wildcardDeleteAuthorized": True}, "authorization-scope-invalid"),
        ({"containerDeleteAuthorized": True}, "authorization-scope-invalid"),
        ({"multipleVersionDeleteAuthorized": True}, "authorization-scope-invalid"),
        ({"blobWriteAuthorized": True}, "authorization-scope-invalid"),
        ({"scannerProofAuthorized": True}, "authorization-scope-invalid"),
        ({"applicationDeploymentAuthorized": True}, "authorization-scope-invalid"),
        ({"migrationAuthorized": True}, "authorization-scope-invalid"),
    ],
)
def test_exact_canary_cleanup_authorization_rejects_scope_expansion(
    changes: dict[str, Any], expected_code: str
) -> None:
    tampered = _resign(replace(_authorization(), **changes))

    with pytest.raises(ScannerCanaryCleanupError, match=expected_code):
        validate_scanner_canary_cleanup_authorization(
            tampered,
            expected_repository_head=HEAD,
            now_utc=NOW,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository_head": "wrong"},
        {"subscription_id": "wrong"},
        {"cleanup_deadline_utc": "2026-08-08T12:30:00Z"},
        {"cleanup_principal_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
    ],
)
def test_builder_rejects_wrong_identity_or_boundary(kwargs: dict[str, str]) -> None:
    arguments = {
        "repository_head": HEAD,
        "subscription_id": SUBSCRIPTION_ID,
        "cleanup_deadline_utc": CLEANUP_DEADLINE_UTC,
        "cleanup_principal_id": WORKER_PRINCIPAL_ID,
        "now_utc": NOW,
    }
    arguments.update(kwargs)

    with pytest.raises(ScannerCanaryCleanupError):
        build_scanner_canary_cleanup_authorization(**arguments)


def test_authorization_round_trip_is_closed(tmp_path: Path) -> None:
    path = tmp_path / "authorization.json"
    authorization = _authorization()

    write_scanner_canary_cleanup_authorization(path, authorization)

    assert load_scanner_canary_cleanup_authorization(path) == authorization
    malformed = asdict(authorization)
    malformed["extra"] = True
    path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ScannerCanaryCleanupError, match="fields-invalid"):
        load_scanner_canary_cleanup_authorization(path)


def test_expired_authorization_is_rejected() -> None:
    authorization = _authorization()

    with pytest.raises(ScannerCanaryCleanupError, match="authorization-expired"):
        validate_scanner_canary_cleanup_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=datetime(2026, 8, 8, 6, 1, tzinfo=UTC),
        )


def test_temporary_role_is_delete_only_and_not_generalized() -> None:
    authorization = _authorization()
    body = adapter_module._role_definition_body(authorization)
    permissions = body["properties"]
    assert isinstance(permissions, dict)
    serialized = json.dumps(body, separators=(",", ":"), sort_keys=True)

    assert "deleteBlobVersion/action" in serialized
    assert "permanentDelete/action" in serialized
    assert "containers/blobs/delete" in serialized
    assert "containers/delete" not in serialized
    assert "containers/blobs/write" not in serialized
    assert "containers/blobs/add/action" not in serialized
    assert "containers/blobs/tags/write" not in serialized
    assert "*" not in serialized


def test_cleanup_job_reuses_exact_proof_cleanup_without_proof_or_write() -> None:
    source = adapter_module._CLEANUP_PROGRAM
    job = adapter_module._job_body(_authorization(), "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    serialized = json.dumps(job, separators=(",", ":"), sort_keys=True)

    assert "from scripts.scanner_bridge_probe import _remove_exact_canary" in source
    assert "await _remove_exact_canary(" in source
    assert "put_immutable" not in source
    assert "_put_exact_canary" not in source
    assert "scripts.scanner_bridge_probe --" not in serialized
    assert "scanner-proof" not in serialized
    assert DETERMINISTIC_BLOB_NAME in serialized
    assert DETERMINISTIC_OBJECT_VERSION_ID in serialized
    assert EXPECTED_PROVIDER_VERSION_SHA256 in serialized
    assert '"parallelism":1' in serialized
    assert '"replicaCompletionCount":1' in serialized
    assert '"replicaRetryLimit":0' in serialized


def test_cleanup_marker_accepts_nested_azure_log_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    marker = _job_marker(authorization)
    log = json.dumps({"TimeStamp": "now", "Log": "F " + json.dumps(marker)})
    monkeypatch.setattr(adapter_module, "_log_output", lambda *_args: log)

    assert adapter_module._cleanup_marker(authorization, "execution") == marker


def test_ambiguous_put_reconciles_without_duplicate_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []

    def ambiguous(argv: tuple[str, ...], **_kwargs: object) -> None:
        calls.append(argv)
        raise managed_binding_lifecycle.AzureCommandError("azure-command-nonzero")

    monkeypatch.setattr(managed_binding_lifecycle, "_run", ambiguous)
    monkeypatch.setattr(
        adapter_module.scanner_adapter,
        "_rest_get",
        lambda resource_id, *_args: {"id": resource_id},
    )
    body = tmp_path / "body.json"
    body.write_text("{}", encoding="utf-8")

    result = adapter_module._put_and_reconcile(
        resource_id="/subscriptions/exact",
        api_version="2025-01-01",
        body_path=body,
        query="{id:id}",
    )

    assert result == {"id": "/subscriptions/exact"}
    assert len(calls) == 1
    assert calls[0][0:4] == ("az", "rest", "--method", "put")


def test_duplicate_execution_is_rejected_without_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter_module,
        "_execution_rows",
        lambda _authorization: [
            {
                "name": "existing",
                "status": "Succeeded",
                "startTime": "2026-08-08T05:00:00Z",
                "endTime": "2026-08-08T05:01:00Z",
            }
        ],
    )

    with pytest.raises(ScannerCanaryCleanupExecutionError, match="duplicate-execution"):
        adapter_module._start_one_execution(_authorization())


def test_preexisting_temporary_resource_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter_module.scanner_adapter,
        "_resource_absent",
        lambda *_args: False,
    )

    with pytest.raises(ScannerCanaryCleanupExecutionError, match="temporary-resource-present"):
        adapter_module._verify_temporary_resources_absent(_authorization())


def _install_execution_fakes(
    monkeypatch: pytest.MonkeyPatch,
    authorization: ScannerCanaryCleanupAuthorization,
    calls: list[str],
) -> None:
    monkeypatch.setattr(managed_binding_lifecycle, "_verify_repository_state", lambda _head: None)
    monkeypatch.setattr(managed_binding_lifecycle, "_account_binding", lambda _now: SUBSCRIPTION_ID)
    monkeypatch.setattr(managed_binding_lifecycle, "_group_exists", lambda *_args: True)
    monkeypatch.setattr(managed_binding_lifecycle, "_verified_cost", lambda: (3_110, 20_607))
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_verify_cleanup_control",
        lambda *_args: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    )
    monkeypatch.setattr(
        managed_binding_lifecycle, "_verify_cleanup_target_role", lambda *_args: None
    )
    monkeypatch.setattr(adapter_module, "_validate_managed_binding", lambda _auth: None)
    monkeypatch.setattr(
        adapter_module,
        "_verify_proof_resources_absent",
        lambda _auth: calls.append("proof-absent"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_temporary_resources_absent",
        lambda _auth: calls.append("temporary-absent"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_verify_permanent_reader",
        lambda _auth: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    )
    monkeypatch.setattr(
        adapter_module,
        "_create_cleanup_graph",
        lambda *_args, **_kwargs: calls.append("create"),
    )
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_cleanup_rbac",
        lambda *_args, **_kwargs: calls.append("rbac") or "1" * 64,
    )
    monkeypatch.setattr(
        adapter_module,
        "_start_one_execution",
        lambda _auth: calls.append("start") or "execution-one",
    )
    monkeypatch.setattr(
        adapter_module,
        "_wait_for_execution",
        lambda *_args: (
            calls.append("wait")
            or {
                "name": "execution-one",
                "status": "Succeeded",
                "startTime": "2026-08-08T05:31:00Z",
                "endTime": "2026-08-08T05:32:00Z",
            }
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "_cleanup_marker",
        lambda *_args: calls.append("marker") or _job_marker(authorization),
    )
    monkeypatch.setattr(
        adapter_module,
        "_remove_cleanup_resources",
        lambda _auth: calls.append("revoke") or "2" * 64,
    )
    monkeypatch.setattr(
        managed_binding_execution,
        "build_authorization_ledger",
        lambda *_args, **_kwargs: pytest.fail("complete lifecycle ledger is unreachable"),
    )


def test_production_adapter_consumes_once_then_revokes_before_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    _install_execution_fakes(monkeypatch, authorization, calls)
    adapter = ProductionScannerCanaryCleanupAdapter(clock=lambda: NOW)
    receipts = tmp_path / "receipts"
    evidence = tmp_path / "evidence.json"

    result = adapter.execute(
        authorization=authorization,
        receipt_directory=receipts,
        expected_repository_head=HEAD,
        evidence_output=evidence,
    )

    assert result["marker"] == "IMAGE_EIGHT_CANARY_RESIDUE_CLEANED"
    assert result["authorization-consumed"] is True
    assert result["authority-revoked"] is True
    assert result["residue-absent"] is True
    assert result["temporary-cleanup-authority-absent"] is True
    assert evidence.is_file()
    assert (receipts / adapter_module.RECEIPT_FILE).is_file()
    assert calls.count("create") == 1
    assert calls.count("start") == 1
    assert calls.count("revoke") == 1
    assert calls.index("create") < calls.index("start") < calls.index("revoke")

    with pytest.raises(ScannerCanaryCleanupExecutionError, match="authorization-already-consumed"):
        adapter.execute(
            authorization=authorization,
            receipt_directory=receipts,
            expected_repository_head=HEAD,
            evidence_output=tmp_path / "second-evidence.json",
        )
    assert calls.count("create") == 1
    assert calls.count("start") == 1


def test_execution_entrypoint_uses_production_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    observed: list[dict[str, object]] = []

    class FakeAdapter:
        def execute(self, **kwargs: object) -> dict[str, JsonValue]:
            observed.append(kwargs)
            return {"status": "image-eight-canary-residue-cleaned"}

    monkeypatch.setattr(
        adapter_module,
        "ProductionScannerCanaryCleanupAdapter",
        FakeAdapter,
    )

    result = cleanup_preflight.execute_scanner_canary_cleanup(
        authorization=authorization,
        receipt_directory=tmp_path / "receipts",
        expected_repository_head=HEAD,
        evidence_output=tmp_path / "evidence.json",
    )

    assert result == {"status": "image-eight-canary-residue-cleaned"}
    assert observed == [
        {
            "authorization": authorization,
            "receipt_directory": tmp_path / "receipts",
            "expected_repository_head": HEAD,
            "evidence_output": tmp_path / "evidence.json",
        }
    ]


def test_cleanup_graph_failure_still_revokes_temporary_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    _install_execution_fakes(monkeypatch, authorization, calls)

    def fail_create(*_args: object, **_kwargs: object) -> None:
        calls.append("create")
        raise ScannerCanaryCleanupExecutionError("create-failed")

    monkeypatch.setattr(adapter_module, "_create_cleanup_graph", fail_create)

    with pytest.raises(ScannerCanaryCleanupExecutionError, match="create-failed"):
        ProductionScannerCanaryCleanupAdapter(clock=lambda: NOW).execute(
            authorization=authorization,
            receipt_directory=tmp_path / "receipts",
            expected_repository_head=HEAD,
            evidence_output=tmp_path / "evidence.json",
        )

    assert calls.count("create") == 1
    assert calls.count("revoke") == 1
    assert "start" not in calls


def test_production_adapter_has_no_image_or_application_execution_path() -> None:
    source = inspect.getsource(ProductionScannerCanaryCleanupAdapter.execute)
    module_source = inspect.getsource(adapter_module)

    assert "build_authorization_ledger" not in source
    assert "prebuilt_image" not in source
    assert "docker" not in source.casefold()
    assert "acr" not in source.casefold()
    assert "application deployment" not in source.casefold()
    assert "migration" not in source.casefold()
    assert "scanner-proof" not in adapter_module._CLEANUP_PROGRAM
    assert "put_immutable" not in adapter_module._CLEANUP_PROGRAM
    assert '"az"' in module_source
    assert '"rest"' in module_source
