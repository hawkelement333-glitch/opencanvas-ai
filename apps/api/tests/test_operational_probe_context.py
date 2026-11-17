from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from infra.milestone_7_8.operational_service_probe import queue_transitions
from infra.milestone_7_8.pilot_application_probe import production_operation_telemetry

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import SYSTEM_USER_ID, SYSTEM_WORKSPACE_ID
from opencanvas_api.services.operational_observations import current_telemetry
from tests.test_operational_observations import metrics, observer


def settings():
    return SimpleNamespace(
        telemetry_enabled=True,
        telemetry_exporter="http",
        telemetry_release="release",
        telemetry_deployment="deployment",
        telemetry_service_name="mobius-worker",
    )


PLAN = {"release": "release", "deployment": "deployment"}


async def test_probe_context_exports_actual_queue_transitions(database, monkeypatch):
    from tests.test_durable_jobs import _source

    canvas, document, _ = await _source(database)
    from opencanvas_api.db.models import Document

    async with database.sessions() as session:
        row = await session.get(Document, document)
        row.status = "ready"
        await session.commit()
    telemetry, sink = observer()
    monkeypatch.setattr(
        "opencanvas_api.services.observability.build_observability", lambda _: telemetry
    )
    journal = SimpleNamespace(
        header={"executionId": "local-actual-queue-observation"},
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        check_time=lambda: None,
        step=lambda *_: None,
    )
    fixture = {
        "workspaceId": str(SYSTEM_WORKSPACE_ID),
        "userId": str(SYSTEM_USER_ID),
        "canvasId": str(canvas),
        "queued": {"documentId": str(document)},
    }
    async with production_operation_telemetry(settings(), PLAN):
        assert current_telemetry() is telemetry
        result = await queue_transitions(
            database, Settings(processing_lease_seconds=5), fixture, journal
        )
    assert current_telemetry() is None
    assert result["elapsedSeconds"] >= 5
    assert result["maximumElapsedSeconds"] == 125
    assert result["activeFixtureJobs"] == 0
    assert result["jobId"] != result["replayJobId"]
    for name in (
        "claim_duration",
        "lease_loss",
        "dead_letters",
        "replays",
        "cancellations",
        "stale_suppression",
    ):
        values = metrics(sink, "mobius.queue." + name)
        assert len(values) == 1 and values[0] > 0


@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
async def test_probe_context_preserves_primary_failure_and_clears_context(monkeypatch, failure):
    telemetry = SimpleNamespace(
        flush=AsyncMock(side_effect=RuntimeError("export failed")), close=AsyncMock()
    )
    monkeypatch.setattr(
        "opencanvas_api.services.observability.build_observability", lambda _: telemetry
    )
    with pytest.raises(failure):
        async with production_operation_telemetry(settings(), PLAN):
            raise failure("actual operation failed")
    assert current_telemetry() is None
    telemetry.flush.assert_awaited_once()
    telemetry.close.assert_awaited_once()


async def test_probe_context_refuses_success_without_export_ack(monkeypatch):
    telemetry = SimpleNamespace(flush=AsyncMock(return_value=False), close=AsyncMock())
    monkeypatch.setattr(
        "opencanvas_api.services.observability.build_observability", lambda _: telemetry
    )
    with pytest.raises(ValueError, match="not acknowledged"):
        async with production_operation_telemetry(settings(), PLAN):
            pass
    telemetry.flush.assert_awaited_once()
    telemetry.close.assert_awaited_once()
    assert current_telemetry() is None


async def test_operational_queue_refuses_unbounded_window_before_database_access():
    journal = SimpleNamespace(deadline=datetime.now(UTC) + timedelta(seconds=20))
    with pytest.raises(ValueError, match="remaining window"):
        await queue_transitions(None, Settings(processing_lease_seconds=60), {}, journal)


@pytest.mark.parametrize(
    "field,value",
    [
        ("telemetry_release", "other"),
        ("telemetry_deployment", "other"),
        ("telemetry_service_name", "invented-probe"),
        ("telemetry_exporter", "memory"),
    ],
)
async def test_probe_context_rejects_wrong_bound_source_before_exporter(monkeypatch, field, value):
    selected = settings()
    setattr(selected, field, value)
    called = []
    monkeypatch.setattr(
        "opencanvas_api.services.observability.build_observability", lambda _: called.append(True)
    )
    with pytest.raises(ValueError, match="bound authenticated"):
        async with production_operation_telemetry(selected, PLAN):
            pytest.fail("unbound source entered")
    assert not called
