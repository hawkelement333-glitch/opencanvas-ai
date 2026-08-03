from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import AbstractContextManager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue, canonical_bytes

LEDGER_INTEGRITY = "a" * 64
REPOSITORY_HEAD = "b" * 40


def _session(directory: Path, stage: str) -> AbstractContextManager[None]:
    return lifecycle._operation_attribution_session(
        receipt_directory=directory,
        lifecycle_stage=stage,
        ledger_integrity=LEDGER_INTEGRITY,
        repository_head=REPOSITORY_HEAD,
    )


def _journal(
    directory: Path, stage: str = "post-secret-provisioning"
) -> lifecycle._OperationAttribution:
    return lifecycle._OperationAttribution(
        receipt_directory=directory,
        lifecycle_stage=stage,
        ledger_integrity=LEDGER_INTEGRITY,
        repository_head=REPOSITORY_HEAD,
    )


def _spec(
    substage: str = "key-vault-secret-metadata-listing",
    *,
    operation_class: str | None = None,
    mutation: bool = False,
) -> dict[str, JsonValue]:
    return {
        "azureMutation": mutation,
        "cleanupOrRevocation": False,
        "endpointClass": "private-key-vault-data-plane",
        "expectedAuthorizationResult": "allow",
        "identityAlias": "interactive-execution-identity",
        "lifecycleSubstage": substage,
        "operationClass": operation_class or substage,
        "serviceClass": "key-vault-data-plane",
    }


def _finish(
    journal: lifecycle._OperationAttribution,
    operation_id: str,
    *,
    disposition: str = "SUCCEEDED",
    error: str | None = None,
) -> None:
    journal.finish(
        operation_id,
        status_code="2xx-not-reported" if disposition == "SUCCEEDED" else "not-reported",
        azure_error_code=error,
        correlation_hash=None,
        terminal_disposition=disposition,
    )


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


def test_pre_secret_closes_before_private_path_opens(tmp_path: Path) -> None:
    with _session(tmp_path, "pre-secret-provisioning"):
        journal = cast(lifecycle._OperationAttribution, lifecycle._ACTIVE_ATTRIBUTION.get())
        operation_id = journal.start(_spec("pre-secret-reconciliation"))
        _finish(journal, operation_id)
    with _session(tmp_path, "private-path-verification"):
        journal = cast(lifecycle._OperationAttribution, lifecycle._ACTIVE_ATTRIBUTION.get())
        operation_id = journal.start(_spec("private-path-verification"))
        _finish(journal, operation_id)

    document = _attribution(tmp_path)
    assert document["activeOperation"] is None
    assert [
        record["lifecycleStage"]
        for record in cast(list[dict[str, object]], document["records"])
        if record["event"] == "pre-operation"
    ] == ["pre-secret-provisioning", "private-path-verification"]


def test_twenty_sequential_protected_operations_do_not_collide(tmp_path: Path) -> None:
    with _session(tmp_path, "post-secret-provisioning"):
        journal = cast(lifecycle._OperationAttribution, lifecycle._ACTIVE_ATTRIBUTION.get())
        for ordinal in range(20):
            operation_id = journal.start(_spec(f"synthetic-stage-{ordinal:02d}"))
            _finish(journal, operation_id)

    document = _attribution(tmp_path)
    records = cast(list[dict[str, object]], document["records"])
    assert len([record for record in records if record["event"] == "pre-operation"]) == 20
    assert len({record["operationId"] for record in records}) == 20
    assert document["activeOperation"] is None


def test_historical_records_remain_intact_across_sessions(tmp_path: Path) -> None:
    with _session(tmp_path, "pre-secret-provisioning"):
        journal = cast(lifecycle._OperationAttribution, lifecycle._ACTIVE_ATTRIBUTION.get())
        first = journal.start(_spec("first-operation"))
        _finish(journal, first)
    before = _attribution(tmp_path)["records"]
    with _session(tmp_path, "private-path-verification"):
        journal = cast(lifecycle._OperationAttribution, lifecycle._ACTIVE_ATTRIBUTION.get())
        second = journal.start(_spec("second-operation"))
        _finish(journal, second)
    after = cast(list[object], _attribution(tmp_path)["records"])
    assert after[: len(cast(list[object], before))] == before


