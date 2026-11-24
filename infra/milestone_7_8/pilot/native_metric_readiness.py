"""Read the bound production signals once before opening the staging account fixture."""
from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from uuid import UUID

from infra.milestone_7_8.campaign import CampaignError, parse_utc, utc
from infra.milestone_7_8.destination_acceptance import rows, validate_signal_row
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new


def assess(response, sources, begin, end):
    records = rows({"status": 200, "result": response})
    seen = set()
    shapes = Counter()
    encoded = 0
    rejected = []
    for row in records:
        try:
            stamp = parse_utc(row["TimeGenerated"])
            if not begin <= stamp <= end:
                raise ValueError("signal outside the native query window")
            if not {"NativePayloadType", "NativeMetricValueType", "NativeMetricExponent",
                    "NativeMetricSignificand"} <= row.keys():
                raise ValueError("native precision columns absent")
            if row["Kind"] == "metric":
                shapes[(row["NativePayloadType"], row["NativeMetricValueType"])] += 1
            validate_signal_row(row, sources, stamp, seen)
            encoded += row["NativeMetricExponent"] is not None
        except (KeyError, TypeError, ValueError, OverflowError, CampaignError) as error:
            rejected.append({"signalId": row.get("SignalId"), "reason": str(error)})
    status = "unproved"
    if rejected:
        status = "integrity-failure"
    elif encoded and len(records) < 10000:
        status = "accepted"
    return {"status": status, "returnedRows": len(records), "validatedRows": len(seen),
            "encodedRows": encoded, "atRowLimit": len(records) == 10000, "rejected": rejected,
            "metricTypes": [{"payload": p, "value": v, "rows": n} for (p, v), n in shapes.items()]}


def capture(context):
    folder = context.run / "native-metric-readiness"
    folder.mkdir(exist_ok=False)
    plan = read(context.package / "destination-plan.bound.json")
    query = context.package / "queries/production-signals.kql"
    digest = file_hash(query)
    if digest != context.plan["queryFiles"]["production-signals"]:
        raise CampaignError("production signal query differs from the approved package")
    begin = parse_utc(context.window["executionStartAt"])
    end = context.policy.clock()
    cutoff = min(parse_utc(context.window["readyBy"]), end + timedelta(minutes=2))
    rid = plan["workspaceResourceId"]
    workspace = context.get(folder, "workspace", rid, "2023-09-01", cutoff=cutoff)
    if workspace["id"].casefold() != rid.casefold():
        raise CampaignError("production signal workspace differs")
    customer = UUID(workspace["properties"]["customerId"])
    request = folder / "request.json"
    write_new(request, {"query": query.read_text(encoding="utf-8"), "timespan": utc(begin) + "/" + utc(end)})
    response = context.call(folder, "result", ("rest", "--method", "post",
        "--url", f"https://api.loganalytics.io/v1/workspaces/{customer}/query",
        "--resource", "https://api.loganalytics.io/", "--body", "@" + str(request.resolve())),
        allow_failure=True, cutoff=cutoff, timeout=65)
    if response is None or "error" in response:
        report = {"status": "unproved", "reason": "native query failed or returned a partial error"}
    else:
        report = assess(response, plan["productionSources"], begin, end)
    write_new(folder / "summary.json", report | {
        "atUtc": utc(context.policy.clock()), "workspace": rid, "querySha256": digest,
        "requestSha256": file_hash(request), "nativeSha256": file_hash(folder / "result.native.json"),
    })
    return report["status"]


def require_accepted(package, run):
    folder = run / "native-metric-readiness"
    summary = read(folder / "summary.json")
    query = package / "queries/production-signals.kql"
    native = folder / "result.native.json"
    request = folder / "request.json"
    if (summary["status"] != "accepted" or summary["querySha256"] != file_hash(query)
            or summary["nativeSha256"] != file_hash(native) or summary["requestSha256"] != file_hash(request)):
        raise CampaignError("accepted native metric readback required before account or Core")
    sent = read(request)
    plan = read(package / "destination-plan.bound.json")
    if sent["query"] != query.read_text(encoding="utf-8") or summary["workspace"] != plan["workspaceResourceId"]:
        raise CampaignError("native metric request does not match the package")
    start, end = map(parse_utc, sent["timespan"].split("/"))
    reply = read(native)
    if reply.get("exitCode") != 0:
        raise CampaignError("successful native metric query required")
    proof = assess(json.loads(reply["stdout"]), plan["productionSources"], start, end)
    if proof["status"] != "accepted" or any(summary.get(k) != value for k, value in proof.items()):
        raise CampaignError("native metric evidence does not reproduce the readiness result")
