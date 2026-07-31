from __future__ import annotations

import hashlib
import inspect
import io
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from performance.milestone_7_7.framework import ContractError, canonical_bytes
from preflight.milestone_7_7 import execution as preflight_execution
from preflight.milestone_7_7 import framework as topology_framework
from preflight.milestone_7_7.execution import (
    AZURE_ENVIRONMENT,
    PreflightExecutionError,
    _BoundedAzureRunner,
    _execute_with_adapter,
    _PopenProcessAdapter,
    _ProcessCapture,
    _resolve_authorized_process_launch,
    dry_run_execution_path,
)
from preflight.milestone_7_7.framework import (
    ACCOUNT_OUTPUT_LIMIT_BYTES,
    DEFINED_OPERATION_IDS,
    EXPECTED_ACCOUNT_COMMAND,
    INFRASTRUCTURE_GATES,
    OPERATION_IDS,
    OPERATION_TIMEOUT_SECONDS,
    RESOURCE_GROUP_OUTPUT_LIMIT_BYTES,
    RUNTIME_GATES,
    SUBSCRIPTION_FINGERPRINT,
    SUBSCRIPTION_FINGERPRINT_DOMAIN,
    TENANT_FINGERPRINT,
    TENANT_FINGERPRINT_DOMAIN,
    SanitizedObservation,
    build_evidence_package,
    evidence_integrity_sha256,
    load_scope_contract,
    parse_current_account_result,
    validate_evidence,
)

SYNTHETIC_SUBSCRIPTION_ID = "synthetic-subscription-context"
SYNTHETIC_TENANT_ID = "synthetic-tenant-context"
BASE_TIME = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)


