"""Closed, one-run lifecycle executor for the Milestone 7.7 managed binding.

The permanent contract remains deny-all.  This entry point accepts only an
unexpired integrity-bound ledger, exact operation names, exact resource names,
and repository-owned templates.  It never accepts or reads provider secret
values.
"""

from __future__ import annotations

import argparse
import hashlib
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
from enum import Enum
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
INFRASTRUCTURE_GROUP: Final = "rg-solarplexus-mobius-77-containerapps-infrastructure"
CONTAINER_APPS_DNS_LINK: Final = "link-mobius77-containerapps"
KEY_VAULT: Final = "kv-mobius77-11564669"
REGISTRY: Final = "acrmobius7711564669"
AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup"
RUNBOOK: Final = "Remove-Mobius77Staging"
SCHEDULE: Final = "schedule-mobius77-cleanup"
STAGING_LOCATION: Final = "southcentralus"
CLEANUP_LOCATION: Final = "westus"
AUTHORIZED_CLEANUP_AT_UTC: Final = datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
MAXIMUM_AUTHORIZED_WINDOW: Final = timedelta(hours=30)
MINIMUM_CLEANUP_RESERVE: Final = timedelta(minutes=90)
ABSOLUTE_COST_CEILING_USD_CENTS: Final = 10_000
MAXIMUM_OUTPUT_BYTES: Final = 65_536
DEPLOYMENT_TIMEOUT_SECONDS: Final = 1_800
OPERATION_TIMEOUT_SECONDS: Final = 120
CLEANUP_JOB_SCHEDULE_PROPAGATION_SECONDS: Final = 120
CLEANUP_JOB_SCHEDULE_RETRY_SECONDS: Final = 5.0
HEX_SHA40: Final = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST: Final = re.compile(
    r"^acrmobius7711564669\.azurecr\.io/opencanvas-api@sha256:[0-9a-f]{64}$"
)
RAW_IMAGE_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
SMTP_HOST: Final = "sandbox.smtp.mailtrap.io"
SMTP_FROM_ADDRESS: Final = "mobius77-validation@example.invalid"
KEY_VAULT_HOST: Final = f"{KEY_VAULT}.vault.azure.net"
REGISTRY_HOST: Final = f"{REGISTRY}.azurecr.io"
RECOVERABLE_API_IMAGE_SOURCE_COMMIT: Final = "24dbad86c44baef53120d75ed993ac8165549f72"
API_IMAGE_BUILD_INPUTS: Final = (
    "apps/api/Dockerfile",
    "apps/api/pyproject.toml",
    "apps/api/build-requirements.lock",
    "apps/api/requirements.lock",
    "apps/api/opencanvas_api",
    "apps/api/alembic.ini",
    "apps/api/alembic",
    "apps/api/scripts",
    "LICENSE",
    "COPYRIGHT",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
)
CONTAINER_APPS_INFRASTRUCTURE_INPUTS: Final = (
    "infra/milestone_7_7/main.bicep",
    "infra/milestone_7_7/manifests",
    "infra/milestone_7_7/modules",
    "infra/milestone_7_7/policies",
)
LIFECYCLE_OPERATIONS: Final = (
    "pre-secret-provisioning",
    "private-path-verification",
    "post-secret-provisioning",
    "temporary-authority-revocation",
    "cleanup",
    "zero-residue-verification",
)
DEPLOYMENT_STAGES: Final = frozenset(
    {
        "cleanup-control",
        "cleanup-job-binding",
        "cleanup-binding",
        "pre-secret",
        "post-secret",
    }
)
PRE_SECRET_PRESERVABLE_STAGE: Final = "pre-secret"
DISPOSITION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/lifecycle-disposition/v1\x00"
)
CLEANUP_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-authorization/v1\x00"
)
CLEANUP_AUTHORIZATION_FILE: Final = "cleanup-authorization.json"
CLEANUP_AUTHORIZATION_MAXIMUM_AGE: Final = timedelta(hours=1)
SECURITY_CONTAINMENT_ERROR_CODES: Final = frozenset(
    {
        "cleanup-role-scope-not-exact",
        "managed-secret-presence-or-state-unproved",
        "pre-secret-related-group-drift",
        "pre-secret-role-inventory-drift",
        "private-endpoint-resolved-publicly",
    }
)
TARGET_RESOURCE_LOCATIONS: Final = (
    ("microsoft.network/virtualnetworks/vnet-mobius77-staging", "southcentralus"),
    ("microsoft.network/privatednszones/privatelink.vaultcore.azure.net", "global"),
    (
        "microsoft.network/privatednszones/privatelink.vaultcore.azure.net/virtualnetworklinks/link-mobius77-keyvault",
        "global",
    ),
    ("microsoft.network/privatednszones/privatelink.azurecr.io", "global"),
    (
        "microsoft.network/privatednszones/privatelink.azurecr.io/virtualnetworklinks/link-mobius77-acr",
        "global",
    ),
    ("microsoft.network/dnsresolvers/dnspr-mobius77-staging", "southcentralus"),
    (
        "microsoft.network/dnsresolvers/dnspr-mobius77-staging/inboundendpoints/dnsin-mobius77-staging",
        "southcentralus",
    ),
    ("microsoft.network/publicipaddresses/pip-mobius77-vpn", "southcentralus"),
    (
        "microsoft.network/virtualnetworkgateways/vpngw-mobius77-staging",
        "southcentralus",
    ),
    (
        "microsoft.managedidentity/userassignedidentities/id-mobius77-api",
        "southcentralus",
    ),
    (
        "microsoft.operationalinsights/workspaces/law-mobius77-staging",
        "southcentralus",
    ),
    (
        "microsoft.containerregistry/registries/acrmobius7711564669",
        "southcentralus",
    ),
    ("microsoft.network/privateendpoints/pe-mobius77-acr", "southcentralus"),
    (
        "microsoft.network/privateendpoints/pe-mobius77-acr/privatednszonegroups/default",
        "southcentralus",
    ),
    ("microsoft.keyvault/vaults/kv-mobius77-11564669", "southcentralus"),
    (
        "microsoft.network/privateendpoints/pe-mobius77-keyvault",
        "southcentralus",
    ),
    (
        "microsoft.network/privateendpoints/pe-mobius77-keyvault/privatednszonegroups/default",
        "southcentralus",
    ),
    ("microsoft.app/managedenvironments/cae-mobius77-staging", "southcentralus"),
    ("microsoft.app/containerapps/ca-mobius77-api", "southcentralus"),
)
TARGET_DEPLOYMENT_NAMES: Final = frozenset(
    {
        "mobius77-managed-binding-network",
        "mobius77-managed-binding-identities",
        "mobius77-managed-binding-observability",
        "mobius77-managed-binding-registry",
        "mobius77-managed-binding-key-vault",
        "mobius77-managed-binding-compute",
    }
)
CLEANUP_DEPLOYMENT_NAMES: Final = frozenset(
    {"mobius77-cleanup-control", "mobius77-cleanup-job-binding"}
)
AUTOMATION_API_VERSION: Final = "2024-10-23"
RECOVERED_CLEANUP_TAG_KEYS: Final = frozenset(
    {
        "mobius-cleanup-binding-sha256",
        "mobius-contract-version",
        "mobius-cost-ceiling-usd-cents",
        "mobius-data-class",
        "mobius-environment",
        "mobius-expires-at-utc",
        "mobius-manifest-sha256",
        "mobius-public-access",
        "mobius-run-id",
        "mobius-source-commit",
        "mobius-teardown-state",
    }
)


class LifecycleDisposition(str, Enum):
    """Explicit terminal handling for one-run lifecycle execution."""

    RUNNING = "RUNNING"
    PAUSED_PRESERVED = "PAUSED_PRESERVED"
    CONTAINED_PRESERVED = "CONTAINED_PRESERVED"
    READY_FOR_FINAL_CLEANUP = "READY_FOR_FINAL_CLEANUP"
    COMPLETED = "COMPLETED"


class LifecycleError(RuntimeError):
    """Sanitized fail-closed lifecycle error."""


