from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import (
    _config,
    _controller_account_record,
    _controller_tags,
    _runtime,
)

from infra.milestone_7_8 import late_cleanup, operator
from infra.milestone_7_8.campaign import (
    ORDER,
    RESIDUE_KEYS,
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    SubprocessRunner,
    load_ledger,
    sanitize,
    save_ledger,
)
from infra.milestone_7_8.cleanup_controller import ARCHITECTURE
from infra.milestone_7_8.controller_renewal import _durable_record

BEFORE = datetime(2030, 1, 1, tzinfo=UTC)
NOW = BEFORE + timedelta(days=1)
SOURCE = "f" * 40
JOB = "33333333-3333-4333-8333-333333333333"
DIGEST = "sha256:" + "d" * 64


def write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return path


def result(value: object) -> dict[str, object]:
    return {"exitCode": 0, "stdout": json.dumps(value), "stderr": ""}


def camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class Provider:
    def __init__(
        self, config: CampaignConfig, runtime: dict[str, str], *, scheduled: bool = False,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.clock = NOW
        self.commands: list[tuple[str, ...]] = []
        self.deletes: list[str] = []
        self.binding_exists = True
        self.schedule_exists = True
        self.group_exists = False
        self.fault = ""
        self.base = (
            f"https://management.azure.com/subscriptions/{runtime['subscriptionId']}"
            f"/resourceGroups/{config.cleanup_resource_group}/providers/Microsoft.Automation"
            f"/automationAccounts/{runtime['automationAccountName']}"
        )
        self.job_name = (
            f"SCH_{runtime['bindingName']}_55555555-5555-4555-8555-555555555555_638714736000000000"
            if scheduled else JOB
        )
        self.job: dict[str, object] = {
            "id": self.base.removeprefix("https://management.azure.com") + f"/jobs/{self.job_name}",
            "name": self.job_name,
            "type": "Microsoft.Automation/automationAccounts/jobs",
            "properties": {
                "status": "Completed", "jobId": JOB,
                "runbook": {"name": runtime["runbookName"]},
                "parameters": operator.cleanup_job_parameters(config, runtime),
                "creationTime": "2030-01-01T04:00:00Z",
                "startTime": "2030-01-01T04:00:00Z",
                "endTime": "2030-01-01T04:08:00Z",
            },
        }
        self.receipt = {
            "version": "m7.8-cleanup-receipt-v4",
            "campaignCorrelation": sanitize(config.campaign_id, domain="campaign"),
            "generationCorrelation": sanitize(config.generation_id, domain="generation"),
            "targetResourceGroups": 0,
            "controllerDisposition": "reusable-controller-retained-disarm-required",
            "cleanupDisposition": "target-zero-residue-controller-retained",
            "freshControllerAdmissionEvidenceSha256": (
                config.fresh_controller_admission_evidence_sha256
            ),
            "freshControllerAdmissionEvidenceVersion": (
                runtime["freshControllerAdmissionEvidenceVersion"]
            ),
            "status": "target-removed-controller-disarm-required",
            "observedAtUtc": "2030-01-01T04:08:00Z",
        }
        self.binding: dict[str, object] = {
            "id": self.base.removeprefix("https://management.azure.com")
            + f"/jobSchedules/{runtime['bindingName']}",
            "type": "Microsoft.Automation/automationAccounts/jobSchedules",
            "properties": {
                "jobScheduleId": runtime["bindingName"],
                "runbook": {"name": runtime["runbookName"]},
                "schedule": {"name": runtime["scheduleName"]},
                "parameters": operator.cleanup_job_parameters(config, runtime),
                "runOn": None,
            },
        }
        self.schedule: dict[str, object] = {
            "id": self.base.removeprefix("https://management.azure.com")
            + f"/schedules/{runtime['scheduleName']}",
            "name": runtime["scheduleName"],
            "type": "Microsoft.Automation/automationAccounts/schedules",
            "properties": {
                "frequency": "OneTime", "interval": None, "isEnabled": True,
                "startTime": config.cleanup_deadline_utc, "timeZone": "Etc/UTC",
            },
        }

    def now(self) -> datetime:
        return self.clock

    def output(self) -> dict[str, object]:
        return {
            "exitCode": 0, "stdout": "True\n\n\n\n" + json.dumps(self.receipt) + "\n\n\n\n\n",
            "stderr": "",
        }

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        assert command[command.index("--subscription") + 1] == self.runtime["subscriptionId"]
        if command[:3] == ("az", "group", "exists"):
            assert command[command.index("--name") + 1] == self.config.target_resource_group
            return result(self.group_exists)
        if command[:3] == ("az", "resource", "list"):
            return result([{"type": "Microsoft.App/jobs"}] if self.fault == "residue" else [])
        if command[:3] == ("az", "role", "assignment"):
            return result([])
        if command[:3] == ("az", "group", "show"):
            return result({
                "name": self.config.cleanup_resource_group, "location": self.config.cleanup_region,
                "tags": _controller_tags(self.config, self.runtime),
            })
        if command[:3] == ("az", "automation", "account"):
            return result(_controller_account_record(self.config, self.runtime))
        assert command[:3] == ("az", "rest", "--method"), command[:4]
        method = command[3].lower()
        url = command[command.index("--url") + 1]
        assert method in {"get", "delete"}
        if method == "delete":
            if url.startswith(self.base + f"/jobSchedules/{self.runtime['bindingName']}?"):
                target = "binding"
            else:
                assert url.startswith(self.base + f"/schedules/{self.runtime['scheduleName']}?")
                target = "schedule"
            self.deletes.append(target)
            if self.fault == f"{target}-lost-before":
                raise TimeoutError("synthetic ambiguous provider response")
            if target == "binding":
                self.binding_exists = False
            else:
                self.schedule_exists = False
            if self.fault == "expiry-after-binding" and target == "binding":
                self.clock += timedelta(minutes=31)
            if self.fault == f"{target}-lost-after":
                raise TimeoutError("synthetic lost successful response")
            return {"exitCode": 0, "stdout": "", "stderr": ""}
        if url.startswith(self.base + f"/jobs/{self.job_name}/output?"):
            return self.output()
        if url.startswith(self.base + f"/jobs/{self.job_name}?"):
            return result(self.job)
        if url.startswith(self.base + f"/jobSchedules/{self.runtime['bindingName']}?"):
            return result(self.binding) if self.binding_exists else self.not_found()
        if url.startswith(self.base + f"/schedules/{self.runtime['scheduleName']}?"):
            return result(self.schedule) if self.schedule_exists else self.not_found()
        if url.startswith(self.base + "/schedules?"):
            return result({"value": [self.schedule] if self.schedule_exists else []})
        if url.startswith(self.base + "/jobSchedules?"):
            return result({"value": [self.binding] if self.binding_exists else []})
        if "/deletedAutomationAccounts?" in url:
            return result({"value": []})
        if "/providers/Microsoft.Automation/automationAccounts?" in url:
            return result({"value": [_controller_account_record(self.config, self.runtime)]})
        raise AssertionError("unexpected scoped read")

    @staticmethod
    def not_found() -> dict[str, object]:
        return {"exitCode": 1, "stdout": "", "stderr": "(ResourceNotFound) not found"}


@dataclass
class Case:
    directory: Path
    config: CampaignConfig
    runtime: dict[str, str]
    provider: Provider
    plan: Path
    authorization: Path
    output: Path

    def execute(self) -> dict[str, object]:
        return late_cleanup.execute(
            self.plan, self.authorization,
            runner=cast(SubprocessRunner, self.provider), now=self.provider.now,
        )


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Case:
    config = cast(Callable[[], CampaignConfig], _config)()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    runtime["controllerAuthorizedUntilUtc"] = "2030-01-01T06:00:00Z"
    provider = Provider(config, runtime, scheduled=getattr(request, "param", None) == "scheduled")
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_: None)
    monkeypatch.setattr(late_cleanup, "source_content", lambda: "c" * 64)
    monkeypatch.setattr(late_cleanup, "_stashes", lambda: "d" * 64)
    monkeypatch.setattr(late_cleanup, "_git", lambda *_args, **_kwargs: SOURCE)
    monkeypatch.setattr(late_cleanup, "_clean_source", lambda *_args: SOURCE)
    document = {camel(key): value for key, value in asdict(config).items()}
    document["resourceItems"] = [
        {camel(key): value for key, value in asdict(item).items()} for item in config.resource_items
    ]
    write(tmp_path / "config.json", document)
    write(tmp_path / "runtime.json", runtime)
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.bind_cleanup_region(config)
    ledger.bind_deadline(config.cleanup_deadline_utc)
    for phase in ORDER[1:ORDER.index(Phase.IMAGE_DECIDED) + 1]:
        if phase is Phase.CLEANUP_ARMED:
            ledger.record_cleanup_arm_evidence("e" * 64)
        if phase is Phase.IMAGE_DECIDED:
            ledger.record_image(DIGEST, built=True)
            ledger.record_image_scan(DIGEST, "c" * 64)
        ledger.transition(phase, BEFORE)
    save_ledger(tmp_path / "ledger.json", ledger)
    unsigned = {
        "version": "m7.8-execution-authorization-v5",
        "disposition": "separately-authorized-azure-execution",
        "campaignId": config.campaign_id, "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": runtime["sourceHead"], "controllerArchitecture": ARCHITECTURE,
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "controllerAuthorityEvidenceSha256": runtime["controllerAuthorityEvidenceSha256"],
        "freshControllerAdmissionEvidenceSha256": config.fresh_controller_admission_evidence_sha256,
        "freshControllerAdmissionEvidenceVersion": (
            runtime["freshControllerAdmissionEvidenceVersion"]
        ),
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "expiresAtUtc": runtime["cleanupAuthorityExpiresUtc"],
        "allowedOperations": ["cleanup"],
    }
    write(tmp_path / "original-authorization.json", {
        **unsigned, "authorizationSha256": hashlib.sha256(
            b"m7.8/execution-authorization/v5\0"
            + json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
    })
    write(tmp_path / "job-result.json", result(provider.job))
    write(tmp_path / "output-result.json", provider.output())
    plan = late_cleanup.build_plan(
        runtime_path=tmp_path / "runtime.json", config_path=tmp_path / "config.json",
        ledger_path=tmp_path / "ledger.json", job_result_path=tmp_path / "job-result.json",
        output_result_path=tmp_path / "output-result.json",
        original_authorization_path=tmp_path / "original-authorization.json",
        output_directory=tmp_path / "execution",
    )
    plan_path = write(tmp_path / "plan.json", plan)
    approval_path = write(tmp_path / "explicit-approval.json", {
        "approved": True, "planSha256": plan["planSha256"],
        "allowedOperations": late_cleanup.OPERATIONS, "maximumMinutes": 30,
    })
    validation_path = write(tmp_path / "validation-receipt.json", {
        "status": "passed", "planSha256": plan["planSha256"],
        "operatorSourceHead": SOURCE, "operatorContentSha256": "c" * 64,
        "completedAtUtc": (NOW - timedelta(seconds=1)).isoformat(),
        "checks": dict.fromkeys(("tests", "ruff", "mypy", "schemas", "hygiene"), "passed"),
    })
    authorization = late_cleanup.build_authorization(
        plan_path, approval_path, issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=30)).isoformat(),
        validation_receipt_path=validation_path, now=NOW,
    )
    write(tmp_path / "authorization.json", authorization)
    return Case(tmp_path, config, runtime, provider, plan_path,
                tmp_path / "authorization.json", tmp_path / "execution")


