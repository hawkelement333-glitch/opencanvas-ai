"""Exact execution-scoped, retained console evidence for the managed probes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_8.automation_region import _safe_inventory_next_link
from infra.milestone_7_8.campaign import CampaignError, CommandRunner, parse_utc
from infra.milestone_7_8.controller_renewal import _durable_record
from infra.milestone_7_8.measurement_handoff import _check_id, _name, _object
from infra.milestone_7_8.replica_readback import (
    API_VERSION,
    collect_worker_replicas,
    worker_replica_url,
)

HASH = re.compile(r"[a-f0-9]{64}\Z")
TOKEN = re.compile(r"[a-f0-9]{32}\Z")
REQUIRED_CODES = frozenset(
    {
        "catalog.roles",
        "catalog.ownership",
        "catalog.public-restrictions",
        "catalog.runtime-grants",
        "migration.nullpool",
        "migration.advisory-lock",
        "migration.exact-revision",
        "migration.reconciliation",
        "capacity.max-connections",
        "capacity.azure-reserved",
        "capacity.pool-ceilings",
        "capacity.rollout-overlap",
        "capacity.operator-consumers",
        "capacity.observed-peak",
        "capacity.safety-reserve",
        "recovery.failover",
        "recovery.stale-pool",
        "recovery.credential-revocation",
        "idempotency.canvas",
        "idempotency.node",
        "idempotency.duplicate-node",
        "idempotency.edge",
        "idempotency.conflict-409",
        "idempotency.authority-revalidation",
        "tenant.pool-reuse",
        "tenant.post-failover",
        "tenant.forged-workspace",
        "tenant.forged-canvas",
        "tenant.forged-replay",
        "tenant.forged-evidence-bundle",
        "tenant.forged-workflow",
        "operations.zones",
        "operations.ha",
        "operations.maintenance",
        "operations.storage",
        "operations.backup",
        "operations.latency",
        "operations.recovery",
    }
)


def evidence_hash(value: object) -> str:
    return hashlib.sha256(
        b"m7.8/managed-assertion-evidence/v1\0"
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def assertions(payload: dict[str, object], phase: str) -> set[str]:
    fields = {"version", "observedAtUtc", "assertions", "status"}
    if phase == "failover-window":
        fields.add("disruption")
    if (
        set(payload) != fields
        or payload.get("status") != "passed"
        or payload.get("version") != "m7.8-managed-postgres-evidence-v1"
    ):
        raise CampaignError("managed assertion marker contract differs")
    parse_utc(str(payload["observedAtUtc"]))
    values = payload.get("assertions")
    if not isinstance(values, list) or not values:
        raise CampaignError("managed assertion marker is empty")
    codes: set[str] = set()
    for item in values:
        row = _object(item, "managed assertion")
        code = row.get("code")
        if (
            set(row) != {"code", "passed", "observed_count", "evidence_sha256"}
            or row.get("passed") is not True
            or not isinstance(code, str)
            or code not in REQUIRED_CODES
            or code in codes
            or type(row.get("observed_count")) is not int
            or cast(int, row["observed_count"]) < 1
            or not isinstance(row.get("evidence_sha256"), str)
            or HASH.fullmatch(str(row["evidence_sha256"])) is None
        ):
            raise CampaignError("managed assertion is missing, duplicated, or failed")
        codes.add(code)
    minimum = {
        "api": {"catalog.roles", "catalog.runtime-grants"},
        "worker": {"catalog.roles", "catalog.runtime-grants"},
        "catalog": {"catalog.roles", "catalog.ownership", "catalog.public-restrictions"},
        "application": {"idempotency.canvas", "tenant.pool-reuse"},
        "migration": {
            "migration.nullpool",
            "migration.advisory-lock",
            "migration.exact-revision",
            "migration.reconciliation",
        },
        "credential-denied": {"recovery.credential-revocation"},
        "failover-window": {"recovery.failover", "recovery.stale-pool", "tenant.post-failover"},
        "operations": {"operations.latency", "operations.recovery", "capacity.observed-peak"},
    }
    if phase not in minimum or not minimum[phase] <= codes:
        raise CampaignError("managed assertion marker does not prove its dispatched phase")
    return codes


def credential(payload: dict[str, object], phase: str, runtime: dict[str, str]) -> None:
    if (
        set(payload)
        != {
            "version",
            "mode",
            "loginEnabled",
            "activeSessions",
            "terminatedSessions",
            "status",
            "campaignId",
            "generationId",
        }
        or payload.get("version") != "m7.8-credential-recovery-observation-v1"
        or payload.get("status") != "observed"
        or payload.get("mode") != phase
        or payload.get("campaignId") != runtime["campaignId"]
        or payload.get("generationId") != runtime["generationId"]
        or payload.get("loginEnabled") is not (phase == "restore")
    ):
        raise CampaignError("credential observation binding differs")
    for key in ("activeSessions", "terminatedSessions"):
        value = payload[key]
        if value is not None and (type(value) is not int or value < 0):
            raise CampaignError("credential observation session count differs")
    if phase == "revoke" and (
        payload["activeSessions"] != 0 or type(payload["terminatedSessions"]) is not int
    ):
        raise CampaignError("credential revocation did not prove session removal")


def _decode(result: dict[str, object]) -> object:
    if result.get("exitCode") != 0 or not isinstance(result.get("stdout"), str):
        raise CampaignError("managed console read failed")
    try:
        return cast(object, json.loads(str(result["stdout"])))
    except json.JSONDecodeError as exc:
        raise CampaignError("managed console read is malformed") from exc


def validate_probe_container(
    container: dict[str, object],
    *,
    phase: str,
    image_digest: str,
    token: str,
) -> None:
    env = container.get("env")
    command = (
        "scripts.credential_recovery_probe"
        if phase in {"revoke", "restore"}
        else "scripts.managed_postgres_evidence"
    )
    expected_args = [phase] if phase in {"revoke", "restore"} else ["--phase=" + phase]
    actual_args = container.get("args")
    equivalent_args = ["--phase", phase] if phase not in {"revoke", "restore"} else expected_args
    command_matches = (
        container.get("command") == ["python", "-m", command]
        and actual_args in (expected_args, equivalent_args)
    ) or (
        phase in {"revoke", "restore"}
        and container.get("command") == ["python", "-m", command, phase]
        and actual_args in (None, [])
    )
    if (
        not command_matches
        or not str(container.get("image", "")).endswith("@" + image_digest)
        or not isinstance(env, list)
        or [
            item.get("value")
            for item in env
            if isinstance(item, dict) and item.get("name") == "M78_EVIDENCE_TOKEN"
        ]
        != [token]
    ):
        raise CampaignError("managed execution image, command, or token differs")


def validate_capture(
    record: dict[str, object],
    runtime: dict[str, str],
    image_digest: str,
) -> dict[str, object]:
    if (
        set(record)
        != {
            "version",
            "job",
            "execution",
            "token",
            "phase",
            "ready",
            "imageDigest",
            "sourceHead",
            "executionReadback",
            "replicas",
            "workspaceReadback",
            "query",
            "queryReadback",
            "payload",
            "evidenceSha256",
            "dispatchedAtUtc",
            "observedAtUtc",
        }
        or record.get("version") != "m7.8-managed-console-capture-v1"
        or record.get("imageDigest") != image_digest
        or record.get("sourceHead") != runtime["sourceHead"]
        or type(record.get("ready")) is not bool
        or not isinstance(record.get("token"), str)
        or TOKEN.fullmatch(str(record["token"])) is None
        or record["evidenceSha256"]
        != evidence_hash({key: value for key, value in record.items() if key != "evidenceSha256"})
    ):
        raise CampaignError("managed console evidence binding differs")
    job, execution = _name(record["job"]), _name(record["execution"])
    phase = str(record["phase"])
    expected_jobs = {
        "api": runtime["apiProbeJobName"],
        "worker": runtime["workerProbeJobName"],
        "catalog": runtime["evidenceJobName"],
        "application": runtime["evidenceJobName"],
        "migration": runtime["migrationProbeJobName"],
        "credential-denied": runtime["apiProbeJobName"],
        "revoke": runtime["recoveryJobName"],
        "restore": runtime["recoveryRestoreJobName"],
        "failover-window": runtime["migrationProbeJobName"],
        "operations": runtime["evidenceJobName"],
    }
    if phase not in expected_jobs or job != expected_jobs[phase]:
        raise CampaignError("managed console job differs from its approved phase")
    execution_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{runtime['resourceGroupName']}"
        f"/providers/Microsoft.App/jobs/{job}/executions/{execution}"
    )
    shown = _object(
        _decode(_object(record["executionReadback"], "execution readback")), "managed execution"
    )
    _check_id(shown, execution_id)
    properties = _object(shown.get("properties"), "managed execution properties")
    if shown.get("name") != execution or properties.get("status") != (
        "Running" if record["ready"] else "Succeeded"
    ):
        raise CampaignError("managed execution terminal identity or state differs")
    template = _object(properties.get("template"), "managed execution template")
    containers = template.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise CampaignError("managed execution container scope differs")
    container = _object(containers[0], "managed execution container")
    validate_probe_container(
        container,
        phase=phase,
        image_digest=image_digest,
        token=str(record["token"]),
    )
    capture = _object(record["replicas"], "managed execution replicas")
    scope = execution_id + "/replicas"
    pages = capture.get("pages")
    if (
        capture.get("complete") is not True
        or capture.get("scopePath") != scope
        or not (isinstance(pages, list) and 0 < len(pages) <= 100)
    ):
        raise CampaignError("managed execution replica pages are incomplete")
    names: list[str] = []
    for offset, raw in enumerate(pages):
        page = _object(raw, "managed replica page")
        values = page.get("value")
        if not isinstance(values, list):
            raise CampaignError("managed replica page is incomplete")
        for item in values:
            replica = _object(item, "managed replica")
            name = _name(replica.get("name"))
            _check_id(replica, scope + "/" + name)
            if name in names:
                raise CampaignError("managed replica is duplicated")
            names.append(name)
        link = page.get("nextLink")
        if offset + 1 < len(pages):
            if not isinstance(link, str):
                raise CampaignError("managed replica continuation is incomplete")
            _safe_inventory_next_link(
                link,
                subscription_id=runtime["subscriptionId"],
                expected_path=scope,
                api_version=API_VERSION,
                label="managed probe",
            )
        elif link not in (None, ""):
            raise CampaignError("managed replica pagination is incomplete")
    if len(names) != 1:
        raise CampaignError("managed execution requires exactly one replica")
    workspace = _object(
        _decode(_object(record["workspaceReadback"], "workspace readback")), "managed workspace"
    )
    _check_id(
        workspace,
        (
            f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{runtime['resourceGroupName']}"
            "/providers/Microsoft.OperationalInsights/workspaces/"
            + runtime["logAnalyticsWorkspaceName"]
        ),
    )
    marker = "M78_FAILOVER_READY" if record["ready"] else "M78_EVIDENCE"
    prefix = f"{marker} {record['token']} "
    query = (
        "ContainerAppConsoleLogs_CL"
        f" | where ContainerGroupName_s in ('{names[0]}')"
        f" | where ContainerName_s == '{_name(container.get('name'))}'"
        f" and Log_s startswith '{prefix}'"
        " | project replica=ContainerGroupName_s, message=Log_s | take 2"
    )
    rows = _decode(_object(record["queryReadback"], "console readback"))
    if record["query"] != query or not isinstance(rows, list) or len(rows) != 1:
        raise CampaignError("managed console query or result is not exact")
    row = _object(rows[0], "managed console row")
    message = row.get("message")
    if (
        row.get("replica") != names[0]
        or not isinstance(message, str)
        or not (message.startswith(prefix))
    ):
        raise CampaignError("managed console marker is not from the exact replica")
    payload = _object(json.loads(message[len(prefix) :]), "managed console payload")
    if payload != record["payload"]:
        raise CampaignError("managed console payload differs from retained response")
    dispatched_at = parse_utc(str(record["dispatchedAtUtc"]))
    observed_at = parse_utc(str(record["observedAtUtc"]))
    if dispatched_at > observed_at:
        raise CampaignError("managed console observation precedes its dispatch")
    if phase not in {"revoke", "restore"} and not (
        dispatched_at <= parse_utc(str(payload.get("observedAtUtc"))) <= observed_at
    ):
        raise CampaignError("managed probe marker timestamp is outside its execution window")
    if record["ready"]:
        if (
            phase != "failover-window"
            or set(payload) != {"version", "observedAtUtc", "workerExecution"}
            or payload.get("version") != "m7.8-failover-ready-v1"
        ):
            raise CampaignError("managed failover ready marker differs")
        _name(payload["workerExecution"])
        parse_utc(str(payload["observedAtUtc"]))
    elif phase in {"revoke", "restore"}:
        credential(payload, phase, runtime)
    else:
        assertions(payload, phase)
    return payload


def validate_ready_readback(
    ready: dict[str, object],
    readback: dict[str, object],
    observed_at: str,
    runtime: dict[str, str],
    image_digest: str,
) -> None:
    observed = parse_utc(observed_at)
    if observed < parse_utc(str(ready["observedAtUtc"])):
        raise CampaignError("failover probe state readback is stale")
    fresh = {**ready, "executionReadback": readback, "observedAtUtc": observed_at}
    fresh["evidenceSha256"] = evidence_hash(
        {key: value for key, value in fresh.items() if key != "evidenceSha256"}
    )
    validate_capture(fresh, runtime, image_digest)


def validate_failover(
    ready: dict[str, object],
    payload: dict[str, object],
    restart: dict[str, object],
    *,
    worker_execution: str,
) -> float:
    if (
        ready.get("workerExecution") != worker_execution
        or ready.get("version") != "m7.8-failover-ready-v1"
    ):
        raise CampaignError("failover ready marker names another worker execution")
    started = parse_utc(str(restart.get("dispatchedAtUtc")))
    returned = parse_utc(str(restart.get("completedAtUtc")))
    result = _object(restart.get("result"), "forced failover result")
    if result.get("exitCode") != 0 or not isinstance(result.get("stdout"), str):
        raise CampaignError("forced failover did not return a successful acknowledgement")
    disruption = _object(payload.get("disruption"), "failover disruption")
    if (
        set(disruption)
        != {
            "version",
            "startedAtUtc",
            "readyAtUtc",
            "endedAtUtc",
            "observations",
            "workerClaimsObserved",
            "workerRecoveryObserved",
            "ambiguousReplayVerified",
            "tenantIsolationVerified",
            "replayEvidenceSha256",
            "tenantEvidenceSha256",
        }
        or disruption.get("version") != "m7.8-failover-window-v1"
        or any(
            disruption[key] is not True
            for key in (
                "workerClaimsObserved",
                "workerRecoveryObserved",
                "ambiguousReplayVerified",
                "tenantIsolationVerified",
            )
        )
        or any(
            HASH.fullmatch(str(disruption[key])) is None
            for key in (
                "replayEvidenceSha256",
                "tenantEvidenceSha256",
            )
        )
    ):
        raise CampaignError("managed failover disruption proof is incomplete")
    beginning = parse_utc(str(disruption["startedAtUtc"]))
    ready_at = parse_utc(str(ready.get("observedAtUtc")))
    ended = parse_utc(str(disruption["endedAtUtc"]))
    if not beginning <= ready_at < started <= returned or not (
        started < ended and parse_utc(str(disruption["readyAtUtc"])) == ready_at
    ):
        raise CampaignError("managed failover probe does not span the real restart dispatch")
    observations = disruption.get("observations")
    if not isinstance(observations, list) or not 3 <= len(observations) <= 24:
        raise CampaignError("managed failover observations are incomplete")
    prior: datetime | None = None
    baseline: tuple[int, int] | None = None
    failed_at: datetime | None = None
    recovered_at: datetime | None = None
    for item in observations:
        row = _object(item, "managed failover observation")
        if (
            set(row)
            != {
                "observedAtUtc",
                "apiReadPassed",
                "apiWritePassed",
                "workerDatabaseActive",
                "workerObservedAtUtc",
                "workerClaims",
                "workerOutcomes",
                "workerLatestClaimAtUtc",
                "workerLatestOutcomeAtUtc",
                "evidenceSha256",
            }
            or any(
                type(row.get(key)) is not bool
                for key in (
                    "apiReadPassed",
                    "apiWritePassed",
                    "workerDatabaseActive",
                )
            )
            or any(
                type(row.get(key)) is not int or cast(int, row[key]) < 0
                for key in ("workerClaims", "workerOutcomes")
            )
            or HASH.fullmatch(str(row.get("evidenceSha256"))) is None
        ):
            raise CampaignError("managed failover observation shape differs")
        observed = parse_utc(str(row["observedAtUtc"]))
        if not beginning <= observed <= ended or (prior is not None and observed <= prior):
            raise CampaignError("managed failover observations are stale or out of order")
        prior = observed
        healthy = all(
            row[key] is True
            for key in (
                "apiReadPassed",
                "apiWritePassed",
                "workerDatabaseActive",
            )
        )
        counts = cast(int, row["workerClaims"]), cast(int, row["workerOutcomes"])
        heartbeat = (
            parse_utc(str(row["workerObservedAtUtc"]))
            if row["workerObservedAtUtc"] is not None
            else None
        )
        latest_claim = (
            parse_utc(str(row["workerLatestClaimAtUtc"]))
            if row["workerLatestClaimAtUtc"] is not None
            else None
        )
        latest_outcome = (
            parse_utc(str(row["workerLatestOutcomeAtUtc"]))
            if row["workerLatestOutcomeAtUtc"] is not None
            else None
        )
        if any(
            value is not None and value > observed
            for value in (heartbeat, latest_claim, latest_outcome)
        ):
            raise CampaignError("worker observation timestamp is in the future")
        if observed < started and healthy:
            baseline = counts
        if observed >= started and not healthy and failed_at is None:
            failed_at = observed
        if (
            failed_at is not None
            and observed > failed_at
            and healthy
            and baseline is not None
            and heartbeat is not None
            and heartbeat >= started
            and counts[0] > baseline[0]
            and counts[1] > baseline[1]
            and latest_claim is not None
            and latest_outcome is not None
            and latest_claim > max(started, failed_at)
            and latest_outcome > max(started, failed_at)
            and recovered_at is None
        ):
            recovered_at = observed
    if baseline is None or failed_at is None or recovered_at is None:
        raise CampaignError("actual API and worker interruption/recovery was not observed")
    # ARM's synchronous command can return after the application has recovered.
    return (recovered_at - started).total_seconds()


def validate_worker_capture(
    capture: dict[str, object], runtime: dict[str, str], execution: str
) -> None:
    scope = (
        worker_replica_url(
            runtime["subscriptionId"],
            runtime["resourceGroupName"],
            runtime["workerJobName"],
            execution,
        )
        .removeprefix("https://management.azure.com")
        .split("?", 1)[0]
    )
    pages = capture.get("pages")
    if (
        capture.get("scopePath") != scope
        or capture.get("complete") is not True
        or not (isinstance(pages, list) and pages)
    ):
        raise CampaignError("failover worker inventory is incomplete")
    capture_start = parse_utc(str(capture.get("startedAtUtc")))
    capture_end = parse_utc(str(capture.get("endedAtUtc")))
    if capture_start > capture_end or len(pages) > 100:
        raise CampaignError("failover worker inventory timing or pagination is invalid")
    records: list[dict[str, object]] = []
    for offset, raw_page in enumerate(pages):
        page = _object(raw_page, "failover worker page")
        link = page.get("nextLink")
        if offset + 1 < len(pages):
            if not isinstance(link, str):
                raise CampaignError("failover worker continuation is missing")
            _safe_inventory_next_link(
                link,
                subscription_id=runtime["subscriptionId"],
                expected_path=scope,
                api_version=API_VERSION,
                label="failover worker",
            )
        elif link not in (None, ""):
            raise CampaignError("failover worker inventory ended before its last page")
        value = page.get("value")
        if not isinstance(value, list):
            raise CampaignError("failover worker page is incomplete")
        records.extend(_object(item, "failover worker replica") for item in value)
    names: set[str] = set()
    for record in records:
        name = _name(record.get("name"))
        _check_id(record, scope + "/" + name)
        if (
            name in names
            or _object(record.get("properties"), "worker properties").get("runningState")
            != "Running"
        ):
            raise CampaignError("failover worker replicas are not four distinct Running instances")
        names.add(name)
    if len(names) != 4:
        raise CampaignError("failover requires four running worker replicas")


PHASES = (
    "api",
    "worker",
    "catalog",
    "application",
    "migration",
    "revoke",
    "credential-denied",
    "restore",
    "api",
    "failover-window",
    "operations",
)


def validate_proofs(
    record: dict[str, object],
    runtime: dict[str, str],
    *,
    image_digest: str,
    control: dict[str, object],
    worker_execution: str,
) -> float:
    if (
        set(record)
        != {
            "version",
            "sourceHead",
            "imageDigest",
            "workerExecution",
            "control",
            "captures",
            "ready",
            "restart",
            "workerBefore",
            "workerAfter",
            "evidenceSha256",
        }
        or record.get("version") != "m7.8-managed-assertion-evidence-v1"
        or record.get("sourceHead") != runtime["sourceHead"]
        or record.get("imageDigest") != image_digest
        or record.get("workerExecution") != worker_execution
        or record.get("control") != control
        or record.get("evidenceSha256")
        != evidence_hash({key: value for key, value in record.items() if key != "evidenceSha256"})
    ):
        raise CampaignError("managed assertion collection binding differs")
    captures = record.get("captures")
    if not isinstance(captures, list) or len(captures) != len(PHASES):
        raise CampaignError("managed assertion collection is incomplete")
    tokens: set[str] = set()
    executions: set[tuple[str, str]] = set()
    codes: set[str] = set()
    payloads: dict[str, dict[str, object]] = {}
    previous_observed: datetime | None = None
    for value, phase in zip(captures, PHASES, strict=True):
        capture = _object(value, "managed assertion capture")
        if capture.get("phase") != phase or capture.get("ready") is not False:
            raise CampaignError("managed assertion execution order differs")
        payload = validate_capture(capture, runtime, image_digest)
        dispatched = parse_utc(str(capture["dispatchedAtUtc"]))
        if previous_observed is not None and dispatched < previous_observed:
            raise CampaignError(
                "managed assertion dispatch order contradicts retained observations"
            )
        previous_observed = parse_utc(str(capture["observedAtUtc"]))
        identity = str(capture["job"]), str(capture["execution"])
        if str(capture["token"]) in tokens or identity in executions:
            raise CampaignError("managed assertion execution or token was replayed")
        tokens.add(str(capture["token"]))
        executions.add(identity)
        if phase not in {"revoke", "restore"}:
            codes.update(assertions(payload, phase))
        payloads[phase] = payload
    if codes != REQUIRED_CODES:
        raise CampaignError("managed assertion collection omitted required observations")
    ready_capture = _object(record["ready"], "failover ready capture")
    final_capture = _object(captures[9], "failover terminal capture")
    if ready_capture.get("ready") is not True or any(
        ready_capture.get(key) != final_capture.get(key)
        for key in ("execution", "job", "token", "phase", "dispatchedAtUtc")
    ):
        raise CampaignError("failover ready and terminal executions differ")
    ready = validate_capture(ready_capture, runtime, image_digest)
    restart = _object(record["restart"], "forced failover evidence")
    validate_ready_readback(
        ready_capture,
        _object(restart.get("probeReadback"), "ready probe readback"),
        str(restart.get("probeObservedAtUtc")),
        runtime,
        image_digest,
    )
    if parse_utc(str(restart["probeObservedAtUtc"])) > parse_utc(str(restart["dispatchedAtUtc"])):
        raise CampaignError("failover probe was observed only after restart dispatch")
    command = restart.get("command")
    if not isinstance(command, (list, tuple)) or tuple(command) != (
        "az",
        "postgres",
        "flexible-server",
        "restart",
        "--resource-group",
        runtime["resourceGroupName"],
        "--name",
        runtime["postgresServerName"],
        "--failover",
        "Forced",
        "--output",
        "json",
        "--subscription",
        runtime["subscriptionId"],
    ):
        raise CampaignError("forced failover request differs from the approved server")
    before = _object(record["workerBefore"], "pre-failover worker capture")
    after = _object(record["workerAfter"], "post-failover worker capture")
    validate_worker_capture(before, runtime, worker_execution)
    validate_worker_capture(after, runtime, worker_execution)
    if not (
        parse_utc(str(before["endedAtUtc"]))
        <= parse_utc(str(restart["dispatchedAtUtc"]))
        < parse_utc(str(after["startedAtUtc"]))
    ):
        raise CampaignError("failover worker captures do not span the dispatched restart")
    recovery = validate_failover(
        ready,
        payloads["failover-window"],
        restart,
        worker_execution=worker_execution,
    )
    rendered = {
        **control,
        "recoverySeconds": recovery,
        "failoverObserved": True,
        "credentialRecoveryObserved": True,
        "postFailoverTenantIsolationObserved": True,
    }
    for item in cast(list[dict[str, object]], payloads["operations"]["assertions"]):
        expected = hashlib.sha256(
            b"m7.8/evidence/v1\0"
            + json.dumps(
                {str(item["code"]): rendered},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if item["evidence_sha256"] != expected:
            raise CampaignError(
                "operations assertions differ from measured connection and latency input"
            )
    return recovery


def _console_io_path(path: Path) -> Path:
    """Use Windows' absolute long-path form without changing retained logical paths."""
    if os.name != "nt":
        return path
    absolute = str(path.resolve())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    return Path("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\")
                else "\\\\?\\" + absolute)


