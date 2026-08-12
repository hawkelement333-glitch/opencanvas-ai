"""Production Azure adapter for terminal Milestone 7.7 lifecycle stages.

The existing managed-binding entry point owns authorization, account binding,
operation receipts, and attribution.  This module keeps the terminal Azure
readback and mutation stages below the protected bundle's per-file size ceiling
while reusing that entry point's established primitives.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    load_json,
)
from preflight.milestone_7_7 import terminal_lifecycle

_PROOF_ROLE_DEFINITION = "7d78ed8f-4b48-4e74-bb95-f0fcfe811897"


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_stage_predecessor(
    *,
    stage: str,
    ledger: Mapping[str, JsonValue],
    receipt_directory: Path,
) -> terminal_lifecycle.TerminalStageEvidence:
    predecessor = terminal_lifecycle.STAGE_PREDECESSOR[stage]
    if predecessor is None:
        lifecycle._fail("terminal-stage-predecessor-invalid")
    path = terminal_lifecycle.stage_evidence_path(receipt_directory, predecessor)
    if not path.is_file():
        lifecycle._fail("terminal-stage-predecessor-missing")
    try:
        return terminal_lifecycle.load_stage_evidence(
            path,
            expected_stage=predecessor,
            repository_head=str(ledger["repositoryHead"]),
            ledger_integrity_sha256=lifecycle._ledger_integrity(ledger),
        )
    except OSError:
        lifecycle._fail("terminal-stage-predecessor-unreadable")
    except terminal_lifecycle.TerminalLifecycleError as exc:
        lifecycle._fail(str(exc))


def container_app_revision_ready(subscription_id: str, app_name: str) -> str:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        value = lifecycle._run(
            (
                "az",
                "resource",
                "show",
                "--resource-group",
                lifecycle.TARGET_GROUP,
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
            lifecycle._fail("container-app-readiness-output-malformed")
        latest = value["latest"]
        ready = value["ready"]
        state = value["state"]
        if (
            state == "Succeeded"
            and isinstance(latest, str)
            and latest
            and ready == latest
        ):
            revision = lifecycle._run(
                (
                    "az",
                    "containerapp",
                    "revision",
                    "show",
                    "--resource-group",
                    lifecycle.TARGET_GROUP,
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
                return latest
            if isinstance(revision, dict) and (
                revision.get("health") == "Unhealthy"
                or revision.get("provisioning") in {"Canceled", "Failed"}
                or revision.get("running") in {"ActivationFailed", "Degraded", "Failed"}
            ):
                lifecycle._fail("container-app-revision-failed")
        if state in {"Canceled", "Failed"}:
            lifecycle._fail("container-app-revision-failed")
        time.sleep(5.0)
    lifecycle._fail("container-app-readiness-timeout")


def _migration_execution_rows(subscription_id: str) -> list[dict[str, str]]:
    value = lifecycle._run(
        (
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--resource-group",
            lifecycle.TARGET_GROUP,
            "--name",
            "caj-mobius77-migration",
            "--subscription",
            subscription_id,
            "--query",
            "[].{name:name,status:properties.status}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        lifecycle._fail("migration-job-execution-inventory-malformed")
    rows: list[dict[str, str]] = []
    names: set[str] = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "status"}
            or not isinstance(item.get("name"), str)
            or not str(item["name"]).startswith("caj-mobius77-migration-")
            or not isinstance(item.get("status"), str)
            or item["name"] in names
        ):
            lifecycle._fail("migration-job-execution-inventory-malformed")
        name = str(item["name"])
        names.add(name)
        rows.append({"name": name, "status": str(item["status"])})
    return rows


def migration_job_ready(subscription_id: str) -> str:
    if _migration_execution_rows(subscription_id):
        lifecycle._fail("migration-job-duplicate-execution-present")
    requested_name: str | None = None
    try:
        started = lifecycle._run(
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                lifecycle.TARGET_GROUP,
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
        if isinstance(started, dict) and set(started) == {"name"}:
            candidate = started["name"]
            if isinstance(candidate, str) and candidate.startswith(
                "caj-mobius77-migration-"
            ):
                requested_name = candidate
    except lifecycle.AzureCommandError:
        requested_name = None
    start_deadline = time.monotonic() + 120.0
    while True:
        rows = _migration_execution_rows(subscription_id)
        if len(rows) == 1 and (
            requested_name is None or rows[0]["name"] == requested_name
        ):
            execution_name = rows[0]["name"]
            break
        if len(rows) > 1:
            lifecycle._fail("migration-job-duplicate-execution-created")
        if time.monotonic() >= start_deadline:
            lifecycle._fail("migration-job-start-unproved")
        time.sleep(5.0)
    deadline = time.monotonic() + 1800.0
    while time.monotonic() < deadline:
        execution = lifecycle._run(
            (
                "az",
                "containerapp",
                "job",
                "execution",
                "show",
                "--resource-group",
                lifecycle.TARGET_GROUP,
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
            lifecycle._fail("migration-job-status-output-malformed")
        if execution.get("name") != execution_name:
            lifecycle._fail("migration-job-status-output-malformed")
        if execution.get("status") == "Succeeded":
            return execution_name
        if execution.get("status") in {"Canceled", "Failed"}:
            lifecycle._fail("migration-job-failed")
        time.sleep(5.0)
    lifecycle._fail("migration-job-timeout")


def private_revision_ready(subscription_id: str) -> dict[str, str]:
    return {
        app_name: container_app_revision_ready(subscription_id, app_name)
        for app_name in (
            "ca-mobius77-telemetry",
            "ca-mobius77-worker",
            "ca-mobius77-api",
        )
    }


def managed_secret_states(subscription_id: str) -> dict[str, bool]:
    rows = lifecycle._run(
        (
            "az",
            "keyvault",
            "secret",
            "list",
            "--vault-name",
            lifecycle.KEY_VAULT,
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
        lifecycle._fail("managed-secret-presence-or-state-unproved")
    result: dict[str, bool] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"enabled", "name"}
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("enabled"), bool)
        ):
            lifecycle._fail("managed-secret-presence-or-state-unproved")
        name = str(row["name"])
        if name in result:
            lifecycle._fail("managed-secret-presence-or-state-unproved")
        result[name] = bool(row["enabled"])
    return result


def _post_secret_deployment_outputs(
    *,
    subscription_id: str,
    ledger: Mapping[str, JsonValue],
    immutable_image_digest: str,
    scanner_evidence_integrity: str,
) -> None:
    value = lifecycle._run(
        (
            "az",
            "deployment",
            "sub",
            "show",
            "--name",
            lifecycle._deployment_name("post-secret", ledger),
            "--subscription",
            subscription_id,
            "--query",
            (
                "{state:properties.provisioningState,"
                "stage:properties.outputs.deploymentStage.value,"
                "enabled:properties.outputs.deploymentEnabled.value,"
                "postgres:properties.outputs.postgresServerFqdn.value,"
                "redis:properties.outputs.redisHostName.value,"
                "redisPort:properties.outputs.redisPort.value,"
                "telemetry:properties.outputs.telemetryContainerAppId.value,"
                "migrationName:properties.outputs.migrationJobName.value,"
                "migrationId:properties.outputs.migrationJobResourceId.value,"
                "bridgeResolved:properties.outputs.scannerResultBridgeResolved.value,"
                "bridgeIntegrity:properties.outputs.scannerResultBridgeEvidenceIntegrity.value,"
                "image:properties.outputs.apiImageDigest.value}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, dict) or set(value) != {
        "bridgeIntegrity",
        "bridgeResolved",
        "enabled",
        "image",
        "migrationId",
        "migrationName",
        "postgres",
        "redis",
        "redisPort",
        "stage",
        "state",
        "telemetry",
    }:
        lifecycle._fail("post-secret-deployment-output-malformed")
    target_scope = lifecycle._scope(
        subscription_id, f"/resourceGroups/{lifecycle.TARGET_GROUP}"
    )
    expected_migration_id = (
        f"{target_scope}/providers/Microsoft.App/jobs/caj-mobius77-migration"
    )
    expected_telemetry_id = (
        f"{target_scope}/providers/Microsoft.App/containerApps/ca-mobius77-telemetry"
    )
    if (
        value.get("state") != "Succeeded"
        or value.get("stage") != "post-secret"
        or value.get("enabled") is not True
        or value.get("bridgeResolved") is not True
        or value.get("bridgeIntegrity") != scanner_evidence_integrity
        or value.get("image") != immutable_image_digest
        or value.get("migrationName") != "caj-mobius77-migration"
        or str(value.get("migrationId", "")).casefold()
        != expected_migration_id.casefold()
        or str(value.get("telemetry", "")).casefold()
        != expected_telemetry_id.casefold()
        or not isinstance(value.get("postgres"), str)
        or not str(value["postgres"])
        .casefold()
        .endswith(".postgres.database.azure.com")
        or not isinstance(value.get("redis"), str)
        or not str(value["redis"]).casefold().endswith(".redis.azure.net")
        or value.get("redisPort") != 10000
    ):
        lifecycle._fail("post-secret-deployment-output-drift")


def _runtime_definition(
    *,
    subscription_id: str,
    resource_type: str,
    name: str,
    api_version: str,
    immutable_image_digest: str,
) -> None:
    value = lifecycle._verify_resource_projection(
        subscription_id,
        resource_type=resource_type,
        name=name,
        api_version=api_version,
        projection=(
            "{state:properties.provisioningState,"
            "image:properties.template.containers[0].image,"
            "environment:properties.environmentId,identity:identity.type}"
        ),
    )
    expected_environment = lifecycle._scope(
        subscription_id,
        f"/resourceGroups/{lifecycle.TARGET_GROUP}/providers/Microsoft.App/"
        "managedEnvironments/cae-mobius77-staging",
    )
    if (
        set(value) != {"environment", "identity", "image", "state"}
        or value.get("state") != "Succeeded"
        or value.get("image") != immutable_image_digest
        or str(value.get("environment", "")).casefold()
        != expected_environment.casefold()
        or value.get("identity") != "UserAssigned"
    ):
        lifecycle._fail("post-secret-runtime-definition-drift")


def verify_post_secret_foundation(
    *,
    subscription_id: str,
    ledger: dict[str, JsonValue],
    cleanup_at: datetime,
    immutable_image_digest: str,
    scanner_evidence_integrity: str,
) -> None:
    """Reconcile every post-secret foundation component authoritatively."""

    _post_secret_deployment_outputs(
        subscription_id=subscription_id,
        ledger=ledger,
        immutable_image_digest=immutable_image_digest,
        scanner_evidence_integrity=scanner_evidence_integrity,
    )
    postgres = lifecycle._verify_resource_projection(
        subscription_id,
        resource_type="Microsoft.DBforPostgreSQL/flexibleServers",
        name="psql-mobius77-11564669",
        api_version="2024-08-01",
        projection=(
            "{state:properties.state,version:properties.version,"
            "public:properties.network.publicNetworkAccess,"
            "highAvailability:properties.highAvailability.mode}"
        ),
    )
    if postgres != {
        "highAvailability": "ZoneRedundant",
        "public": "Disabled",
        "state": "Ready",
        "version": "17",
    }:
        lifecycle._fail("post-secret-postgresql-drift")
    redis = lifecycle._verify_resource_projection(
        subscription_id,
        resource_type="Microsoft.Cache/redisEnterprise",
        name="redis-mobius77-11564669",
        api_version="2026-05-01-preview",
        projection=(
            "{state:properties.provisioningState,"
            "public:properties.publicNetworkAccess,sku:sku.name,"
            "minimumTls:properties.minimumTlsVersion}"
        ),
    )
    if redis != {
        "minimumTls": "1.2",
        "public": "Disabled",
        "sku": "Balanced_B0",
        "state": "Succeeded",
    }:
        lifecycle._fail("post-secret-redis-drift")
    lifecycle._verify_container_apps_infrastructure(
        subscription_id=subscription_id,
        ledger=ledger,
        cleanup_at=cleanup_at,
        allow_prior_binding_with_changed_inputs=True,
    )
    lifecycle._verify_container_apps_private_dns(subscription_id)
    for app_name in (
        "ca-mobius77-api",
        "ca-mobius77-worker",
        "ca-mobius77-telemetry",
    ):
        _runtime_definition(
            subscription_id=subscription_id,
            resource_type="Microsoft.App/containerApps",
            name=app_name,
            api_version="2026-01-01",
            immutable_image_digest=immutable_image_digest,
        )
    _runtime_definition(
        subscription_id=subscription_id,
        resource_type="Microsoft.App/jobs",
        name="caj-mobius77-migration",
        api_version="2025-01-01",
        immutable_image_digest=immutable_image_digest,
    )


def migration_stage(
    *,
    ledger: Mapping[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    _require_stage_predecessor(
        stage="migration-execution",
        ledger=ledger,
        receipt_directory=receipt_directory,
    )
    state_path = lifecycle._state_path(receipt_directory)
    state = lifecycle._read_current_transient_state(state_path, ledger=ledger)
    if state.get("resumableCheckpoint") != "migration-execution":
        lifecycle._fail("migration-stage-prerequisite-missing")
    from infra.milestone_7_7 import observability_operator_bootstrap_adapter

    repository_head = ledger.get("repositoryHead")
    if not isinstance(repository_head, str):
        lifecycle._fail("migration-stage-repository-head-missing")
    try:
        execution_name = observability_operator_bootstrap_adapter.reconcile_completed_bootstrap_migration(
            receipt_directory=receipt_directory,
            repository_head=repository_head,
            subscription_id=subscription_id,
        )
    except observability_operator_bootstrap_adapter.ObservabilityOperatorBootstrapExecutionError as exc:
        lifecycle._fail(str(exc))
    if execution_name is None:
        execution_name = migration_job_ready(subscription_id)
    state["lastCompletedStage"] = "migration-execution"
    state["resumableCheckpoint"] = "readiness-validation"
    lifecycle._replace_state(state_path, state)
    return {
        "executionNameSha256": hashlib.sha256(execution_name.encode()).hexdigest(),
        "expectedRevision": terminal_lifecycle.MIGRATION_REVISION,
        "singleExecution": True,
        "terminalStatus": "Succeeded",
    }


def readiness_stage(
    *,
    ledger: Mapping[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    _require_stage_predecessor(
        stage="readiness-validation",
        ledger=ledger,
        receipt_directory=receipt_directory,
    )
    state_path = lifecycle._state_path(receipt_directory)
    state = lifecycle._read_current_transient_state(state_path, ledger=ledger)
    if state.get("resumableCheckpoint") != "readiness-validation":
        lifecycle._fail("readiness-stage-prerequisite-missing")
    revisions = private_revision_ready(subscription_id)
    image_digest = lifecycle._reconcile_published_api_image(ledger=ledger, state=state)
    state["lastCompletedStage"] = "readiness-validation"
    state["resumableCheckpoint"] = "live-validation"
    lifecycle._replace_state(state_path, state)
    return {
        "apiRevisionSha256": hashlib.sha256(
            revisions["ca-mobius77-api"].encode()
        ).hexdigest(),
        "immutableImageDigest": image_digest,
        "privateIngressOnly": True,
        "telemetryRevisionSha256": hashlib.sha256(
            revisions["ca-mobius77-telemetry"].encode()
        ).hexdigest(),
        "workerRevisionSha256": hashlib.sha256(
            revisions["ca-mobius77-worker"].encode()
        ).hexdigest(),
    }


def _private_https_json(
    hostname: str, path: str, *, expected_address: str
) -> tuple[dict[str, JsonValue], str, str]:
    if (
        re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{1,251}[a-z0-9])?", hostname) is None
        or not path.startswith("/")
        or "?" in path
        or "#" in path
    ):
        lifecycle._fail("live-validation-endpoint-invalid")
    try:
        resolved = socket.getaddrinfo(
            hostname,
            443,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        lifecycle._fail("live-validation-private-dns-unavailable")
    addresses = sorted(
        {str(item[4][0]) for item in resolved if isinstance(item[4], tuple) and item[4]}
    )
    approved = ipaddress.ip_network("10.77.0.0/20")
    try:
        parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError:
        lifecycle._fail("live-validation-private-dns-malformed")
    if (
        not parsed
        or any(
            not isinstance(address, ipaddress.IPv4Address) or address not in approved
            for address in parsed
        )
        or addresses != [expected_address]
    ):
        lifecycle._fail("live-validation-private-dns-unproved")
    connection = http.client.HTTPSConnection(
        hostname,
        443,
        timeout=15.0,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/json",
                "User-Agent": "mobius77-lifecycle/1",
            },
        )
        response = connection.getresponse()
        body = response.read(16_385)
        tls_socket = connection.sock
        tls_raw = tls_socket.version() if tls_socket is not None else None
    except (OSError, ssl.SSLError, http.client.HTTPException):
        lifecycle._fail("live-validation-private-tls-or-http-failed")
    finally:
        connection.close()
    if response.status != 200 or len(body) > 16_384:
        lifecycle._fail("live-validation-http-status-invalid")
    try:
        value = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        lifecycle._fail("live-validation-response-malformed")
    if not isinstance(value, dict):
        lifecycle._fail("live-validation-response-malformed")
    tls_versions = {"TLSv1.2": "TLS1_2", "TLSv1.3": "TLS1_3"}
    tls_version = None if tls_raw is None else tls_versions.get(tls_raw)
    if tls_version is None:
        lifecycle._fail("live-validation-tls-version-invalid")
    address_integrity = hashlib.sha256(
        b"solarplexus-mobius/milestone-7.7/live-private-addresses/v1\0"
        + canonical_bytes(cast(JsonValue, addresses))
    ).hexdigest()
    return cast(dict[str, JsonValue], value), address_integrity, tls_version


def live_validation_sample(
    *,
    ledger: Mapping[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> terminal_lifecycle.LiveValidationSample:
    state = lifecycle._read_current_transient_state(
        lifecycle._state_path(receipt_directory), ledger=ledger
    )
    cleanup_raw = state.get("cleanupAtUtc")
    if not isinstance(cleanup_raw, str):
        lifecycle._fail("live-validation-cleanup-deadline-missing")
    try:
        cleanup_at = datetime.strptime(cleanup_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        lifecycle._fail("live-validation-cleanup-deadline-invalid")
    if lifecycle._utc_now() >= cleanup_at - lifecycle.MINIMUM_CLEANUP_RESERVE:
        lifecycle._fail("live-validation-cleanup-reserve-active")
    lifecycle._verify_cleanup_control(subscription_id, cleanup_at)
    revisions = private_revision_ready(subscription_id)
    image_digest = lifecycle._reconcile_published_api_image(ledger=ledger, state=state)
    domain, static_ip = lifecycle._container_apps_private_dns_projection(
        subscription_id
    )
    api_hostname = f"ca-mobius77-api.{domain}"
    telemetry_hostname = f"ca-mobius77-telemetry.{domain}"
    live, address_integrity, tls_version = _private_https_json(
        api_hostname, "/api/v1/health/live", expected_address=static_ip
    )
    ready, ready_addresses, ready_tls = _private_https_json(
        api_hostname, "/api/v1/health/ready", expected_address=static_ip
    )
    worker, worker_addresses, worker_tls = _private_https_json(
        api_hostname, "/api/v1/health/worker", expected_address=static_ip
    )
    runtime, runtime_addresses, runtime_tls = _private_https_json(
        api_hostname, "/api/v1/health/runtime", expected_address=static_ip
    )
    telemetry, telemetry_addresses, telemetry_tls = _private_https_json(
        telemetry_hostname, "/health", expected_address=static_ip
    )
    if (
        live != {"service": "opencanvas-api", "status": "ok"}
        or ready != {"service": "opencanvas-api", "status": "ready"}
        or worker != {"service": "opencanvas-worker", "status": "ready"}
        or runtime.get("mode") != "live"
        or runtime.get("appMode") != "staging"
        or runtime.get("externalAiEnabled") is not True
        or telemetry != {"status": "healthy"}
        or len(
            {
                address_integrity,
                ready_addresses,
                worker_addresses,
                runtime_addresses,
                telemetry_addresses,
            }
        )
        != 1
        or {tls_version, ready_tls, worker_tls, runtime_tls, telemetry_tls}
        - {"TLS1_2", "TLS1_3"}
    ):
        lifecycle._fail("live-validation-health-contract-failed")
    _expected_cost, maximum_cost = lifecycle._verified_cost()
    runtime_graph = hashlib.sha256(
        b"solarplexus-mobius/milestone-7.7/live-runtime-graph/v1\0"
        + canonical_bytes(
            cast(
                JsonValue,
                {"domain": domain, "image": image_digest, "revisions": revisions},
            )
        )
    ).hexdigest()
    temporary_absent = (
        state.get("temporaryKeyVaultAssignmentId") is None
        and state.get("temporaryRegistryAssignmentId") is None
    )
    sample = terminal_lifecycle.LiveValidationSample(
        observed_at_utc=_format_utc(lifecycle._utc_now()),
        runtime_graph_integrity_sha256=runtime_graph,
        private_address_sha256=hashlib.sha256(
            (address_integrity + telemetry_addresses).encode("ascii")
        ).hexdigest(),
        private_dns_proved=True,
        tls_version=(
            "TLS1_2"
            if "TLS1_2"
            in {tls_version, ready_tls, worker_tls, runtime_tls, telemetry_tls}
            else "TLS1_3"
        ),
        api_live=True,
        api_ready=True,
        worker_ready=True,
        telemetry_ready=True,
        cleanup_armed=True,
        cleanup_deadline_utc=_format_utc(cleanup_at),
        maximum_cost_usd_cents=maximum_cost,
        temporary_authority_absent=temporary_absent,
    )
    return terminal_lifecycle.validate_live_sample(sample)


def live_validation_stage(
    *,
    ledger: Mapping[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    _require_stage_predecessor(
        stage="live-validation",
        ledger=ledger,
        receipt_directory=receipt_directory,
    )
    state_path = lifecycle._state_path(receipt_directory)
    state = lifecycle._read_current_transient_state(state_path, ledger=ledger)
    if state.get("resumableCheckpoint") != "live-validation":
        lifecycle._fail("live-validation-stage-prerequisite-missing")
    sample = live_validation_sample(
        ledger=ledger,
        subscription_id=subscription_id,
        receipt_directory=receipt_directory,
    )
    state["lastCompletedStage"] = "live-validation"
    state["resumableCheckpoint"] = "soak"
    lifecycle._replace_state(state_path, state)
    return {
        "apiLive": sample.api_live,
        "apiReady": sample.api_ready,
        "cleanupArmed": sample.cleanup_armed,
        "cleanupDeadlineUtc": sample.cleanup_deadline_utc,
        "maximumCostUsdCents": sample.maximum_cost_usd_cents,
        "privateAddressSha256": sample.private_address_sha256,
        "privateDnsProved": sample.private_dns_proved,
        "runtimeGraphIntegritySha256": sample.runtime_graph_integrity_sha256,
        "runtimeMode": "live-staging",
        "telemetryReady": sample.telemetry_ready,
        "temporaryAuthorityAbsent": sample.temporary_authority_absent,
        "tlsVersion": sample.tls_version,
        "workerReady": sample.worker_ready,
    }


def soak_stage(
    *,
    ledger: Mapping[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    _require_stage_predecessor(
        stage="soak",
        ledger=ledger,
        receipt_directory=receipt_directory,
    )
    state_path = lifecycle._state_path(receipt_directory)
    state = lifecycle._read_current_transient_state(state_path, ledger=ledger)
    if state.get("resumableCheckpoint") != "soak":
        lifecycle._fail("soak-stage-prerequisite-missing")
    cleanup_raw = state.get("cleanupAtUtc")
    if not isinstance(cleanup_raw, str):
        lifecycle._fail("soak-cleanup-deadline-missing")
    try:
        cleanup_at = datetime.strptime(cleanup_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        lifecycle._fail("soak-cleanup-deadline-invalid")
    progress_path = receipt_directory / terminal_lifecycle.SOAK_PROGRESS_FILE
    result = terminal_lifecycle.run_uninterrupted_soak(
        repository_head=str(ledger["repositoryHead"]),
        ledger_integrity_sha256=lifecycle._ledger_integrity(ledger),
        cleanup_deadline_utc=cleanup_at,
        sample=lambda: live_validation_sample(
            ledger=ledger,
            subscription_id=subscription_id,
            receipt_directory=receipt_directory,
        ),
        clock=lifecycle._utc_now,
        monotonic=time.monotonic,
        sleep=time.sleep,
        progress=lambda value: terminal_lifecycle.write_soak_progress(
            progress_path, value
        ),
    )
    state["lastCompletedStage"] = "soak"
    state["resumableCheckpoint"] = "successful-closeout"
    lifecycle._replace_state(state_path, state)
    return result.payload


def _exact_ephemeral_identity_count(
    *, ledger: Mapping[str, JsonValue], identity_prefix: str
) -> int:
    ledger_integrity = lifecycle._ledger_integrity(ledger)
    display_name = f"{identity_prefix}-{ledger_integrity[:12]}"
    applications = lifecycle._run(
        (
            "az",
            "ad",
            "app",
            "list",
            "--display-name",
            display_name,
            "--query",
            "[].{displayName:displayName}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    principals = lifecycle._run(
        (
            "az",
            "ad",
            "sp",
            "list",
            "--display-name",
            display_name,
            "--query",
            "[].{displayName:displayName}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    for value in (applications, principals):
        if not isinstance(value, list) or any(
            not isinstance(item, dict) or item != {"displayName": display_name}
            for item in value
        ):
            lifecycle._fail("closeout-ephemeral-identity-inventory-malformed")
    assert isinstance(applications, list)
    assert isinstance(principals, list)
    return len(applications) + len(principals)


def _proof_residue_counts(subscription_id: str) -> tuple[int, int, int]:
    resources = lifecycle._run(
        (
            "az",
            "resource",
            "list",
            "--subscription",
            subscription_id,
            "--query",
            (
                f"[?resourceGroup=='{lifecycle.TARGET_GROUP}' && ("
                "name=='caj-mobius77-scanner-proof' || "
                f"name=='{_PROOF_ROLE_DEFINITION}')].{{name:name,type:type}}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    roles = lifecycle._run(
        (
            "az",
            "role",
            "definition",
            "list",
            "--name",
            _PROOF_ROLE_DEFINITION,
            "--subscription",
            subscription_id,
            "--query",
            "[].{name:name}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    assignments = lifecycle._run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--all",
            "--subscription",
            subscription_id,
            "--query",
            f"[?ends_with(roleDefinitionId, '/{_PROOF_ROLE_DEFINITION}')].{{id:id}}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not all(isinstance(value, list) for value in (resources, roles, assignments)):
        lifecycle._fail("closeout-proof-residue-inventory-malformed")
    assert isinstance(resources, list)
    assert isinstance(roles, list)
    assert isinstance(assignments, list)
    return len(resources), len(roles), len(assignments)


def successful_closeout(
    *,
    ledger: Mapping[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    soak_evidence = _require_stage_predecessor(
        stage="successful-closeout",
        ledger=ledger,
        receipt_directory=receipt_directory,
    )
    state_path = lifecycle._state_path(receipt_directory)
    state = lifecycle._read_current_transient_state(state_path, ledger=ledger)
    if state.get("resumableCheckpoint") != "successful-closeout":
        lifecycle._fail("successful-closeout-stage-prerequisite-missing")
    proof_jobs, proof_roles, proof_assignments = _proof_residue_counts(subscription_id)
    publisher_residue = _exact_ephemeral_identity_count(
        ledger=ledger, identity_prefix="mobius77-acr-publisher"
    )
    finalizer_residue = _exact_ephemeral_identity_count(
        ledger=ledger, identity_prefix="mobius77-acr-finalizer"
    )
    revocation = lifecycle._revoke(subscription_id, receipt_directory)
    if revocation.get("status") != "revoked-and-denied":
        lifecycle._fail("successful-closeout-revocation-unproved")
    return {
        "lifecycleTemporaryTagCount": 0,
        "proofJobResidueCount": proof_jobs,
        "publisherFinalizerResidueCount": publisher_residue + finalizer_residue,
        "requiredEvidenceChainIntegritySha256": soak_evidence.integrity_sha256,
        "temporaryAssignmentCount": proof_assignments,
        "temporaryAuthorizationCount": 0,
        "temporaryCustomRoleCount": proof_roles,
    }


def validate_cleanup_authorization(
    *, receipt_directory: Path, ledger: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    path = lifecycle._cleanup_authorization_path(receipt_directory)
    if not path.is_file():
        lifecycle._fail("cleanup-authorization-missing")
    value = load_json(path)
    if not isinstance(value, dict):
        lifecycle._fail("cleanup-authorization-malformed")
    closeout_evidence: terminal_lifecycle.TerminalStageEvidence | None = None
    if value.get("authorizationMode") == "successful-closeout":
        closeout_path = terminal_lifecycle.stage_evidence_path(
            receipt_directory, "successful-closeout"
        )
        if not closeout_path.is_file():
            lifecycle._fail("cleanup-success-evidence-incomplete")
        try:
            closeout_evidence = terminal_lifecycle.load_stage_evidence(
                closeout_path,
                expected_stage="successful-closeout",
                repository_head=str(ledger["repositoryHead"]),
                ledger_integrity_sha256=lifecycle._ledger_integrity(ledger),
            )
        except terminal_lifecycle.TerminalLifecycleError as exc:
            lifecycle._fail(str(exc))
    authorization_id = ledger.get("authorizationId")
    repository_head = ledger.get("repositoryHead")
    if not isinstance(authorization_id, str) or not isinstance(repository_head, str):
        lifecycle._fail("cleanup-authorization-scope-mismatch")
    try:
        return terminal_lifecycle.validate_cleanup_authorization(
            value,
            authorization_id=authorization_id,
            repository_head=repository_head,
            resource_groups=(
                lifecycle.TARGET_GROUP,
                lifecycle.CLEANUP_GROUP,
                lifecycle.INFRASTRUCTURE_GROUP,
            ),
            now_utc=lifecycle._utc_now(),
            closeout_evidence=closeout_evidence,
        )
    except terminal_lifecycle.TerminalLifecycleError as exc:
        lifecycle._fail(str(exc))


def cleanup(
    subscription_id: str,
    receipt_directory: Path,
    *,
    ledger: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    authorization = validate_cleanup_authorization(
        receipt_directory=receipt_directory, ledger=ledger
    )
    authorization_mode = str(authorization["authorizationMode"])
    state_path = lifecycle._state_path(receipt_directory)
    revocation_path = "no-transient-state"
    if state_path.is_file():
        try:
            lifecycle._revoke(subscription_id, receipt_directory)
            revocation_path = "explicit-revocation-and-denial"
        except (ContractError, lifecycle.LifecycleError, OSError, ValueError):
            revocation_path = "superseded-by-resource-deletion"
    resource_group_delete_count = 0
    target_group_present = lifecycle._group_exists(
        subscription_id, lifecycle.TARGET_GROUP
    )

    def delete_group(group: str) -> None:
        nonlocal resource_group_delete_count
        try:
            lifecycle._run(
                (
                    "az",
                    "group",
                    "delete",
                    "--name",
                    group,
                    "--subscription",
                    subscription_id,
                    "--yes",
                    "--only-show-errors",
                    "--output",
                    "none",
                ),
                timeout_seconds=lifecycle.DEPLOYMENT_TIMEOUT_SECONDS,
            )
        except lifecycle.AzureCommandError as exc:
            if lifecycle._group_exists(subscription_id, group):
                lifecycle._fail(
                    "cleanup-resource-group-delete-azure-"
                    + exc.sanitized_azure_error_code
                )
        resource_group_delete_count += 1

    if target_group_present:
        delete_group(lifecycle.TARGET_GROUP)
    if lifecycle._group_exists(subscription_id, lifecycle.INFRASTRUCTURE_GROUP):
        delete_group(lifecycle.INFRASTRUCTURE_GROUP)
    vault_purged = lifecycle._purge_exact_deleted_vault(subscription_id)
    if lifecycle._group_exists(subscription_id, lifecycle.CLEANUP_GROUP):
        delete_group(lifecycle.CLEANUP_GROUP)
    if target_group_present and not vault_purged:
        deadline = time.monotonic() + 600.0
        while time.monotonic() < deadline:
            if lifecycle._purge_exact_deleted_vault(subscription_id):
                vault_purged = True
                break
            time.sleep(5.0)
        if not vault_purged:
            lifecycle._fail("soft-deleted-key-vault-not-observed-for-purge")
    if target_group_present:
        absent_observations = 0
        deadline = time.monotonic() + 600.0
        while time.monotonic() < deadline and absent_observations < 3:
            if lifecycle._deleted_vault_present(subscription_id):
                absent_observations = 0
            else:
                absent_observations += 1
            if absent_observations < 3:
                time.sleep(5.0)
        if absent_observations != 3:
            lifecycle._fail("soft-deleted-key-vault-residue-detected")
    elif lifecycle._deleted_vault_present(subscription_id):
        lifecycle._fail("soft-deleted-key-vault-residue-detected")
    state_path.unlink(missing_ok=True)
    lifecycle._cleanup_authorization_path(receipt_directory).unlink()
    return {
        "authorizationMode": authorization_mode,
        "resourceGroupDeleteCount": resource_group_delete_count,
        "softDeletedVaultAbsent": True,
        "status": "cleanup-completed",
        "temporaryAuthorityRevoked": True,
        "temporary-authority-cleanup-path": revocation_path,
        "provisioning-authorized": False,
        "secret-value-accessed": False,
    }


def zero_residue(
    subscription_id: str,
    *,
    ledger: Mapping[str, JsonValue],
    receipt_directory: Path,
) -> dict[str, JsonValue]:
    _require_stage_predecessor(
        stage="zero-residue-verification",
        ledger=ledger,
        receipt_directory=receipt_directory,
    )
    for group in (
        lifecycle.TARGET_GROUP,
        lifecycle.INFRASTRUCTURE_GROUP,
        lifecycle.CLEANUP_GROUP,
    ):
        if lifecycle._group_exists(subscription_id, group):
            lifecycle._fail("resource-group-residue-detected")
    resources = lifecycle._run(
        (
            "az",
            "resource",
            "list",
            "--subscription",
            subscription_id,
            "--query",
            f"[?resourceGroup=='{lifecycle.TARGET_GROUP}'].{{id:id,name:name,type:type}}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(resources, list):
        lifecycle._fail("zero-residue-resource-inventory-malformed")
    target_resource_count = len(resources)
    if target_resource_count != 0:
        lifecycle._fail("target-resource-residue-detected")
    if lifecycle._deleted_vault_present(subscription_id):
        lifecycle._fail("soft-deleted-key-vault-residue-detected")
    proof_jobs, proof_roles, proof_assignments = _proof_residue_counts(subscription_id)
    publisher_count = _exact_ephemeral_identity_count(
        ledger=ledger, identity_prefix="mobius77-acr-publisher"
    )
    finalizer_count = _exact_ephemeral_identity_count(
        ledger=ledger, identity_prefix="mobius77-acr-finalizer"
    )
    temporary_authorization_count = int(
        lifecycle._cleanup_authorization_path(receipt_directory).exists()
    )
    counts: dict[str, JsonValue] = {
        "finalizerIdentityCount": finalizer_count,
        "lifecycleTemporaryTagCount": 0,
        "proofJobCount": proof_jobs,
        "publisherIdentityCount": publisher_count,
        "resourceGroupCount": 0,
        "softDeletedVaultCount": 0,
        "targetResourceCount": target_resource_count,
        "temporaryAssignmentCount": proof_assignments,
        "temporaryAuthorizationCount": temporary_authorization_count,
        "temporaryCustomRoleCount": proof_roles,
    }
    if any(value != 0 for value in counts.values()):
        lifecycle._fail("zero-residue-not-zero")
    return {
        **counts,
        "status": "zero-residue",
        "absent-resource-group-count": 3,
        "soft-deleted-key-vault-present": False,
        "provisioning-authorized": False,
        "secret-value-accessed": False,
    }


def milestone_completion(
    *, ledger: Mapping[str, JsonValue], receipt_directory: Path
) -> dict[str, JsonValue]:
    zero_evidence = terminal_lifecycle.load_stage_evidence(
        terminal_lifecycle.stage_evidence_path(
            receipt_directory, "zero-residue-verification"
        ),
        expected_stage="zero-residue-verification",
        repository_head=str(ledger["repositoryHead"]),
        ledger_integrity_sha256=lifecycle._ledger_integrity(ledger),
    )
    return {
        "marker": terminal_lifecycle.MILESTONE_COMPLETION_MARKER,
        "milestone78Started": False,
        "provisioningAuthorized": False,
        "zeroResidueEvidenceIntegritySha256": zero_evidence.integrity_sha256,
    }


def terminal_stage_payload(
    operation: str, result: Mapping[str, JsonValue]
) -> dict[str, JsonValue] | None:
    if operation not in terminal_lifecycle.TERMINAL_STAGE_ORDER:
        return None
    if operation == "cleanup":
        if result.get("authorizationMode") != "successful-closeout":
            return None
        fields = {
            "authorizationMode",
            "resourceGroupDeleteCount",
            "softDeletedVaultAbsent",
            "temporaryAuthorityRevoked",
        }
        return {key: result[key] for key in fields}
    if operation == "zero-residue-verification":
        fields = {
            "finalizerIdentityCount",
            "lifecycleTemporaryTagCount",
            "proofJobCount",
            "publisherIdentityCount",
            "resourceGroupCount",
            "softDeletedVaultCount",
            "targetResourceCount",
            "temporaryAssignmentCount",
            "temporaryAuthorizationCount",
            "temporaryCustomRoleCount",
        }
        return {key: result[key] for key in fields}
    return dict(result)


def persist_terminal_stage(
    *,
    operation: str,
    result: Mapping[str, JsonValue],
    ledger: Mapping[str, JsonValue],
    receipt_directory: Path,
    started_at_utc: datetime,
    completed_at_utc: datetime,
) -> terminal_lifecycle.TerminalStageEvidence | None:
    payload = terminal_stage_payload(operation, result)
    if payload is None:
        return None
    predecessor = terminal_lifecycle.STAGE_PREDECESSOR[operation]
    previous = None
    if predecessor is not None:
        predecessor_path = terminal_lifecycle.stage_evidence_path(
            receipt_directory, predecessor
        )
        if operation == "zero-residue-verification" and not predecessor_path.is_file():
            return None
        previous = terminal_lifecycle.load_stage_evidence(
            predecessor_path,
            expected_stage=predecessor,
            repository_head=str(ledger["repositoryHead"]),
            ledger_integrity_sha256=lifecycle._ledger_integrity(ledger),
        )
    try:
        evidence = terminal_lifecycle.build_stage_evidence(
            stage=operation,
            repository_head=str(ledger["repositoryHead"]),
            ledger_integrity_sha256=lifecycle._ledger_integrity(ledger),
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            payload=payload,
            previous=previous,
        )
        terminal_lifecycle.write_stage_evidence(receipt_directory, evidence)
    except terminal_lifecycle.TerminalLifecycleError as exc:
        lifecycle._fail(str(exc))
    return evidence


def issue_successful_cleanup_authorization(
    *,
    ledger: Mapping[str, JsonValue],
    receipt_directory: Path,
    closeout_evidence: terminal_lifecycle.TerminalStageEvidence,
    issued_at_utc: datetime,
) -> dict[str, JsonValue]:
    authorization_id = ledger.get("authorizationId")
    if not isinstance(authorization_id, str):
        lifecycle._fail("cleanup-authorization-scope-mismatch")
    try:
        value = terminal_lifecycle.build_successful_cleanup_authorization(
            closeout_evidence=closeout_evidence,
            authorization_id=authorization_id,
            resource_groups=(
                lifecycle.TARGET_GROUP,
                lifecycle.CLEANUP_GROUP,
                lifecycle.INFRASTRUCTURE_GROUP,
            ),
            issued_at_utc=issued_at_utc,
        )
        terminal_lifecycle.write_cleanup_authorization(receipt_directory, value)
    except terminal_lifecycle.TerminalLifecycleError as exc:
        lifecycle._fail(str(exc))
    return value


__all__ = [
    "cleanup",
    "issue_successful_cleanup_authorization",
    "live_validation_sample",
    "live_validation_stage",
    "migration_stage",
    "milestone_completion",
    "persist_terminal_stage",
    "readiness_stage",
    "soak_stage",
    "successful_closeout",
    "validate_cleanup_authorization",
    "verify_post_secret_foundation",
    "zero_residue",
]
