"""Bounded current-release capacity observations, not a safe-cohort calculator.

Uses the existing workload dimensions and settings. Selected interventions are
performed by the separately authorized scoped controller; this driver cannot
provision, inject infrastructure faults or replay an uncertain mutation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DIMENSIONS = (
    "authenticatedUsers",
    "workspacesPerUser",
    "membersPerWorkspace",
    "canvases",
    "resources",
    "comments",
    "shares",
    "workflows",
    "agents",
    "executions",
    "documents",
    "totalBytes",
    "maximumFileBytes",
    "pages",
    "chunks",
    "indexRevisions",
    "uploadsPerMinute",
    "indexJobsPerMinute",
    "parsingThroughput",
    "scanThroughput",
    "embeddingThroughput",
    "indexThroughput",
    "retrievalConcurrency",
    "workflowConcurrency",
    "agentConcurrency",
    "queueDepth",
    "oldestQueueAge",
    "databaseConnections",
    "poolWaitMs",
    "workerConcurrency",
    "objectThroughput",
    "dependencyRecoverySeconds",
)
SETTINGS = (
    "requests_per_user_per_minute",
    "requests_per_workspace_per_minute",
    "ai_requests_per_user_per_minute",
    "document_max_file_size_bytes",
    "request_max_body_bytes",
    "document_max_pdf_pages",
    "document_max_extracted_characters",
    "processing_max_concurrent_per_workspace",
    "processing_max_concurrent_global",
    "database_pool_size",
    "database_max_overflow",
    "upload_max_active_sessions_per_workspace",
    "indexer_max_active_requests_per_workspace",
    "document_chunk_size_chars",
    "document_chunk_overlap_chars",
    "processing_retry_limit",
)
FAULTS = (
    "network-delay",
    "partial-response",
    "provider-failure",
    "worker-loss",
    "queue-unavailable",
    "object-store-unavailable",
    "retry-storm",
    "ambiguous-commit",
)


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def prepare(
    settings: dict[str, Any], *, request_budget: int, concurrency_cap: int
) -> dict[str, Any]:
    """Generate finite synthetic fixtures relative to enforced settings, not users/SLOs."""
    require(
        1 <= request_budget <= 10000 and 1 <= concurrency_cap <= 64,
        "explicit bounded request/concurrency budget required",
    )
    limits = {key: settings[key] for key in SETTINGS}
    require(
        all(type(value) is int and value >= 0 for value in limits.values()),
        "typed deployed settings required",
    )
    maximum = limits["document_max_file_size_bytes"]
    require(maximum >= 1024, "invalid maximum document bytes")
    profiles = [
        {
            "name": "small",
            "users": 1,
            "workspacesPerUser": 1,
            "canvasesPerWorkspace": 1,
            "documentsPerCanvas": 1,
            "fileBytes": min(1024, maximum),
        },
        {
            "name": "median-fixture",
            "users": 2,
            "workspacesPerUser": 1,
            "canvasesPerWorkspace": 2,
            "documentsPerCanvas": 3,
            "fileBytes": min(65536, maximum),
        },
        {
            "name": "large-fixture",
            "users": 4,
            "workspacesPerUser": 2,
            "canvasesPerWorkspace": 2,
            "documentsPerCanvas": 2,
            "fileBytes": min(262144, maximum),
        },
        {
            "name": "abusive-boundary",
            "users": 1,
            "workspacesPerUser": 1,
            "canvasesPerWorkspace": 1,
            "documentsPerCanvas": 1,
            "fileBytes": maximum + 1,
            "expectedRejection": [413],
        },
    ]
    return {
        "schema": "m78-capacity-plan-v1",
        "settings": limits,
        "profiles": profiles,
        "requestBudget": request_budget,
        "logicalModelCallBudget": 48,
        "maximumSdkAttemptsPerCall": 3,
        "concurrencyCap": concurrency_cap,
        "phases": ["baseline", "ramp", "spike", "failure-under-load", "recovery"],
        "rampConcurrencies": sorted(
            {
                1,
                min(2, concurrency_cap),
                min(4, concurrency_cap),
                min(8, concurrency_cap),
                concurrency_cap,
            }
        ),
        "selectedFaults": list(FAULTS),
        "creditedEvidence": [
            "accepted PostgreSQL failover",
            "accepted object/scanner component proof",
            "accepted Redis component proof",
            "accepted 7.7 health soak",
        ],
        "dimensions": list(DIMENSIONS),
        "interpretation": "Synthetic exploration bounds only; median/large are fixture labels, not population measurements. No supported cohort or latency SLO inferred.",
        "managedAcceptance": "unproved",
    }


@dataclass(frozen=True)
class Operation:
    operation_id: str
    actor_id: str
    workspace_id: str
    kind: str
    method: str
    path: str
    payload: dict[str, Any] | None = None
    expected_statuses: tuple[int, ...] = (200, 201, 429, 503)
    expected_rejection: bool = False
    expected_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class Response:
    status: int
    body_bytes: int
    body_sha256: str
    request_id: str | None
    retry_after: str | None
    durable_effect_ids: tuple[str, ...] = ()
    expected_state: bool = True


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def reserve_requests(
    directory: Path,
    plan: dict[str, Any],
    count: int,
    execution_id: str,
    logical_model_calls: int = 0,
) -> None:
    """Durably reserve total allowance before dispatch; uncertainty consumes budget."""
    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / "capacity-budget.lock"
    record = parent / "capacity-budget.json"
    binding = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(execution_id)
    try:
        ledger: dict[str, Any] = (
            json.loads(record.read_text())
            if record.exists()
            else {"planSha256": binding, "reservedRequests": 0, "reservations": []}
        )
        require(ledger["planSha256"] == binding, "capacity budget plan changed")
        require(
            ledger["reservedRequests"] + count <= plan["requestBudget"],
            "total request budget exhausted",
        )
        ledger["reservedRequests"] += count
        require(
            ledger.get("reservedLogicalModelCalls", 0) + logical_model_calls
            <= plan.get("logicalModelCallBudget", 0),
            "capacity model-call allowance exhausted",
        )
        ledger["reservedLogicalModelCalls"] = (
            ledger.get("reservedLogicalModelCalls", 0) + logical_model_calls
        )
        ledger["reservations"].append(
            {
                "executionId": execution_id,
                "directory": directory.name,
                "requests": count,
                "logicalModelCalls": logical_model_calls,
            }
        )
        temporary = parent / "capacity-budget.pending.json"
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(ledger, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, record)
    finally:
        lock.unlink()


async def run_phase(
    operations: list[Operation],
    *,
    phase: str,
    concurrency: int,
    plan: dict[str, Any],
    execute: Callable[[Operation], Awaitable[Response]],
    evidence_directory: Path,
    deadline: datetime,
    execution_id: str,
    reservation_applied: bool = False,
) -> dict[str, Any]:
    """Execute each exact operation once; persist intent before dispatch, even on timeout."""
    require(phase in plan["phases"], "phase not approved")
    require(0 < len(operations) <= plan["requestBudget"], "request bound exceeded")
    require(1 <= concurrency <= plan["concurrencyCap"], "concurrency bound exceeded")
    require(deadline.tzinfo is not None, "absolute authority deadline required")
    require(
        len({item.operation_id for item in operations}) == len(operations),
        "operation IDs must be unique",
    )
    require(
        all(
            item.path.startswith("/api/v1/")
            and "?" not in item.path
            and "//" not in item.path
            for item in operations
        ),
        "exact relative API paths required",
    )
    require(
        all(item.actor_id and item.workspace_id for item in operations),
        "authenticated scoped operation required",
    )
    require(
        not evidence_directory.exists(), "preserve prior intent; reconcile before retry"
    )
    model_calls = sum(
        item.method == "POST"
        and (
            item.path.endswith("/workflows/executions")
            or item.path.endswith("/invocations")
            or item.path.endswith("/run")
        )
        for item in operations
    )
    if not reservation_applied:
        reserve_requests(
            evidence_directory, plan, len(operations), execution_id, model_calls
        )
    evidence_directory.mkdir(parents=True)
    semaphore = asyncio.Semaphore(concurrency)
    measurements: list[dict[str, Any]] = []

    async def dispatch(operation: Operation) -> None:
        async with semaphore:
            require(datetime.now(UTC) < deadline, "proof deadline expired")
            identity = hashlib.sha256(operation.operation_id.encode()).hexdigest()
            intent = evidence_directory / (identity + ".intent.json")
            data = {
                "executionId": execution_id,
                "phase": phase,
                "operationId": operation.operation_id,
                "actorSha256": hashlib.sha256(operation.actor_id.encode()).hexdigest(),
                "workspaceSha256": hashlib.sha256(
                    operation.workspace_id.encode()
                ).hexdigest(),
                "kind": operation.kind,
                "method": operation.method,
                "pathSha256": hashlib.sha256(operation.path.encode()).hexdigest(),
                "payloadSha256": hashlib.sha256(
                    json.dumps(operation.payload, sort_keys=True).encode()
                ).hexdigest(),
                "at": datetime.now(UTC).isoformat(),
            }
            with intent.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, sort_keys=True)
            started = time.monotonic()
            try:
                # No retry loop, especially for mutation timeouts/ambiguous commits.
                response = await execute(operation)
                measurement = {
                    "operationId": operation.operation_id,
                    "kind": operation.kind,
                    "elapsedMs": (time.monotonic() - started) * 1000,
                    **asdict(response),
                    "expectedStatus": response.status in operation.expected_statuses
                    and response.expected_state
                    and (
                        not operation.expected_rejection
                        or response.status in (413, 429, 503)
                    ),
                    "expectedRejection": operation.expected_rejection,
                    "at": datetime.now(UTC).isoformat(),
                }
            except Exception as error:
                measurement = {
                    "operationId": operation.operation_id,
                    "kind": operation.kind,
                    "elapsedMs": (time.monotonic() - started) * 1000,
                    "status": None,
                    "errorClass": type(error).__name__,
                    "reconcileBeforeRetry": True,
                    "expectedStatus": False,
                    "at": datetime.now(UTC).isoformat(),
                }
            with intent.with_suffix(".result.json").open(
                "x", encoding="utf-8"
            ) as handle:
                json.dump(measurement, handle, sort_keys=True)
            measurements.append(measurement)

    started = time.monotonic()
    await asyncio.gather(*(dispatch(operation) for operation in operations))
    elapsed = time.monotonic() - started
    latencies = [item["elapsedMs"] for item in measurements]
    counts = Counter(str(item["status"]) for item in measurements)
    return {
        "phase": phase,
        "executionId": execution_id,
        "requests": len(measurements),
        "concurrency": concurrency,
        "durationSeconds": elapsed,
        "requestsPerSecond": len(measurements) / elapsed if elapsed else None,
        "statusCounts": dict(counts),
        "p50Ms": percentile(latencies, 0.5),
        "p95Ms": percentile(latencies, 0.95),
        "p99Ms": percentile(latencies, 0.99),
        "measurements": measurements,
        "managedAcceptance": "observations only; effect/operational/recovery reconciliation required",
    }


def validate_results(
    plan: dict[str, Any],
    phases: list[dict[str, Any]],
    correlations: dict[str, Any],
    *,
    evidence_directory: Path | None = None,
) -> dict[str, Any]:
    def retained(path: str, expected: str) -> None:
        require(evidence_directory is not None, "native evidence directory required")
        assert evidence_directory is not None
        root = evidence_directory.resolve()
        target = (root / path).resolve()
        require(
            target.is_relative_to(root), "native evidence escaped retained directory"
        )
        require(
            target.is_file() and target.stat().st_size <= 8000000,
            "bounded native artifact required",
        )
        require(
            hashlib.sha256(target.read_bytes()).hexdigest() == expected,
            "native artifact hash differs",
        )

    require(
        sum(item["requests"] for item in phases) <= plan["requestBudget"],
        "total campaign request allowance exceeded",
    )
    observed = {item["phase"] for item in phases}
    assertions: dict[str, dict[str, Any]] = {}
    for name in plan["phases"]:
        group = [item for item in phases if item["phase"] == name]
        assertions[name] = {
            "status": "unproved" if not group else "accepted",
            "observations": len(group),
        }
        if any(
            not row["expectedStatus"] for item in group for row in item["measurements"]
        ):
            assertions[name]["status"] = "failed"
        elif group and not any(
            200 <= row["status"] < 300
            for item in group
            for row in item["measurements"]
            if row["status"] is not None
        ):
            assertions[name]["status"] = "unproved"
    ramp = {item.get("concurrency") for item in phases if item["phase"] == "ramp"}
    if assertions["ramp"]["status"] == "accepted" and not set(
        plan["rampConcurrencies"]
    ).issubset(ramp):
        assertions["ramp"]["status"] = "unproved"
    rejections = [
        row
        for item in phases
        for row in item["measurements"]
        if row["status"] in (413, 429, 503)
    ]
    assertions["bounded-rejection"] = {
        "status": "accepted" if rejections else "unproved",
        "count": len(rejections),
    }
    for name in DIMENSIONS:
        item = correlations.get("dimensions", {}).get(name)
        if item is None:
            assertions["dimension:" + name] = {"status": "unproved"}
            continue
        require(
            item["sourceKind"]
            in ("application-native", "database-native", "provider-native"),
            "dimension lacks native observation",
        )
        require(
            bool(item["evidenceSha256"])
            and item["unit"]
            and item["measuredValue"] is not None,
            "dimension lacks measurement/unit/evidence",
        )
        retained(item["evidencePath"], item["evidenceSha256"])
        assertions["dimension:" + name] = {"status": "accepted", "measurement": item}
    for fault in plan["selectedFaults"]:
        receipt = correlations.get("faults", {}).get(fault)
        status = "unproved"
        if receipt is not None:
            require(
                receipt["faultResourceId"] in correlations["approvedFaultResourceIds"],
                "fault outside approved scope",
            )
            require(
                receipt["nativeApplySha256"] and receipt["nativeRestoreSha256"],
                "fault mutation/readback evidence absent",
            )
            retained(receipt["nativeApplyPath"], receipt["nativeApplySha256"])
            retained(receipt["nativeRestorePath"], receipt["nativeRestoreSha256"])
            require(
                receipt["effectsBefore"] == receipt["effectsAfterReconciliation"],
                "recovery repeated/lost durable effects",
            )
            require(
                receipt["recoverySeconds"] >= 0
                and receipt["recoverySeconds"]
                <= receipt["approvedRecoveryDeadlineSeconds"],
                "recovery exceeded approved deadline",
            )
            require(
                receipt["successfulPostRecoveryRequestIds"],
                "no actual post-recovery requests",
            )
            successes = {
                row["operationId"]
                for phase in phases
                if phase["phase"] == "recovery"
                for row in phase["measurements"]
                if row["status"] is not None
                and 200 <= row["status"] < 300
                and row["expectedStatus"]
            }
            require(
                set(receipt["successfulPostRecoveryRequestIds"]).issubset(successes),
                "post-recovery request evidence does not match",
            )
            status = "accepted"
        assertions["fault:" + fault] = {"status": status}
    for profile in plan["profiles"]:
        observed_profile = correlations.get("profiles", {}).get(profile["name"])
        status = "unproved"
        if profile["name"] == "abusive-boundary" and any(
            row.get("kind") == "oversized-upload"
            and row["status"] == 413
            and row.get("expectedRejection")
            and row["expectedStatus"]
            for phase in phases
            for row in phase["measurements"]
        ):
            status = "accepted"
        if observed_profile is not None:
            retained(
                observed_profile["evidencePath"], observed_profile["evidenceSha256"]
            )
            require(
                all(
                    observed_profile["observed"].get(key) == value
                    for key, value in profile.items()
                    if key not in {"name", "expectedRejection"}
                ),
                "observed fixture size differs from prepared profile",
            )
            status = "accepted"
        assertions["profile:" + profile["name"]] = {"status": status}
    return {
        "assertions": assertions,
        "phasesObserved": sorted(observed),
        "supportedCohort": None,
        "publishedLimits": "only measured settings/dimensions, never inferred from fixture size",
        "fullCapacityClosure": all(
            item["status"] == "accepted" for item in assertions.values()
        ),
        "cleanupRequired": True,
    }


def admit_row_lock(
    stage: dict[str, Any], fixture: dict[str, Any], deadline: datetime
) -> dict[str, Any]:
    import uuid

    lock = stage["rowLock"]
    expected = {
        "canvasId": fixture["canvasId"],
        "workspaceId": fixture["workspaceId"],
        "ownerId": fixture["userId"],
    }
    substitutions = {
        "PRIMARY_CANVAS": expected["canvasId"],
        "PRIMARY_WORKSPACE": expected["workspaceId"],
        "PRIMARY_USER": expected["ownerId"],
    }
    require(
        lock["faultSource"] == "postgresql-exact-core-canvas-row",
        "unapproved lock source",
    )
    require(
        resolve_templates(lock["target"], substitutions) == expected,
        "lock target differs from accepted core scope",
    )
    require(
        type(lock["holdSeconds"]) is int and 1 <= lock["holdSeconds"] <= 600,
        "row lock duration outside approved bound",
    )
    require(
        (deadline - datetime.now(UTC)).total_seconds() >= lock["holdSeconds"] + 60,
        "insufficient authority for lock rollback and recovery",
    )
    return {
        **{key: uuid.UUID(value) for key, value in expected.items()},
        "holdSeconds": lock["holdSeconds"],
    }


@asynccontextmanager
async def scoped_row_lock(
    db: Any, binding: dict[str, Any], journal: Any
) -> AsyncIterator[dict[str, Any]]:
    """Hold exactly one accepted canvas row, sample actual waits, always roll back."""
    from sqlalchemy import text
    from opencanvas_api.services.operational_observations import (
        observe_database_lock_wait,
    )

    require(
        db.engine.dialect.name == "postgresql",
        "real PostgreSQL row-lock semantics required",
    )
    receipt: dict[str, Any] = {
        "faultSource": "postgresql-exact-core-canvas-row",
        "target": {
            key: str(binding[key]) for key in ("canvasId", "workspaceId", "ownerId")
        },
        "holdSeconds": binding["holdSeconds"],
        "waitObservations": [],
        "rollbackVerified": False,
    }
    released = asyncio.Event()
    timer = sampler = None
    async with db.sessions() as session:
        started = time.monotonic()
        try:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await session.execute(text("SET LOCAL statement_timeout = '10s'"))
            row = await session.scalar(
                text(
                    "SELECT c.id FROM canvases c JOIN workspaces w ON w.id=c.workspace_id WHERE c.id=:canvasId AND c.workspace_id=:workspaceId AND w.owner_id=:ownerId AND w.deleted_at IS NULL AND w.lifecycle_state != 'deleted' FOR UPDATE OF c"
                ),
                {key: binding[key] for key in ("canvasId", "workspaceId", "ownerId")},
            )
            require(row is not None, "exact owned synthetic canvas is absent")
            receipt["acquisitionWaitMs"] = (time.monotonic() - started) * 1000
            started = time.monotonic()
            receipt["holderPid"] = int(
                await session.scalar(text("SELECT pg_backend_pid()"))
            )
            receipt["acquiredAt"] = datetime.now(UTC).isoformat()
            journal.step(
                "capacity-row-lock-acquired",
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "waitObservations"
                },
            )

            async def release_after_bound() -> None:
                await asyncio.sleep(binding["holdSeconds"])
                await session.rollback()
                receipt["releasedAt"] = datetime.now(UTC).isoformat()
                receipt["actualHoldSeconds"] = time.monotonic() - started
                released.set()

            async def sample_waits() -> None:
                while not released.is_set():
                    async with db.sessions() as observation:
                        rows = (
                            (
                                await observation.execute(
                                    text(
                                        "SELECT wait_event_type, wait_event, count(*) AS blocked FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user AND :holder=ANY(pg_blocking_pids(pid)) GROUP BY wait_event_type, wait_event"
                                    ),
                                    {"holder": receipt["holderPid"]},
                                )
                            )
                            .mappings()
                            .all()
                        )
                        measured_wait = await observe_database_lock_wait(observation)
                        receipt["waitObservations"].append(
                            {
                                "at": datetime.now(UTC).isoformat(),
                                "ownRoleDatabasePendingLockWaitMs": measured_wait,
                                "blocked": sum(int(row["blocked"]) for row in rows),
                                "events": [
                                    {
                                        "type": row["wait_event_type"],
                                        "event": row["wait_event"],
                                        "count": int(row["blocked"]),
                                    }
                                    for row in rows
                                ],
                            }
                        )
                        await observation.rollback()
                    await asyncio.sleep(1)

            timer = asyncio.create_task(release_after_bound())
            sampler = asyncio.create_task(sample_waits())
            yield receipt
        finally:
            for task in (timer, sampler):
                if task is not None and not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(
                *(task for task in (timer, sampler) if task is not None),
                return_exceptions=True,
            )
            await session.rollback()
            released.set()
            receipt.setdefault("releasedAt", datetime.now(UTC).isoformat())
            receipt.setdefault("actualHoldSeconds", time.monotonic() - started)
            if "holderPid" in receipt:
                async with db.sessions() as check:
                    remaining = int(
                        await check.scalar(
                            text(
                                "SELECT count(*) FROM pg_locks WHERE pid=:holder AND locktype='transactionid' AND mode='ExclusiveLock'"
                            ),
                            {"holder": receipt["holderPid"]},
                        )
                    )
                    await check.rollback()
                receipt["holderTransactionLocksAfter"] = remaining
                receipt["rollbackVerified"] = remaining == 0
                journal.step("capacity-row-lock-released", receipt)
                require(remaining == 0, "row-lock holder transaction not released")
            errors = [value for value in outcomes if isinstance(value, Exception)]
            require(not errors, "row-lock timer/native wait sampler failed")


async def run_bound_phase(
    api: Any,
    fixture: dict[str, Any],
    plan: dict[str, Any],
    readbacks: dict[str, Any],
    args: Any,
    deadline: datetime,
) -> dict[str, Any]:
    """Actual HTTP adapter behind pilot_application_probe's source/authority gate."""
    import httpx
    from opencanvas_api.core.config import Settings
    from infra.milestone_7_8.pilot_application_probe import Api

    capacity = plan["capacityProof"]
    stages = plan["capacityStages"]
    require(
        type(args.capacity_stage) is int and 0 <= args.capacity_stage < len(stages),
        "exact capacity stage required",
    )
    stage = stages[args.capacity_stage]
    require(
        args.capacity_operations is not None, "bound capacity operations file required"
    )
    raw = args.capacity_operations.read_bytes()
    require(
        len(raw) <= 250000
        and hashlib.sha256(raw).hexdigest() == stage["operationsSha256"],
        "capacity operation file differs from approval",
    )
    app = next(
        record["response"]["body"]
        for record in readbacks["resources"]
        if record["request"]["resourceId"].lower()
        == plan["applicationResourceId"].lower()
    )
    env = {
        item["name"]: item
        for container in app["properties"]["template"]["containers"]
        for item in container["env"]
    }
    actual = {
        name: int(env["OPENCANVAS_" + name.upper()]["value"])
        if "OPENCANVAS_" + name.upper() in env
        else Settings.model_fields[name].default
        for name in SETTINGS
    }
    require(
        actual == capacity["settings"],
        "deployed enforced limits differ from capacity plan",
    )
    records = json.loads(raw)
    if stage.get("kind") == "fixture":
        from infra.milestone_7_8.capacity_fixtures import run_setup

        require(args.capacity_stage == 0, "fixture setup must precede measured phases")
        require(
            isinstance(records, dict),
            "exact private fixture package required",
        )
        require(
            stage["operationsSha256"] == plan["capacityFixturePackageSha256"],
            "fixture source binding differs",
        )
        output_root = args.output.with_suffix(".capacity")
        output_root.mkdir(exist_ok=False)
        return await run_setup(api, plan, records, args, deadline, output_root)
    require(
        isinstance(records, list) and 1 <= len(records) <= 900,
        "per-job evidence export bound exceeded",
    )
    substitutions = {
        "PRIMARY_USER": fixture["userId"],
        "PRIMARY_WORKSPACE": fixture["workspaceId"],
        "PRIMARY_CANVAS": fixture["canvasId"],
        "PRIMARY_DOCUMENT": fixture["primary"]["documentId"],
        "SECONDARY_USER": fixture["foreign"]["userId"],
        "SECONDARY_WORKSPACE": fixture["foreign"]["workspaceId"],
        "SECONDARY_CANVAS": fixture["foreign"]["canvasId"],
        "EXECUTION_ID": args.execution_id,
    }
    substitutions.update(core_recovery_document_slots(fixture))
    additional = None
    credentials = None
    if getattr(args, "capacity_fixture", None) is not None:
        additional = json.loads(args.capacity_fixture.read_text())
        require(
            additional.get("sourceCommit") == plan["sourceCommit"]
            and additional.get("imageDigest") == plan["imageDigest"]
            and additional.get("operation") == "capacity",
            "capacity fixture release differs",
        )
        require(
            additional.get("fixturePackageSha256")
            == plan["capacityFixturePackageSha256"],
            "capacity fixture came from a different prepared package",
        )
        require(
            getattr(args, "capacity_accounts", None) is not None,
            "source-bound private capacity accounts required",
        )
        credential_bytes = args.capacity_accounts.read_bytes()
        require(
            hashlib.sha256(credential_bytes).hexdigest()
            == plan["capacityFixturePackageSha256"],
            "capacity accounts differ from prepared package",
        )
        credentials = json.loads(credential_bytes)
        for index, canvas in enumerate(additional["capacityFixture"]["canvases"]):
            substitutions.update(
                {
                    f"CAPACITY_{index}_USER": canvas["userId"],
                    f"CAPACITY_{index}_WORKSPACE": canvas["workspaceId"],
                    f"CAPACITY_{index}_CANVAS": canvas["canvasId"],
                    f"CAPACITY_{index}_WORKFLOW": canvas["workflow"]["versions"][0][
                        "versionId"
                    ],
                    f"CAPACITY_{index}_AGENT": canvas["agent"]["agentId"],
                    f"CAPACITY_{index}_NOTE_0": canvas["canonicalNoteIds"][0],
                    f"CAPACITY_{index}_NOTE_1": canvas["canonicalNoteIds"][1],
                }
            )
            for number, document in enumerate(canvas["documents"]):
                substitutions[f"CAPACITY_{index}_DOCUMENT_{number}"] = document[
                    "documentId"
                ]
    records = resolve_templates(records, substitutions)
    operations = [
        Operation(**{**item, "expected_statuses": tuple(item["expected_statuses"])})
        for item in records
    ]
    lock_binding = (
        admit_row_lock(stage, fixture, deadline) if "rowLock" in stage else None
    )
    recovery_operations: list[Operation] = []
    if lock_binding is not None:
        recovery_records = resolve_templates(
            stage["rowLock"]["recoveryOperations"], substitutions
        )
        require(
            isinstance(recovery_records, list) and 1 <= len(recovery_records) <= 8,
            "bounded explicit lock recovery operations required",
        )
        recovery_operations = [
            Operation(**{**item, "expected_statuses": tuple(item["expected_statuses"])})
            for item in recovery_records
        ]
        require(
            stage["phase"] == "failure-under-load"
            and all(
                op.actor_id == fixture["userId"]
                and op.workspace_id == fixture["workspaceId"]
                and op.path == f"/api/v1/canvases/{fixture['canvasId']}/nodes"
                and op.method == "POST"
                for op in operations + recovery_operations
            ),
            "row-lock pressure/recovery escaped exact synthetic canvas writes",
        )
        require(
            not (
                {op.operation_id for op in operations}
                & {op.operation_id for op in recovery_operations}
            ),
            "row-lock recovery cannot replay uncertain writes",
        )
    app = next(
        record["response"]["body"]
        for record in readbacks["resources"]
        if record["request"]["resourceId"].lower()
        == plan["applicationResourceId"].lower()
    )
    env = {
        item["name"]: item
        for container in app["properties"]["template"]["containers"]
        for item in container["env"]
    }
    actual = {}
    for name in SETTINGS:
        item = env.get("OPENCANVAS_" + name.upper())
        actual[name] = (
            int(item["value"])
            if item is not None
            else Settings.model_fields[name].default
        )
    require(
        actual == capacity["settings"],
        "deployed enforced limits differ from capacity plan",
    )
    output_root = args.output.with_suffix(".capacity")
    output_root.mkdir(exist_ok=False)
    if args.capacity_stage:
        require(
            args.capacity_budget is not None,
            "previous cumulative budget receipt required",
        )
        budget = args.capacity_budget.read_bytes()
        require(args.before is not None, "previous native phase receipt required")
        previous = json.loads(args.before.read_text())
        require(
            previous.get("sourceCommit") == plan["sourceCommit"]
            and previous.get("imageDigest") == plan["imageDigest"]
            and previous.get("operation") == "capacity"
            and previous.get("capacityStage") == args.capacity_stage - 1,
            "previous capacity checkpoint differs",
        )
        require(
            hashlib.sha256(budget).hexdigest() == previous["budgetReceiptSha256"],
            "cumulative budget carry differs from admitted checkpoint",
        )
        with (output_root / "capacity-budget.json").open("xb") as stream:
            stream.write(budget)
    actors = {
        fixture["userId"]: {
            "workspaceId": fixture["workspaceId"],
            "canvasId": fixture["canvasId"],
            "secondary": False,
        },
        fixture["foreign"]["userId"]: {**fixture["foreign"], "secondary": True},
    }
    if additional is not None:
        for canvas in additional["capacityFixture"]["canvases"]:
            identity = canvas["userId"]
            if identity not in actors:
                actors[identity] = {
                    "workspaceId": canvas["workspaceId"],
                    "canvasId": canvas["canvasId"],
                    "secondary": False,
                    "capacityAccount": canvas["accountIndex"],
                    "scopes": [],
                }
            actors[identity]["scopes"].append(
                (canvas["workspaceId"], canvas["canvasId"])
            )
    require(
        all(
            op.actor_id in actors
            and op.workspace_id
            in {
                item[0]
                for item in actors[op.actor_id].get(
                    "scopes",
                    [
                        (
                            actors[op.actor_id]["workspaceId"],
                            actors[op.actor_id]["canvasId"],
                        )
                    ],
                )
            }
            for op in operations
        ),
        "operation actor/workspace differs from accepted fixture",
    )
    for operation in operations:
        actor = actors[operation.actor_id]
        scopes = actor.get("scopes", [(actor["workspaceId"], actor["canvasId"])])
        prefixes = tuple(
            prefix
            for workspace, canvas in scopes
            if workspace == operation.workspace_id
            for prefix in (
                f"/api/v1/canvases/{canvas}/",
                f"/api/v1/workspaces/{workspace}/",
            )
        )
        require(
            operation.path.startswith(prefixes),
            "capacity operation escaped accepted actor scope",
        )
        require(operation.method in {"GET", "POST"}, "unprepared mutation method")
        if (
            operation.method == "POST"
            and not operation.path.endswith("/documents/search")
            and not operation.path.endswith("/run")
        ):
            require(
                isinstance(operation.payload, dict)
                and bool(operation.payload.get("idempotencyKey")),
                "mutation must bind a distinct idempotency key",
            )
    async with AsyncExitStack() as stack:
        apis = {}
        for identity in {op.actor_id for op in operations}:
            actor = actors[identity]
            if actor["secondary"] or "capacityAccount" in actor:
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=api.client.base_url,
                        timeout=45,
                        follow_redirects=False,
                        trust_env=False,
                    )
                )
                selected = Api(client, api.journal, api.execution)
            else:
                selected = api
            if "capacityAccount" in actor:
                assert credentials is not None
                account = credentials["accounts"][actor["capacityAccount"]]
                signed = await selected.request(
                    "POST",
                    "/api/v1/auth/signin",
                    secret=True,
                    data={"email": account["email"], "password": account["password"]},
                )
                selected.csrf = signed["csrfToken"]
                user = signed["user"]
            else:
                user = await selected.signin(secondary=actor["secondary"])
            require(user["id"] == identity, "authenticated actor differs from fixture")
            apis[identity] = selected

        async def execute(operation: Operation) -> Response:
            selected = apis[operation.actor_id]
            selected.journal.check_time()
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            require(remaining > 0, "capacity proof deadline expired")
            timeout = (
                lock_binding["holdSeconds"] + 30 if lock_binding is not None else 45
            )
            response = await selected.client.request(
                operation.method,
                operation.path,
                json=operation.payload,
                headers={"X-CSRF-Token": selected.csrf},
                timeout=min(timeout, remaining),
            )
            expected_state = True
            if (
                operation.expected_json is not None
                and 200 <= response.status_code < 300
            ):
                observed_body = response.json()
                expected_state = all(
                    observed_body.get(key) == value
                    for key, value in operation.expected_json.items()
                )
            effect_ids: tuple[str, ...] = ()
            if 200 <= response.status_code < 300 and "json" in response.headers.get(
                "content-type", ""
            ):
                body = response.json()
                if isinstance(body, dict):
                    effect_ids = tuple(
                        str(body[key])
                        for key in (
                            "id",
                            "executionId",
                            "requestId",
                            "invocationId",
                            "workflowExecutionId",
                        )
                        if body.get(key)
                    )
            return Response(
                response.status_code,
                len(response.content),
                hashlib.sha256(response.content).hexdigest(),
                response.headers.get("x-request-id"),
                response.headers.get("retry-after"),
                effect_ids,
                expected_state,
            )

        common = {
            "plan": capacity,
            "execute": execute,
            "deadline": deadline,
            "execution_id": args.execution_id,
        }
        directory = output_root / ("phase-" + str(args.capacity_stage))
        if lock_binding is None:
            result = await run_phase(
                operations,
                phase=stage["phase"],
                concurrency=stage["concurrency"],
                evidence_directory=directory,
                **common,
            )
        else:
            from infra.milestone_7_8.pilot_application_probe import database

            reserve_requests(
                directory,
                capacity,
                len(operations) + len(recovery_operations),
                args.execution_id,
            )
            db, _ = database(plan, restored=False, worker=False)
            stack.push_async_callback(db.dispose)
            async with scoped_row_lock(db, lock_binding, api.journal) as lock_receipt:
                result = await run_phase(
                    operations,
                    phase=stage["phase"],
                    concurrency=stage["concurrency"],
                    evidence_directory=directory,
                    reservation_applied=True,
                    **common,
                )
            recovery = await run_phase(
                recovery_operations,
                phase="recovery",
                concurrency=1,
                evidence_directory=output_root
                / ("phase-" + str(args.capacity_stage) + "-recovery"),
                reservation_applied=True,
                **common,
            )
            result["recoveryPhase"] = recovery
            result["rowLock"] = lock_receipt
            result["rowLock"]["nativeBlockingObserved"] = any(
                row["blocked"] > 0 for row in lock_receipt["waitObservations"]
            )
            result["rowLock"]["successfulNewRecoveryWrites"] = all(
                row["expectedStatus"] and row["status"] == 201
                for row in recovery["measurements"]
            )
    result["capacityStage"] = args.capacity_stage
    result["budgetReceiptSha256"] = hashlib.sha256(
        (output_root / "capacity-budget.json").read_bytes()
    ).hexdigest()
    result["settingsMatchedNativeReadback"] = True
    result["actorsObserved"] = len({op.actor_id for op in operations})
    return result