def _capture_path(directory: Path, sequence: int) -> Path:
    # Execution, token and phase remain inside the validated, hashed record.
    return directory / f"c{sequence:04d}.json"


class EvidenceConsole:
    def __init__(
        self,
        runner: CommandRunner,
        runtime: dict[str, str],
        *,
        image_digest: str,
        directory: Path,
        deadline: datetime,
        authorize: Callable[[], None],
    ) -> None:
        self.runner, self.runtime, self.image_digest = runner, runtime, image_digest
        self.directory, self.deadline, self.authorize = directory, deadline, authorize
        _console_io_path(self.directory).mkdir(mode=0o700, exist_ok=False)
        self.sequence = 0

    def guard(self) -> None:
        if datetime.now(UTC) >= self.deadline:
            raise CampaignError("managed console capture crossed the cleanup deadline")
        self.authorize()

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        if "--subscription" not in command:
            command = (*command, "--subscription", self.runtime["subscriptionId"])
        self.guard()
        self.sequence += 1
        stem = self.directory / f"{self.sequence:04d}"
        _durable_record(
            _console_io_path(stem.with_suffix(".intent.json")),
            {
                "command": command,
                "requestedAtUtc": datetime.now(UTC).isoformat(),
            },
        )
        self.guard()
        result = self.runner.run(command)
        _durable_record(
            _console_io_path(stem.with_suffix(".result.json")),
            {
                **result,
                "observedAtUtc": datetime.now(UTC).isoformat(),
            },
        )
        self.guard()
        return result

    def capture(
        self,
        job: str,
        execution: str,
        token: str,
        phase: str,
        *,
        dispatched_at: datetime,
        ready: bool = False,
    ) -> dict[str, object]:
        if TOKEN.fullmatch(token) is None:
            raise CampaignError("managed console dispatch token is malformed")
        job, execution = _name(job), _name(execution)
        rt = self.runtime
        base = (
            f"/subscriptions/{rt['subscriptionId']}/resourceGroups/{rt['resourceGroupName']}"
            "/providers/Microsoft.App/jobs/" + job + "/executions/" + execution
        )
        shown_command = (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com" + base + "?api-version=2024-03-01",
            "--subscription",
            rt["subscriptionId"],
            "--output",
            "json",
        )
        ready_until = time.monotonic() + min(
            240,
            (self.deadline - datetime.now(UTC)).total_seconds(),
        )
        while True:
            shown = self.run(shown_command)
            value = _object(_decode(shown), "managed probe execution")
            _check_id(value, base)
            properties = _object(value.get("properties"), "managed probe properties")
            if not ready or properties.get("status") == "Running":
                break
            if (
                properties.get("status") not in {"Pending", "Processing", "Starting"}
                or time.monotonic() >= ready_until
            ):
                raise CampaignError("managed failover probe did not become ready")
            time.sleep(min(2, max(0, ready_until - time.monotonic())))
        if value.get("name") != execution or properties.get("status") not in (
            {"Running"} if ready else {"Succeeded"}
        ):
            raise CampaignError("managed probe execution is not the exact required state")
        template = _object(properties.get("template"), "managed probe template")
        containers = template.get("containers")
        if not isinstance(containers, list) or len(containers) != 1:
            raise CampaignError("managed probe container identity is incomplete")
        container = _object(containers[0], "managed probe container")
        if not str(container.get("image", "")).endswith("@" + self.image_digest):
            raise CampaignError("managed probe image differs from admission")
        container_name = _name(container.get("name"))
        env = container.get("env")
        if not isinstance(env, list) or [
            item.get("value")
            for item in env
            if isinstance(item, dict) and item.get("name") == "M78_EVIDENCE_TOKEN"
        ] != [token]:
            raise CampaignError("managed probe execution token differs")
        replicas = collect_worker_replicas(
            self,
            subscription=rt["subscriptionId"],
            group=rt["resourceGroupName"],
            job=job,
            execution=execution,
        )
        scope = worker_replica_url(rt["subscriptionId"], rt["resourceGroupName"], job, execution)
        scope = scope.removeprefix("https://management.azure.com").split("?", 1)[0]
        names: list[str] = []
        for page in cast(list[dict[str, object]], replicas["pages"]):
            for item in cast(list[dict[str, object]], page["value"]):
                name = _name(item.get("name"))
                _check_id(item, scope + "/" + name)
                names.append(name)
        if len(names) != 1:
            raise CampaignError("managed probe requires exactly one scoped replica")
        workspace_id = (
            f"/subscriptions/{rt['subscriptionId']}/resourceGroups/{rt['resourceGroupName']}"
            "/providers/Microsoft.OperationalInsights/workspaces/" + rt["logAnalyticsWorkspaceName"]
        )
        workspace_result = self.run(
            (
                "az",
                "monitor",
                "log-analytics",
                "workspace",
                "show",
                "--resource-group",
                rt["resourceGroupName"],
                "--workspace-name",
                rt["logAnalyticsWorkspaceName"],
                "--subscription",
                rt["subscriptionId"],
                "--output",
                "json",
            )
        )
        workspace = _object(_decode(workspace_result), "managed console workspace")
        _check_id(workspace, workspace_id)
        customer = workspace.get("customerId")
        if not isinstance(customer, str) or re.fullmatch(r"[a-fA-F0-9-]{36}", customer) is None:
            raise CampaignError("managed console workspace identity is malformed")
        marker = "M78_FAILOVER_READY" if ready else "M78_EVIDENCE"
        prefix = f"{marker} {token} "
        query = (
            "ContainerAppConsoleLogs_CL"
            f" | where ContainerGroupName_s in ('{names[0]}')"
            f" | where ContainerName_s == '{container_name}' and Log_s startswith '{prefix}'"
            " | project replica=ContainerGroupName_s, message=Log_s | take 2"
        )
        until = time.monotonic() + min(240, (self.deadline - datetime.now(UTC)).total_seconds())
        while time.monotonic() < until:
            query_result = self.run(
                (
                    "az",
                    "monitor",
                    "log-analytics",
                    "query",
                    "--workspace",
                    customer,
                    "--analytics-query",
                    query,
                    "--timespan",
                    "PT30M",
                    "--subscription",
                    rt["subscriptionId"],
                    "--output",
                    "json",
                )
            )
            rows = _decode(query_result)
            if not isinstance(rows, list) or len(rows) > 1:
                raise CampaignError("managed probe marker is ambiguous")
            if rows:
                row = _object(rows[0], "managed probe console row")
                message = row.get("message")
                if (
                    row.get("replica") not in names
                    or not isinstance(message, str)
                    or not (message.startswith(prefix))
                ):
                    raise CampaignError("managed probe marker is outside its exact execution")
                payload = _object(json.loads(message[len(prefix) :]), "managed probe marker")
                record: dict[str, object] = {
                    "version": "m7.8-managed-console-capture-v1",
                    "job": job,
                    "execution": execution,
                    "token": token,
                    "phase": phase,
                    "ready": ready,
                    "imageDigest": self.image_digest,
                    "sourceHead": rt["sourceHead"],
                    "executionReadback": shown,
                    "replicas": replicas,
                    "workspaceReadback": workspace_result,
                    "query": query,
                    "queryReadback": query_result,
                    "payload": payload,
                    "dispatchedAtUtc": dispatched_at.isoformat(),
                    "observedAtUtc": datetime.now(UTC).isoformat(),
                }
                record["evidenceSha256"] = evidence_hash(record)
                validate_capture(record, rt, self.image_digest)
                path = _capture_path(self.directory, self.sequence)
                _durable_record(_console_io_path(path), record)
                return record
            time.sleep(min(5, max(0, until - time.monotonic())))
        raise CampaignError("managed probe marker did not arrive before its capture timeout")


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z")


