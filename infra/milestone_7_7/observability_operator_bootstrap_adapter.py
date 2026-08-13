"""Production adapter for the private observability-owner bootstrap ordering fix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal, NoReturn, cast

from infra.milestone_7_7 import api_image_publication
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from infra.milestone_7_7.scripts.scanner_bridge_deployment import (
    ScannerBridgeDeploymentError,
    deployment_name,
    deployment_parameters,
    parse_owner_bootstrap_outputs,
)
from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
)
from preflight.milestone_7_7.managed_binding_contracts import REPOSITORY_ROOT
from preflight.milestone_7_7.observability_operator_bootstrap import (
    API_CONTAINER_APP,
    CANONICAL_IMAGE_INPUT_SHA256,
    CLEANUP_ROLE_DEFINITION_ID,
    COST_CEILING_USD_CENTS,
    EXPECTED_DATABASE_REVISION,
    IMMUTABLE_API_IMAGE,
    MIGRATION_JOB,
    MINIMUM_DATABASE_ADMINISTRATOR_PROPAGATION,
    OWNER_READBACK_JOB,
    SESSION_SECRET,
    TARGET_RESOURCE_GROUP,
    ObservabilityOperatorBootstrapAuthorization,
    load_observability_operator_bootstrap_authorization,
    validate_observability_operator_bootstrap_authorization,
)

RECEIPT_VERSION: Final = (
    "mobius.milestone-7.7.observability-operator-bootstrap-receipt.v1"
)
RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/observability-operator-bootstrap-receipt/v1\0"
)
RECEIPT_FILE: Final = "observability-operator-bootstrap.receipt.json"
RETAINED_MIGRATION_AUTHORIZATION_ID: Final = "bcdc5404-5742-5030-bd02-b4b3a25ef576"
RETAINED_MIGRATION_AUTHORIZATION_INTEGRITY: Final = (
    "8931d119f6cf930517e29ad7b020c940a2b1e90c37ec4913fd2420ded3852a87"
)
RETAINED_MIGRATION_RECEIPT_INTEGRITY: Final = (
    "7f4dcfd0e7ff61c199b318ee67d4c9797bea3b4a37c18e6ddb910c32b63e9ca2"
)
RETAINED_MIGRATION_SOURCE_HEAD: Final = "e44670cb430edd807f5487345472eaa8c0115c2c"
RETAINED_MIGRATION_EXECUTION: Final = "caj-mobius77-migration-r22ygqj"
RETAINED_MIGRATION_CLAIMED_AT: Final = "2026-08-12T17:12:59Z"
RETAINED_MIGRATION_PRIVATE_URL: Final = (
    "https://ca-mobius77-api.internal.delightfulgrass-bfebe48e."
    "southcentralus.azurecontainerapps.io"
)
STAGING_LOCATION: Final = "southcentralus"
POSTGRES_API_VERSION: Final = "2024-08-01"
CONTAINER_APP_API_VERSION: Final = "2026-01-01"
JOB_API_VERSION: Final = "2025-01-01"
KEY_VAULT_SECRET_API_VERSION: Final = "2024-11-01"
MANAGED_IDENTITY_API_VERSION: Final = "2024-11-30"
MIGRATION_TIMEOUT_SECONDS: Final = 1_800.0
APPLICATION_TIMEOUT_SECONDS: Final = 900.0
READBACK_TIMEOUT_SECONDS: Final = 300.0
START_RECONCILIATION_SECONDS: Final = 120.0
POLL_SECONDS: Final = 5.0
PROPAGATION_POLL_SECONDS: Final = 15.0
MAXIMUM_SUCCESS_ADOPTION_AGE: Final = timedelta(hours=1)
_TERMINAL_JOB_STATUSES: Final = frozenset(
    {"Cancelled", "Failed", "Stopped", "Succeeded"}
)
_MIGRATION_FAILURE_CODES: Final = frozenset(
    {
        "observability-bootstrap-migration-or-runtime-privilege-reconciliation-failed",
        "observability-bootstrap-final-database-connect-failed",
        "observability-bootstrap-final-managed-identity-token-failed",
        "observability-bootstrap-final-revision-mismatch",
        "observability-bootstrap-final-revision-value-invalid",
        "observability-bootstrap-final-revision-value-read-failed",
        "observability-bootstrap-final-settings-validation-failed",
        "observability-bootstrap-final-version-table-read-failed",
        "observability-bootstrap-initial-database-connect-failed",
        "observability-bootstrap-initial-managed-identity-token-failed",
        "observability-bootstrap-initial-revision-value-invalid",
        "observability-bootstrap-initial-revision-value-read-failed",
        "observability-bootstrap-initial-settings-validation-failed",
        "observability-bootstrap-initial-version-table-read-failed",
        "observability-bootstrap-migration-apply-failed",
        "observability-bootstrap-revision-drift",
        "observability-bootstrap-runtime-grant-database-connect-failed",
        "observability-bootstrap-runtime-managed-identity-token-failed",
        "observability-bootstrap-runtime-principal-catalog-connect-failed",
        "observability-bootstrap-runtime-principal-contract-invalid",
        "observability-bootstrap-runtime-principal-create-failed",
        "observability-bootstrap-runtime-principal-list-failed",
        "observability-bootstrap-runtime-principal-mapping-invalid",
        "observability-bootstrap-runtime-principal-privilege-invalid",
        "observability-bootstrap-runtime-principal-provider-column-invalid",
        "observability-bootstrap-runtime-principal-provider-duplicate",
        "observability-bootstrap-runtime-principal-provider-function-absent",
        "observability-bootstrap-runtime-principal-provider-identity-not-found",
        "observability-bootstrap-runtime-principal-provider-permission-denied",
        "observability-bootstrap-runtime-principal-readback-failed",
        "observability-bootstrap-runtime-role-grant-failed",
    }
)
_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?$"
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_OWNER_MARKER = re.compile(
    r'\{"marker":"GENUINE_OWNER_APPLICATION_UUID_PROVED","userId":"'
    r'([0-9a-fA-F-]{36})"\}'
)

ReceiptPhase = Literal["claimed", "prepared", "owner-proved"]


class ObservabilityOperatorBootstrapExecutionError(RuntimeError):
    """Raised when the narrow production bootstrap cannot be proved."""


def _fail(code: str) -> NoReturn:
    raise ObservabilityOperatorBootstrapExecutionError(code)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        _fail(code)


def _parse_azure_utc(value: str, code: str) -> datetime:
    try:
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except (AttributeError, TypeError, ValueError):
        _fail(code)
    if parsed.tzinfo is None:
        _fail(code)
    return parsed.astimezone(UTC)


def _parse_duration_seconds(value: str, code: str) -> float:
    matched = _DURATION.fullmatch(value)
    if matched is None:
        _fail(code)
    parts = {
        name: float(raw) if raw is not None else 0.0
        for name, raw in matched.groupdict().items()
    }
    seconds = (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )
    if seconds < 0:
        _fail(code)
    return seconds


def _outside_repository(path: Path) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        _fail("observability-bootstrap-receipts-inside-repository")
    return resolved


def _receipt_path(receipt_directory: Path) -> Path:
    return _outside_repository(receipt_directory) / RECEIPT_FILE


def _unsigned_receipt(value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        key: child for key, child in value.items() if key != "receiptIntegritySha256"
    }


def _receipt_integrity(value: Mapping[str, JsonValue]) -> str:
    return integrity_sha256(_unsigned_receipt(value), RECEIPT_DOMAIN)


def _new_receipt(
    authorization: ObservabilityOperatorBootstrapAuthorization,
    *,
    now_utc: datetime,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "authorizationId": authorization.authorizationId,
        "authorizationIntegritySha256": authorization.authorizationIntegritySha256,
        "bootstrapPrivateApplicationUrl": None,
        "claimedAtUtc": _format_utc(now_utc),
        "migrationExecutionName": None,
        "migrationTerminalStatus": None,
        "ownerReadbackExecutionName": None,
        "ownerReadbackJobDeleted": False,
        "ownerUserId": None,
        "phase": "claimed",
        "receiptVersion": RECEIPT_VERSION,
        "repositoryHead": authorization.repositoryHead,
        "subscriptionId": authorization.subscriptionId,
    }
    return {**body, "receiptIntegritySha256": _receipt_integrity(body)}


def _write_new_receipt(path: Path, value: Mapping[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("observability-bootstrap-authorization-already-consumed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(cast(JsonValue, dict(value))))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("observability-bootstrap-receipt-write-failed")


def _replace_receipt(path: Path, value: Mapping[str, JsonValue]) -> None:
    unsigned = _unsigned_receipt(value)
    document: dict[str, JsonValue] = {
        **unsigned,
        "receiptIntegritySha256": _receipt_integrity(unsigned),
    }
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(canonical_bytes(document))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        _fail("observability-bootstrap-receipt-write-failed")


def _load_receipt(path: Path) -> dict[str, JsonValue]:
    try:
        value = load_json(path)
    except (OSError, ValueError):
        _fail("observability-bootstrap-receipt-invalid")
    required = {
        "authorizationId",
        "authorizationIntegritySha256",
        "bootstrapPrivateApplicationUrl",
        "claimedAtUtc",
        "migrationExecutionName",
        "migrationTerminalStatus",
        "ownerReadbackExecutionName",
        "ownerReadbackJobDeleted",
        "ownerUserId",
        "phase",
        "receiptIntegritySha256",
        "receiptVersion",
        "repositoryHead",
        "subscriptionId",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("receiptVersion") != RECEIPT_VERSION
        or value.get("phase") not in {"claimed", "prepared", "owner-proved"}
        or not isinstance(value.get("receiptIntegritySha256"), str)
        or value.get("receiptIntegritySha256") != _receipt_integrity(value)
    ):
        _fail("observability-bootstrap-receipt-invalid")
    return value


def _receipt_for_authorization(
    path: Path, authorization: ObservabilityOperatorBootstrapAuthorization
) -> dict[str, JsonValue]:
    receipt = _load_receipt(path)
    if (
        receipt.get("authorizationId") != authorization.authorizationId
        or receipt.get("authorizationIntegritySha256")
        != authorization.authorizationIntegritySha256
        or receipt.get("repositoryHead") != authorization.repositoryHead
        or receipt.get("subscriptionId") != authorization.subscriptionId
    ):
        _fail("observability-bootstrap-receipt-authorization-mismatch")
    return receipt


def _verify_repository_boundary(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> None:
    try:
        lifecycle._verify_repository_state(authorization.repositoryHead)
        stash_output = lifecycle._run(("git", "stash", "list"), require_text=True)
    except lifecycle.LifecycleError as exc:
        _fail(str(exc))
    if not isinstance(stash_output, str) or len(stash_output.splitlines()) != 5:
        _fail("observability-bootstrap-protected-stash-count-invalid")
    if (
        api_image_publication._api_image_build_input_sha256(
            authorization.repositoryHead
        )
        != CANONICAL_IMAGE_INPUT_SHA256
    ):
        _fail("observability-bootstrap-canonical-image-input-drift")
    if authorization.apiImageDigest != IMMUTABLE_API_IMAGE:
        _fail("observability-bootstrap-immutable-image-drift")


def _verify_cleanup_and_cost(
    authorization: ObservabilityOperatorBootstrapAuthorization,
    *,
    now_utc: datetime,
) -> tuple[int, int]:
    cleanup_at = _parse_utc(
        authorization.cleanupDeadlineUtc,
        "observability-bootstrap-cleanup-deadline-invalid",
    )
    if cleanup_at <= now_utc.astimezone(UTC):
        _fail("observability-bootstrap-cleanup-deadline-expired")
    try:
        principal_id = lifecycle._verify_cleanup_control(
            authorization.subscriptionId, cleanup_at
        )
        lifecycle._verify_cleanup_target_role(
            authorization.subscriptionId,
            principal_id,
            CLEANUP_ROLE_DEFINITION_ID,
        )
        expected_cost, maximum_cost = lifecycle._verified_cost()
    except lifecycle.LifecycleError as exc:
        _fail(str(exc))
    if maximum_cost > min(authorization.maximumCostUsdCents, COST_CEILING_USD_CENTS):
        _fail("observability-bootstrap-cost-ceiling-exceeded")
    return expected_cost, maximum_cost


def _verify_session_secret_metadata(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> None:
    value = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (
                "https://management.azure.com"
                f"{authorization.keyVaultId}/secrets/{SESSION_SECRET}"
                f"?api-version={KEY_VAULT_SECRET_API_VERSION}"
            ),
            "--query",
            "{id:id,enabled:properties.attributes.enabled}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected_id = f"{authorization.keyVaultId}/secrets/{SESSION_SECRET}"
    if (
        not isinstance(value, dict)
        or set(value) != {"enabled", "id"}
        or value.get("enabled") is not True
        or not isinstance(value.get("id"), str)
        or str(value["id"]).casefold() != expected_id.casefold()
    ):
        _fail("observability-bootstrap-session-secret-metadata-invalid")


def _lifecycle_tags(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> dict[str, str]:
    return {
        "mobius-cleanup-binding-sha256": (authorization.authorizationIntegritySha256),
        "mobius-contract-version": "m7.7-observability-owner-bootstrap-v1",
        "mobius-cost-ceiling-usd-cents": str(authorization.maximumCostUsdCents),
        "mobius-data-class": "isolated-synthetic",
        "mobius-environment": "milestone-7.7-staging",
        "mobius-expires-at-utc": authorization.cleanupDeadlineUtc,
        "mobius-manifest-sha256": authorization.authorizationIntegritySha256,
        "mobius-public-access": "denied",
        "mobius-run-id": authorization.authorizationId,
        "mobius-source-commit": authorization.repositoryHead,
        "mobius-teardown-state": "preservation-only",
    }


def _deployment_name(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> str:
    try:
        return deployment_name(
            "owner-bootstrap",
            authorization.authorizationIntegritySha256,
            allowed_stages=frozenset({"owner-bootstrap"}),
        )
    except ScannerBridgeDeploymentError as exc:
        _fail(str(exc))


def _deployment_readback(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> dict[str, str]:
    response = lifecycle._run(
        (
            "az",
            "deployment",
            "sub",
            "show",
            "--name",
            _deployment_name(authorization),
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "{properties:properties}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(response, dict):
        _fail("owner-bootstrap-deployment-output-malformed")
    try:
        parsed = parse_owner_bootstrap_outputs(response)
    except ScannerBridgeDeploymentError as exc:
        _fail(str(exc))
    if parsed.get("immutable-image") != authorization.apiImageDigest:
        _fail("observability-bootstrap-immutable-image-drift")
    return parsed


def _deployment_state(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> str:
    value = lifecycle._run(
        (
            "az",
            "deployment",
            "sub",
            "show",
            "--name",
            _deployment_name(authorization),
            "--subscription",
            authorization.subscriptionId,
            "--query",
            "properties.provisioningState",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        require_text=True,
    )
    if not isinstance(value, str) or not value:
        _fail("observability-bootstrap-deployment-state-malformed")
    return value


def _optional_deployment_state(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> str | None:
    name = _deployment_name(authorization)
    value = lifecycle._run(
        (
            "az",
            "deployment",
            "sub",
            "list",
            "--subscription",
            authorization.subscriptionId,
            "--query",
            f"[?name=='{name}'].{{name:name,state:properties.provisioningState}}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if value == []:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], dict)
        or value[0].get("name") != name
        or not isinstance(value[0].get("state"), str)
    ):
        _fail("observability-bootstrap-deployment-inventory-malformed")
    return str(value[0]["state"])


def _wait_deployment_readback(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> dict[str, str]:
    deadline = time.monotonic() + lifecycle.DEPLOYMENT_TIMEOUT_SECONDS
    while True:
        state = _deployment_state(authorization)
        if state == "Succeeded":
            return _deployment_readback(authorization)
        if state in {"Canceled", "Failed"}:
            _fail("observability-bootstrap-deployment-terminal-failure")
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-deployment-timeout")
        time.sleep(POLL_SECONDS)


def _expected_migration_bootstrap_program() -> str:
    path = REPOSITORY_ROOT / "infra" / "milestone_7_7" / "modules" / "compute.bicep"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        _fail("observability-bootstrap-migration-program-unreadable")
    prefix = "var migrationBootstrapProgram = '''\n"
    suffix = "\n'''\nvar ownerReadbackProgram"
    if source.count(prefix) != 1 or source.count(suffix) != 1:
        _fail("observability-bootstrap-migration-program-malformed")
    program = source.split(prefix, 1)[1].split(suffix, 1)[0] + "\n"
    if not 1 <= len(program.encode("utf-8")) <= 16_384:
        _fail("observability-bootstrap-migration-program-malformed")
    return program


def _wait_migration_job_definition(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> None:
    deadline = time.monotonic() + APPLICATION_TIMEOUT_SECONDS
    while True:
        try:
            value = lifecycle._verify_resource_projection(
                authorization.subscriptionId,
                resource_type="Microsoft.App/jobs",
                name=MIGRATION_JOB,
                api_version=JOB_API_VERSION,
                projection=(
                    "{state:properties.provisioningState,"
                    "image:properties.template.containers[0].image,"
                    "command:properties.template.containers[0].command,"
                    "args:properties.template.containers[0].args}"
                ),
            )
        except lifecycle.LifecycleError:
            value = None
        if value == {
            "args": ["-c", _expected_migration_bootstrap_program()],
            "command": ["python"],
            "image": authorization.apiImageDigest,
            "state": "Succeeded",
        }:
            return
        if isinstance(value, dict) and value.get("state") in {"Canceled", "Failed"}:
            _fail("observability-bootstrap-migration-definition-failed")
        try:
            deployment_state = _deployment_state(authorization)
        except lifecycle.AzureCommandError:
            deployment_state = None
        if deployment_state in {"Canceled", "Failed"}:
            _fail("observability-bootstrap-deployment-terminal-failure")
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-migration-definition-unready")
        time.sleep(POLL_SECONDS)


def _deploy_owner_bootstrap(
    authorization: ObservabilityOperatorBootstrapAuthorization,
    *,
    expected_cost: int,
    maximum_cost: int,
    now_utc: datetime,
) -> None:
    try:
        parameters = deployment_parameters(
            stage="owner-bootstrap",
            ledger_integrity=authorization.authorizationIntegritySha256,
            repository_head=authorization.repositoryHead,
            cleanup_at_utc=authorization.cleanupDeadlineUtc,
            expected_cost=expected_cost,
            maximum_cost=maximum_cost,
            lifecycle_tags=_lifecycle_tags(authorization),
            runtime_config={"apiImageDigest": authorization.apiImageDigest},
            scanner_bridge_evidence=None,
            now=now_utc,
        )
    except ScannerBridgeDeploymentError as exc:
        _fail(str(exc))
    existing_state = _optional_deployment_state(authorization)
    if existing_state in {"Canceled", "Failed"}:
        _fail("observability-bootstrap-deployment-terminal-failure")
    if existing_state not in {None, "Running", "Succeeded"}:
        _fail("observability-bootstrap-deployment-state-invalid")
    if existing_state is None:
        with tempfile.TemporaryDirectory(
            prefix="mobius77-owner-bootstrap-"
        ) as directory:
            template = Path(directory) / "main.json"
            try:
                lifecycle._compile_template(template)
                with suppress(lifecycle.AzureCommandError):
                    lifecycle._run(
                        (
                            "az",
                            "deployment",
                            "sub",
                            "create",
                            "--name",
                            _deployment_name(authorization),
                            "--location",
                            STAGING_LOCATION,
                            "--subscription",
                            authorization.subscriptionId,
                            "--template-file",
                            str(template),
                            "--parameters",
                            *parameters,
                            "--no-wait",
                            "--only-show-errors",
                            "--output",
                            "none",
                        ),
                        timeout_seconds=lifecycle.DEPLOYMENT_TIMEOUT_SECONDS,
                    )
            except lifecycle.LifecycleError as exc:
                _fail(str(exc))
    _wait_migration_job_definition(authorization)


def _job_execution_rows(
    subscription_id: str, job_name: str
) -> list[dict[str, str | None]]:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--name",
            job_name,
            "--subscription",
            subscription_id,
            "--query",
            "[].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("observability-bootstrap-job-execution-inventory-malformed")
    rows: list[dict[str, str | None]] = []
    names: set[str] = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"end", "name", "start", "status"}
            or not isinstance(item.get("name"), str)
            or not str(item["name"]).startswith(f"{job_name}-")
            or item["name"] in names
            or not isinstance(item.get("status"), str)
            or (
                item.get("start") is not None and not isinstance(item.get("start"), str)
            )
            or (item.get("end") is not None and not isinstance(item.get("end"), str))
        ):
            _fail("observability-bootstrap-job-execution-inventory-malformed")
        names.add(str(item["name"]))
        rows.append(
            {
                "end": cast(str | None, item["end"]),
                "name": str(item["name"]),
                "start": cast(str | None, item["start"]),
                "status": str(item["status"]),
            }
        )
    return rows


def _start_or_reconcile_one_job(
    *,
    authorization: ObservabilityOperatorBootstrapAuthorization,
    job_name: str,
    claimed_at_utc: str,
) -> str:
    rows = _job_execution_rows(authorization.subscriptionId, job_name)
    claimed = _parse_utc(
        claimed_at_utc, "observability-bootstrap-receipt-claimed-time-invalid"
    )
    if any(row["status"] not in _TERMINAL_JOB_STATUSES for row in rows):
        _fail("observability-bootstrap-concurrent-job-execution-present")
    if any(row["status"] == "Succeeded" for row in rows):
        _fail("observability-bootstrap-prior-successful-job-execution-present")
    current: list[dict[str, str | None]] = []
    for row in rows:
        start_raw = row["start"]
        if start_raw is None:
            _fail("observability-bootstrap-job-start-time-unproved")
        if (
            _parse_azure_utc(
                start_raw, "observability-bootstrap-job-start-time-invalid"
            )
            >= claimed
        ):
            current.append(row)
    if len(current) > 1:
        _fail("observability-bootstrap-job-execution-ceiling-exceeded")
    if current:
        return cast(str, current[0]["name"])
    prior_names = {str(row["name"]) for row in rows}
    if not current:
        with suppress(lifecycle.AzureCommandError):
            lifecycle._run(
                (
                    "az",
                    "containerapp",
                    "job",
                    "start",
                    "--resource-group",
                    TARGET_RESOURCE_GROUP,
                    "--name",
                    job_name,
                    "--subscription",
                    authorization.subscriptionId,
                    "--output",
                    "none",
                    "--only-show-errors",
                )
            )
    deadline = time.monotonic() + START_RECONCILIATION_SECONDS
    while True:
        rows = _job_execution_rows(authorization.subscriptionId, job_name)
        if any(
            row["name"] in prior_names and row["status"] not in _TERMINAL_JOB_STATUSES
            for row in rows
        ):
            _fail("observability-bootstrap-prior-job-became-nonterminal")
        created = [row for row in rows if row["name"] not in prior_names]
        if len(created) == 1:
            start_raw = created[0]["start"]
            if start_raw is None:
                if time.monotonic() < deadline:
                    time.sleep(POLL_SECONDS)
                    continue
                _fail("observability-bootstrap-job-start-time-unproved")
            started = _parse_azure_utc(
                start_raw, "observability-bootstrap-job-start-time-invalid"
            )
            if started < claimed:
                _fail("observability-bootstrap-prior-job-execution-present")
            return cast(str, created[0]["name"])
        if len(created) > 1:
            _fail("observability-bootstrap-job-execution-ceiling-exceeded")
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-job-start-unproved")
        time.sleep(POLL_SECONDS)


def _migration_failure_code(subscription_id: str, execution_name: str) -> str:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "logs",
            "show",
            "--name",
            MIGRATION_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            subscription_id,
            "--execution",
            execution_name,
            "--container",
            "migration",
            "--tail",
            "100",
            "--only-show-errors",
        ),
        require_text=True,
    )
    if not isinstance(value, str):
        _fail("observability-bootstrap-migration-log-readback-invalid")
    observed = sorted(code for code in _MIGRATION_FAILURE_CODES if code in value)
    if len(observed) != 1:
        _fail("observability-bootstrap-migration-failure-unclassified")
    return observed[0]


def _verify_migration_success_marker(subscription_id: str, execution_name: str) -> None:
    replicas = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "replica",
            "list",
            "--name",
            MIGRATION_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            subscription_id,
            "--execution",
            execution_name,
            "--only-show-errors",
            "--output",
            "json",
        ),
        require_json=True,
    )
    if not isinstance(replicas, list):
        _fail("observability-bootstrap-migration-replica-readback-invalid")
    if not replicas:
        # Azure can retire a terminal job's replicas before its execution
        # record. Adoption still requires the exact unchanged job plus
        # authoritative PostgreSQL and private-API postconditions below.
        return
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "logs",
            "show",
            "--name",
            MIGRATION_JOB,
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--subscription",
            subscription_id,
            "--execution",
            execution_name,
            "--container",
            "migration",
            "--tail",
            "100",
            "--only-show-errors",
        ),
        require_text=True,
    )
    if (
        not isinstance(value, str)
        or value.count("observability-bootstrap-migration-succeeded") != 1
        or any(code in value for code in _MIGRATION_FAILURE_CODES)
    ):
        _fail("observability-bootstrap-migration-success-evidence-invalid")


def _migration_job_modified_at(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> datetime:
    value = lifecycle._verify_resource_projection(
        authorization.subscriptionId,
        resource_type="Microsoft.App/jobs",
        name=MIGRATION_JOB,
        api_version=JOB_API_VERSION,
        projection="{modified:systemData.lastModifiedAt,state:properties.provisioningState}",
    )
    if (
        set(value) != {"modified", "state"}
        or value.get("state") != "Succeeded"
        or not isinstance(value.get("modified"), str)
    ):
        _fail("observability-bootstrap-migration-definition-time-invalid")
    modified = str(value["modified"])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", modified):
        modified = f"{modified}+00:00"
    return _parse_azure_utc(
        modified, "observability-bootstrap-migration-definition-time-invalid"
    )


def _adopt_completed_prepare(
    authorization: ObservabilityOperatorBootstrapAuthorization,
    *,
    now_utc: datetime,
) -> tuple[str, str] | None:
    """Read-only adoption of one exact recent success after an ambiguous client stop."""

    rows = _job_execution_rows(authorization.subscriptionId, MIGRATION_JOB)
    succeeded = [row for row in rows if row["status"] == "Succeeded"]
    if not succeeded:
        return None
    if len(succeeded) != 1 or any(
        row["status"] not in _TERMINAL_JOB_STATUSES for row in rows
    ):
        _fail("observability-bootstrap-migration-success-adoption-ambiguous")
    row = succeeded[0]
    start_raw = row["start"]
    end_raw = row["end"]
    if start_raw is None or end_raw is None:
        _fail("observability-bootstrap-migration-success-time-invalid")
    started = _parse_azure_utc(
        start_raw, "observability-bootstrap-migration-success-time-invalid"
    )
    ended = _parse_azure_utc(
        end_raw, "observability-bootstrap-migration-success-time-invalid"
    )
    current = now_utc.astimezone(UTC)
    if (
        ended <= started
        or ended > current
        or current - ended > MAXIMUM_SUCCESS_ADOPTION_AGE
    ):
        _fail("observability-bootstrap-migration-success-time-invalid")
    _wait_migration_job_definition(authorization)
    if _migration_job_modified_at(authorization) > started:
        _fail("observability-bootstrap-migration-definition-mutated-after-success")
    execution = cast(str, row["name"])
    _verify_migration_success_marker(authorization.subscriptionId, execution)
    _verify_postgres(authorization)
    private_url = _verify_private_bootstrap_api(authorization)
    return execution, private_url


def _wait_job(
    *,
    subscription_id: str,
    job_name: str,
    execution_name: str,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        rows = _job_execution_rows(subscription_id, job_name)
        matches = [row for row in rows if row["name"] == execution_name]
        if len(matches) != 1 or any(
            row["name"] != execution_name
            and row["status"] not in _TERMINAL_JOB_STATUSES
            for row in rows
        ):
            _fail("observability-bootstrap-job-execution-drift")
        status = matches[0]["status"]
        if status == "Succeeded":
            return
        if status in {"Failed", "Stopped", "Cancelled"}:
            if job_name == MIGRATION_JOB:
                _fail(_migration_failure_code(subscription_id, execution_name))
            _fail("observability-bootstrap-job-terminal-failure")
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-job-timeout")
        time.sleep(POLL_SECONDS)


def _verify_postgres(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> None:
    value = lifecycle._verify_resource_projection(
        authorization.subscriptionId,
        resource_type="Microsoft.DBforPostgreSQL/flexibleServers",
        name="psql-mobius77-11564669",
        api_version=POSTGRES_API_VERSION,
        projection=(
            "{state:properties.state,version:properties.version,"
            "public:properties.network.publicNetworkAccess,"
            "highAvailability:properties.highAvailability.mode}"
        ),
    )
    if value != {
        "highAvailability": "ZoneRedundant",
        "public": "Disabled",
        "state": "Ready",
        "version": "17",
    }:
        _fail("observability-bootstrap-postgresql-drift")
    extension_allowlist = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (
                "https://management.azure.com"
                f"{authorization.postgresServerId}/configurations/azure.extensions"
                f"?api-version={POSTGRES_API_VERSION}"
            ),
            "--query",
            "{name:name,source:properties.source,value:properties.value}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if extension_allowlist != {
        "name": "azure.extensions",
        "source": "user-override",
        "value": "vector",
    }:
        _fail("observability-bootstrap-postgresql-extension-allowlist-drift")


def _postgres_administrator_completed_at(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> datetime:
    identity = lifecycle._verify_resource_projection(
        authorization.subscriptionId,
        resource_type="Microsoft.ManagedIdentity/userAssignedIdentities",
        name="id-mobius77-db-admin",
        api_version=MANAGED_IDENTITY_API_VERSION,
        projection="{id:id,name:name,principalId:properties.principalId}",
    )
    principal_id = identity.get("principalId")
    if (
        not isinstance(identity.get("id"), str)
        or str(identity["id"]).casefold()
        != authorization.databaseAdministratorIdentityId.casefold()
        or identity.get("name") != "id-mobius77-db-admin"
        or not isinstance(principal_id, str)
        or _UUID.fullmatch(principal_id) is None
    ):
        _fail("observability-bootstrap-database-administrator-identity-drift")
    administrator_id = f"{authorization.postgresServerId}/administrators/{principal_id}"
    administrator = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{administrator_id}?api-version={POSTGRES_API_VERSION}",
            "--query",
            (
                "{id:id,name:name,objectId:properties.objectId,"
                "principalName:properties.principalName,"
                "principalType:properties.principalType}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if (
        not isinstance(administrator, dict)
        or set(administrator)
        != {"id", "name", "objectId", "principalName", "principalType"}
        or not isinstance(administrator.get("id"), str)
        or str(administrator["id"]).casefold() != administrator_id.casefold()
        or administrator.get("name") != "id-mobius77-db-admin"
        or administrator.get("objectId") != principal_id
        or administrator.get("principalName") != "id-mobius77-db-admin"
        or administrator.get("principalType") != "ServicePrincipal"
    ):
        _fail("observability-bootstrap-database-administrator-drift")
    database_id = (
        f"{authorization.postgresServerId}/databases/{authorization.postgresDatabase}"
    )
    database = lifecycle._run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{database_id}?api-version={POSTGRES_API_VERSION}",
            "--query",
            "{id:id,name:name}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if (
        not isinstance(database, dict)
        or set(database) != {"id", "name"}
        or not isinstance(database.get("id"), str)
        or str(database["id"]).casefold() != database_id.casefold()
        or database.get("name") != authorization.postgresDatabase
    ):
        _fail("observability-bootstrap-postgresql-database-drift")
    operations = lifecycle._run(
        (
            "az",
            "deployment",
            "operation",
            "group",
            "list",
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--name",
            "mobius77-observability-owner-bootstrap-postgres",
            "--subscription",
            authorization.subscriptionId,
            "--query",
            (
                "[?properties.targetResource.resourceType=="
                "'Microsoft.DBforPostgreSQL/flexibleServers/administrators']."
                "{duration:properties.duration,name:properties.targetResource.resourceName,"
                "state:properties.provisioningState,timestamp:properties.timestamp}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected_name = f"psql-mobius77-11564669/{principal_id}"
    if (
        not isinstance(operations, list)
        or len(operations) != 1
        or not isinstance(operations[0], dict)
        or set(operations[0]) != {"duration", "name", "state", "timestamp"}
        or operations[0].get("name") != expected_name
        or operations[0].get("state") != "Succeeded"
        or not isinstance(operations[0].get("timestamp"), str)
        or not isinstance(operations[0].get("duration"), str)
    ):
        _fail("observability-bootstrap-database-administrator-operation-drift")
    started = _parse_azure_utc(
        str(operations[0]["timestamp"]),
        "observability-bootstrap-database-administrator-time-invalid",
    )
    authorized = _parse_utc(
        authorization.authorizedAtUtc,
        "observability-bootstrap-authorization-time-invalid",
    )
    if started < authorized:
        _fail("observability-bootstrap-database-administrator-operation-stale")
    duration = _parse_duration_seconds(
        str(operations[0]["duration"]),
        "observability-bootstrap-database-administrator-duration-invalid",
    )
    return started + timedelta(seconds=duration)


def _wait_postgres_administrator_propagation(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> None:
    deadline = time.monotonic() + APPLICATION_TIMEOUT_SECONDS
    while True:
        deployment_state = _deployment_state(authorization)
        if deployment_state in {"Canceled", "Failed"}:
            _fail("observability-bootstrap-deployment-terminal-failure")
        try:
            _verify_postgres(authorization)
            completed_at = _postgres_administrator_completed_at(authorization)
        except (lifecycle.LifecycleError, ObservabilityOperatorBootstrapExecutionError):
            if (
                deployment_state in {"Canceled", "Failed", "Succeeded"}
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(PROPAGATION_POLL_SECONDS)
            continue
        remaining = (
            completed_at
            + MINIMUM_DATABASE_ADMINISTRATOR_PROPAGATION
            - datetime.now(UTC)
        ).total_seconds()
        if remaining <= 0:
            return
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-database-administrator-propagation-timeout")
        time.sleep(min(PROPAGATION_POLL_SECONDS, remaining))


def _verify_private_bootstrap_api(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> str:
    value = lifecycle._verify_resource_projection(
        authorization.subscriptionId,
        resource_type="Microsoft.App/containerApps",
        name=API_CONTAINER_APP,
        api_version=CONTAINER_APP_API_VERSION,
        projection=(
            "{state:properties.provisioningState,external:properties.configuration.ingress.external,"
            "fqdn:properties.configuration.ingress.fqdn,mode:properties.configuration.activeRevisionsMode,"
            "image:properties.template.containers[0].image,"
            "secrets:properties.configuration.secrets[].name,"
            "env:properties.template.containers[0].env}"
        ),
    )
    if (
        set(value) != {"env", "external", "fqdn", "image", "mode", "secrets", "state"}
        or value.get("state") != "Succeeded"
        or value.get("external") is not False
        or value.get("mode") != "Single"
        or value.get("image") != authorization.apiImageDigest
        or value.get("secrets") != [SESSION_SECRET]
        or not isinstance(value.get("fqdn"), str)
        or not isinstance(value.get("env"), list)
    ):
        _fail("observability-bootstrap-private-api-drift")
    env = value["env"]
    assert isinstance(env, list)
    rows: dict[str, tuple[str | None, str | None]] = {}
    for item in env:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or set(item) - {"name", "secretRef", "value"}
            or item["name"] in rows
        ):
            _fail("observability-bootstrap-private-api-env-malformed")
        raw_value = item.get("value")
        raw_secret = item.get("secretRef")
        if raw_value is not None and not isinstance(raw_value, str):
            _fail("observability-bootstrap-private-api-env-malformed")
        if raw_secret is not None and not isinstance(raw_secret, str):
            _fail("observability-bootstrap-private-api-env-malformed")
        rows[str(item["name"])] = (
            raw_value,
            raw_secret,
        )
    required = {
        "OPENCANVAS_APP_MODE": ("development", None),
        "OPENCANVAS_AUTH_ENABLED": ("true", None),
        "OPENCANVAS_AUTH_TEST_BYPASS": ("false", None),
        "OPENCANVAS_DATABASE_EXPECTED_REVISION": (
            EXPECTED_DATABASE_REVISION,
            None,
        ),
        "OPENCANVAS_SESSION_SECRET": (None, SESSION_SECRET),
    }
    if any(rows.get(name) != expected for name, expected in required.items()):
        _fail("observability-bootstrap-private-api-env-drift")
    forbidden = {
        "OPENAI_API_KEY",
        "OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS",
        "OPENCANVAS_SCANNER_RESULT_SECRET",
        "OPENCANVAS_TELEMETRY_AUTH_TOKEN",
    }
    if forbidden & rows.keys():
        _fail("observability-bootstrap-forbidden-runtime-setting-present")
    revisions = lifecycle._run(
        (
            "az",
            "containerapp",
            "revision",
            "list",
            "--resource-group",
            TARGET_RESOURCE_GROUP,
            "--name",
            API_CONTAINER_APP,
            "--subscription",
            authorization.subscriptionId,
            "--query",
            (
                "[?properties.active].{name:name,health:properties.healthState,"
                "running:properties.runningState,state:properties.provisioningState}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(revisions, list) or len(revisions) != 1:
        _fail("observability-bootstrap-active-revision-cardinality-invalid")
    row = revisions[0]
    if (
        not isinstance(row, dict)
        or set(row) != {"health", "name", "running", "state"}
        or row.get("health") != "Healthy"
        or row.get("running") not in {"Running", "RunningAtMaxScale"}
        or row.get("state") != "Provisioned"
    ):
        _fail("observability-bootstrap-active-revision-unready")
    return f"https://{value['fqdn']}"


def _wait_private_bootstrap_api(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> str:
    deadline = time.monotonic() + APPLICATION_TIMEOUT_SECONDS
    while True:
        try:
            return _verify_private_bootstrap_api(authorization)
        except (lifecycle.LifecycleError, ObservabilityOperatorBootstrapExecutionError):
            if time.monotonic() >= deadline:
                _fail("observability-bootstrap-private-api-unready")
            time.sleep(POLL_SECONDS)


def _owner_readback_log(
    *,
    authorization: ObservabilityOperatorBootstrapAuthorization,
    execution_name: str,
) -> str:
    deadline = time.monotonic() + READBACK_TIMEOUT_SECONDS
    while True:
        try:
            output = lifecycle._run(
                (
                    "az",
                    "containerapp",
                    "job",
                    "logs",
                    "show",
                    "--resource-group",
                    TARGET_RESOURCE_GROUP,
                    "--name",
                    OWNER_READBACK_JOB,
                    "--execution",
                    execution_name,
                    "--container",
                    "owner-readback",
                    "--tail",
                    "100",
                    "--format",
                    "text",
                    "--subscription",
                    authorization.subscriptionId,
                    "--output",
                    "tsv",
                    "--only-show-errors",
                ),
                require_text=True,
            )
        except lifecycle.LifecycleError:
            output = None
        if isinstance(output, str):
            matches = _OWNER_MARKER.findall(output)
            if len(matches) == 1 and _UUID.fullmatch(matches[0]) is not None:
                return str(matches[0]).lower()
            if len(matches) > 1:
                _fail("observability-bootstrap-owner-readback-ambiguous")
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-owner-readback-evidence-absent")
        time.sleep(POLL_SECONDS)


def _delete_owner_readback_job(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> None:
    with suppress(lifecycle.AzureCommandError):
        lifecycle._run(
            (
                "az",
                "resource",
                "delete",
                "--ids",
                authorization.ownerReadbackJobId,
                "--api-version",
                JOB_API_VERSION,
                "--subscription",
                authorization.subscriptionId,
                "--only-show-errors",
                "--output",
                "none",
            )
        )
    deadline = time.monotonic() + START_RECONCILIATION_SECONDS
    while True:
        value = lifecycle._run(
            (
                "az",
                "resource",
                "list",
                "--resource-group",
                TARGET_RESOURCE_GROUP,
                "--subscription",
                authorization.subscriptionId,
                "--query",
                (f"[?type=='Microsoft.App/jobs' && name=='{OWNER_READBACK_JOB}'].id"),
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if value == []:
            return
        if time.monotonic() >= deadline:
            _fail("observability-bootstrap-owner-readback-job-residue-present")
        time.sleep(POLL_SECONDS)


def _prepare(
    *,
    authorization: ObservabilityOperatorBootstrapAuthorization,
    receipt_path: Path,
    receipt: dict[str, JsonValue],
    now_utc: datetime,
) -> dict[str, JsonValue]:
    if receipt.get("phase") in {"prepared", "owner-proved"}:
        return {
            "authorizationConsumed": True,
            "marker": "PRE_RUNTIME_OWNER_BOOTSTRAP_REQUIRED",
            "migrationExecutionNameSha256": hashlib.sha256(
                str(receipt["migrationExecutionName"]).encode()
            ).hexdigest(),
            "privateApplicationUrl": receipt["bootstrapPrivateApplicationUrl"],
            "readyForOwnerSignup": True,
        }
    _verify_repository_boundary(authorization)
    expected_cost, maximum_cost = _verify_cleanup_and_cost(
        authorization, now_utc=now_utc
    )
    _verify_session_secret_metadata(authorization)
    adopted = _adopt_completed_prepare(authorization, now_utc=now_utc)
    if adopted is not None:
        execution, private_url = adopted
        receipt.update(
            {
                "bootstrapPrivateApplicationUrl": private_url,
                "migrationExecutionName": execution,
                "migrationTerminalStatus": "Succeeded",
                "phase": "prepared",
            }
        )
        _replace_receipt(receipt_path, receipt)
        return {
            "authorizationConsumed": True,
            "marker": "PRE_RUNTIME_OWNER_BOOTSTRAP_REQUIRED",
            "migrationExecutionNameSha256": hashlib.sha256(
                execution.encode()
            ).hexdigest(),
            "privateApplicationUrl": private_url,
            "readyForOwnerSignup": True,
        }
    _deploy_owner_bootstrap(
        authorization,
        expected_cost=expected_cost,
        maximum_cost=maximum_cost,
        now_utc=now_utc,
    )
    _wait_postgres_administrator_propagation(authorization)
    claimed_at = receipt.get("claimedAtUtc")
    if not isinstance(claimed_at, str):
        _fail("observability-bootstrap-receipt-invalid")
    execution = _start_or_reconcile_one_job(
        authorization=authorization,
        job_name=MIGRATION_JOB,
        claimed_at_utc=claimed_at,
    )
    _wait_job(
        subscription_id=authorization.subscriptionId,
        job_name=MIGRATION_JOB,
        execution_name=execution,
        timeout_seconds=MIGRATION_TIMEOUT_SECONDS,
    )
    _verify_postgres(authorization)
    deployment = _wait_deployment_readback(authorization)
    private_url = _wait_private_bootstrap_api(authorization)
    if private_url != deployment.get("private-application-url"):
        _fail("observability-bootstrap-private-url-drift")
    receipt.update(
        {
            "bootstrapPrivateApplicationUrl": private_url,
            "migrationExecutionName": execution,
            "migrationTerminalStatus": "Succeeded",
            "phase": "prepared",
        }
    )
    _replace_receipt(receipt_path, receipt)
    return {
        "authorizationConsumed": True,
        "marker": "PRE_RUNTIME_OWNER_BOOTSTRAP_REQUIRED",
        "migrationExecutionNameSha256": hashlib.sha256(execution.encode()).hexdigest(),
        "privateApplicationUrl": private_url,
        "readyForOwnerSignup": True,
    }


def _read_owner(
    *,
    authorization: ObservabilityOperatorBootstrapAuthorization,
    receipt_path: Path,
    receipt: dict[str, JsonValue],
    now_utc: datetime,
) -> dict[str, JsonValue]:
    if receipt.get("phase") == "owner-proved":
        return {
            "authorizationConsumed": True,
            "marker": "GENUINE_OWNER_APPLICATION_UUID_PROVED",
            "ownerReadbackJobDeleted": receipt["ownerReadbackJobDeleted"],
            "ownerUserId": receipt["ownerUserId"],
        }
    if receipt.get("phase") != "prepared":
        _fail("observability-bootstrap-owner-readback-prerequisite-missing")
    _verify_repository_boundary(authorization)
    _verify_cleanup_and_cost(authorization, now_utc=now_utc)
    _verify_private_bootstrap_api(authorization)
    claimed_at = receipt.get("claimedAtUtc")
    if not isinstance(claimed_at, str):
        _fail("observability-bootstrap-receipt-invalid")
    execution = _start_or_reconcile_one_job(
        authorization=authorization,
        job_name=OWNER_READBACK_JOB,
        claimed_at_utc=claimed_at,
    )
    _wait_job(
        subscription_id=authorization.subscriptionId,
        job_name=OWNER_READBACK_JOB,
        execution_name=execution,
        timeout_seconds=READBACK_TIMEOUT_SECONDS,
    )
    owner_user_id = _owner_readback_log(
        authorization=authorization,
        execution_name=execution,
    )
    _delete_owner_readback_job(authorization)
    receipt.update(
        {
            "ownerReadbackExecutionName": execution,
            "ownerReadbackJobDeleted": True,
            "ownerUserId": owner_user_id,
            "phase": "owner-proved",
        }
    )
    _replace_receipt(receipt_path, receipt)
    return {
        "authorizationConsumed": True,
        "marker": "GENUINE_OWNER_APPLICATION_UUID_PROVED",
        "ownerReadbackJobDeleted": True,
        "ownerUserId": owner_user_id,
    }


def execute_observability_operator_bootstrap(
    authorization: ObservabilityOperatorBootstrapAuthorization,
    *,
    receipt_directory: Path,
    phase: Literal["prepare", "read-owner"],
    now_utc: datetime,
) -> dict[str, JsonValue]:
    """Consume one narrow authority and execute or reconcile its requested phase."""

    try:
        validate_observability_operator_bootstrap_authorization(
            authorization,
            expected_repository_head=authorization.repositoryHead,
            now_utc=now_utc,
        )
    except ValueError as exc:
        _fail(str(exc))
    path = _receipt_path(receipt_directory)
    if not path.exists():
        if phase != "prepare":
            _fail("observability-bootstrap-authorization-not-consumed")
        _write_new_receipt(path, _new_receipt(authorization, now_utc=now_utc))
    receipt = _receipt_for_authorization(path, authorization)
    if phase == "prepare":
        return _prepare(
            authorization=authorization,
            receipt_path=path,
            receipt=receipt,
            now_utc=now_utc,
        )
    return _read_owner(
        authorization=authorization,
        receipt_path=path,
        receipt=receipt,
        now_utc=now_utc,
    )


def reconcile_completed_bootstrap_migration(
    *,
    receipt_directory: Path,
    repository_head: str,
    subscription_id: str,
) -> str | None:
    """Adopt the exact successful bootstrap migration without a second execution."""

    if (
        _SHA40.fullmatch(repository_head) is None
        or _UUID.fullmatch(subscription_id) is None
    ):
        _fail("observability-bootstrap-migration-adoption-input-invalid")
    path = _receipt_path(receipt_directory)
    if not path.is_file():
        return None
    receipt = _load_receipt(path)
    execution = receipt.get("migrationExecutionName")
    current_owner_proved = not (
        receipt.get("phase") != "owner-proved"
        or receipt.get("repositoryHead") != repository_head
        or receipt.get("subscriptionId") != subscription_id
        or receipt.get("migrationTerminalStatus") != "Succeeded"
        or not isinstance(execution, str)
        or not execution.startswith(f"{MIGRATION_JOB}-")
        or receipt.get("ownerReadbackJobDeleted") is not True
        or _UUID.fullmatch(str(receipt.get("ownerUserId", ""))) is None
    )
    exact_retained_prepared = not (
        repository_head == RETAINED_MIGRATION_SOURCE_HEAD
        or receipt.get("phase") != "prepared"
        or receipt.get("repositoryHead") != RETAINED_MIGRATION_SOURCE_HEAD
        or receipt.get("subscriptionId") != subscription_id
        or receipt.get("authorizationId") != RETAINED_MIGRATION_AUTHORIZATION_ID
        or receipt.get("authorizationIntegritySha256")
        != RETAINED_MIGRATION_AUTHORIZATION_INTEGRITY
        or receipt.get("receiptIntegritySha256") != RETAINED_MIGRATION_RECEIPT_INTEGRITY
        or receipt.get("claimedAtUtc") != RETAINED_MIGRATION_CLAIMED_AT
        or receipt.get("bootstrapPrivateApplicationUrl")
        != RETAINED_MIGRATION_PRIVATE_URL
        or execution != RETAINED_MIGRATION_EXECUTION
        or receipt.get("migrationTerminalStatus") != "Succeeded"
        or receipt.get("ownerReadbackExecutionName") is not None
        or receipt.get("ownerReadbackJobDeleted") is not False
        or receipt.get("ownerUserId") is not None
    )
    if not current_owner_proved and not exact_retained_prepared:
        _fail("observability-bootstrap-migration-adoption-receipt-invalid")
    if not isinstance(execution, str):
        _fail("observability-bootstrap-migration-adoption-receipt-invalid")
    rows = _job_execution_rows(subscription_id, MIGRATION_JOB)
    matches = [row for row in rows if row["name"] == execution]
    if (
        len(matches) != 1
        or matches[0]["status"] != "Succeeded"
        or any(
            row["name"] != execution
            and row["status"] not in {"Cancelled", "Failed", "Stopped"}
            for row in rows
        )
    ):
        _fail("observability-bootstrap-migration-adoption-readback-invalid")
    return execution


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--receipt-directory", type=Path, required=True)
    parser.add_argument("--phase", choices=("prepare", "read-owner"), required=True)
    parser.add_argument("--now-utc")
    args = parser.parse_args(argv)
    authorization = load_observability_operator_bootstrap_authorization(
        args.authorization
    )
    now = (
        datetime.now(UTC).replace(microsecond=0)
        if args.now_utc is None
        else _parse_utc(
            args.now_utc, "observability-bootstrap-authorization-time-invalid"
        )
    )
    result = execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=args.receipt_directory,
        phase=cast(Literal["prepare", "read-owner"], args.phase),
        now_utc=now,
    )
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