def test_one_active_operation_blocks_a_nested_operation(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    operation_id = journal.start(_spec("active-operation"))
    with pytest.raises(
        lifecycle.LifecycleError,
        match="protected-operation-attribution-active-operation-present",
    ):
        journal.start(_spec("second-operation"))
    _finish(journal, operation_id)


def test_attempt_lock_blocks_a_concurrent_process(tmp_path: Path) -> None:
    process_id = lifecycle._lifecycle_process_id(
        ledger_integrity=LEDGER_INTEGRITY, repository_head=REPOSITORY_HEAD
    )
    lock_path = lifecycle._acquire_operation_attribution_lock(
        receipt_directory=tmp_path, lifecycle_process_id=process_id
    )
    try:
        with (
            pytest.raises(
                lifecycle.LifecycleError,
                match="protected-operation-attribution-concurrent-process",
            ),
            _session(tmp_path, "private-path-verification"),
        ):
            pass
    finally:
        lifecycle._release_operation_attribution_lock(lock_path, lifecycle_process_id=process_id)


def test_completed_operation_does_not_block_a_later_process(tmp_path: Path) -> None:
    for stage in ("pre-secret-provisioning", "private-path-verification"):
        with _session(tmp_path, stage):
            journal = cast(lifecycle._OperationAttribution, lifecycle._ACTIVE_ATTRIBUTION.get())
            operation_id = journal.start(_spec(stage))
            _finish(journal, operation_id)
    assert not (tmp_path / lifecycle.OPERATION_ATTRIBUTION_LOCK_FILE).exists()


def test_failed_operation_closes_before_failure_cleanup(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    failed = journal.start(_spec("publisher-failure"))
    _finish(
        journal,
        failed,
        disposition="FAILED",
        error="lifecycle-command-nonzero",
    )
    cleanup = journal.start(
        _spec("failure-cleanup", operation_class="temporary-role-revocation", mutation=True)
    )
    journal.mark_request_attempt_began(cleanup, cleanup_or_revocation=True)
    _finish(journal, cleanup)
    assert journal.document["activeOperation"] is None


@pytest.mark.parametrize(
    ("failure_stage", "cleanup_stages"),
    [
        (
            "key-vault-secret-metadata-listing",
            ("key-vault-temporary-authority-revocation", "key-vault-post-revocation-denial-proof"),
        ),
        (
            "immutable-image-publication",
            ("temporary-role-revocation", "post-revocation-token-denial-proof"),
        ),
    ],
)
def test_revocation_and_denial_follow_a_protected_failure(
    tmp_path: Path, failure_stage: str, cleanup_stages: tuple[str, str]
) -> None:
    journal = _journal(tmp_path)
    failed = journal.start(_spec(failure_stage))
    _finish(journal, failed, disposition="FAILED", error="lifecycle-command-nonzero")
    for stage in cleanup_stages:
        operation_id = journal.start(_spec(stage, mutation="revocation" in stage))
        _finish(journal, operation_id)
    assert journal.document["activeOperation"] is None


def test_timeout_closes_active_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_az_process(monkeypatch, returncode=0, stdout=b"[]", stderr=b"")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="az", timeout=1)
        ),
    )
    with (
        _session(tmp_path, "post-secret-provisioning"),
        pytest.raises(lifecycle.LifecycleError, match="lifecycle-process-timed-out"),
    ):
        lifecycle._run(_secret_metadata_argv(), require_json=True)
    document = _attribution(tmp_path)
    assert document["activeOperation"] is None
    assert (
        cast(list[dict[str, object]], document["records"])[-1]["terminalDisposition"] == "TIMED_OUT"
    )


def test_cancellation_closes_active_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_az_process(monkeypatch, returncode=0, stdout=b"[]", stderr=b"")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with _session(tmp_path, "post-secret-provisioning"), pytest.raises(KeyboardInterrupt):
        lifecycle._run(_secret_metadata_argv(), require_json=True)
    document = _attribution(tmp_path)
    assert document["activeOperation"] is None
    assert (
        cast(list[dict[str, object]], document["records"])[-1]["terminalDisposition"] == "CANCELLED"
    )


def test_handled_exception_closes_active_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_az_process(monkeypatch, returncode=0, stdout=b"not-json", stderr=b"")
    with (
        _session(tmp_path, "post-secret-provisioning"),
        pytest.raises(lifecycle.LifecycleError, match="lifecycle-json-malformed"),
    ):
        lifecycle._run(_secret_metadata_argv(), require_json=True)
    assert _attribution(tmp_path)["activeOperation"] is None


