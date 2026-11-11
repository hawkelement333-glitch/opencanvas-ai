from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy import text

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.session import Database


async def sample(
    connections: Callable[[], Awaitable[tuple[int, int]]],
    request: Callable[[], Awaitable[int]],
    *,
    batches: int = 5,
    concurrency: int = 8,
    clock: Callable[[], float] = time.perf_counter,
    workload: asyncio.Task[object] | None = None,
    application_latencies_ms: list[float] | None = None,
    application_observed_at_utc: list[str] | None = None,
) -> dict[str, Any]:
    """Collect bounded raw samples; this alone never proves replica or rollout state."""
    if not 1 <= batches <= 20 or not 1 <= concurrency <= 16:
        raise ValueError("measurement bounds are invalid")
    started = datetime.now(UTC).isoformat()
    latencies: list[float] = []
    connection_times: list[str] = []
    peak = 0

    async def timed_request() -> float:
        before = clock()
        status = await request()
        elapsed = (clock() - before) * 1000
        if status != 200 or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("private readiness request failed")
        return elapsed

    observed_batches = 0
    while observed_batches < batches or (workload is not None and not workload.done()):
        if observed_batches >= 1200:
            raise ValueError("measurement window exceeded its bound")
        counts, *timings = await asyncio.gather(
            connections(), *(timed_request() for _ in range(concurrency))
        )
        if (
            not isinstance(counts, tuple)
            or len(counts) != 2
            or any(type(count) is not int or count < 0 for count in counts)
        ):
            raise ValueError("connection sample is invalid")
        peak = max(peak, sum(counts))
        connection_times.append(datetime.now(UTC).isoformat())
        latencies.extend(cast(float, value) for value in timings)
        observed_batches += 1
        if workload is not None and not workload.done():
            await asyncio.sleep(0.25)
    if workload is not None:
        await workload
    application_p95 = None
    if application_latencies_ms is not None:
        if not application_latencies_ms or any(
            not math.isfinite(value) or value < 0 for value in application_latencies_ms
        ):
            raise ValueError("application request timings are missing or invalid")
        if application_observed_at_utc is None or len(application_observed_at_utc) != len(
            application_latencies_ms
        ):
            raise ValueError("application request timestamps are missing")
        application = sorted(application_latencies_ms)
        application_p95 = application[math.ceil(len(application) * 0.95) - 1]
    ordered = sorted(latencies)
    return {
        "version": "m7.8-raw-measurement-sample-v1",
        "status": "blocked-unverified",
        "startedAtUtc": started,
        "endedAtUtc": datetime.now(UTC).isoformat(),
        "connectionSamples": observed_batches,
        "connectionObservationTimesUtc": connection_times,
        "privateReadinessRequests": len(ordered),
        "observedRuntimeConnectionPeak": peak,
        "readinessP95Ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "applicationP95Ms": application_p95,
        "applicationRequests": len(application_latencies_ms or []),
        "applicationRequestTimesUtc": application_observed_at_utc or [],
    }


async def collect(
    exercise: Callable[[list[float], list[str]], Coroutine[Any, Any, object]] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    settings.require_database_role(DatabaseRole.OBSERVABILITY)
    manifest = load_principal_manifest()
    base_url = os.environ.get("M78_PRIVATE_API_URL", "")
    if not base_url.startswith("https://"):
        raise ValueError("private HTTPS API URL is required")
    if exercise is None:
        raise ValueError("bounded application exercise is required")
    database = Database.from_settings(settings, expected_role=DatabaseRole.OBSERVABILITY)
    try:
        async with database.engine.connect() as connection:
            current = str((await connection.execute(text("SELECT current_user"))).scalar_one())
            manifest.require_current(PrincipalSlot.EVIDENCE, current_name=current)
            roles = {
                "api": manifest.principals[PrincipalSlot.API].name,
                "worker": manifest.principals[PrincipalSlot.WORKER].name,
            }

            async def connections() -> tuple[int, int]:
                result = await connection.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE usename = :api), "
                        "count(*) FILTER (WHERE usename = :worker) "
                        "FROM pg_catalog.pg_stat_activity WHERE datname = current_database()"
                    ),
                    roles,
                )
                row = result.one()
                return int(row[0]), int(row[1])

            async with httpx.AsyncClient(
                base_url=base_url, timeout=30.0, trust_env=False
            ) as client:

                async def request() -> int:
                    return (await client.get("/api/v1/health/ready")).status_code

                application_latencies: list[float] = []
                application_times: list[str] = []
                task: asyncio.Task[object] = asyncio.create_task(
                    exercise(application_latencies, application_times)
                )
                try:
                    return await sample(
                        connections, request, workload=task,
                        application_latencies_ms=application_latencies,
                        application_observed_at_utc=application_times,
                    )
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
    finally:
        await database.dispose()


def main() -> int:
    try:
        from scripts.managed_postgres_evidence import application_assertions

        async def exercise(latencies: list[float], times: list[str]) -> object:
            return await application_assertions(latencies_ms=latencies, observed_at_utc=times)

        result = asyncio.run(collect(exercise))
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    # Samples cannot be admitted until replica ceilings and rollout overlap are proved.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