def _account_output(**changes: object) -> bytes:
    value: dict[str, object] = {
        "environmentName": "AzureCloud",
        "state": "Enabled",
        "isDefault": True,
        "userType": "user",
        "id": SYNTHETIC_SUBSCRIPTION_ID,
        "tenantId": SYNTHETIC_TENANT_ID,
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _clock(*values: datetime) -> Callable[[], datetime]:
    iterator = iter(values)
    return lambda: next(iterator)


def _successful_clock() -> Callable[[], datetime]:
    return _clock(
        BASE_TIME,
        BASE_TIME + timedelta(seconds=1),
        BASE_TIME + timedelta(seconds=2),
        BASE_TIME + timedelta(seconds=3),
    )


class FakeProcessAdapter:
    def __init__(
        self,
        outcomes: Mapping[str, list[_ProcessCapture]] | None = None,
    ) -> None:
        self.outcomes = {
            "current-account-context": [
                _ProcessCapture(
                    exit_code=0,
                    timed_out=False,
                    oversized=False,
                    read_failed=False,
                    stdout=bytearray(_account_output()),
                )
            ],
            "target-group-existence": [
                _ProcessCapture(
                    exit_code=0,
                    timed_out=False,
                    oversized=False,
                    read_failed=False,
                    stdout=bytearray(b"false\n"),
                )
            ],
            "cleanup-group-existence": [
                _ProcessCapture(
                    exit_code=0,
                    timed_out=False,
                    oversized=False,
                    read_failed=False,
                    stdout=bytearray(b"false\n"),
                )
            ],
        }
        if outcomes is not None:
            self.outcomes.update({key: list(value) for key, value in outcomes.items()})
        self.calls: list[dict[str, object]] = []

    @staticmethod
    def operation_id(argv: tuple[str, ...]) -> str:
        if argv == EXPECTED_ACCOUNT_COMMAND:
            return "current-account-context"
        name = argv[argv.index("--name") + 1]
        if name == topology_framework.TARGET_RESOURCE_GROUP:
            return "target-group-existence"
        if name == topology_framework.CLEANUP_RESOURCE_GROUP:
            return "cleanup-group-existence"
        raise AssertionError("unexpected fake operation")

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        operation_id = self.operation_id(argv)
        self.calls.append(
            {
                "operationId": operation_id,
                "argv": argv,
                "environment": dict(environment),
                "timeoutSeconds": timeout_seconds,
                "maximumOutputBytes": maximum_output_bytes,
            }
        )
        available = self.outcomes[operation_id]
        if not available:
            raise AssertionError("operation retried")
        return available.pop(0)


@pytest.fixture(autouse=True)
def synthetic_fingerprints(monkeypatch: pytest.MonkeyPatch) -> None:
    real_fingerprint = topology_framework._identifier_fingerprint

    def fingerprint(identifier: str, *, domain: str) -> str:
        if identifier == SYNTHETIC_SUBSCRIPTION_ID and domain == SUBSCRIPTION_FINGERPRINT_DOMAIN:
            return SUBSCRIPTION_FINGERPRINT
        if identifier == SYNTHETIC_TENANT_ID and domain == TENANT_FINGERPRINT_DOMAIN:
            return TENANT_FINGERPRINT
        return real_fingerprint(identifier, domain=domain)

    monkeypatch.setattr(topology_framework, "_identifier_fingerprint", fingerprint)


def _execute_success(
    adapter: FakeProcessAdapter | None = None,
) -> tuple[dict[str, Any], FakeProcessAdapter]:
    current_adapter = FakeProcessAdapter() if adapter is None else adapter
    evidence, destination = _execute_with_adapter(
        adapter=current_adapter,
        clock=_successful_clock(),
        write_evidence=False,
    )
    assert destination is None
    return evidence, current_adapter


def test_exact_three_operation_orchestration_builds_valid_sanitized_evidence() -> None:
    evidence, adapter = _execute_success()
    assert [call["operationId"] for call in adapter.calls] == list(DEFINED_OPERATION_IDS)
    assert all(call["timeoutSeconds"] == OPERATION_TIMEOUT_SECONDS for call in adapter.calls)
    assert adapter.calls[0]["maximumOutputBytes"] == ACCOUNT_OUTPUT_LIMIT_BYTES
    assert all(
        call["maximumOutputBytes"] == RESOURCE_GROUP_OUTPUT_LIMIT_BYTES
        for call in adapter.calls[1:]
    )
    assert all(
        all(environment.get(key) == value for key, value in AZURE_ENVIRONMENT.items())
        for environment in (call["environment"] for call in adapter.calls)
    )
    assert (
        validate_evidence(
            evidence,
            now=BASE_TIME + timedelta(seconds=3),
        )
        == evidence
    )
    assert evidence["completion"]["preflightStatus"] == "complete-with-provisioning-blocked"
    assert all(row["status"] == "blocked" for row in evidence["infrastructureGates"])
    assert all(row["status"] == "unproved" for row in evidence["runtimeGates"])


def test_builder_and_orchestrator_are_deterministic_for_identical_inputs() -> None:
    first, _ = _execute_success()
    second, _ = _execute_success()
    assert canonical_bytes(first) == canonical_bytes(second)
    assert evidence_integrity_sha256(first) == evidence_integrity_sha256(second)


def test_only_three_closed_operation_ids_are_supported() -> None:
    adapter = FakeProcessAdapter()
    runner = _BoundedAzureRunner(adapter=adapter, clock=_clock(BASE_TIME))
    with pytest.raises(PreflightExecutionError, match="operation-not-authorized"):
        runner._capture(
            "regional-service-availability",
            ("az", "provider", "show"),
            maximum_output_bytes=16,
        )
    assert adapter.calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ("python", "-c", "print('unsafe')"),
        ("az", "account", "list"),
        ("az", "account", "show", "--query", "id"),
        ("az", "account", "show", "&&", "az", "group", "create"),
    ],
)
def test_altered_executable_arguments_and_shell_injection_are_rejected(
    argv: tuple[str, ...],
) -> None:
    adapter = FakeProcessAdapter()
    runner = _BoundedAzureRunner(adapter=adapter, clock=_clock(BASE_TIME))
    with pytest.raises(PreflightExecutionError):
        runner._capture(
            "current-account-context",
            argv,
            maximum_output_bytes=ACCOUNT_OUTPUT_LIMIT_BYTES,
        )
    assert adapter.calls == []


def test_one_attempt_is_enforced() -> None:
    adapter = FakeProcessAdapter()
    runner = _BoundedAzureRunner(adapter=adapter, clock=_clock(BASE_TIME, BASE_TIME))
    context = runner.run_account()
    context.release()
    with pytest.raises(PreflightExecutionError, match="operation-already-attempted"):
        runner.run_account()
    assert len(adapter.calls) == 1


