import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.milestone_7_8.campaign import CampaignError, utc
from infra.milestone_7_8.pilot import consolidated, integrity_windows as windows
from infra.milestone_7_8.pilot.core_proof_operator import proof_disposition
from infra.milestone_7_8.pilot_cleanup import file_hash


PRIMARY = "d6406918-df67-47cf-8c36-17923c542e74"
SECONDARY = "267dfc46-ef80-409b-b9fa-021b1848c288"
PLAN = {"sourceCommit": "a" * 40, "release": "rc-test", "deployment": "m78-test",
        "imageDigest": "sha256:" + "f" * 64, "helperJobResourceId": "/target/jobs/migration",
        "consolidatedScope": consolidated.MODE}
ACCOUNT = {"accountsReady": True, "accountCreated": True, "accountActions": {"primary": "signup", "secondary": "signup"},
           "userId": PRIMARY, "secondaryUserId": SECONDARY}
FIXTURE = {"userId": PRIMARY, "workspaceId": "primary-workspace", "canvasId": "primary-canvas",
           "foreign": {"userId": SECONDARY, "workspaceId": "secondary-workspace", "canvasId": "secondary-canvas"}}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("case,expected", [
    ("exact", "accepted"), ("altered", "integrity-failure"), ("skipped-fraction", "integrity-failure"),
    ("no-fraction", "unproved"), ("partial", "unproved"),
    ("gateway-text", "accepted"), ("gateway-text-altered", "integrity-failure"),
    ("legacy-when-text-required", "unproved"),
])
def test_metric_readiness_through_staging_entry_point(tmp_path, monkeypatch, case, expected):
    from scripts.telemetry_destination import destination_rows
    from infra.milestone_7_8.destination_acceptance import METRIC_VALUE_PROJECTION
    from infra.milestone_7_8.pilot import core_proof_operator as operator

    now = datetime(2026, 11, 24, tzinfo=UTC)
    package = tmp_path / consolidated.PACKAGE_ID
    review = save(package / "review-package.json", {"packageId": consolidated.PACKAGE_ID})
    run = tmp_path / ("run-" + file_hash(review)[:8])
    run.mkdir()
    query = package / "queries/production-signals.kql"
    query.parent.mkdir()
    query.write_text("MobiusMetric_CL " + METRIC_VALUE_PROJECTION, encoding="utf-8")
    source = {"service": "mobius-worker", "environment": "staging", "release": "r", "deployment": "d"}
    plan = {"requireNativeMetricReadiness": True, "queryFiles": {"production-signals": file_hash(query)}}
    if case in ("gateway-text", "gateway-text-altered", "legacy-when-text-required"):
        plan["requireGatewayMetricEncoding"] = True
    save(package / "planned-bindings.json", plan)
    save(package / "destination-plan.bound.json", {"workspaceResourceId": "/fixture/ws", "productionSources": [source]})
    signal = source | {"schema_version": "mobius-operational-v1", "kind": "metric", "name": "mobius.queue.depth",
        "timestamp": now.isoformat(), "component": "queue", "payload": {"catalog_version": "mobius-signals-v1",
            "type": "gauge", "unit": "job", "labels": {"component": "queue", "outcome": "success"},
            "value": 1.0 if case == "no-fraction" else 0.125}}
    row, = destination_rows({"resource": {"schema": "mobius-operational-v1"}, "signals": [signal]}, [source], now=now)
    row.update(NativePayloadType="dictionary", NativeMetricValueType="double",
               NativeMetricExponent=None, NativeMetricSignificand=None)
    if case in ("exact", "altered", "legacy-when-text-required"):
        row["Payload"] = {key: value for key, value in row["Payload"].items() if key != "value"}
        row.update(NativeMetricExponent=-57, NativeMetricSignificand=2**(55 if case == "altered" else 54))
    if case.startswith("gateway-text"):
        row["NativeMetricValueType"] = "string"
        row["Payload"] = row["Payload"] | {"value_encoding": "binary64-decimal-v1",
                                           "value": "0.125" if case == "gateway-text" else "0.12500000000000003"}
    result = {"tables": [{"columns": [{"name": name} for name in row], "rows": [list(row.values())]}]}
    if case == "partial":
        result["error"] = {"code": "PartialError"}
    window = {"executionStartAt": utc(now - timedelta(minutes=5)), "readyBy": utc(now + timedelta(minutes=30))}
    context = SimpleNamespace(package=package, run=run, plan=plan, window=window, telemetry_first=True,
        policy=SimpleNamespace(clock=lambda: now, stop_by=now + timedelta(hours=2)), admit=lambda: None,
        get=lambda *a, **kw: {"id": "/fixture/ws", "properties": {"customerId": PRIMARY}})
    def query_native(folder, label, command, **kwargs):
        assert json.loads((folder / "request.json").read_text())["query"] == query.read_text()
        assert "https://api.loganalytics.io/v1/workspaces/" + PRIMARY + "/query" in command
        save(folder / (label + ".native.json"), {"exitCode": 0, "stdout": json.dumps(result)})
        return result
    context.call = query_native
    def stop(reason):
        save(run / "stop-proof-intent.json", {"reason": reason})
        return reason
    context.cleanup = stop
    monkeypatch.setattr(operator.telemetry_first, "run", lambda *a: "liveness")
    actual = operator.operate(context, "telemetry-first")
    assert actual == ("privacy-or-integrity-failure" if expected == "integrity-failure" else "liveness")
    summary = json.loads((run / "native-metric-readiness/summary.json").read_text())
    assert summary["status"] == expected
    if case == "gateway-text":
        assert summary["gatewayEncodedRows"] == 1
    if expected == "accepted":
        consolidated.guard_dispatch(package, ["account"], {})
        native = run / "native-metric-readiness/result.native.json"
        save(native, {"exitCode": 1})
        with pytest.raises(CampaignError):
            consolidated.guard_dispatch(package, ["account"], {})
    else:
        with pytest.raises(CampaignError):
            consolidated.guard_dispatch(package, ["account"], {})
        if expected == "integrity-failure":
            with pytest.raises(CampaignError, match="proof has stopped"):
                consolidated.guard_dispatch(package, ["query"], {})
        else:
            consolidated.guard_dispatch(package, ["query"], {})


