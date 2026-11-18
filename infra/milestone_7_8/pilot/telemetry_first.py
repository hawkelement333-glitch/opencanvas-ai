"""One private liveness request, followed by same-deployment stage admission."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import timedelta

import httpx

from infra.milestone_7_8.campaign import CampaignError, utc
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new
from infra.milestone_7_8.pilot_validation import admit_runtime_bindings

POLICY = {
    "schema": "m78-telemetry-first-v1",
    "request": "/api/v1/health/live",
    "requestLimit": 1,
    "queryLimit": 12,
    "seconds": 1200,
    "missing": "hold-api-destination-dependent-stages",
    "emailLimit": 0,
    "earlyFallback": "exact-native-automation-monthly-quota-429",
}
TRACE = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-0[01]")
RELEASE_KEY_SHA256 = "856f48ad36a3f8787619c96b857cbad0e7583e768f76ec4ff653092f572ec789"


def validate_release(package):
    signing = package / "signing"
    binding = read(package / "release-bindings.json")
    scan_path = signing / "api/scout.sarif.json"
    scan = read(scan_path)
    if (
        binding["api"]["scanSarifSha256"] != file_hash(scan_path)
        or scan.get("version") != "2.1.0"
        or not scan.get("runs")
        or any(result.get("results") != [] for result in scan["runs"])
    ):
        raise CampaignError("the exact API candidate must pass the Critical/High scan gate")
    receipt = read(signing / "signature-verification-receipt.json")
    endorsement = signing / "editable-release-endorsement.json"
    if (
        receipt.get("status") != "verified-local-endorsement"
        or receipt.get("publicKeySha256") != RELEASE_KEY_SHA256
        or receipt.get("tamperedContentRejected") is not True
        or file_hash(signing / "opencanvas-m78-release.pub") != RELEASE_KEY_SHA256
        or read(endorsement)["artifacts"] != binding
        or read(package / "planned-bindings.json")["imageDigest"]
        != binding["api"]["imageIndexDigest"]
    ):
        raise CampaignError("release endorsement differs from the actual candidate")
    originals = {
        "api-release-binding": signing / "api/release-binding.json",
        "api-buildkit-provenance": signing / "api/buildkit-provenance.json",
        "frontend-release-binding": signing / "frontend/release-binding.json",
        "frontend-buildkit-provenance": signing / "frontend/buildkit-provenance.json",
        "editable-release-endorsement": endorsement,
    }
    expected = {
        item: (
            file_hash(path),
            file_hash(signing / f"{item}.bundle.json"),
        )
        for item, path in originals.items()
    }
    targets = receipt["targets"]
    if (
        len(targets) != len(expected)
        or {
            t["id"]: (t["contentSha256"], t["bundleSha256"])
            for t in targets
            if t["verified"] is True
        }
        != expected
    ):
        raise CampaignError("verified release signatures do not cover the exact files")


def decision(context):
    path = context.run / "telemetry-first"
    result = read(path / "result.json")
    if (
        result["deployment"] != context.policy.deployment
        or result["requestSha256"] != file_hash(path / "request.json")
        or result["nativeBindingsSha256"] != file_hash(path / "native-bindings.json")
        or result["state"] not in {"accepted", "unproved"}
    ):
        raise CampaignError("telemetry-first receipt differs from the bound deployment")
    if result["state"] == "accepted":
        name = result["query"]
        if (
            not re.fullmatch(r"trace-(0[0-9]|1[01])\.native\.json", name)
            or file_hash(path / name) != result["querySha256"]
        ):
            raise CampaignError("telemetry-first accepted row evidence differs")
    return result


def route(context):
    """Keep telemetry-dependent claims distinct from independent operations."""
    result_path = context.run / "telemetry-first/result.json"
    if not result_path.is_file():
        return "telemetry-first-required"
    state = decision(context)["state"]
    core = any(
        (context.run / f"proof-{phase}/accepted.json").is_file() for phase in ("core", "core-retry")
    )
    if state == "accepted" and core:
        return "shared-run-admitted"
    if state == "accepted":
        return "telemetry-admitted-continue-core-and-independent-stages"
    if core:
        return "api-destination-held-continue-core-fixture-independent-stages"
    return "api-destination-held-continue-core-and-independent-stages"


def diagnose(context, path, revision, trace, cutoff, native_failure):
    if not trace or context.policy.clock() >= cutoff:
        return "no-trace-or-console-window", []
    common = (
        "--name",
        context.plan["applicationResourceId"].rsplit("/", 1)[1],
        "--resource-group",
        context.rg,
        "--revision",
        revision,
    )
    try:
        replicas = context.call(
            path,
            "replicas",
            ("containerapp", "replica", "list", *common),
            timeout=20,
            cutoff=cutoff,
        )
    except native_failure:
        return "replica-read-unavailable", []
    if not isinstance(replicas, list) or not 1 <= len(replicas) <= 2:
        return "replica-inventory-unavailable", []
    emitted = False
    incomplete = False
    statuses = set()
    for index, replica in enumerate(replicas):
        name = replica.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name):
            raise CampaignError("invalid replica name in native readback")
        if context.policy.clock() >= cutoff:
            incomplete = True
            break
        try:
            console = context.call(
                path,
                f"console-{index}",
                (
                    "containerapp",
                    "logs",
                    "show",
                    *common,
                    "--replica",
                    name,
                    "--container",
                    "api",
                    "--type",
                    "console",
                    "--tail",
                    "150",
                ),
                timeout=20,
                cutoff=cutoff,
                as_json=False,
            )
        except native_failure:
            incomplete = True
            continue
        for line in console.splitlines():
            if trace not in line:
                continue
            emitted |= "api.request.completed" in line
            if "telemetry_liveness_delivery" in line:
                status = re.search(r"gateway_status[=\"\\:\s]+(\d{3}|None|null)", line)
                if status:
                    statuses.add(status.group(1))
    if "202" in statuses:
        point = "gateway-acknowledged-row-not-observed"
    elif statuses:
        point = "export-attempt-without-gateway-acceptance"
    elif emitted:
        point = "api-emission-without-export-outcome"
    else:
        point = "console-read-incomplete" if incomplete else "api-emission-not-observed"
    return point, sorted(statuses)


def run(context, validate_sample, native_failure):
    path = context.run / "telemetry-first"
    path.mkdir(exist_ok=False)
    clock = context.policy.clock
    cutoff = min(context.policy.core_by, clock() + timedelta(seconds=POLICY["seconds"]))
    readbacks = context.native_readbacks(path, cutoff)
    plan = context.plan
    admitted = admit_runtime_bindings(
        plan, readbacks, plan_sha256=file_hash(context.package / "planned-bindings.json")
    )
    app = readbacks["resources"]
    (application,) = (
        row["response"]["body"]["properties"]
        for row in app
        if row["request"]["resourceId"] == plan["applicationResourceId"]
    )
    revision = application["latestReadyRevisionName"]
    if (
        not isinstance(revision, str)
        or not re.fullmatch(r"[a-z0-9-]+", revision)
        or revision != application["latestRevisionName"]
        or application["configuration"]["activeRevisionsMode"] != "Single"
    ):
        raise CampaignError("one exact serving revision required for the telemetry request")
    write_new(path / "native-bindings.json", readbacks)
    begin = clock()
    write_new(path / "request-intent.json", {"path": POLICY["request"], "atUtc": utc(begin)})
    response_status, trace = None, None
    with httpx.Client(
        base_url=admitted["apiBaseUrl"], follow_redirects=False, trust_env=False
    ) as client:
        try:
            response = client.get(POLICY["request"], timeout=min(10, context.remaining(cutoff)))
            response_status = response.status_code
            header = TRACE.fullmatch(response.headers.get("traceparent", ""))
            if response_status == 200 and header and int(header[1], 16) and int(header[2], 16):
                trace = header[1]
        except httpx.RequestError:
            pass
    write_new(
        path / "request.json",
        {
            "status": response_status,
            "traceId": trace,
            "startedAt": utc(begin),
            "finishedAt": utc(clock()),
            "revision": revision,
        },
    )
    result = {
        "deployment": context.policy.deployment,
        "requestSha256": file_hash(path / "request.json"),
        "nativeBindingsSha256": file_hash(path / "native-bindings.json"),
        "state": "unproved",
    }
    if trace:
        destination = read(context.package / "destination-plan.bound.json")
        workspace_values = next(
            row["response"]["body"]["properties"]
            for row in app
            if row["request"]["resourceId"] == plan["workspaceResourceId"]
        )
        workspace = str(uuid.UUID(workspace_values["customerId"]))
        query = (
            "MobiusApplication_CL "
            f"| where TimeGenerated >= datetime({utc(begin)}) "
            '| where Name == "api.request.completed" '
            f'and tostring(todynamic(Payload).trace_id) == "{trace}" '
            "| summarize arg_max(TimeGenerated, *) by SignalId | take 2 "
            "| project TimeGenerated, SignalId, Service, Environment, Release, Deployment, "
            "Kind, Name, Component, Payload"
        )
        for index in range(POLICY["queryLimit"]):
            remaining = (cutoff - clock()).total_seconds()
            if remaining <= 75:
                break  # Preserve the bounded replica/console diagnostic.
            label = f"trace-{index:02}"
            try:
                values = context.call(
                    path,
                    label,
                    (
                        "monitor",
                        "log-analytics",
                        "query",
                        "--workspace",
                        workspace,
                        "--analytics-query",
                        query,
                        "--timespan",
                        "PT12H",
                    ),
                    timeout=min(30, remaining - 75),
                    cutoff=cutoff,
                )
            except native_failure:
                break
            observed, count = validate_sample(values, destination, begin, clock())
            if count:
                if not isinstance(values, list) or observed != {"mobius-api"} or count != 1:
                    raise CampaignError("exact API liveness row differs")
                row = values[0]
                fields = row["Payload"]
                if isinstance(fields, str):
                    fields = json.loads(fields)
                if (
                    row["Name"] != "api.request.completed"
                    or fields.get("trace_id") != trace
                    or fields.get("route") != "/health/live"
                    or fields.get("method") != "GET"
                    or fields.get("status_code") != "200"
                ):
                    raise CampaignError("API liveness row does not bind the exact operation")
                name = f"{label}.native.json"
                result.update(state="accepted", query=name, querySha256=file_hash(path / name))
                break
            if index + 1 < POLICY["queryLimit"]:
                time.sleep(max(0, min(90, (cutoff - clock()).total_seconds() - 75)))
    if result["state"] == "unproved":
        point, statuses = diagnose(context, path, revision, trace, cutoff, native_failure)
        result.update(lastObservedBoundary=point, gatewayStatuses=statuses)
    write_new(path / "result.json", result)
    return route(context)