def test_expired_historical_windows_allow_only_fresh_exact_cleanup(case: Case) -> None:
    original = (case.directory / "ledger.json").read_bytes()
    evidence = case.execute()
    assert evidence["status"] == "failed-campaign-closed-zero-residue"
    assert evidence["campaignSucceeded"] is False
    assert case.provider.deletes == ["binding", "schedule"]
    ledger = load_ledger(case.directory / "ledger.json", case.config)
    assert ledger.phase == Phase.FINALIZED.value
    assert set(ledger.residue) == set(RESIDUE_KEYS) and not any(ledger.residue.values())
    receipt = json.loads((case.directory / "terminal-receipt.json").read_text())
    assert receipt["status"] == "zero-residue"
    assert json.loads((case.output / "original-ledger.json").read_text()) == json.loads(original)
    assert ledger.cleanup_completed_utc == "2030-01-01T04:08:00Z"
    assert cast(dict[str, object], case.provider.job["properties"])["endTime"] == (
        "2030-01-01T04:08:00Z"
    )
    assert evidence["ledgerAdoptedAtUtc"] == "2030-01-02T00:00:00Z"


@pytest.mark.parametrize("case", ["scheduled"], indirect=True)
def test_scheduled_resource_name_is_distinct_from_bound_provider_job_uuid(case: Case) -> None:
    assert case.provider.job_name.startswith("SCH_" + case.runtime["bindingName"] + "_")
    job_id = cast(dict[str, object], case.provider.job["properties"])["jobId"]
    assert job_id != case.provider.job_name
    assert json.loads(case.plan.read_text())["scheduledJobId"] == job_id
    assert case.execute()["status"] == "failed-campaign-closed-zero-residue"
    assert case.provider.deletes == ["binding", "schedule"]


