"""Closed, bounded execution path for the three Checkpoint 6 Azure operations."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Final, Protocol, cast

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
)
from preflight.milestone_7_7.framework import (
    ACCOUNT_OUTPUT_LIMIT_BYTES,
    DEFINED_OPERATION_IDS,
    EXPECTED_ACCOUNT_COMMAND,
    EXPECTED_RESOURCE_GROUP_COMMAND,
    OPERATION_TIMEOUT_SECONDS,
    RESOURCE_GROUP_OPERATION_IDS,
    RESOURCE_GROUP_OUTPUT_LIMIT_BYTES,
    SanitizedObservation,
    VerifiedAccountContext,
    build_evidence_package,
    load_operation_inventory,
    load_scope_contract,
    materialize_resource_group_exists_command,
    parse_current_account_result,
    resource_group_exists_command_template,
    sanitized_resource_group_observation,
    scope_verification_result,
)

ROOT: Final = Path(__file__).resolve().parent
EVIDENCE_DIRECTORY: Final = ROOT / "evidence"
AZURE_EXECUTABLE: Final = "az"
PROCESS_PLATFORM: Final = os.name
APPROVED_WINDOWS_AZURE_CMD_SHA256: Final = frozenset(
    {"f24c501b242614afa989acf22719c816be87e7ac1ff8ff84c5fa200751f30fe2"}
)
WINDOWS_AZURE_MODULE_ARGUMENTS: Final = ("-IBm", "azure.cli")
WINDOWS_WRAPPER_MAXIMUM_BYTES: Final = 4_096
AZURE_ENVIRONMENT: Final = {
    "AZURE_CORE_COLLECT_TELEMETRY": "0",
    "AZURE_CORE_NO_COLOR": "true",
    "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
}
PROCESS_POLL_INTERVAL_SECONDS: Final = 0.01
PROCESS_TERMINATION_TIMEOUT_SECONDS: Final = 5.0
STREAM_CHUNK_BYTES: Final = 256
MANAGED_BINDING_OUTPUT_LIMIT_BYTES: Final = 65_536


class PreflightExecutionError(RuntimeError):
    """Closed failure carrying only a stable, non-sensitive error code."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(slots=True)
class _ProcessCapture:
    exit_code: int
    timed_out: bool
    oversized: bool
    read_failed: bool
    stdout: bytearray = field(default_factory=bytearray, repr=False)
    stderr: bytearray = field(default_factory=bytearray, repr=False)

    def release(self) -> None:
        """Release buffers without claiming physical memory erasure."""

        self.stdout.clear()
        self.stderr.clear()


@dataclass(frozen=True, slots=True)
class _ResolvedProcessLaunch:
    argv: tuple[str, ...] = field(repr=False)
    azure_installer_msi: bool


