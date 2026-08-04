"""Closed, one-run lifecycle executor for the Milestone 7.7 managed binding.

The permanent contract remains deny-all.  This entry point accepts only an
unexpired integrity-bound ledger, exact operation names, exact resource names,
and repository-owned templates.  It never accepts or reads provider secret
values.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Final, NoReturn, cast
from urllib.parse import urlsplit

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
    cleanup_runbook_sha256,
    load_managed_binding_contract,
    validate_authorization_ledger,
)

_CANONICAL_LIFECYCLE_MODULE: Final = (
    "infra.milestone_7_7.scripts.managed_binding_lifecycle"
)
if __name__ == "__main__":
    _existing_lifecycle_module = sys.modules.get(_CANONICAL_LIFECYCLE_MODULE)
    if (
        _existing_lifecycle_module is not None
        and _existing_lifecycle_module is not sys.modules[__name__]
    ):
        raise RuntimeError("lifecycle module identity collision")
    sys.modules[_CANONICAL_LIFECYCLE_MODULE] = sys.modules[__name__]

_LIFECYCLE_MODULE_IDENTITY: Final = object()

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
REDIS_LOCATION: Final = "australiacentral"
AUTHORIZED_CLEANUP_AT_UTC: Final = datetime(2026, 8, 4, 9, 15, tzinfo=UTC)
MAXIMUM_AUTHORIZED_WINDOW: Final = timedelta(hours=30)
MINIMUM_CLEANUP_RESERVE: Final = timedelta(minutes=90)
PROVISIONING_COST_BLOCK_USD_CENTS: Final = 12_000
ABSOLUTE_COST_CEILING_USD_CENTS: Final = 17_500
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
PUBLISHER_REPOSITORY: Final = "opencanvas-api"
API_IMAGE_PLATFORM: Final = "linux/amd64"
API_IMAGE_BUILDER_PREFIX: Final = "mobius77-api-build-"
API_IMAGE_BUILD_INPUT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/api-image-build-input/v1\x00"
)
PREBUILT_IMAGE_RECORD_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/prebuilt-api-image/v1\x00"
)
PREBUILT_IMAGE_RECORD_VERSION: Final = "mobius.milestone-7.7.prebuilt-api-image.v1"
DOCKER_PUSH_MAXIMUM_ATTEMPTS: Final = 2
ACR_TOKEN_RESOURCE: Final = "https://containerregistry.azure.net"
ACR_REFRESH_TOKEN_USERNAME: Final = "00000000-0000-0000-0000-000000000000"
PUBLISHER_REPOSITORY_SCOPE: Final = f"repository:{PUBLISHER_REPOSITORY}:pull,push"
MAXIMUM_TOKEN_BYTES: Final = 16_384
TOKEN_BYTES: Final = re.compile(rb"^[A-Za-z0-9._~+/=-]{32,16384}$")
MANIFEST_ACCEPT: Final = (
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json"
)
RECOVERABLE_API_IMAGE_SOURCE_COMMIT: Final = "24dbad86c44baef53120d75ed993ac8165549f72"
API_IMAGE_BUILD_INPUTS: Final = (
    "apps/api/Dockerfile",
    "apps/api/Dockerfile.dockerignore",
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
OPERATION_ATTRIBUTION_FILE: Final = "managed-binding-operation-attribution.json"
OPERATION_ATTRIBUTION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/operation-attribution/v1\x00"
)
OPERATION_ID_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/protected-operation-id/v1\x00"
)
LIFECYCLE_PROCESS_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/lifecycle-process/v1\x00"
)
OPERATION_ATTRIBUTION_LOCK_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/operation-attribution-lock/v1\x00"
)
OPERATION_ATTRIBUTION_LOCK_FILE: Final = (
    "managed-binding-operation-attribution.lock.json"
)
CORRELATION_HASH_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/operation-correlation/v1\x00"
)
PROTECTED_OPERATION_CATALOG: Final = (
    ("pre-secret-provisioning", "key-vault-temporary-authority-creation"),
    ("pre-secret-provisioning", "key-vault-authority-propagation-proof"),
    ("post-secret-provisioning", "key-vault-secret-metadata-listing"),
    ("post-secret-provisioning", "key-vault-temporary-authority-creation"),
    ("post-secret-provisioning", "key-vault-authority-propagation-proof"),
    ("post-secret-provisioning", "key-vault-temporary-authority-revocation"),
    ("post-secret-provisioning", "key-vault-post-revocation-denial-proof"),
    (
        "post-secret-provisioning",
        "publisher-application-and-service-principal-creation",
    ),
    ("post-secret-provisioning", "initial-acr-denial-token-proof"),
    ("post-secret-provisioning", "acrpush-assignment-creation"),
    ("post-secret-provisioning", "acrpush-propagation-verification"),
    ("post-secret-provisioning", "acrpush-propagation-token-verification"),
    ("post-secret-provisioning", "entra-token-acquisition"),
    ("post-secret-provisioning", "private-acr-oauth-exchange"),
    ("post-secret-provisioning", "private-acr-docker-login"),
    ("post-secret-provisioning", "repository-specific-digest-verification"),
    ("post-secret-provisioning", "immutable-image-publication"),
    ("post-secret-provisioning", "mutable-tag-removal"),
    ("post-secret-provisioning", "temporary-role-revocation"),
    ("post-secret-provisioning", "post-revocation-token-denial-proof"),
    ("post-secret-provisioning", "acr-manifest-denial-proof"),
    ("post-secret-provisioning", "acr-pull-denial-proof"),
    ("post-secret-provisioning", "acr-push-denial-proof"),
    ("post-secret-provisioning", "publisher-identity-and-credential-deletion"),
    ("post-secret-provisioning", "publisher-credential-and-cache-deletion"),
    ("temporary-authority-revocation", "temporary-role-revocation"),
    ("cleanup", "failure-cleanup-and-resource-group-deletion"),
    ("cleanup", "preserved-environment-reconciliation"),
)
LOCAL_PRE_REQUEST_ERROR_CODES: Final = frozenset(
    {
        "lifecycle-bookkeeping-failed",
        "lifecycle-process-launch-failed",
        "lifecycle-serialization-failed",
        "protected-operation-attribution-reconciliation-failed",
    }
)
TRANSIENT_STATE_FIELDS: Final = frozenset(
    {
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
        "temporaryKeyVaultAuthorityLedgerSha256",
        "temporaryKeyVaultAuthorityProved",
        "temporaryRegistryAssignmentId",
    }
)
KEY_VAULT_AUTHORITY_PROVED_STAGE: Final = "key-vault-authority-proved"
KEY_VAULT_AUTHORITY_REVOKED_STAGE: Final = "key-vault-authority-revoked"
LEGACY_TRANSIENT_STATE_FIELDS: Final = TRANSIENT_STATE_FIELDS - {
    "temporaryKeyVaultAuthorityLedgerSha256",
    "temporaryKeyVaultAuthorityProved",
}
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
        "microsoft.managedidentity/userassignedidentities/id-mobius77-worker",
        "southcentralus",
    ),
    (
        "microsoft.managedidentity/userassignedidentities/id-mobius77-telemetry",
        "southcentralus",
    ),
    (
        "microsoft.managedidentity/userassignedidentities/id-mobius77-db-admin",
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


class PublisherAccessPending(LifecycleError):
    """The exact repository scope has not propagated to ACR yet."""


class PublisherOAuthTransient(LifecycleError):
    """One explicitly recognized, non-mutating OAuth condition may be retried once."""


class DockerPushTransient(LifecycleError):
    """One recognized ordinary-push transport rejection may be retried once."""


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
    require_text: bool = False,
    environment_overrides: Mapping[str, str] | None = None,
    working_directory: Path | None = None,
) -> JsonValue | None:
    if require_json and require_text:
        _fail("lifecycle-output-contract-conflict")
    if not argv or argv[0] not in {"az", "bicep", "docker", "git"}:
        _fail("lifecycle-executable-unapproved")
    attribution, operation_id, attribution_spec = _begin_process_attribution(
        argv, environment_overrides=environment_overrides
    )
    executable = _resolved_executable(argv[0])
    actual = (executable, *argv[1:])
    if argv[0] == "az":
        try:
            actual = _resolve_authorized_process_launch(("az", *argv[1:])).argv
        except Exception:
            _fail("azure-launcher-unapproved")
    environment = _environment()
    if environment_overrides is not None:
        if set(environment_overrides) - {
            "AZURE_CONFIG_DIR",
            "DOCKER_CONFIG",
            "USERPROFILE",
        }:
            _fail("lifecycle-environment-override-unapproved")
        for key, value in environment_overrides.items():
            if not isinstance(value, str):
                _fail("lifecycle-environment-override-unapproved")
            resolved = _outside_repository(Path(value), key.casefold())
            if not resolved.is_dir():
                _fail("lifecycle-environment-override-unapproved")
        environment.update(environment_overrides)
    execution_directory = REPOSITORY_ROOT
    if working_directory is not None:
        execution_directory = _outside_repository(
            working_directory, "lifecycle-working-directory"
        )
        if not execution_directory.is_dir():
            _fail("lifecycle-working-directory-invalid")
    if (
        attribution is not None
        and operation_id is not None
        and attribution_spec is not None
    ):
        attribution.mark_request_attempt_began(
            operation_id,
            cleanup_or_revocation=attribution_spec["cleanupOrRevocation"] is True,
        )
    try:
        completed = subprocess.run(
            actual,
            cwd=execution_directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="lifecycle-process-timed-out",
            correlation_hash=None,
            terminal_disposition="TIMED_OUT",
        )
        _fail("lifecycle-process-timed-out")
    except KeyboardInterrupt:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="lifecycle-process-cancelled",
            correlation_hash=None,
            terminal_disposition="CANCELLED",
        )
        raise
    except OSError:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="lifecycle-process-launch-failed",
            correlation_hash=None,
            terminal_disposition="UNCERTAIN",
        )
        _fail("lifecycle-process-launch-failed")
    if attribution is not None and operation_id is not None:
        attribution.mark_azure_request_issued(operation_id)
    stdout = bytearray(completed.stdout)
    stderr = bytearray(completed.stderr)
    attribution_finished = False
    try:
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("lifecycle-output-oversized")
        if completed.returncode != 0:
            if argv[0] == "az":
                azure_error_code = _sanitized_azure_error_code(stdout, stderr)
                _finish_process_attribution(
                    attribution,
                    operation_id,
                    status_code=_sanitized_status_code(
                        stdout,
                        stderr,
                        default="403"
                        if azure_error_code == "forbidden"
                        else "not-reported",
                    ),
                    azure_error_code=azure_error_code,
                    correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                    terminal_disposition="FAILED",
                )
                attribution_finished = True
                raise AzureCommandError(azure_error_code)
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code="not-reported",
                azure_error_code="lifecycle-command-nonzero",
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
            attribution_finished = True
            _fail("lifecycle-command-nonzero")
        if not require_json and not require_text:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code="2xx-not-reported",
                azure_error_code=None,
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="SUCCEEDED",
            )
            attribution_finished = True
            return None
        if require_text:
            try:
                value_text = bytes(stdout).decode("utf-8", errors="strict")
            except UnicodeError:
                _fail("lifecycle-text-malformed")
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code="2xx-not-reported",
                azure_error_code=None,
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="SUCCEEDED",
            )
            attribution_finished = True
            return value_text
        try:
            text = bytes(stdout).decode("utf-8", errors="strict")
            value = json.loads(text)
        except (UnicodeError, json.JSONDecodeError):
            _fail("lifecycle-json-malformed")
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="2xx-not-reported",
            azure_error_code=None,
            correlation_hash=_sanitized_correlation_hash(stdout, stderr),
            terminal_disposition="SUCCEEDED",
        )
        attribution_finished = True
        return cast(JsonValue, value)
    except BaseException as exc:
        if not attribution_finished:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=_sanitized_status_code(
                    stdout, stderr, default="not-reported"
                ),
                azure_error_code=_safe_attribution_error(exc),
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
        raise
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


_ACTIVE_ATTRIBUTION: ContextVar[_OperationAttribution | None] = ContextVar(
    "managed_binding_active_attribution", default=None
)
_ATTRIBUTION_EXPECTED_AUTHORIZATION: ContextVar[str] = ContextVar(
    "managed_binding_attribution_expected_authorization", default="allow"
)
_ATTRIBUTION_SUBSTAGE: ContextVar[str | None] = ContextVar(
    "managed_binding_attribution_substage", default=None
)


def _operation_attribution_path(receipt_directory: Path) -> Path:
    return receipt_directory / OPERATION_ATTRIBUTION_FILE


def _operation_attribution_lock_path(receipt_directory: Path) -> Path:
    return receipt_directory / OPERATION_ATTRIBUTION_LOCK_FILE


def _lifecycle_process_id(*, ledger_integrity: str, repository_head: str) -> str:
    if (
        HEX_SHA256.fullmatch(ledger_integrity) is None
        or HEX_SHA40.fullmatch(repository_head) is None
    ):
        _fail("protected-operation-attribution-binding-invalid")
    return hashlib.sha256(
        LIFECYCLE_PROCESS_DOMAIN
        + ledger_integrity.encode("ascii")
        + b"\x00"
        + repository_head.encode("ascii")
    ).hexdigest()


def _process_is_running(process_id: int) -> bool:
    if process_id < 1:
        return False
    if process_id == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _attribution_lock_integrity(value: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(
        OPERATION_ATTRIBUTION_LOCK_DOMAIN + canonical_bytes(dict(value))
    ).hexdigest()


def _acquire_operation_attribution_lock(
    *, receipt_directory: Path, lifecycle_process_id: str
) -> Path:
    path = _operation_attribution_lock_path(receipt_directory)
    for attempt in range(2):
        body: dict[str, JsonValue] = {
            "acquiredAtUtc": _format_utc(_utc_now()),
            "lifecycleProcessId": lifecycle_process_id,
            "ownerProcessId": os.getpid(),
            "schemaVersion": "mobius.milestone-7.7.operation-attribution-lock.v1",
        }
        document = {**body, "integritySha256": _attribution_lock_integrity(body)}
        try:
            _write_state(path, document)
            return path
        except LifecycleError as exc:
            if str(exc) != "transient-state-already-present" or attempt != 0:
                raise
        try:
            observed = _read_state(path)
        except (ContractError, LifecycleError, OSError, ValueError):
            _fail("protected-operation-attribution-lock-invalid")
        if set(observed) != {
            "acquiredAtUtc",
            "integritySha256",
            "lifecycleProcessId",
            "ownerProcessId",
            "schemaVersion",
        }:
            _fail("protected-operation-attribution-lock-invalid")
        unsigned = {
            key: value for key, value in observed.items() if key != "integritySha256"
        }
        owner = observed.get("ownerProcessId")
        if (
            observed.get("schemaVersion")
            != "mobius.milestone-7.7.operation-attribution-lock.v1"
            or observed.get("lifecycleProcessId") != lifecycle_process_id
            or not isinstance(owner, int)
            or isinstance(owner, bool)
            or observed.get("integritySha256") != _attribution_lock_integrity(unsigned)
        ):
            _fail("protected-operation-attribution-lock-invalid")
        if _process_is_running(owner):
            _fail("protected-operation-attribution-concurrent-process")
        attribution_path = _operation_attribution_path(receipt_directory)
        if attribution_path.is_file():
            prior = _read_state(attribution_path)
            if prior.get("activeOperation") is not None:
                _fail("protected-operation-attribution-interrupted-operation")
        try:
            path.unlink()
        except OSError:
            _fail("protected-operation-attribution-lock-reconcile-failed")
    _fail("protected-operation-attribution-lock-unavailable")


def _release_operation_attribution_lock(
    path: Path, *, lifecycle_process_id: str
) -> None:
    observed = _read_state(path)
    if (
        observed.get("lifecycleProcessId") != lifecycle_process_id
        or observed.get("ownerProcessId") != os.getpid()
    ):
        _fail("protected-operation-attribution-lock-ownership-mismatch")
    try:
        path.unlink()
    except OSError:
        _fail("protected-operation-attribution-lock-release-failed")


def _safe_operation_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if re.fullmatch(r"[a-z0-9-]{1,96}", normalized) is None:
        _fail("protected-operation-attribution-invalid")
    return normalized


def _safe_attribution_error(error: BaseException) -> str:
    if isinstance(error, AzureCommandError):
        return error.sanitized_azure_error_code
    candidate = str(error)
    if re.fullmatch(r"[a-z0-9-]{1,96}", candidate) is not None:
        return candidate
    return "failed-closed"


def _sanitized_status_code(
    stdout: bytearray, stderr: bytearray, *, default: str
) -> str:
    for buffer in (stderr, stdout):
        try:
            decoded = bytes(buffer).decode("utf-8", errors="strict")
        except UnicodeError:
            continue
        matched = re.search(
            r"(?i)\b(?:http\s*)?(?:status(?:\s*code)?)?\s*[:=]?\s*([1-5]\d{2})\b",
            decoded,
        )
        if matched is not None:
            return matched.group(1)
    return default


def _sanitized_correlation_hash(stdout: bytearray, stderr: bytearray) -> str | None:
    pattern = re.compile(
        r'(?i)(?:"(?:correlationId|requestId)"|\b(?:correlation|request)[-_ ]?id)'
        r'\s*[:=]\s*"?([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})\b'
    )
    for buffer in (stderr, stdout):
        try:
            decoded = bytes(buffer).decode("utf-8", errors="strict")
        except UnicodeError:
            continue
        matched = pattern.search(decoded)
        if matched is not None:
            return hashlib.sha256(
                CORRELATION_HASH_DOMAIN + matched.group(1).casefold().encode("ascii")
            ).hexdigest()
    return None


def _expected_authorization_result() -> str:
    value = _ATTRIBUTION_EXPECTED_AUTHORIZATION.get()
    if value not in {"allow", "deny"}:
        _fail("protected-operation-attribution-invalid")
    return value


def _process_attribution_spec(
    argv: tuple[str, ...],
    *,
    environment_overrides: Mapping[str, str] | None,
    expected_authorization: str | None = None,
) -> dict[str, JsonValue]:
    if not argv:
        _fail("protected-operation-attribution-invalid")
    command = argv[0]
    operation_class = ""
    lifecycle_substage = _ATTRIBUTION_SUBSTAGE.get()
    service_class = ""
    endpoint_class = ""
    mutation = False
    cleanup_or_revocation = False

    if command == "az":
        process_map: dict[tuple[str, ...], tuple[str, str, str, bool, bool]] = {
            ("az", "keyvault", "secret", "list"): (
                "key-vault-secret-metadata-listing",
                "key-vault-secret-metadata-listing",
                "key-vault-data-plane",
                False,
                False,
            ),
            ("az", "ad", "sp", "create-for-rbac"): (
                "publisher-application-and-service-principal-creation",
                "publisher-application-and-service-principal-creation",
                "microsoft-graph",
                True,
                False,
            ),
            ("az", "ad", "sp", "delete"): (
                "publisher-service-principal-deletion",
                "publisher-identity-and-credential-deletion",
                "microsoft-graph",
                True,
                True,
            ),
            ("az", "ad", "app", "delete"): (
                "publisher-application-deletion",
                "publisher-identity-and-credential-deletion",
                "microsoft-graph",
                True,
                True,
            ),
            ("az", "ad", "sp", "show"): (
                "publisher-service-principal-propagation-verification",
                "publisher-service-principal-propagation-verification",
                "microsoft-graph",
                False,
                False,
            ),
            ("az", "ad", "sp", "list"): (
                "publisher-service-principal-inventory",
                "publisher-identity-and-credential-deletion",
                "microsoft-graph",
                False,
                False,
            ),
            ("az", "ad", "app", "list"): (
                "publisher-application-inventory",
                "publisher-identity-and-credential-deletion",
                "microsoft-graph",
                False,
                False,
            ),
            ("az", "role", "assignment", "create"): (
                "acrpush-assignment-creation",
                "acrpush-assignment-creation",
                "azure-resource-manager",
                True,
                False,
            ),
            ("az", "role", "assignment", "delete"): (
                "temporary-role-revocation",
                "temporary-role-revocation",
                "azure-resource-manager",
                True,
                True,
            ),
            ("az", "role", "assignment", "list"): (
                "acrpush-propagation-verification",
                "acrpush-propagation-verification",
                "azure-resource-manager",
                False,
                False,
            ),
            (
                "az",
                "login",
                "--service-principal",
            ): (
                "publisher-certificate-authentication",
                "publisher-certificate-authentication",
                "microsoft-entra",
                False,
                False,
            ),
            ("az", "account", "get-access-token"): (
                "entra-token-acquisition",
                "entra-token-acquisition",
                "microsoft-entra",
                False,
                False,
            ),
            ("az", "deployment", "group", "create"): (
                "managed-runtime-deployment",
                "managed-runtime-deployment",
                "azure-resource-manager",
                True,
                False,
            ),
            ("az", "group", "delete"): (
                "resource-group-cleanup",
                "failure-cleanup-and-resource-group-deletion",
                "azure-resource-manager",
                True,
                True,
            ),
            ("az", "group", "exists"): (
                "preserved-environment-reconciliation",
                "failure-cleanup-and-preserved-environment-reconciliation",
                "azure-resource-manager",
                False,
                False,
            ),
            ("az", "keyvault", "purge"): (
                "key-vault-cleanup",
                "failure-cleanup-and-resource-group-deletion",
                "azure-resource-manager",
                True,
                True,
            ),
            ("az", "bicep", "build"): (
                "template-compilation",
                "template-compilation",
                "local-tooling",
                False,
                False,
            ),
        }
        matched_key = next(
            (key for key in process_map if argv[: len(key)] == key), None
        )
        mapped = process_map.get(matched_key) if matched_key is not None else None
        if mapped is None:
            safe = "-".join(_safe_operation_token(value) for value in argv[:4])
            operation_class = f"process-{safe}"
            service_class = "azure-resource-manager"
            endpoint_class = "azure-management-plane"
        else:
            (
                operation_class,
                mapped_substage,
                service_class,
                mutation,
                cleanup_or_revocation,
            ) = mapped
            lifecycle_substage = (
                mapped_substage
                if matched_key
                in {
                    ("az", "account", "get-access-token"),
                    ("az", "login", "--service-principal"),
                }
                else lifecycle_substage or mapped_substage
            )
            if lifecycle_substage in {
                "key-vault-temporary-authority-creation",
                "key-vault-authority-propagation-proof",
                "key-vault-temporary-authority-revocation",
                "key-vault-post-revocation-denial-proof",
            }:
                operation_class = lifecycle_substage
        endpoint_class = {
            "key-vault-data-plane": "private-key-vault-data-plane",
            "local-tooling": "local-process",
            "microsoft-entra": "microsoft-entra-token-endpoint",
            "microsoft-graph": "microsoft-graph",
        }.get(service_class, "azure-management-plane")
    elif command == "docker":
        docker_map: dict[tuple[str, ...], tuple[str, str, bool]] = {
            ("docker", "buildx", "build"): (
                "immutable-image-publication",
                "immutable-image-publication",
                True,
            ),
            ("docker", "manifest", "inspect"): (
                "acr-manifest-denial-proof",
                "post-revocation-manifest-denial-proof",
                False,
            ),
            ("docker", "pull"): (
                "acr-pull-denial-proof",
                "post-revocation-pull-denial-proof",
                False,
            ),
            ("docker", "push"): (
                "acr-push-denial-proof",
                "post-revocation-push-denial-proof",
                True,
            ),
            ("docker", "image", "rm"): (
                "publisher-local-image-cleanup",
                "publisher-identity-and-credential-deletion",
                False,
            ),
            ("docker", "login"): (
                "private-acr-docker-login",
                "private-acr-docker-login",
                False,
            ),
            ("docker", "logout"): (
                "publisher-docker-credential-clearance",
                "publisher-identity-and-credential-deletion",
                False,
            ),
            ("docker", "tag"): (
                "publisher-local-revocation-probe-preparation",
                "publisher-local-revocation-probe-preparation",
                False,
            ),
        }
        docker_matched_key = next(
            (key for key in docker_map if argv[: len(key)] == key), None
        )
        docker_mapped = (
            docker_map.get(docker_matched_key)
            if docker_matched_key is not None
            else None
        )
        if docker_mapped is None:
            safe = "-".join(_safe_operation_token(value) for value in argv[:2])
            operation_class = f"process-{safe}"
            lifecycle_substage = lifecycle_substage or operation_class
        else:
            operation_class, mapped_substage, mutation = docker_mapped
            lifecycle_substage = lifecycle_substage or mapped_substage
            if (
                docker_matched_key == ("docker", "push")
                and lifecycle_substage == "immutable-image-publication"
            ):
                operation_class = "ordinary-docker-image-push"
        service_class = "azure-container-registry-data-plane"
        endpoint_class = "private-acr-registry-data-plane"
    elif command == "git":
        operation_class = "repository-state-verification"
        lifecycle_substage = lifecycle_substage or "repository-state-verification"
        service_class = "local-repository"
        endpoint_class = "local-process"
    elif command == "bicep":
        operation_class = "template-compilation"
        lifecycle_substage = lifecycle_substage or "template-compilation"
        service_class = "local-tooling"
        endpoint_class = "local-process"
    else:
        _fail("protected-operation-attribution-invalid")

    if lifecycle_substage is None:
        lifecycle_substage = operation_class
    if re.fullmatch(r"[a-z0-9-]{1,96}", lifecycle_substage) is None:
        _fail("protected-operation-attribution-invalid")
    identity_alias = (
        "ephemeral-acr-publisher"
        if environment_overrides is not None
        and "AZURE_CONFIG_DIR" in environment_overrides
        else "interactive-execution-identity"
    )
    return {
        "lifecycleSubstage": lifecycle_substage,
        "operationClass": operation_class,
        "serviceClass": service_class,
        "endpointClass": endpoint_class,
        "identityAlias": identity_alias,
        "expectedAuthorizationResult": expected_authorization
        or _expected_authorization_result(),
        "azureMutation": mutation,
        "cleanupOrRevocation": cleanup_or_revocation,
    }


def _registry_attribution_spec(method: str, path: str) -> dict[str, JsonValue]:
    mapped: dict[tuple[str, str], tuple[str, str, bool]] = {
        ("GET", "/v2/"): (
            "private-acr-bearer-challenge",
            "private-acr-bearer-challenge",
            False,
        ),
        ("POST", "/oauth2/exchange"): (
            "private-acr-oauth-exchange",
            "private-acr-oauth-exchange",
            False,
        ),
        ("POST", "/oauth2/token"): (
            "repository-scoped-acr-token-request",
            "repository-scoped-acr-token-request",
            False,
        ),
    }
    scoped_substage = _ATTRIBUTION_SUBSTAGE.get()
    if (method, path) in mapped:
        operation_class, substage, mutation = mapped[(method, path)]
        if (method, path) == ("POST", "/oauth2/exchange"):
            if scoped_substage == "initial-acr-denial":
                operation_class = "initial-acr-denial-exchange-proof"
            elif scoped_substage == "acrpush-propagation-verification":
                operation_class = "acrpush-propagation-exchange-verification"
            elif scoped_substage == "post-revocation-acr-denial":
                operation_class = "post-revocation-exchange-denial-proof"
        elif (method, path) == ("POST", "/oauth2/token"):
            if scoped_substage == "initial-acr-denial":
                operation_class = "initial-acr-denial-token-proof"
            elif scoped_substage == "acrpush-propagation-verification":
                operation_class = "acrpush-propagation-token-verification"
            elif scoped_substage == "post-revocation-acr-denial":
                operation_class = "post-revocation-token-denial-proof"
    elif method == "HEAD" and "/manifests/" in path:
        operation_class = "repository-specific-digest-verification"
        substage = "repository-specific-digest-verification"
        mutation = False
    elif method == "DELETE" and "/_tags/" in path:
        operation_class = "mutable-tag-removal"
        substage = "mutable-tag-removal"
        mutation = True
    else:
        _fail("protected-operation-attribution-invalid")
    return {
        "lifecycleSubstage": scoped_substage or substage,
        "operationClass": operation_class,
        "serviceClass": "azure-container-registry-data-plane",
        "endpointClass": "private-acr-registry-data-plane",
        "identityAlias": "ephemeral-acr-publisher",
        "expectedAuthorizationResult": _expected_authorization_result(),
        "azureMutation": mutation,
        "cleanupOrRevocation": False,
    }


class _OperationAttribution:
    def __init__(
        self,
        *,
        receipt_directory: Path,
        lifecycle_stage: str,
        ledger_integrity: str,
        repository_head: str,
    ) -> None:
        self.path = _operation_attribution_path(receipt_directory)
        self.lifecycle_stage = lifecycle_stage
        self.ledger_integrity = ledger_integrity
        self.repository_head = repository_head
        self.lifecycle_process_id = _lifecycle_process_id(
            ledger_integrity=ledger_integrity, repository_head=repository_head
        )
        self._mutex = threading.RLock()
        if self.path.exists():
            self.document = self._load_existing()
        else:
            self.document = {
                "activeOperation": None,
                "integritySha256": None,
                "ledgerIntegritySha256": ledger_integrity,
                "lifecycleProcessId": self.lifecycle_process_id,
                "records": [],
                "repositoryHead": repository_head,
                "schemaVersion": "mobius.milestone-7.7.operation-attribution.v2",
            }
            self._persist(initial=True)

    def _load_existing(self) -> dict[str, JsonValue]:
        document = _read_state(self.path)
        if set(document) != {
            "activeOperation",
            "integritySha256",
            "ledgerIntegritySha256",
            "lifecycleProcessId",
            "records",
            "repositoryHead",
            "schemaVersion",
        }:
            _fail("protected-operation-attribution-malformed")
        unsigned = {
            key: value for key, value in document.items() if key != "integritySha256"
        }
        if (
            document.get("schemaVersion")
            != "mobius.milestone-7.7.operation-attribution.v2"
            or document.get("ledgerIntegritySha256") != self.ledger_integrity
            or document.get("repositoryHead") != self.repository_head
            or document.get("lifecycleProcessId") != self.lifecycle_process_id
            or document.get("integritySha256")
            != hashlib.sha256(
                OPERATION_ATTRIBUTION_DOMAIN + canonical_bytes(unsigned)
            ).hexdigest()
            or not isinstance(document.get("records"), list)
        ):
            _fail("protected-operation-attribution-binding-invalid")
        if document.get("activeOperation") is not None:
            _fail("protected-operation-attribution-interrupted-operation")
        return document

    def _persist(self, *, initial: bool = False) -> None:
        unsigned = {
            key: value
            for key, value in self.document.items()
            if key != "integritySha256"
        }
        self.document["integritySha256"] = hashlib.sha256(
            OPERATION_ATTRIBUTION_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest()
        if initial:
            _write_state(self.path, self.document)
        else:
            _replace_state(self.path, self.document)

    def _record_for(self, operation_id: str) -> dict[str, JsonValue] | None:
        records = self.document.get("records")
        if not isinstance(records, list):
            _fail("protected-operation-attribution-malformed")
        for value in reversed(records):
            if isinstance(value, dict) and value.get("operationId") == operation_id:
                return value
        return None

    def start(
        self,
        spec: Mapping[str, JsonValue],
        *,
        retry_of_operation_id: str | None = None,
        retry_count: int = 0,
    ) -> str:
        with self._mutex:
            if self.document["activeOperation"] is not None:
                _fail("protected-operation-attribution-active-operation-present")
            records = self.document["records"]
            if not isinstance(records, list):
                _fail("protected-operation-attribution-malformed")
            ordinal = (
                sum(
                    1
                    for value in records
                    if isinstance(value, dict) and value.get("event") == "pre-operation"
                )
                + 1
            )
            binding: dict[str, JsonValue] = {
                "ledgerIntegritySha256": self.ledger_integrity,
                "lifecycleProcessId": self.lifecycle_process_id,
                "lifecycleStage": self.lifecycle_stage,
                "lifecycleSubstage": spec["lifecycleSubstage"],
                "operationClass": spec["operationClass"],
                "ordinal": ordinal,
                "repositoryHead": self.repository_head,
                "retryCount": retry_count,
                "retryOfOperationId": retry_of_operation_id,
            }
            record_id = hashlib.sha256(
                OPERATION_ID_DOMAIN + canonical_bytes(binding)
            ).hexdigest()
            record: dict[str, JsonValue] = {
                "azureMutationBegan": False,
                "azureMutationCompleted": False,
                "azureMutationExpected": spec["azureMutation"],
                "azureRequestIssued": False,
                "cleanupOrRevocationRan": False,
                "endpointClass": spec["endpointClass"],
                "event": "pre-operation",
                "expectedAuthorizationResult": spec["expectedAuthorizationResult"],
                "finishedAtUtc": None,
                "identityAlias": spec["identityAlias"],
                "ledgerIntegritySha256": self.ledger_integrity,
                "lifecycleProcessId": self.lifecycle_process_id,
                "lifecycleStage": self.lifecycle_stage,
                "lifecycleSubstage": spec["lifecycleSubstage"],
                "operationClass": spec["operationClass"],
                "operationId": record_id,
                "repositoryHead": self.repository_head,
                "requestAttemptBegan": False,
                "requestOrCorrelationHash": None,
                "retryCount": retry_count,
                "retryOfOperationId": retry_of_operation_id,
                "sanitizedAzureErrorCode": None,
                "sanitizedStatusCode": "not-observed",
                "serviceClass": spec["serviceClass"],
                "startedAtUtc": _format_utc(_utc_now()),
                "terminalDisposition": "STARTED",
            }
            self.document["activeOperation"] = dict(record)
            records.append(record)
            self._persist()
            return record_id

    def mark_request_attempt_began(
        self, operation_id: str, *, cleanup_or_revocation: bool
    ) -> None:
        with self._mutex:
            active = self.document["activeOperation"]
            if (
                not isinstance(active, dict)
                or active.get("operationId") != operation_id
            ):
                _fail("protected-operation-attribution-active-operation-mismatch")
            active["requestAttemptBegan"] = True
            active["azureMutationBegan"] = active["azureMutationExpected"] is True
            active["cleanupOrRevocationRan"] = cleanup_or_revocation
            records = self.document["records"]
            if not isinstance(records, list):
                _fail("protected-operation-attribution-malformed")
            records.append({**active, "event": "request-attempt-began"})
            self._persist()

    def mark_azure_request_issued(self, operation_id: str) -> None:
        with self._mutex:
            active = self.document["activeOperation"]
            if (
                not isinstance(active, dict)
                or active.get("operationId") != operation_id
            ):
                _fail("protected-operation-attribution-active-operation-mismatch")
            active["azureRequestIssued"] = True
            self._persist()

    def mark_local_effect_began(
        self, operation_id: str, *, cleanup_or_revocation: bool
    ) -> None:
        with self._mutex:
            active = self.document["activeOperation"]
            if (
                not isinstance(active, dict)
                or active.get("operationId") != operation_id
            ):
                _fail("protected-operation-attribution-active-operation-mismatch")
            active["cleanupOrRevocationRan"] = cleanup_or_revocation
            records = self.document["records"]
            if not isinstance(records, list):
                _fail("protected-operation-attribution-malformed")
            records.append({**active, "event": "local-effect-began"})
            self._persist()

    def finish(
        self,
        operation_id: str,
        *,
        status_code: str,
        azure_error_code: str | None,
        correlation_hash: str | None,
        terminal_disposition: str,
    ) -> None:
        if (
            status_code not in {"not-reported", "2xx-not-reported"}
            and re.fullmatch(r"[1-5][0-9]{2}", status_code) is None
        ):
            _fail("protected-operation-attribution-status-invalid")
        if terminal_disposition not in {
            "SUCCEEDED",
            "FAILED",
            "TIMED_OUT",
            "CANCELLED",
            "UNCERTAIN",
            "SKIPPED_ALREADY_SATISFIED",
        }:
            _fail("protected-operation-attribution-disposition-invalid")
        if (
            azure_error_code is not None
            and re.fullmatch(r"[a-z0-9-]{1,64}", azure_error_code) is None
        ):
            _fail("protected-operation-attribution-error-invalid")
        if (
            correlation_hash is not None
            and HEX_SHA256.fullmatch(correlation_hash) is None
        ):
            _fail("protected-operation-attribution-correlation-invalid")
        with self._mutex:
            active = self.document["activeOperation"]
            if (
                not isinstance(active, dict)
                or active.get("operationId") != operation_id
            ):
                _fail("protected-operation-attribution-active-operation-mismatch")
            complete = {
                **active,
                "azureMutationCompleted": terminal_disposition
                in {"SUCCEEDED", "SKIPPED_ALREADY_SATISFIED"}
                and active.get("azureMutationBegan") is True,
                "event": "post-operation",
                "finishedAtUtc": _format_utc(_utc_now()),
                "requestOrCorrelationHash": correlation_hash,
                "sanitizedAzureErrorCode": azure_error_code,
                "sanitizedStatusCode": status_code,
                "terminalDisposition": terminal_disposition,
            }
            records = self.document["records"]
            if not isinstance(records, list):
                _fail("protected-operation-attribution-malformed")
            records.append(complete)
            self.document["activeOperation"] = None
            self._persist()

    def close_active(self, *, error: BaseException, disposition: str) -> None:
        active = self.document.get("activeOperation")
        if not isinstance(active, dict):
            return
        operation_id = active.get("operationId")
        if not isinstance(operation_id, str):
            _fail("protected-operation-attribution-malformed")
        self.finish(
            operation_id,
            status_code="not-reported",
            azure_error_code=_safe_attribution_error(error),
            correlation_hash=None,
            terminal_disposition=disposition,
        )

    def retry_local_pre_request(
        self, failed_operation_id: str, spec: Mapping[str, JsonValue]
    ) -> str:
        with self._mutex:
            prior = self._record_for(failed_operation_id)
            if (
                prior is None
                or prior.get("event") != "post-operation"
                or prior.get("terminalDisposition") != "FAILED"
                or prior.get("requestAttemptBegan") is not False
                or prior.get("azureRequestIssued") is not False
                or prior.get("azureMutationBegan") is not False
                or prior.get("azureMutationCompleted") is not False
                or prior.get("sanitizedAzureErrorCode")
                not in LOCAL_PRE_REQUEST_ERROR_CODES
                or prior.get("lifecycleProcessId") != self.lifecycle_process_id
                or prior.get("ledgerIntegritySha256") != self.ledger_integrity
                or prior.get("repositoryHead") != self.repository_head
                or prior.get("lifecycleStage") != self.lifecycle_stage
                or prior.get("lifecycleSubstage") != spec.get("lifecycleSubstage")
                or prior.get("operationClass") != spec.get("operationClass")
                or prior.get("retryCount") != 0
            ):
                _fail("local-pre-request-retry-not-authorized")
            return self.start(
                spec, retry_of_operation_id=failed_operation_id, retry_count=1
            )


@contextmanager
def _operation_attribution_session(
    *,
    receipt_directory: Path,
    lifecycle_stage: str,
    ledger_integrity: str,
    repository_head: str,
) -> Iterator[None]:
    lifecycle_process_id = _lifecycle_process_id(
        ledger_integrity=ledger_integrity, repository_head=repository_head
    )
    lock_path = _acquire_operation_attribution_lock(
        receipt_directory=receipt_directory,
        lifecycle_process_id=lifecycle_process_id,
    )
    try:
        attribution = _OperationAttribution(
            receipt_directory=receipt_directory,
            lifecycle_stage=lifecycle_stage,
            ledger_integrity=ledger_integrity,
            repository_head=repository_head,
        )
    except BaseException:
        _release_operation_attribution_lock(
            lock_path, lifecycle_process_id=lifecycle_process_id
        )
        raise
    token = _ACTIVE_ATTRIBUTION.set(attribution)
    try:
        yield
    except KeyboardInterrupt as exc:
        attribution.close_active(error=exc, disposition="CANCELLED")
        raise
    except BaseException as exc:
        attribution.close_active(error=exc, disposition="FAILED")
        raise
    finally:
        _ACTIVE_ATTRIBUTION.reset(token)
        _release_operation_attribution_lock(
            lock_path, lifecycle_process_id=lifecycle_process_id
        )


@contextmanager
def _attribution_scope(
    *, lifecycle_substage: str, expected_authorization: str
) -> Iterator[None]:
    if re.fullmatch(
        r"[a-z0-9-]{1,96}", lifecycle_substage
    ) is None or expected_authorization not in {"allow", "deny"}:
        _fail("protected-operation-attribution-invalid")
    substage_token = _ATTRIBUTION_SUBSTAGE.set(lifecycle_substage)
    authorization_token = _ATTRIBUTION_EXPECTED_AUTHORIZATION.set(
        expected_authorization
    )
    try:
        yield
    finally:
        _ATTRIBUTION_EXPECTED_AUTHORIZATION.reset(authorization_token)
        _ATTRIBUTION_SUBSTAGE.reset(substage_token)


def _begin_process_attribution(
    argv: tuple[str, ...],
    *,
    environment_overrides: Mapping[str, str] | None,
    expected_authorization: str | None = None,
) -> tuple[_OperationAttribution | None, str | None, dict[str, JsonValue] | None]:
    attribution = _ACTIVE_ATTRIBUTION.get()
    if attribution is None:
        return None, None, None
    spec = _process_attribution_spec(
        argv,
        environment_overrides=environment_overrides,
        expected_authorization=expected_authorization,
    )
    return attribution, attribution.start(spec), spec


def _finish_process_attribution(
    attribution: _OperationAttribution | None,
    operation_id: str | None,
    *,
    status_code: str,
    azure_error_code: str | None,
    correlation_hash: str | None,
    terminal_disposition: str,
) -> None:
    if attribution is not None and operation_id is not None:
        attribution.finish(
            operation_id,
            status_code=status_code,
            azure_error_code=azure_error_code,
            correlation_hash=correlation_hash,
            terminal_disposition=terminal_disposition,
        )


def _remove_ephemeral_publisher_directory(path: Path) -> None:
    attribution = _ACTIVE_ATTRIBUTION.get()
    operation_id: str | None = None
    if attribution is not None:
        operation_id = attribution.start(
            {
                "lifecycleSubstage": "publisher-identity-and-credential-deletion",
                "operationClass": "publisher-credential-and-cache-deletion",
                "serviceClass": "local-ephemeral-storage",
                "endpointClass": "local-process",
                "identityAlias": "ephemeral-acr-publisher",
                "expectedAuthorizationResult": "not-applicable",
                "azureMutation": False,
                "cleanupOrRevocation": True,
            }
        )
        attribution.mark_local_effect_began(operation_id, cleanup_or_revocation=True)
    try:
        shutil.rmtree(path)
    except KeyboardInterrupt as exc:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code=_safe_attribution_error(exc),
            correlation_hash=None,
            terminal_disposition="CANCELLED",
        )
        raise
    except BaseException as exc:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code=_safe_attribution_error(exc),
            correlation_hash=None,
            terminal_disposition="FAILED",
        )
        raise
    _finish_process_attribution(
        attribution,
        operation_id,
        status_code="2xx-not-reported",
        azure_error_code=None,
        correlation_hash=None,
        terminal_disposition="SUCCEEDED",
    )


def _attributed_failed_stage(receipt_directory: Path) -> str | None:
    path = _operation_attribution_path(receipt_directory)
    if not path.is_file():
        return None
    try:
        document = load_json(path)
    except (ContractError, OSError, ValueError):
        return "protected-attribution-invalid"
    if not isinstance(document, dict) or set(document) != {
        "activeOperation",
        "integritySha256",
        "ledgerIntegritySha256",
        "lifecycleProcessId",
        "records",
        "repositoryHead",
        "schemaVersion",
    }:
        return "protected-attribution-invalid"
    integrity = document.get("integritySha256")
    unsigned = {
        key: value for key, value in document.items() if key != "integritySha256"
    }
    if (
        not isinstance(integrity, str)
        or HEX_SHA256.fullmatch(integrity) is None
        or integrity
        != hashlib.sha256(
            OPERATION_ATTRIBUTION_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest()
        or document.get("schemaVersion")
        != "mobius.milestone-7.7.operation-attribution.v2"
        or not isinstance(document.get("ledgerIntegritySha256"), str)
        or HEX_SHA256.fullmatch(str(document.get("ledgerIntegritySha256"))) is None
        or not isinstance(document.get("lifecycleProcessId"), str)
        or HEX_SHA256.fullmatch(str(document.get("lifecycleProcessId"))) is None
        or not isinstance(document.get("repositoryHead"), str)
        or HEX_SHA40.fullmatch(str(document.get("repositoryHead"))) is None
    ):
        return "protected-attribution-invalid"
    expected_record_fields = {
        "azureMutationBegan",
        "azureMutationCompleted",
        "azureMutationExpected",
        "azureRequestIssued",
        "cleanupOrRevocationRan",
        "endpointClass",
        "event",
        "expectedAuthorizationResult",
        "finishedAtUtc",
        "identityAlias",
        "ledgerIntegritySha256",
        "lifecycleProcessId",
        "lifecycleStage",
        "lifecycleSubstage",
        "operationClass",
        "operationId",
        "repositoryHead",
        "requestAttemptBegan",
        "requestOrCorrelationHash",
        "retryCount",
        "retryOfOperationId",
        "sanitizedAzureErrorCode",
        "sanitizedStatusCode",
        "serviceClass",
        "startedAtUtc",
        "terminalDisposition",
    }

    def stage_from(value: JsonValue) -> str | None:
        if not isinstance(value, dict) or set(value) != expected_record_fields:
            return "protected-attribution-invalid"
        stage = value.get("lifecycleSubstage")
        if (
            not isinstance(stage, str)
            or re.fullmatch(r"[a-z0-9-]{1,96}", stage) is None
            or value.get("ledgerIntegritySha256")
            != document.get("ledgerIntegritySha256")
            or value.get("lifecycleProcessId") != document.get("lifecycleProcessId")
            or value.get("repositoryHead") != document.get("repositoryHead")
        ):
            return "protected-attribution-invalid"
        return stage

    active = document.get("activeOperation")
    if active is not None:
        return stage_from(active)
    records = document.get("records")
    if not isinstance(records, list):
        return "protected-attribution-invalid"
    resolved: set[tuple[str, str, str]] = set()
    for record in reversed(records):
        if not isinstance(record, dict) or record.get("event") != "post-operation":
            continue
        stage = stage_from(record)
        if stage is None or stage == "protected-attribution-invalid":
            return stage
        operation_class = record.get("operationClass")
        lifecycle_stage = record.get("lifecycleStage")
        if not isinstance(operation_class, str) or not isinstance(lifecycle_stage, str):
            return "protected-attribution-invalid"
        key = (lifecycle_stage, stage, operation_class)
        terminal = record.get("terminalDisposition")
        unexpected_denial = (
            record.get("sanitizedStatusCode") in {"401", "403"}
            and record.get("expectedAuthorizationResult") == "allow"
        )
        if terminal in {"FAILED", "TIMED_OUT", "CANCELLED", "UNCERTAIN"} or (
            terminal == "SUCCEEDED" and unexpected_denial
        ):
            if key not in resolved:
                return stage
        elif terminal in {"SUCCEEDED", "SKIPPED_ALREADY_SATISFIED"}:
            resolved.add(key)
    return None


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
    path = _disposition_path(receipt_directory)
    if path.is_file():
        prior = _read_state(path)
        prior_integrity = prior.get("dispositionIntegritySha256")
        prior_unsigned = {
            key: value
            for key, value in prior.items()
            if key != "dispositionIntegritySha256"
        }
        if (
            not isinstance(prior_integrity, str)
            or HEX_SHA256.fullmatch(prior_integrity) is None
            or prior_integrity
            != hashlib.sha256(
                DISPOSITION_DOMAIN + canonical_bytes(prior_unsigned)
            ).hexdigest()
        ):
            _fail("prior-disposition-integrity-invalid")
        archive = receipt_directory / (
            f"managed-binding-lifecycle-disposition-{prior_integrity}.json"
        )
        if not archive.exists():
            _write_state(archive, prior)
        _replace_state(path, complete)
    else:
        _write_state(path, complete)
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
        or expected > PROVISIONING_COST_BLOCK_USD_CENTS
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
        "mobius-cost-ceiling-usd-cents",
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
    cost_key = "mobius-cost-ceiling-usd-cents"
    observed_cost = observed.get(cost_key)
    expected_cost = expected.get(cost_key)
    if (
        not isinstance(observed_cost, str)
        or not observed_cost.isascii()
        or not observed_cost.isdecimal()
        or not isinstance(expected_cost, str)
        or not expected_cost.isascii()
        or not expected_cost.isdecimal()
        or int(observed_cost) > int(expected_cost)
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
        f"redisLocation={REDIS_LOCATION}",
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
    runbook_id = _scope(
        subscription_id,
        f"/resourceGroups/{CLEANUP_GROUP}/providers/Microsoft.Automation/"
        f"automationAccounts/{AUTOMATION_ACCOUNT}/runbooks/{RUNBOOK}",
    )
    _run(
        (
            "az",
            "rest",
            "--method",
            "put",
            "--url",
            f"https://management.azure.com{runbook_id}/draft/content"
            f"?api-version={AUTOMATION_API_VERSION}",
            "--headers",
            "Content-Type=text/plain",
            "--body",
            f"@{CLEANUP_RUNBOOK}",
            "--only-show-errors",
            "--output",
            "none",
        )
    )
    _run(
        (
            "az",
            "rest",
            "--method",
            "post",
            "--url",
            f"https://management.azure.com{runbook_id}/publish"
            f"?api-version={AUTOMATION_API_VERSION}",
            "--only-show-errors",
            "--output",
            "none",
        )
    )


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
        if not isinstance(parameters, dict) or len(parameters) != 2:
            _fail("cleanup-job-schedule-not-ready")
        normalized_parameters = {
            str(name).casefold(): value for name, value in parameters.items()
        }
        if (
            exact_job_schedule["id"] != resource_id
            or exact_job_schedule["jobScheduleId"] != job_schedule_id
            or exact_job_schedule["runbook"] != RUNBOOK
            or exact_job_schedule["schedule"] != SCHEDULE
            or not isinstance(exact_job_schedule["type"], str)
            or exact_job_schedule["type"].casefold()
            != "microsoft.automation/automationaccounts/jobschedules"
            or normalized_parameters
            != {
                "cleanupauthorized": "true",
                "targetresourcegroupname": TARGET_GROUP,
            }
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
    published_content = _run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (
                "https://management.azure.com"
                f"{_scope(subscription_id, f'/resourceGroups/{CLEANUP_GROUP}/providers/Microsoft.Automation/automationAccounts/{AUTOMATION_ACCOUNT}/runbooks/{RUNBOOK}')}/content"
                f"?api-version={AUTOMATION_API_VERSION}"
            ),
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        require_text=True,
    )
    contract = load_managed_binding_contract()
    cleanup_execution = cast(dict[str, JsonValue], contract["cleanupExecution"])
    if (
        not isinstance(published_content, str)
        or cleanup_runbook_sha256(published_content)
        != cleanup_execution["publishedContentSha256"]
    ):
        _fail("cleanup-runbook-content-drift")

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


MANAGED_BINDING_IDENTITY_NAMES: Final = frozenset(
    {
        "id-mobius77-api",
        "id-mobius77-worker",
        "id-mobius77-telemetry",
        "id-mobius77-db-admin",
    }
)


def _managed_identity_principal(subscription_id: str, identity_name: str) -> str:
    if identity_name not in MANAGED_BINDING_IDENTITY_NAMES:
        _fail("pre-secret-workload-identity-malformed")
    value = _run(
        (
            "az",
            "identity",
            "show",
            "--resource-group",
            TARGET_GROUP,
            "--name",
            identity_name,
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

    protected_resources = {
        "microsoft.keyvault/vaults/kv-mobius77-11564669": (
            f"{target_scope}/providers/Microsoft.KeyVault/vaults/{KEY_VAULT}",
            str(rbac["keyVaultSecretsUserRoleDefinitionId"]),
            (
                "id-mobius77-api",
                "id-mobius77-worker",
                "id-mobius77-telemetry",
            ),
        ),
        "microsoft.containerregistry/registries/acrmobius7711564669": (
            f"{target_scope}/providers/Microsoft.ContainerRegistry/registries/{REGISTRY}",
            str(rbac["acrPullRoleDefinitionId"]),
            (
                "id-mobius77-api",
                "id-mobius77-worker",
                "id-mobius77-telemetry",
                "id-mobius77-db-admin",
            ),
        ),
    }
    if any(relative in target_resources for relative in protected_resources):
        for relative, (scope, role_id, identity_names) in protected_resources.items():
            if relative not in target_resources:
                continue
            if any(
                (f"microsoft.managedidentity/userassignedidentities/{identity_name}")
                not in target_resources
                for identity_name in identity_names
            ):
                _fail("pre-secret-role-inventory-drift")
            expected = sorted(
                (
                    {
                        "principalId": _managed_identity_principal(
                            subscription_id, identity_name
                        ).casefold(),
                        "roleDefinitionId": (role_prefix + role_id).casefold(),
                        "scope": scope.casefold(),
                    }
                    for identity_name in identity_names
                ),
                key=lambda row: row["principalId"],
            )
            rows = _exact_scope_role_rows(subscription_id, scope)
            if rows and sorted(rows, key=lambda row: row["principalId"]) != expected:
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
    if not assignment_id.casefold().startswith(
        f"{scope}/providers/microsoft.authorization/roleassignments/".casefold()
    ):
        _fail("temporary-role-assignment-scope-not-exact")
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


def _ledger_integrity(ledger: Mapping[str, JsonValue]) -> str:
    value = ledger.get("ledgerIntegritySha256")
    if not isinstance(value, str) or HEX_SHA256.fullmatch(value) is None:
        _fail("temporary-authority-ledger-binding-invalid")
    return value


def _validate_transient_state(
    state: dict[str, JsonValue], *, ledger: Mapping[str, JsonValue]
) -> None:
    if set(state) != TRANSIENT_STATE_FIELDS:
        _fail("transient-state-malformed")
    if state.get("repositoryHead") != ledger.get("repositoryHead"):
        _fail("transient-state-repository-head-mismatch")
    if state.get("secretValueAccessed") is not False:
        _fail("transient-state-secret-access-invalid")
    if state.get("resumableCheckpoint") in {
        "post-secret-provisioning",
        "runtime-deployment-handoff",
    }:
        _fail("resumable-checkpoint-skips-key-vault-authority")
    assignment_id = state.get("temporaryKeyVaultAssignmentId")
    proved = state.get("temporaryKeyVaultAuthorityProved")
    assignment_ledger = state.get("temporaryKeyVaultAuthorityLedgerSha256")
    if assignment_id is None:
        if proved is not False or assignment_ledger is not None:
            _fail("temporary-key-vault-authority-state-invalid")
    elif (
        not isinstance(assignment_id, str)
        or not assignment_id.startswith("/subscriptions/")
        or not isinstance(proved, bool)
        or not isinstance(assignment_ledger, str)
        or HEX_SHA256.fullmatch(assignment_ledger) is None
    ):
        _fail("temporary-key-vault-authority-state-invalid")
    registry_assignment = state.get("temporaryRegistryAssignmentId")
    if registry_assignment is not None and (
        not isinstance(registry_assignment, str)
        or not registry_assignment.startswith("/subscriptions/")
    ):
        _fail("temporary-registry-authority-state-invalid")


def _read_current_transient_state(
    state_path: Path, *, ledger: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    state = _read_state(state_path)
    if set(state) == LEGACY_TRANSIENT_STATE_FIELDS:
        if state.get("temporaryKeyVaultAssignmentId") is not None:
            _fail("legacy-temporary-key-vault-authority-unreconciled")
        state["temporaryKeyVaultAuthorityLedgerSha256"] = None
        state["temporaryKeyVaultAuthorityProved"] = False
        _replace_state(state_path, state)
    _validate_transient_state(state, ledger=ledger)
    return state


def _last_durable_checkpoint(state: Mapping[str, JsonValue]) -> str | None:
    for key in ("resumableCheckpoint", "lastCompletedStage"):
        value = state.get(key)
        if isinstance(value, str) and re.fullmatch(r"[a-z0-9-]{1,96}", value):
            return value
    return None


def _key_vault_metadata_access_probe(subscription_id: str) -> None:
    value = _run(
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
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("key-vault-authority-propagation-output-malformed")


def _wait_for_key_vault_metadata_authority(subscription_id: str) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        _private_tls_endpoint(KEY_VAULT_HOST)
        try:
            with _attribution_scope(
                lifecycle_substage="key-vault-authority-propagation-proof",
                expected_authorization="allow",
            ):
                _key_vault_metadata_access_probe(subscription_id)
            return
        except AzureCommandError as error:
            if error.sanitized_azure_error_code != "forbidden":
                raise
        time.sleep(10.0)
    _fail("key-vault-authority-propagation-unproved")


def _revoke_temporary_key_vault_authority(
    *,
    subscription_id: str,
    state_path: Path,
    state: dict[str, JsonValue],
) -> bool:
    assignment_id = state.get("temporaryKeyVaultAssignmentId")
    if assignment_id is None:
        return False
    if not isinstance(assignment_id, str) or not assignment_id.startswith(
        "/subscriptions/"
    ):
        _fail("temporary-key-vault-authority-state-invalid")
    _mark_stage(state_path, state, "temporary-key-vault-authority-revocation")
    with _attribution_scope(
        lifecycle_substage="key-vault-temporary-authority-revocation",
        expected_authorization="allow",
    ):
        _delete_assignment(subscription_id, assignment_id)
    state["temporaryKeyVaultAssignmentId"] = None
    state["temporaryKeyVaultAuthorityProved"] = False
    state["temporaryKeyVaultAuthorityLedgerSha256"] = None
    _replace_state(state_path, state)
    with _attribution_scope(
        lifecycle_substage="key-vault-post-revocation-denial-proof",
        expected_authorization="deny",
    ):
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
    state["activeStage"] = None
    state["lastCompletedStage"] = KEY_VAULT_AUTHORITY_REVOKED_STAGE
    state["resumableCheckpoint"] = KEY_VAULT_AUTHORITY_REVOKED_STAGE
    _replace_state(state_path, state)
    return True


def _ensure_temporary_key_vault_authority(
    *,
    subscription_id: str,
    ledger: Mapping[str, JsonValue],
    state_path: Path,
    state: dict[str, JsonValue],
) -> None:
    _validate_transient_state(state, ledger=ledger)
    current_ledger = _ledger_integrity(ledger)
    assignment_id = state.get("temporaryKeyVaultAssignmentId")
    assignment_ledger = state.get("temporaryKeyVaultAuthorityLedgerSha256")
    if assignment_id is not None and assignment_ledger != current_ledger:
        _revoke_temporary_key_vault_authority(
            subscription_id=subscription_id, state_path=state_path, state=state
        )
        assignment_id = None
    if assignment_id is None:
        contract = load_managed_binding_contract()
        rbac = contract.get("rbac")
        scopes = contract.get("scopeBinding")
        if not isinstance(rbac, dict) or not isinstance(scopes, dict):
            _fail("managed-binding-contract-malformed")
        vault_scope = _scope(subscription_id, str(scopes["keyVault"]))
        _mark_stage(state_path, state, "temporary-key-vault-authority-creation")
        with _attribution_scope(
            lifecycle_substage="key-vault-temporary-authority-creation",
            expected_authorization="allow",
        ):
            assignment_id = _temporary_role_assignment(
                subscription_id=subscription_id,
                object_id=_signed_in_user_object_id(),
                role_id=str(rbac["keyVaultSecretsOfficerRoleDefinitionId"]),
                scope=vault_scope,
            )
        state["temporaryKeyVaultAssignmentId"] = assignment_id
        state["temporaryKeyVaultAuthorityLedgerSha256"] = current_ledger
        state["temporaryKeyVaultAuthorityProved"] = False
        _replace_state(state_path, state)
    _mark_stage(state_path, state, "key-vault-authority-propagation-proof")
    _wait_for_key_vault_metadata_authority(subscription_id)
    state["activeStage"] = None
    state["lastCompletedStage"] = KEY_VAULT_AUTHORITY_PROVED_STAGE
    state["resumableCheckpoint"] = KEY_VAULT_AUTHORITY_PROVED_STAGE
    state["temporaryKeyVaultAuthorityProved"] = True
    _replace_state(state_path, state)


def _publisher_role_rows(
    *, subscription_id: str, publisher_app_id: str
) -> list[dict[str, str]]:
    rows = _run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--assignee",
            publisher_app_id,
            "--all",
            "--include-groups",
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
        _fail("publisher-role-inventory-malformed")
    normalized: list[dict[str, str]] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"principalId", "roleDefinitionId", "scope"}
            or not all(isinstance(value, str) for value in row.values())
        ):
            _fail("publisher-role-inventory-malformed")
        normalized.append(
            {
                "principalId": str(row["principalId"]).casefold(),
                "roleDefinitionId": str(row["roleDefinitionId"]).casefold(),
                "scope": str(row["scope"]).casefold(),
            }
        )
    return normalized


def _validate_publisher_role_inventory(
    rows: list[dict[str, str]],
    *,
    publisher_object_id: str,
    registry_scope: str,
    acr_push_role_id: str,
    assignment_required: bool,
) -> None:
    expected = {
        "principalId": publisher_object_id.casefold(),
        "roleDefinitionId": (
            f"{registry_scope.rsplit('/resourceGroups/', 1)[0]}"
            f"/providers/Microsoft.Authorization/roleDefinitions/{acr_push_role_id}"
        ).casefold(),
        "scope": registry_scope.casefold(),
    }
    if assignment_required:
        if rows != [expected]:
            _fail("publisher-role-inventory-drift")
    elif rows:
        _fail("publisher-inherited-authority")


def _wait_for_publisher_role_inventory(
    *,
    subscription_id: str,
    publisher_app_id: str,
    publisher_object_id: str,
    registry_scope: str,
    acr_push_role_id: str,
    assignment_required: bool,
) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        try:
            _validate_publisher_role_inventory(
                _publisher_role_rows(
                    subscription_id=subscription_id,
                    publisher_app_id=publisher_app_id,
                ),
                publisher_object_id=publisher_object_id,
                registry_scope=registry_scope,
                acr_push_role_id=acr_push_role_id,
                assignment_required=assignment_required,
            )
            return
        except LifecycleError as exc:
            if str(exc) not in {
                "publisher-inherited-authority",
                "publisher-role-inventory-drift",
            }:
                raise
            time.sleep(10.0)
    _fail("publisher-role-propagation-unproved")


def _temporary_publisher_role_assignment(
    *,
    subscription_id: str,
    publisher_app_id: str,
    publisher_object_id: str,
    role_id: str,
    scope: str,
) -> str:
    _validate_publisher_role_inventory(
        _publisher_role_rows(
            subscription_id=subscription_id,
            publisher_app_id=publisher_app_id,
        ),
        publisher_object_id=publisher_object_id,
        registry_scope=scope,
        acr_push_role_id=role_id,
        assignment_required=False,
    )
    created = _run(
        (
            "az",
            "role",
            "assignment",
            "create",
            "--assignee-object-id",
            publisher_object_id,
            "--assignee-principal-type",
            "ServicePrincipal",
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
        _fail("publisher-role-assignment-output-malformed")
    assignment_id = created["id"]
    if not isinstance(assignment_id, str) or not assignment_id.startswith(
        "/subscriptions/"
    ):
        _fail("publisher-role-assignment-output-malformed")
    _wait_for_publisher_role_inventory(
        subscription_id=subscription_id,
        publisher_app_id=publisher_app_id,
        publisher_object_id=publisher_object_id,
        registry_scope=scope,
        acr_push_role_id=role_id,
        assignment_required=True,
    )
    return assignment_id


def _secure_ephemeral_directory(path: Path) -> Path:
    resolved = _outside_repository(path, "publisher-directory")
    try:
        resolved.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(resolved, 0o700)
    except OSError:
        _fail("publisher-directory-create-failed")
    return resolved


def _reset_ephemeral_directory(path: Path) -> None:
    resolved = _outside_repository(path, "publisher-directory")
    try:
        if resolved.exists():
            shutil.rmtree(resolved)
        resolved.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(resolved, 0o700)
    except OSError:
        _fail("publisher-auth-cache-reset-failed")


def _management_azure_config_directory() -> Path:
    configured = os.environ.get("AZURE_CONFIG_DIR")
    candidate = Path(configured) if configured else Path.home() / ".azure"
    resolved = _outside_repository(candidate, "management-azure-config-directory")
    if not resolved.is_dir():
        _fail("management-azure-config-directory-invalid")
    return resolved


def _wait_for_ephemeral_publisher_principal(app_id: str) -> str:
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        try:
            principal = _run(
                (
                    "az",
                    "ad",
                    "sp",
                    "show",
                    "--id",
                    app_id,
                    "--query",
                    "{objectId:id,servicePrincipalType:servicePrincipalType}",
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                require_json=True,
            )
        except AzureCommandError:
            time.sleep(5.0)
            continue
        if (
            not isinstance(principal, dict)
            or set(principal) != {"objectId", "servicePrincipalType"}
            or principal.get("servicePrincipalType") != "Application"
            or not isinstance(principal.get("objectId"), str)
            or re.fullmatch(r"[0-9a-fA-F-]{36}", str(principal["objectId"])) is None
        ):
            _fail("publisher-service-principal-output-malformed")
        return str(principal["objectId"])
    _fail("publisher-service-principal-propagation-unproved")


def _create_ephemeral_publisher(
    *, ledger: dict[str, JsonValue], publisher_directory: Path
) -> tuple[str, str, str, Path]:
    ledger_integrity = ledger.get("ledgerIntegritySha256")
    if (
        not isinstance(ledger_integrity, str)
        or HEX_SHA256.fullmatch(ledger_integrity) is None
    ):
        _fail("publisher-ledger-binding-invalid")
    display_name = f"mobius77-acr-publisher-{ledger_integrity[:12]}"
    management_azure_config = _management_azure_config_directory()
    created = _run(
        (
            "az",
            "ad",
            "sp",
            "create-for-rbac",
            "--name",
            display_name,
            "--create-cert",
            "--years",
            "1",
            "--skip-assignment",
            "--query",
            "{appId:appId,certificatePath:fileWithCertAndPrivateKey,tenant:tenant}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
        environment_overrides={
            "AZURE_CONFIG_DIR": str(management_azure_config),
            "USERPROFILE": str(publisher_directory),
        },
        working_directory=publisher_directory,
    )
    if not isinstance(created, dict) or set(created) != {
        "appId",
        "certificatePath",
        "tenant",
    }:
        _fail("publisher-identity-output-malformed")
    app_id = created["appId"]
    raw_certificate_path = created["certificatePath"]
    tenant_id = created["tenant"]
    if not all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F-]{36}", value)
        for value in (app_id, tenant_id)
    ):
        _fail("publisher-identity-output-malformed")
    if not isinstance(raw_certificate_path, str) or not raw_certificate_path:
        _fail("publisher-certificate-path-malformed")
    certificate_path = Path(raw_certificate_path).resolve()
    if certificate_path.parent != publisher_directory.resolve():
        _fail("publisher-certificate-path-outside-directory")
    if not certificate_path.is_file() or certificate_path.stat().st_size <= 0:
        _fail("publisher-certificate-missing")
    try:
        os.chmod(certificate_path, 0o600)
    except OSError:
        _fail("publisher-certificate-permissions-failed")
    try:
        object_id = _wait_for_ephemeral_publisher_principal(str(app_id))
    except LifecycleError:
        _delete_ephemeral_publisher_by_app_id(str(app_id))
        raise
    return str(app_id), object_id, str(tenant_id), certificate_path


def _publisher_login(
    *,
    publisher_app_id: str,
    tenant_id: str,
    certificate_path: Path,
    environment: Mapping[str, str],
) -> None:
    _run(
        (
            "az",
            "login",
            "--service-principal",
            "--username",
            publisher_app_id,
            "--tenant",
            tenant_id,
            "--certificate",
            str(certificate_path),
            "--allow-no-subscriptions",
            "--output",
            "none",
            "--only-show-errors",
        ),
        environment_overrides=environment,
    )


def _publisher_environment(
    environment_overrides: Mapping[str, str],
) -> dict[str, str]:
    if set(environment_overrides) != {"AZURE_CONFIG_DIR", "DOCKER_CONFIG"}:
        _fail("publisher-environment-invalid")
    environment = _environment()
    for key, value in environment_overrides.items():
        resolved = _outside_repository(Path(value), key.casefold())
        if not resolved.is_dir():
            _fail("publisher-environment-invalid")
        environment[key] = value
    return environment


def _jwt_claims(token: bytearray) -> dict[str, JsonValue]:
    if len(token) > MAXIMUM_TOKEN_BYTES or TOKEN_BYTES.fullmatch(token) is None:
        _fail("publisher-token-malformed")
    parts = bytes(token).split(b".")
    if len(parts) != 3 or any(not part for part in parts):
        _fail("publisher-token-malformed")
    padding = b"=" * (-len(parts[1]) % 4)
    try:
        payload = bytearray(base64.urlsafe_b64decode(parts[1] + padding))
    except (ValueError, binascii.Error):
        _fail("publisher-token-malformed")
    try:
        if len(payload) > MAXIMUM_TOKEN_BYTES:
            _fail("publisher-token-malformed")
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        _fail("publisher-token-malformed")
    finally:
        payload.clear()
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail("publisher-token-malformed")
    return cast(dict[str, JsonValue], value)


def _validate_token_time(claims: Mapping[str, JsonValue]) -> None:
    now = int(_utc_now().timestamp())
    expires = claims.get("exp")
    not_before = claims.get("nbf")
    if (
        not isinstance(expires, int)
        or isinstance(expires, bool)
        or not isinstance(not_before, int)
        or isinstance(not_before, bool)
    ):
        _fail("publisher-token-time-invalid")
    if expires <= now:
        raise PublisherOAuthTransient("publisher-token-expired")
    if expires <= now + 60:
        _fail("publisher-token-lifetime-insufficient")
    if not_before > now + 60:
        _fail("publisher-token-time-invalid")
    if not_before > now:
        raise PublisherOAuthTransient("publisher-token-not-yet-valid")


def _validate_entra_token(
    token: bytearray, *, publisher_app_id: str, tenant_id: str
) -> None:
    claims = _jwt_claims(token)
    try:
        _validate_token_time(claims)
        client_id = claims.get("appid", claims.get("azp"))
        if (
            claims.get("aud") != ACR_TOKEN_RESOURCE
            or claims.get("tid") != tenant_id
            or client_id != publisher_app_id
        ):
            _fail("publisher-entra-token-binding-invalid")
    finally:
        claims.clear()


def _publisher_entra_token(
    *,
    publisher_app_id: str,
    tenant_id: str,
    environment_overrides: Mapping[str, str],
) -> bytearray:
    argv = (
        "az",
        "account",
        "get-access-token",
        "--resource",
        ACR_TOKEN_RESOURCE,
        "--query",
        "accessToken",
        "--output",
        "tsv",
        "--only-show-errors",
    )
    attribution, operation_id, _attribution_spec = _begin_process_attribution(
        argv,
        environment_overrides=environment_overrides,
        expected_authorization="allow",
    )
    try:
        actual = _resolve_authorized_process_launch(argv).argv
        publisher_environment = _publisher_environment(environment_overrides)
        if attribution is not None and operation_id is not None:
            attribution.mark_request_attempt_began(
                operation_id, cleanup_or_revocation=False
            )
        completed = subprocess.run(
            actual,
            cwd=REPOSITORY_ROOT,
            env=publisher_environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-entra-token-process-timed-out",
            correlation_hash=None,
            terminal_disposition="TIMED_OUT",
        )
        _fail("publisher-entra-token-process-timed-out")
    except KeyboardInterrupt:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-entra-token-process-cancelled",
            correlation_hash=None,
            terminal_disposition="CANCELLED",
        )
        raise
    except OSError:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-entra-token-process-launch-failed",
            correlation_hash=None,
            terminal_disposition="UNCERTAIN",
        )
        _fail("publisher-entra-token-process-launch-failed")
    if attribution is not None and operation_id is not None:
        attribution.mark_azure_request_issued(operation_id)
    stdout = bytearray(completed.stdout)
    stderr = bytearray(completed.stderr)
    token = bytearray()
    attribution_finished = False
    try:
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("publisher-entra-token-output-oversized")
        if completed.returncode != 0:
            azure_error_code = _sanitized_azure_error_code(stdout, stderr)
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=_sanitized_status_code(
                    stdout,
                    stderr,
                    default="403"
                    if azure_error_code == "forbidden"
                    else "not-reported",
                ),
                azure_error_code=azure_error_code,
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
            attribution_finished = True
            raise AzureCommandError(azure_error_code)
        while stdout and stdout[-1] in b"\r\n\t ":
            stdout.pop()
        token.extend(stdout)
        if TOKEN_BYTES.fullmatch(token) is None or bytes(token) in stderr:
            _fail("publisher-entra-token-output-malformed")
        _validate_entra_token(
            token, publisher_app_id=publisher_app_id, tenant_id=tenant_id
        )
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="2xx-not-reported",
            azure_error_code=None,
            correlation_hash=_sanitized_correlation_hash(stdout, stderr),
            terminal_disposition="SUCCEEDED",
        )
        attribution_finished = True
        return token
    except BaseException as exc:
        token.clear()
        if not attribution_finished:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=_sanitized_status_code(
                    stdout, stderr, default="not-reported"
                ),
                azure_error_code=_safe_attribution_error(exc),
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
        raise
    finally:
        stdout.clear()
        stderr.clear()


def _form_body(fields: tuple[tuple[bytes, bytes | bytearray], ...]) -> bytearray:
    body = bytearray()
    unreserved = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    allowed = set(unreserved)
    for field_index, (name, value) in enumerate(fields):
        if not name or any(byte not in allowed for byte in name):
            _fail("publisher-oauth-form-invalid")
        if field_index:
            body.append(ord("&"))
        body.extend(name)
        body.append(ord("="))
        for byte in value:
            if byte in allowed:
                body.append(byte)
            else:
                body.extend(f"%{byte:02X}".encode("ascii"))
    if len(body) > MAXIMUM_OUTPUT_BYTES:
        body.clear()
        _fail("publisher-oauth-form-oversized")
    return body


def _validate_registry_request(method: str, path: str) -> None:
    exact = {
        ("GET", "/v2/"),
        ("POST", "/oauth2/exchange"),
        ("POST", "/oauth2/token"),
    }
    if (method, path) in exact:
        return
    manifest = re.fullmatch(
        r"/v2/opencanvas-api/manifests/"
        r"(?:source-[0-9a-f]{40}|sha256:[0-9a-f]{64})",
        path,
    )
    tag = re.fullmatch(
        r"/acr/v1/opencanvas-api/_tags/source-[0-9a-f]{40}"
        r"\?api-version=2021-07-01",
        path,
    )
    if (method == "HEAD" and manifest is not None) or (
        method == "DELETE" and tag is not None
    ):
        return
    _fail("publisher-registry-request-scope-invalid")


def _private_registry_request(
    method: str,
    path: str,
    *,
    headers: Mapping[str, str],
    body: bytearray | None = None,
) -> tuple[int, dict[str, str], bytearray]:
    _validate_registry_request(method, path)
    if path in {"/oauth2/exchange", "/oauth2/token"} and headers != {
        "Content-Type": "application/x-www-form-urlencoded"
    }:
        _fail("publisher-oauth-request-content-type-invalid")
    if (method, path) == ("GET", "/v2/") and (headers or body is not None):
        _fail("publisher-registry-challenge-request-invalid")
    attribution = _ACTIVE_ATTRIBUTION.get()
    operation_id: str | None = None
    attribution_spec: dict[str, JsonValue] | None = None
    if attribution is not None:
        attribution_spec = _registry_attribution_spec(method, path)
        operation_id = attribution.start(attribution_spec)
    try:
        _private_tls_endpoint(REGISTRY_HOST)
    except BaseException as exc:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code=_safe_attribution_error(exc),
            correlation_hash=None,
            terminal_disposition="FAILED",
        )
        raise
    connection = http.client.HTTPSConnection(
        REGISTRY_HOST,
        port=443,
        timeout=10.0,
        context=ssl.create_default_context(),
    )
    response_body = bytearray()
    attribution_finished = False
    correlation_hash: str | None = None
    observed_status = "not-reported"
    try:
        if (
            attribution is not None
            and operation_id is not None
            and attribution_spec is not None
        ):
            attribution.mark_request_attempt_began(
                operation_id,
                cleanup_or_revocation=attribution_spec["cleanupOrRevocation"] is True,
            )
        connection.request(method, path, body=body, headers=dict(headers))
        if attribution is not None and operation_id is not None:
            attribution.mark_azure_request_issued(operation_id)
        response = connection.getresponse()
        observed_status = str(response.status)
        response_body.extend(response.read(MAXIMUM_OUTPUT_BYTES + 1))
        if len(response_body) > MAXIMUM_OUTPUT_BYTES:
            _fail("publisher-registry-output-oversized")
        retained_headers: dict[str, str] = {}
        digest = response.getheader("Docker-Content-Digest")
        if digest is not None:
            retained_headers["docker-content-digest"] = digest
        content_type = response.getheader("Content-Type")
        if content_type is not None:
            retained_headers["content-type"] = content_type
        challenge = response.getheader("WWW-Authenticate")
        if challenge is not None and (method, path) == ("GET", "/v2/"):
            retained_headers["www-authenticate"] = challenge
        correlation = response.getheader("x-ms-correlation-request-id")
        correlation_hash = (
            hashlib.sha256(
                CORRELATION_HASH_DOMAIN + correlation.encode("ascii")
            ).hexdigest()
            if correlation is not None
            and re.fullmatch(r"[0-9a-fA-F-]{36}", correlation) is not None
            else None
        )
        expected_authorization = (
            attribution_spec["expectedAuthorizationResult"]
            if attribution_spec is not None
            else _expected_authorization_result()
        )
        oauth_request = path in {"/oauth2/exchange", "/oauth2/token"}
        expected_denial = expected_authorization == "deny" and response.status in {
            401,
            403,
        }
        response_succeeded = (
            expected_denial
            or (expected_authorization == "allow" and response.status == 200)
            or (not oauth_request and (method, path) != ("GET", "/v2/"))
        )
        if oauth_request and response.status == 200:
            media_type = retained_headers.get("content-type", "").split(";", 1)[0]
            if media_type.casefold() != "application/json":
                _fail("publisher-oauth-response-content-type-invalid")
            token_key = (
                "refresh_token" if path == "/oauth2/exchange" else "access_token"
            )
            allowed_keys = (
                frozenset({"refresh_token"})
                if path == "/oauth2/exchange"
                else frozenset({"access_token", "expires_in", "issued_at"})
            )
            probe = _oauth_secret(
                response_body, key=token_key, allowed_keys=allowed_keys
            )
            probe.clear()
        if (method, path) == ("GET", "/v2/"):
            response_succeeded = expected_denial
        azure_error_code = None
        if not response_succeeded:
            azure_error_code = (
                f"acr-oauth-http-{response.status}"
                if oauth_request or (method, path) == ("GET", "/v2/")
                else _sanitized_azure_error_code(response_body, bytearray())
            )
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code=observed_status,
            azure_error_code=azure_error_code,
            correlation_hash=correlation_hash,
            terminal_disposition="SUCCEEDED" if response_succeeded else "FAILED",
        )
        attribution_finished = True
        return response.status, retained_headers, response_body
    except TimeoutError as exc:
        response_body.clear()
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code=_safe_attribution_error(exc),
            correlation_hash=None,
            terminal_disposition="TIMED_OUT",
        )
        attribution_finished = True
        if path in {"/v2/", "/oauth2/exchange", "/oauth2/token"}:
            raise PublisherOAuthTransient(
                "publisher-private-registry-request-timed-out"
            )
        _fail("publisher-private-registry-request-timed-out")
    except KeyboardInterrupt as exc:
        response_body.clear()
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code=_safe_attribution_error(exc),
            correlation_hash=None,
            terminal_disposition="CANCELLED",
        )
        raise
    except BaseException as exc:
        response_body.clear()
        if not attribution_finished:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=observed_status,
                azure_error_code=_safe_attribution_error(exc),
                correlation_hash=correlation_hash,
                terminal_disposition="UNCERTAIN"
                if isinstance(exc, (OSError, ssl.SSLError, http.client.HTTPException))
                else "FAILED",
            )
        if isinstance(exc, (OSError, ssl.SSLError, http.client.HTTPException)):
            _fail("publisher-private-registry-request-failed")
        raise
    finally:
        connection.close()


def _oauth_secret(
    body: bytearray,
    *,
    key: str,
    allowed_keys: frozenset[str],
) -> bytearray:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        _fail("publisher-oauth-response-malformed")
    if (
        not isinstance(value, dict)
        or set(value) - allowed_keys
        or key not in value
        or not isinstance(value[key], str)
    ):
        _fail("publisher-oauth-response-malformed")
    raw_secret = cast(str, value[key])
    secret = bytearray(raw_secret.encode("ascii", errors="strict"))
    value[key] = None
    value.clear()
    if len(secret) > MAXIMUM_TOKEN_BYTES or TOKEN_BYTES.fullmatch(secret) is None:
        secret.clear()
        _fail("publisher-oauth-response-malformed")
    return secret


def _challenge_service(header: str) -> str:
    if "\r" in header or "\n" in header:
        _fail("publisher-registry-challenge-malformed")
    matched = re.fullmatch(r"(?i)Bearer\s+(.+)", header)
    if matched is None:
        _fail("publisher-registry-challenge-malformed")
    raw_parameters = matched.group(1)
    if (
        re.fullmatch(
            r'\s*[A-Za-z][A-Za-z0-9_-]*="[^"\r\n]+"'
            r'(?:\s*,\s*[A-Za-z][A-Za-z0-9_-]*="[^"\r\n]+")*\s*',
            raw_parameters,
        )
        is None
    ):
        _fail("publisher-registry-challenge-malformed")
    parameters: dict[str, str] = {}
    for parameter in re.finditer(
        r'([A-Za-z][A-Za-z0-9_-]*)="([^"\r\n]+)"', raw_parameters
    ):
        normalized = parameter.group(1).casefold()
        if normalized in parameters:
            _fail("publisher-registry-challenge-malformed")
        parameters[normalized] = parameter.group(2)
    if set(parameters) not in ({"realm", "service"}, {"realm", "service", "scope"}):
        _fail("publisher-registry-challenge-malformed")
    realm = urlsplit(parameters["realm"])
    if (
        realm.scheme != "https"
        or realm.hostname != REGISTRY_HOST
        or realm.port not in {None, 443}
        or realm.username is not None
        or realm.password is not None
        or realm.path != "/oauth2/token"
        or realm.query
        or realm.fragment
        or parameters["service"] != REGISTRY_HOST
    ):
        _fail("publisher-registry-challenge-binding-invalid")
    scope = parameters.get("scope")
    if scope is not None and scope != PUBLISHER_REPOSITORY_SCOPE:
        _fail("publisher-registry-challenge-scope-invalid")
    return parameters["service"]


def _registry_bearer_challenge() -> str:
    body = bytearray()
    retained_headers: dict[str, str] = {}
    try:
        with _attribution_scope(
            lifecycle_substage="private-acr-bearer-challenge",
            expected_authorization="deny",
        ):
            status, retained_headers, body = _private_registry_request(
                "GET", "/v2/", headers={}
            )
        if status != 401:
            _fail("publisher-registry-challenge-status-invalid")
        challenge = retained_headers.pop("www-authenticate", None)
        if challenge is None:
            _fail("publisher-registry-challenge-missing")
        return _challenge_service(challenge)
    finally:
        retained_headers.clear()
        body.clear()


def _publisher_refresh_token(
    *, entra_token: bytearray, tenant_id: str, service: str
) -> bytearray | None:
    if service != REGISTRY_HOST:
        _fail("publisher-oauth-service-invalid")
    form = _form_body(
        (
            (b"grant_type", b"access_token"),
            (b"service", service.encode("ascii")),
            (b"tenant", tenant_id.encode("ascii")),
            (b"access_token", entra_token),
        )
    )
    response = bytearray()
    try:
        expected_authorization = _expected_authorization_result()
        propagation_verification = (
            _ATTRIBUTION_SUBSTAGE.get() == "acrpush-propagation-verification"
        )
        with _attribution_scope(
            lifecycle_substage="private-acr-oauth-exchange",
            expected_authorization=expected_authorization,
        ):
            status, _headers, response = _private_registry_request(
                "POST",
                "/oauth2/exchange",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=form,
            )
        if status in {401, 403} and expected_authorization == "deny":
            return None
        if status in {401, 403} and propagation_verification:
            raise PublisherAccessPending(
                f"publisher-oauth-exchange-propagation-http-{status}"
            )
        if status in {429, *range(500, 600)}:
            raise PublisherOAuthTransient(f"publisher-oauth-exchange-http-{status}")
        if status != 200:
            _fail(f"publisher-oauth-exchange-http-{status}")
        return _oauth_secret(
            response,
            key="refresh_token",
            allowed_keys=frozenset({"refresh_token"}),
        )
    finally:
        form.clear()
        response.clear()


def _acr_access_is_exact(token: bytearray, *, tenant_id: str) -> bool:
    claims = _jwt_claims(token)
    try:
        _validate_token_time(claims)
        if claims.get("aud") != REGISTRY_HOST:
            _fail("publisher-acr-token-audience-invalid")
        token_tenant = claims.get("tid", claims.get("tenant"))
        if token_tenant is not None and token_tenant != tenant_id:
            _fail("publisher-acr-token-tenant-invalid")
        access = claims.get("access")
        if access in (None, []):
            return False
        if not isinstance(access, list) or len(access) != 1:
            _fail("publisher-acr-token-scope-invalid")
        item = access[0]
        if not isinstance(item, dict) or set(item) != {"actions", "name", "type"}:
            _fail("publisher-acr-token-scope-invalid")
        actions = item.get("actions")
        if (
            item.get("type") != "repository"
            or item.get("name") != PUBLISHER_REPOSITORY
            or not isinstance(actions, list)
            or len(actions) != 2
            or set(actions) != {"pull", "push"}
            or any(not isinstance(action, str) for action in actions)
        ):
            _fail("publisher-acr-token-scope-invalid")
        return True
    finally:
        claims.clear()


def _publisher_repository_token(
    *, refresh_token: bytearray, tenant_id: str, service: str
) -> bytearray | None:
    if service != REGISTRY_HOST:
        _fail("publisher-oauth-service-invalid")
    form = _form_body(
        (
            (b"grant_type", b"refresh_token"),
            (b"service", service.encode("ascii")),
            (b"scope", PUBLISHER_REPOSITORY_SCOPE.encode("ascii")),
            (b"refresh_token", refresh_token),
        )
    )
    response = bytearray()
    try:
        expected_authorization = _expected_authorization_result()
        propagation_verification = (
            _ATTRIBUTION_SUBSTAGE.get() == "acrpush-propagation-verification"
        )
        with _attribution_scope(
            lifecycle_substage="repository-scoped-acr-token-request",
            expected_authorization=expected_authorization,
        ):
            status, _headers, response = _private_registry_request(
                "POST",
                "/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=form,
            )
        if status in {401, 403} and expected_authorization == "deny":
            return None
        if status in {401, 403} and propagation_verification:
            raise PublisherAccessPending(
                f"publisher-oauth-token-propagation-http-{status}"
            )
        if status in {429, *range(500, 600)}:
            raise PublisherOAuthTransient(f"publisher-oauth-token-http-{status}")
        if status != 200:
            _fail(f"publisher-oauth-token-http-{status}")
        token = _oauth_secret(
            response,
            key="access_token",
            allowed_keys=frozenset({"access_token", "expires_in", "issued_at"}),
        )
        if not _acr_access_is_exact(token, tenant_id=tenant_id):
            token.clear()
            if expected_authorization == "deny":
                return None
            _fail("publisher-acr-token-scope-missing")
        return token
    finally:
        form.clear()
        response.clear()


def _publisher_repository_session_once(
    *,
    publisher_app_id: str,
    tenant_id: str,
    environment: Mapping[str, str],
) -> tuple[bytearray, bytearray | None]:
    service = _registry_bearer_challenge()
    entra_token = _publisher_entra_token(
        publisher_app_id=publisher_app_id,
        tenant_id=tenant_id,
        environment_overrides=environment,
    )
    refresh_token = bytearray()
    try:
        exchanged = _publisher_refresh_token(
            entra_token=entra_token,
            tenant_id=tenant_id,
            service=service,
        )
        if exchanged is None:
            return refresh_token, None
        refresh_token = exchanged
    finally:
        entra_token.clear()
    try:
        access_token = _publisher_repository_token(
            refresh_token=refresh_token,
            tenant_id=tenant_id,
            service=service,
        )
        return refresh_token, access_token
    except Exception:
        refresh_token.clear()
        raise


def _publisher_repository_session(
    *,
    publisher_app_id: str,
    tenant_id: str,
    environment: Mapping[str, str],
) -> tuple[bytearray, bytearray | None]:
    for attempt in range(2):
        try:
            return _publisher_repository_session_once(
                publisher_app_id=publisher_app_id,
                tenant_id=tenant_id,
                environment=environment,
            )
        except PublisherOAuthTransient:
            if attempt == 1:
                raise
    _fail("publisher-oauth-retry-state-invalid")


def _prove_initial_publisher_denial(
    *,
    publisher_app_id: str,
    tenant_id: str,
    environment: Mapping[str, str],
) -> None:
    with _attribution_scope(
        lifecycle_substage="initial-acr-denial",
        expected_authorization="deny",
    ):
        refresh_token, access_token = _publisher_repository_session(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            environment=environment,
        )
    try:
        if access_token is not None:
            _fail("publisher-initial-denial-unproved")
    finally:
        refresh_token.clear()
        if access_token is not None:
            access_token.clear()


def _wait_for_publisher_access(
    *,
    publisher_app_id: str,
    tenant_id: str,
    environment: Mapping[str, str],
) -> tuple[bytearray, bytearray]:
    deadline = time.monotonic() + 600.0
    while True:
        try:
            with _attribution_scope(
                lifecycle_substage="acrpush-propagation-verification",
                expected_authorization="allow",
            ):
                refresh_token, access_token = _publisher_repository_session(
                    publisher_app_id=publisher_app_id,
                    tenant_id=tenant_id,
                    environment=environment,
                )
        except PublisherAccessPending:
            refresh_token = bytearray()
            access_token = None
        if access_token is not None:
            return refresh_token, access_token
        refresh_token.clear()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail("publisher-role-propagation-unproved")
        time.sleep(min(10.0, remaining))


def _wait_for_publisher_denial(
    *,
    publisher_app_id: str,
    tenant_id: str,
    environment: Mapping[str, str],
) -> bytearray:
    deadline = time.monotonic() + 600.0
    while True:
        try:
            with _attribution_scope(
                lifecycle_substage="post-revocation-acr-denial",
                expected_authorization="deny",
            ):
                refresh_token, access_token = _publisher_repository_session(
                    publisher_app_id=publisher_app_id,
                    tenant_id=tenant_id,
                    environment=environment,
                )
        except PublisherAccessPending:
            refresh_token = bytearray()
            access_token = None
        if access_token is None and refresh_token:
            return refresh_token
        refresh_token.clear()
        if access_token is not None:
            access_token.clear()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail("temporary-authority-revocation-unproved")
        time.sleep(min(10.0, remaining))


def _delete_ephemeral_publisher(
    *, publisher_app_id: str, publisher_object_id: str
) -> None:
    _run(
        (
            "az",
            "ad",
            "sp",
            "delete",
            "--id",
            publisher_object_id,
            "--only-show-errors",
            "--output",
            "none",
        )
    )
    _run(
        (
            "az",
            "ad",
            "app",
            "delete",
            "--id",
            publisher_app_id,
            "--only-show-errors",
            "--output",
            "none",
        )
    )
    applications = _run(
        (
            "az",
            "ad",
            "app",
            "list",
            "--filter",
            f"appId eq '{publisher_app_id}'",
            "--query",
            "[].{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    principals = _run(
        (
            "az",
            "ad",
            "sp",
            "list",
            "--filter",
            f"appId eq '{publisher_app_id}'",
            "--query",
            "[].{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if applications != [] or principals != []:
        _fail("publisher-identity-deletion-unproved")


def _delete_ephemeral_publisher_by_app_id(app_id: str) -> None:
    principals = _run(
        (
            "az",
            "ad",
            "sp",
            "list",
            "--filter",
            f"appId eq '{app_id}'",
            "--query",
            "[].{appId:appId,objectId:id,servicePrincipalType:servicePrincipalType}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(principals, list) or len(principals) > 1:
        _fail("publisher-partial-identity-inventory-malformed")
    if principals:
        principal = principals[0]
        if (
            not isinstance(principal, dict)
            or set(principal) != {"appId", "objectId", "servicePrincipalType"}
            or principal.get("appId") != app_id
            or principal.get("servicePrincipalType") != "Application"
            or not isinstance(principal.get("objectId"), str)
        ):
            _fail("publisher-partial-identity-inventory-malformed")
        _run(
            (
                "az",
                "ad",
                "sp",
                "delete",
                "--id",
                str(principal["objectId"]),
                "--only-show-errors",
                "--output",
                "none",
            )
        )
    _run(
        (
            "az",
            "ad",
            "app",
            "delete",
            "--id",
            app_id,
            "--only-show-errors",
            "--output",
            "none",
        )
    )
    applications = _run(
        (
            "az",
            "ad",
            "app",
            "list",
            "--filter",
            f"appId eq '{app_id}'",
            "--query",
            "[].{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    remaining_principals = _run(
        (
            "az",
            "ad",
            "sp",
            "list",
            "--filter",
            f"appId eq '{app_id}'",
            "--query",
            "[].{id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if applications != [] or remaining_principals != []:
        _fail("publisher-identity-deletion-unproved")


def _denial_probe(
    argv: tuple[str, ...],
    *,
    environment_overrides: Mapping[str, str] | None = None,
) -> str:
    if not argv or argv[0] not in {"az", "docker"}:
        _fail("denial-probe-executable-unapproved")
    attribution, operation_id, attribution_spec = _begin_process_attribution(
        argv,
        environment_overrides=environment_overrides,
        expected_authorization="deny",
    )
    try:
        if argv[0] == "az":
            actual = _resolve_authorized_process_launch(argv).argv
        else:
            actual = (_resolved_executable("docker"), *argv[1:])
        environment = _environment()
        if environment_overrides is not None:
            if set(environment_overrides) - {"AZURE_CONFIG_DIR", "DOCKER_CONFIG"}:
                _fail("lifecycle-environment-override-unapproved")
            for key, value in environment_overrides.items():
                resolved = _outside_repository(Path(value), key.casefold())
                if not resolved.is_dir():
                    _fail("lifecycle-environment-override-unapproved")
            environment.update(environment_overrides)
        if (
            attribution is not None
            and operation_id is not None
            and attribution_spec is not None
        ):
            attribution.mark_request_attempt_began(
                operation_id,
                cleanup_or_revocation=attribution_spec["cleanupOrRevocation"] is True,
            )
        completed = subprocess.run(
            actual,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="denial-probe-process-timed-out",
            correlation_hash=None,
            terminal_disposition="TIMED_OUT",
        )
        _fail("denial-probe-process-timed-out")
    except KeyboardInterrupt:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="denial-probe-process-cancelled",
            correlation_hash=None,
            terminal_disposition="CANCELLED",
        )
        raise
    except OSError:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="denial-probe-process-launch-failed",
            correlation_hash=None,
            terminal_disposition="UNCERTAIN",
        )
        _fail("denial-probe-process-launch-failed")
    if attribution is not None and operation_id is not None:
        attribution.mark_azure_request_issued(operation_id)
    stdout = bytearray(completed.stdout)
    stderr = bytearray(completed.stderr)
    attribution_finished = False
    try:
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("denial-probe-output-oversized")
        if completed.returncode == 0:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code="2xx-not-reported",
                azure_error_code=None,
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="SUCCEEDED",
            )
            attribution_finished = True
            return "allowed"
        try:
            message = bytes(stderr).decode("utf-8", errors="strict").casefold()
        except UnicodeError:
            _fail("denial-probe-output-malformed")
        if not any(
            marker in message
            for marker in ("403", "denied", "forbidden", "permission", "unauthorized")
        ):
            error_code = _sanitized_azure_error_code(stdout, stderr)
            _fail(f"denial-probe-result-ambiguous-{error_code}")
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code=_sanitized_status_code(stdout, stderr, default="403"),
            azure_error_code=_sanitized_azure_error_code(stdout, stderr),
            correlation_hash=_sanitized_correlation_hash(stdout, stderr),
            terminal_disposition="SUCCEEDED",
        )
        attribution_finished = True
        return "denied"
    except BaseException as exc:
        if not attribution_finished:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=_sanitized_status_code(
                    stdout, stderr, default="not-reported"
                ),
                azure_error_code=_safe_attribution_error(exc),
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
        raise
    finally:
        stdout.clear()
        stderr.clear()


def _wait_for_denial(
    argv: tuple[str, ...],
    *,
    endpoint_host: str,
    environment_overrides: Mapping[str, str] | None = None,
) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        _private_tls_endpoint(endpoint_host)
        if (
            _denial_probe(
                argv,
                environment_overrides=environment_overrides,
            )
            == "denied"
        ):
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
    if not isinstance(rbac, dict):
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
        "temporaryKeyVaultAuthorityLedgerSha256": None,
        "temporaryKeyVaultAuthorityProved": False,
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

    _ensure_temporary_key_vault_authority(
        subscription_id=subscription_id,
        ledger=ledger,
        state_path=state_path,
        state=state,
    )
    state["activeStage"] = None
    state["disposition"] = LifecycleDisposition.COMPLETED.value
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


def _docker_login_with_refresh_token(
    refresh_token: bytearray, *, environment: Mapping[str, str]
) -> None:
    attribution, operation_id, _attribution_spec = _begin_process_attribution(
        ("docker", "login"),
        environment_overrides=environment,
        expected_authorization="allow",
    )
    payload = bytearray(refresh_token)
    payload.append(ord("\n"))
    stdout = bytearray()
    stderr = bytearray()
    attribution_finished = False
    try:
        publisher_environment = _publisher_environment(environment)
        docker_executable = _resolved_executable("docker")
        if attribution is not None and operation_id is not None:
            attribution.mark_request_attempt_began(
                operation_id, cleanup_or_revocation=False
            )
        completed = subprocess.run(
            (
                docker_executable,
                "login",
                REGISTRY_HOST,
                "--username",
                ACR_REFRESH_TOKEN_USERNAME,
                "--password-stdin",
            ),
            cwd=REPOSITORY_ROOT,
            env=publisher_environment,
            input=payload,
            capture_output=True,
            check=False,
            shell=False,
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
        if attribution is not None and operation_id is not None:
            attribution.mark_azure_request_issued(operation_id)
        stdout.extend(completed.stdout)
        stderr.extend(completed.stderr)
        if len(stdout) + len(stderr) > MAXIMUM_OUTPUT_BYTES:
            _fail("publisher-docker-login-output-oversized")
        if bytes(refresh_token) in stdout or bytes(refresh_token) in stderr:
            _fail("publisher-secret-echo-detected")
        if completed.returncode != 0:
            _fail("publisher-docker-login-failed")
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="2xx-not-reported",
            azure_error_code=None,
            correlation_hash=_sanitized_correlation_hash(stdout, stderr),
            terminal_disposition="SUCCEEDED",
        )
        attribution_finished = True
    except subprocess.TimeoutExpired:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-docker-login-process-timed-out",
            correlation_hash=None,
            terminal_disposition="TIMED_OUT",
        )
        attribution_finished = True
        _fail("publisher-docker-login-process-timed-out")
    except KeyboardInterrupt:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-docker-login-process-cancelled",
            correlation_hash=None,
            terminal_disposition="CANCELLED",
        )
        attribution_finished = True
        raise
    except OSError:
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-docker-login-process-launch-failed",
            correlation_hash=None,
            terminal_disposition="UNCERTAIN",
        )
        attribution_finished = True
        _fail("publisher-docker-login-process-launch-failed")
    except BaseException as exc:
        if not attribution_finished:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=_sanitized_status_code(
                    stdout, stderr, default="not-reported"
                ),
                azure_error_code=_safe_attribution_error(exc),
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
        raise
    finally:
        payload.clear()
        stdout.clear()
        stderr.clear()


def _registry_authorization(access_token: bytearray) -> str:
    value = bytearray(b"Bearer ")
    value.extend(access_token)
    try:
        return value.decode("ascii", errors="strict")
    except UnicodeError:
        _fail("publisher-acr-token-malformed")
    finally:
        value.clear()


def _acr_manifest_digest(access_token: bytearray, *, reference: str) -> str | None:
    if not (
        re.fullmatch(r"source-[0-9a-f]{40}", reference)
        or RAW_IMAGE_DIGEST.fullmatch(reference)
    ):
        _fail("registry-manifest-reference-invalid")
    body = bytearray()
    try:
        status, headers, body = _private_registry_request(
            "HEAD",
            f"/v2/{PUBLISHER_REPOSITORY}/manifests/{reference}",
            headers={
                "Accept": MANIFEST_ACCEPT,
                "Authorization": _registry_authorization(access_token),
            },
        )
        if status == 404:
            return None
        if status in {401, 403}:
            raise PublisherAccessPending("publisher-repository-access-denied")
        if status != 200:
            _fail("registry-manifest-verification-failed")
        digest = headers.get("docker-content-digest")
        if digest is None or RAW_IMAGE_DIGEST.fullmatch(digest) is None:
            _fail("registry-digest-output-malformed")
        if RAW_IMAGE_DIGEST.fullmatch(reference) and digest != reference:
            _fail("registry-immutable-digest-mismatch")
        return digest
    finally:
        body.clear()


def _assert_source_tag_absent(*, source_tag: str, access_token: bytearray) -> None:
    if _acr_manifest_digest(access_token, reference=source_tag) is not None:
        _fail("registry-source-tag-already-present")


def _prebuild_api_image(
    *, repository_head: str, record_path: Path
) -> dict[str, JsonValue]:
    from infra.milestone_7_7 import api_image_publication

    if (
        api_image_publication._LIFECYCLE_MODULE_IDENTITY
        is not _LIFECYCLE_MODULE_IDENTITY
    ):
        _fail("api-image-publication-module-state-mismatch")
    return api_image_publication._prebuild_api_image(
        repository_head=repository_head, record_path=record_path
    )


def _publish_api_image(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    prebuilt_image_record: Path,
) -> str:
    from infra.milestone_7_7 import api_image_publication

    if (
        api_image_publication._LIFECYCLE_MODULE_IDENTITY
        is not _LIFECYCLE_MODULE_IDENTITY
    ):
        _fail("api-image-publication-module-state-mismatch")
    return api_image_publication._publish_api_image(
        ledger=ledger,
        subscription_id=subscription_id,
        receipt_directory=receipt_directory,
        prebuilt_image_record=prebuilt_image_record,
    )


def _reconcile_published_api_image(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    prebuilt_image_record: Path,
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
    return _publish_api_image(
        ledger=ledger,
        subscription_id=subscription_id,
        receipt_directory=receipt_directory,
        prebuilt_image_record=prebuilt_image_record,
    )


def _container_app_revision_ready(subscription_id: str, app_name: str) -> None:
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
                app_name,
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
                    app_name,
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


def _migration_job_ready(subscription_id: str) -> None:
    started = _run(
        (
            "az",
            "containerapp",
            "job",
            "start",
            "--resource-group",
            TARGET_GROUP,
            "--name",
            "caj-mobius77-migration",
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
    if not isinstance(started, dict) or set(started) != {"name"}:
        _fail("migration-job-start-output-malformed")
    execution_name = started["name"]
    if not isinstance(execution_name, str) or not execution_name.startswith(
        "caj-mobius77-migration-"
    ):
        _fail("migration-job-start-output-malformed")
    deadline = time.monotonic() + 1800.0
    while time.monotonic() < deadline:
        execution = _run(
            (
                "az",
                "containerapp",
                "job",
                "execution",
                "show",
                "--resource-group",
                TARGET_GROUP,
                "--name",
                "caj-mobius77-migration",
                "--job-execution-name",
                execution_name,
                "--subscription",
                subscription_id,
                "--query",
                "{name:name,status:properties.status}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if not isinstance(execution, dict) or set(execution) != {"name", "status"}:
            _fail("migration-job-status-output-malformed")
        if execution.get("name") != execution_name:
            _fail("migration-job-status-output-malformed")
        if execution.get("status") == "Succeeded":
            return
        if execution.get("status") in {"Canceled", "Failed"}:
            _fail("migration-job-failed")
        time.sleep(5.0)
    _fail("migration-job-timeout")


def _private_revision_ready(subscription_id: str) -> None:
    for app_name in (
        "ca-mobius77-telemetry",
        "ca-mobius77-worker",
        "ca-mobius77-api",
    ):
        _container_app_revision_ready(subscription_id, app_name)


def _managed_secret_states(subscription_id: str) -> dict[str, bool]:
    rows = _run(
        (
            "az",
            "keyvault",
            "secret",
            "list",
            "--vault-name",
            KEY_VAULT,
            "--subscription",
            subscription_id,
            "--query",
            "[].{name:name,enabled:attributes.enabled}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(rows, list):
        _fail("managed-secret-presence-or-state-unproved")
    result: dict[str, bool] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"enabled", "name"}
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("enabled"), bool)
        ):
            _fail("managed-secret-presence-or-state-unproved")
        name = str(row["name"])
        if name in result:
            _fail("managed-secret-presence-or-state-unproved")
        result[name] = bool(row["enabled"])
    return result


def _post_secret(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    prebuilt_image_record: Path,
) -> dict[str, JsonValue]:
    state_path = _state_path(receipt_directory)
    state = _read_current_transient_state(state_path, ledger=ledger)
    cleanup_at_raw = state.get("cleanupAtUtc")
    if not isinstance(cleanup_at_raw, str):
        _fail("cleanup-binding-missing")
    cleanup_at = datetime.strptime(cleanup_at_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    if _utc_now() >= cleanup_at - timedelta(minutes=90):
        _fail("cleanup-reserve-active")
    required_secret_names = (
        "openai-api-key",
        "opencanvas-smtp-username",
        "opencanvas-smtp-password",
        "opencanvas-session-secret",
        "opencanvas-invitation-secret",
        "opencanvas-upload-capability-secret",
        "opencanvas-scanner-result-secret",
        "opencanvas-rate-limit-hmac-secret",
        "opencanvas-telemetry-token",
        "opencanvas-telemetry-pseudonymization-secret",
        "opencanvas-observability-operator-user-ids",
    )
    try:
        _ensure_temporary_key_vault_authority(
            subscription_id=subscription_id,
            ledger=ledger,
            state_path=state_path,
            state=state,
        )
        with _attribution_scope(
            lifecycle_substage="key-vault-secret-metadata-listing",
            expected_authorization="allow",
        ):
            secret_states = _managed_secret_states(subscription_id)
        if secret_states != dict.fromkeys(required_secret_names, True):
            _fail("managed-secret-presence-or-state-unproved")
    finally:
        _revoke_temporary_key_vault_authority(
            subscription_id=subscription_id,
            state_path=state_path,
            state=state,
        )
    expected_cost, maximum_cost = _verified_cost()
    api_image_digest = _reconcile_published_api_image(
        ledger=ledger,
        subscription_id=subscription_id,
        receipt_directory=receipt_directory,
        prebuilt_image_record=prebuilt_image_record,
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
    _migration_job_ready(subscription_id)
    _private_revision_ready(subscription_id)
    return {
        "status": "private-revision-ready",
        "managed-secret-count": len(required_secret_names),
        "migration-job-succeeded": True,
        "immutable-image-digest-bound": True,
        "canonical-openai-alias-only": True,
        "secret-value-accessed": False,
    }


def _revoke(subscription_id: str, receipt_directory: Path) -> dict[str, JsonValue]:
    state_path = _state_path(receipt_directory)
    state = _read_state(state_path)
    removed = 0
    key_vault_assignment_removed = _revoke_temporary_key_vault_authority(
        subscription_id=subscription_id, state_path=state_path, state=state
    )
    if key_vault_assignment_removed:
        removed += 1
    registry_assignment_removed = False
    for key in ("temporaryRegistryAssignmentId",):
        value = state.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.startswith("/subscriptions/"):
            _fail("temporary-assignment-state-malformed")
        _delete_assignment(subscription_id, value)
        state[key] = None
        removed += 1
        if key == "temporaryRegistryAssignmentId":
            registry_assignment_removed = True
        _replace_state(state_path, state)
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
    state = _read_current_transient_state(state_path, ledger=ledger)
    try:
        _validate_transient_state(state, ledger=ledger)
    except LifecycleError:
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
        or state["temporaryKeyVaultAuthorityLedgerSha256"] is not None
        or state["temporaryKeyVaultAuthorityProved"] is not False
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


def _safe_failed_stage(receipt_directory: Path | None, *, operation: str) -> str:
    if receipt_directory is None:
        return "unknown"
    attributed = _attributed_failed_stage(receipt_directory)
    if attributed is not None:
        return attributed
    if operation in LIFECYCLE_OPERATIONS:
        return "protected-attribution-missing"
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
    failed_stage = _safe_failed_stage(receipt_directory, operation=operation)
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
    durable_checkpoint: str | None = None
    if receipt_directory is not None:
        state_path = _state_path(receipt_directory)
        if state_path.is_file():
            try:
                state = (
                    _read_current_transient_state(state_path, ledger=ledger)
                    if ledger is not None
                    else _read_state(state_path)
                )
                durable_checkpoint = _last_durable_checkpoint(state)
                if (
                    subscription_id is not None
                    and state.get("temporaryKeyVaultAssignmentId") is not None
                ):
                    _revoke_temporary_key_vault_authority(
                        subscription_id=subscription_id,
                        state_path=state_path,
                        state=state,
                    )
                    cleanup_status = "temporary-key-vault-authority-revoked-and-denied"
                    durable_checkpoint = KEY_VAULT_AUTHORITY_REVOKED_STAGE
                state["activeStage"] = None
                state["disposition"] = failure_disposition.value
                state["failedStage"] = failed_stage
                state["resumableCheckpoint"] = durable_checkpoint
                _replace_state(state_path, state)
            except (ContractError, LifecycleError, OSError, ValueError):
                # A malformed transient state cannot safely identify a role to revoke.
                # Preserve it fail-closed; a verified assignment is revoked above.
                pass
    record = _failure_record(
        disposition=failure_disposition,
        operation=operation,
        failed_stage=failed_stage,
        error_code=error_code,
        azure_error_code=azure_error_code,
        proof={"proved": False},
        resumable_checkpoint=durable_checkpoint,
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--operation", choices=LIFECYCLE_OPERATIONS)
    mode.add_argument("--prebuild-local-image", action="store_true")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--receipt-directory", type=Path)
    parser.add_argument("--prebuilt-image-record", type=Path)
    parser.add_argument("--repository-head", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    now = _utc_now()
    if args.prebuild_local_image:
        try:
            if (
                args.ledger is not None
                or args.receipt_directory is not None
                or args.prebuilt_image_record is None
                or HEX_SHA40.fullmatch(args.repository_head) is None
            ):
                _fail("prebuilt-api-image-command-contract-invalid")
            record = _prebuild_api_image(
                repository_head=args.repository_head,
                record_path=args.prebuilt_image_record,
            )
            result = {
                "azure-mutation-performed": False,
                "build-input-sha256": record["buildInputSha256"],
                "completion-status": record["completionStatus"],
                "config-digest": record["configDigest"],
                "image-id": record["imageId"],
                "platform": record["platform"],
                "repository-head": record["repositoryHead"],
                "status": "complete",
            }
            print(json.dumps(result, separators=(",", ":"), sort_keys=True))
            return 0
        except (Exception, KeyboardInterrupt) as exc:
            error_code, _azure_error_code = _sanitized_failure(exc)
            print(
                json.dumps(
                    {
                        "azure-mutation-performed": False,
                        "error": error_code,
                        "status": "blocked",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 130 if isinstance(exc, KeyboardInterrupt) else 2
    if (
        args.operation is None
        or args.ledger is None
        or args.receipt_directory is None
        or (
            args.operation == "post-secret-provisioning"
            and args.prebuilt_image_record is None
        )
        or (
            args.operation != "post-secret-provisioning"
            and args.prebuilt_image_record is not None
        )
    ):
        print(
            json.dumps(
                {
                    "azure-mutation-performed": False,
                    "error": "lifecycle-command-contract-invalid",
                    "status": "blocked",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    operation = cast(str, args.operation)
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
            operation_id=operation,
            receipt_directory=receipt_directory,
            now_utc=now,
            expected_repository_head=args.repository_head,
        )
        with _operation_attribution_session(
            receipt_directory=receipt_directory,
            lifecycle_stage=operation,
            ledger_integrity=_ledger_integrity(ledger),
            repository_head=args.repository_head,
        ):
            if operation == "pre-secret-provisioning":
                result = _pre_secret(
                    ledger=ledger,
                    subscription_id=subscription_id,
                    receipt_directory=receipt_directory,
                )
            elif operation == "private-path-verification":
                result = _private_path(subscription_id)
            elif operation == "post-secret-provisioning":
                assert args.prebuilt_image_record is not None
                result = _post_secret(
                    ledger=ledger,
                    subscription_id=subscription_id,
                    receipt_directory=receipt_directory,
                    prebuilt_image_record=args.prebuilt_image_record,
                )
            elif operation == "temporary-authority-revocation":
                result = _revoke(subscription_id, receipt_directory)
            elif operation == "cleanup":
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
                    operation=operation,
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
