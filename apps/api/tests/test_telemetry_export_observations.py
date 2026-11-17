from __future__ import annotations

import json

from apps.api.tests.test_observability import _telemetry

from opencanvas_api.services.observability import InMemoryTelemetrySink
from scripts.telemetry_destination import destination_rows


def operation(telemetry):
    return telemetry.record_metric(
        "mobius.api.requests", 1, labels={"method": "GET", "outcome": "success"}
    )


async def test_actual_export_failures_and_recovery_arrive_without_feedback_loop():
    sink = InMemoryTelemetrySink(fail=True)
    telemetry, _ = _telemetry(sink=sink, telemetry_retry_limit=2)
    operation(telemetry)
    assert not await telemetry.flush()
    assert telemetry.counters.export_failures == 3
    assert telemetry.buffered == 1
    sink.fail = False
    assert await telemetry.flush()
    assert len([s for s in sink.signals if s.name == "telemetry.export.failed"]) == 3
    for _ in range(3):
        operation(telemetry)
        assert await telemetry.flush()
    health = [
        s.payload["value"] for s in sink.signals if s.name == "mobius.telemetry.export_health"
    ]
    assert health == [0, 1, 1, 1]
    buffers = [s.payload["value"] for s in sink.signals if s.name == "mobius.telemetry.buffer"]
    assert buffers[-3:] == [0, 0, 0]
    assert len(
        destination_rows(
            {
                "resource": {"schema": "mobius-operational-v1"},
                "signals": [s.as_dict() for s in sink.signals],
            },
            [
                {
                    key: getattr(telemetry, key)
                    for key in ("service", "environment", "release", "deployment")
                }
            ],
        )
    ) == len(sink.signals)
    exported = len(sink.signals)
    assert await telemetry.flush()
    assert len(sink.signals) == exported
    assert await telemetry.close()


async def test_diagnostics_do_not_exceed_destination_batch_limit():
    class CountingSink(InMemoryTelemetrySink):
        def __init__(self):
            super().__init__()
            self.sizes = []

        async def export(self, signals):
            self.sizes.append(len(signals))
            await super().export(signals)

    sink = CountingSink()
    telemetry, _ = _telemetry(sink=sink, telemetry_batch_size=512, telemetry_buffer_size=512)
    operation(telemetry)
    assert await telemetry.flush()
    for _ in range(512):
        operation(telemetry)
    assert await telemetry.close()
    assert sink.sizes == [1, 512, 6]
    assert telemetry.counters.exported == 513
    assert telemetry.buffered == 0


async def test_loss_is_a_delta_and_diagnostic_reserve_and_wire_batch_stay_bounded():
    sink = InMemoryTelemetrySink(fail=True)
    telemetry, _ = _telemetry(sink=sink, telemetry_retry_limit=0, telemetry_buffer_size=16)
    for _ in range(20):
        operation(telemetry)
    assert telemetry.counters.dropped == 4
    for _ in range(12):
        assert not await telemetry.flush()
        assert telemetry.buffered <= 16
        assert len(telemetry._export_observations) <= 32
    sink.fail = False
    assert await telemetry.flush()
    operation(telemetry)
    assert await telemetry.flush()
    operation(telemetry)
    assert await telemetry.flush()
    losses = [s.payload["value"] for s in sink.signals if s.name == "mobius.telemetry.dropped"]
    assert losses[-1] == 0 and any(value > 0 for value in losses)
    assert all(s.component in {"api", "telemetry"} for s in sink.signals)
    assert "telemetry_sink_unavailable" not in json.dumps([s.as_dict() for s in sink.signals])
    assert await telemetry.close()