def _approved_windows_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    installation_root = tmp_path / "synthetic-cli"
    wrapper_directory = installation_root / "wbin"
    wrapper_directory.mkdir(parents=True)
    wrapper = wrapper_directory / "az.cmd"
    wrapper_payload = b"synthetic fixed Azure command wrapper"
    wrapper.write_bytes(wrapper_payload)
    native_runtime = installation_root / "python.exe"
    native_runtime.write_bytes(b"synthetic native runtime")
    monkeypatch.setattr(preflight_execution, "PROCESS_PLATFORM", "nt")
    monkeypatch.setattr(
        preflight_execution.shutil,
        "which",
        lambda executable: str(wrapper) if executable == "az" else None,
    )
    monkeypatch.setattr(
        preflight_execution,
        "APPROVED_WINDOWS_AZURE_CMD_SHA256",
        frozenset({hashlib.sha256(wrapper_payload).hexdigest()}),
    )
    return wrapper, native_runtime


def test_approved_windows_wrapper_resolves_to_adjacent_native_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, native_runtime = _approved_windows_wrapper(tmp_path, monkeypatch)
    launch = _resolve_authorized_process_launch(EXPECTED_ACCOUNT_COMMAND)
    assert launch.argv == (
        str(native_runtime.resolve()),
        "-IBm",
        "azure.cli",
        *EXPECTED_ACCOUNT_COMMAND[1:],
    )
    assert launch.azure_installer_msi is True
    assert str(wrapper.resolve()) not in launch.argv
    assert "cmd.exe" not in launch.argv


def test_approved_windows_wrapper_launch_keeps_shell_disabled_and_fixed_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, native_runtime = _approved_windows_wrapper(tmp_path, monkeypatch)
    popen_call: dict[str, object] = {}

    class CompletedPopen:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(b"false\n")
            self.stderr = io.BytesIO()
            self.pid = 123

        @staticmethod
        def poll() -> int:
            return 0

        @staticmethod
        def wait(timeout: float | None = None) -> int:
            return 0

    def fake_popen(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> CompletedPopen:
        popen_call["argv"] = argv
        popen_call.update(kwargs)
        return CompletedPopen()

    monkeypatch.setattr(preflight_execution.subprocess, "Popen", fake_popen)
    capture = _PopenProcessAdapter().run(
        EXPECTED_ACCOUNT_COMMAND,
        environment=AZURE_ENVIRONMENT,
        timeout_seconds=OPERATION_TIMEOUT_SECONDS,
        maximum_output_bytes=ACCOUNT_OUTPUT_LIMIT_BYTES,
    )
    assert popen_call["argv"] == (
        str(native_runtime.resolve()),
        "-IBm",
        "azure.cli",
        *EXPECTED_ACCOUNT_COMMAND[1:],
    )
    assert popen_call["shell"] is False
    assert popen_call["stdin"] is preflight_execution.subprocess.DEVNULL
    assert popen_call["cwd"] == preflight_execution.ROOT
    assert isinstance(popen_call["env"], dict)
    assert popen_call["env"]["AZ_INSTALLER"] == "MSI"
    assert capture.exit_code == 0


def test_native_windows_azure_executable_is_accepted_without_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_azure = tmp_path / "az.exe"
    native_azure.write_bytes(b"synthetic native Azure executable")
    monkeypatch.setattr(preflight_execution, "PROCESS_PLATFORM", "nt")
    monkeypatch.setattr(
        preflight_execution.shutil,
        "which",
        lambda executable: str(native_azure) if executable == "az" else None,
    )
    launch = _resolve_authorized_process_launch(EXPECTED_ACCOUNT_COMMAND)
    assert launch.argv == (str(native_azure.resolve()), *EXPECTED_ACCOUNT_COMMAND[1:])
    assert launch.azure_installer_msi is False


def test_missing_azure_executable_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight_execution.shutil, "which", lambda _: None)
    with pytest.raises(
        PreflightExecutionError,
        match="azure-executable-not-found",
    ):
        _resolve_authorized_process_launch(EXPECTED_ACCOUNT_COMMAND)


