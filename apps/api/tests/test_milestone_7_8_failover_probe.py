from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from scripts.m78_failover_probe import FailoverProbe, _transition_observations
from scripts.managed_postgres_evidence import EvidenceError

from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.session import Database
from opencanvas_api.services.jobs import DocumentWorker


@pytest.mark.asyncio
async def test_disruption_setup_worker_processing_and_revoked_tenant_real_routes(
    app: FastAPI,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real app/auth/worker/indexer path; SQLite is not managed failover proof."""
    current = cast(Settings, app.dependency_overrides[get_settings]())
    settings = current.model_copy(
        update={
            "auth_test_bypass": False,
            "job_provider": "database",
            "storage_provider": "local",
            "session_secret": "synthetic-local-failover-test-session-secret",
            "auth_requests_per_ip_per_minute": 100,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setenv("OPENCANVAS_CAMPAIGN_ID", "m78-synthetic-local")
    monkeypatch.setenv("OPENCANVAS_CAMPAIGN_GENERATION_ID", "g1-synthetic")
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        httpx.AsyncClient(transport=transport, base_url="http://test") as other,
    ):
        probe = FailoverProbe(
            client,
            other,
            database,
            token="c" * 32,
            worker_execution="synthetic-execution",
        )
        await probe.setup()
        assert len(probe.requests) == 4 and len(probe.opaque_dispatches) == 4
        assert all(record["responseWithheld"] is True for record in probe.opaque_dispatches)
        worker = DocumentWorker(
            settings=settings,
            sessions=database.sessions,
            worker_id="synthetic-execution-0",
        )
        assert await worker.run_once()
        evidence = await probe.tenant_checks()
        assert len(evidence) == 64


def _observation(second: int, *, healthy: bool, claims: int, completed: int) -> dict[str, object]:
    stamp = f"2026-11-14T00:00:{second:02d}+00:00"
    return {
        "observedAtUtc": stamp,
        "apiReadPassed": healthy,
        "apiWritePassed": healthy,
        "workerDatabaseActive": healthy,
        "workerObservedAtUtc": stamp,
        "workerLatestClaimAtUtc": stamp,
        "workerLatestOutcomeAtUtc": stamp,
        "workerClaims": claims,
        "workerOutcomes": completed,
        "evidenceSha256": "a" * 64,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["complete", "no-disruption", "stale-outcome", "no-workers"])
async def test_bounded_window_requires_observed_disruption_and_new_worker_completion(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    elapsed = [0.0]

    async def sleep(_: float) -> None:
        elapsed[0] += 250

    monkeypatch.setattr("scripts.m78_failover_probe.asyncio.sleep", sleep)
    rows = [
        _observation(0, healthy=True, claims=1, completed=1),
        _observation(10, healthy=False, claims=1, completed=1),
        _observation(20, healthy=True, claims=2, completed=2),
        _observation(30, healthy=True, claims=2, completed=2),
    ]
    if scenario == "no-disruption":
        rows[1] = _observation(10, healthy=True, claims=1, completed=1)
    elif scenario == "stale-outcome":
        for row in rows[2:]:
            row["workerLatestOutcomeAtUtc"] = "2026-11-14T00:00:01+00:00"
    elif scenario == "no-workers":
        for row in rows:
            row["workerDatabaseActive"] = False
    async with httpx.AsyncClient() as client:
        probe = FailoverProbe(
            client,
            client,
            cast(Database, object()),
            token="c" * 32,
            worker_execution="worker-exact",
            clock=lambda: elapsed[0],
        )
        setup, upload = AsyncMock(), AsyncMock()
        replay, tenants = AsyncMock(return_value="d" * 64), AsyncMock(return_value="e" * 64)
        monkeypatch.setattr(probe, "setup", setup)
        monkeypatch.setattr(probe, "upload", upload)
        monkeypatch.setattr(probe, "observe", AsyncMock(side_effect=rows))
        monkeypatch.setattr(probe, "replay", replay)
        monkeypatch.setattr(probe, "tenant_checks", tenants)
        if scenario == "complete":
            value = await probe.exercise()
            assert value["status"] == "passed"
            replay.assert_awaited_once()
            tenants.assert_awaited_once()
        else:
            with pytest.raises(EvidenceError, match="did not establish"):
                await probe.exercise()
            replay.assert_not_awaited()
            tenants.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [True, False])
async def test_withheld_commit_is_resolved_before_any_replay(committed: bool) -> None:
    events: list[str] = []

    class Connection:
        async def execute(self, statement: object, *_: object) -> Any:
            if str(statement).startswith("SELECT"):
                events.append("resolve")
                rows = [{"resources": 1, "result": "result-id"}] if committed else []
                return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
            assert str(statement) == "SET TRANSACTION READ ONLY"
            return None

    @asynccontextmanager
    async def begin() -> AsyncIterator[Connection]:
        yield Connection()

    async def respond(_: httpx.Request) -> httpx.Response:
        events.append("replay")
        return httpx.Response(201, json={"id": "result-id"})

    database = cast(Database, SimpleNamespace(engine=SimpleNamespace(begin=begin)))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as c:
        probe = FailoverProbe(c, c, database, token="a" * 32, worker_execution="exact")
        probe.requests = [("/api/v1/canvases", {"idempotencyKey": "withheld"}, "canvas.create")]
        if committed:
            assert len(await probe.replay()) == 64
            assert events == ["resolve", "replay", "replay"]
        else:
            with pytest.raises(EvidenceError, match="before replay"):
                await probe.replay()
            assert events == ["resolve"]


def test_long_sampling_run_retains_real_transition_boundaries_with_bounded_console_size() -> None:
    rows: list[dict[str, object]] = []
    for second in range(900):
        row = _observation(0, healthy=not 250 <= second < 500, claims=second, completed=second)
        row["observedAtUtc"] = (datetime(2026, 11, 14, tzinfo=UTC)
                                + timedelta(seconds=second)).isoformat()
        rows.append(row)
    selected = _transition_observations(rows)
    assert selected == [rows[index] for index in (1, 249, 250, 499, 898, 899)]
    assert len(json.dumps(selected).encode()) < 8_192


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError, ConnectionRefusedError])
async def test_snapshot_connection_timeout_records_disruption_then_fresh_recovery(
    monkeypatch: pytest.MonkeyPatch, error: type[OSError],
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201 if request.method == "POST" else 200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        probe = FailoverProbe(
            client, client, cast(Database, object()), token="a" * 32,
            worker_execution="exact-worker-execution",
        )
        stamp = "2030-01-01T00:01:00+00:00"
        snapshots = AsyncMock(side_effect=[
            error("synthetic connection acquisition failure"),
            {
                "heartbeats": [{"seen": stamp} for _ in range(4)],
                "attempts": [{"started": stamp}],
                "outcomes": [{"recorded": stamp}],
            },
        ])
        monkeypatch.setattr(probe, "worker_snapshot", snapshots)
        interrupted = await probe.observe()
        recovered = await probe.observe()
        assert interrupted["apiReadPassed"] is True
        assert interrupted["apiWritePassed"] is True
        assert interrupted["workerDatabaseActive"] is False
        assert interrupted["workerObservedAtUtc"] is None
        assert interrupted["workerClaims"] == interrupted["workerOutcomes"] == 0
        assert recovered["workerDatabaseActive"] is True
        assert recovered["workerClaims"] == recovered["workerOutcomes"] == 1
        assert snapshots.await_count == 2


@pytest.mark.asyncio
async def test_snapshot_programming_failure_is_not_classified_as_disruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201 if request.method == "POST" else 200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        probe = FailoverProbe(
            client, client, cast(Database, object()), token="a" * 32,
            worker_execution="exact-worker-execution",
        )
        monkeypatch.setattr(probe, "worker_snapshot", AsyncMock(side_effect=RuntimeError("bug")))
        with pytest.raises(RuntimeError, match="bug"):
            await probe.observe()