def evidence(run, operation, payload):
    folder = run / ("proof-" + operation)
    receipt = save(folder / "export" / (operation + ".json"), PLAN | payload | {
        "executionId": operation + "-1", "operation": operation, "finishedAt": "2026-11-24T12:00:00Z"})
    save(folder / "accepted.json", {"operation": operation, "execution": operation + "-1", "resultSha256": file_hash(receipt)})
    save(folder / "evidence-execution.json", {"execution": operation + "-1"})
    save(folder / "evidence-terminal.json", {"name": operation + "-1", "properties": {"status": "Succeeded"}})
    return receipt


def test_windows_vpn_client_admission_uses_the_exact_installed_profile():
    from infra.milestone_7_8.pilot.windows_vpn_profile import verify

    xml = ("<AzVpnProfile><name>fixture</name><clientauth><aad><audience>current</audience>"
           "<issuer>issuer</issuer><tenant>tenant</tenant></aad></clientauth>"
           "<serverlist><ServerEntry><fqdn>current.test</fqdn></ServerEntry></serverlist>"
           "<clientconfig><dnsservers><dnsserver>10.0.0.1</dnsserver></dnsservers>"
           "<dnssuffixes><dnssuffix>.internal.test</dnssuffix></dnssuffixes>"
           "<includeroutes><route><destination>10.0.0.0</destination><mask>16</mask></route>"
           "</includeroutes></clientconfig></AzVpnProfile>")
    def phonebook(document):
        blob = document.encode("utf-16-le").hex()
        return ("[other]\r\nThirdPartyProfileInfo=00\r\n[fixture]\r\nThirdPartyProfileInfo="
                + blob[:80] + "\r\nThirdPartyProfileInfo=" + blob[80:] + "\r\n").encode("utf-16")
    assert verify(phonebook(xml), xml.encode())["installedEntries"] == 1
    with pytest.raises(CampaignError, match="audience, servers"):
        verify(phonebook(xml.replace("current", "stale")), xml.encode())
    with pytest.raises(CampaignError, match="unexpected number"):
        verify(phonebook(xml), xml.encode(), absent=True)
    assert verify(b"", xml.encode(), absent=True)["installedEntries"] == 0


