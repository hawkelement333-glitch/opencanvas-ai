"""Replacement cleanup planning: all partial prefixes retain the predecessor."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from test_milestone_7_8_campaign_enablement import (
    _cleanup_arm_success_results,
    _command_result,
    _config,
    _controller_account_record,
    _runtime,
)

from infra.milestone_7_8.campaign import CampaignError, Ledger, Phase
from infra.milestone_7_8.campaign_deadline_renewal import (
    AUTHORITY_TAG,
    BINDING_TAG,
    DEADLINE_TAG,
    activation_request,
    build_plan,
    classify_readback,
)
from infra.milestone_7_8.operator import cleanup_job_parameters, controller_binding_sha256

NOW = datetime(2030, 1, 1, 1, tzinfo=UTC)


def fixture():
    config = _config(authorized_ceiling_usd="56.51", maximum_hours=8)
    runtime = {
        **_runtime(),
        "subscriptionId": "00000000-0000-4000-8000-000000000001",
        "automationAccountName": "aa-m78-controller-aaaaaaaaaa",
        "automationApiVersion": "2024-10-23",
        "runbookName": "Remove-M78Campaign",
        "scheduleName": "m78-deadline-aabbccddee",
        "bindingName": "00000000-0000-4000-8000-000000000002",
        "cleanupScriptSha256": hashlib.sha256(b"cleanup-content").hexdigest(),
        "cleanupAuthorityExpiresUtc": "2030-01-01T05:00:00Z",
        "controllerAuthorizedUntilUtc": "2030-01-01T09:00:00Z",
        "freshControllerAdmissionEvidenceVersion": (
            "m7.8-fresh-subscription-predeployment-absence-evidence-v1"
        ),
    }
    runtime["controllerBindingSha256"] = controller_binding_sha256(
        runtime["subscriptionId"],
        resource_group=config.cleanup_resource_group,
        account=runtime["automationAccountName"],
        runbook=runtime["runbookName"],
    )
    ledger = Ledger(
        config.campaign_id,
        config.generation_id,
        phase=Phase.INFRASTRUCTURE_DEPLOYED,
        cleanup_deadline_utc=config.cleanup_deadline_utc,
        original_cleanup_deadline_utc=config.cleanup_deadline_utc,
        first_billable_mutation_utc="2030-01-01T00:00:00Z",
        cleanup_arm_evidence_sha256="e" * 64,
    )
    base = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
        f"automationAccounts/{runtime['automationAccountName']}"
    )
    target = {
        "id": (
            f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
            f"{config.target_resource_group}"
        ),
        "name": config.target_resource_group,
        "properties": {"provisioningState": "Succeeded"},
        "tags": {
            "mobius.campaign": config.campaign_id,
            "mobius.generation": config.generation_id,
            "mobius.cleanup-deadline-utc": config.cleanup_deadline_utc,
            "mobius.expiry": config.cleanup_deadline_utc,
            "mobius.cost-ceiling-cents": "5651",
            "mobius.fresh-controller-admission-sha256": (
                config.fresh_controller_admission_evidence_sha256
            ),
            "unrelated": "preserved",
        },
    }
    baseline = {
        "observedAtUtc": "2030-01-01T01:00:00Z",
        "target": target,
        "schedule": {
            "name": runtime["scheduleName"],
            "id": base + "/schedules/" + runtime["scheduleName"],
            "properties": {
                "isEnabled": True,
                "frequency": "OneTime",
                "startTime": config.cleanup_deadline_utc,
            },
        },
        "binding": {
            "id": base + "/jobSchedules/" + runtime["bindingName"],
            "properties": {
                "jobScheduleId": runtime["bindingName"],
                "runbook": {"name": runtime["runbookName"]},
                "schedule": {"name": runtime["scheduleName"]},
                "parameters": cleanup_job_parameters(config, runtime),
            },
        },
        "cleanupJobs": [],
        "cleanupJobsComplete": True,
        "controllerAuthorizedUntilUtc": runtime["controllerAuthorizedUntilUtc"],
    }
    return config, runtime, ledger, baseline


def plan_fixture():
    config, runtime, ledger, baseline = fixture()
    plan = build_plan(
        config,
        runtime,
        ledger,
        new_deadline="2030-01-01T08:00:00Z",
        authorized_not_after_utc="2030-01-01T08:00:00Z",
        baseline=baseline,
        now=NOW,
    )
    return plan, baseline


def snapshot(plan, baseline, prefix):
    observed = copy.deepcopy(baseline)
    observed["readStatus"] = dict.fromkeys(("target", "schedule", "binding"), "found")
    observed.update(newSchedule=None, newBinding=None)
    observed["readStatus"].update(newSchedule="absent", newBinding="absent")
    if prefix >= 1:
        observed["newSchedule"] = {
            "id": plan["after"]["scheduleId"],
            "name": plan["after"]["scheduleName"],
            "properties": copy.deepcopy(plan["stageRequests"][0]["body"]["properties"]),
        }
        observed["readStatus"]["newSchedule"] = "found"
    if prefix >= 2:
        observed["newBinding"] = {
            "id": plan["after"]["bindingId"],
            "properties": {
                **copy.deepcopy(plan["stageRequests"][1]["body"]["properties"]),
                "jobScheduleId": plan["after"]["bindingName"],
            },
        }
        observed["readStatus"]["newBinding"] = "found"
    if prefix >= 3:
        observed["target"]["tags"] = copy.deepcopy(plan["afterTags"])
    return observed


@pytest.mark.parametrize(
    ("prefix", "classification"),
    [
        (0, "old-active"),
        (1, "old-active"),
        (2, "new-staged"),
        (3, "new-active"),
    ],
)
def test_every_partial_prefix_keeps_predecessor_and_is_classified(prefix, classification):
    plan, baseline = plan_fixture()
    before = copy.deepcopy(baseline)
    observed = snapshot(plan, baseline, prefix)
    assert classify_readback(plan, observed, now=NOW) == classification
    assert observed["schedule"]["properties"]["isEnabled"] is True
    assert baseline == before
    assert plan["afterTags"]["unrelated"] == "preserved"
    assert plan["before"]["parameters"]["CleanupDeadlineUtc"] == "2030-01-01T04:00:00Z"
    assert plan["after"]["parameters"]["CleanupDeadlineUtc"] == "2030-01-01T08:00:00Z"
    assert all(request["method"] == "PUT" for request in plan["stageRequests"])
    assert "if-match" not in str(plan).lower()


def test_activation_requires_complete_fresh_stage_and_is_not_a_retry():
    plan, baseline = plan_fixture()
    for prefix in (0, 1, 3):
        with pytest.raises(CampaignError, match="not safely staged"):
            activation_request(plan, snapshot(plan, baseline, prefix), now=NOW)
    request = activation_request(plan, snapshot(plan, baseline, 2), now=NOW)
    assert request["method"] == "PATCH"
    assert request["body"]["operation"] == "Merge"
    assert request["body"]["properties"]["tags"] == plan["activationTags"]
    assert all(len(value) <= 256 for value in plan["activationTags"].values())


@pytest.mark.parametrize(
    "defect",
    [
        "timeout",
        "conflicting-binding",
        "disabled-predecessor",
        "partial-tag-write",
        "activation-without-binding",
        "deleting",
        "cleanup-job",
        "stale",
        "wrong-target",
        "unexpected-tag",
        "controller-drift",
        "unknown-read-status",
    ],
)
def test_ambiguous_or_conflicting_state_never_authorizes_activation(defect):
    plan, baseline = plan_fixture()
    observed = snapshot(plan, baseline, 2)
    if defect == "timeout":
        observed["readStatus"]["newBinding"] = "timeout"
    elif defect == "conflicting-binding":
        observed["newBinding"]["properties"]["parameters"]["CostCeilingCents"] = "9999"
    elif defect == "disabled-predecessor":
        observed["schedule"]["properties"]["isEnabled"] = False
    elif defect == "partial-tag-write":
        observed["target"]["tags"][DEADLINE_TAG] = plan["after"]["deadlineUtc"]
    elif defect == "activation-without-binding":
        observed = snapshot(plan, baseline, 1)
        observed["target"]["tags"] = plan["afterTags"]
    elif defect == "deleting":
        observed["target"]["properties"]["provisioningState"] = "Deleting"
    elif defect == "cleanup-job":
        observed["cleanupJobs"] = [{"status": "Running"}]
    elif defect == "stale":
        observed["observedAtUtc"] = "2030-01-01T00:00:00Z"
    elif defect == "wrong-target":
        observed["target"]["id"] += "-other"
    elif defect == "unexpected-tag":
        observed["target"]["tags"]["unexpected"] = "changed"
    elif defect == "controller-drift":
        observed["controllerAuthorizedUntilUtc"] = "2030-01-01T07:00:00Z"
    elif defect == "unknown-read-status":
        del observed["readStatus"]["newSchedule"]
    assert classify_readback(plan, observed, now=NOW) == "uncertain"
    with pytest.raises(CampaignError):
        activation_request(plan, observed, now=NOW)


@pytest.mark.parametrize("phase", [Phase.CLEANING, Phase.CLEANED, Phase.FINALIZED])
def test_campaign_whose_deletion_began_is_not_reopened(phase):
    config, runtime, ledger, baseline = fixture()
    ledger.phase = phase
    with pytest.raises(CampaignError, match="active bound campaign"):
        build_plan(
            config,
            runtime,
            ledger,
            new_deadline="2030-01-01T08:00:00Z",
            authorized_not_after_utc="2030-01-01T08:00:00Z",
            baseline=baseline,
            now=NOW,
        )


@pytest.mark.parametrize(
    "defect", ["late", "over-budget-window", "controller-short", "cleanup-started"]
)
def test_plan_rejects_expansion_or_loss_of_protection(defect):
    config, runtime, ledger, baseline = fixture()
    now = NOW
    new = maximum = "2030-01-01T08:00:00Z"
    if defect == "late":
        now = NOW + timedelta(hours=2, minutes=31)
    elif defect == "over-budget-window":
        new = maximum = "2030-01-01T09:00:00Z"
    elif defect == "controller-short":
        runtime["controllerAuthorizedUntilUtc"] = "2030-01-01T08:59:59Z"
        baseline["controllerAuthorizedUntilUtc"] = runtime["controllerAuthorizedUntilUtc"]
    else:
        ledger.cleanup_started_utc = "2030-01-01T00:30:00Z"
    with pytest.raises(CampaignError):
        build_plan(
            config,
            runtime,
            ledger,
            new_deadline=new,
            authorized_not_after_utc=maximum,
            baseline=baseline,
            now=now,
        )


def test_new_active_after_old_deadline_is_not_accepted_as_timely_completion():
    plan, baseline = plan_fixture()
    observed = snapshot(plan, baseline, 3)
    observed["observedAtUtc"] = "2030-01-01T04:00:00Z"
    assert classify_readback(plan, observed, now=NOW + timedelta(hours=3)) == "uncertain"


def test_plan_hash_prevents_request_substitution():
    plan, baseline = plan_fixture()
    plan["activationTags"][AUTHORITY_TAG] = "f" * 64
    with pytest.raises(CampaignError, match="hash differs"):
        classify_readback(plan, snapshot(plan, baseline, 2), now=NOW)


def test_replacement_names_are_deterministic_and_never_reuse_predecessor():
    first, _ = plan_fixture()
    second, _ = plan_fixture()
    assert first == second
    assert first["before"]["scheduleName"] != first["after"]["scheduleName"]
    assert first["before"]["bindingName"] != first["activationTags"][BINDING_TAG]


def renewed_readback(plan):
    from infra.milestone_7_8.campaign_deadline_renewal import config_from_snapshot

    old = _cleanup_arm_success_results(
        config_from_snapshot(plan["beforeConfig"]), plan["beforeRuntime"]
    )
    deployment = json.loads(old[0]["stdout"])
    deployment["properties"]["outputs"]["costCeilingCents"]["value"] = 5651
    old[0] = _command_result(deployment)
    new = _cleanup_arm_success_results(
        config_from_snapshot(plan["afterConfig"]), plan["afterRuntime"]
    )
    predecessor = copy.deepcopy(plan["baseline"]["binding"])
    active = json.loads(new[12]["stdout"])
    return [*old[:4], *new[4:6], new[9], _command_result({"value": [predecessor, active]}), new[12]]


def execution_fixture(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from infra.milestone_7_8 import campaign_deadline_renewal as renewal
    from infra.milestone_7_8 import cleanup_controller

    plan, baseline = plan_fixture()
    authorizations = []
    for name in ("old", "new"):
        path = tmp_path / f"{name}-auth.json"
        path.write_text(json.dumps({"version": "m7.8-execution-authorization-v6"}))
        authorizations.append(path)
    calls = []

    def authorize(path, *, config, runtime, operation, now):
        active = path == authorizations[1]
        expected = plan["after"] if active else plan["before"]
        assert config.cleanup_deadline_utc == expected["deadlineUtc"]
        assert runtime["bindingName"] == expected["bindingName"]
        calls.append((active, operation))
        return SimpleNamespace(authorization_sha256=("b" if active else "a") * 64)

    monkeypatch.setattr(cleanup_controller, "load_execution_authorization", authorize)
    monkeypatch.setattr(
        renewal,
        "local_source_binding",
        lambda: (plan["beforeRuntime"]["sourceHead"], plan["beforeRuntime"]["cleanupScriptSha256"]),
    )

    class Provider:
        prefix = 0
        fail_at = None
        apply_failed = False
        unreadable_once = False

        def run(self, command):
            index = len(self.commands)
            self.commands.append(command)
            if index == self.fail_at:
                if self.apply_failed:
                    self.prefix += 1
                raise TimeoutError("transport outcome unknown")
            self.prefix += 1
            return _command_result({})

        def snapshot(self):
            if self.unreadable_once:
                self.unreadable_once = False
                raise TimeoutError("GET unavailable")
            return snapshot(plan, baseline, self.prefix)

    provider = Provider()
    provider.commands = []
    kwargs = dict(
        old_authorization=authorizations[0],
        new_authorization=authorizations[1],
        directory=tmp_path / "journal",
        runner=provider,
        collect_snapshot=provider.snapshot,
        collect_cleanup_readback=lambda: renewed_readback(plan),
        clock=lambda: NOW,
    )
    return renewal, plan, provider, kwargs, calls


def test_executor_proves_timeout_that_applied_and_never_replays(monkeypatch, tmp_path):
    renewal, plan, provider, kwargs, calls = execution_fixture(monkeypatch, tmp_path)
    provider.fail_at, provider.apply_failed = 1, True
    record = renewal.execute_plan(plan, **kwargs)
    assert len(provider.commands) == 3
    assert record["completion"]["beforeDeadlineUtc"] == plan["before"]["deadlineUtc"]
    assert (False, "cleanup-arm") in calls and (True, "cleanup-arm") in calls
    assert renewal.execute_plan(plan, **kwargs) == record
    assert len(provider.commands) == 3


def test_executor_unapplied_timeout_cannot_be_retried_then_can_reconcile(monkeypatch, tmp_path):
    renewal, plan, provider, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    provider.fail_at = 1
    with pytest.raises(CampaignError, match="reconciliation"):
        renewal.execute_plan(plan, **kwargs)
    with pytest.raises(CampaignError, match="refusing replay"):
        renewal.execute_plan(plan, **kwargs)
    assert len(provider.commands) == 2
    # Provider later finishes the already dispatched binding; only activation remains.
    provider.prefix = 2
    record = renewal.execute_plan(plan, **kwargs)
    assert record["completion"]["afterDeadlineUtc"] == plan["after"]["deadlineUtc"]
    assert len(provider.commands) == 3


@pytest.mark.parametrize("prefix", [0, 1, 2, 3])
def test_executor_resumes_each_confirmed_prefix(monkeypatch, tmp_path, prefix):
    renewal, plan, provider, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    provider.prefix = prefix
    renewal.execute_plan(plan, **kwargs)
    assert len(provider.commands) == 3 - prefix


def test_no_dispatch_or_new_completion_after_old_expiry(monkeypatch, tmp_path):
    renewal, plan, provider, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    provider.prefix = 3
    kwargs["clock"] = lambda: NOW + timedelta(hours=3)
    with pytest.raises(CampaignError, match="old deadline"):
        renewal.execute_plan(plan, **kwargs)
    assert provider.commands == []


def test_evidence_preserves_original_foundation_and_disarms_all_bindings(monkeypatch, tmp_path):
    from infra.milestone_7_8.operator import command_plan

    renewal, plan, _, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    record = renewal.execute_plan(plan, **kwargs)
    evidence_path = Path(plan["afterRuntime"]["campaignParametersFile"]).resolve().parent
    # Bind the file beside parameters, without altering the immutable plan.
    monkeypatch.chdir(tmp_path)
    evidence_path = tmp_path / "runtime"
    evidence_path.mkdir()
    evidence_path = evidence_path / "renewal-evidence.json"
    evidence_path.write_text(
        json.dumps({"version": "m7.8-campaign-deadline-renewal-evidence-v1", "records": [record]})
    )
    runtime = {
        **plan["afterRuntime"],
        "deadlineRenewalEvidenceFile": str(evidence_path),
        "deadlineRenewalEvidenceSha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    assert renewal.load_evidence(runtime)["records"][0] == record
    config = renewal.config_from_snapshot(plan["afterConfig"])
    commands = command_plan("cleanup-disarm", config, runtime)
    assert len(commands) == 6
    assert plan["before"]["bindingName"] in " ".join(commands[0])
    assert plan["after"]["bindingName"] in " ".join(commands[2])
    ledger = Ledger(**plan["beforeLedger"])
    ledger.record_deadline_renewal(record["completion"])
    renewal.validate_ledger_binding(runtime, ledger)
    assert ledger.original_cleanup_deadline_utc == plan["before"]["deadlineUtc"]
    assert ledger.cleanup_deadline_utc == plan["after"]["deadlineUtc"]


@pytest.mark.parametrize("absent_target", [False, True])
def test_discard_staged_replacement_keeps_predecessor(monkeypatch, tmp_path, absent_target):
    renewal, plan, provider, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    provider.prefix = 2

    def read():
        observed = provider.snapshot()
        if absent_target:
            observed["target"] = None
            observed["readStatus"]["target"] = "absent"
        return observed

    class DeleteRunner:
        def run(self, command):
            assert "delete" in command
            assert plan["before"]["bindingId"] not in " ".join(command)
            provider.commands.append(command)
            provider.prefix -= 1
            return _command_result({})

    options = dict(
        authorization=kwargs["old_authorization"],
        directory=tmp_path / "discard",
        runner=DeleteRunner(),
        clock=lambda: NOW,
        collect_snapshot=read,
    )
    record = renewal.discard_staged_plan(plan, **options)
    assert len(provider.commands) == 2
    assert record["snapshot"]["readStatus"]["newSchedule"] == "absent"
    assert record["snapshot"]["schedule"]["properties"]["isEnabled"] is True
    assert renewal.discard_staged_plan(plan, **options) == record
    assert len(provider.commands) == 2


@pytest.mark.parametrize("case", ["activated", "unknown", "started", "after-cutoff"])
def test_discard_never_removes_active_or_uncertain_protection(monkeypatch, tmp_path, case):
    renewal, plan, provider, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    provider.prefix = 3 if case == "activated" else 2
    observed = provider.snapshot()
    now = NOW
    if case == "unknown":
        observed["readStatus"]["newBinding"] = "unknown"
    if case == "started":
        observed["target"]["tags"]["mobius.cleanup-started-utc"] = "2030-01-01T00:59:00Z"
    if case == "after-cutoff":
        now = NOW + timedelta(hours=3)
        observed["observedAtUtc"] = "2030-01-01T04:00:00Z"
    with pytest.raises(CampaignError, match="active or uncertain"):
        renewal.discard_staged_plan(
            plan,
            authorization=kwargs["old_authorization"],
            directory=tmp_path / "discard",
            runner=provider,
            clock=lambda: now,
            collect_snapshot=lambda: observed,
        )
    assert provider.commands == []


@pytest.mark.parametrize(
    "conflict",
    [
        None,
        "pagination",
        "failed-get",
        "duplicate",
        "foreign-terminal",
        "local-terminal",
        "failed-empty-terminal",
        "active",
    ],
)
def test_live_collector_requires_complete_inventories_and_exact_gets(conflict):
    from infra.milestone_7_8.campaign_deadline_renewal import (
        collect_live_snapshot,
        config_from_snapshot,
    )

    plan, baseline = plan_fixture()
    config, runtime = config_from_snapshot(plan["beforeConfig"]), plan["beforeRuntime"]
    account = _controller_account_record(config, runtime)
    account["tags"]["mobius.controller-authorized-until-utc"] = runtime[
        "controllerAuthorizedUntilUtc"
    ]
    calls = []
    job_id = plan["before"]["scheduleId"].rsplit("/schedules/", 1)[0] + "/jobs/job-1"

    class Runner:
        def run(self, command):
            calls.append(command)
            assert command[command.index("--subscription") + 1] == runtime["subscriptionId"]
            if command[1:3] == ("group", "exists"):
                return _command_result(True)
            url = command[command.index("--url") + 1].split("?", 1)[0]
            if url.endswith(plan["targetId"]):
                return _command_result(baseline["target"])
            if url.endswith("/" + runtime["automationAccountName"]):
                return _command_result(account)
            if url.endswith("/schedules"):
                values = [baseline["schedule"]]
                if conflict == "duplicate":
                    values.append(baseline["schedule"])
                response = {"value": values}
                if conflict == "pagination":
                    response["nextLink"] = "https://management.azure.com/next"
                return _command_result(response)
            if url.endswith("/jobSchedules"):
                return _command_result({"value": [baseline["binding"]]})
            if url.endswith("/jobs"):
                return _command_result(
                    {
                        "value": [{"id": job_id}]
                        if conflict
                        in {"foreign-terminal", "local-terminal", "failed-empty-terminal", "active"}
                        else []
                    }
                )
            if url.endswith(job_id):
                return _command_result(
                    {
                        "id": job_id,
                        "properties": {
                            "status": (
                                "Running"
                                if conflict == "active"
                                else "Failed"
                                if conflict == "failed-empty-terminal"
                                else "Completed"
                            ),
                            "parameters": {}
                            if conflict == "failed-empty-terminal"
                            else {
                                **plan["before"]["parameters"],
                                **(
                                    {
                                        "CampaignId": "other",
                                        "GenerationId": "other",
                                        "TargetResourceGroupName": "rg-other",
                                    }
                                    if conflict in {"foreign-terminal", "active"}
                                    else {}
                                ),
                            },
                        },
                    }
                )
            if url.endswith(plan["before"]["scheduleId"]):
                if conflict == "failed-get":
                    return {"exitCode": 1, "stdout": "", "stderr": "404 or timeout"}
                return _command_result(baseline["schedule"])
            if url.endswith(plan["before"]["bindingId"]):
                return _command_result(baseline["binding"])
            raise AssertionError(url)

    if conflict in {"pagination", "failed-get", "duplicate"}:
        with pytest.raises(CampaignError):
            collect_live_snapshot(config, runtime, runner=Runner(), clock=lambda: NOW, plan=plan)
    else:
        observed = collect_live_snapshot(
            config, runtime, runner=Runner(), clock=lambda: NOW, plan=plan
        )
        assert classify_readback(plan, observed, now=NOW) == (
            "uncertain" if conflict == "active" else "old-active"
        )
        if conflict:
            assert len(observed["cleanupJobs"]) == 1
            assert observed["cleanupJobs"][0]["id"] == job_id
            assert "parameters" in observed["cleanupJobs"][0]["properties"]
        assert observed["readStatus"]["newSchedule"] == "absent"
        assert len(calls) == (9 if conflict else 8)


@pytest.mark.parametrize("deadline", ["2030-01-01T07:59:25Z", "2030-01-01T07:59:00.1Z"])
def test_non_minute_requested_deadline_is_rejected_without_rounding(deadline):
    config, runtime, ledger, baseline = fixture()
    with pytest.raises(CampaignError, match="whole-minute"):
        build_plan(
            config,
            runtime,
            ledger,
            new_deadline=deadline,
            authorized_not_after_utc="2030-01-01T08:00:00Z",
            baseline=baseline,
            now=NOW,
        )


@pytest.mark.parametrize(
    "status",
    [
        "Completed",
        "Failed",
        "Stopped",
        "Running",
        "New",
        "Activating",
        "Starting",
        "Queued",
        "Suspended",
        "Stopping",
        "Unknown",
        "completed",
        "",
        None,
        [],
        {},
    ],
)
def test_only_explicit_terminal_job_states_allow_planning_and_readback(status):
    config, runtime, ledger, baseline = fixture()
    baseline["cleanupJobs"] = [
        {
            "id": "historical-p-six-job",
            "properties": {
                "status": status,
                "parameters": {},
            },
        }
    ]
    options = dict(
        new_deadline="2030-01-01T08:00:00Z",
        authorized_not_after_utc="2030-01-01T08:00:00Z",
        baseline=baseline,
        now=NOW,
    )
    if isinstance(status, str) and status in {"Completed", "Failed", "Stopped"}:
        plan = build_plan(config, runtime, ledger, **options)
        assert plan["baseline"]["cleanupJobs"] == baseline["cleanupJobs"]
        assert classify_readback(plan, snapshot(plan, baseline, 3), now=NOW) == "new-active"
    else:
        with pytest.raises(CampaignError, match="incomplete or drifted"):
            build_plan(config, runtime, ledger, **options)
        plan, _ = plan_fixture()
        assert classify_readback(plan, snapshot(plan, baseline, 3), now=NOW) == "uncertain"


@pytest.mark.parametrize("jobs", [None, {}, [None], [{}], [{"properties": None}]])
def test_malformed_job_inventory_never_proves_no_active_jobs(jobs):
    plan, baseline = plan_fixture()
    observed = snapshot(plan, baseline, 2)
    observed["cleanupJobs"] = jobs
    assert classify_readback(plan, observed, now=NOW) == "uncertain"


@pytest.mark.parametrize("complete", [False, None, "true"])
def test_terminal_jobs_do_not_replace_complete_inventory_proof(complete):
    plan, baseline = plan_fixture()
    observed = snapshot(plan, baseline, 2)
    observed["cleanupJobs"] = [{"properties": {"status": "Failed", "parameters": {}}}]
    observed["cleanupJobsComplete"] = complete
    assert classify_readback(plan, observed, now=NOW) == "uncertain"


def test_focused_correction_gets_new_names_under_same_authority():
    config, runtime, ledger, baseline = fixture()
    first, _ = plan_fixture()
    second = build_plan(
        config,
        runtime,
        ledger,
        new_deadline=first["after"]["deadlineUtc"],
        authorized_not_after_utc=first["authorizedNotAfterUtc"],
        baseline=baseline,
        now=NOW + timedelta(seconds=1),
    )
    assert first["after"]["scheduleName"] != second["after"]["scheduleName"]
    assert first["after"]["bindingName"] != second["after"]["bindingName"]
    assert first["afterConfig"] == second["afterConfig"]
    assert first["before"] == second["before"]


def test_adoption_after_old_cutoff_preserves_original_files(monkeypatch, tmp_path):
    from infra.milestone_7_8 import campaign, operator

    renewal, plan, _, kwargs, _ = execution_fixture(monkeypatch, tmp_path)
    record = renewal.execute_plan(plan, **kwargs)
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "runtime"
    directory.mkdir()
    paths = {name: directory / f"original-{name}.json" for name in ("config", "runtime", "ledger")}
    paths["config"].write_text(json.dumps({"cleanupDeadlineUtc": plan["before"]["deadlineUtc"]}))
    paths["runtime"].write_text(json.dumps(plan["beforeRuntime"]))
    paths["ledger"].write_text(json.dumps(plan["beforeLedger"]))
    originals = {name: path.read_bytes() for name, path in paths.items()}

    def config_from_json(cls, path, **_):
        deadline = json.loads(path.read_text())["cleanupDeadlineUtc"]
        return renewal.config_from_snapshot(
            plan["beforeConfig"]
            if deadline == plan["before"]["deadlineUtc"]
            else plan["afterConfig"]
        )

    # This isolates the atomic sibling-file adoption. Full prepared-bundle validation
    # remains exercised by the existing enablement tests; proof validation stays real.
    monkeypatch.setattr(campaign.CampaignConfig, "from_json", classmethod(config_from_json))
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *a: None)
    monkeypatch.setattr(
        campaign, "load_ledger", lambda path, config: Ledger(**json.loads(path.read_text()))
    )
    options = dict(
        config_path=paths["config"],
        runtime_path=paths["runtime"],
        ledger_path=paths["ledger"],
        output_prefix="renewed-one",
        now=NOW + timedelta(hours=4),
    )
    outputs = renewal.adopt_completion(record, **options)
    assert renewal.adopt_completion(record, **options) == outputs
    assert all(path.read_bytes() == originals[name] for name, path in paths.items())
    new_ledger = json.loads(outputs["ledger"].read_text())
    assert new_ledger["original_cleanup_deadline_utc"] == plan["before"]["deadlineUtc"]
    assert new_ledger["cleanup_deadline_utc"] == plan["after"]["deadlineUtc"]
    options["now"] = NOW + timedelta(hours=7)
    with pytest.raises(CampaignError, match="execution window has expired"):
        renewal.adopt_completion(record, **options)
