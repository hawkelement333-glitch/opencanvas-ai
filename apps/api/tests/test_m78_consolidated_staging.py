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


def evidence(run, operation, payload):
    folder = run / ("proof-" + operation)
    receipt = save(folder / "export" / (operation + ".json"), PLAN | payload | {
        "executionId": operation + "-1", "operation": operation, "finishedAt": "2026-11-24T12:00:00Z"})
    save(folder / "accepted.json", {"operation": operation, "execution": operation + "-1", "resultSha256": file_hash(receipt)})
    save(folder / "evidence-execution.json", {"execution": operation + "-1"})
    save(folder / "evidence-terminal.json", {"name": operation + "-1", "properties": {"status": "Succeeded"}})
    return receipt


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
