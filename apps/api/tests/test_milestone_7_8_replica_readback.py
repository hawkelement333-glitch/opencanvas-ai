from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.replica_readback import (
    collect_worker_replicas,
    validate_api_measurement_window,
    validate_worker_measurement_window,
    worker_replica_url,
)

SUBSCRIPTION = "00000000-0000-4000-8000-000000000100"
GROUP = "rg-m78-test"
JOB = "job-m78-test-worker"
EXECUTION = "job-m78-test-worker-abc"
URL = worker_replica_url(SUBSCRIPTION, GROUP, JOB, EXECUTION)
PATH = urlsplit(URL).path


class FakeRunner:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        if len(self.commands) > len(self.pages):
            return {"exitCode": 1, "stdout": "", "stderr": "unavailable"}
        return {"exitCode": 0, "stdout": json.dumps(self.pages[len(self.commands) - 1])}


def collect(pages: list[dict[str, object]]) -> tuple[dict[str, object], FakeRunner]:
    runner = FakeRunner(pages)
    result = collect_worker_replicas(
        runner, subscription=SUBSCRIPTION, group=GROUP, job=JOB, execution=EXECUTION
    )
    return result, runner


def test_worker_pages_preserve_full_raw_response_and_follow_exact_scope() -> None:
    next_url = URL + "&%24skiptoken=page2"
    pages = [
        {
            "value": [{"name": "replica-a", "properties": {"providerField": "retained"}}],
            "nextLink": next_url,
        },
        {"value": [{"name": "replica-b"}], "nextLink": None},
    ]
    result, runner = collect(pages)
    assert result["pages"] == pages
    assert result["complete"] is True
    assert result["workerRunningState"] == "unverified"
    assert runner.commands[1][5] == next_url


@pytest.mark.parametrize(
    "pages",
    [
        [{"nextLink": None}],
        [{"value": [], "nextLink": 3}],
        [{"value": [{"name": "same"}], "nextLink": URL + "&skip=2"}, {"value": [{"name": "SAME"}]}],
        [{"value": [], "nextLink": URL.replace(EXECUTION, "other-execution") + "&skip=2"}],
        [
            {
                "value": [],
                "nextLink": URL.replace("management.azure.com", "example.test") + "&skip=2",
            }
        ],
        [{"value": [{"name": "a", "id": PATH.replace(EXECUTION, "other") + "/a"}]}],
        [{"value": [], "nextLink": URL}],
        [{"value": [], "nextLink": URL + "&skip=2"}],
    ],
)
def test_worker_pages_reject_incomplete_duplicate_or_out_of_scope(
    pages: list[dict[str, object]],
) -> None:
    with pytest.raises(CampaignError):
        collect(pages)


API_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}"
    "/providers/Microsoft.App/containerApps/app"
)


def revision(name: str, count: int) -> dict[str, object]:
    revision_id = f"{API_ID}/revisions/{name}"
    return {
        "name": name,
        "id": revision_id,
        "replicas": [
            {
                "name": f"{name}-{i}",
                "id": f"{revision_id}/replicas/{name}-{i}",
                "properties": {"runningState": "Running"},
            }
            for i in range(count)
        ],
    }


SAMPLE: dict[str, object] = {
    "startedAtUtc": "2030-01-01T00:00:00Z",
    "endedAtUtc": "2030-01-01T00:00:10Z",
    "connectionSamples": 1,
    "connectionObservationTimesUtc": ["2030-01-01T00:00:05Z"],
    "applicationRequests": 1,
    "applicationRequestTimesUtc": ["2030-01-01T00:00:05Z"],
}


def test_api_window_requires_running_replicas_and_overlap_in_sample_window() -> None:
    observation = {"observedAtUtc": "2030-01-01T00:00:05Z", "revisions": [revision("old", 4)]}
    validate_api_measurement_window(
        SAMPLE, [observation], require_overlap=False, api_resource_id=API_ID
    )
    with pytest.raises(CampaignError, match="overlap"):
        validate_api_measurement_window(
            SAMPLE, [observation], require_overlap=True, api_resource_id=API_ID
        )
    observation["revisions"] = [revision("old", 4), revision("new", 1)]
    validate_api_measurement_window(
        SAMPLE, [observation], require_overlap=True, api_resource_id=API_ID
    )
    observation["observedAtUtc"] = "2030-01-01T00:00:11Z"
    with pytest.raises(CampaignError, match="outside"):
        validate_api_measurement_window(
            SAMPLE, [observation], require_overlap=True, api_resource_id=API_ID
        )


def test_worker_window_remains_blocked_even_with_four_records() -> None:
    capture = {
        "scopePath": PATH,
        "complete": True,
        "startedAtUtc": "2030-01-01T00:00:04Z",
        "endedAtUtc": "2030-01-01T00:00:05Z",
        "pages": [{"value": [{"name": str(i)} for i in range(4)]}],
    }
    with pytest.raises(CampaignError, match="running-state semantics are unverified"):
        validate_worker_measurement_window(SAMPLE, [capture], expected_scope=PATH)


def test_api_window_rejects_missing_timestamps_and_not_running_replicas() -> None:
    observation = {"observedAtUtc": "2030-01-01T00:00:05Z", "revisions": [revision("old", 4)]}
    incomplete = {**SAMPLE, "applicationRequestTimesUtc": []}
    with pytest.raises(CampaignError, match="timestamps are incomplete"):
        validate_api_measurement_window(
            incomplete, [observation], require_overlap=False, api_resource_id=API_ID
        )
    replicas = observation["revisions"][0]["replicas"]  # type: ignore[index]
    replicas[0]["properties"]["runningState"] = "NotRunning"
    with pytest.raises(CampaignError, match="ceiling"):
        validate_api_measurement_window(
            SAMPLE, [observation], require_overlap=False, api_resource_id=API_ID
        )
    observation["revisions"] = [revision("old", 5)]
    replicas = observation["revisions"][0]["replicas"]  # type: ignore[index]
    replicas[4]["properties"]["runningState"] = "Unknown"
    with pytest.raises(CampaignError, match="running state is unproved"):
        validate_api_measurement_window(
            SAMPLE, [observation], require_overlap=False, api_resource_id=API_ID
        )