@pytest.mark.parametrize("changes", [
    {"accountActions": {"primary": "signup"}, "secondaryUserId": None}, {"secondaryUserId": PRIMARY},
    {"secondaryUserId": "malformed"}, {"accountActions": {"primary": "signup", "secondary": "resume"}},
])
def test_consolidated_account_entry_requires_two_distinct_created_identities(changes):
    data = PLAN | ACCOUNT | changes | {"executionId": "one", "operation": "account", "finishedAt": "now"}
    with pytest.raises(CampaignError, match="two distinct"):
        proof_disposition(data, PLAN, "one", "account", "Succeeded")


def test_current_core_and_each_downstream_gate(tmp_path):
    package = tmp_path / consolidated.PACKAGE_ID
    review = save(package / "review-package.json", {"sourceCommit": PLAN["sourceCommit"]})
    save(package / "planned-bindings.json", PLAN)
    run = tmp_path / ("run-" + file_hash(review)[:8])
    dispatch = lambda arguments, inputs=None: consolidated.guard_dispatch(package, arguments, inputs or {})
    dispatch(["account"])
    dispatch(["telemetry"])
    with pytest.raises(FileNotFoundError):
        dispatch(["core"])
    evidence(run, "account", ACCOUNT)
    dispatch(["core"])
    for operation in ("activity-delivery-happy", "restore-snapshot", "capacity", "workload"):
        with pytest.raises(FileNotFoundError):
            dispatch([operation])
    payload = {"fixture": FIXTURE, "core": {"status": "accepted"}, "managedAcceptance": "only listed core observations accepted"}
    fixture_path = evidence(run, "core", payload)
    folder = run / "scanner-in-window"
    last = "worker-read-restored-03.native.json"
    status = {"verified": True, "lastProvisioningState": "Succeeded", "differencesFromOriginal": [],
              "executionPendingOrUnknown": False, "lastNativeReadback": last}
    save(folder / "worker-read-restoration.json", status)
    body = {"id": PLAN["helperJobResourceId"], "identity": {"type": "UserAssigned", "userAssignedIdentities": {"migration": {}}},
            "properties": {"provisioningState": "Succeeded", "configuration": {"registries": []}, "template": {"containers": []}}}
    original = {"exitCode": 0, "stdout": json.dumps(body)}
    save(folder / "worker-read-original.native.json", original)
    altered = body | {"identity": {"type": "UserAssigned", "userAssignedIdentities": {"worker": {}}}}
    save(folder / last, {"exitCode": 0, "stdout": json.dumps(altered)})
    with pytest.raises(CampaignError, match="native configuration"):
        dispatch(["capacity"])
    save(folder / last, original)
    for operation in ("activity-delivery-happy", "restore-snapshot", "capacity", "workload"):
        dispatch([operation, "--fixture", "/tmp/current.json"], {"current.json": str(fixture_path)})
    with pytest.raises(CampaignError, match="this run"):
        dispatch(["capacity", "--fixture", "/tmp/other.json"], {"other.json": str(review)})
    rejected = FIXTURE | {"foreign": FIXTURE["foreign"] | {"userId": PRIMARY}}
    evidence(run, "core", payload | {"fixture": rejected})
    with pytest.raises(CampaignError, match="independent scopes"):
        dispatch(["restore-verify"])
    save(run / "stop-proof-intent.json", {})
    with pytest.raises(CampaignError, match="stopped"):
        dispatch(["telemetry"])


