"""Closed, one-run lifecycle executor for the Milestone 7.7 managed binding.

The permanent contract remains deny-all.  This entry point accepts only an
unexpired integrity-bound ledger, exact operation names, exact resource names,
and repository-owned templates.  It never accepts or reads provider secret
values.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NoReturn, cast

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    load_json,
)
from preflight.milestone_7_7.execution import (
    AZURE_ENVIRONMENT,
    _BoundedAzureRunner,
    _PopenProcessAdapter,
    _resolve_authorized_process_launch,
)
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    claim_operation_receipt,
    load_managed_binding_contract,
    validate_authorization_ledger,
)

INFRASTRUCTURE_ROOT: Final = REPOSITORY_ROOT / "infra" / "milestone_7_7"
MAIN_TEMPLATE: Final = INFRASTRUCTURE_ROOT / "main.bicep"
CLEANUP_RUNBOOK: Final = INFRASTRUCTURE_ROOT / "scripts" / "Remove-Mobius77Staging.ps1"
TARGET_GROUP: Final = "rg-solarplexus-mobius-77-staging"
CLEANUP_GROUP: Final = "rg-solarplexus-mobius-77-cleanup-control"
KEY_VAULT: Final = "kv-mobius77-11564669"
REGISTRY: Final = "acrmobius7711564669"
AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup"
RUNBOOK: Final = "Remove-Mobius77Staging"
SCHEDULE: Final = "schedule-mobius77-cleanup"
STAGING_LOCATION: Final = "southcentralus"
CLEANUP_LOCATION: Final = "westus"
MAXIMUM_OUTPUT_BYTES: Final = 65_536
DEPLOYMENT_TIMEOUT_SECONDS: Final = 1_800
OPERATION_TIMEOUT_SECONDS: Final = 120
HEX_SHA40: Final = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST: Final = re.compile(
    r"^acrmobius7711564669\.azurecr\.io/opencanvas-api@sha256:[0-9a-f]{64}$"
)
RAW_IMAGE_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
SMTP_HOST: Final = "sandbox.smtp.mailtrap.io"
SMTP_FROM_ADDRESS: Final = "mobius77-validation@example.invalid"
KEY_VAULT_HOST: Final = f"{KEY_VAULT}.vault.azure.net"
REGISTRY_HOST: Final = f"{REGISTRY}.azurecr.io"
LIFECYCLE_OPERATIONS: Final = (
    "pre-secret-provisioning",
    "private-path-verification",
    "post-secret-provisioning",
    "temporary-authority-revocation",
    "cleanup",
    "zero-residue-verification",
)


class LifecycleError(RuntimeError):
    """Sanitized fail-closed lifecycle error."""


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fail(code: str) -> NoReturn:
    raise LifecycleError(code)


def _outside_repository(path: Path, label: str) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        _fail(f"{label}-inside-repository")
    return resolved


def _environment() -> dict[str, str]:
    return {
        **os.environ,
        **AZURE_ENVIRONMENT,
        "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        "AZURE_CORE_COLLECT_TELEMETRY": "no",
    }


def _resolved_executable(name: str) -> str:
    if name == "az":
        return name
    resolved = shutil.which(name)
    if resolved is None:
        _fail(f"{name}-executable-missing")
    candidate = Path(resolved).resolve()
    if candidate.name.casefold() not in {
        "bicep",
        "bicep.exe",
        "docker",
        "docker.exe",
        "git",
        "git.exe",
    }:
        _fail(f"{name}-executable-unapproved")
    return str(candidate)


def _run(
    argv: tuple[str, ...],
    *,
    timeout_seconds: int = OPERATION_TIMEOUT_SECONDS,
    require_json: bool = False,
    environment_overrides: Mapping[str, str] | None = None,
) -> JsonValue | None:
    if not argv or argv[0] not in {"az", "bicep", "docker", "git"}:
        _fail("lifecycle-executable-unapproved")
    executable = _resolved_executable(argv[0])
    actual = (executable, *argv[1:])
    if argv[0] == "az":
        try:
            actual = _resolve_authorized_process_launch(("az", *argv[1:])).argv
        except Exception:
            _fail("azure-launcher-unapproved")
    environment = _environment()
    if environment_overrides is not None:
        if set(environment_overrides) - {"DOCKER_CONFIG"}:
            _fail("lifecycle-environment-override-unapproved")
        environment.update(environment_overrides)
    try:
        completed = subprocess.run(
            actual,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("lifecycle-process-failed")
    stdout = bytearray(completed.stdout)
    stderr = bytearray(completed.stderr)
    try:
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("lifecycle-output-oversized")
        if completed.returncode != 0:
            _fail("lifecycle-command-nonzero")
        if not require_json:
            return None
        try:
            text = bytes(stdout).decode("utf-8", errors="strict")
            value = json.loads(text)
        except (UnicodeError, json.JSONDecodeError):
            _fail("lifecycle-json-malformed")
        return cast(JsonValue, value)
    finally:
        stdout.clear()
        stderr.clear()


def _account_binding(now: datetime) -> str:
    adapter = _PopenProcessAdapter()
    account = _BoundedAzureRunner(adapter=adapter, clock=lambda: now).run_account()
    try:
        return account.subscription_id_for_materialization()
    finally:
        account.release()


def _run_text(argv: tuple[str, ...]) -> str:
    if not argv or argv[0] != "git":
        _fail("text-executable-unapproved")
    try:
        completed = subprocess.run(
            (_resolved_executable("git"), *argv[1:]),
            cwd=REPOSITORY_ROOT,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("repository-command-failed")
    stdout = bytearray(completed.stdout)
    stderr = bytearray(completed.stderr)
    try:
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("repository-output-oversized")
        if completed.returncode != 0:
            _fail("repository-command-nonzero")
        try:
            return bytes(stdout).decode("ascii", errors="strict").strip()
        except UnicodeError:
            _fail("repository-output-malformed")
    finally:
        stdout.clear()
        stderr.clear()


def _verify_repository_state(expected_head: str) -> None:
    if _run_text(("git", "rev-parse", "HEAD")) != expected_head:
        _fail("repository-head-mismatch")
    if _run_text(("git", "status", "--porcelain=v1", "--untracked-files=all")):
        _fail("repository-not-clean")


def _scope(subscription_id: str, relative_scope: str) -> str:
    if not relative_scope.startswith("/resourceGroups/"):
        _fail("relative-scope-invalid")
    return f"/subscriptions/{subscription_id}{relative_scope}"


def _state_path(receipt_directory: Path) -> Path:
    return receipt_directory / "managed-binding-transient-state.json"


def _write_state(path: Path, value: dict[str, JsonValue]) -> None:
    temporary = path.with_suffix(".tmp")
    if path.exists() or temporary.exists():
        _fail("transient-state-already-present")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        _fail("transient-state-write-failed")


def _read_state(path: Path) -> dict[str, JsonValue]:
    value = load_json(path)
    if not isinstance(value, dict):
        _fail("transient-state-malformed")
    return value


def _replace_state(path: Path, value: dict[str, JsonValue]) -> None:
    if not path.is_file():
        _fail("transient-state-missing")
    temporary = path.with_suffix(".replace.tmp")
    if temporary.exists():
        _fail("transient-state-replacement-present")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        _fail("transient-state-replace-failed")


def _verified_cost() -> tuple[int, int]:
    value = load_json(INFRASTRUCTURE_ROOT / "manifests" / "cost-envelope.template.json")
    if not isinstance(value, dict) or value.get("resolutionStatus") != "verified":
        _fail("cost-envelope-unresolved")
    expected = value.get("expectedUsdCents")
    maximum = value.get("maximumPlausibleUsdCents")
    if (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or expected < 1
        or expected > 12_000
        or maximum < expected
        or maximum >= 15_000
    ):
        _fail("cost-envelope-outside-approved-bound")
    return expected, maximum


def _compile_template(output_path: Path) -> None:
    if not (Path.home() / ".azure" / "cliextensions" / "automation").is_dir():
        _fail("automation-extension-missing")
    _run(
        (
            "bicep",
            "build",
            str(MAIN_TEMPLATE),
            "--outfile",
            str(output_path),
        ),
        timeout_seconds=OPERATION_TIMEOUT_SECONDS,
    )
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        _fail("compiled-template-missing")


def _lifecycle_tags(
    *, ledger: dict[str, JsonValue], cleanup_at: datetime, maximum_cost: int
) -> dict[str, str]:
    return {
        "mobius-cleanup-binding-sha256": str(ledger["ledgerIntegritySha256"]),
        "mobius-contract-version": "m7.7-managed-binding-v1",
        "mobius-cost-ceiling-usd-cents": str(maximum_cost),
        "mobius-data-class": "isolated-synthetic",
        "mobius-environment": "milestone-7.7-staging",
        "mobius-expires-at-utc": _format_utc(cleanup_at),
        "mobius-manifest-sha256": str(ledger["managedBindingIntegritySha256"]),
        "mobius-public-access": "denied",
        "mobius-run-id": str(ledger["authorizationId"]),
        "mobius-source-commit": str(ledger["repositoryHead"]),
        "mobius-teardown-state": "armed",
    }


def _deploy_stage(
    *,
    template_path: Path,
    subscription_id: str,
    ledger: dict[str, JsonValue],
    stage: str,
    cleanup_at: datetime,
    expected_cost: int,
    maximum_cost: int,
    runtime_config: dict[str, JsonValue] | None = None,
) -> None:
    parameters = [
        "checkpointMode=contract-only",
        "deploymentEnabled=false",
        "managedBindingMode=managed-binding-one-run",
        "managedBindingDeploymentEnabled=true",
        f"deploymentStage={stage}",
        f"location={STAGING_LOCATION}",
        f"cleanupLocation={CLEANUP_LOCATION}",
        f"authorizationLedgerSha256={ledger['ledgerIntegritySha256']}",
        f"cleanupAtUtc={_format_utc(cleanup_at)}",
        f"expectedUsdCents={expected_cost}",
        f"maximumPlausibleUsdCents={maximum_cost}",
        "lifecycleTags="
        + json.dumps(
            _lifecycle_tags(
                ledger=ledger, cleanup_at=cleanup_at, maximum_cost=maximum_cost
            ),
            separators=(",", ":"),
            sort_keys=True,
        ),
    ]
    if runtime_config is not None:
        parameters.extend(
            (
                f"apiImageDigest={runtime_config['apiImageDigest']}",
                f"smtpHost={runtime_config['smtpHost']}",
                f"smtpFromAddress={runtime_config['smtpFromAddress']}",
            )
        )
    _run(
        (
            "az",
            "deployment",
            "sub",
            "create",
            "--name",
            f"mobius77-managed-binding-{stage}",
            "--location",
            STAGING_LOCATION,
            "--subscription",
            subscription_id,
            "--template-file",
            str(template_path),
            "--parameters",
            *parameters,
            "--only-show-errors",
            "--output",
            "none",
        ),
        timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
    )


def _configure_cleanup_runbook(subscription_id: str) -> None:
    common = (
        "--resource-group",
        CLEANUP_GROUP,
        "--automation-account-name",
        AUTOMATION_ACCOUNT,
        "--name",
        RUNBOOK,
        "--subscription",
        subscription_id,
        "--only-show-errors",
        "--output",
        "none",
    )
    _run(
        (
            "az",
            "automation",
            "runbook",
            "replace-content",
            *common,
            "--content",
            f"@{CLEANUP_RUNBOOK}",
        )
    )
    _run(("az", "automation", "runbook", "publish", *common))


def _verify_cleanup_control(subscription_id: str, cleanup_at: datetime) -> str:
    account = _run(
        (
            "az",
            "automation",
            "account",
            "show",
            "--resource-group",
            CLEANUP_GROUP,
            "--automation-account-name",
            AUTOMATION_ACCOUNT,
            "--subscription",
            subscription_id,
            "--query",
            "{location:location,localAuthDisabled:disableLocalAuth,principalId:identity.principalId,publicNetworkAccess:publicNetworkAccess,state:state}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(account, dict) or set(account) != {
        "localAuthDisabled",
        "location",
        "principalId",
        "publicNetworkAccess",
        "state",
    }:
        _fail("cleanup-automation-output-malformed")
    principal_id = account["principalId"]
    if (
        not isinstance(principal_id, str)
        or re.fullmatch(r"[0-9a-fA-F-]{36}", principal_id) is None
    ):
        _fail("cleanup-automation-output-malformed")
    if {key: value for key, value in account.items() if key != "principalId"} != {
        "localAuthDisabled": True,
        "location": CLEANUP_LOCATION,
        "publicNetworkAccess": False,
        "state": "Ok",
    }:
        _fail("cleanup-automation-not-ready")

    runbook = _run(
        (
            "az",
            "automation",
            "runbook",
            "show",
            "--resource-group",
            CLEANUP_GROUP,
            "--automation-account-name",
            AUTOMATION_ACCOUNT,
            "--name",
            RUNBOOK,
            "--subscription",
            subscription_id,
            "--query",
            "{location:location,runbookType:runbookType,state:state}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if runbook != {
        "location": CLEANUP_LOCATION,
        "runbookType": "PowerShell72",
        "state": "Published",
    }:
        _fail("cleanup-runbook-not-ready")

    schedule = _run(
        (
            "az",
            "automation",
            "schedule",
            "show",
            "--resource-group",
            CLEANUP_GROUP,
            "--automation-account-name",
            AUTOMATION_ACCOUNT,
            "--name",
            SCHEDULE,
            "--subscription",
            subscription_id,
            "--query",
            "{isEnabled:isEnabled,startTime:startTime,timeZone:timeZone}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(schedule, dict) or set(schedule) != {
        "isEnabled",
        "startTime",
        "timeZone",
    }:
        _fail("cleanup-schedule-output-malformed")
    start_time = schedule["startTime"]
    if not isinstance(start_time, str):
        _fail("cleanup-schedule-output-malformed")
    try:
        observed_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except ValueError:
        _fail("cleanup-schedule-output-malformed")
    if (
        observed_start.tzinfo is None
        or observed_start.utcoffset() != timedelta(0)
        or schedule["isEnabled"] is not True
        or schedule["timeZone"] != "Etc/UTC"
        or observed_start.astimezone(UTC).replace(microsecond=0) != cleanup_at
    ):
        _fail("cleanup-schedule-not-armed")
    return principal_id


def _verify_cleanup_target_role(
    subscription_id: str, principal_id: str, role_id: str
) -> None:
    if re.fullmatch(r"[0-9a-fA-F-]{36}", role_id) is None:
        _fail("cleanup-role-definition-malformed")
    target_scope = _scope(subscription_id, f"/resourceGroups/{TARGET_GROUP}")
    role_definition_id = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
        f"roleDefinitions/{role_id}"
    )
    expected = {
        "roleDefinitionId": role_definition_id.casefold(),
        "scope": target_scope.casefold(),
    }
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        assignments = _run(
            (
                "az",
                "role",
                "assignment",
                "list",
                "--assignee-object-id",
                principal_id,
                "--all",
                "--subscription",
                subscription_id,
                "--query",
                "[].{roleDefinitionId:roleDefinitionId,scope:scope}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if not isinstance(assignments, list):
            _fail("cleanup-role-output-malformed")
        normalized: list[dict[str, str]] = []
        for assignment in assignments:
            if not isinstance(assignment, dict) or set(assignment) != {
                "roleDefinitionId",
                "scope",
            }:
                _fail("cleanup-role-output-malformed")
            observed_role_id = assignment["roleDefinitionId"]
            scope = assignment["scope"]
            if not isinstance(observed_role_id, str) or not isinstance(scope, str):
                _fail("cleanup-role-output-malformed")
            normalized.append(
                {
                    "roleDefinitionId": observed_role_id.casefold(),
                    "scope": scope.casefold(),
                }
            )
        if normalized == [expected]:
            return
        if normalized:
            _fail("cleanup-role-scope-not-exact")
        time.sleep(5.0)
    _fail("cleanup-role-assignment-unproved")


def _signed_in_user_object_id() -> str:
    value = _run(
        (
            "az",
            "ad",
            "signed-in-user",
            "show",
            "--query",
            "{objectId:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, dict) or set(value) != {"objectId"}:
        _fail("signed-in-user-output-malformed")
    object_id = value["objectId"]
    if (
        not isinstance(object_id, str)
        or re.fullmatch(r"[0-9a-fA-F-]{36}", object_id) is None
    ):
        _fail("signed-in-user-output-malformed")
    return object_id


def _temporary_role_assignment(
    *, subscription_id: str, object_id: str, role_id: str, scope: str
) -> str:
    existing = _run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            object_id,
            "--role",
            role_id,
            "--scope",
            scope,
            "--fill-principal-name",
            "false",
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(existing, list) or existing:
        _fail("preexisting-temporary-role-assignment")
    created = _run(
        (
            "az",
            "role",
            "assignment",
            "create",
            "--assignee-object-id",
            object_id,
            "--assignee-principal-type",
            "User",
            "--role",
            role_id,
            "--scope",
            scope,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(created, dict) or set(created) != {"id"}:
        _fail("temporary-role-assignment-output-malformed")
    assignment_id = created["id"]
    if not isinstance(assignment_id, str) or not assignment_id.startswith(
        "/subscriptions/"
    ):
        _fail("temporary-role-assignment-output-malformed")
    return assignment_id


def _delete_assignment(subscription_id: str, assignment_id: str) -> None:
    _run(
        (
            "az",
            "role",
            "assignment",
            "delete",
            "--ids",
            assignment_id,
            "--subscription",
            subscription_id,
            "--only-show-errors",
            "--output",
            "none",
        )
    )


def _denial_probe(argv: tuple[str, ...]) -> str:
    if not argv or argv[0] != "az":
        _fail("denial-probe-executable-unapproved")
    try:
        actual = _resolve_authorized_process_launch(argv).argv
        completed = subprocess.run(
            actual,
            cwd=REPOSITORY_ROOT,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("denial-probe-process-failed")
    stdout = bytearray(completed.stdout)
    stderr = bytearray(completed.stderr)
    try:
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("denial-probe-output-oversized")
        if completed.returncode == 0:
            return "allowed"
        try:
            message = bytes(stderr).decode("utf-8", errors="strict").casefold()
        except UnicodeError:
            _fail("denial-probe-output-malformed")
        if not any(
            marker in message
            for marker in ("403", "denied", "forbidden", "permission", "unauthorized")
        ):
            _fail("denial-probe-result-ambiguous")
        return "denied"
    finally:
        stdout.clear()
        stderr.clear()


def _wait_for_denial(argv: tuple[str, ...], *, endpoint_host: str) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        _private_tls_endpoint(endpoint_host)
        if _denial_probe(argv) == "denied":
            return
        time.sleep(10.0)
    _fail("temporary-authority-revocation-unproved")


def _pre_secret(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    expected_cost, maximum_cost = _verified_cost()
    cleanup_at = _utc_now() + timedelta(hours=24)
    contract = load_managed_binding_contract()
    rbac = contract["rbac"]
    scopes = contract["scopeBinding"]
    if not isinstance(rbac, dict) or not isinstance(scopes, dict):
        _fail("managed-binding-contract-malformed")
    with tempfile.TemporaryDirectory(prefix="mobius77-binding-") as directory:
        template = Path(directory) / "main.json"
        _compile_template(template)
        _deploy_stage(
            template_path=template,
            subscription_id=subscription_id,
            ledger=ledger,
            stage="cleanup-control",
            cleanup_at=cleanup_at,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
        )
        _configure_cleanup_runbook(subscription_id)
        _deploy_stage(
            template_path=template,
            subscription_id=subscription_id,
            ledger=ledger,
            stage="cleanup-job-binding",
            cleanup_at=cleanup_at,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
        )
        cleanup_principal_id = _verify_cleanup_control(subscription_id, cleanup_at)
        _deploy_stage(
            template_path=template,
            subscription_id=subscription_id,
            ledger=ledger,
            stage="cleanup-binding",
            cleanup_at=cleanup_at,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
        )
        _verify_cleanup_target_role(
            subscription_id,
            cleanup_principal_id,
            str(rbac["cleanupContributorRoleDefinitionId"]),
        )
        _deploy_stage(
            template_path=template,
            subscription_id=subscription_id,
            ledger=ledger,
            stage="pre-secret",
            cleanup_at=cleanup_at,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
        )
    object_id = _signed_in_user_object_id()
    vault_scope = _scope(subscription_id, str(scopes["keyVault"]))
    state_path = _state_path(receipt_directory)
    state: dict[str, JsonValue] = {
        "cleanupAtUtc": _format_utc(cleanup_at),
        "temporaryKeyVaultAssignmentId": None,
        "temporaryRegistryAssignmentId": None,
    }
    _write_state(state_path, state)
    assignment_id: str | None = None
    try:
        assignment_id = _temporary_role_assignment(
            subscription_id=subscription_id,
            object_id=object_id,
            role_id=str(rbac["keyVaultSecretsOfficerRoleDefinitionId"]),
            scope=vault_scope,
        )
        state["temporaryKeyVaultAssignmentId"] = assignment_id
        _replace_state(state_path, state)
    except (ContractError, LifecycleError, OSError, ValueError):
        if assignment_id is not None:
            _delete_assignment(subscription_id, assignment_id)
        state_path.unlink(missing_ok=True)
        raise
    return {
        "status": "ready-for-secure-manual-entry",
        "cleanup-timer-armed": True,
        "target-scope-matched": True,
        "temporary-key-vault-authority": True,
        "secret-value-accessed": False,
    }


def _private_tls_endpoint(hostname: str) -> None:
    try:
        resolved = socket.getaddrinfo(
            hostname,
            443,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        _fail("private-endpoint-dns-unavailable")
    addresses = {
        str(item[4][0]) for item in resolved if isinstance(item[4], tuple) and item[4]
    }
    if not addresses:
        _fail("private-endpoint-dns-unavailable")
    try:
        parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError:
        _fail("private-endpoint-dns-malformed")
    approved_subnet = ipaddress.ip_network("10.77.2.0/24")
    if any(
        not isinstance(address, ipaddress.IPv4Address) or address not in approved_subnet
        for address in parsed
    ):
        _fail("private-endpoint-resolved-publicly")
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection((hostname, 443), timeout=5.0) as raw_socket,
            context.wrap_socket(raw_socket, server_hostname=hostname) as tls_socket,
        ):
            if tls_socket.version() is None:
                _fail("private-endpoint-tls-unproved")
    except (OSError, ssl.SSLError):
        _fail("private-endpoint-tls-unproved")


def _private_path(subscription_id: str) -> dict[str, JsonValue]:
    queries: tuple[tuple[str, str, str, str, dict[str, JsonValue]], ...] = (
        (
            "Microsoft.KeyVault/vaults",
            KEY_VAULT,
            "2026-02-01",
            "{state:properties.provisioningState,public:properties.publicNetworkAccess}",
            {"public": "Disabled", "state": "Succeeded"},
        ),
        (
            "Microsoft.ContainerRegistry/registries",
            REGISTRY,
            "2025-11-01",
            "{state:properties.provisioningState,public:properties.publicNetworkAccess}",
            {"public": "Disabled", "state": "Succeeded"},
        ),
        (
            "Microsoft.Network/privateEndpoints",
            "pe-mobius77-keyvault",
            "2026-01-01",
            "{state:properties.provisioningState,approval:properties.privateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status}",
            {"approval": "Approved", "state": "Succeeded"},
        ),
        (
            "Microsoft.Network/privateEndpoints",
            "pe-mobius77-acr",
            "2026-01-01",
            "{state:properties.provisioningState,approval:properties.privateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status}",
            {"approval": "Approved", "state": "Succeeded"},
        ),
        (
            "Microsoft.Network/virtualNetworkGateways",
            "vpngw-mobius77-staging",
            "2026-01-01",
            "{state:properties.provisioningState,active:properties.activeActive}",
            {"active": False, "state": "Succeeded"},
        ),
    )
    for resource_type, name, api_version, projection, expected in queries:
        value = _run(
            (
                "az",
                "resource",
                "show",
                "--resource-group",
                TARGET_GROUP,
                "--resource-type",
                resource_type,
                "--name",
                name,
                "--api-version",
                api_version,
                "--subscription",
                subscription_id,
                "--query",
                projection,
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if value != expected:
            _fail("private-path-resource-state-unproved")
    _private_tls_endpoint(KEY_VAULT_HOST)
    _private_tls_endpoint(REGISTRY_HOST)
    return {
        "status": "private-entry-path-proved",
        "private-key-vault": True,
        "private-registry": True,
        "private-endpoint-count": 2,
        "p2s-gateway": True,
        "client-dns-and-tls-proved": True,
        "secret-value-accessed": False,
    }


def _assert_source_tag_absent(
    *,
    subscription_id: str,
    source_tag: str,
    docker_environment: Mapping[str, str],
) -> None:
    repositories = _run(
        (
            "az",
            "acr",
            "repository",
            "list",
            "--name",
            REGISTRY,
            "--subscription",
            subscription_id,
            "--query",
            "[?@=='opencanvas-api']",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
        environment_overrides=docker_environment,
    )
    if repositories not in ([], ["opencanvas-api"]):
        _fail("registry-repository-output-malformed")
    if repositories == []:
        return
    tags = _run(
        (
            "az",
            "acr",
            "repository",
            "show-tags",
            "--name",
            REGISTRY,
            "--repository",
            "opencanvas-api",
            "--subscription",
            subscription_id,
            "--query",
            f"[?@=='{source_tag}']",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
        environment_overrides=docker_environment,
    )
    if tags not in ([], [source_tag]):
        _fail("registry-tag-output-malformed")
    if tags:
        _fail("registry-source-tag-already-present")


def _publish_api_image(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> str:
    repository_head = str(ledger["repositoryHead"])
    if HEX_SHA40.fullmatch(repository_head) is None:
        _fail("repository-head-invalid")
    state_path = _state_path(receipt_directory)
    state = _read_state(state_path)
    if state.get("temporaryRegistryAssignmentId") is not None:
        _fail("temporary-registry-authority-already-present")
    contract = load_managed_binding_contract()
    rbac = contract["rbac"]
    scopes = contract["scopeBinding"]
    if not isinstance(rbac, dict) or not isinstance(scopes, dict):
        _fail("managed-binding-contract-malformed")
    object_id = _signed_in_user_object_id()
    registry_scope = _scope(subscription_id, str(scopes["containerRegistry"]))
    assignment_id: str | None = None
    source_tag = f"source-{repository_head}"
    image_by_tag = f"{REGISTRY_HOST}/opencanvas-api:{source_tag}"
    try:
        assignment_id = _temporary_role_assignment(
            subscription_id=subscription_id,
            object_id=object_id,
            role_id=str(rbac["acrPushRoleDefinitionId"]),
            scope=registry_scope,
        )
        state["temporaryRegistryAssignmentId"] = assignment_id
        _replace_state(state_path, state)
        with tempfile.TemporaryDirectory(
            prefix="mobius77-docker-auth-"
        ) as docker_directory:
            docker_config = Path(docker_directory).resolve()
            _outside_repository(docker_config, "docker-config")
            os.chmod(docker_config, 0o700)
            docker_environment = {"DOCKER_CONFIG": str(docker_config)}
            _run(
                (
                    "az",
                    "acr",
                    "login",
                    "--name",
                    REGISTRY,
                    "--subscription",
                    subscription_id,
                    "--only-show-errors",
                    "--output",
                    "none",
                ),
                environment_overrides=docker_environment,
            )
            try:
                _assert_source_tag_absent(
                    subscription_id=subscription_id,
                    source_tag=source_tag,
                    docker_environment=docker_environment,
                )
                _run(
                    (
                        "docker",
                        "buildx",
                        "build",
                        "--file",
                        "apps/api/Dockerfile",
                        "--tag",
                        image_by_tag,
                        "--push",
                        "--provenance=false",
                        "--sbom=false",
                        "--quiet",
                        ".",
                    ),
                    timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
                    environment_overrides=docker_environment,
                )
                digest_projection = _run(
                    (
                        "az",
                        "acr",
                        "repository",
                        "show",
                        "--name",
                        REGISTRY,
                        "--image",
                        f"opencanvas-api:{source_tag}",
                        "--subscription",
                        subscription_id,
                        "--query",
                        "{digest:digest}",
                        "--output",
                        "json",
                        "--only-show-errors",
                    ),
                    require_json=True,
                    environment_overrides=docker_environment,
                )
                if not isinstance(digest_projection, dict) or set(
                    digest_projection
                ) != {"digest"}:
                    _fail("registry-digest-output-malformed")
                raw_digest = digest_projection["digest"]
                if (
                    not isinstance(raw_digest, str)
                    or RAW_IMAGE_DIGEST.fullmatch(raw_digest) is None
                ):
                    _fail("registry-digest-output-malformed")
                _run(
                    (
                        "az",
                        "acr",
                        "repository",
                        "untag",
                        "--name",
                        REGISTRY,
                        "--image",
                        f"opencanvas-api:{source_tag}",
                        "--subscription",
                        subscription_id,
                        "--yes",
                        "--only-show-errors",
                        "--output",
                        "none",
                    ),
                    environment_overrides=docker_environment,
                )
                _assert_source_tag_absent(
                    subscription_id=subscription_id,
                    source_tag=source_tag,
                    docker_environment=docker_environment,
                )
                immutable_reference = f"{REGISTRY_HOST}/opencanvas-api@{raw_digest}"
                if IMAGE_DIGEST.fullmatch(immutable_reference) is None:
                    _fail("registry-immutable-reference-malformed")
                return immutable_reference
            finally:
                _run(
                    ("docker", "logout", REGISTRY_HOST),
                    environment_overrides=docker_environment,
                )
    finally:
        if assignment_id is not None:
            _delete_assignment(subscription_id, assignment_id)
            state["temporaryRegistryAssignmentId"] = None
            _replace_state(state_path, state)
            _wait_for_denial(
                (
                    "az",
                    "acr",
                    "repository",
                    "list",
                    "--name",
                    REGISTRY,
                    "--subscription",
                    subscription_id,
                    "--query",
                    "length(@)",
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                endpoint_host=REGISTRY_HOST,
            )


def _private_revision_ready(subscription_id: str) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        value = _run(
            (
                "az",
                "resource",
                "show",
                "--resource-group",
                TARGET_GROUP,
                "--resource-type",
                "Microsoft.App/containerApps",
                "--name",
                "ca-mobius77-api",
                "--api-version",
                "2026-01-01",
                "--subscription",
                subscription_id,
                "--query",
                "{state:properties.provisioningState,latest:properties.latestRevisionName,ready:properties.latestReadyRevisionName}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if not isinstance(value, dict) or set(value) != {"latest", "ready", "state"}:
            _fail("container-app-readiness-output-malformed")
        latest = value["latest"]
        ready = value["ready"]
        state = value["state"]
        if (
            state == "Succeeded"
            and isinstance(latest, str)
            and latest
            and ready == latest
        ):
            return
        if state in {"Canceled", "Failed"}:
            _fail("container-app-revision-failed")
        time.sleep(5.0)
    _fail("container-app-readiness-timeout")


def _post_secret(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    state = _read_state(_state_path(receipt_directory))
    cleanup_at_raw = state.get("cleanupAtUtc")
    if not isinstance(cleanup_at_raw, str):
        _fail("cleanup-binding-missing")
    cleanup_at = datetime.strptime(cleanup_at_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    if _utc_now() >= cleanup_at - timedelta(minutes=90):
        _fail("cleanup-reserve-active")
    for secret_name in (
        "openai-api-key",
        "opencanvas-smtp-username",
        "opencanvas-smtp-password",
    ):
        secret_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{TARGET_GROUP}"
            f"/providers/Microsoft.KeyVault/vaults/{KEY_VAULT}/secrets/{secret_name}"
        )
        value = _run(
            (
                "az",
                "resource",
                "show",
                "--ids",
                secret_id,
                "--api-version",
                "2026-02-01",
                "--query",
                "{enabled:properties.attributes.enabled}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if value != {"enabled": True}:
            _fail("managed-secret-presence-or-state-unproved")
    expected_cost, maximum_cost = _verified_cost()
    api_image_digest = _publish_api_image(
        ledger=ledger,
        subscription_id=subscription_id,
        receipt_directory=receipt_directory,
    )
    with tempfile.TemporaryDirectory(prefix="mobius77-binding-") as directory:
        template = Path(directory) / "main.json"
        _compile_template(template)
        _deploy_stage(
            template_path=template,
            subscription_id=subscription_id,
            ledger=ledger,
            stage="post-secret",
            cleanup_at=cleanup_at,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
            runtime_config={
                "apiImageDigest": api_image_digest,
                "smtpHost": SMTP_HOST,
                "smtpFromAddress": SMTP_FROM_ADDRESS,
            },
        )
    _private_revision_ready(subscription_id)
    return {
        "status": "private-revision-ready",
        "managed-secret-count": 3,
        "immutable-image-digest-bound": True,
        "canonical-openai-alias-only": True,
        "secret-value-accessed": False,
    }


def _revoke(subscription_id: str, receipt_directory: Path) -> dict[str, JsonValue]:
    state_path = _state_path(receipt_directory)
    state = _read_state(state_path)
    removed = 0
    key_vault_assignment_removed = False
    registry_assignment_removed = False
    for key in (
        "temporaryKeyVaultAssignmentId",
        "temporaryRegistryAssignmentId",
    ):
        value = state.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.startswith("/subscriptions/"):
            _fail("temporary-assignment-state-malformed")
        _delete_assignment(subscription_id, value)
        state[key] = None
        removed += 1
        if key == "temporaryKeyVaultAssignmentId":
            key_vault_assignment_removed = True
        if key == "temporaryRegistryAssignmentId":
            registry_assignment_removed = True
        _replace_state(state_path, state)
    if key_vault_assignment_removed:
        _wait_for_denial(
            (
                "az",
                "keyvault",
                "secret",
                "list",
                "--vault-name",
                KEY_VAULT,
                "--maxresults",
                "1",
                "--subscription",
                subscription_id,
                "--query",
                "length(@)",
                "--output",
                "json",
                "--only-show-errors",
            ),
            endpoint_host=KEY_VAULT_HOST,
        )
    if registry_assignment_removed:
        _wait_for_denial(
            (
                "az",
                "acr",
                "repository",
                "list",
                "--name",
                REGISTRY,
                "--subscription",
                subscription_id,
                "--query",
                "length(@)",
                "--output",
                "json",
                "--only-show-errors",
            ),
            endpoint_host=REGISTRY_HOST,
        )
    state_path.unlink(missing_ok=True)
    return {
        "status": "revoked-and-denied",
        "assignment-count-removed": removed,
        "secret-value-accessed": False,
    }


def _group_exists(subscription_id: str, group: str) -> bool:
    value = _run(
        (
            "az",
            "group",
            "exists",
            "--name",
            group,
            "--subscription",
            subscription_id,
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, bool):
        _fail("resource-group-existence-output-malformed")
    return value


def _deleted_vault_present(subscription_id: str) -> bool:
    value = _run(
        (
            "az",
            "keyvault",
            "list-deleted",
            "--subscription",
            subscription_id,
            "--query",
            f"[?name=='{KEY_VAULT}'].{{present:name != null}}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or set(item) != {"present"} for item in value
    ):
        _fail("deleted-vault-output-malformed")
    return bool(value)


def _cleanup(subscription_id: str, receipt_directory: Path) -> dict[str, JsonValue]:
    state_path = _state_path(receipt_directory)
    revocation_path = "no-transient-state"
    if state_path.is_file():
        try:
            _revoke(subscription_id, receipt_directory)
            revocation_path = "explicit-revocation-and-denial"
        except (ContractError, LifecycleError, OSError, ValueError):
            revocation_path = "superseded-by-resource-deletion"
    if _group_exists(subscription_id, TARGET_GROUP):
        _run(
            (
                "az",
                "group",
                "delete",
                "--name",
                TARGET_GROUP,
                "--subscription",
                subscription_id,
                "--yes",
                "--only-show-errors",
                "--output",
                "none",
            ),
            timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
        )
    if _deleted_vault_present(subscription_id):
        _run(
            (
                "az",
                "keyvault",
                "purge",
                "--name",
                KEY_VAULT,
                "--location",
                STAGING_LOCATION,
                "--subscription",
                subscription_id,
                "--only-show-errors",
                "--output",
                "none",
            ),
            timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
        )
    if _group_exists(subscription_id, CLEANUP_GROUP):
        _run(
            (
                "az",
                "group",
                "delete",
                "--name",
                CLEANUP_GROUP,
                "--subscription",
                subscription_id,
                "--yes",
                "--only-show-errors",
                "--output",
                "none",
            ),
            timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
        )
    state_path.unlink(missing_ok=True)
    return {
        "status": "cleanup-completed",
        "temporary-authority-cleanup-path": revocation_path,
        "provisioning-authorized": False,
        "secret-value-accessed": False,
    }


def _zero_residue(subscription_id: str) -> dict[str, JsonValue]:
    absent = 0
    for group in (TARGET_GROUP, CLEANUP_GROUP):
        if _group_exists(subscription_id, group):
            _fail("resource-group-residue-detected")
        absent += 1
    if _deleted_vault_present(subscription_id):
        _fail("soft-deleted-key-vault-residue-detected")
    return {
        "status": "zero-residue",
        "absent-resource-group-count": absent,
        "soft-deleted-key-vault-present": False,
        "provisioning-authorized": False,
        "secret-value-accessed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=LIFECYCLE_OPERATIONS, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--receipt-directory", type=Path, required=True)
    parser.add_argument("--repository-head", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    now = _utc_now()
    subscription_id: str | None = None
    receipt_directory: Path | None = None
    try:
        if HEX_SHA40.fullmatch(args.repository_head) is None:
            _fail("repository-head-invalid")
        receipt_directory = _outside_repository(
            args.receipt_directory, "receipt-directory"
        )
        receipt_directory.mkdir(parents=True, exist_ok=True)
        ledger = validate_authorization_ledger(
            load_json(_outside_repository(args.ledger, "ledger")),
            now_utc=now,
            expected_repository_head=args.repository_head,
        )
        _verify_repository_state(args.repository_head)
        subscription_id = _account_binding(now)
        claim_operation_receipt(
            ledger=ledger,
            operation_id=args.operation,
            receipt_directory=receipt_directory,
            now_utc=now,
            expected_repository_head=args.repository_head,
        )
        if args.operation == "pre-secret-provisioning":
            result = _pre_secret(
                ledger=ledger,
                subscription_id=subscription_id,
                receipt_directory=receipt_directory,
            )
        elif args.operation == "private-path-verification":
            result = _private_path(subscription_id)
        elif args.operation == "post-secret-provisioning":
            result = _post_secret(
                ledger=ledger,
                subscription_id=subscription_id,
                receipt_directory=receipt_directory,
            )
        elif args.operation == "temporary-authority-revocation":
            result = _revoke(subscription_id, receipt_directory)
        elif args.operation == "cleanup":
            result = _cleanup(subscription_id, receipt_directory)
        else:
            result = _zero_residue(subscription_id)
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except (ContractError, LifecycleError, OSError, ValueError) as exc:
        code = str(exc)
        if not re.fullmatch(r"[a-z0-9-]+", code):
            code = "managed-binding-lifecycle-failed-closed"
        cleanup_status = "not-required-before-effect"
        if (
            subscription_id is not None
            and receipt_directory is not None
            and args.operation != "cleanup"
        ):
            try:
                _cleanup(subscription_id, receipt_directory)
                cleanup_status = "completed"
            except (ContractError, LifecycleError, OSError, ValueError):
                cleanup_status = "failed-closed-manual-cleanup-required"
        print(
            json.dumps(
                {
                    "cleanup-status": cleanup_status,
                    "status": "blocked",
                    "error": code,
                    "provisioning-authorized": False,
                    "secret-value-accessed": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
