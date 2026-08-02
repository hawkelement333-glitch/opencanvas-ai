from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle


def _install_az_process(
    monkeypatch: pytest.MonkeyPatch, *, returncode: int, stdout: bytes, stderr: bytes
) -> None:
    monkeypatch.setattr(lifecycle, "_resolved_executable", lambda _name: "az")
    monkeypatch.setattr(
        lifecycle,
        "_resolve_authorized_process_launch",
        lambda argv: SimpleNamespace(argv=argv),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args="az", returncode=returncode, stdout=stdout, stderr=stderr
        ),
    )


def _attribution(directory: Path) -> dict[str, object]:
    value = json.loads(
        (directory / lifecycle.OPERATION_ATTRIBUTION_FILE).read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _secret_metadata_argv() -> tuple[str, ...]:
    return (
        "az",
        "keyvault",
        "secret",
        "list",
        "--vault-name",
        "synthetic-vault",
        "--subscription",
        "synthetic-subscription",
        "--query",
        "[].{name:name,enabled:attributes.enabled}",
        "--output",
        "json",
    )


def test_attribution_writes_sanitized_pre_and_post_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_az_process(monkeypatch, returncode=0, stdout=b"[]", stderr=b"")

    with lifecycle._operation_attribution_session(
        receipt_directory=tmp_path, lifecycle_stage="post-secret-provisioning"
    ):
        assert lifecycle._run(_secret_metadata_argv(), require_json=True) == []

    document = _attribution(tmp_path)
    records = document["records"]
    assert isinstance(records, list)
    assert [record["event"] for record in records] == [
        "pre-operation",
        "post-operation",
    ]
    pre, post = records
    assert pre["lifecycleStage"] == "post-secret-provisioning"
    assert pre["lifecycleSubstage"] == "key-vault-secret-metadata-listing"
    assert pre["operationClass"] == "key-vault-secret-metadata-listing"
    assert pre["serviceClass"] == "key-vault-data-plane"
    assert pre["endpointClass"] == "private-key-vault-data-plane"
    assert pre["identityAlias"] == "interactive-execution-identity"
    assert pre["expectedAuthorizationResult"] == "allow"
    assert pre["terminalDisposition"] == "RUNNING"
    assert post["sanitizedStatusCode"] == "2xx-not-reported"
    assert post["terminalDisposition"] == "COMPLETED"
    serialized = json.dumps(document, sort_keys=True)
    assert "synthetic-subscription" not in serialized
    assert "synthetic-vault" not in serialized
    assert "synthetic-private-path-marker" not in serialized
    assert "credential-material" not in serialized


def test_403_is_attributed_to_the_exact_protected_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_az_process(
        monkeypatch,
        returncode=1,
        stdout=(
            b'{"error":{"code":"Forbidden"},"correlationId":"11111111-1111-1111-1111-111111111111"}'
        ),
        stderr=b"",
    )

    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path, lifecycle_stage="post-secret-provisioning"
        ),
        pytest.raises(lifecycle.AzureCommandError, match="lifecycle-command-nonzero"),
    ):
        lifecycle._run(_secret_metadata_argv(), require_json=True)

    document = _attribution(tmp_path)
    records = document["records"]
    assert isinstance(records, list)
    final = records[-1]
    assert final["event"] == "post-operation"
    assert final["lifecycleSubstage"] == "key-vault-secret-metadata-listing"
    assert final["sanitizedStatusCode"] == "403"
    assert final["sanitizedAzureErrorCode"] == "forbidden"
    assert final["requestOrCorrelationHash"] is not None
    assert final["terminalDisposition"] == "FAILED"
    assert (
        lifecycle._safe_failed_stage(tmp_path, operation="post-secret-provisioning")
        == "key-vault-secret-metadata-listing"
    )


