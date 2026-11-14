from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import cast

from infra.milestone_7_8.campaign import CampaignError, CommandRunner
from infra.milestone_7_8.replica_readback import collect_worker_replicas, worker_replica_url

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z")


def read_job_marker(
    runner: CommandRunner, *, subscription: str, group: str, workspace: str,
    job: str, execution: str, container: str, marker: str, token: str,
    deadline: datetime, maximum_wait_seconds: int = 240,
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
            remaining() <= 0 or result.get("exitCode") != 0
            or not isinstance(result.get("stdout"), str)
        ):
            raise CampaignError("evidence console read failed")
        try:
            return cast(object, json.loads(str(result["stdout"])))
        except json.JSONDecodeError as exc:
            raise CampaignError("evidence console read is malformed") from exc

    found = read(
        "monitor", "log-analytics", "workspace", "show",
        "--resource-group", group, "--workspace-name", workspace,
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
            BoundedReplicaReader(), subscription=subscription, group=group,
            job=job, execution=execution,
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
                "monitor", "log-analytics", "query", "--workspace", str(customer),
                "--analytics-query", query, "--timespan", "PT30M",
            )
            if not isinstance(rows, list) or len(rows) > 1:
                raise CampaignError("evidence console record is ambiguous")
            if rows:
                row = rows[0]
                if (
                    not isinstance(row, dict) or row.get("replica") not in names
                    or row.get("container") != container
                    or not isinstance(row.get("message"), str)
                    or not row["message"].startswith(prefix)
                ):
                    raise CampaignError("evidence console record escaped its exact execution")
                try:
                    payload = json.loads(row["message"][len(prefix):])
                except json.JSONDecodeError as exc:
                    raise CampaignError("evidence console record is malformed") from exc
                if not isinstance(payload, dict):
                    raise CampaignError("evidence console payload is malformed")
                return cast(dict[str, object], payload)
        time.sleep(min(5, max(0, remaining())))
    raise CampaignError("evidence console record was not observed before its deadline")
