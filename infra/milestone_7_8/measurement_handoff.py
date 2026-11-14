from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from urllib.parse import urlsplit

from infra.milestone_7_8.automation_region import _safe_inventory_next_link
from infra.milestone_7_8.campaign import CampaignError, CommandRunner, parse_utc
from infra.milestone_7_8.replica_readback import (
    MAX_PAGES,
    collect_worker_replicas,
    validate_api_measurement_window,
    validate_worker_measurement_window,
    wait_for_four_running_candidates,
    worker_replica_url,
)

ARM = "https://management.azure.com"
APP_API_VERSION = "2024-03-01"
MEASUREMENT_VERSION = "m7.8-raw-measurement-sample-v1"
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,127}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def _name(value: object) -> str:
    if not isinstance(value, str) or NAME.fullmatch(value) is None:
        raise CampaignError("measurement resource identity is invalid")
    return value


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CampaignError(f"{label} is malformed")
    return cast(dict[str, object], value)


def _digest(value: object) -> str:
    return hashlib.sha256(
        b"m7.8/measurement-window/v1\0"
        + json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _check_id(value: dict[str, object], expected: str) -> None:
    observed = value.get("id")
    if not isinstance(observed, str) or observed.casefold() != expected.casefold():
        raise CampaignError("measurement resource identity differs from the campaign scope")


def _number(value: object) -> float:
    if type(value) not in {int, float}:
        raise CampaignError("application latency measurement is malformed")
    number = float(cast(int | float, value))
    if not math.isfinite(number) or number < 0:
        raise CampaignError("application latency measurement is malformed")
    return number


def _p95(values: list[float]) -> float:
    if not values:
        raise CampaignError("application latency measurements are absent")
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _application_latencies(sample: dict[str, object]) -> list[float]:
    values = sample.get("applicationRequestDurationsMs")
    count = sample.get("applicationRequests")
    if (
        not isinstance(values, list)
        or type(count) is not int
        or not 0 < len(values) <= 1200
        or count != len(values)
    ):
        raise CampaignError("application latency samples are incomplete")
    latencies = [_number(value) for value in values]
    if _number(sample.get("applicationP95Ms")) != _p95(latencies):
        raise CampaignError("application latency summary differs from samples")
    return latencies


def _peak(sample: dict[str, object]) -> int:
    peak = sample.get("observedRuntimeConnectionPeak")
    if type(peak) is not int or peak <= 0:
        raise CampaignError("measured connection peak is missing or invalid")
    return peak


def start_evidence_job(
    runner: CommandRunner,
    command: tuple[str, ...],
    *,
    private_directory: Path,
    image_digest: str,
    expected_command: tuple[str, ...] | None = None,
    before_dispatch: Callable[[dict[str, object]], None] | None = None,
    database_grants_only: bool = False,
) -> dict[str, object]:
    """Submit a full execution template when a job's arguments or environment change."""
    args = next((arg for arg in command if arg.startswith((
        "--args=--phase=", "--args=--retry-after-execution=", "--args=--diagnose-prerequisites",
    ))), None)
    if database_grants_only and (
        args is None or not args.startswith("--args=--retry-after-execution=")
        or expected_command != ("python", "-m", "scripts.migrate_and_grant")
        or before_dispatch is None
    ):
        raise CampaignError("grant-only execution requires the exact guarded migration command")
    if args is None and "--env-vars" not in command:
        return runner.run(command)
    read = list(command)
    read[3] = "show"
    if args is not None:
        read.remove(args)
    env_overrides: list[str] = []
    if "--env-vars" in read:
        index = read.index("--env-vars")
        end = index + 1
        while end < len(read) and not read[end].startswith("--"):
            env_overrides.append(read[end])
            end += 1
        if not env_overrides:
            raise CampaignError("evidence execution environment override is empty")
        del read[index:end]
    group = command[command.index("--resource-group") + 1]
    subscription = command[command.index("--subscription") + 1]
    job = command[command.index("--name") + 1]
    result = runner.run(tuple(read))
    if result.get("exitCode") != 0 or not isinstance(result.get("stdout"), str):
        raise CampaignError("evidence job template read failed")
    try:
        resource = _object(json.loads(str(result["stdout"])), "evidence job")
    except json.JSONDecodeError as exc:
        raise CampaignError("evidence job template is malformed") from exc
    _check_id(
        resource,
        f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.App/jobs/{job}",
    )
    properties = _object(resource.get("properties"), "evidence job properties")
    template = _object(properties.get("template"), "evidence job template")
    containers = template.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise CampaignError("evidence job execution template must have one container")
    container = _object(containers[0], "evidence job container")
    image = container.get("image")
    if not isinstance(image, str) or not image.endswith(f"@{image_digest}"):
        raise CampaignError("evidence job image differs from the admitted digest")
    if args is not None and args.startswith((
        "--args=--retry-after-execution=", "--args=--diagnose-prerequisites",
    )) and (
        expected_command is None or container.get("command") != list(expected_command)
        or before_dispatch is None
    ):
        raise CampaignError("database command or dispatch guard is missing")
    if args == "--args=--diagnose-prerequisites" and container.get("args") not in (None, []):
        raise CampaignError("database prerequisite requires the standard job arguments")
    if args is not None:
        container["args"] = [
            *(["--reconcile-grants-only"] if database_grants_only else []),
            args.removeprefix("--args="),
        ]
    for env_override in env_overrides:
        key, separator, value = env_override.partition("=")
        env = container.get("env")
        if not key or not separator or not isinstance(env, list):
            raise CampaignError("evidence job environment is malformed")
        variables = [_object(item, "evidence job environment variable") for item in env]
        if any(item.get("name") == key for item in variables):
            raise CampaignError("evidence execution environment binding already exists")
        container["env"] = [*variables, {"name": key, "value": value}]
    read[3] = "start"
    with TemporaryDirectory(prefix="m78-job-", dir=private_directory) as directory:
        override = Path(directory) / "execution.yaml"
        override.write_text(json.dumps(template, allow_nan=False), encoding="utf-8")
        if before_dispatch is not None:
            before_dispatch(resource)
        return {**runner.run((*read, "--yaml", str(override))), "executionTemplate": template}


class CampaignMeasurement:
    """Run the two measurement windows inside the authorized campaign scope."""

    def __init__(
        self, runner: CommandRunner, runtime: dict[str, str], deadline_utc: str,
        *, private_directory: Path, image_digest: str,
        authorize: Callable[[], None] | None = None,
    ) -> None:
        self.runner = runner
        self.private_directory = private_directory
        self.image_digest = image_digest
        self.deadline = parse_utc(deadline_utc)
        self.authorize = authorize or (lambda: None)
        self.subscription = runtime["subscriptionId"]
        self.group = _name(runtime["resourceGroupName"])
        self.worker = _name(runtime["workerJobName"])
        self.sampler = _name(runtime["evidenceJobName"])
        self.workspace = _name(runtime["logAnalyticsWorkspaceName"])
        self.worker_execution: str | None = None
        group = re.fullmatch(r"rg-m78-([a-f0-9]{10})-target", self.group)
        if group is None:
            raise CampaignError("measurement campaign scope is malformed")
        self.api = f"app-m78-{group[1]}"
        self.group_id = f"/subscriptions/{self.subscription}/resourceGroups/{self.group}"
        self.api_id = f"{self.group_id}/providers/Microsoft.App/containerApps/{self.api}"
        # Validate the subscription and worker path before issuing any request.
        worker_replica_url(self.subscription, self.group, self.worker, "validation")

    def remaining(self) -> float:
        remaining = (self.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise CampaignError("campaign cleanup deadline reached during measurement")
        return remaining

    def command(self, *args: str, output: bool = True) -> object:
        self.remaining()
        self.authorize()
        command = ("az", *args, "--subscription", self.subscription, "--output", "json")
        if args[:3] == ("containerapp", "job", "start"):
            def before_dispatch(_resource: dict[str, object]) -> None:
                self.remaining()
                self.authorize()

            result = start_evidence_job(
                self.runner, command, private_directory=self.private_directory,
                image_digest=self.image_digest,
                before_dispatch=before_dispatch,
            )
        else:
            result = self.runner.run(command)
        if result.get("exitCode") != 0:
            label = " ".join(args[:3])
            raise CampaignError(f"measurement provider command failed: {label}")
        self.remaining()
        if not output:
            return None
        raw = result.get("stdout")
        if not isinstance(raw, str):
            raise CampaignError("measurement provider output is absent")
        try:
            return cast(object, json.loads(raw))
        except json.JSONDecodeError as exc:
            raise CampaignError("measurement provider output is malformed") from exc

    def inventory(self, path: str) -> list[dict[str, object]]:
        url = f"{ARM}{path}?api-version={APP_API_VERSION}"
        seen: set[str] = set()
        identities: set[str] = set()
        records: list[dict[str, object]] = []
        while True:
            if url.casefold() in seen or len(seen) >= MAX_PAGES:
                raise CampaignError("API inventory pagination repeated or exceeded its bound")
            seen.add(url.casefold())
            page = _object(self.command("rest", "--method", "get", "--url", url), "API inventory")
            values = page.get("value")
            if not isinstance(values, list):
                raise CampaignError("API inventory page is incomplete")
            for item in values:
                record = _object(item, "API inventory record")
                name = _name(record.get("name"))
                _check_id(record, f"{path}/{name}")
                if name.casefold() in identities:
                    raise CampaignError("API inventory contains a duplicate identity")
                identities.add(name.casefold())
                records.append(record)
            continuation = page.get("nextLink")
            if continuation in (None, ""):
                return records
            if not isinstance(continuation, str):
                raise CampaignError("API inventory continuation is malformed")
            url = _safe_inventory_next_link(
                continuation, subscription_id=self.subscription, expected_path=path,
                api_version=APP_API_VERSION, label="API measurement",
            )

    def active_revisions(self) -> dict[str, dict[str, object]]:
        active: dict[str, dict[str, object]] = {}
        for revision in self.inventory(f"{self.api_id}/revisions"):
            properties = _object(revision.get("properties"), "API revision properties")
            if type(properties.get("active")) is not bool:
                raise CampaignError("API revision active state is missing")
            if properties["active"]:
                active[_name(revision["name"])] = revision
        return active

    def revision_replicas(self, revision: str) -> list[dict[str, object]]:
        return self.inventory(f"{self.api_id}/revisions/{revision}/replicas")

    def wait_for_api(self, revisions: tuple[str, ...]) -> None:
        expires = time.monotonic() + min(300, self.remaining())
        with ThreadPoolExecutor(max_workers=len(revisions)) as pool:
            while time.monotonic() < expires:
                active = self.active_revisions()
                if set(active) - set(revisions):
                    raise CampaignError("unexpected API revision is active")
                if set(active) == set(revisions):
                    replicas = list(pool.map(self.revision_replicas, revisions))
                    if all(_four_running(items) for items in replicas):
                        return
                time.sleep(min(2, self.remaining(), max(0, expires - time.monotonic())))
        raise CampaignError("four running API replicas per intended revision were not observed")

    def start_job(self, job: str, *options: str) -> str:
        value = _object(
            self.command(
                "containerapp", "job", "start", "--resource-group", self.group,
                "--name", job, *options,
            ),
            "job start result",
        )
        execution = _name(value.get("name"))
        _check_id(value, self.execution_id(job, execution))
        return execution

    def execution_id(self, job: str, execution: str) -> str:
        return f"{self.group_id}/providers/Microsoft.App/jobs/{job}/executions/{execution}"

    def sampler_status(self, execution: str) -> str:
        shown = _object(
            self.command(
                "containerapp", "job", "execution", "show", "--resource-group", self.group,
                "--name", self.sampler, "--job-execution-name", execution,
            ),
            "sampler execution",
        )
        _check_id(shown, self.execution_id(self.sampler, execution))
        if shown.get("name") != execution:
            raise CampaignError("sampler execution name differs")
        status = _object(shown.get("properties"), "sampler execution properties").get("status")
        if not isinstance(status, str):
            raise CampaignError("sampler execution status is missing")
        return status

    def workspace_id(self) -> str:
        value = _object(
            self.command(
                "monitor", "log-analytics", "workspace", "show",
                "--resource-group", self.group, "--workspace-name", self.workspace,
            ),
            "campaign Log Analytics workspace",
        )
        workspace_resource = (
            f"{self.group_id}/providers/Microsoft.OperationalInsights/workspaces/{self.workspace}"
        )
        _check_id(value, workspace_resource)
        customer_id = value.get("customerId")
        if not isinstance(customer_id, str):
            raise CampaignError("campaign Log Analytics workspace ID is missing")
        try:
            parsed = uuid.UUID(customer_id)
        except ValueError as exc:
            raise CampaignError("campaign Log Analytics workspace ID is malformed") from exc
        if parsed.int == 0:
            raise CampaignError("campaign Log Analytics workspace ID is malformed")
        return str(parsed)

    def read_sample(self, workspace: str, execution: str, token: str) -> dict[str, object]:
        prefix = f"M78_MEASUREMENT {token} "
        query = (
            "ContainerAppConsoleLogs_CL"
            f" | where ContainerGroupName_s startswith '{execution}-'"
            f" | where ContainerName_s == 'evidence' and Log_s startswith '{prefix}'"
            " | project replica = ContainerGroupName_s, message = Log_s | take 2"
        )
        expires = time.monotonic() + min(240, self.remaining())
        while time.monotonic() < expires:
            rows = self.command(
                "monitor", "log-analytics", "query", "--workspace", workspace,
                "--analytics-query", query, "--timespan", "PT30M",
            )
            if not isinstance(rows, list) or len(rows) > 1:
                raise CampaignError("sampler output is missing or ambiguous")
            if rows:
                row = _object(rows[0], "sampler log entry")
                replica = _name(row.get("replica"))
                message = row.get("message")
                if (
                    not replica.startswith(f"{execution}-")
                    or not isinstance(message, str)
                    or not message.startswith(prefix)
                ):
                    raise CampaignError("sampler log is not bound to the exact execution")
                try:
                    sample = _object(json.loads(message[len(prefix):]), "sampler output")
                except json.JSONDecodeError as exc:
                    raise CampaignError("sampler output is malformed") from exc
                if (
                    sample.get("version") != MEASUREMENT_VERSION
                    or sample.get("status") != "blocked-unverified"
                ):
                    raise CampaignError("sampler output contract differs")
                return sample
            time.sleep(min(5, self.remaining(), max(0, expires - time.monotonic())))
        raise CampaignError("sampler output did not arrive before timeout")

    def window(
        self, workspace: str, worker_execution: str, revisions: tuple[str, ...],
    ) -> tuple[dict[str, object], dict[str, object]]:
        token = uuid.uuid4().hex
        dispatched = datetime.now(UTC)
        execution = self.start_job(
            self.sampler, "--args=--phase=measurement-sample",
            "--env-vars", f"M78_MEASUREMENT_TOKEN={token}",
        )
        worker_url = worker_replica_url(
            self.subscription, self.group, self.worker, worker_execution,
        )
        snapshots: list[tuple[datetime, datetime, dict[str, object], dict[str, object]]] = []
        expires = time.monotonic() + min(240, self.remaining())
        with ThreadPoolExecutor(max_workers=len(revisions) + 2) as pool:
            while time.monotonic() < expires:
                status = self.sampler_status(execution)
                if status == "Succeeded":
                    break
                if status not in {"Running", "Processing", "Pending", "Starting"}:
                    raise CampaignError("measurement sampler did not reach terminal success")
                capture_start = datetime.now(UTC)
                worker_read = pool.submit(
                    collect_worker_replicas, self.runner, subscription=self.subscription,
                    group=self.group, job=self.worker, execution=worker_execution,
                )
                active_read = pool.submit(self.active_revisions)
                api_reads = [pool.submit(self.revision_replicas, name) for name in revisions]
                workers = worker_read.result()
                active = active_read.result()
                replica_sets = [read.result() for read in api_reads]
                capture_end = datetime.now(UTC)
                if set(active) != set(revisions) or not all(map(_four_running, replica_sets)):
                    raise CampaignError("API replica ceiling or intended revision overlap changed")
                api: dict[str, object] = {
                    "observedAtUtc": capture_end.isoformat(),
                    "revisions": [
                        {"name": name, "id": active[name]["id"], "replicas": replicas}
                        for name, replicas in zip(revisions, replica_sets, strict=True)
                    ],
                }
                snapshots.append((capture_start, capture_end, workers, api))
                time.sleep(min(1, self.remaining(), max(0, expires - time.monotonic())))
            else:
                raise CampaignError("measurement sampler did not finish before timeout")
        completed = datetime.now(UTC)
        sample = self.read_sample(workspace, execution, token)
        start = parse_utc(str(sample.get("startedAtUtc")))
        end = parse_utc(str(sample.get("endedAtUtc")))
        if not dispatched <= start < end <= completed:
            raise CampaignError("sampler timestamps are stale or outside its exact execution")
        matched = [
            (workers, api) for before, after, workers, api in snapshots
            if start <= before <= after <= end and after - before <= timedelta(seconds=5)
        ]
        api_observations = [api for _, api in matched]
        worker_observations = [workers for workers, _ in matched]
        validate_api_measurement_window(
            sample, api_observations,
            require_overlap=len(revisions) == 2, api_resource_id=self.api_id,
        )
        validate_worker_measurement_window(
            sample, worker_observations, expected_scope=urlsplit(worker_url).path,
        )
        _application_latencies(sample)
        _peak(sample)
        return sample, {
            "samplerExecution": execution,
            "apiRevisions": list(revisions),
            "sampleSha256": _digest(sample),
            "readbacksSha256": _digest({"api": api_observations, "worker": worker_observations}),
        }

    def run(self, control: dict[str, object], *, keep_worker: bool = False) -> dict[str, object]:
        pools = cast(int, control["poolCeilings"])
        allowance = cast(int, control["rolloutOverlap"])
        # The campaign pins ten connections per API and worker replica.
        if pools < 80 or allowance < 40:
            raise CampaignError("declared connection budget omits campaign replicas")
        initial = tuple(self.active_revisions())
        if len(initial) != 1:
            raise CampaignError("measurement requires one initial active API revision")
        old = initial[0]
        self.wait_for_api(initial)
        workspace = self.workspace_id()
        worker_execution = self.start_job(self.worker)
        self.worker_execution = worker_execution
        wait_for_four_running_candidates(
            self.runner, subscription=self.subscription, group=self.group, job=self.worker,
            execution=worker_execution, timeout_seconds=min(180, self.remaining()),
            clock=time.monotonic, sleep=time.sleep,
        )
        steady, steady_evidence = self.window(workspace, worker_execution, initial)
        app_args = ("--name", self.api, "--resource-group", self.group)
        suffix = f"m78-{uuid.uuid4().hex[:8]}"
        new = f"{self.api}--{suffix}"
        self.command(
            "containerapp", "revision", "set-mode", *app_args, "--mode", "multiple", output=False,
        )
        self.command(
            "containerapp", "revision", "copy", *app_args, "--from-revision", old,
            "--revision-suffix", suffix, output=False,
        )
        self.wait_for_api((old, new))
        self.command(
            "containerapp", "ingress", "traffic", "set", *app_args,
            "--revision-weight", f"{old}=50", f"{new}=50", output=False,
        )
        overlap, overlap_evidence = self.window(workspace, worker_execution, (old, new))
        steady_peak = _peak(steady)
        overlap_peak = _peak(overlap)
        if steady_peak > pools or overlap_peak > pools + allowance:
            raise CampaignError("measured connection peak exceeds the declared topology budget")

        self.command(
            "containerapp", "ingress", "traffic", "set", *app_args,
            "--revision-weight", f"{old}=100", f"{new}=0", output=False,
        )
        self.command(
            "containerapp", "revision", "deactivate", *app_args, "--revision", new, output=False,
        )
        self.wait_for_api((old,))
        if not keep_worker:
            self.stop_worker(worker_execution)
        return {
            "workerExecution": worker_execution,
            "steady": steady_evidence,
            "overlap": overlap_evidence,
            "observedPeak": max(steady_peak, overlap_peak),
            "latencyP95Ms": _p95(_application_latencies(steady) + _application_latencies(overlap)),
        }

    def stop_worker(self, execution: str) -> None:
        self.command(
            "containerapp", "job", "stop", "--resource-group", self.group,
            "--name", self.worker, "--job-execution-name", _name(execution), output=False,
        )


def _four_running(records: list[dict[str, object]]) -> bool:
    return len(records) == 4 and all(
        _object(record.get("properties"), "API replica properties").get("runningState") == "Running"
        for record in records
    )


def validate_measurement_receipt(value: object, control: dict[str, object]) -> dict[str, object]:
    measurement = _object(value, "measurement receipt")
    if set(measurement) != {"workerExecution", "steady", "overlap", "observedPeak", "latencyP95Ms"}:
        raise CampaignError("measurement receipt is incomplete")
    _name(measurement["workerExecution"])
    steady, overlap = (
        _object(measurement[key], "measurement window receipt") for key in ("steady", "overlap")
    )
    for window, revision_count in ((steady, 1), (overlap, 2)):
        if set(window) != {"samplerExecution", "apiRevisions", "sampleSha256", "readbacksSha256"}:
            raise CampaignError("measurement window receipt is incomplete")
        _name(window["samplerExecution"])
        revisions = window["apiRevisions"]
        if not isinstance(revisions, list) or len(revisions) != revision_count:
            raise CampaignError("measurement window revision identities are incomplete")
        for name in revisions:
            _name(name)
        for key in ("sampleSha256", "readbacksSha256"):
            digest = window[key]
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise CampaignError("measurement window digest is malformed")
    old = cast(list[str], steady["apiRevisions"])[0]
    during = cast(list[str], overlap["apiRevisions"])
    if (
        old != during[0]
        or old == during[1]
        or steady["samplerExecution"] == overlap["samplerExecution"]
        or steady["sampleSha256"] == overlap["sampleSha256"]
    ):
        raise CampaignError("measurement receipt contains mismatched or replayed windows")
    peak = measurement["observedPeak"]
    if (
        type(peak) is not int
        or not 0 < peak <= cast(int, control["poolCeilings"]) + cast(int, control["rolloutOverlap"])
    ):
        raise CampaignError("measurement receipt connection peak exceeds the topology budget")
    _number(measurement["latencyP95Ms"])
    return measurement
