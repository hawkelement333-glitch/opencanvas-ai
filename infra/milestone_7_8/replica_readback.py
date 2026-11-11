from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from infra.milestone_7_8.automation_region import _safe_inventory_next_link
from infra.milestone_7_8.campaign import CampaignError, parse_utc

API_VERSION = "2023-11-02-preview"
MAX_PAGES = 100
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class Runner(Protocol):
    def run(self, command: tuple[str, ...]) -> dict[str, object]: ...


def worker_replica_url(subscription: str, group: str, job: str, execution: str) -> str:
    try:
        if (
            str(uuid.UUID(subscription)) != subscription.casefold()
            or uuid.UUID(subscription).int == 0
        ):
            raise ValueError
    except ValueError as exc:
        raise CampaignError("worker replica subscription is invalid") from exc
    if any(_SEGMENT.fullmatch(item) is None for item in (group, job, execution)):
        raise CampaignError("worker replica scope is invalid")
    return (
        f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.App/jobs/{job}/executions/{execution}/replicas"
        f"?api-version={API_VERSION}"
    )


def collect_worker_replicas(
    runner: Runner, *, subscription: str, group: str, job: str, execution: str
) -> dict[str, object]:
    """Read all raw worker replica pages, without inferring worker running state."""
    url = worker_replica_url(subscription, group, job, execution)
    expected_path = urlsplit(url).path
    seen_urls: set[str] = set()
    seen_names: set[str] = set()
    pages: list[dict[str, object]] = []
    started = datetime.now(UTC).isoformat()
    while True:
        if url.casefold() in seen_urls or len(pages) >= MAX_PAGES:
            raise CampaignError("worker replica pagination repeated or exceeded its bound")
        seen_urls.add(url.casefold())
        result = runner.run(("az", "rest", "--method", "get", "--url", url, "--output", "json"))
        if result.get("exitCode") != 0 or not isinstance(result.get("stdout"), str):
            raise CampaignError("worker replica page read failed")
        try:
            page = json.loads(str(result["stdout"]))
        except json.JSONDecodeError as exc:
            raise CampaignError("worker replica page is malformed") from exc
        if not isinstance(page, dict) or not isinstance(page.get("value"), list):
            raise CampaignError("worker replica page is incomplete")
        for item in page["value"]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise CampaignError("worker replica identity is malformed")
            name = item["name"]
            if _SEGMENT.fullmatch(name) is None or name.casefold() in seen_names:
                raise CampaignError("worker replica identity is duplicated or malformed")
            item_id = item.get("id")
            if item_id is not None and (
                not isinstance(item_id, str)
                or item_id.casefold() != f"{expected_path}/{name}".casefold()
            ):
                raise CampaignError("worker replica identity is out of scope")
            seen_names.add(name.casefold())
        pages.append(page)
        continuation = page.get("nextLink")
        if continuation is None or continuation == "":
            break
        if not isinstance(continuation, str):
            raise CampaignError("worker replica continuation is malformed")
        url = _safe_inventory_next_link(
            continuation,
            subscription_id=subscription,
            expected_path=expected_path,
            api_version=API_VERSION,
            label="worker replica",
        )
    return {
        "scopePath": expected_path,
        "startedAtUtc": started,
        "endedAtUtc": datetime.now(UTC).isoformat(),
        "pages": pages,
        "complete": True,
        "workerRunningState": "unverified",
    }