def core_recovery_document_slots(fixture: dict[str, Any]) -> dict[str, str]:
    """Resolve only existing documents from the admitted core receipt, never operator IDs."""
    result = {}
    seen = {fixture["primary"]["documentId"]}
    for key in ("queued", "deletion"):
        if key not in fixture:
            continue  # A requested absent slot is rejected by resolve_templates.
        document = fixture[key]
        value = document.get("documentId")
        require(isinstance(value, str), "core document ID absent")
        require(str(uuid.UUID(value)) == value, "noncanonical core document ID")
        require(value not in seen, "core recovery document must be distinct")
        for field in ("workspaceId", "canvasId", "userId"):
            require(
                field not in document or document[field] == fixture[field],
                "core recovery document scope differs",
            )
        seen.add(value)
        result[key.upper() + "_DOCUMENT"] = value
    return result


def resolve_templates(value: Any, substitutions: dict[str, str]) -> Any:
    """Only approved symbolic slots derive IDs from the accepted fixture/native job."""
    if isinstance(value, str):

        def substitute(match: re.Match[str]) -> str:
            key = match[1]
            require(key in substitutions, "unknown operation-template slot")
            return substitutions[key]

        return re.sub(r"\$\{([A-Z_0-9]+)\}", substitute, value)
    if isinstance(value, list):
        return [resolve_templates(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {
            key: resolve_templates(item, substitutions) for key, item in value.items()
        }
    return value
