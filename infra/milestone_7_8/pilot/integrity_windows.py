"""Capture the evidence-integrity signal and the native evaluation cutoffs before teardown."""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from infra.milestone_7_8.campaign import CampaignError, parse_utc, utc
from infra.milestone_7_8.pilot.consolidated import MODE
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new
from infra.milestone_7_8.pilot_alerts import bound

POINTS = ("readiness", "after-core", "before-stop")
RULE = "evidence-integrity-v1"
SIGNAL = "mobius.evidence.integrity"
ROW_LIMIT = 10000
COLUMNS = ["TimeGenerated", "IngestedAt", "SignalId", "Release", "Deployment", "Service", "Name", "Value", "SourceTable"]


def signal_query(release: str, deployment: str) -> str:
    return (
        "union withsource=SourceTable MobiusMetric_CL, MobiusApplication_CL, MobiusSecurity_CL\n"
        f'| where Release == "{bound(release)}" and Deployment == "{bound(deployment)}"\n'
        '| where Service in ("mobius-api", "mobius-worker", "mobius-outbox")\n'
        f'| where Name == "{SIGNAL}"\n'
        "| project TimeGenerated, IngestedAt=ingestion_time(), SignalId, Release, Deployment, "
        "Service, Name, Value=todouble(Payload.value), SourceTable\n"
        f"| order by TimeGenerated asc, SignalId asc | take {ROW_LIMIT + 1}\n"
    )


def read_signals(context, folder, finish, cutoff):
    plan = context.plan
    workspace = context.get(folder, "workspace", plan["workspaceResourceId"], "2023-09-01", cutoff=cutoff)
    if workspace["id"].casefold() != plan["workspaceResourceId"].casefold():
        raise CampaignError("integrity capture workspace differs")
    customer = UUID(workspace["properties"]["customerId"])
    path = context.package / "queries/integrity-source-rows.kql"
    if (file_hash(path) != plan["queryFiles"]["integrity-source-rows"]
            or path.read_text(encoding="utf-8") != signal_query(plan["release"], plan["deployment"])):
        raise CampaignError("integrity source query binding differs")
    start = parse_utc(context.window["executionStartAt"]) - timedelta(days=2)
    request = folder / "source-request.json"
    write_new(request, {"query": path.read_text(encoding="utf-8"), "timespan": f"{utc(start)}/{utc(finish)}"})
    reply = context.call(folder, "source-rows", ("rest", "--method", "post", "--url",
        f"https://api.loganalytics.io/v1/workspaces/{customer}/query", "--resource", "https://api.loganalytics.io/",
        "--body", "@" + str(request.resolve())), allow_failure=True, cutoff=cutoff, timeout=40)
    if not reply or reply.get("error") or len(reply.get("tables", [])) != 1:
        return {"status": "failed-or-partial"}
    table = reply["tables"][0]
    if [column["name"] for column in table["columns"]] != COLUMNS:
        raise CampaignError("integrity source column binding differs")
    rows = table["rows"]
    for values in rows:
        if (len(values) != len(COLUMNS) or values[3:5] != [plan["release"], plan["deployment"]]
                or values[5] not in {"mobius-api", "mobius-worker", "mobius-outbox"}
                or values[6] != SIGNAL or not start <= parse_utc(values[0]) <= finish):
            raise CampaignError("integrity source row binding differs")
    return {"status": "captured" if len(rows) <= ROW_LIMIT else "truncated", "returnedRows": len(rows),
            "nativeSha256": file_hash(folder / "source-rows.native.json")}


def read_windows(context, folder, finish, cutoff):
    # Use the parent scope so recorded alert identities survive target deletion.
    base = f"https://management.azure.com/subscriptions/{context.sub}/providers/Microsoft.AlertsManagement/alerts"
    start = parse_utc(context.window["executionStartAt"])
    url = base + "?" + urlencode({"api-version": "2019-03-01", "targetResourceGroup": context.rg,
        "customTimeRange": f"{utc(start)}/{utc(finish)}", "includeContext": "true", "pageCount": 25})
    query = next(rule["query"] for rule in read(context.package / "catalog.json")["alerts"] if rule["id"] == RULE)
    windows = []
    seen = set()
    for page in range(32):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "management.azure.com"
                or parsed.path.casefold() != urlsplit(base).path.casefold() or url in seen):
            raise CampaignError("integrity alert history pagination differs")
        seen.add(url)
        data = context.call(folder, f"alerts-{page:02}", ("rest", "--method", "get", "--url", url),
                            allow_failure=True, cutoff=cutoff, timeout=25)
        if not data or "error" in data or not isinstance(data.get("value"), list):
            return {"status": "incomplete", "windows": windows}
        for alert in data["value"]:
            e = alert["properties"]["essentials"]
            if (e["alertRule"].rsplit("/", 1)[-1] != context.plan["deployment"] + "-" + RULE
                    or e["targetResource"].casefold() != context.plan["workspaceResourceId"].casefold()
                    or not start <= parse_utc(e["startDateTime"]) <= finish):
                continue
            condition = alert["properties"]["context"]["context"]["condition"]
            criterion, = condition["allOf"]
            windows.append({"alertId": alert["id"], "monitorCondition": e["monitorCondition"],
                "alertTime": e["startDateTime"], "windowStart": condition["windowStartTime"],
                "windowEnd": condition["windowEndTime"], "aggregation": criterion["timeAggregation"],
                "queryResultCount": criterion["metricValue"], "queryMatches": criterion["searchQuery"].strip() == query.strip(),
                "nativePage": f"alerts-{page:02}.native.json"})
        url = data.get("nextLink")
        if not url:
            return {"status": "captured", "windows": windows}
    return {"status": "incomplete", "windows": windows}


def capture(context, point: str) -> dict:
    if context.plan.get("consolidatedScope") != MODE or point not in POINTS:
        raise CampaignError("consolidated integrity capture scope differs")
    context.policy.check()
    context.admit()
    finish = context.policy.clock()
    cutoff = min(context.policy.stop_by, finish + timedelta(minutes=2))
    folder = context.run / "integrity-windows" / point
    folder.mkdir(parents=True, exist_ok=False)
    result = {"point": point, "throughUtc": utc(finish), "release": context.plan["release"],
              "deployment": context.plan["deployment"], "workspace": context.plan["workspaceResourceId"]}
    for key, reader in (("sourceRows", read_signals), ("nativeWindows", read_windows)):
        try:
            result[key] = reader(context, folder, finish, cutoff)
        except (CampaignError, ValueError, OSError, KeyError, TypeError) as error:
            result[key] = {"status": "unproved", "error": str(error)}
        write_new(folder / (key + ".json"), result[key])
    result["capturedAtUtc"] = utc(context.policy.clock())
    write_new(folder / "summary.json", result)
    return result


def main() -> None:
    from infra.milestone_7_8.pilot.core_proof_operator import Campaign

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--bound", type=Path, required=True)
    parser.add_argument("--point", choices=POINTS, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    result = capture(Campaign(args.package, args.bound), args.point)
    print("Source rows", result["sourceRows"]["status"], "Native windows", result["nativeWindows"]["status"])


if __name__ == "__main__":
    main()