def read_job_marker(
    runner: CommandRunner,
    *,
    subscription: str,
    group: str,
    workspace: str,
    job: str,
    execution: str,
    container: str,
    marker: str,
    token: str,
    deadline: datetime,
    maximum_wait_seconds: int = 240,
) -> dict[str, object]:
    """Read a unique, invocation-bound console record from an exact job execution."""
    worker_replica_url(subscription, group, job, execution)
    delimiters = (workspace, container, execution)
    if (
        any(_NAME.fullmatch(part) is None for part in delimiters)
        or re.fullmatch(r"M78_[A-Z0-9_]{1,64}", marker) is None
        or re.fullmatch(r"[0-9a-f]{32}", token) is None
        or not 0 < maximum_wait_seconds <= 600
    ):
        raise CampaignError("evidence console scope is malformed")
    end = time.monotonic() + maximum_wait_seconds

    def remaining() -> float:
        return min(end - time.monotonic(), (deadline - datetime.now(UTC)).total_seconds())

    def read(*parts: str) -> object:
        if remaining() <= 0:
            raise CampaignError("evidence console read budget expired")
        result = runner.run(("az", *parts, "--subscription", subscription, "--output", "json"))
        if (
            remaining() <= 0
            or result.get("exitCode") != 0
            or not isinstance(result.get("stdout"), str)
        ):
            raise CampaignError("evidence console read failed")
        try:
            return cast(object, json.loads(str(result["stdout"])))
        except json.JSONDecodeError as exc:
            raise CampaignError("evidence console read is malformed") from exc

    found = read(
        "monitor",
        "log-analytics",
        "workspace",
        "show",
        "--resource-group",
        group,
        "--workspace-name",
        workspace,
    )
    workspace_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.OperationalInsights/workspaces/{workspace}"
    )
    if (
        not isinstance(found, dict)
        or str(found.get("id", "")).casefold() != workspace_id.casefold()
    ):
        raise CampaignError("evidence console workspace identity differs")
    try:
        customer = uuid.UUID(str(found.get("customerId", "")))
        if customer.int == 0:
            raise ValueError
    except ValueError as exc:
        raise CampaignError("evidence console workspace customer ID is malformed") from exc

    class BoundedReplicaReader:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            if remaining() <= 0:
                raise CampaignError("evidence console replica read budget expired")
            return runner.run(command)

    prefix = f"{marker} {token} "
    while remaining() > 0:
        capture = collect_worker_replicas(
            BoundedReplicaReader(),
            subscription=subscription,
            group=group,
            job=job,
            execution=execution,
        )
        names = sorted(
            str(item["name"])
            for page in cast(list[dict[str, object]], capture["pages"])
            for item in cast(list[dict[str, object]], page["value"])
        )
        if len(names) > 4 or any(
            _NAME.fullmatch(name) is None or not name.startswith(f"{execution}-") for name in names
        ):
            raise CampaignError("evidence console replica identity differs")
        if names:
            scope = ",".join(f"'{name}'" for name in names)
            query = (
                f"ContainerAppConsoleLogs_CL | where ContainerGroupName_s in ({scope})"
                f" | where ContainerName_s == '{container}' and Log_s startswith '{prefix}'"
                " | project replica = ContainerGroupName_s, container = ContainerName_s,"
                " message = Log_s | take 2"
            )
            rows = read(
                "monitor",
                "log-analytics",
                "query",
                "--workspace",
                str(customer),
                "--analytics-query",
                query,
                "--timespan",
                "PT30M",
            )
            if not isinstance(rows, list) or len(rows) > 1:
                raise CampaignError("evidence console record is ambiguous")
            if rows:
                row = rows[0]
                if (
                    not isinstance(row, dict)
                    or row.get("replica") not in names
                    or row.get("container") != container
                    or not isinstance(row.get("message"), str)
                    or not row["message"].startswith(prefix)
                ):
                    raise CampaignError("evidence console record escaped its exact execution")
                try:
                    payload = json.loads(row["message"][len(prefix) :])
                except json.JSONDecodeError as exc:
                    raise CampaignError("evidence console record is malformed") from exc
                if not isinstance(payload, dict):
                    raise CampaignError("evidence console payload is malformed")
                return cast(dict[str, object], payload)
        time.sleep(min(5, max(0, remaining())))
    raise CampaignError("evidence console record was not observed before its deadline")