def test_interrupted_active_operation_remains_detectable(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.start(_spec("interrupted-operation"))
    with (
        pytest.raises(
            lifecycle.LifecycleError,
            match="protected-operation-attribution-interrupted-operation",
        ),
        _session(tmp_path, "private-path-verification"),
    ):
        pass


def test_stale_completed_record_is_not_active(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    operation_id = journal.start(_spec("completed-operation"))
    _finish(journal, operation_id)
    with _session(tmp_path, "private-path-verification"):
        assert lifecycle._ACTIVE_ATTRIBUTION.get() is not None


def test_ambiguous_interrupted_mutation_fails_closed(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    operation_id = journal.start(_spec("ambiguous-mutation", mutation=True))
    journal.mark_request_attempt_began(operation_id, cleanup_or_revocation=False)
    with pytest.raises(
        lifecycle.LifecycleError,
        match="protected-operation-attribution-interrupted-operation",
    ):
        _journal(tmp_path, "private-path-verification")


def test_local_pre_request_failure_permits_one_same_process_retry(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    spec = _spec("local-bookkeeping")
    failed = journal.start(spec)
    _finish(
        journal,
        failed,
        disposition="FAILED",
        error="lifecycle-bookkeeping-failed",
    )
    retry = journal.retry_local_pre_request(failed, spec)
    assert retry != failed
    active = cast(dict[str, object], journal.document["activeOperation"])
    assert active["retryCount"] == 1
    assert active["retryOfOperationId"] == failed
    _finish(journal, retry)


def test_second_same_process_retry_is_rejected(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    spec = _spec("local-bookkeeping")
    first = journal.start(spec)
    _finish(journal, first, disposition="FAILED", error="lifecycle-bookkeeping-failed")
    second = journal.retry_local_pre_request(first, spec)
    _finish(journal, second, disposition="FAILED", error="lifecycle-bookkeeping-failed")
    with pytest.raises(lifecycle.LifecycleError, match="local-pre-request-retry-not-authorized"):
        journal.retry_local_pre_request(second, spec)


def test_local_retry_keeps_ledger_head_and_process_binding(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    spec = _spec("local-bookkeeping")
    first = journal.start(spec)
    _finish(journal, first, disposition="FAILED", error="lifecycle-serialization-failed")
    retry = journal.retry_local_pre_request(first, spec)
    active = cast(dict[str, object], journal.document["activeOperation"])
    assert active["ledgerIntegritySha256"] == LEDGER_INTEGRITY
    assert active["repositoryHead"] == REPOSITORY_HEAD
    assert active["lifecycleProcessId"] == journal.lifecycle_process_id
    _finish(journal, retry)


@pytest.mark.parametrize(("issued", "mutation"), [(True, False), (False, True)])
def test_azure_or_mutation_started_failure_cannot_be_local_retry(
    tmp_path: Path, issued: bool, mutation: bool
) -> None:
    journal = _journal(tmp_path)
    spec = _spec("unsafe-retry", mutation=mutation)
    failed = journal.start(spec)
    journal.mark_request_attempt_began(failed, cleanup_or_revocation=False)
    if issued:
        journal.mark_azure_request_issued(failed)
    _finish(journal, failed, disposition="FAILED", error="lifecycle-bookkeeping-failed")
    with pytest.raises(lifecycle.LifecycleError, match="local-pre-request-retry-not-authorized"):
        journal.retry_local_pre_request(failed, spec)


def test_operation_ids_are_unique_and_bound(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    ids: list[str] = []
    for stage in ("one", "two", "three"):
        operation_id = journal.start(_spec(stage))
        ids.append(operation_id)
        _finish(journal, operation_id)
    assert len(set(ids)) == 3
    assert all(len(value) == 64 for value in ids)


def test_integrity_history_remains_valid(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    for stage in ("one", "two"):
        operation_id = journal.start(_spec(stage))
        _finish(journal, operation_id)
    document = _attribution(tmp_path)
    integrity = cast(str, document.pop("integritySha256"))
    assert (
        integrity
        == hashlib.sha256(
            lifecycle.OPERATION_ATTRIBUTION_DOMAIN
            + canonical_bytes(cast(dict[str, JsonValue], document))
        ).hexdigest()
    )


def test_attribution_writes_sanitized_pre_attempt_and_post_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_az_process(monkeypatch, returncode=0, stdout=b"[]", stderr=b"")
    with _session(tmp_path, "post-secret-provisioning"):
        assert lifecycle._run(_secret_metadata_argv(), require_json=True) == []
    document = _attribution(tmp_path)
    records = cast(list[dict[str, object]], document["records"])
    assert [record["event"] for record in records] == [
        "pre-operation",
        "request-attempt-began",
        "post-operation",
    ]
    assert records[-1]["terminalDisposition"] == "SUCCEEDED"
    assert records[-1]["azureRequestIssued"] is True
    serialized = json.dumps(document, sort_keys=True)
    assert "synthetic-subscription" not in serialized
    assert "synthetic-vault" not in serialized
    assert "credential-material" not in serialized


def test_403_is_attributed_to_the_exact_protected_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_az_process(
        monkeypatch,
        returncode=1,
        stdout=b'{"error":{"code":"Forbidden"},"correlationId":"11111111-1111-1111-1111-111111111111"}',
        stderr=b"",
    )
    with (
        _session(tmp_path, "post-secret-provisioning"),
        pytest.raises(lifecycle.AzureCommandError, match="lifecycle-command-nonzero"),
    ):
        lifecycle._run(_secret_metadata_argv(), require_json=True)
    final = cast(list[dict[str, object]], _attribution(tmp_path)["records"])[-1]
    assert final["lifecycleSubstage"] == "key-vault-secret-metadata-listing"
    assert final["sanitizedStatusCode"] == "403"
    assert final["sanitizedAzureErrorCode"] == "forbidden"
    assert final["requestOrCorrelationHash"] is not None
    assert (
        lifecycle._safe_failed_stage(tmp_path, operation="post-secret-provisioning")
        == "key-vault-secret-metadata-listing"
    )


def test_unknown_failed_stage_is_rejected_for_every_lifecycle_operation(
    tmp_path: Path,
) -> None:
    for operation in lifecycle.LIFECYCLE_OPERATIONS:
        assert (
            lifecycle._safe_failed_stage(tmp_path, operation=operation)
            == "protected-attribution-missing"
        )


def test_protected_operations_have_unique_stage_and_operation_classes() -> None:
    assert len(lifecycle.PROTECTED_OPERATION_CATALOG) == len(
        set(lifecycle.PROTECTED_OPERATION_CATALOG)
    )


def test_secret_token_raw_id_and_private_path_never_reach_evidence(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    operation_id = journal.start(_spec("sanitized-operation"))
    _finish(journal, operation_id, disposition="FAILED", error="failed-closed")
    serialized = json.dumps(_attribution(tmp_path), sort_keys=True)
    for forbidden in (
        "credential-material",
        "secret-value",
        "bearer-token",
        "C:\\\\private\\\\publisher",
        "/subscriptions/",
        "synthetic-private-ip",
    ):
        assert forbidden not in serialized


def test_runtime_handoff_follows_publisher_completion(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    for stage in ("publisher-identity-and-credential-deletion", "managed-runtime-deployment"):
        operation_id = journal.start(_spec(stage, mutation=True))
        journal.mark_request_attempt_began(operation_id, cleanup_or_revocation=False)
        journal.mark_azure_request_issued(operation_id)
        _finish(journal, operation_id)
    assert journal.document["activeOperation"] is None


def test_migration_readiness_soak_evidence_and_cleanup_follow_sequentially(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    stages = (
        "migration-execution",
        "readiness-validation",
        "soak-start",
        "soak-completion",
        "evidence-export",
        "cleanup",
    )
    for stage in stages:
        operation_id = journal.start(
            _spec(stage, mutation=stage in {"migration-execution", "cleanup"})
        )
        _finish(journal, operation_id)
    records = cast(list[dict[str, object]], journal.document["records"])
    assert [
        record["lifecycleSubstage"] for record in records if record["event"] == "post-operation"
    ] == list(stages)


def test_disposition_reuse_archives_prior_integrity(tmp_path: Path) -> None:
    first = lifecycle._write_disposition(tmp_path, {"status": "first"})
    second = lifecycle._write_disposition(tmp_path, {"status": "second"})
    first_integrity = cast(str, first["dispositionIntegritySha256"])
    archive = tmp_path / f"managed-binding-lifecycle-disposition-{first_integrity}.json"
    assert archive.is_file()
    assert json.loads(archive.read_text(encoding="utf-8")) == first
    assert json.loads(lifecycle._disposition_path(tmp_path).read_text(encoding="utf-8")) == second


def test_stale_completed_lock_is_reconciled_only_when_owner_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = _journal(tmp_path)
    operation_id = journal.start(_spec("completed"))
    _finish(journal, operation_id)
    process_id = journal.lifecycle_process_id
    body: dict[str, JsonValue] = {
        "acquiredAtUtc": "2026-08-02T00:00:00Z",
        "lifecycleProcessId": process_id,
        "ownerProcessId": 999999,
        "schemaVersion": "mobius.milestone-7.7.operation-attribution-lock.v1",
    }
    lifecycle._write_state(
        lifecycle._operation_attribution_lock_path(tmp_path),
        {**body, "integritySha256": lifecycle._attribution_lock_integrity(body)},
    )
    monkeypatch.setattr(lifecycle, "_process_is_running", lambda _pid: False)
    with _session(tmp_path, "private-path-verification"):
        pass
    assert not lifecycle._operation_attribution_lock_path(tmp_path).exists()