def test_altered_or_unapproved_windows_launcher_is_rejected_without_private_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, _ = _approved_windows_wrapper(tmp_path / "private-location", monkeypatch)
    wrapper.write_bytes(b"altered wrapper")
    with pytest.raises(
        PreflightExecutionError,
        match="azure-launcher-not-approved",
    ) as raised:
        _resolve_authorized_process_launch(EXPECTED_ACCOUNT_COMMAND)
    rendered = repr(raised.value) + str(raised.value)
    assert "private-location" not in rendered
    assert str(wrapper) not in rendered


def test_windows_batch_launcher_is_never_approved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = tmp_path / "az.bat"
    launcher.write_bytes(b"synthetic batch launcher")
    monkeypatch.setattr(preflight_execution, "PROCESS_PLATFORM", "nt")
    monkeypatch.setattr(preflight_execution.shutil, "which", lambda _: str(launcher))
    with pytest.raises(
        PreflightExecutionError,
        match="azure-launcher-not-approved",
    ):
        _resolve_authorized_process_launch(EXPECTED_ACCOUNT_COMMAND)


@pytest.mark.parametrize(
    "start_error",
    [
        PermissionError("private local path"),
        OSError("private operating-system detail"),
        ValueError("private process configuration detail"),
    ],
)
def test_process_start_failures_remain_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_error: BaseException,
) -> None:
    native_azure = tmp_path / "az.exe"
    native_azure.write_bytes(b"synthetic native Azure executable")
    monkeypatch.setattr(preflight_execution, "PROCESS_PLATFORM", "nt")
    monkeypatch.setattr(preflight_execution.shutil, "which", lambda _: str(native_azure))
    monkeypatch.setattr(
        preflight_execution.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(start_error),
    )
    with pytest.raises(
        PreflightExecutionError,
        match="process-start-failed",
    ) as raised:
        _PopenProcessAdapter().run(
            EXPECTED_ACCOUNT_COMMAND,
            environment=AZURE_ENVIRONMENT,
            timeout_seconds=OPERATION_TIMEOUT_SECONDS,
            maximum_output_bytes=ACCOUNT_OUTPUT_LIMIT_BYTES,
        )
    rendered = repr(raised.value) + str(raised.value)
    assert "private" not in rendered
    assert str(native_azure) not in rendered