@pytest.mark.parametrize("minutes", [-1, 30, 31])
def test_new_authorization_must_be_current_before_any_request(case: Case, minutes: int) -> None:
    case.provider.clock = NOW + timedelta(minutes=minutes)
    with pytest.raises(CampaignError):
        case.execute()
    assert case.provider.commands == [] and case.provider.deletes == []
    assert not (case.directory / "terminal-receipt.json").exists()


def test_expiry_between_deletes_stops_second_mutation(case: Case) -> None:
    case.provider.fault = "expiry-after-binding"
    with pytest.raises(CampaignError):
        case.execute()
    assert case.provider.deletes == ["binding"]
    assert case.provider.schedule_exists
    assert not (case.directory / "terminal-receipt.json").exists()


def test_expiry_during_first_read_prevents_any_further_dispatch(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_ledger = (case.directory / "ledger.json").read_bytes()
    run = case.provider.run

    def consuming_read(command: tuple[str, ...]) -> dict[str, object]:
        response = run(command)
        case.provider.clock = NOW + timedelta(minutes=30)
        return response

    monkeypatch.setattr(case.provider, "run", consuming_read)
    with pytest.raises(CampaignError, match="window is not current"):
        case.execute()
    assert len(case.provider.commands) == 1
    assert case.provider.commands[0][:4] == ("az", "rest", "--method", "get")
    assert case.provider.deletes == []
    assert (case.directory / "ledger.json").read_bytes() == original_ledger
    assert not (case.directory / "terminal-receipt.json").exists()


@pytest.mark.parametrize("fault", [
    "job-id", "job-name", "job-property-id", "job-status", "job-parameter", "binding-parameter",
    "binding-id", "schedule-id", "schedule-deadline", "receipt-correlation", "receipt-status",
])
def test_live_identity_parameter_or_receipt_drift_prevents_deletion(case: Case, fault: str) -> None:
    provider = case.provider
    job_properties = cast(dict[str, object], provider.job["properties"])
    binding_properties = cast(dict[str, object], provider.binding["properties"])
    schedule_properties = cast(dict[str, object], provider.schedule["properties"])
    if fault == "job-id":
        provider.job["id"] = str(provider.job["id"]).replace(JOB, "4" * 32)
    elif fault == "job-name":
        provider.job["name"] = "different-job"
    elif fault == "job-property-id":
        job_properties["jobId"] = "44444444-4444-4444-8444-444444444444"
    elif fault == "job-status":
        job_properties["status"] = "Running"
    elif fault == "job-parameter":
        cast(dict[str, object], job_properties["parameters"])["TargetResourceGroupName"] = (
            "unrelated"
        )
    elif fault == "binding-parameter":
        cast(dict[str, object], binding_properties["parameters"])["TargetResourceGroupName"] = (
            "unrelated"
        )
    elif fault == "binding-id":
        provider.binding["id"] = str(provider.binding["id"]).replace("jobSchedules", "other")
    elif fault == "schedule-id":
        provider.schedule["id"] = str(provider.schedule["id"]).replace("schedules", "other")
    elif fault == "schedule-deadline":
        schedule_properties["startTime"] = "2030-01-01T04:01:00Z"
    elif fault == "receipt-correlation":
        provider.receipt["campaignCorrelation"] = "f" * 16
    else:
        provider.receipt["status"] = "success-without-bound-cleanup"
    with pytest.raises(CampaignError):
        case.execute()
    assert provider.deletes == []
    assert not (case.directory / "terminal-receipt.json").exists()


def test_existing_target_group_cannot_be_deleted_by_late_cleanup(case: Case) -> None:
    case.provider.group_exists = True
    with pytest.raises(CampaignError, match="not absent"):
        case.execute()
    assert case.provider.deletes == []
    assert not any(command[:3] == ("az", "group", "delete") for command in case.provider.commands)


@pytest.mark.parametrize("filename", [
    "runtime.json", "config.json", "job-result.json", "output-result.json",
    "original-authorization.json", "explicit-approval.json", "validation-receipt.json",
])
def test_changed_bound_private_input_prevents_all_provider_requests(
    case: Case, filename: str,
) -> None:
    path = case.directory / filename
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(CampaignError):
        case.execute()
    assert case.provider.commands == []


@pytest.mark.parametrize("fault", ["source-content", "source-head", "stashes"])
def test_changed_executing_source_or_stashes_prevents_requests(
    case: Case, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    if fault == "source-content":
        monkeypatch.setattr(late_cleanup, "source_content", lambda: "1" * 64)
    elif fault == "source-head":
        monkeypatch.setattr(late_cleanup, "_clean_source", lambda *_: "1" * 40)
    else:
        monkeypatch.setattr(late_cleanup, "_stashes", lambda: "1" * 64)
    with pytest.raises(CampaignError):
        case.execute()
    assert case.provider.commands == []


def test_rehashed_plan_cannot_authorize_arbitrary_delete(case: Case) -> None:
    plan = json.loads(case.plan.read_text())
    plan["deletes"][0] = ["az", "group", "delete", "--name", "unrelated", "--yes"]
    plan["planSha256"] = late_cleanup.digest(
        "late-cleanup-plan", {key: value for key, value in plan.items() if key != "planSha256"},
    )
    write(case.plan, plan)
    with pytest.raises(CampaignError, match="command or job scope"):
        case.execute()
    assert case.provider.commands == []


def test_nonzero_residue_cannot_advance_ledger_or_emit_receipt(case: Case) -> None:
    original = (case.directory / "ledger.json").read_bytes()
    case.provider.fault = "residue"
    with pytest.raises(CampaignError, match="residue remains"):
        case.execute()
    assert case.provider.deletes == ["binding", "schedule"]
    assert (case.directory / "ledger.json").read_bytes() == original
    assert not (case.directory / "terminal-receipt.json").exists()
    assert not (case.output / "validated-final-ledger.json").exists()


@pytest.mark.parametrize("target", ["binding", "schedule"])
def test_successful_delete_with_lost_response_is_reconciled_without_repeat(
    case: Case, target: str,
) -> None:
    case.provider.fault = target + "-lost-after"
    with pytest.raises(CampaignError, match="indeterminate"):
        case.execute()
    assert case.provider.deletes.count(target) == 1
    assert not (case.directory / "terminal-receipt.json").exists()
    case.provider.fault = ""
    evidence = case.execute()
    assert evidence["status"] == "failed-campaign-closed-zero-residue"
    assert case.provider.deletes == ["binding", "schedule"]


@pytest.mark.parametrize("target", ["binding", "schedule"])
def test_ambiguous_dispatch_with_resource_present_never_retries(case: Case, target: str) -> None:
    case.provider.fault = target + "-lost-before"
    with pytest.raises(CampaignError, match="indeterminate"):
        case.execute()
    previous = list(case.provider.deletes)
    case.provider.fault = ""
    with pytest.raises(CampaignError, match="unresolved"):
        case.execute()
    assert case.provider.deletes == previous
    assert not (case.directory / "terminal-receipt.json").exists()


@pytest.mark.parametrize("after_dispatch", [False, True])
def test_journal_persistence_failure_never_creates_a_false_completion(
    case: Case, monkeypatch: pytest.MonkeyPatch, after_dispatch: bool,
) -> None:
    original = _durable_record
    suffix = "delete-0.result.json" if after_dispatch else "delete-0.intent.json"

    def persist(path: Path, value: object) -> None:
        if path.name == suffix:
            raise OSError("synthetic durable write failure")
        original(path, value)

    monkeypatch.setattr(late_cleanup, "_durable_record", persist)
    with pytest.raises((CampaignError, OSError)):
        case.execute()
    assert case.provider.deletes == (["binding"] if after_dispatch else [])
    assert not (case.directory / "terminal-receipt.json").exists()
    if after_dispatch:
        monkeypatch.setattr(late_cleanup, "_durable_record", original)
        assert case.execute()["status"] == "failed-campaign-closed-zero-residue"
        assert case.provider.deletes == ["binding", "schedule"]


@pytest.mark.parametrize("fault", [
    "future-validation", "failed-validation", "missing-check", "wrong-source", "wrong-plan",
    "future-issuance", "stale-issuance", "overlong-window",
])
def test_authorization_cannot_start_before_validated_readiness(case: Case, fault: str) -> None:
    path = case.directory / "validation-receipt.json"
    value = json.loads(path.read_text())
    issued, expires = NOW, NOW + timedelta(minutes=30)
    if fault == "future-validation":
        value["completedAtUtc"] = (NOW + timedelta(seconds=1)).isoformat()
    elif fault == "failed-validation":
        value["status"] = "failed"
    elif fault == "missing-check":
        del value["checks"]["schemas"]
    elif fault == "wrong-source":
        value["operatorSourceHead"] = "1" * 40
    elif fault == "wrong-plan":
        value["planSha256"] = "1" * 64
    elif fault == "future-issuance":
        issued += timedelta(seconds=1)
    elif fault == "stale-issuance":
        issued -= timedelta(minutes=2)
        expires = issued + timedelta(minutes=30)
        value["completedAtUtc"] = (issued - timedelta(seconds=1)).isoformat()
    else:
        expires += timedelta(seconds=1)
    write(path, value)
    with pytest.raises(CampaignError):
        late_cleanup.build_authorization(
            case.plan, case.directory / "explicit-approval.json", validation_receipt_path=path,
            issued_at=issued.isoformat(), expires_at=expires.isoformat(), now=NOW,
        )
    assert case.provider.commands == []


def test_normal_cli_requires_execute_flag_and_runs_only_exact_cleanup(
    case: Case, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "late_cleanup", "execute", "--plan", str(case.plan),
        "--authorization", str(case.authorization),
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    assert late_cleanup.main() == 2
    assert case.provider.commands == []
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    execute = late_cleanup.execute

    def frozen_execute(
        plan: Path, authorization: Path, *, runner: SubprocessRunner,
    ) -> dict[str, object]:
        return execute(plan, authorization, runner=runner, now=case.provider.now)

    monkeypatch.setattr(late_cleanup, "execute", frozen_execute)
    monkeypatch.setattr(late_cleanup, "SubprocessRunner", lambda **_kwargs: case.provider)
    monkeypatch.setattr(sys, "argv", [*arguments, "--execute"])
    assert late_cleanup.main() == 0
    value = json.loads(capsys.readouterr().out)
    assert value == {"status": "failed-campaign-closed-zero-residue", "operation": "execute"}
    assert case.provider.deletes == ["binding", "schedule"]