class _ProcessAdapter(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture: ...


def _resolve_authorized_process_launch(
    argv: tuple[str, ...],
) -> _ResolvedProcessLaunch:
    if not argv or argv[0] != AZURE_EXECUTABLE:
        raise PreflightExecutionError("executable-not-authorized")
    located = shutil.which(AZURE_EXECUTABLE)
    if located is None:
        raise PreflightExecutionError("azure-executable-not-found")
    candidate = Path(located)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise PreflightExecutionError("azure-launcher-resolution-failed") from None
    if not resolved.is_file():
        raise PreflightExecutionError("azure-launcher-not-approved")

    if PROCESS_PLATFORM != "nt":
        if candidate.name != AZURE_EXECUTABLE or not os.access(resolved, os.X_OK):
            raise PreflightExecutionError("azure-launcher-not-approved")
        return _ResolvedProcessLaunch(
            argv=(str(resolved), *argv[1:]),
            azure_installer_msi=False,
        )

    candidate_name = candidate.name.casefold()
    candidate_suffix = candidate.suffix.casefold()
    if candidate_name == "az.exe" and candidate_suffix == ".exe":
        return _ResolvedProcessLaunch(
            argv=(str(resolved), *argv[1:]),
            azure_installer_msi=False,
        )
    if candidate_name != "az.cmd" or candidate_suffix != ".cmd":
        raise PreflightExecutionError("azure-launcher-not-approved")

    try:
        wrapper_size = resolved.stat().st_size
        if wrapper_size <= 0 or wrapper_size > WINDOWS_WRAPPER_MAXIMUM_BYTES:
            raise PreflightExecutionError("azure-launcher-not-approved")
        wrapper_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        raise PreflightExecutionError("azure-launcher-resolution-failed") from None
    if wrapper_sha256 not in APPROVED_WINDOWS_AZURE_CMD_SHA256:
        raise PreflightExecutionError("azure-launcher-not-approved")

    try:
        installation_root = resolved.parent.parent.resolve(strict=True)
        native_runtime = (installation_root / "python.exe").resolve(strict=True)
    except OSError:
        raise PreflightExecutionError("azure-native-runtime-not-found") from None
    if (
        native_runtime.name.casefold() != "python.exe"
        or native_runtime.suffix.casefold() != ".exe"
        or native_runtime.parent != installation_root
        or not native_runtime.is_file()
    ):
        raise PreflightExecutionError("azure-native-runtime-not-found")
    return _ResolvedProcessLaunch(
        argv=(
            str(native_runtime),
            *WINDOWS_AZURE_MODULE_ARGUMENTS,
            *argv[1:],
        ),
        azure_installer_msi=True,
    )


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.kill()
        else:
            kill_process_group = getattr(os, "killpg", None)
            sigkill = getattr(signal, "SIGKILL", None)
            if not callable(kill_process_group) or not isinstance(sigkill, int):
                raise OSError("process-group termination is unavailable")
            kill_process_group(process.pid, sigkill)
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass


class _PopenProcessAdapter:
    """In-memory bounded subprocess adapter used only by the closed production entry point."""

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> _ProcessCapture:
        if not argv or argv[0] != AZURE_EXECUTABLE:
            raise PreflightExecutionError("executable-not-authorized")
        if timeout_seconds != OPERATION_TIMEOUT_SECONDS:
            raise PreflightExecutionError("operation-timeout-contract-mismatch")
        if maximum_output_bytes not in {
            ACCOUNT_OUTPUT_LIMIT_BYTES,
            MANAGED_BINDING_OUTPUT_LIMIT_BYTES,
            RESOURCE_GROUP_OUTPUT_LIMIT_BYTES,
        }:
            raise PreflightExecutionError("operation-output-bound-mismatch")

        launch = _resolve_authorized_process_launch(argv)
        process_environment = dict(environment)
        if launch.azure_installer_msi:
            process_environment["AZ_INSTALLER"] = "MSI"
        creation_flags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(
                launch.argv,
                cwd=ROOT,
                env=process_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                creationflags=creation_flags,
                start_new_session=start_new_session,
            )
        except (OSError, ValueError):
            raise PreflightExecutionError("process-start-failed") from None

        if process.stdout is None or process.stderr is None:
            _terminate_process(process)
            raise PreflightExecutionError("process-pipe-setup-failed")

        stdout = bytearray()
        stderr = bytearray()
        lock = threading.Lock()
        oversized = threading.Event()
        read_failed = threading.Event()
        total_bytes = [0]

        def drain(stream: BinaryIO, destination: bytearray) -> None:
            try:
                while True:
                    chunk = stream.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        return
                    with lock:
                        total_bytes[0] += len(chunk)
                        if total_bytes[0] > maximum_output_bytes:
                            oversized.set()
                        elif not oversized.is_set():
                            destination.extend(chunk)
            except (OSError, ValueError):
                read_failed.set()

        stdout_thread = threading.Thread(
            target=drain,
            args=(process.stdout, stdout),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=drain,
            args=(process.stderr, stderr),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        while process.poll() is None:
            if oversized.is_set() or read_failed.is_set():
                _terminate_process(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_process(process)
                break
            time.sleep(PROCESS_POLL_INTERVAL_SECONDS)

        try:
            exit_code = process.wait(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process(process)
            exit_code = -1
        finally:
            stdout_thread.join(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
            stderr_thread.join(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
            if stdout_thread.is_alive() or stderr_thread.is_alive():
                try:
                    process.stdout.close()
                    process.stderr.close()
                except OSError:
                    read_failed.set()
                stdout_thread.join(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
                stderr_thread.join(timeout=PROCESS_TERMINATION_TIMEOUT_SECONDS)
                if stdout_thread.is_alive() or stderr_thread.is_alive():
                    read_failed.set()
            else:
                try:
                    process.stdout.close()
                    process.stderr.close()
                except OSError:
                    read_failed.set()

        if oversized.is_set():
            stdout.clear()
            stderr.clear()
        return _ProcessCapture(
            exit_code=exit_code,
            timed_out=timed_out,
            oversized=oversized.is_set(),
            read_failed=read_failed.is_set(),
            stdout=stdout,
            stderr=stderr,
        )


def _utc_now_seconds(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise PreflightExecutionError("clock-not-utc")
    return value.astimezone(UTC).replace(microsecond=0)


class _BoundedAzureRunner:
    def __init__(
        self,
        *,
        adapter: _ProcessAdapter,
        clock: Callable[[], datetime],
    ) -> None:
        self._adapter = adapter
        self._clock = clock
        self._attempted: set[str] = set()

    def _capture(
        self,
        operation_id: str,
        argv: tuple[str, ...],
        *,
        maximum_output_bytes: int,
    ) -> tuple[_ProcessCapture, datetime]:
        if operation_id not in DEFINED_OPERATION_IDS:
            raise PreflightExecutionError("operation-not-authorized")
        if operation_id in self._attempted:
            raise PreflightExecutionError("operation-already-attempted")
        if not argv or argv[0] != AZURE_EXECUTABLE:
            raise PreflightExecutionError("executable-not-authorized")
        if operation_id == "current-account-context":
            if argv != EXPECTED_ACCOUNT_COMMAND:
                raise PreflightExecutionError("operation-command-mismatch")
        else:
            try:
                template = resource_group_exists_command_template(operation_id)
                subscription_index = template.index("{verified_subscription_id}")
                candidate_subscription_id = argv[subscription_index]
                expected = materialize_resource_group_exists_command(
                    operation_id,
                    candidate_subscription_id,
                )
            except (ContractError, IndexError, ValueError):
                raise PreflightExecutionError("operation-command-mismatch") from None
            if argv != expected:
                raise PreflightExecutionError("operation-command-mismatch")
        self._attempted.add(operation_id)
        environment = os.environ.copy()
        environment.update(AZURE_ENVIRONMENT)
        capture = self._adapter.run(
            argv,
            environment=environment,
            timeout_seconds=OPERATION_TIMEOUT_SECONDS,
            maximum_output_bytes=maximum_output_bytes,
        )
        return capture, _utc_now_seconds(self._clock)

    @staticmethod
    def _check_capture(capture: _ProcessCapture) -> None:
        if capture.timed_out:
            raise PreflightExecutionError("operation-timeout")
        if capture.oversized:
            raise PreflightExecutionError("operation-output-oversized")
        if capture.read_failed:
            raise PreflightExecutionError("operation-output-read-failed")
        if capture.exit_code != 0:
            raise PreflightExecutionError("operation-nonzero-exit")
        if capture.stderr:
            raise PreflightExecutionError("operation-mixed-output")
        if not capture.stdout:
            raise PreflightExecutionError("operation-output-blank")

    def run_account(self) -> VerifiedAccountContext:
        capture, observed_at = self._capture(
            "current-account-context",
            EXPECTED_ACCOUNT_COMMAND,
            maximum_output_bytes=ACCOUNT_OUTPUT_LIMIT_BYTES,
        )
        try:
            self._check_capture(capture)
            return parse_current_account_result(
                stdout=bytes(capture.stdout),
                observed_at_utc=observed_at,
            )
        except ContractError:
            raise PreflightExecutionError("current-account-output-invalid") from None
        finally:
            capture.release()

    def run_resource_group(
        self,
        operation_id: str,
        raw_subscription_id: str,
    ) -> SanitizedObservation:
        try:
            argv = materialize_resource_group_exists_command(
                operation_id,
                raw_subscription_id,
            )
        except ContractError:
            raise PreflightExecutionError("resource-group-command-rejected") from None
        capture, observed_at = self._capture(
            operation_id,
            argv,
            maximum_output_bytes=RESOURCE_GROUP_OUTPUT_LIMIT_BYTES,
        )
        try:
            self._check_capture(capture)
            try:
                stdout = bytes(capture.stdout).decode("utf-8", errors="strict")
            except UnicodeError:
                raise PreflightExecutionError(
                    "resource-group-output-malformed"
                ) from None
            observation = sanitized_resource_group_observation(
                operation_id=operation_id,
                stdout=stdout,
                exit_code=capture.exit_code,
                timed_out=capture.timed_out,
                observed_at_utc=observed_at,
            )
            if observation.status != "proved":
                raise PreflightExecutionError(observation.explanation_code)
            return observation
        finally:
            capture.release()


def _write_evidence_atomically(evidence: dict[str, JsonValue]) -> Path:
    evidence_id = evidence.get("evidenceId")
    if not isinstance(evidence_id, str):
        raise PreflightExecutionError("evidence-id-invalid")
    payload = canonical_bytes(evidence)
    EVIDENCE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = EVIDENCE_DIRECTORY / f"{evidence_id}.json"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb",
            dir=EVIDENCE_DIRECTORY,
            prefix=".checkpoint-6-evidence-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_path, destination)
        temporary_path.unlink()
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise PreflightExecutionError("evidence-write-failed") from None
    return destination


def _execute_with_adapter(
    *,
    adapter: _ProcessAdapter,
    clock: Callable[[], datetime],
    write_evidence: bool,
) -> tuple[dict[str, JsonValue], Path | None]:
    scope_verification_result()
    runner = _BoundedAzureRunner(adapter=adapter, clock=clock)
    account: VerifiedAccountContext | None = None
    observations: tuple[SanitizedObservation, ...]
    try:
        account = runner.run_account()
        raw_subscription_id = account.subscription_id_for_materialization()
        target = runner.run_resource_group(
            RESOURCE_GROUP_OPERATION_IDS[0],
            raw_subscription_id,
        )
        cleanup = runner.run_resource_group(
            RESOURCE_GROUP_OPERATION_IDS[1],
            raw_subscription_id,
        )
        observations = (account.observation, target, cleanup)
    finally:
        if account is not None:
            account.release()

    verified_at = _utc_now_seconds(clock)
    evidence = build_evidence_package(
        observations,
        verified_at_utc=verified_at,
    )
    destination = _write_evidence_atomically(evidence) if write_evidence else None
    return evidence, destination


def execute_authorized_preflight() -> dict[str, JsonValue]:
    """Execute the exact three-operation sequence and atomically persist valid evidence."""

    evidence, _ = _execute_with_adapter(
        adapter=_PopenProcessAdapter(),
        clock=lambda: datetime.now(UTC),
        write_evidence=True,
    )
    return evidence


def dry_run_execution_path() -> dict[str, JsonValue]:
    """Validate the closed local path without resolving or executing Azure CLI."""

    scope = load_scope_contract()
    inventory = load_operation_inventory()
    operations_value = inventory.get("operations")
    if not isinstance(operations_value, list):
        raise ContractError("operation inventory is malformed")
    operations: list[dict[str, JsonValue]] = []
    for value in operations_value:
        if not isinstance(value, dict):
            raise ContractError("operation inventory is malformed")
        operations.append(value)
    defined = tuple(
        row["id"] for row in operations if row.get("definitionStatus") == "defined"
    )
    if defined != DEFINED_OPERATION_IDS:
        raise ContractError("defined operation order differs")
    account_command = operations[0].get("commandTemplate")
    if not isinstance(account_command, list) or not all(
        isinstance(value, str) for value in account_command
    ):
        raise ContractError("current-account command is malformed")
    if EXPECTED_ACCOUNT_COMMAND != tuple(cast(list[str], account_command)):
        raise ContractError("current-account command differs")
    operation_by_id = {str(row["id"]): row for row in operations}
    for operation_id in RESOURCE_GROUP_OPERATION_IDS:
        command = operation_by_id[operation_id].get("commandTemplate")
        if not isinstance(command, list) or not all(
            isinstance(value, str) for value in command
        ):
            raise ContractError(f"{operation_id}: command is malformed")
        if tuple(cast(list[str], command)) != EXPECTED_RESOURCE_GROUP_COMMAND:
            raise ContractError(f"{operation_id}: command differs")
        resource_group_exists_command_template(operation_id)
    return {
        "status": "valid-local-only",
        "definedOperationIds": list(DEFINED_OPERATION_IDS),
        "scopeIntegritySha256": scope["scopeIntegritySha256"],
        "operationInventorySha256": inventory["inventoryIntegritySha256"],
        "operationTimeoutSeconds": int(OPERATION_TIMEOUT_SECONDS),
        "azureProcessInvocations": 0,
        "evidenceWritten": False,
        "provisioningAuthorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or locally validate the closed Checkpoint 6 preflight path."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute-authorized-preflight", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dry_run:
            result = dry_run_execution_path()
        else:
            evidence = execute_authorized_preflight()
            completion = evidence.get("completion")
            if not isinstance(completion, dict):
                raise ContractError("evidence completion is malformed")
            result = {
                "status": "complete",
                "evidenceId": evidence["evidenceId"],
                "evidenceIntegritySha256": evidence["evidenceIntegritySha256"],
                "preflightStatus": completion["preflightStatus"],
            }
        print(canonical_bytes(result).decode("utf-8"), end="")
        return 0
    except (
        ContractError,
        PreflightExecutionError,
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        error_code = (
            exc.error_code
            if isinstance(exc, PreflightExecutionError)
            else "preflight-contract-invalid"
        )
        print(
            canonical_bytes(
                {
                    "status": "failed",
                    "errorCode": error_code,
                    "evidenceWritten": False,
                    "provisioningAuthorized": False,
                }
            ).decode("utf-8"),
            end="",
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
