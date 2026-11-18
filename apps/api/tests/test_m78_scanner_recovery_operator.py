from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from infra.milestone_7_8 import pilot_application_probe as probe
from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.pilot import core_proof_operator as operator
from infra.milestone_7_8.pilot.scanner_hold import POLICY, ProofOperator
from infra.milestone_7_8.pilot.scanner_operator import worker_command, worker_result
from infra.milestone_7_8.pilot.scanner_read_diagnostic import observe
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new

from opencanvas_api.services.documents.errors import DocumentStorageError
from opencanvas_api.services.scanner_bridge import ScannerBridgeEvidenceError


@pytest.mark.parametrize(
    "conflict,outcome",
    [
        ("documents_not_ready", "clean"),
        ("different_conflict", "conflict"),
        ("documents_not_ready", "expired"),
    ],
)
async def test_exact_quarantine_conflict_then_real_promotion_contract(
    tmp_path, monkeypatch, conflict, outcome
):
    now = datetime.now(UTC)
    clock = [0.0]

    class WallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(seconds=clock[0])

    monkeypatch.setattr(probe, "datetime", WallClock)
    monkeypatch.setattr(probe, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    workspace, canvas, session, document, version = (str(uuid4()) for _ in range(5))
    fixture = {"workspaceId": workspace, "canvasId": canvas}
    pending = {
        "objectVersionId": version,
        "scanOutcome": None,
        "objectState": "scan_pending",
        "scanDeadlineAt": (now + timedelta(seconds=899)).isoformat(),
    }

    async def handle(request):
        path = request.url.path
        if path.endswith("upload-sessions"):
            return httpx.Response(
                201,
                json={
                    **fixture,
                    "sessionId": session,
                    "documentId": document,
                    "documentVersionId": str(uuid4()),
                    "objectVersionId": version,
                    "uploadPath": "/api/v1/upload-sessions/" + session + "/content",
                    "capability": "private-fixture",
                },
            )
        if path.endswith("/content"):
            return httpx.Response(204)
        if path.endswith("/complete"):
            return httpx.Response(200, json=pending)
        if path.endswith("/search"):
            return httpx.Response(409, json={"code": conflict})
        if path.endswith(session):
            if outcome == "expired":
                return httpx.Response(200, json=pending)
            return httpx.Response(
                200, json=pending | {"scanOutcome": "clean", "objectState": "clean"}
            )
        if path.endswith("/snapshot"):
            return httpx.Response(
                200, json={"nodes": [{"documentId": document, "id": str(uuid4())}]}
            )
        return httpx.Response(200, json={"status": "ready", "publishedAt": now.isoformat()})

    async def instant(seconds):
        clock[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", instant)
    output = tmp_path / "proof.json"
    journal = probe.Journal(
        output,
        "execution",
        "core",
        {
            "imageDigest": "sha256:" + "a" * 64,
            "sourceCommit": "b" * 40,
            "release": "fixture",
            "deployment": "fixture",
        },
        now + timedelta(hours=1),
    )
    async with httpx.AsyncClient(
        base_url="https://fixture.invalid", transport=httpx.MockTransport(handle)
    ) as client:
        api = probe.Api(client, journal, "execution")
        if outcome == "clean":
            assert (await api.clean_upload(fixture, "first"))["documentId"] == document
            assert len((journal.directory / "scanner-polls.jsonl").read_text().splitlines()) == 2
        elif outcome == "expired":
            with pytest.raises(probe.ScannerDeadline) as error:
                await api.clean_upload(fixture, "first")
            assert error.value.upload["objectVersionId"] == version
            assert clock[0] == 899
            assert error.value.upload["scanDeadlineAt"] == pending["scanDeadlineAt"]
        else:
            with pytest.raises(ValueError, match="unrelated HTTP 409"):
                await api.clean_upload(fixture, "first")


async def test_both_native_reads_have_separate_failure_reasons():
    async def tags(*_, **_kw):
        try:
            raise DocumentStorageError("raw sensitive message", provider_status_code=403)
        except DocumentStorageError as error:
            raise ScannerBridgeEvidenceError("scanner-blob-tags-http-status") from error

    async def logs(**kw):
        assert kw["etag"] == "etag"
        raise ScannerBridgeEvidenceError("scanner-log-query-authorization-unavailable")

    now = datetime.now(UTC)
    bridge = SimpleNamespace(
        blob_reader=SimpleNamespace(read=tags, hostname="fixture.blob.core.windows.net"),
        log_reader=SimpleNamespace(read=logs),
        storage=SimpleNamespace(
            object_url=lambda key: "https://fixture.blob.core.windows.net/" + key
        ),
    )
    result = await observe(
        bridge,
        SimpleNamespace(physical_key="fixture", etag="etag"),
        SimpleNamespace(requested_at=now, deadline_at=now),
        now,
    )
    assert result["blob"] == {
        "status": "failed",
        "code": "scanner-blob-tags-http-status",
        "httpStatus": 403,
    }
    assert result["logAnalytics"] == {
        "status": "failed",
        "code": "scanner-log-query-authorization-unavailable",
    }
    assert result["requestExpired"] and result["correlation"]["status"] == "unproved"
    assert "raw sensitive message" not in str(result)


def test_worker_exec_argument_is_consumable_without_provider(tmp_path):
    import shlex

    source = tmp_path / "fixture.py"
    source.write_text(
        "import json\ndef main(inputs): print('M78-SCANNER-READ:' + json.dumps(inputs))\n"
    )
    inputs = {"challenge": "local", "objectVersionId": str(uuid4())}
    parsed = shlex.split(worker_command(inputs, source))
    result = subprocess.run(
        [sys.executable, *parsed[1:]], check=True, capture_output=True, text=True
    )
    assert worker_result(result.stdout, inputs) == inputs
    with pytest.raises(CampaignError, match="not reconciled"):
        worker_result(result.stdout, inputs | {"challenge": "different"})


def test_recoverable_path_same_deployment_then_scheduled_hard_stop(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    time = [now]
    release = {
        "sourceCommit": "a" * 40,
        "imageDigest": "sha256:" + "b" * 64,
        "release": "stage",
        "deployment": "original-deployment",
    }
    context = operator.Campaign.__new__(operator.Campaign)
    context.run = tmp_path
    context.policy = ProofOperator(
        tmp_path,
        {
            "coreReadyBy": (now + timedelta(hours=1)).isoformat(),
            "stopProofBy": (now + timedelta(hours=9)).isoformat(),
        },
        release,
        clock=lambda: time[0],
    )
    context.admit = lambda: None
    calls = []
    paused = {
        **release,
        "operation": "core",
        "executionId": "first",
        "status": "scanner-paused",
        "managedAcceptance": "unproved",
        "finishedAt": now.isoformat(),
        "upload": {"objectVersionId": "original-object", "scanDeadlineAt": now.isoformat()},
    }
    first = tmp_path / "proof-core/export/core.json"

    def dispatch(ctx, phase, resume=None):
        calls.append((phase, ctx.policy.deployment["deployment"]))
        if phase == "core":
            write_new(first, paused)
            outcome = operator.proof_disposition(paused, release, "first", "core", "Succeeded")
            ctx.policy.hold(first.parent.parent, first, "first")
            return outcome
        assert resume == first
        return "accepted"

    def independent(ctx):
        calls.append(("destination", ctx.policy.deployment["deployment"]))
        assert first.is_file()
        return "destination-readiness-observed"

    def diagnose(ctx, *, repair):
        calls.append(("repair" if repair else "diagnose", ctx.policy.deployment["deployment"]))
        if repair:
            native = tmp_path / "scanner-repair/after-worker-read.json"
            write_new(native, {"correlation": {"status": "agreed", "verdict": "clean"}})
            write_new(
                native.with_name("verified.json"),
                {
                    "repair": POLICY["authorizedRepair"],
                    "deployment": release,
                    "pausedResultSha256": file_hash(first),
                    "objectVersionId": "original-object",
                    "exactLogReadVerified": True,
                    "verificationSha256": file_hash(native),
                },
            )
        return "verified" if repair else "observed"

    monkeypatch.setattr(operator, "dispatch_proof", dispatch)
    monkeypatch.setattr(operator, "destination_readiness", independent)
    monkeypatch.setattr(operator, "collect_and_repair", diagnose)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("unexpected subprocess in scheduled path")
    )
    assert operator.operate(context, "core").startswith("scanner-paused")
    assert operator.operate(context, "diagnose") == "observed"
    assert operator.operate(context, "destination-readiness") == "destination-readiness-observed"
    with pytest.raises(FileNotFoundError):
        operator.operate(context, "core-retry")
    assert operator.operate(context, "repair") == "verified"
    assert operator.operate(context, "core-retry") == "accepted"
    with pytest.raises(FileExistsError):
        operator.operate(context, "core-retry")
    assert read(first) == paused
    assert all(deployment == "original-deployment" for _, deployment in calls)
    assert not (tmp_path / "stop-proof-intent.json").exists()
    time[0] = context.policy.stop_by
    assert operator.operate(context, "diagnose") == "scheduled-cleanup-due"
    assert read(tmp_path / "stop-proof-intent.json")["reason"] == "scheduled-proof-stop"
    assert read(tmp_path / "proof-cleanup-dispatch-intent.json")["kind"] == "scheduled"
    with pytest.raises(CampaignError, match="cleanup dispatch already recorded"):
        operator.operate(context, "core")


def test_unreconciled_native_write_hard_stops_and_dispatches_exact_cleanup(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    context = operator.Campaign.__new__(operator.Campaign)
    context.run, context.bound = tmp_path, tmp_path / "bound"
    context.policy = ProofOperator(
        tmp_path,
        {
            "coreReadyBy": (now + timedelta(hours=1)).isoformat(),
            "stopProofBy": (now + timedelta(hours=9)).isoformat(),
        },
        {},
    )
    context.window = {"automationBindingExpiresAt": (now + timedelta(hours=10)).isoformat()}
    context.admit = lambda: None

    def uncertain(*_args):
        raise operator.NativeFailure("known fixture: uncertain write")

    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "synthetic cleanup receipt", "")

    monkeypatch.setattr(operator, "dispatch_proof", uncertain)
    monkeypatch.setattr(subprocess, "run", execute)
    assert operator.operate(context, "core") == "early-cleanup-dispatched"
    assert calls[0][1:4] == ["-m", "infra.milestone_7_8.operator", "cleanup"]
    assert str(context.bound / "operator-approval.json") in calls[0]
    assert read(tmp_path / "stop-proof-intent.json")["reason"] == "unreconciled-operation"
    with pytest.raises(CampaignError, match="proof already stopped"):
        operator.operate(context, "destination-readiness")
    assert len(calls) == 1


async def test_core_continuation_reuses_prefix_and_uses_one_fresh_upload(monkeypatch):
    now = datetime.now(UTC)
    old_doc, new_doc = str(uuid4()), str(uuid4())
    fixture = {
        "canvasId": "bound-canvas",
        "userId": "bound-user",
        "primary": {"documentId": "accepted-primary"},
    }
    baseline = {
        "positive": "already-proved",
        "refusal": "already-proved",
        "editableArtifact": "already-proved",
    }
    calls = []

    async def unexpected(*args):
        pytest.fail("retry replayed completed setup or grounded requests")

    class ApiFixture:
        async def signin(self):
            return {"id": "bound-user"}

        async def clean_upload(self, existing, suffix):
            calls.append((existing["canvasId"], suffix))
            return {"documentId": new_doc if suffix.endswith("-corrected") else str(uuid4())}

    monkeypatch.setattr(probe, "prepare_core", unexpected)
    monkeypatch.setattr(probe, "verify_primary", unexpected)
    previous = {
        "fixture": fixture,
        "primaryProof": baseline,
        "upload": {
            "suffix": "queued-recovery",
            "documentId": old_doc,
            "scanDeadlineAt": now.isoformat(),
        },
    }
    result = await probe.core(ApiFixture(), previous)
    assert result["core"] == {"status": "accepted", **baseline}
    assert result["fixture"]["queued"]["documentId"] == new_doc
    assert result["fixture"]["primary"]["documentId"] == "accepted-primary"
    assert calls == [
        ("bound-canvas", "queued-recovery-corrected"),
        ("bound-canvas", "deletion-recovery"),
    ]


def test_retained_artifact_console_wrapper_and_failed_proof_disposition():
    expected = {"artifactSha256": "a" * 64, "artifactBytes": 345}
    version = {"sha256": "a" * 64, "bytes": 345, "versionId": "test-exact-version"}
    wrapped = '{"TimeStamp":"2026-11-18T04:50:00Z","Log":"F ' + json.dumps(version) + '"}'
    assert operator.artifact_receipt(wrapped, expected) == version
    with pytest.raises(CampaignError, match="proof failed"):
        operator.proof_disposition(
            {"operation": "core", "executionId": "prior", "errorClass": "ValueError"},
            {},
            "prior",
            "core",
            "Failed",
        )


def test_unchanged_exact_scanner_role_permissions_are_required():
    from infra.milestone_7_8.pilot.scanner_operator import SCANNER_ROLE_ACTIONS, exact_role

    props = {
        "type": "CustomRole",
        "roleName": "scanner-role",
        "assignableScopes": ["/synthetic"],
        "permissions": [
            {
                "actions": sorted(SCANNER_ROLE_ACTIONS),
                "dataActions": [],
                "notDataActions": [],
                "notActions": [],
            }
        ],
    }
    supplied = {"id": "/synthetic/role", "properties": props}
    assert exact_role(supplied, "/synthetic", "scanner-role") == "/synthetic/role"
    props["permissions"][0]["actions"].append(
        "Microsoft.OperationalInsights/workspaces/query/*/read"
    )
    with pytest.raises(CampaignError, match="does not match the sealed narrow role"):
        exact_role(supplied, "/synthetic", "scanner-role")

def test_destination_gate_verifies_azure_integral_float_and_still_rejects_tampering(
    tmp_path,
    monkeypatch,
):
    from infra.milestone_7_8.azure_cli import _validate_argument

    from scripts.telemetry_destination import destination_rows

    now = datetime.now(UTC)
    context = operator.Campaign.__new__(operator.Campaign)
    context.package = tmp_path / "package"
    context.run = tmp_path / "valid"
    context.run.mkdir()
    context.bound = tmp_path / "bound"
    context.window = {
        "executionStartAt": (now - timedelta(minutes=5)).isoformat(),
        "automationBindingExpiresAt": (now + timedelta(hours=3)).isoformat(),
    }
    clock = [now]
    context.policy = ProofOperator(
        context.run,
        {
            "coreReadyBy": (now + timedelta(hours=1)).isoformat(),
            "stopProofBy": (now + timedelta(hours=2)).isoformat(),
        },
        {"release": "r", "deployment": "d", "campaignId": "same-campaign"},
        clock=lambda: clock[0],
    )
    context.admit = lambda: None
    sources = [
        {"service": service, "environment": "staging", "release": "r", "deployment": "d"}
        for service in ("mobius-api", "mobius-worker")
    ]
    write_new(
        context.package / "destination-plan.bound.json",
        {
            "workspaceResourceId": "fixture",
            "release": "r",
            "deployment": "d",
            "productionSources": sources,
        },
    )
    context.get = lambda *args, **kwargs: {"properties": {"customerId": str(uuid4())}}
    native = destination_rows(
        {
            "resource": {"schema": "mobius-operational-v1"},
            "signals": [
                {
                    **source,
                    "schema_version": "mobius-operational-v1",
                    "kind": "metric",
                    "name": "mobius.queue.depth",
                    "component": "queue",
                    "timestamp": now.isoformat(),
                    "payload": {
                        "catalog_version": "mobius-signals-v1",
                        "type": "gauge",
                        "unit": "job",
                        "value": 3.0,
                        "labels": {"component": "queue", "outcome": "success"},
                    },
                }
                for source in sources
            ],
        },
        sources,
        now=now,
    )
    for row in native:
        row["TimeGenerated"] = row["TimeGenerated"].replace("+00:00", "Z")
        row["Payload"] = json.dumps(row["Payload"] | {"value": 3})
    rows = native
    followup_unavailable = False

    def query(folder, label, args, **_kwargs):
        assert args[:3] == ("monitor", "log-analytics", "query")
        for arg in args:
            _validate_argument(arg)
        if followup_unavailable and label == "production-rows-01":
            write_new(
                folder / (label + ".native.json"),
                {"atUtc": clock[0].isoformat(), "status": "timed-out"},
            )
            raise operator.NativeFailure("offline read timeout")
        write_new(
            folder / (label + ".native.json"),
            {"atUtc": clock[0].isoformat(), "exitCode": 0, "stdout": json.dumps(rows)},
        )
        return rows

    context.call = query
    assert operator.operate(context, "destination-readiness") == "destination-readiness-observed"
    assert read(context.run / "destination-readiness/accepted.json")["rows"] == 2

    # A one-source native read is valid evidence but cannot satisfy the gate.
    (tmp_path / "missing-api").mkdir()
    context.run = tmp_path / "missing-api"
    context.policy.run = context.run
    rows = [native[1]]
    followup_unavailable = True
    monkeypatch.setattr(operator.time, "sleep", lambda _: None)
    assert operator.operate(context, "destination-readiness") == "destination-readiness-unproved"
    assert not (context.run / "destination-readiness/accepted.json").exists()
    hold_path = context.run / "destination-readiness/unproved.json"
    hold = read(hold_path)
    assert hold["deployment"] == context.policy.deployment
    assert hold["rows"] == 1
    assert hold["nativeReadback"] == "production-rows-00.native.json"

    independent = []

    def core(ctx, phase, resume):
        assert phase == "core" and resume is None
        assert ctx.remaining(ctx.policy.core_by) > 0
        independent.append((ctx.run, ctx.policy.deployment))
        return "accepted"

    cleanup = []

    def execute(args, **kwargs):
        cleanup.append(args)
        return subprocess.CompletedProcess(args, 0, "offline cleanup receipt", "")

    monkeypatch.setattr(operator, "dispatch_proof", core)
    monkeypatch.setattr(subprocess, "run", execute)
    assert operator.operate(context, "core") == "accepted"
    assert independent == [(context.run, hold["deployment"])]
    clock[0] = context.policy.core_by
    assert (
        operator.operate(context, "gate")
        == "destination-dependent-checks-held-independent-checks-may-continue"
    )
    assert not cleanup
    assert not (context.run / "stop-proof-intent.json").exists()
    clock[0] = context.policy.stop_by
    assert operator.operate(context, "gate") == "scheduled-cleanup-due"
    assert read(context.run / "stop-proof-intent.json")["reason"] == "scheduled-proof-stop"
    assert read(context.run / "proof-cleanup-dispatch-intent.json")["kind"] == "scheduled"
    assert not cleanup

    # The hold's copied native receipt must remain intact at the gate.
    clock[0] = now
    context.run = tmp_path / "changed-hold"
    context.run.mkdir()
    context.policy.run = context.run
    assert operator.operate(context, "destination-readiness") == "destination-readiness-unproved"
    witness = context.run / "destination-readiness" / hold["nativeReadback"]
    witness.write_text("{}", encoding="utf-8")
    clock[0] = context.policy.core_by
    assert operator.operate(context, "gate") == "early-cleanup-dispatched"
    assert read(context.run / "stop-proof-intent.json")["reason"] == "privacy-or-integrity-failure"

    clock[0] = now
    followup_unavailable = False
    for name, bad in (
        (
            "changed",
            native[1] | {"Payload": json.dumps(json.loads(native[1]["Payload"]) | {"value": 4})},
        ),
        ("duplicate", native[0]),
        ("source", native[1] | {"Release": "another-release"}),
        ("late", native[1] | {"TimeGenerated": (now + timedelta(minutes=1)).isoformat()}),
        (
            "privacy",
            native[1] | {"Payload": json.dumps(json.loads(native[1]["Payload"]) | {"body": "x"})},
        ),
    ):
        context.run = tmp_path / name
        context.run.mkdir()
        context.policy.run = context.run
        rows = [native[0], bad]
        assert operator.operate(context, "destination-readiness") == "early-cleanup-dispatched"
        assert read(context.run / "stop-proof-intent.json")["reason"] == "unreconciled-operation"
        assert not (context.run / "destination-readiness/accepted.json").exists()
        assert not (context.run / "destination-readiness/unproved.json").exists()
    assert len(cleanup) == 6
    assert all(
        args[1:4] == ["-m", "infra.milestone_7_8.operator", "cleanup"]
        and str(context.bound / "operator-approval.json") in args
        for args in cleanup
    )
