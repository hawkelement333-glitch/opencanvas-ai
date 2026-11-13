"""Explicit, operator-only closure of an expired, already deleted campaign.

This path cannot start a runbook, delete a group, renew a controller or resume a
campaign. Historical execution authority is evidence, never current authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from infra.milestone_7_8 import operator as op
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    SubprocessRunner,
    load_ledger,
    parse_utc,
    save_ledger,
    terminal_receipt,
    utc,
)
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.cleanup_controller import load_execution_authorization
from infra.milestone_7_8.controller import REPOSITORY_ROOT, local_source_binding
from infra.milestone_7_8.controller_renewal import _durable_record

PLAN_VERSION = "m7.8-late-cleanup-plan-v1"
AUTH_VERSION = "m7.8-late-cleanup-authorization-v1"
OPERATIONS = [
    "adopt-scheduled-cleanup",
    "delete-exact-binding",
    "delete-exact-schedule",
    "verify-residue",
    "finalize-failed-campaign",
]
PLAN_FIELDS = {
    "version",
    "files",
    "ledgerPath",
    "ledgerFileSha256",
    "originalLedger",
    "outputDirectory",
    "reviewSourceHead",
    "operatorContentSha256",
    "protectedStashesSha256",
    "jobResourceId",
    "scheduledJobId",
    "deletes",
    "planSha256",
}
AUTH_FIELDS = {
    "version",
    "planSha256",
    "operatorSourceHead",
    "operatorContentSha256",
    "approvalPath",
    "approvalSha256",
    "issuedAtUtc",
    "expiresAtUtc",
    "allowedOperations",
    "authorizationSha256",
    "validationReceiptPath",
    "validationReceiptSha256",
}
FILE_NAMES = {"runtime", "config", "jobResult", "outputResult", "originalAuthorization"}


def digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        f"m7.8/{domain}/v1\0".encode()
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CampaignError("late cleanup document is not an object")
    return value


def _git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        raise CampaignError("late cleanup source inspection failed")
    return result.stdout.strip()


def source_content() -> str:
    # Bind executable infrastructure dependencies, including this new file before
    # its checkpoint. Execution additionally requires an actual clean commit.
    root = REPOSITORY_ROOT / "infra"
    files = {
        str(p.relative_to(REPOSITORY_ROOT)).replace("\\", "/"): file_hash(p)
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".json", ".bicep", ".ps1"}
        and "__pycache__" not in p.parts
    }
    return digest("late-cleanup-source", files)


def _stashes() -> str:
    hashes = _git("stash", "list", "--format=%H").splitlines()
    if len(hashes) != 5:
        raise CampaignError("late cleanup protected stash count differs")
    return digest("late-cleanup-stashes", hashes)


def _result(value: dict[str, object]) -> object:
    if value.get("exitCode") != 0 or not isinstance(value.get("stdout"), str):
        raise CampaignError("late cleanup read did not succeed")
    return json.loads(str(value["stdout"]))


def validate_scheduled_cleanup(
    job_result: dict[str, object],
    output_result: dict[str, object],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> str:
    job = _result(job_result)
    if not isinstance(job, dict) or not isinstance(job.get("properties"), dict):
        raise CampaignError("scheduled cleanup job is malformed")
    resource = str(job.get("id", ""))
    prefix = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
        f"automationAccounts/{runtime['automationAccountName']}/jobs/"
    )
    if not resource.casefold().startswith(prefix.casefold()):
        raise CampaignError("scheduled cleanup job scope differs")
    tail = resource[len(prefix) :]
    try:
        valid_id = bool(uuid.UUID(tail).int) and str(uuid.UUID(tail)).casefold() == tail.casefold()
    except ValueError:
        parts = tail.split("_")
        try:
            valid_id = (
                len(parts) == 4
                and parts[0] == "SCH"
                and parts[1].casefold() == runtime["bindingName"].casefold()
                and bool(uuid.UUID(parts[1]).int)
                and bool(uuid.UUID(parts[2]).int)
                and re.fullmatch(r"[0-9]{18}", parts[3]) is not None
            )
        except (ValueError, IndexError):
            valid_id = False
    props = cast(dict[str, object], job["properties"])
    try:
        valid_job_id = bool(uuid.UUID(str(props.get("jobId"))).int)
    except ValueError:
        valid_job_id = False
    runbook, parameters = props.get("runbook"), props.get("parameters")
    if (
        not valid_id
        or not valid_job_id
        or str(job.get("name", "")).casefold() != tail.casefold()
        or props.get("status") != "Completed"
        or props.get("exception") not in (None, "")
        or not isinstance(runbook, dict)
        or runbook.get("name") != runtime["runbookName"]
        or not isinstance(parameters, dict)
    ):
        raise CampaignError("scheduled cleanup job is not exactly completed")
    normalized: dict[str, str] = {}
    for key, item in parameters.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise CampaignError("scheduled cleanup parameter shape differs")
        decoded = json.loads(item) if item.startswith('"') else item
        if not isinstance(decoded, str) or key.casefold() in normalized:
            raise CampaignError("scheduled cleanup parameter is ambiguous")
        normalized[key.casefold()] = decoded
    expected = {k.casefold(): v for k, v in op.cleanup_job_parameters(config, runtime).items()}
    if normalized != expected:
        raise CampaignError("scheduled cleanup parameters differ")
    created, started, ended = (
        parse_utc(str(props.get(k))) for k in ("creationTime", "startTime", "endTime")
    )
    deadline = parse_utc(config.cleanup_deadline_utc)
    if not (
        deadline <= created <= deadline + timedelta(minutes=2)
        and created <= started <= ended <= parse_utc(runtime["cleanupAuthorityExpiresUtc"])
    ):
        raise CampaignError("scheduled cleanup historical time binding differs")
    if output_result.get("exitCode") != 0 or not isinstance(output_result.get("stdout"), str):
        raise CampaignError("scheduled cleanup output is unavailable")
    lines = [line.strip() for line in str(output_result["stdout"]).splitlines() if line.strip()]
    objects = [line for line in lines if line.startswith("{")]
    if len(objects) != 1 or any(line != "True" and line not in objects for line in lines):
        raise CampaignError("scheduled cleanup output is ambiguous")
    receipt = json.loads(objects[0])
    expected_receipt = {
        "version": "m7.8-cleanup-receipt-v4",
        "campaignCorrelation": hashlib.sha256(
            ("m7.8/campaign\0" + config.campaign_id).encode()
        ).hexdigest()[:16],
        "generationCorrelation": hashlib.sha256(
            ("m7.8/generation\0" + config.generation_id).encode()
        ).hexdigest()[:16],
        "targetResourceGroups": 0,
        "controllerDisposition": "reusable-controller-retained-disarm-required",
        "cleanupDisposition": "target-zero-residue-controller-retained",
        "freshControllerAdmissionEvidenceSha256": config.fresh_controller_admission_evidence_sha256,
        "freshControllerAdmissionEvidenceVersion": runtime[
            "freshControllerAdmissionEvidenceVersion"
        ],
        "status": "target-removed-controller-disarm-required",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != set(expected_receipt) | {"observedAtUtc"}
        or any(receipt[k] != v for k, v in expected_receipt.items())
        or type(receipt["targetResourceGroups"]) is not int
        or not started <= parse_utc(str(receipt["observedAtUtc"])) <= ended
    ):
        raise CampaignError("scheduled cleanup receipt binding differs")
    return resource


def build_plan(
    *,
    runtime_path: Path,
    config_path: Path,
    ledger_path: Path,
    job_result_path: Path,
    output_result_path: Path,
    original_authorization_path: Path,
    output_directory: Path,
) -> dict[str, object]:
    if output_directory.exists() or not output_directory.resolve().is_relative_to(
        runtime_path.resolve().parent
    ):
        raise CampaignError("late cleanup needs a new private output directory within the bundle")
    if ledger_path.resolve().parent != runtime_path.resolve().parent:
        raise CampaignError("late cleanup ledger must belong to the original bundle")
    runtime = op.load_runtime(runtime_path)
    config = CampaignConfig.from_json(config_path, allow_expired=True)
    op.validate_prepared_bundle(runtime_path, runtime, config)
    ledger = load_ledger(ledger_path, config)
    if Phase(ledger.phase) is not Phase.IMAGE_DECIDED:
        raise CampaignError("late cleanup requires the retained paused campaign")
    job, output = document(job_result_path), document(output_result_path)
    resource = validate_scheduled_cleanup(job, output, config, runtime)
    props = cast(dict[str, object], cast(dict[str, object], _result(job))["properties"])
    load_execution_authorization(
        original_authorization_path,
        config=config,
        runtime=runtime,
        operation="cleanup",
        now=parse_utc(str(props["startTime"])),
    )
    files = {
        "runtime": runtime_path,
        "config": config_path,
        "jobResult": job_result_path,
        "outputResult": output_result_path,
        "originalAuthorization": original_authorization_path,
    }
    plan: dict[str, object] = {
        "version": PLAN_VERSION,
        "files": {
            k: {"path": str(p.resolve(strict=True)), "sha256": file_hash(p)}
            for k, p in files.items()
        },
        "ledgerPath": str(ledger_path.resolve(strict=True)),
        "ledgerFileSha256": file_hash(ledger_path),
        "originalLedger": document(ledger_path),
        "outputDirectory": str(output_directory.resolve()),
        "reviewSourceHead": _git("rev-parse", "HEAD"),
        "operatorContentSha256": source_content(),
        "protectedStashesSha256": _stashes(),
        "jobResourceId": resource,
        "scheduledJobId": props["jobId"],
        "deletes": [list(cmd) for cmd in op.command_plan("cleanup-disarm", config, runtime)[:2]],
    }
    plan["planSha256"] = digest("late-cleanup-plan", plan)
    return plan


def _load_plan(path: Path) -> tuple[dict[str, object], CampaignConfig, dict[str, str], Ledger]:
    plan = document(path)
    if (
        set(plan) != PLAN_FIELDS
        or plan.get("version") != PLAN_VERSION
        or plan.get("planSha256")
        != digest("late-cleanup-plan", {k: v for k, v in plan.items() if k != "planSha256"})
    ):
        raise CampaignError("late cleanup plan hash or fields differ")
    files = plan.get("files")
    if not isinstance(files, dict) or set(files) != FILE_NAMES:
        raise CampaignError("late cleanup file bindings differ")
    paths: dict[str, Path] = {}
    for key, entry in files.items():
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise CampaignError("late cleanup file binding is malformed")
        p = Path(str(entry["path"]))
        if not p.is_absolute() or file_hash(p) != entry["sha256"]:
            raise CampaignError("late cleanup original file changed")
        paths[key] = p
    runtime = op.load_runtime(paths["runtime"])
    config = CampaignConfig.from_json(paths["config"], allow_expired=True)
    op.validate_prepared_bundle(paths["runtime"], runtime, config)
    ledger = Ledger(**cast(dict[str, object], plan["originalLedger"]))  # type: ignore[arg-type]
    ledger.validate_resume(config)
    if Phase(ledger.phase) is not Phase.IMAGE_DECIDED:
        raise CampaignError("late cleanup original phase differs")
    job, output = document(paths["jobResult"]), document(paths["outputResult"])
    resource = validate_scheduled_cleanup(job, output, config, runtime)
    props = cast(dict[str, object], cast(dict[str, object], _result(job))["properties"])
    load_execution_authorization(
        paths["originalAuthorization"],
        config=config,
        runtime=runtime,
        operation="cleanup",
        now=parse_utc(str(props["startTime"])),
    )
    if (
        resource != plan["jobResourceId"]
        or props["jobId"] != plan["scheduledJobId"]
        or plan["deletes"]
        != [list(cmd) for cmd in op.command_plan("cleanup-disarm", config, runtime)[:2]]
    ):
        raise CampaignError("late cleanup command or job scope differs")
    if (
        source_content() != plan["operatorContentSha256"]
        or _stashes() != plan["protectedStashesSha256"]
    ):
        raise CampaignError("late cleanup reviewed source or stashes changed")
    return plan, config, runtime, ledger


def _clean_source(plan: dict[str, object], runtime: dict[str, str]) -> str:
    head, script_hash = local_source_binding()
    if (
        script_hash != runtime["cleanupScriptSha256"]
        or canonical_snapshot(head)["buildInputSha256"] != runtime["canonicalBuildInputSha256"]
    ):
        raise CampaignError("late cleanup changed historical image or cleanup content")
    _git("merge-base", "--is-ancestor", str(plan["reviewSourceHead"]), head)
    return head


def build_authorization(
    plan_path: Path,
    explicit_approval_path: Path,
    *,
    validation_receipt_path: Path,
    issued_at: str,
    expires_at: str,
    now: datetime | None = None,
) -> dict[str, object]:
    plan, _, runtime, _ = _load_plan(plan_path)
    approval = document(explicit_approval_path)
    if (
        approval.get("approved") is not True
        or approval.get("planSha256") != plan["planSha256"]
        or approval.get("allowedOperations") != OPERATIONS
        or approval.get("maximumMinutes") != 30
    ):
        raise CampaignError("explicit late cleanup approval differs")
    auth: dict[str, object] = {
        "version": AUTH_VERSION,
        "planSha256": plan["planSha256"],
        "operatorSourceHead": _clean_source(plan, runtime),
        "operatorContentSha256": plan["operatorContentSha256"],
        "approvalPath": str(explicit_approval_path.resolve(strict=True)),
        "approvalSha256": file_hash(explicit_approval_path),
        "issuedAtUtc": issued_at,
        "expiresAtUtc": expires_at,
        "allowedOperations": OPERATIONS,
        "validationReceiptPath": str(validation_receipt_path.resolve(strict=True)),
        "validationReceiptSha256": file_hash(validation_receipt_path),
    }
    _validate_readiness(auth)
    auth["authorizationSha256"] = digest("late-cleanup-authorization", auth)
    actual_now = now or datetime.now(UTC)
    _window(auth, actual_now)
    if actual_now - parse_utc(issued_at) > timedelta(minutes=1):
        raise CampaignError("late cleanup window must start at actual readiness")
    return auth


def _validate_readiness(auth: dict[str, object]) -> None:
    path = Path(str(auth["validationReceiptPath"]))
    value = document(path)
    if (
        file_hash(path) != auth["validationReceiptSha256"]
        or value.get("status") != "passed"
        or any(
            value.get(k) != auth[k]
            for k in ("planSha256", "operatorSourceHead", "operatorContentSha256")
        )
        or value.get("checks")
        != dict.fromkeys(("tests", "ruff", "mypy", "schemas", "hygiene"), "passed")
        or parse_utc(str(value.get("completedAtUtc"))) > parse_utc(str(auth["issuedAtUtc"]))
    ):
        raise CampaignError("late cleanup validation must pass before window issuance")


def _window(auth: dict[str, object], now: datetime) -> None:
    issued, expires = parse_utc(str(auth["issuedAtUtc"])), parse_utc(str(auth["expiresAtUtc"]))
    if not issued <= now < expires or expires > issued + timedelta(minutes=30):
        raise CampaignError("late cleanup authorization window is not current")


def load_authorization(
    path: Path,
    plan: dict[str, object],
    runtime: dict[str, str],
    now: datetime,
) -> dict[str, object]:
    auth = document(path)
    if (
        set(auth) != AUTH_FIELDS
        or auth.get("version") != AUTH_VERSION
        or auth.get("allowedOperations") != OPERATIONS
        or auth.get("planSha256") != plan["planSha256"]
        or auth.get("operatorContentSha256") != plan["operatorContentSha256"]
        or auth.get("operatorSourceHead") != _clean_source(plan, runtime)
        or auth.get("authorizationSha256")
        != digest(
            "late-cleanup-authorization",
            {k: v for k, v in auth.items() if k != "authorizationSha256"},
        )
    ):
        raise CampaignError("late cleanup authorization is not exact")
    approval_path = Path(str(auth["approvalPath"]))
    approval = document(approval_path)
    if (
        file_hash(approval_path) != auth["approvalSha256"]
        or approval.get("approved") is not True
        or approval.get("planSha256") != plan["planSha256"]
        or approval.get("allowedOperations") != OPERATIONS
        or approval.get("maximumMinutes") != 30
    ):
        raise CampaignError("late cleanup explicit approval was altered")
    _validate_readiness(auth)
    _window(auth, now)
    return auth


class _Capture(SubprocessRunner):
    def __init__(
        self,
        runner: SubprocessRunner,
        directory: Path,
        now: Callable[[], datetime],
        subscription: str,
        authorize: Callable[[], None],
    ) -> None:
        self.runner, self.directory, self.now, self.subscription = (
            runner,
            directory,
            now,
            subscription,
        )
        self.authorize = authorize
        self.sequence = 0

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        # This wrapper is only used for reads. DELETE dispatch is separate below.
        if not (
            command[:4] == ("az", "rest", "--method", "get")
            or command[:3]
            in {
                ("az", "group", "exists"),
                ("az", "group", "show"),
                ("az", "resource", "list"),
                ("az", "role", "assignment"),
                ("az", "automation", "account"),
            }
        ):
            raise CampaignError("late cleanup read command is outside scope")
        if "--subscription" in command:
            if command[command.index("--subscription") + 1] != self.subscription:
                raise CampaignError("late cleanup subscription differs")
        else:
            command = (*command, "--subscription", self.subscription)
        self.sequence += 1
        prefix = self.directory / f"{self.sequence:03d}"
        _durable_record(
            prefix.with_suffix(".intent.json"),
            {
                "command": command,
                "requestedAtUtc": utc(self.now()),
            },
        )
        self.authorize()
        result = self.runner.run(command)
        _durable_record(prefix.with_suffix(".result.json"), result)
        return result


def execute(
    plan_path: Path,
    authorization_path: Path,
    *,
    runner: SubprocessRunner,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    plan, config, runtime, ledger = _load_plan(plan_path)
    auth = load_authorization(authorization_path, plan, runtime, now())
    output = Path(str(plan["outputDirectory"]))
    output.mkdir(parents=True, exist_ok=True)
    binding = {"planSha256": plan["planSha256"], "authorizationSha256": auth["authorizationSha256"]}
    start_path = output / "attempt.json"
    if start_path.exists():
        if document(start_path) != binding:
            raise CampaignError("late cleanup attempt approval differs")
    else:
        if file_hash(Path(str(plan["ledgerPath"]))) != plan["ledgerFileSha256"]:
            raise CampaignError("late cleanup ledger changed before adoption")
        _durable_record(output / "original-ledger.json", plan["originalLedger"])
        _durable_record(start_path, binding)
    if document(output / "original-ledger.json") != plan["originalLedger"]:
        raise CampaignError("late cleanup preserved ledger snapshot differs")
    current_path = Path(str(plan["ledgerPath"]))
    final_path = output / "validated-final-ledger.json"
    if file_hash(current_path) != plan["ledgerFileSha256"] and (
        not final_path.exists() or document(current_path) != document(final_path)
    ):
        raise CampaignError("late cleanup current ledger differs from its checkpoint")
    read_directory = output / ("readback-" + uuid.uuid4().hex)
    read_directory.mkdir()
    capture = _Capture(
        runner, read_directory, now, runtime["subscriptionId"], lambda: _window(auth, now())
    )
    job_url = "https://management.azure.com" + str(plan["jobResourceId"])
    job = capture.run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            job_url + "?api-version=2024-10-23",
            "--output",
            "json",
        )
    )
    job_output = capture.run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            job_url + "/output?api-version=2019-06-01",
            "--output",
            "json",
        )
    )
    if validate_scheduled_cleanup(job, job_output, config, runtime) != plan["jobResourceId"]:
        raise CampaignError("late cleanup live job identity differs")
    if (
        cast(dict[str, object], cast(dict[str, object], _result(job))["properties"])["jobId"]
        != plan["scheduledJobId"]
    ):
        raise CampaignError("late cleanup live job execution ID differs")
    group_command = ("az", "group", "exists", "--name", config.target_resource_group)
    if _result(capture.run(group_command)) is not False:
        raise CampaignError("late cleanup target is not absent; deletion is not authorized")
    disarm = op.command_plan("cleanup-disarm", config, runtime)
    schedule_result, bindings_result = (capture.run(cmd) for cmd in disarm[2:])
    schedules = op._collection(_result(schedule_result), label="late cleanup schedules")
    bindings = op._collection(_result(bindings_result), label="late cleanup bindings")
    if len(schedules) > 1 or len(bindings) > 1:
        raise CampaignError("late cleanup controller contains unrelated bindings or schedules")
    if schedules:
        op.validate_cleanup_schedule(schedules[0], config=config, runtime=runtime)
        schedule = cast(dict[str, object], schedules[0])
        expected_id = (
            disarm[1][disarm[1].index("--url") + 1]
            .split("?")[0]
            .removeprefix("https://management.azure.com")
        )
        if str(schedule.get("id", "")).casefold() != expected_id.casefold():
            raise CampaignError("late cleanup schedule resource ID differs")
    if bindings:
        detail_cmd = list(disarm[0])
        detail_cmd[3] = "get"
        detail_cmd[detail_cmd.index("--output") + 1] = "json"
        detail = _result(capture.run(tuple(detail_cmd)))
        op.validate_cleanup_bindings(
            _result(bindings_result), config=config, runtime=runtime, exact_binding=detail
        )
    for index, present in enumerate((bool(bindings), bool(schedules))):
        command = (*disarm[index], "--subscription", runtime["subscriptionId"])
        intent_path = output / f"delete-{index}.intent.json"
        intent = {**binding, "command": list(command)}
        if intent_path.exists():
            saved = document(intent_path)
            if any(saved.get(k) != v for k, v in intent.items()):
                raise CampaignError("late cleanup saved dispatch history differs")
            _window(auth, parse_utc(str(saved.get("dispatchedAtUtc"))))
            if present:
                raise CampaignError(
                    "late cleanup prior dispatch remains unresolved; no repeat allowed"
                )
            continue
        if not present:
            continue
        if _result(capture.run(group_command)) is not False:
            raise CampaignError("late cleanup target reappeared; stop without mutation")
        _load_plan(plan_path)
        load_authorization(authorization_path, plan, runtime, now())
        _durable_record(intent_path, {**intent, "dispatchedAtUtc": utc(now())})
        # Persistence may take time: check immediately before dispatch again.
        _window(auth, now())
        try:
            response = runner.run(command)
            _durable_record(output / f"delete-{index}.result.json", response)
        except Exception:
            # Durable intent survives. A later call can only observe absence;
            # it never retries this mutation, even when dispatch is uncertain.
            raise CampaignError("late cleanup dispatch or persistence is indeterminate") from None
        if response.get("exitCode") != 0:
            raise CampaignError("late cleanup delete did not succeed; reconcile without repeating")
    disarm_results = [capture.run(cmd) for cmd in disarm[2:]]
    disarm_hash = op.validate_disarm_readback(disarm_results, config, runtime)
    residue_results = op.execute_residue_commands(
        capture, op.command_plan("residue", config, runtime)
    )
    residue = op.observe_residue(residue_results, config, runtime)
    if any(residue.counters.values()):
        raise CampaignError("late cleanup residue remains; finalization blocked")
    load_authorization(authorization_path, plan, runtime, now())
    # Preserve actual job times in evidence; reconciliation times belong to the
    # new ledger transitions. Never backdate the observer to scheduled execution.
    closure_at = now()
    if final_path.exists():
        saved = document(final_path)
        transitions = saved.get("transitions")
        if not isinstance(transitions, list) or len(transitions) != len(ledger.transitions) + 5:
            raise CampaignError("late cleanup final checkpoint history differs")
        closure_at = parse_utc(str(transitions[len(ledger.transitions)]["atUtc"]))
        _window(auth, closure_at)
        if closure_at > now():
            raise CampaignError("late cleanup checkpoint timestamp is in the future")
    ledger.transition(Phase.CLEANING, closure_at)
    ledger.transition(Phase.CLEANED, closure_at)
    ledger.record_cleanup_disarm_evidence(disarm_hash)
    ledger.transition(Phase.CLEANUP_DISARMED, closure_at)
    ledger.record_residue(residue.counters, evidence_sha256=residue.evidence_sha256)
    ledger.transition(Phase.RESIDUE_VERIFIED, closure_at)
    ledger.transition(Phase.FINALIZED, closure_at)
    job_properties = cast(dict[str, object], cast(dict[str, object], _result(job))["properties"])
    # Transition timestamps say when we adopted the observation; cleanup fields
    # retain the actual provider job times, including in the terminal receipt.
    ledger.cleanup_started_utc = utc(parse_utc(str(job_properties["startTime"])))
    ledger.cleanup_completed_utc = utc(parse_utc(str(job_properties["endTime"])))
    ledger.validate_resume(config)
    receipt = terminal_receipt(ledger)
    if final_path.exists():
        if document(final_path) != asdict(ledger):
            raise CampaignError("late cleanup final checkpoint differs from verified evidence")
    else:
        _durable_record(final_path, asdict(ledger))
    if file_hash(current_path) != plan["ledgerFileSha256"] and document(current_path) != asdict(
        ledger
    ):
        raise CampaignError("late cleanup live ledger diverged from its preserved snapshot")
    evidence = {
        **binding,
        "operatorSourceHead": auth["operatorSourceHead"],
        "status": "failed-campaign-closed-zero-residue",
        "campaignSucceeded": False,
        "scheduledJobResourceIdSha256": hashlib.sha256(
            str(plan["jobResourceId"]).encode()
        ).hexdigest(),
        "scheduledCleanupStartedAtUtc": cast(
            dict[str, object], cast(dict[str, object], _result(job))["properties"]
        )["startTime"],
        "scheduledCleanupCompletedAtUtc": cast(
            dict[str, object], cast(dict[str, object], _result(job))["properties"]
        )["endTime"],
        "ledgerAdoptedAtUtc": utc(closure_at),
        "originalLedgerSha256": plan["ledgerFileSha256"],
        "finalLedgerSha256": file_hash(final_path),
        "readbackDirectory": str(read_directory),
        "readbacksSha256": {p.name: file_hash(p) for p in read_directory.iterdir() if p.is_file()},
        "residueEvidenceSha256": residue.evidence_sha256,
        "cleanupDisarmEvidenceSha256": disarm_hash,
        "observedAtUtc": utc(now()),
    }
    evidence["evidenceSha256"] = digest("late-cleanup-completion", evidence)
    _durable_record(read_directory / "completion.json", evidence)
    save_ledger(current_path, ledger)
    receipt_path = current_path.with_name("terminal-receipt.json")
    if receipt_path.exists():
        if document(receipt_path) != receipt:
            raise CampaignError("late cleanup terminal receipt already differs")
    else:
        _durable_record(receipt_path, receipt)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "authorize", "execute"))
    for name in (
        "runtime",
        "config",
        "ledger",
        "job-result",
        "output-result",
        "original-authorization",
        "output-directory",
        "plan",
        "approval",
        "output",
        "authorization",
        "validation-receipt",
    ):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--issued-at")
    parser.add_argument("--expires-at")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "plan":
            value = build_plan(
                runtime_path=args.runtime,
                config_path=args.config,
                ledger_path=args.ledger,
                job_result_path=args.job_result,
                output_result_path=args.output_result,
                original_authorization_path=args.original_authorization,
                output_directory=args.output_directory,
            )
        elif args.operation == "authorize":
            value = build_authorization(
                args.plan,
                args.approval,
                validation_receipt_path=args.validation_receipt,
                issued_at=args.issued_at,
                expires_at=args.expires_at,
            )
        else:
            if not args.execute:
                raise CampaignError("late cleanup execution requires explicit --execute")
            value = execute(
                args.plan, args.authorization, runner=SubprocessRunner(timeout_seconds=60)
            )
        if args.operation != "execute":
            if args.output is None:
                raise CampaignError("private output path is required")
            _durable_record(args.output, value)
        print(
            json.dumps(
                {
                    "status": "prepared" if args.operation != "execute" else value["status"],
                    "operation": args.operation,
                }
            )
        )
        return 0
    except (CampaignError, OSError, ValueError, KeyError, TypeError) as exc:
        # Provider stdout/stderr and private identifiers stay in private captures.
        print(json.dumps({"status": "blocked", "errorClass": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