def context(tmp_path):
    end = datetime(2026, 11, 24, 12, 42, tzinfo=UTC)
    return SimpleNamespace(package=tmp_path, run=tmp_path / "current", rg="target", sub="subscription",
        plan=PLAN | {"workspaceResourceId": "/subscriptions/subscription/resourcegroups/target/providers/workspaces/current"},
        policy=SimpleNamespace(clock=lambda: end, check=lambda: None, stop_by=end + timedelta(minutes=3)),
        window={"executionStartAt": utc(end - timedelta(hours=1))}, admit=lambda: None)


@pytest.mark.parametrize("failed,other", [("read_signals", "nativeWindows"), ("read_windows", "sourceRows")])
def test_failed_capture_retains_other_result(tmp_path, monkeypatch, failed, other):
    ctx = context(tmp_path)
    def broken(*args):
        raise CampaignError("native read failed")
    for name in ("read_signals", "read_windows"):
        monkeypatch.setattr(windows, name, broken if name == failed else lambda *args: {"status": "captured", "evidence": "other"})
    result = windows.capture(ctx, "before-stop")
    assert result[other] == {"status": "captured", "evidence": "other"}
    assert {result[k]["status"] for k in ("sourceRows", "nativeWindows")} == {"captured", "unproved"}
    assert json.loads((ctx.run / "integrity-windows/before-stop/summary.json").read_text()) == result


def test_integrity_rows_and_native_count_have_distinct_evidence(tmp_path):
    ctx = context(tmp_path)
    folder = tmp_path / "capture"
    folder.mkdir()
    end = ctx.policy.clock()
    plan = ctx.plan
    query_file = tmp_path / "queries/integrity-source-rows.kql"
    query_file.parent.mkdir()
    query_file.write_bytes(windows.signal_query(plan["release"], plan["deployment"]).encode())
    plan["queryFiles"] = {"integrity-source-rows": file_hash(query_file)}
    ctx.get = lambda *args, **kwargs: {"id": plan["workspaceResourceId"], "properties": {"customerId": PRIMARY}}
    query = "project Count"
    save(tmp_path / "catalog.json", {"alerts": [{"id": windows.RULE, "query": query}]})
    active = {"alertRule": plan["deployment"] + "-" + windows.RULE, "targetResource": plan["workspaceResourceId"],
              "startDateTime": utc(end), "monitorCondition": "Fired"}
    condition = {"windowStartTime": utc(end - timedelta(days=2)), "windowEndTime": utc(end),
                 "allOf": [{"timeAggregation": "Count", "metricValue": 1, "searchQuery": query}]}
    alert = {"id": "instance", "properties": {"essentials": active, "context": {"context": {"condition": condition}}}}
    rows = [[utc(end - timedelta(minutes=3)), utc(end), "bound-signal", plan["release"], plan["deployment"],
             "mobius-worker", windows.SIGNAL, 0, "MobiusMetric_CL"]]
    def reply(path, label, args, **kwargs):
        data = ({"tables": [{"columns": [{"name": c} for c in windows.COLUMNS], "rows": rows}]}
                if label == "source-rows" else {"value": [alert]})
        save(path / (label + ".native.json"), {"exitCode": 0, "stdout": json.dumps(data)})
        return data
    ctx.call = reply
    assert windows.read_signals(ctx, folder, end, end)["returnedRows"] == 1
    summary = windows.read_windows(ctx, folder, end, end)["windows"]
    assert len(summary) == 1 and summary[0]["queryResultCount"] == 1 and summary[0]["queryMatches"]
    native = json.loads(json.loads((folder / "source-rows.native.json").read_text())["stdout"])
    assert native["tables"][0]["rows"][0][7] == 0
    assert "Value" not in summary[0]