def validate_api_measurement_window(
    sample: dict[str, object],
    observations: list[dict[str, object]],
    *,
    require_overlap: bool,
    api_resource_id: str,
) -> None:
    """Check API revision replica observations against the sampled time window."""
    try:
        start = parse_utc(str(sample["startedAtUtc"]))
        end = parse_utc(str(sample["endedAtUtc"]))
    except (KeyError, CampaignError) as exc:
        raise CampaignError("measurement window is malformed") from exc
    if end < start or not observations:
        raise CampaignError("measurement window lacks API observations")
    observed_times = []
    for observation in observations:
        observed_at = parse_utc(str(observation.get("observedAtUtc", "")))
        observed_times.append(observed_at)
        revisions = observation.get("revisions")
        if not start <= observed_at <= end or not isinstance(revisions, list):
            raise CampaignError("API observation is outside the measurement window")
        names: set[str] = set()
        all_replicas: set[str] = set()
        running = 0
        populated = 0
        for revision in revisions:
            if not isinstance(revision, dict) or not isinstance(revision.get("name"), str):
                raise CampaignError("API revision observation is malformed")
            name = str(revision["name"]).casefold()
            replicas = revision.get("replicas")
            expected_revision_id = f"{api_resource_id}/revisions/{revision['name']}"
            revision_id = revision.get("id")
            if (
                not name
                or name in names
                or not isinstance(replicas, list)
                or not isinstance(revision_id, str)
                or revision_id.casefold() != expected_revision_id.casefold()
            ):
                raise CampaignError("API revision observation is duplicated or malformed")
            names.add(name)
            revision_running = 0
            replica_names: set[str] = set()
            for replica in replicas:
                if not isinstance(replica, dict) or not isinstance(replica.get("name"), str):
                    raise CampaignError("API replica observation is malformed")
                replica_name = str(replica["name"]).casefold()
                properties = replica.get("properties")
                replica_id = replica.get("id")
                expected_replica_id = f"{expected_revision_id}/replicas/{replica['name']}"
                if (
                    not replica_name
                    or replica_name in replica_names
                    or replica_name in all_replicas
                    or not isinstance(properties, dict)
                    or not isinstance(replica_id, str)
                    or replica_id.casefold() != expected_replica_id.casefold()
                ):
                    raise CampaignError("API replica observation is duplicated or malformed")
                replica_names.add(replica_name)
                all_replicas.add(replica_name)
                state = properties.get("runningState")
                if not isinstance(state, str) or state not in {"Running", "NotRunning", "Unknown"}:
                    raise CampaignError("API replica running state is malformed")
                if state == "Unknown":
                    raise CampaignError("API replica running state is unproved")
                revision_running += int(state == "Running")
            running += revision_running
            populated += int(revision_running > 0)
        if (not require_overlap and (running != 4 or populated != 1)) or (
            require_overlap and (running < 4 or populated < 2)
        ):
            raise CampaignError("API replica ceiling or revision overlap is unproved")
    for key, count_key in (
        ("connectionObservationTimesUtc", "connectionSamples"),
        ("applicationRequestTimesUtc", "applicationRequests"),
    ):
        timestamps = sample.get(key)
        if (
            not isinstance(timestamps, list)
            or not timestamps
            or type(sample.get(count_key)) is not int
            or len(timestamps) != sample[count_key]
        ):
            raise CampaignError("measurement sample timestamps are incomplete")
        for value in timestamps:
            timestamp = parse_utc(str(value))
            if not start <= timestamp <= end or all(
                abs((timestamp - observed).total_seconds()) > 5 for observed in observed_times
            ):
                raise CampaignError("API replica observation is not contemporaneous with samples")


def validate_worker_measurement_window(
    sample: dict[str, object], captures: list[dict[str, object]], *, expected_scope: str
) -> None:
    """Never infer running workers from page presence while semantics are unverified."""
    try:
        start = parse_utc(str(sample["startedAtUtc"]))
        end = parse_utc(str(sample["endedAtUtc"]))
    except (KeyError, CampaignError) as exc:
        raise CampaignError("worker measurement timestamps are malformed") from exc
    if not captures:
        raise CampaignError("worker observation is incomplete or outside the measurement window")
    observed_times = []
    for capture in captures:
        try:
            observed_start = parse_utc(str(capture["startedAtUtc"]))
            observed_end = parse_utc(str(capture["endedAtUtc"]))
        except (KeyError, CampaignError) as exc:
            raise CampaignError("worker measurement timestamps are malformed") from exc
        scope = capture.get("scopePath")
        if (
            not start <= observed_start <= observed_end <= end
            or capture.get("complete") is not True
            or not isinstance(scope, str)
            or scope.casefold() != expected_scope.casefold()
            or not isinstance(capture.get("pages"), list)
            or not capture["pages"]
        ):
            raise CampaignError(
                "worker observation is incomplete or outside the measurement window"
            )
        observed_times.append(observed_end)
    for key in ("connectionObservationTimesUtc", "applicationRequestTimesUtc"):
        times = sample.get(key)
        if not isinstance(times, list) or not times:
            raise CampaignError("worker measurement sample timestamps are incomplete")
        for item in times:
            timestamp = parse_utc(str(item))
            if not start <= timestamp <= end or all(
                abs((timestamp - observed).total_seconds()) > 5 for observed in observed_times
            ):
                raise CampaignError("worker observation is not contemporaneous with samples")
    raise CampaignError("worker replica running-state semantics are unverified")