def test_real_adapter_timeout_path_terminates_a_controlled_fake_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _approved_windows_wrapper(tmp_path, monkeypatch)

    class FakePopen:
        def __init__(self) -> None:
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.pid = 123
            self.killed = False

        def poll(self) -> int | None:
            return -9 if self.killed else None

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == preflight_execution.PROCESS_TERMINATION_TIMEOUT_SECONDS
            return -9

    fake = FakePopen()
    monotonic_values = iter((0.0, OPERATION_TIMEOUT_SECONDS + 1.0))
    monkeypatch.setattr(
        preflight_execution.subprocess,
        "Popen",
        lambda *args, **kwargs: fake,
    )
    monkeypatch.setattr(
        preflight_execution.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    capture = _PopenProcessAdapter().run(
        EXPECTED_ACCOUNT_COMMAND,
        environment=AZURE_ENVIRONMENT,
        timeout_seconds=OPERATION_TIMEOUT_SECONDS,
        maximum_output_bytes=ACCOUNT_OUTPUT_LIMIT_BYTES,
    )
    assert fake.killed is True
    assert capture.timed_out is True
    assert capture.stdout == bytearray()
    assert capture.stderr == bytearray()


@pytest.mark.parametrize(
    ("result", "error_code"),
    [
        (
            _ProcessCapture(
                exit_code=-1,
                timed_out=True,
                oversized=False,
                read_failed=False,
            ),
            "operation-timeout",
        ),
        (
            _ProcessCapture(
                exit_code=-1,
                timed_out=False,
                oversized=True,
                read_failed=False,
            ),
            "operation-output-oversized",
        ),
        (
            _ProcessCapture(
                exit_code=2,
                timed_out=False,
                oversized=False,
                read_failed=False,
                stdout=bytearray(b"private output"),
                stderr=bytearray(b"private error"),
            ),
            "operation-nonzero-exit",
        ),
        (
            _ProcessCapture(
                exit_code=0,
                timed_out=False,
                oversized=False,
                read_failed=False,
            ),
            "operation-output-blank",
        ),
        (
            _ProcessCapture(
                exit_code=0,
                timed_out=False,
                oversized=False,
                read_failed=False,
                stdout=bytearray(_account_output()),
                stderr=bytearray(b"unexpected warning"),
            ),
            "operation-mixed-output",
        ),
    ],
)
def test_timeout_oversize_nonzero_blank_and_mixed_output_fail_closed(
    result: _ProcessCapture,
    error_code: str,
) -> None:
    adapter = FakeProcessAdapter({"current-account-context": [result]})
    with pytest.raises(PreflightExecutionError, match=error_code) as raised:
        _execute_with_adapter(
            adapter=adapter,
            clock=_clock(BASE_TIME),
            write_evidence=False,
        )
    assert str(raised.value) == error_code
    assert len(adapter.calls) == 1
    assert result.stdout == bytearray()
    assert result.stderr == bytearray()


@pytest.mark.parametrize(
    "stdout",
    [
        b"{}",
        b"[]",
        b"not-json",
        b'{"id":"first","id":"duplicate"}',
        _account_output(environmentName="AzureUSGovernment"),
        _account_output(state="Disabled"),
        _account_output(isDefault=False),
        _account_output(userType="servicePrincipal"),
        _account_output(id="synthetic-wrong-subscription"),
        _account_output(tenantId="synthetic-wrong-tenant"),
        _account_output(unexpected=True),
    ],
)
def test_invalid_account_output_fails_before_group_execution(stdout: bytes) -> None:
    adapter = FakeProcessAdapter(
        {
            "current-account-context": [
                _ProcessCapture(
                    exit_code=0,
                    timed_out=False,
                    oversized=False,
                    read_failed=False,
                    stdout=bytearray(stdout),
                )
            ]
        }
    )
    with pytest.raises(PreflightExecutionError, match="current-account-output-invalid"):
        _execute_with_adapter(
            adapter=adapter,
            clock=_clock(BASE_TIME),
            write_evidence=False,
        )
    assert [call["operationId"] for call in adapter.calls] == ["current-account-context"]


@pytest.mark.parametrize(
    "stdout",
    [
        b"true\n",
        b"False\n",
        b"false\nfalse\n",
        b"warning\nfalse\n",
        b"false true\n",
        b"\xff",
    ],
)
def test_target_collision_malformed_duplicate_mixed_or_unexpected_output_stops_cleanup(
    stdout: bytes,
) -> None:
    adapter = FakeProcessAdapter(
        {
            "target-group-existence": [
                _ProcessCapture(
                    exit_code=0,
                    timed_out=False,
                    oversized=False,
                    read_failed=False,
                    stdout=bytearray(stdout),
                )
            ]
        }
    )
    with pytest.raises(PreflightExecutionError):
        _execute_with_adapter(
            adapter=adapter,
            clock=_clock(BASE_TIME, BASE_TIME + timedelta(seconds=1)),
            write_evidence=False,
        )
    assert [call["operationId"] for call in adapter.calls] == [
        "current-account-context",
        "target-group-existence",
    ]


def test_private_account_context_repr_and_evidence_exclude_raw_identifiers() -> None:
    context = parse_current_account_result(
        stdout=_account_output(),
        observed_at_utc=BASE_TIME,
    )
    try:
        assert SYNTHETIC_SUBSCRIPTION_ID not in repr(context)
        assert SYNTHETIC_TENANT_ID not in repr(context)
        assert SYNTHETIC_SUBSCRIPTION_ID not in repr(context.observation)
        assert SYNTHETIC_TENANT_ID not in repr(context.observation)
    finally:
        context.release()
    evidence, _ = _execute_success()
    encoded = canonical_bytes(evidence)
    assert SYNTHETIC_SUBSCRIPTION_ID.encode() not in encoded
    assert SYNTHETIC_TENANT_ID.encode() not in encoded


def test_failure_exceptions_exclude_raw_stdout_stderr_and_identifiers() -> None:
    private_text = f"{SYNTHETIC_SUBSCRIPTION_ID}:{SYNTHETIC_TENANT_ID}"
    result = _ProcessCapture(
        exit_code=2,
        timed_out=False,
        oversized=False,
        read_failed=False,
        stdout=bytearray(private_text.encode()),
        stderr=bytearray(private_text.encode()),
    )
    adapter = FakeProcessAdapter({"current-account-context": [result]})
    with pytest.raises(PreflightExecutionError) as raised:
        _execute_with_adapter(
            adapter=adapter,
            clock=_clock(BASE_TIME),
            write_evidence=False,
        )
    rendered = repr(raised.value) + str(raised.value)
    assert SYNTHETIC_SUBSCRIPTION_ID not in rendered
    assert SYNTHETIC_TENANT_ID not in rendered
    assert private_text not in rendered


def test_builder_rejects_missing_duplicate_mixed_scope_and_stale_inputs() -> None:
    evidence, _ = _execute_success()
    account_row = next(
        row for row in evidence["observations"] if row["operationId"] == "current-account-context"
    )
    scope_hash = load_scope_contract()["scopeIntegritySha256"]
    account = SanitizedObservation(
        operation_id="current-account-context",
        status="proved",
        observed_at_utc=BASE_TIME,
        authority_level="subscription-scoped-control-plane",
        scope_integrity_sha256=scope_hash,
        fields=tuple((field["id"], field["value"]) for field in account_row["fields"]),
        explanation_code="approved-context-matched",
    )
    with pytest.raises(ContractError, match="exactly three"):
        build_evidence_package((account,), verified_at_utc=BASE_TIME)
    with pytest.raises(ContractError, match="unique"):
        build_evidence_package(
            (account, account, account),
            verified_at_utc=BASE_TIME,
        )
    mixed = SanitizedObservation(
        operation_id="target-group-existence",
        status="proved",
        observed_at_utc=BASE_TIME,
        authority_level="subscription-scoped-control-plane",
        scope_integrity_sha256="0" * 64,
        fields=(("exists", False),),
        explanation_code="exact-resource-group-absent",
    )
    cleanup = SanitizedObservation(
        operation_id="cleanup-group-existence",
        status="proved",
        observed_at_utc=BASE_TIME,
        authority_level="subscription-scoped-control-plane",
        scope_integrity_sha256=scope_hash,
        fields=(("exists", False),),
        explanation_code="exact-resource-group-absent",
    )
    with pytest.raises(ContractError, match="mixed or unknown scope"):
        build_evidence_package(
            (account, mixed, cleanup),
            verified_at_utc=BASE_TIME,
        )
    with pytest.raises(ContractError, match="stale"):
        validate_evidence(
            evidence,
            now=BASE_TIME + timedelta(hours=24, seconds=1),
        )


def test_builder_preserves_failed_observation_as_incomplete() -> None:
    scope_hash = load_scope_contract()["scopeIntegritySha256"]
    account = SanitizedObservation(
        operation_id="current-account-context",
        status="proved",
        observed_at_utc=BASE_TIME,
        authority_level="subscription-scoped-control-plane",
        scope_integrity_sha256=scope_hash,
        fields=(
            ("cloud", "AzureCloud"),
            ("is-default", True),
            ("state", "Enabled"),
            ("subscription-fingerprint", SUBSCRIPTION_FINGERPRINT),
            ("tenant-fingerprint", TENANT_FINGERPRINT),
            ("user-type", "user"),
        ),
        explanation_code="approved-context-matched",
    )
    target = SanitizedObservation(
        operation_id="target-group-existence",
        status="failed",
        observed_at_utc=BASE_TIME + timedelta(seconds=1),
        authority_level="subscription-scoped-control-plane",
        scope_integrity_sha256=scope_hash,
        fields=(),
        explanation_code="exact-resource-group-present",
    )
    cleanup = SanitizedObservation(
        operation_id="cleanup-group-existence",
        status="proved",
        observed_at_utc=BASE_TIME + timedelta(seconds=2),
        authority_level="subscription-scoped-control-plane",
        scope_integrity_sha256=scope_hash,
        fields=(("exists", False),),
        explanation_code="exact-resource-group-absent",
    )
    evidence = build_evidence_package(
        (account, target, cleanup),
        verified_at_utc=BASE_TIME + timedelta(seconds=3),
    )
    assert evidence["completion"]["preflightStatus"] == "incomplete"
    assert (
        next(
            row
            for row in evidence["observations"]
            if row["operationId"] == "target-group-existence"
        )["status"]
        == "failed"
    )


def test_tampered_evidence_and_runtime_gate_upgrade_are_rejected() -> None:
    evidence, _ = _execute_success()
    tampered = deepcopy(evidence)
    tampered["evidenceIntegritySha256"] = "0" * 64
    with pytest.raises(ContractError, match="integrity mismatch"):
        validate_evidence(tampered, now=BASE_TIME + timedelta(seconds=3))
    upgraded = deepcopy(evidence)
    upgraded["runtimeGates"][0]["status"] = "proved"
    upgraded["evidenceIntegritySha256"] = evidence_integrity_sha256(upgraded)
    with pytest.raises(ContractError):
        validate_evidence(upgraded, now=BASE_TIME + timedelta(seconds=3))


def test_all_blocked_operations_and_gate_states_remain_closed() -> None:
    evidence, _ = _execute_success()
    blocked = [row["operationId"] for row in evidence["observations"] if row["status"] == "blocked"]
    assert blocked == [
        operation_id for operation_id in OPERATION_IDS if operation_id not in DEFINED_OPERATION_IDS
    ]
    assert len(blocked) == 15
    assert {row["gateId"] for row in evidence["infrastructureGates"]} == set(INFRASTRUCTURE_GATES)
    assert {row["gateId"] for row in evidence["runtimeGates"]} == set(RUNTIME_GATES)


def test_failure_writes_no_partial_or_atomic_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight_execution, "EVIDENCE_DIRECTORY", tmp_path / "evidence")
    adapter = FakeProcessAdapter(
        {
            "target-group-existence": [
                _ProcessCapture(
                    exit_code=0,
                    timed_out=False,
                    oversized=False,
                    read_failed=False,
                    stdout=bytearray(b"true\n"),
                )
            ]
        }
    )
    with pytest.raises(PreflightExecutionError):
        _execute_with_adapter(
            adapter=adapter,
            clock=_clock(BASE_TIME, BASE_TIME + timedelta(seconds=1)),
            write_evidence=True,
        )
    assert not (tmp_path / "evidence").exists()