class AzureCommandError(LifecycleError):
    """A failed Azure command with only a bounded sanitized error code."""

    def __init__(self, sanitized_azure_error_code: str) -> None:
        super().__init__("lifecycle-command-nonzero")
        self.sanitized_azure_error_code = sanitized_azure_error_code


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cleanup_deadline(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        _fail("cleanup-time-invalid")
    policy = load_json(INFRASTRUCTURE_ROOT / "policies" / "lifecycle-policy.json")
    if not isinstance(policy, dict):
        _fail("cleanup-policy-malformed")
    lease = policy.get("lease")
    if (
        not isinstance(lease, dict)
        or lease.get("authorizedCleanupAtUtc") != _format_utc(AUTHORIZED_CLEANUP_AT_UTC)
        or lease.get("hardMaximumHours") != 30
    ):
        _fail("cleanup-policy-deadline-mismatch")
    remaining = AUTHORIZED_CLEANUP_AT_UTC - now
    if remaining <= MINIMUM_CLEANUP_RESERVE:
        _fail("cleanup-deadline-expired-or-reserve-active")
    if remaining > MAXIMUM_AUTHORIZED_WINDOW:
        _fail("cleanup-deadline-outside-authorized-window")
    return AUTHORIZED_CLEANUP_AT_UTC


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


def _normalize_azure_error_code(value: str) -> str | None:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", value) is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized if re.fullmatch(r"[a-z0-9-]{1,64}", normalized) else None


def _sanitized_azure_error_code(stdout: bytearray, stderr: bytearray) -> str:
    observed: list[str] = []

    def visit(value: JsonValue) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.casefold() == "code" and isinstance(child, str):
                    normalized = _normalize_azure_error_code(child)
                    if normalized is not None:
                        observed.append(normalized)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for buffer in (stderr, stdout):
        try:
            decoded = bytes(buffer).decode("utf-8", errors="strict")
        except UnicodeError:
            continue
        try:
            visit(cast(JsonValue, json.loads(decoded)))
        except json.JSONDecodeError:
            for match in re.finditer(
                r"(?i)\bcode\b\s*[:=]\s*['\"]?([A-Za-z][A-Za-z0-9._-]{0,63})",
                decoded,
            ):
                normalized = _normalize_azure_error_code(match.group(1))
                if normalized is not None:
                    observed.append(normalized)
    return observed[-1] if observed else "azure-command-nonzero"


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
            if argv[0] == "az":
                raise AzureCommandError(_sanitized_azure_error_code(stdout, stderr))
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


def _disposition_path(receipt_directory: Path) -> Path:
    return receipt_directory / "managed-binding-lifecycle-disposition.json"


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


def _mark_stage(
    state_path: Path,
    state: dict[str, JsonValue],
    stage: str,
    *,
    completed: bool = False,
) -> None:
    if re.fullmatch(r"[a-z0-9-]+", stage) is None:
        _fail("lifecycle-stage-invalid")
    state["disposition"] = LifecycleDisposition.RUNNING.value
    if completed:
        state["activeStage"] = None
        state["lastCompletedStage"] = stage
    else:
        state["activeStage"] = stage
    _replace_state(state_path, state)


def _write_disposition(
    receipt_directory: Path, record: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    if "dispositionIntegritySha256" in record:
        _fail("disposition-integrity-prepopulated")
    integrity = hashlib.sha256(DISPOSITION_DOMAIN + canonical_bytes(record)).hexdigest()
    complete = {**record, "dispositionIntegritySha256": integrity}
    _write_state(_disposition_path(receipt_directory), complete)
    return complete


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
        or expected > ABSOLUTE_COST_CEILING_USD_CENTS
        or maximum < expected
        or maximum > ABSOLUTE_COST_CEILING_USD_CENTS
    ):
        _fail("cost-envelope-outside-approved-bound")
    return expected, maximum


def _compile_template(output_path: Path) -> None:
    if not (Path.home() / ".azure" / "cliextensions" / "automation").is_dir():
        _fail("automation-extension-missing")
    if not (Path.home() / ".azure" / "bin" / "bicep.exe").is_file():
        _fail("azure-cli-bicep-cache-missing")
    _run(
        (
            "az",
            "bicep",
            "build",
            "--file",
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
        "mobius-teardown-state": "preservation-only",
    }


def _matches_container_apps_infrastructure_tags(
    observed: JsonValue,
    expected: Mapping[str, str],
    *,
    cleanup_at: datetime,
    environment_id: str,
) -> bool:
    managed_environment_key = "aca-managed-env-id"
    if not isinstance(observed, dict) or set(observed) != {
        *expected,
        managed_environment_key,
    }:
        return False
    managed_environment_id = observed.get(managed_environment_key)
    if (
        not isinstance(managed_environment_id, str)
        or managed_environment_id.casefold() != environment_id.casefold()
    ):
        return False
    binding_key = "mobius-cleanup-binding-sha256"
    observed_binding = observed.get(binding_key)
    expected_binding = expected.get(binding_key)
    if (
        not isinstance(observed_binding, str)
        or HEX_SHA256.fullmatch(observed_binding) is None
        or not isinstance(expected_binding, str)
        or HEX_SHA256.fullmatch(expected_binding) is None
    ):
        return False
    expiry_key = "mobius-expires-at-utc"
    observed_expiry = observed.get(expiry_key)
    expected_expiry = expected.get(expiry_key)
    if observed_expiry != expected_expiry:
        if not isinstance(observed_expiry, str):
            return False
        try:
            normalized_expiry = datetime.strptime(
                observed_expiry, "%m/%d/%Y %H:%M:%S"
            ).replace(tzinfo=UTC)
        except ValueError:
            return False
        if normalized_expiry != cleanup_at.astimezone(UTC).replace(microsecond=0):
            return False
    source_key = "mobius-source-commit"
    observed_source = observed.get(source_key)
    expected_source = expected.get(source_key)
    if observed_source != expected_source:
        if (
            not isinstance(observed_source, str)
            or HEX_SHA40.fullmatch(observed_source) is None
            or not isinstance(expected_source, str)
            or HEX_SHA40.fullmatch(expected_source) is None
        ):
            return False
        try:
            _run(
                (
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    observed_source,
                    expected_source,
                )
            )
            changed_inputs = _run_text(
                (
                    "git",
                    "diff",
                    "--name-only",
                    f"{observed_source}..{expected_source}",
                    "--",
                    *CONTAINER_APPS_INFRASTRUCTURE_INPUTS,
                )
            )
        except LifecycleError:
            return False
        if changed_inputs:
            return False
    return all(
        observed.get(key) == value
        for key, value in expected.items()
        if key not in {binding_key, expiry_key, source_key}
    )


def _container_apps_infrastructure_tags_reconcilable(
    observed: JsonValue,
    expected: Mapping[str, str],
    *,
    cleanup_at: datetime,
    environment_id: str,
) -> bool:
    managed_environment_key = "aca-managed-env-id"
    if (
        not isinstance(observed, dict)
        or set(observed) != {*expected, managed_environment_key}
        or str(observed.get(managed_environment_key, "")).casefold()
        != environment_id.casefold()
    ):
        return False
    variable_keys = {
        "mobius-cleanup-binding-sha256",
        "mobius-expires-at-utc",
        "mobius-manifest-sha256",
        "mobius-run-id",
        "mobius-source-commit",
    }
    if any(
        observed.get(key) != value
        for key, value in expected.items()
        if key not in variable_keys
    ):
        return False
    if any(
        not isinstance(observed.get(key), str)
        or HEX_SHA256.fullmatch(str(observed[key])) is None
        for key in ("mobius-cleanup-binding-sha256", "mobius-manifest-sha256")
    ):
        return False
    observed_run_id = observed.get("mobius-run-id")
    if (
        not isinstance(observed_run_id, str)
        or observed_run_id != expected.get("mobius-run-id")
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", observed_run_id) is None
    ):
        return False
    observed_source = observed.get("mobius-source-commit")
    expected_source = expected.get("mobius-source-commit")
    if (
        not isinstance(observed_source, str)
        or HEX_SHA40.fullmatch(observed_source) is None
        or not isinstance(expected_source, str)
        or HEX_SHA40.fullmatch(expected_source) is None
    ):
        return False
    try:
        _run(("git", "merge-base", "--is-ancestor", observed_source, expected_source))
    except LifecycleError:
        return False
    observed_expiry = observed.get("mobius-expires-at-utc")
    if not isinstance(observed_expiry, str):
        return False
    try:
        parsed_expiry = datetime.strptime(observed_expiry, "%m/%d/%Y %H:%M:%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        try:
            parsed_expiry = datetime.strptime(
                observed_expiry, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except ValueError:
            return False
    return parsed_expiry <= cleanup_at.astimezone(UTC).replace(microsecond=0)


def _reconcile_container_apps_infrastructure_tags(
    *,
    subscription_id: str,
    ledger: dict[str, JsonValue],
    cleanup_at: datetime,
) -> None:
    expected = _lifecycle_tags(
        ledger=ledger,
        cleanup_at=cleanup_at,
        maximum_cost=_verified_cost()[1],
    )
    environment_id = _scope(
        subscription_id,
        f"/resourceGroups/{TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging",
    )
    managed_environment_key = "aca-managed-env-id"
    desired = {**expected, managed_environment_key: environment_id}
    group = _run(
        (
            "az",
            "group",
            "show",
            "--name",
            INFRASTRUCTURE_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id,location:location,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    group_scope = _scope(subscription_id, f"/resourceGroups/{INFRASTRUCTURE_GROUP}")
    observed = group.get("tags") if isinstance(group, dict) else None
    if (
        not isinstance(group, dict)
        or set(group) != {"id", "location", "tags"}
        or group.get("id") != group_scope
        or group.get("location") != STAGING_LOCATION
        or not isinstance(observed, dict)
        or set(observed) != set(desired)
        or str(observed.get(managed_environment_key, "")).casefold()
        != environment_id.casefold()
    ):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    if observed == desired:
        return

    variable_keys = {
        "mobius-cleanup-binding-sha256",
        "mobius-expires-at-utc",
        "mobius-manifest-sha256",
        "mobius-run-id",
        "mobius-source-commit",
    }
    if any(
        observed.get(key) != value
        for key, value in expected.items()
        if key not in variable_keys
    ):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    if any(
        not isinstance(observed.get(key), str)
        or HEX_SHA256.fullmatch(str(observed[key])) is None
        for key in ("mobius-cleanup-binding-sha256", "mobius-manifest-sha256")
    ):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    observed_run_id = observed.get("mobius-run-id")
    if (
        not isinstance(observed_run_id, str)
        or observed_run_id != expected.get("mobius-run-id")
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", observed_run_id) is None
    ):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    observed_source = observed.get("mobius-source-commit")
    expected_source = expected.get("mobius-source-commit")
    if (
        not isinstance(observed_source, str)
        or HEX_SHA40.fullmatch(observed_source) is None
        or not isinstance(expected_source, str)
        or HEX_SHA40.fullmatch(expected_source) is None
    ):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    try:
        _run(("git", "merge-base", "--is-ancestor", observed_source, expected_source))
    except LifecycleError:
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    observed_expiry = observed.get("mobius-expires-at-utc")
    if not isinstance(observed_expiry, str):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")
    try:
        parsed_expiry = datetime.strptime(observed_expiry, "%m/%d/%Y %H:%M:%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        try:
            parsed_expiry = datetime.strptime(
                observed_expiry, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except ValueError:
            _fail("container-apps-infrastructure-tag-reconciliation-denied")
    if parsed_expiry > cleanup_at.astimezone(UTC).replace(microsecond=0):
        _fail("container-apps-infrastructure-tag-reconciliation-denied")

    updated = _run(
        (
            "az",
            "group",
            "update",
            "--name",
            INFRASTRUCTURE_GROUP,
            "--subscription",
            subscription_id,
            "--set",
            "tags=" + json.dumps(desired, separators=(",", ":"), sort_keys=True),
            "--query",
            "{id:id,location:location,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if updated != {"id": group_scope, "location": STAGING_LOCATION, "tags": desired}:
        _fail("container-apps-infrastructure-tag-reconciliation-unproved")


def _deployment_name(stage: str, ledger: Mapping[str, JsonValue]) -> str:
    ledger_integrity = ledger.get("ledgerIntegritySha256")
    if (
        stage not in DEPLOYMENT_STAGES
        or not isinstance(ledger_integrity, str)
        or HEX_SHA256.fullmatch(ledger_integrity) is None
    ):
        _fail("deployment-history-binding-invalid")
    deployment_name = f"mobius77-managed-binding-{stage}-{ledger_integrity[:16]}"
    if len(deployment_name) > 64:
        _fail("deployment-history-binding-invalid")
    return deployment_name


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
    deployment_name = _deployment_name(stage, ledger)
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
            deployment_name,
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


def _verify_cleanup_job_schedule(subscription_id: str) -> None:
    deadline = time.monotonic() + CLEANUP_JOB_SCHEDULE_PROPAGATION_SECONDS
    account_id = _scope(
        subscription_id,
        f"/resourceGroups/{CLEANUP_GROUP}/providers/"
        f"Microsoft.Automation/automationAccounts/{AUTOMATION_ACCOUNT}",
    )
    job_schedule_prefix = f"{account_id}/jobSchedules/"
    endpoint = (
        f"https://management.azure.com{job_schedule_prefix[:-1]}"
        f"?api-version={AUTOMATION_API_VERSION}"
    )
    while True:
        try:
            response = _run(
                (
                    "az",
                    "rest",
                    "--method",
                    "get",
                    "--url",
                    endpoint,
                    "--query",
                    (
                        "{nextLink:nextLink,value:value[]."
                        "{id:id,jobScheduleId:properties.jobScheduleId,"
                        "runbook:properties.runbook.name,"
                        "schedule:properties.schedule.name,type:type}}"
                    ),
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                require_json=True,
            )
        except AzureCommandError as exc:
            if exc.sanitized_azure_error_code not in {
                "notfound",
                "resource-not-found",
            }:
                raise
            if time.monotonic() >= deadline:
                _fail("cleanup-job-schedule-propagation-timeout")
            time.sleep(CLEANUP_JOB_SCHEDULE_RETRY_SECONDS)
            continue
        if not isinstance(response, dict) or set(response) != {"nextLink", "value"}:
            _fail("cleanup-job-schedule-output-malformed")
        next_link = response["nextLink"]
        rows = response["value"]
        if next_link not in (None, "") or not isinstance(rows, list):
            _fail("cleanup-job-schedule-output-malformed")
        if not rows:
            if time.monotonic() >= deadline:
                _fail("cleanup-job-schedule-propagation-timeout")
            time.sleep(CLEANUP_JOB_SCHEDULE_RETRY_SECONDS)
            continue
        if len(rows) != 1:
            _fail("cleanup-job-schedule-not-ready")
        job_schedule = rows[0]
        if not isinstance(job_schedule, dict) or set(job_schedule) != {
            "id",
            "jobScheduleId",
            "runbook",
            "schedule",
            "type",
        }:
            _fail("cleanup-job-schedule-output-malformed")
        resource_id = job_schedule["id"]
        job_schedule_id = job_schedule["jobScheduleId"]
        if (
            not isinstance(resource_id, str)
            or not resource_id.casefold().startswith(job_schedule_prefix.casefold())
            or not isinstance(job_schedule_id, str)
            or not isinstance(job_schedule["runbook"], str)
            or not isinstance(job_schedule["schedule"], str)
            or not isinstance(job_schedule["type"], str)
        ):
            _fail("cleanup-job-schedule-not-ready")
        resource_name = resource_id[len(job_schedule_prefix) :]
        if (
            re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                resource_name,
            )
            is None
            or job_schedule_id.casefold() != resource_name.casefold()
            or job_schedule["runbook"] != RUNBOOK
            or job_schedule["schedule"] != SCHEDULE
            or job_schedule["type"].casefold()
            != "microsoft.automation/automationaccounts/jobschedules"
        ):
            _fail("cleanup-job-schedule-not-ready")

        exact_endpoint = (
            f"https://management.azure.com{job_schedule_prefix}{resource_name}"
            f"?api-version={AUTOMATION_API_VERSION}"
        )
        try:
            exact_job_schedule = _run(
                (
                    "az",
                    "rest",
                    "--method",
                    "get",
                    "--url",
                    exact_endpoint,
                    "--query",
                    (
                        "{id:id,jobScheduleId:properties.jobScheduleId,"
                        "parameters:properties.parameters,"
                        "runbook:properties.runbook.name,"
                        "schedule:properties.schedule.name,type:type}"
                    ),
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                require_json=True,
            )
        except AzureCommandError as exc:
            if exc.sanitized_azure_error_code not in {
                "notfound",
                "resource-not-found",
            }:
                raise
            if time.monotonic() >= deadline:
                _fail("cleanup-job-schedule-propagation-timeout")
            time.sleep(CLEANUP_JOB_SCHEDULE_RETRY_SECONDS)
            continue

        if not isinstance(exact_job_schedule, dict) or set(exact_job_schedule) != {
            "id",
            "jobScheduleId",
            "parameters",
            "runbook",
            "schedule",
            "type",
        }:
            _fail("cleanup-job-schedule-output-malformed")
        parameters = exact_job_schedule["parameters"]
        if not isinstance(parameters, dict) or len(parameters) != 1:
            _fail("cleanup-job-schedule-not-ready")
        parameter_name, parameter_value = next(iter(parameters.items()))
        if (
            exact_job_schedule["id"] != resource_id
            or exact_job_schedule["jobScheduleId"] != job_schedule_id
            or exact_job_schedule["runbook"] != RUNBOOK
            or exact_job_schedule["schedule"] != SCHEDULE
            or not isinstance(exact_job_schedule["type"], str)
            or exact_job_schedule["type"].casefold()
            != "microsoft.automation/automationaccounts/jobschedules"
            or not isinstance(parameter_name, str)
            or parameter_name.casefold() != "targetresourcegroupname"
            or parameter_value != TARGET_GROUP
        ):
            _fail("cleanup-job-schedule-not-ready")
        return


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
    _verify_cleanup_job_schedule(subscription_id)
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


def _private_endpoint_network_interfaces(subscription_id: str) -> frozenset[str]:
    target_scope = _scope(subscription_id, f"/resourceGroups/{TARGET_GROUP}")
    private_subnet = (
        f"{target_scope}/providers/Microsoft.Network/virtualNetworks/"
        "vnet-mobius77-staging/subnets/snet-mobius77-private-endpoints"
    ).casefold()
    expected = {
        "pe-mobius77-acr": (
            f"{target_scope}/providers/Microsoft.ContainerRegistry/registries/{REGISTRY}".casefold(),
            ("registry",),
        ),
        "pe-mobius77-keyvault": (
            f"{target_scope}/providers/Microsoft.KeyVault/vaults/{KEY_VAULT}".casefold(),
            ("vault",),
        ),
    }
    rows = _run(
        (
            "az",
            "network",
            "private-endpoint",
            "list",
            "--resource-group",
            TARGET_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "[].{connections:privateLinkServiceConnections[].{groups:groupIds,service:privateLinkServiceId,state:privateLinkServiceConnectionState.status},name:name,nics:networkInterfaces[].id,subnet:subnet.id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(rows, list):
        _fail("pre-secret-private-endpoint-output-malformed")
    observed_names: set[str] = set()
    network_interfaces: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "connections",
            "name",
            "nics",
            "subnet",
        }:
            _fail("pre-secret-private-endpoint-output-malformed")
        name = row["name"]
        subnet = row["subnet"]
        connections = row["connections"]
        nics = row["nics"]
        if (
            not isinstance(name, str)
            or name not in expected
            or name in observed_names
            or not isinstance(subnet, str)
            or subnet.casefold() != private_subnet
            or not isinstance(connections, list)
            or len(connections) != 1
            or not isinstance(nics, list)
        ):
            _fail("pre-secret-private-endpoint-drift")
        connection = connections[0]
        if not isinstance(connection, dict) or set(connection) != {
            "groups",
            "service",
            "state",
        }:
            _fail("pre-secret-private-endpoint-output-malformed")
        groups = connection["groups"]
        service = connection["service"]
        state = connection["state"]
        expected_service, expected_groups = expected[name]
        if (
            not isinstance(groups, list)
            or tuple(groups) != expected_groups
            or not isinstance(service, str)
            or service.casefold() != expected_service
            or state not in {"Approved", "Pending", "Rejected", "Disconnected"}
        ):
            _fail("pre-secret-private-endpoint-drift")
        for nic in nics:
            if not isinstance(nic, str) or not nic.casefold().startswith(
                f"{target_scope.casefold()}/providers/microsoft.network/networkinterfaces/"
            ):
                _fail("pre-secret-private-endpoint-drift")
            network_interfaces.add(nic.casefold())
        observed_names.add(name)
    return frozenset(network_interfaces)


def _resource_group_inventory(
    *,
    subscription_id: str,
    group: str,
    allowed_network_interfaces: frozenset[str] = frozenset(),
) -> frozenset[str]:
    scope = _scope(subscription_id, f"/resourceGroups/{group}").casefold()
    rows = _run(
        (
            "az",
            "resource",
            "list",
            "--resource-group",
            group,
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id,location:location,type:type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(rows, list):
        _fail("pre-secret-resource-inventory-malformed")
    target_locations = dict(TARGET_RESOURCE_LOCATIONS)
    if group == TARGET_GROUP:
        domain, _ = _container_apps_private_dns_projection(subscription_id)
        target_locations.update(
            {
                f"microsoft.network/privatednszones/{domain}": "global",
                (
                    f"microsoft.network/privatednszones/{domain}/"
                    f"virtualnetworklinks/{CONTAINER_APPS_DNS_LINK}"
                ): "global",
            }
        )
    observed: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "location", "type"}:
            _fail("pre-secret-resource-inventory-malformed")
        resource_id = row["id"]
        location = row["location"]
        resource_type = row["type"]
        if (
            not isinstance(resource_id, str)
            or not isinstance(resource_type, str)
            or (location is not None and not isinstance(location, str))
        ):
            _fail("pre-secret-resource-inventory-malformed")
        normalized_id = resource_id.casefold()
        prefix = f"{scope}/providers/"
        if not normalized_id.startswith(prefix):
            _fail("pre-secret-resource-scope-drift")
        relative = normalized_id[len(prefix) :]
        normalized_location = location.casefold() if isinstance(location, str) else ""
        normalized_type = resource_type.casefold()
        if normalized_type == "microsoft.authorization/roleassignments":
            continue
        if normalized_type == "microsoft.network/networkinterfaces":
            if normalized_id not in allowed_network_interfaces:
                _fail("pre-secret-resource-inventory-drift")
        elif normalized_type == "microsoft.resources/deployments":
            name = relative.rsplit("/", 1)[-1]
            allowed_deployments = (
                TARGET_DEPLOYMENT_NAMES
                if group == TARGET_GROUP
                else CLEANUP_DEPLOYMENT_NAMES
            )
            if name not in allowed_deployments:
                _fail("pre-secret-resource-inventory-drift")
        elif group == TARGET_GROUP:
            expected_location = target_locations.get(relative)
            if expected_location is None or normalized_location != expected_location:
                _fail("pre-secret-resource-inventory-drift")
        else:
            exact_cleanup = {
                f"microsoft.automation/automationaccounts/{AUTOMATION_ACCOUNT.casefold()}",
                f"microsoft.automation/automationaccounts/{AUTOMATION_ACCOUNT.casefold()}/runbooks/{RUNBOOK.casefold()}",
                f"microsoft.automation/automationaccounts/{AUTOMATION_ACCOUNT.casefold()}/schedules/{SCHEDULE.casefold()}",
            }
            job_prefix = (
                f"microsoft.automation/automationaccounts/{AUTOMATION_ACCOUNT.casefold()}"
                "/jobschedules/"
            )
            if relative in exact_cleanup:
                if normalized_location not in {"", CLEANUP_LOCATION}:
                    _fail("pre-secret-resource-inventory-drift")
            elif relative.startswith(job_prefix):
                if re.fullmatch(r"[0-9a-f-]{36}", relative[len(job_prefix) :]) is None:
                    _fail("pre-secret-resource-inventory-drift")
            else:
                _fail("pre-secret-resource-inventory-drift")
        observed.add(relative)
    return frozenset(observed)


def _exact_scope_role_rows(subscription_id: str, scope: str) -> list[dict[str, str]]:
    rows = _run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--scope",
            scope,
            "--fill-principal-name",
            "false",
            "--subscription",
            subscription_id,
            "--query",
            "[].{principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(rows, list):
        _fail("pre-secret-role-inventory-malformed")
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "principalId",
            "roleDefinitionId",
            "scope",
        }:
            _fail("pre-secret-role-inventory-malformed")
        principal_id = row["principalId"]
        role_definition_id = row["roleDefinitionId"]
        observed_scope = row["scope"]
        if not all(
            isinstance(value, str)
            for value in (principal_id, role_definition_id, observed_scope)
        ):
            _fail("pre-secret-role-inventory-malformed")
        assert isinstance(principal_id, str)
        assert isinstance(role_definition_id, str)
        assert isinstance(observed_scope, str)
        if observed_scope.casefold() != scope.casefold():
            continue
        normalized.append(
            {
                "principalId": principal_id.casefold(),
                "roleDefinitionId": role_definition_id.casefold(),
                "scope": observed_scope.casefold(),
            }
        )
    return normalized


def _verify_recovered_cleanup_tags(
    tags: JsonValue,
    *,
    allowed_teardown_states: frozenset[str] = frozenset({"preservation-only"}),
) -> None:
    if not isinstance(tags, dict) or set(tags) != RECOVERED_CLEANUP_TAG_KEYS:
        _fail("recovered-cleanup-tags-drift")
    fixed_values = {
        "mobius-contract-version": "m7.7-managed-binding-v1",
        "mobius-data-class": "isolated-synthetic",
        "mobius-environment": "milestone-7.7-staging",
        "mobius-public-access": "denied",
    }
    if any(tags.get(key) != value for key, value in fixed_values.items()):
        _fail("recovered-cleanup-tags-drift")
    if tags.get("mobius-teardown-state") not in allowed_teardown_states:
        _fail("recovered-cleanup-tags-drift")
    for key in ("mobius-cleanup-binding-sha256", "mobius-manifest-sha256"):
        value = tags.get(key)
        if not isinstance(value, str) or HEX_SHA256.fullmatch(value) is None:
            _fail("recovered-cleanup-tags-drift")
    source_commit = tags.get("mobius-source-commit")
    if not isinstance(source_commit, str) or HEX_SHA40.fullmatch(source_commit) is None:
        _fail("recovered-cleanup-tags-drift")
    _run_text(("git", "cat-file", "-e", f"{source_commit}^{{commit}}"))
    run_id = tags.get("mobius-run-id")
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", run_id) is None
    ):
        _fail("recovered-cleanup-tags-drift")
    cleanup_at = tags.get("mobius-expires-at-utc")
    if (
        not isinstance(cleanup_at, str)
        or re.fullmatch(r"[0-9T:Z+./ -]{1,64}", cleanup_at) is None
    ):
        _fail("recovered-cleanup-tags-drift")
    cost_ceiling = tags.get("mobius-cost-ceiling-usd-cents")
    if (
        not isinstance(cost_ceiling, str)
        or not cost_ceiling.isdigit()
        or not 1 <= int(cost_ceiling) <= ABSOLUTE_COST_CEILING_USD_CENTS
    ):
        _fail("recovered-cleanup-tags-drift")


def _verify_recovered_cleanup_seed_state(subscription_id: str) -> None:
    group_scope = _scope(subscription_id, f"/resourceGroups/{CLEANUP_GROUP}")
    group = _run(
        (
            "az",
            "group",
            "show",
            "--name",
            CLEANUP_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id,location:location,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    group_tags = group.get("tags") if isinstance(group, dict) else None
    if (
        not isinstance(group, dict)
        or set(group) != {"id", "location", "tags"}
        or group.get("id") != group_scope
        or group.get("location") != STAGING_LOCATION
    ):
        _fail("recovered-cleanup-group-drift")
    if group_tags not in (None, {}):
        _verify_recovered_cleanup_tags(group_tags)

    account_scope = _scope(
        subscription_id,
        f"/resourceGroups/{CLEANUP_GROUP}/providers/"
        f"Microsoft.Automation/automationAccounts/{AUTOMATION_ACCOUNT}",
    )
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
            (
                "{id:id,identityType:identity.type,"
                "linkedWorkspaceId:linkedWorkspaceId,"
                "localAuthDisabled:disableLocalAuth,location:location,"
                "principalId:identity.principalId,"
                "publicNetworkAccess:publicNetworkAccess,state:state,tags:tags}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(account, dict) or set(account) != {
        "id",
        "identityType",
        "linkedWorkspaceId",
        "localAuthDisabled",
        "location",
        "principalId",
        "publicNetworkAccess",
        "state",
        "tags",
    }:
        _fail("recovered-cleanup-account-output-malformed")
    if (
        account.get("id") != account_scope
        or account.get("identityType") not in (None, "")
        or account.get("linkedWorkspaceId") not in (None, "")
        or account.get("localAuthDisabled") is not True
        or account.get("location") != CLEANUP_LOCATION
        or account.get("principalId") not in (None, "")
        or account.get("publicNetworkAccess") is not False
        or account.get("state") != "Ok"
    ):
        _fail("recovered-cleanup-account-drift")
    _verify_recovered_cleanup_tags(
        account["tags"],
        allowed_teardown_states=frozenset({"armed", "preservation-only"}),
    )

    resources = _resource_group_inventory(
        subscription_id=subscription_id,
        group=CLEANUP_GROUP,
    )
    if resources != frozenset(
        {f"microsoft.automation/automationaccounts/{AUTOMATION_ACCOUNT.casefold()}"}
    ):
        _fail("recovered-cleanup-resource-drift")
    if _exact_scope_role_rows(subscription_id, group_scope) or _exact_scope_role_rows(
        subscription_id, account_scope
    ):
        _fail("recovered-cleanup-role-drift")


def _workload_identity_principal(subscription_id: str) -> str:
    value = _run(
        (
            "az",
            "identity",
            "show",
            "--resource-group",
            TARGET_GROUP,
            "--name",
            "id-mobius77-api",
            "--subscription",
            subscription_id,
            "--query",
            "{principalId:principalId}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, dict) or set(value) != {"principalId"}:
        _fail("pre-secret-workload-identity-malformed")
    principal_id = value["principalId"]
    if (
        not isinstance(principal_id, str)
        or re.fullmatch(r"[0-9a-fA-F-]{36}", principal_id) is None
    ):
        _fail("pre-secret-workload-identity-malformed")
    return principal_id


def _verify_pre_secret_role_inventory(
    *,
    subscription_id: str,
    cleanup_principal_id: str,
    target_resources: frozenset[str],
) -> None:
    contract = load_managed_binding_contract()
    rbac = contract.get("rbac")
    if not isinstance(rbac, dict):
        _fail("managed-binding-contract-malformed")
    target_scope = _scope(subscription_id, f"/resourceGroups/{TARGET_GROUP}")
    role_prefix = f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/roleDefinitions/"
    target_expected = {
        "principalId": cleanup_principal_id.casefold(),
        "roleDefinitionId": (
            role_prefix + str(rbac["cleanupContributorRoleDefinitionId"])
        ).casefold(),
        "scope": target_scope.casefold(),
    }
    if _exact_scope_role_rows(subscription_id, target_scope) != [target_expected]:
        _fail("pre-secret-role-inventory-drift")

    cleanup_scope = _scope(subscription_id, f"/resourceGroups/{CLEANUP_GROUP}")
    account_scope = (
        f"{cleanup_scope}/providers/Microsoft.Automation/automationAccounts/"
        f"{AUTOMATION_ACCOUNT}"
    )
    if _exact_scope_role_rows(subscription_id, cleanup_scope) or _exact_scope_role_rows(
        subscription_id, account_scope
    ):
        _fail("pre-secret-role-inventory-drift")

    identity_relative = (
        "microsoft.managedidentity/userassignedidentities/id-mobius77-api"
    )
    protected_resources = {
        "microsoft.keyvault/vaults/kv-mobius77-11564669": (
            f"{target_scope}/providers/Microsoft.KeyVault/vaults/{KEY_VAULT}",
            str(rbac["keyVaultSecretsUserRoleDefinitionId"]),
        ),
        "microsoft.containerregistry/registries/acrmobius7711564669": (
            f"{target_scope}/providers/Microsoft.ContainerRegistry/registries/{REGISTRY}",
            str(rbac["acrPullRoleDefinitionId"]),
        ),
    }
    if any(relative in target_resources for relative in protected_resources):
        if identity_relative not in target_resources:
            _fail("pre-secret-role-inventory-drift")
        workload_principal = _workload_identity_principal(subscription_id).casefold()
        for relative, (scope, role_id) in protected_resources.items():
            if relative not in target_resources:
                continue
            expected = {
                "principalId": workload_principal,
                "roleDefinitionId": (role_prefix + role_id).casefold(),
                "scope": scope.casefold(),
            }
            rows = _exact_scope_role_rows(subscription_id, scope)
            if rows not in ([], [expected]):
                _fail("pre-secret-role-inventory-drift")


def _verify_resource_projection(
    subscription_id: str,
    *,
    resource_type: str,
    name: str,
    api_version: str,
    projection: str,
) -> dict[str, JsonValue]:
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
    if not isinstance(value, dict):
        _fail("pre-secret-security-projection-malformed")
    return value


def _container_apps_private_dns_projection(subscription_id: str) -> tuple[str, str]:
    environment = _verify_resource_projection(
        subscription_id,
        resource_type="Microsoft.App/managedEnvironments",
        name="cae-mobius77-staging",
        api_version="2026-01-01",
        projection="{domain:properties.defaultDomain,staticIp:properties.staticIp}",
    )
    if set(environment) != {"domain", "staticIp"}:
        _fail("pre-secret-container-apps-dns-drift")
    domain = environment.get("domain")
    static_ip = environment.get("staticIp")
    if (
        not isinstance(domain, str)
        or re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{1,251}[a-z0-9])?", domain) is None
        or not domain.casefold().endswith(".azurecontainerapps.io")
        or not isinstance(static_ip, str)
    ):
        _fail("pre-secret-container-apps-dns-drift")
    try:
        address = ipaddress.ip_address(static_ip)
    except ValueError:
        _fail("pre-secret-container-apps-dns-drift")
    if address.version != 4 or not address.is_private:
        _fail("pre-secret-container-apps-dns-drift")
    return domain.casefold(), str(address)


def _verify_container_apps_private_dns(subscription_id: str) -> None:
    domain, static_ip = _container_apps_private_dns_projection(subscription_id)
    zone = _run(
        (
            "az",
            "network",
            "private-dns",
            "zone",
            "show",
            "--resource-group",
            TARGET_GROUP,
            "--name",
            domain,
            "--subscription",
            subscription_id,
            "--query",
            "{name:name}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    link = _run(
        (
            "az",
            "network",
            "private-dns",
            "link",
            "vnet",
            "show",
            "--resource-group",
            TARGET_GROUP,
            "--zone-name",
            domain,
            "--name",
            CONTAINER_APPS_DNS_LINK,
            "--subscription",
            subscription_id,
            "--query",
            "{registration:registrationEnabled,virtualNetwork:virtualNetwork.id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    record = _run(
        (
            "az",
            "network",
            "private-dns",
            "record-set",
            "a",
            "show",
            "--resource-group",
            TARGET_GROUP,
            "--zone-name",
            domain,
            "--name",
            "*",
            "--subscription",
            subscription_id,
            "--query",
            "{records:aRecords,ttl:ttl}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected_vnet = _scope(
        subscription_id,
        f"/resourceGroups/{TARGET_GROUP}/providers/Microsoft.Network/"
        "virtualNetworks/vnet-mobius77-staging",
    )
    if zone != {"name": domain} or link != {
        "registration": False,
        "virtualNetwork": expected_vnet,
    }:
        _fail("pre-secret-container-apps-dns-drift")
    if record != {"records": [{"ipv4Address": static_ip}], "ttl": 60}:
        _fail("pre-secret-container-apps-dns-drift")


def _verify_pre_secret_security(
    subscription_id: str,
    target_resources: frozenset[str],
    *,
    require_container_apps_dns: bool = True,
) -> None:
    if "microsoft.keyvault/vaults/kv-mobius77-11564669" in target_resources:
        vault = _verify_resource_projection(
            subscription_id,
            resource_type="Microsoft.KeyVault/vaults",
            name=KEY_VAULT,
            api_version="2026-02-01",
            projection="{defaultAction:properties.networkAcls.defaultAction,purge:properties.enablePurgeProtection,public:properties.publicNetworkAccess,rbac:properties.enableRbacAuthorization,softDelete:properties.enableSoftDelete}",
        )
        if (
            set(vault) != {"defaultAction", "purge", "public", "rbac", "softDelete"}
            or vault["defaultAction"] != "Deny"
            or vault["purge"] not in {None, False}
            or vault["public"] != "Disabled"
            or vault["rbac"] is not True
            or vault["softDelete"] is not True
        ):
            _fail("pre-secret-key-vault-security-drift")
    if "microsoft.containerregistry/registries/acrmobius7711564669" in target_resources:
        registry = _verify_resource_projection(
            subscription_id,
            resource_type="Microsoft.ContainerRegistry/registries",
            name=REGISTRY,
            api_version="2025-11-01",
            projection="{admin:properties.adminUserEnabled,anonymous:properties.anonymousPullEnabled,public:properties.publicNetworkAccess}",
        )
        if registry != {"admin": False, "anonymous": False, "public": "Disabled"}:
            _fail("pre-secret-registry-security-drift")
    if (
        "microsoft.operationalinsights/workspaces/law-mobius77-staging"
        in target_resources
    ):
        workspace = _verify_resource_projection(
            subscription_id,
            resource_type="Microsoft.OperationalInsights/workspaces",
            name="law-mobius77-staging",
            api_version="2026-03-01",
            projection="{ingestion:properties.publicNetworkAccessForIngestion,query:properties.publicNetworkAccessForQuery}",
        )
        if workspace != {"ingestion": "Disabled", "query": "Disabled"}:
            _fail("pre-secret-observability-security-drift")
    if "microsoft.app/managedenvironments/cae-mobius77-staging" in target_resources:
        environment = _verify_resource_projection(
            subscription_id,
            resource_type="Microsoft.App/managedEnvironments",
            name="cae-mobius77-staging",
            api_version="2026-01-01",
            projection="{internal:properties.vnetConfiguration.internal,public:properties.publicNetworkAccess}",
        )
        if environment != {"internal": True, "public": "Disabled"}:
            _fail("pre-secret-compute-security-drift")
        if require_container_apps_dns:
            _verify_container_apps_private_dns(subscription_id)


def _verify_no_related_group_drift(subscription_id: str) -> None:
    rows = _run(
        (
            "az",
            "group",
            "list",
            "--subscription",
            subscription_id,
            "--query",
            "[?contains(to_string(name), 'mobius77')].{name:name}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(rows, list):
        _fail("pre-secret-related-group-inventory-malformed")
    observed: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"name"}
            or not isinstance(row["name"], str)
        ):
            _fail("pre-secret-related-group-inventory-malformed")
        observed.add(row["name"])
    if not observed.issubset({TARGET_GROUP, CLEANUP_GROUP, INFRASTRUCTURE_GROUP}):
        _fail("pre-secret-related-group-drift")


def _verify_container_apps_infrastructure(
    *,
    subscription_id: str,
    ledger: dict[str, JsonValue],
    cleanup_at: datetime,
    allow_prior_binding_with_changed_inputs: bool = False,
) -> int:
    group_scope = _scope(subscription_id, f"/resourceGroups/{INFRASTRUCTURE_GROUP}")
    group = _run(
        (
            "az",
            "group",
            "show",
            "--name",
            INFRASTRUCTURE_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "{id:id,location:location,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected_tags = _lifecycle_tags(
        ledger=ledger,
        cleanup_at=cleanup_at,
        maximum_cost=_verified_cost()[1],
    )
    environment_id = _scope(
        subscription_id,
        f"/resourceGroups/{TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging",
    )
    group_tags = group.get("tags") if isinstance(group, dict) else None
    if (
        not isinstance(group, dict)
        or set(group) != {"id", "location", "tags"}
        or group.get("id") != group_scope
        or group.get("location") != STAGING_LOCATION
        or (
            group_tags != expected_tags
            and not (
                allow_prior_binding_with_changed_inputs
                and _container_apps_infrastructure_tags_reconcilable(
                    group_tags,
                    expected_tags,
                    cleanup_at=cleanup_at,
                    environment_id=environment_id,
                )
            )
            and not _matches_container_apps_infrastructure_tags(
                group_tags,
                expected_tags,
                cleanup_at=cleanup_at,
                environment_id=environment_id,
            )
        )
    ):
        _fail("container-apps-infrastructure-group-drift")

    environment = _verify_resource_projection(
        subscription_id,
        resource_type="Microsoft.App/managedEnvironments",
        name="cae-mobius77-staging",
        api_version="2026-01-01",
        projection=(
            "{infrastructureResourceGroup:properties.infrastructureResourceGroup,"
            "internal:properties.vnetConfiguration.internal,"
            "public:properties.publicNetworkAccess}"
        ),
    )
    if environment != {
        "infrastructureResourceGroup": INFRASTRUCTURE_GROUP,
        "internal": True,
        "public": "Disabled",
    }:
        _fail("container-apps-infrastructure-binding-drift")

    resources = _run(
        (
            "az",
            "resource",
            "list",
            "--resource-group",
            INFRASTRUCTURE_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "[].{id:id,location:location,type:type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(resources, list) or len(resources) != 1:
        _fail("container-apps-infrastructure-resource-drift")
    resource = resources[0]
    resource_id = resource.get("id") if isinstance(resource, dict) else None
    if (
        not isinstance(resource, dict)
        or set(resource) != {"id", "location", "type"}
        or not isinstance(resource_id, str)
        or not resource_id.casefold().startswith(
            f"{group_scope}/providers/microsoft.network/loadbalancers/".casefold()
        )
        or resource.get("location") != STAGING_LOCATION
        or str(resource.get("type", "")).casefold() != "microsoft.network/loadbalancers"
    ):
        _fail("container-apps-infrastructure-resource-drift")

    delegated_subnet = _scope(
        subscription_id,
        f"/resourceGroups/{TARGET_GROUP}/providers/Microsoft.Network/"
        "virtualNetworks/vnet-mobius77-staging/subnets/snet-mobius77-container-apps",
    ).casefold()
    network_contributor = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
        "roleDefinitions/4d97b98b-1d4f-4787-a291-c67834d212e7"
    ).casefold()
    assignments = _run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--scope",
            group_scope,
            "--subscription",
            subscription_id,
            "--query",
            "[].{principalType:principalType,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(assignments, list):
        _fail("container-apps-infrastructure-role-drift")
    allowed_scopes = {group_scope.casefold(), delegated_subnet}
    for assignment in assignments:
        if (
            not isinstance(assignment, dict)
            or set(assignment) != {"principalType", "roleDefinitionId", "scope"}
            or assignment.get("principalType") != "ServicePrincipal"
            or str(assignment.get("roleDefinitionId", "")).casefold()
            != network_contributor
            or str(assignment.get("scope", "")).casefold() not in allowed_scopes
        ):
            _fail("container-apps-infrastructure-role-drift")
    return len(resources)


def _verify_preservable_pre_secret_state(
    *,
    subscription_id: str,
    cleanup_at: datetime,
    ledger: dict[str, JsonValue],
    allow_pending_dns_update: bool = False,
) -> dict[str, JsonValue]:
    if any(
        not _group_exists(subscription_id, group)
        for group in (TARGET_GROUP, CLEANUP_GROUP, INFRASTRUCTURE_GROUP)
    ):
        _fail("pre-secret-authorized-scope-missing")
    _verify_no_related_group_drift(subscription_id)
    cleanup_principal = _verify_cleanup_control(subscription_id, cleanup_at)
    contract = load_managed_binding_contract()
    rbac = contract.get("rbac")
    if not isinstance(rbac, dict):
        _fail("managed-binding-contract-malformed")
    _verify_cleanup_target_role(
        subscription_id,
        cleanup_principal,
        str(rbac["cleanupContributorRoleDefinitionId"]),
    )
    network_interfaces = _private_endpoint_network_interfaces(subscription_id)
    target_resources = _resource_group_inventory(
        subscription_id=subscription_id,
        group=TARGET_GROUP,
        allowed_network_interfaces=network_interfaces,
    )
    cleanup_resources = _resource_group_inventory(
        subscription_id=subscription_id,
        group=CLEANUP_GROUP,
    )
    _verify_pre_secret_role_inventory(
        subscription_id=subscription_id,
        cleanup_principal_id=cleanup_principal,
        target_resources=target_resources,
    )
    _verify_pre_secret_security(
        subscription_id,
        target_resources,
        require_container_apps_dns=not allow_pending_dns_update,
    )
    infrastructure_resource_count = _verify_container_apps_infrastructure(
        subscription_id=subscription_id,
        ledger=ledger,
        cleanup_at=cleanup_at,
        allow_prior_binding_with_changed_inputs=allow_pending_dns_update,
    )
    return {
        "cleanup-backstop-armed": True,
        "cleanup-deadline-active": _utc_now() < cleanup_at,
        "cost-within-ceiling": _verified_cost()[1] <= ABSOLUTE_COST_CEILING_USD_CENTS,
        "known-state": True,
        "least-privilege-exact": True,
        "no-protected-data-exposure": True,
        "private-boundaries-preserved": True,
        "scope-inventory-exact": True,
        "cleanup-resource-count": len(cleanup_resources),
        "infrastructure-resource-count": infrastructure_resource_count,
        "private-endpoint-count": len(network_interfaces),
        "target-resource-count": len(target_resources),
    }


def _verify_terminal_pre_secret_deployment(
    *, subscription_id: str, ledger: dict[str, JsonValue]
) -> str:
    value = _run(
        (
            "az",
            "deployment",
            "sub",
            "show",
            "--name",
            _deployment_name(PRE_SECRET_PRESERVABLE_STAGE, ledger),
            "--subscription",
            subscription_id,
            "--query",
            "{state:properties.provisioningState}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, dict) or set(value) != {"state"}:
        _fail("pre-secret-deployment-state-malformed")
    state = value["state"]
    if state not in {"Canceled", "Failed", "Succeeded"}:
        _fail("pre-secret-deployment-not-terminal")
    return str(state)


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
    cleanup_at = _cleanup_deadline(_utc_now())
    contract = load_managed_binding_contract()
    rbac = contract["rbac"]
    scopes = contract["scopeBinding"]
    if not isinstance(rbac, dict) or not isinstance(scopes, dict):
        _fail("managed-binding-contract-malformed")
    state_path = _state_path(receipt_directory)
    state: dict[str, JsonValue] = {
        "activeStage": "initialization",
        "cleanupAtUtc": _format_utc(cleanup_at),
        "disposition": LifecycleDisposition.RUNNING.value,
        "failedStage": None,
        "lastCompletedStage": None,
        "preSecretDeploymentName": _deployment_name(
            PRE_SECRET_PRESERVABLE_STAGE, ledger
        ),
        "repositoryHead": str(ledger["repositoryHead"]),
        "resumableCheckpoint": PRE_SECRET_PRESERVABLE_STAGE,
        "secretValueAccessed": False,
        "temporaryKeyVaultAssignmentId": None,
        "temporaryRegistryAssignmentId": None,
    }
    _write_state(state_path, state)

    target_exists = _group_exists(subscription_id, TARGET_GROUP)
    cleanup_exists = _group_exists(subscription_id, CLEANUP_GROUP)
    infrastructure_exists = _group_exists(subscription_id, INFRASTRUCTURE_GROUP)
    if target_exists and (not cleanup_exists or not infrastructure_exists):
        _fail("pre-secret-authorized-scope-incomplete")
    if not target_exists and infrastructure_exists:
        _fail("container-apps-infrastructure-group-collision")

    with tempfile.TemporaryDirectory(prefix="mobius77-binding-") as directory:
        template = Path(directory) / "main.json"
        _mark_stage(state_path, state, "compile-template")
        _compile_template(template)
        _mark_stage(state_path, state, "compile-template", completed=True)

        if target_exists:
            _mark_stage(state_path, state, "pre-secret-reconciliation")
            _verify_preservable_pre_secret_state(
                subscription_id=subscription_id,
                cleanup_at=cleanup_at,
                ledger=ledger,
                allow_pending_dns_update=True,
            )
            _mark_stage(state_path, state, "pre-secret-reconciliation", completed=True)
        else:
            if cleanup_exists:
                _mark_stage(state_path, state, "cleanup-recovery-seed-verification")
                _verify_recovered_cleanup_seed_state(subscription_id)
                _mark_stage(
                    state_path,
                    state,
                    "cleanup-recovery-seed-verification",
                    completed=True,
                )
            _mark_stage(state_path, state, "cleanup-control")
            _deploy_stage(
                template_path=template,
                subscription_id=subscription_id,
                ledger=ledger,
                stage="cleanup-control",
                cleanup_at=cleanup_at,
                expected_cost=expected_cost,
                maximum_cost=maximum_cost,
            )
            _mark_stage(state_path, state, "cleanup-control", completed=True)

            _mark_stage(state_path, state, "cleanup-runbook")
            _configure_cleanup_runbook(subscription_id)
            _mark_stage(state_path, state, "cleanup-runbook", completed=True)

            _mark_stage(state_path, state, "cleanup-job-binding")
            _deploy_stage(
                template_path=template,
                subscription_id=subscription_id,
                ledger=ledger,
                stage="cleanup-job-binding",
                cleanup_at=cleanup_at,
                expected_cost=expected_cost,
                maximum_cost=maximum_cost,
            )
            _mark_stage(state_path, state, "cleanup-job-binding", completed=True)

            _mark_stage(state_path, state, "cleanup-control-verification")
            cleanup_principal_id = _verify_cleanup_control(subscription_id, cleanup_at)
            _mark_stage(
                state_path, state, "cleanup-control-verification", completed=True
            )

            _mark_stage(state_path, state, "cleanup-binding")
            _deploy_stage(
                template_path=template,
                subscription_id=subscription_id,
                ledger=ledger,
                stage="cleanup-binding",
                cleanup_at=cleanup_at,
                expected_cost=expected_cost,
                maximum_cost=maximum_cost,
            )
            _mark_stage(state_path, state, "cleanup-binding", completed=True)

            _mark_stage(state_path, state, "cleanup-role-verification")
            _verify_cleanup_target_role(
                subscription_id,
                cleanup_principal_id,
                str(rbac["cleanupContributorRoleDefinitionId"]),
            )
            _mark_stage(state_path, state, "cleanup-role-verification", completed=True)

        _mark_stage(state_path, state, PRE_SECRET_PRESERVABLE_STAGE)
        _deploy_stage(
            template_path=template,
            subscription_id=subscription_id,
            ledger=ledger,
            stage=PRE_SECRET_PRESERVABLE_STAGE,
            cleanup_at=cleanup_at,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
        )
        _mark_stage(state_path, state, PRE_SECRET_PRESERVABLE_STAGE, completed=True)

    _mark_stage(state_path, state, "container-apps-infrastructure-tag-reconciliation")
    _reconcile_container_apps_infrastructure_tags(
        subscription_id=subscription_id,
        ledger=ledger,
        cleanup_at=cleanup_at,
    )
    _mark_stage(
        state_path,
        state,
        "container-apps-infrastructure-tag-reconciliation",
        completed=True,
    )

    _mark_stage(state_path, state, "pre-secret-verification")
    _verify_preservable_pre_secret_state(
        subscription_id=subscription_id, cleanup_at=cleanup_at, ledger=ledger
    )
    _mark_stage(state_path, state, "pre-secret-verification", completed=True)

    object_id = _signed_in_user_object_id()
    vault_scope = _scope(subscription_id, str(scopes["keyVault"]))
    _mark_stage(state_path, state, "temporary-key-vault-authority")
    assignment_id = _temporary_role_assignment(
        subscription_id=subscription_id,
        object_id=object_id,
        role_id=str(rbac["keyVaultSecretsOfficerRoleDefinitionId"]),
        scope=vault_scope,
    )
    state["temporaryKeyVaultAssignmentId"] = assignment_id
    state["activeStage"] = None
    state["disposition"] = LifecycleDisposition.COMPLETED.value
    state["lastCompletedStage"] = "temporary-key-vault-authority"
    state["resumableCheckpoint"] = "secure-manual-entry"
    _replace_state(state_path, state)
    return {
        "disposition": LifecycleDisposition.COMPLETED.value,
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
                    "[:0]",
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                endpoint_host=REGISTRY_HOST,
            )


def _reconcile_published_api_image(
    *, ledger: dict[str, JsonValue], subscription_id: str
) -> str:
    repository_head = str(ledger["repositoryHead"])
    if HEX_SHA40.fullmatch(repository_head) is None:
        _fail("repository-head-invalid")
    _run(
        (
            "git",
            "merge-base",
            "--is-ancestor",
            RECOVERABLE_API_IMAGE_SOURCE_COMMIT,
            repository_head,
        )
    )
    changed_inputs = _run_text(
        (
            "git",
            "diff",
            "--name-only",
            f"{RECOVERABLE_API_IMAGE_SOURCE_COMMIT}..{repository_head}",
            "--",
            *API_IMAGE_BUILD_INPUTS,
        )
    )
    if changed_inputs:
        _fail("recovered-image-build-input-drift")
    source_tag = f"source-{RECOVERABLE_API_IMAGE_SOURCE_COMMIT}"
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
            "[]",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if tags != [source_tag]:
        _fail("recovered-image-source-tag-mismatch")
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
    )
    if not isinstance(digest_projection, dict) or set(digest_projection) != {"digest"}:
        _fail("recovered-image-digest-output-malformed")
    raw_digest = digest_projection["digest"]
    if (
        not isinstance(raw_digest, str)
        or RAW_IMAGE_DIGEST.fullmatch(raw_digest) is None
    ):
        _fail("recovered-image-digest-output-malformed")
    immutable_reference = f"{REGISTRY_HOST}/opencanvas-api@{raw_digest}"
    if IMAGE_DIGEST.fullmatch(immutable_reference) is None:
        _fail("recovered-image-digest-output-malformed")
    return immutable_reference


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
            revision = _run(
                (
                    "az",
                    "containerapp",
                    "revision",
                    "show",
                    "--resource-group",
                    TARGET_GROUP,
                    "--name",
                    "ca-mobius77-api",
                    "--revision",
                    latest,
                    "--subscription",
                    subscription_id,
                    "--query",
                    "{health:properties.healthState,provisioning:properties.provisioningState,running:properties.runningState}",
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                require_json=True,
            )
            if revision == {
                "health": "Healthy",
                "provisioning": "Provisioned",
                "running": "Running",
            }:
                return
            if isinstance(revision, dict) and (
                revision.get("health") == "Unhealthy"
                or revision.get("provisioning") in {"Canceled", "Failed"}
                or revision.get("running") in {"ActivationFailed", "Degraded", "Failed"}
            ):
                _fail("container-app-revision-failed")
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
    api_image_digest = _reconcile_published_api_image(
        ledger=ledger,
        subscription_id=subscription_id,
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
                "[:0]",
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
                "[:0]",
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


def _cleanup_authorization_path(receipt_directory: Path) -> Path:
    return receipt_directory / CLEANUP_AUTHORIZATION_FILE


def _validate_cleanup_authorization(
    *,
    receipt_directory: Path,
    ledger: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    path = _cleanup_authorization_path(receipt_directory)
    if not path.is_file():
        _fail("cleanup-authorization-missing")
    value = load_json(path)
    if not isinstance(value, dict):
        _fail("cleanup-authorization-malformed")
    expected_keys = {
        "authorizationEvidenceSha256",
        "authorizationId",
        "authorizationIntegritySha256",
        "authorizationMode",
        "expiresAtUtc",
        "issuedAtUtc",
        "lifecycleState",
        "repositoryHead",
        "requiredStages",
        "resourceGroups",
        "schemaVersion",
    }
    if set(value) != expected_keys:
        _fail("cleanup-authorization-malformed")
    integrity = value.get("authorizationIntegritySha256")
    if not isinstance(integrity, str) or HEX_SHA256.fullmatch(integrity) is None:
        _fail("cleanup-authorization-malformed")
    unsigned = {
        key: item
        for key, item in value.items()
        if key != "authorizationIntegritySha256"
    }
    expected_integrity = hashlib.sha256(
        CLEANUP_AUTHORIZATION_DOMAIN + canonical_bytes(unsigned)
    ).hexdigest()
    if integrity != expected_integrity:
        _fail("cleanup-authorization-integrity-mismatch")
    issued_raw = value.get("issuedAtUtc")
    expires_raw = value.get("expiresAtUtc")
    if not isinstance(issued_raw, str) or not isinstance(expires_raw, str):
        _fail("cleanup-authorization-time-malformed")
    try:
        issued = datetime.strptime(issued_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        expires = datetime.strptime(expires_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        _fail("cleanup-authorization-time-malformed")
    now = _utc_now()
    if (
        issued > now
        or expires < now
        or expires <= issued
        or expires - issued > CLEANUP_AUTHORIZATION_MAXIMUM_AGE
    ):
        _fail("cleanup-authorization-stale")
    if (
        value.get("schemaVersion") != "mobius.milestone-7.7.cleanup-authorization.v1"
        or value.get("authorizationId") != ledger.get("authorizationId")
        or value.get("repositoryHead") != ledger.get("repositoryHead")
        or value.get("resourceGroups")
        != [TARGET_GROUP, CLEANUP_GROUP, INFRASTRUCTURE_GROUP]
    ):
        _fail("cleanup-authorization-scope-mismatch")
    evidence_sha = value.get("authorizationEvidenceSha256")
    if not isinstance(evidence_sha, str) or HEX_SHA256.fullmatch(evidence_sha) is None:
        _fail("cleanup-authorization-evidence-invalid")
    mode = value.get("authorizationMode")
    lifecycle_state = value.get("lifecycleState")
    stages = value.get("requiredStages")
    required_stage_names = {
        "deployment",
        "evidenceCapture",
        "providerValidation",
        "secureKeyEntry",
        "soak90Minutes",
        "temporaryAccessRevocation",
    }
    if not isinstance(stages, dict) or set(stages) != required_stage_names:
        _fail("cleanup-authorization-stages-malformed")
    if mode == "successful-closeout":
        if lifecycle_state != LifecycleDisposition.READY_FOR_FINAL_CLEANUP.value or any(
            stages[name] is not True for name in required_stage_names
        ):
            _fail("cleanup-success-evidence-incomplete")
    elif mode == "explicit-user":
        if lifecycle_state not in {
            LifecycleDisposition.PAUSED_PRESERVED.value,
            LifecycleDisposition.CONTAINED_PRESERVED.value,
        } or any(stages[name] is not False for name in required_stage_names):
            _fail("cleanup-explicit-authorization-malformed")
    else:
        _fail("cleanup-authorization-mode-invalid")
    return value


def _cleanup(
    subscription_id: str,
    receipt_directory: Path,
    *,
    ledger: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    _validate_cleanup_authorization(receipt_directory=receipt_directory, ledger=ledger)
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
    if _group_exists(subscription_id, INFRASTRUCTURE_GROUP):
        _run(
            (
                "az",
                "group",
                "delete",
                "--name",
                INFRASTRUCTURE_GROUP,
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
    for group in (TARGET_GROUP, INFRASTRUCTURE_GROUP, CLEANUP_GROUP):
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


def _sanitized_failure(error: BaseException) -> tuple[str, str | None]:
    azure_code = (
        error.sanitized_azure_error_code
        if isinstance(error, AzureCommandError)
        else None
    )
    candidate = str(error)
    if re.fullmatch(r"[a-z0-9-]+", candidate) is None:
        candidate = "managed-binding-lifecycle-failed-closed"
    return candidate, azure_code


def _state_for_pre_secret_preservation(
    *,
    state_path: Path,
    ledger: dict[str, JsonValue],
    now: datetime,
) -> tuple[dict[str, JsonValue], datetime]:
    state = _read_state(state_path)
    if set(state) != {
        "activeStage",
        "cleanupAtUtc",
        "disposition",
        "failedStage",
        "lastCompletedStage",
        "preSecretDeploymentName",
        "repositoryHead",
        "resumableCheckpoint",
        "secretValueAccessed",
        "temporaryKeyVaultAssignmentId",
        "temporaryRegistryAssignmentId",
    }:
        _fail("pre-secret-state-malformed")
    cleanup_at_raw = state["cleanupAtUtc"]
    if not isinstance(cleanup_at_raw, str):
        _fail("pre-secret-state-malformed")
    try:
        cleanup_at = datetime.strptime(cleanup_at_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        _fail("pre-secret-state-malformed")
    if (
        state["activeStage"] != PRE_SECRET_PRESERVABLE_STAGE
        or state["disposition"] != LifecycleDisposition.RUNNING.value
        or state["failedStage"] is not None
        or state["lastCompletedStage"]
        not in {"cleanup-role-verification", "pre-secret-reconciliation"}
        or state["preSecretDeploymentName"]
        != _deployment_name(PRE_SECRET_PRESERVABLE_STAGE, ledger)
        or state["repositoryHead"] != ledger.get("repositoryHead")
        or state["resumableCheckpoint"] != PRE_SECRET_PRESERVABLE_STAGE
        or state["secretValueAccessed"] is not False
        or state["temporaryKeyVaultAssignmentId"] is not None
        or state["temporaryRegistryAssignmentId"] is not None
        or cleanup_at != AUTHORIZED_CLEANUP_AT_UTC
        or now >= cleanup_at - MINIMUM_CLEANUP_RESERVE
    ):
        _fail("pre-secret-state-not-preservable")
    return state, cleanup_at


def _validate_preservation_proof(proof: dict[str, JsonValue]) -> None:
    required_true = {
        "cleanup-backstop-armed",
        "cleanup-deadline-active",
        "cost-within-ceiling",
        "known-state",
        "least-privilege-exact",
        "no-protected-data-exposure",
        "private-boundaries-preserved",
        "scope-inventory-exact",
    }
    count_fields = {
        "cleanup-resource-count",
        "infrastructure-resource-count",
        "private-endpoint-count",
        "target-resource-count",
    }
    if set(proof) != required_true | count_fields:
        _fail("pre-secret-preservation-proof-malformed")
    if any(proof[key] is not True for key in required_true):
        _fail("pre-secret-preservation-proof-incomplete")
    for key in count_fields:
        value = proof[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            _fail("pre-secret-preservation-proof-malformed")
    cleanup_resource_count = proof["cleanup-resource-count"]
    if (
        not isinstance(cleanup_resource_count, int)
        or isinstance(cleanup_resource_count, bool)
        or cleanup_resource_count < 1
    ):
        _fail("pre-secret-preservation-proof-incomplete")


def _safe_failed_stage(receipt_directory: Path | None) -> str:
    if receipt_directory is None:
        return "unknown"
    path = _state_path(receipt_directory)
    if not path.is_file():
        return "unknown"
    try:
        state = _read_state(path)
    except (ContractError, LifecycleError, OSError, ValueError):
        return "unknown"
    stage = state.get("activeStage")
    if isinstance(stage, str) and re.fullmatch(r"[a-z0-9-]+", stage) is not None:
        return stage
    return "unknown"


def _failure_record(
    *,
    disposition: LifecycleDisposition,
    operation: str,
    failed_stage: str,
    error_code: str,
    azure_error_code: str | None,
    proof: dict[str, JsonValue],
    resumable_checkpoint: str | None,
    cleanup_status: str,
    ledger: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    deployment_name: str | None = None
    repository_head: str | None = None
    if ledger is not None:
        repository_head_value = ledger.get("repositoryHead")
        if (
            isinstance(repository_head_value, str)
            and HEX_SHA40.fullmatch(repository_head_value) is not None
        ):
            repository_head = repository_head_value
        if operation == "pre-secret-provisioning":
            deployment_name = _deployment_name(PRE_SECRET_PRESERVABLE_STAGE, ledger)
    return {
        "cleanupAtUtc": _format_utc(AUTHORIZED_CLEANUP_AT_UTC),
        "cleanupStatus": cleanup_status,
        "disposition": disposition.value,
        "failedStage": failed_stage,
        "operation": operation,
        "preservationProof": proof,
        "recordedAtUtc": _format_utc(_utc_now()),
        "repositoryHead": repository_head,
        "resumableCheckpoint": resumable_checkpoint,
        "safeIdentifiers": {
            "cleanupResourceGroup": CLEANUP_GROUP,
            "containerAppsInfrastructureResourceGroup": INFRASTRUCTURE_GROUP,
            "preSecretDeploymentName": deployment_name,
            "targetResourceGroup": TARGET_GROUP,
        },
        "sanitizedAzureErrorCode": azure_error_code,
        "sanitizedErrorCode": error_code,
        "schemaVersion": "mobius.milestone-7.7.lifecycle-disposition.v1",
        "secretValueAccessed": False,
    }


def _handle_failure(
    *,
    error: BaseException,
    operation: str,
    ledger: dict[str, JsonValue] | None,
    subscription_id: str | None,
    receipt_directory: Path | None,
) -> dict[str, JsonValue]:
    error_code, azure_error_code = _sanitized_failure(error)
    failure_disposition = (
        LifecycleDisposition.CONTAINED_PRESERVED
        if error_code in SECURITY_CONTAINMENT_ERROR_CODES
        else LifecycleDisposition.PAUSED_PRESERVED
    )
    failed_stage = _safe_failed_stage(receipt_directory)
    cancellation_codes = {
        "canceled",
        "cancelled",
        "operation-canceled",
        "operation-cancelled",
    }
    if (
        operation == "pre-secret-provisioning"
        and ledger is not None
        and subscription_id is not None
        and receipt_directory is not None
        and not isinstance(error, KeyboardInterrupt)
        and azure_error_code not in cancellation_codes
    ):
        try:
            state_path = _state_path(receipt_directory)
            state, cleanup_at = _state_for_pre_secret_preservation(
                state_path=state_path,
                ledger=ledger,
                now=_utc_now(),
            )
            terminal_state = _verify_terminal_pre_secret_deployment(
                subscription_id=subscription_id, ledger=ledger
            )
            if terminal_state == "Canceled":
                _fail("pre-secret-deployment-canceled")
            proof = _verify_preservable_pre_secret_state(
                subscription_id=subscription_id, cleanup_at=cleanup_at, ledger=ledger
            )
            _validate_preservation_proof(proof)
            proof = {**proof, "deployment-terminal-state": terminal_state}
            state["activeStage"] = None
            state["disposition"] = failure_disposition.value
            state["failedStage"] = PRE_SECRET_PRESERVABLE_STAGE
            _replace_state(state_path, state)
            record = _failure_record(
                disposition=failure_disposition,
                operation=operation,
                failed_stage=PRE_SECRET_PRESERVABLE_STAGE,
                error_code=error_code,
                azure_error_code=azure_error_code,
                proof=proof,
                resumable_checkpoint=PRE_SECRET_PRESERVABLE_STAGE,
                cleanup_status="preserved-safe-pre-secret-state",
                ledger=ledger,
            )
            _write_disposition(receipt_directory, record)
            return {
                "cleanup-status": "preserved-safe-pre-secret-state",
                "disposition": failure_disposition.value,
                "error": error_code,
                "provisioning-authorized": False,
                "resumable-checkpoint": PRE_SECRET_PRESERVABLE_STAGE,
                "sanitized-azure-error-code": azure_error_code,
                "secret-value-accessed": False,
                "status": "blocked",
            }
        except (Exception, KeyboardInterrupt):
            pass

    cleanup_status = "not-authorized-preserved"
    if receipt_directory is not None:
        state_path = _state_path(receipt_directory)
        if state_path.is_file():
            try:
                state = _read_state(state_path)
                state["activeStage"] = None
                state["disposition"] = failure_disposition.value
                state["failedStage"] = failed_stage
                state["resumableCheckpoint"] = failed_stage
                _replace_state(state_path, state)
            except (ContractError, LifecycleError, OSError, ValueError):
                pass
    record = _failure_record(
        disposition=failure_disposition,
        operation=operation,
        failed_stage=failed_stage,
        error_code=error_code,
        azure_error_code=azure_error_code,
        proof={"proved": False},
        resumable_checkpoint=None,
        cleanup_status=cleanup_status,
        ledger=ledger,
    )
    disposition_evidence = "not-written-before-receipt-directory"
    if receipt_directory is not None:
        try:
            _write_disposition(receipt_directory, record)
            disposition_evidence = "recorded"
        except (ContractError, LifecycleError, OSError, ValueError):
            disposition_evidence = "failed-closed"
    return {
        "cleanup-status": cleanup_status,
        "disposition": failure_disposition.value,
        "disposition-evidence": disposition_evidence,
        "error": error_code,
        "provisioning-authorized": False,
        "sanitized-azure-error-code": azure_error_code,
        "secret-value-accessed": False,
        "status": "blocked",
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
    ledger: dict[str, JsonValue] | None = None
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
            result = _cleanup(
                subscription_id,
                receipt_directory,
                ledger=ledger,
            )
        else:
            result = _zero_residue(subscription_id)
        result.setdefault("disposition", LifecycleDisposition.COMPLETED.value)
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(
            json.dumps(
                _handle_failure(
                    error=exc,
                    operation=args.operation,
                    ledger=ledger,
                    subscription_id=subscription_id,
                    receipt_directory=receipt_directory,
                ),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
