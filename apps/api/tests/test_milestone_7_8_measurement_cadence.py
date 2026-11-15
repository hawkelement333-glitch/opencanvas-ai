from datetime import UTC, datetime, timedelta

import pytest

from infra.milestone_7_8 import measurement_handoff as mh
from infra.milestone_7_8.campaign import CampaignError

BASE = datetime(2030, 1, 1, tzinfo=UTC)
SUB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
GROUP = "rg-m78-aabbccddee-target"
API = f"/subscriptions/{SUB}/resourceGroups/{GROUP}/providers/Microsoft.App/containerApps/api"
REVISION = API + "/revisions/old"
WORKER = (
    f"/subscriptions/{SUB}/resourceGroups/{GROUP}"
    "/providers/Microsoft.App/jobs/worker/executions/execution/replicas"
)


def run_window(monkeypatch, method, *, read_seconds=1.7, status="Succeeded"):
    class Clock:
        elapsed = 0.0

        @classmethod
        def now(cls, tz):
            return BASE + timedelta(seconds=cls.elapsed)

    class Future:
        def __init__(self, pool, fn, args, kwargs):
            self.pool, self.fn, self.args, self.kwargs = pool, fn, args, kwargs

        def result(self):
            if not self.pool.done:
                start, end = Clock.elapsed, Clock.elapsed
                for future in self.pool.pending:
                    Clock.elapsed = start
                    future.value = future.fn(*future.args, **future.kwargs)
                    end = max(end, Clock.elapsed)
                Clock.elapsed = end
                self.pool.done = True
            return self.value

    class Pool:
        def __init__(self, **kwargs):
            self.pending, self.done = [], False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, *args, **kwargs):
            if self.done:
                self.pending, self.done = [], False
            future = Future(self, fn, args, kwargs)
            self.pending.append(future)
            return future

    def sleep(seconds):
        Clock.elapsed += seconds

    def timestamp(seconds):
        return (BASE + timedelta(seconds=seconds)).isoformat()

    def worker(*args, **kwargs):
        before = Clock.elapsed
        Clock.elapsed += read_seconds
        return {
            "startedAtUtc": timestamp(before),
            "endedAtUtc": timestamp(Clock.elapsed),
            "scopePath": WORKER,
            "complete": True,
            "pages": [
                {
                    "value": [
                        {
                            "name": f"w{i}",
                            "id": WORKER + f"/w{i}",
                            "properties": {"runningState": "Running"},
                        }
                        for i in range(4)
                    ]
                }
            ],
        }

    class Measurement:
        subscription, group, worker, sampler = SUB, GROUP, "worker", "sampler"
        runner, api_id = None, API

        def remaining(self):
            return 200 - Clock.elapsed

        def start_job(self, *args):
            Clock.elapsed = 2.848455
            return "sampler-execution"

        def sampler_status(self, execution):
            Clock.elapsed += 1.5
            return status if Clock.elapsed >= 44 else "Running"

        def active_revisions(self):
            Clock.elapsed += 1.6
            return {"old": {"id": REVISION}}

        def revision_replicas(self, revision):
            Clock.elapsed += read_seconds
            return [
                {
                    "name": f"a{i}",
                    "id": REVISION + f"/replicas/a{i}",
                    "properties": {"runningState": "Running"},
                }
                for i in range(4)
            ]

        def read_sample(self, *args):
            times = [timestamp(13.096296 + i * 0.3) for i in range(99)]
            return {
                "startedAtUtc": timestamp(12.907257),
                "endedAtUtc": timestamp(43.042613),
                "applicationRequestTimesUtc": times,
                "connectionObservationTimesUtc": times,
                "applicationRequests": len(times),
                "connectionSamples": len(times),
                "applicationRequestDurationsMs": [10] * len(times),
                "applicationP95Ms": 10,
                "observedRuntimeConnectionPeak": 20,
            }

    monkeypatch.setattr(mh, "datetime", Clock)
    monkeypatch.setattr(mh, "ThreadPoolExecutor", Pool)
    monkeypatch.setattr(mh, "collect_worker_replicas", worker)
    monkeypatch.setattr(mh.time, "monotonic", lambda: Clock.elapsed)
    monkeypatch.setattr(mh.time, "sleep", sleep)
    return method(Measurement(), "workspace", "execution", ("old",))


def test_concurrent_cadence_covers_start_and_end_without_changing_validators(monkeypatch):
    sample, receipt = run_window(monkeypatch, mh.CampaignMeasurement.window)
    assert sample["startedAtUtc"].startswith("2030-01-01T00:00:12.907257")
    assert receipt["samplerExecution"] == "sampler-execution"


def test_slow_readbacks_still_fail_closed(monkeypatch):
    with pytest.raises(CampaignError):
        run_window(monkeypatch, mh.CampaignMeasurement.window, read_seconds=6)


def test_failed_sampler_is_never_accepted(monkeypatch):
    with pytest.raises(CampaignError, match="terminal success"):
        run_window(monkeypatch, mh.CampaignMeasurement.window, status="Failed")