def test_successful_atomic_write_contains_only_verified_canonical_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight_execution, "EVIDENCE_DIRECTORY", tmp_path / "evidence")
    evidence, destination = _execute_with_adapter(
        adapter=FakeProcessAdapter(),
        clock=_successful_clock(),
        write_evidence=True,
    )
    assert destination is not None
    assert destination.read_bytes() == canonical_bytes(evidence)
    assert list(destination.parent.iterdir()) == [destination]


def test_atomic_write_never_overwrites_an_existing_evidence_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight_execution, "EVIDENCE_DIRECTORY", tmp_path / "evidence")
    evidence, destination = _execute_with_adapter(
        adapter=FakeProcessAdapter(),
        clock=_successful_clock(),
        write_evidence=True,
    )
    assert destination is not None
    original = destination.read_bytes()
    with pytest.raises(PreflightExecutionError, match="evidence-write-failed"):
        _execute_with_adapter(
            adapter=FakeProcessAdapter(),
            clock=_successful_clock(),
            write_evidence=True,
        )
    assert destination.read_bytes() == original == canonical_bytes(evidence)
    assert list(destination.parent.iterdir()) == [destination]


def test_dry_run_never_resolves_or_invokes_azure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def prohibited_popen(*args: object, **kwargs: object) -> None:
        nonlocal invoked
        invoked = True
        raise AssertionError("dry run invoked a process")

    monkeypatch.setattr(preflight_execution.subprocess, "Popen", prohibited_popen)
    result = dry_run_execution_path()
    assert result["status"] == "valid-local-only"
    assert result["definedOperationIds"] == list(DEFINED_OPERATION_IDS)
    assert result["azureProcessInvocations"] == 0
    assert result["evidenceWritten"] is False
    assert invoked is False


def test_production_entry_point_has_no_executable_or_adapter_override() -> None:
    parameters = inspect.signature(preflight_execution.execute_authorized_preflight).parameters
    assert tuple(parameters) == ()
    parser = preflight_execution._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--executable", "python"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--adapter", "fake"])