def test_interruption_preserves_the_active_pre_operation_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle, "_resolved_executable", lambda _name: "az")
    monkeypatch.setattr(
        lifecycle,
        "_resolve_authorized_process_launch",
        lambda argv: SimpleNamespace(argv=argv),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path, lifecycle_stage="post-secret-provisioning"
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        lifecycle._run(_secret_metadata_argv(), require_json=True)

    document = _attribution(tmp_path)
    active = document["activeOperation"]
    assert isinstance(active, dict)
    assert active["event"] == "pre-operation"
    assert active["lifecycleSubstage"] == "key-vault-secret-metadata-listing"
    assert active["terminalDisposition"] == "RUNNING"


def test_revocation_attempt_is_recorded_before_an_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle, "_resolved_executable", lambda _name: "az")
    monkeypatch.setattr(
        lifecycle,
        "_resolve_authorized_process_launch",
        lambda argv: SimpleNamespace(argv=argv),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path, lifecycle_stage="temporary-authority-revocation"
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        lifecycle._run(("az", "role", "assignment", "delete", "--ids", "synthetic-id"))

    document = _attribution(tmp_path)
    records = document["records"]
    assert isinstance(records, list)
    assert [record["event"] for record in records] == [
        "pre-operation",
        "execution-began",
    ]
    active = document["activeOperation"]
    assert isinstance(active, dict)
    assert active["azureMutationBegan"] is True
    assert active["cleanupOrRevocationRan"] is True
    assert active["lifecycleSubstage"] == "temporary-role-revocation"


def test_protected_operations_have_unique_stage_and_operation_classes() -> None:
    assert len(lifecycle.PROTECTED_OPERATION_CATALOG) == len(
        set(lifecycle.PROTECTED_OPERATION_CATALOG)
    )
    assert {
        "key-vault-secret-metadata-listing",
        "publisher-application-and-service-principal-creation",
        "initial-acr-denial-token-proof",
        "acrpush-assignment-creation",
        "acrpush-propagation-verification",
        "acrpush-propagation-token-verification",
        "entra-token-acquisition",
        "private-acr-oauth-exchange",
        "private-acr-docker-login",
        "repository-specific-digest-verification",
        "immutable-image-publication",
        "mutable-tag-removal",
        "temporary-role-revocation",
        "post-revocation-token-denial-proof",
        "acr-manifest-denial-proof",
        "acr-pull-denial-proof",
        "acr-push-denial-proof",
        "publisher-identity-and-credential-deletion",
        "preserved-environment-reconciliation",
    } <= {operation_class for _stage, operation_class in lifecycle.PROTECTED_OPERATION_CATALOG}


def test_docker_artifact_references_never_reach_the_attribution_class() -> None:
    spec = lifecycle._process_attribution_spec(
        (
            "docker",
            "pull",
            "private-registry.example/opencanvas-api@sha256:" + "a" * 64,
        ),
        environment_overrides={"AZURE_CONFIG_DIR": "synthetic"},
    )

    assert spec["operationClass"] == "acr-pull-denial-proof"
    assert spec["lifecycleSubstage"] == "post-revocation-pull-denial-proof"
    assert "private-registry" not in json.dumps(spec, sort_keys=True)


def test_unknown_failed_stage_is_rejected_for_protected_operations(tmp_path: Path) -> None:
    with lifecycle._operation_attribution_session(
        receipt_directory=tmp_path, lifecycle_stage="post-secret-provisioning"
    ):
        pass

    assert (
        lifecycle._safe_failed_stage(tmp_path, operation="post-secret-provisioning")
        == "protected-attribution-missing"
    )


def test_cleanup_attempt_is_preserved_when_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle, "_resolved_executable", lambda _name: "az")
    monkeypatch.setattr(
        lifecycle,
        "_resolve_authorized_process_launch",
        lambda argv: SimpleNamespace(argv=argv),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path, lifecycle_stage="cleanup"
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        lifecycle._run(("az", "group", "delete", "--name", "synthetic-group"))

    document = _attribution(tmp_path)
    active = document["activeOperation"]
    assert isinstance(active, dict)
    assert active["lifecycleSubstage"] == "failure-cleanup-and-resource-group-deletion"
    assert active["azureMutationBegan"] is True
    assert active["cleanupOrRevocationRan"] is True
