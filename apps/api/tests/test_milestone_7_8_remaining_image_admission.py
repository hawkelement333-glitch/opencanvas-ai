from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import cast

import pytest
import test_milestone_7_8_image_continuation as original

from infra.milestone_7_8 import image_continuation as continuation
from infra.milestone_7_8 import image_continuation_recovery, operator
from infra.milestone_7_8 import workload_image_update as update
from infra.milestone_7_8.campaign import CampaignError

NEW_HEAD = "f" * 40


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_remaining(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, empty_ephemeral_storage: bool = False,
) -> tuple[original.Case, Path, Path, dict[Path, bytes]]:
    factory = cast(Callable[..., original.Case], original.case._get_wrapped_function())
    case = factory(tmp_path, monkeypatch)
    if empty_ephemeral_storage:
        worker = list(case.provider.states.values())[1]
        update._object(update._object(update._containers(worker)[0])["resources"])[
            "ephemeralStorage"
        ] = ""
    # The prior retained-image recovery is tested separately. This fixture keeps
    # the real operator, request journals, authorizations and remaining-job replay.
    monkeypatch.setattr(image_continuation_recovery, "validate_prior", lambda _: None)
    old_folder = case.plan.parent
    folder = case.folder / "image-continuation-r1"
    old_folder.rename(folder)
    case.plan = folder / "plan.json"
    old_plan = json.loads(case.plan.read_text())
    old_plan["priorImageAttempt"] = {"fixture": "independently-validated-image-recovery"}
    old_plan["planSha256"] = continuation._hash({
        key: value for key, value in old_plan.items() if key != "planSha256"
    })
    original.write(case.plan, old_plan)
    original_run = case.provider.run

    def empty_ack(command: tuple[str, ...]) -> dict[str, object]:
        result = original_run(command)
        if command[3] == "patch":
            result["stdout"] = ""
        return result

    def old_decoder(result: dict[str, object], target: dict[str, str]) -> dict[str, object]:
        value = update._decoded(result)
        update._patch_response(value, target)
        return value

    monkeypatch.setattr(case.provider, "run", empty_ack)
    with monkeypatch.context() as historical:
        historical.setattr(update, "_acknowledgement", old_decoder)
        assert case.invoke(monkeypatch) == 2
    assert case.provider.patches == 1
    assert not (folder / "workload/012-intent.json").exists()
    scope = update._scope(
        case.runtime, case.config, continuation.ORIGINAL_IMAGE, continuation.IMAGE,
    )
    target = cast(list[dict[str, str]], scope["targets"])[0]
    command = update._command(case.runtime, target, None)
    response = case.provider.run(command)
    response["completedAtUtc"] = original.Clock.now(UTC).isoformat()
    readback = folder / "api-patch-readback"
    original.write(readback / "intent.json", {
        "command": command, "atUtc": original.Clock.now(UTC).isoformat(),
        "purpose": "exact previously dispatched API preservation readback",
    })
    original.write(readback / "response.json", response)
    original.write(readback / "result.json", {
        "method": "GET", "mutationCount": 0, "provisioningState": "Succeeded",
        "responseSha256": sha(readback / "response.json"),
        "status": "observed-correct-image-and-preservation",
    })
    update.inspect_remaining_prefix(
        case.runtime, case.config, previous_digest=continuation.ORIGINAL_IMAGE,
        digest=continuation.IMAGE, prior_output=folder / "workload",
        api_readback_directory=readback,
    )

    def validated_predecessor(record: dict[str, object]) -> None:
        # Replace only the private, hard-coded live image provenance identity.
        # Every retained dispatch, authorization and API GET is replayed for real.
        if (record["planFile"] != str(case.plan.resolve())
                or record["planFileSha256"] != sha(case.plan)
                or record["filesSha256"] != {
                    str(path): sha(path) for path in folder.rglob("*") if path.is_file()
                }):
            raise CampaignError("completed predecessor changed")
        update.inspect_remaining_prefix(
            case.runtime, case.config, previous_digest=continuation.ORIGINAL_IMAGE,
            digest=continuation.IMAGE, prior_output=folder / "workload",
            api_readback_directory=readback,
        )

    monkeypatch.setattr(continuation, "_validate_completed_image", validated_predecessor)
    monkeypatch.setattr(continuation, "_source", lambda: NEW_HEAD)
    new_plan = continuation.build_plan(
        case.folder / "runtime.json", case.folder / "cost.json", case.folder / "ledger.json",
        cost_path=case.folder / "replacement-cost.json",
        retained_image=case.folder / "retained-image.json", completed_image_plan=case.plan,
    )
    plan_path = original.write(case.folder / "image-continuation-r2/plan.json", new_plan)
    old_auth = json.loads(case.authorization.read_text())
    unsigned = {key: value for key, value in old_auth.items() if key != "authorizationSha256"}
    unsigned["sourceHead"] = NEW_HEAD
    authorization = original.write(case.folder / "remaining-authorization.json", {
        **unsigned, "authorizationSha256": hashlib.sha256(
            b"m7.8/execution-authorization/v5\0"
            + json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    })
    preserved = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    preserved.update(case.originals)
    case.provider.commands.clear()
    case.provider.patches = 0
    return case, plan_path, authorization, preserved


def invoke(
    case: original.Case, plan: Path, authorization: Path,
    monkeypatch: pytest.MonkeyPatch, *, operation: str = "image-decision", execute: bool = True,
) -> int:
    arguments = ["operator", operation, "--runtime", str(case.folder / "runtime.json"),
                 "--config", str(case.folder / "cost.json"),
                 "--ledger", str(case.folder / "ledger.json"),
                 "--image-continuation", str(plan), "--authorization", str(authorization)]
    if execute:
        arguments += ["--execute"]
    if operation == "image-decision":
        arguments += ["--image-digest", continuation.IMAGE, "--image-scan-evidence",
                      str(case.plan.parent / "local-image/image-scan.json")]
    monkeypatch.setattr(sys, "argv", arguments)
    return operator.main()


def test_normal_operator_admits_only_remaining_jobs_and_preserves_old_image_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, plan, authorization, preserved = setup_remaining(tmp_path, monkeypatch)
    assert invoke(case, plan, authorization, monkeypatch) == 0
    assert case.provider.patches == 9
    assert [command[3] for command in case.provider.commands] == ["get"] * 10 + ["patch", "get"] * 9
    assert all("/containerApps/" not in command[5] for command in case.provider.commands
               if command[3] == "patch")
    runtime, config, ledger = continuation.load_context(
        plan, case.folder / "runtime.json", case.folder / "cost.json",
        case.folder / "ledger.json", operation="bootstrap",
    )
    assert runtime["sourceHead"] == NEW_HEAD != case.runtime["sourceHead"]
    assert ledger.image_digest == continuation.IMAGE
    assert ledger.image_scan_count == ledger.required_scan_count == 2
    assert ledger.image_generation_count == 0 and ledger.resource_generation_count == 1
    receipt = continuation.validate_admission(plan, runtime, config, ledger)
    workload = json.loads((plan.parent / "workload/completion.json").read_text())
    assert workload["completionSha256"] == receipt["workloadCompletionSha256"]
    assert workload["patchCount"] == 9 and workload["priorApiPatchCount"] == 1
    assert all(path.read_bytes() == content for path, content in preserved.items())
    count = len(case.provider.commands)
    assert invoke(case, plan, authorization, monkeypatch, operation="bootstrap", execute=False) == 0
    assert len(case.provider.commands) == count
    assert invoke(case, plan, authorization, monkeypatch) == 2
    assert case.provider.patches == 9


@pytest.mark.parametrize("fault", ["prior-dispatch", "old-authorization", "new-authorization"])
def test_remaining_operator_rejects_changed_history_or_wrong_current_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    case, plan, authorization, _ = setup_remaining(tmp_path, monkeypatch)
    before = (case.folder / "ledger.json").read_bytes()
    if fault == "prior-dispatch":
        (case.plan.parent / "workload/011-dispatch.json").unlink()
    elif fault == "old-authorization":
        original.write(case.plan.parent / "authorization.json", {})
    else:
        authorization = case.authorization
    assert invoke(case, plan, authorization, monkeypatch) == 2
    assert case.provider.commands == []
    assert (case.folder / "ledger.json").read_bytes() == before
    assert not (plan.parent / "completed.json").exists()


def test_remaining_completion_is_required_before_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, plan, authorization, _ = setup_remaining(tmp_path, monkeypatch)
    assert invoke(case, plan, authorization, monkeypatch) == 0
    (plan.parent / "completed.json").unlink()
    count = len(case.provider.commands)
    assert invoke(case, plan, authorization, monkeypatch, operation="bootstrap", execute=False) == 2
    assert len(case.provider.commands) == count


def setup_last_eight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[original.Case, Path, Path, Path, dict[Path, bytes]]:
    case, prior_plan, prior_authorization, preserved = setup_remaining(
        tmp_path, monkeypatch, empty_ephemeral_storage=True,
    )
    monkeypatch.setattr(time, "sleep", lambda _: None)
    run = case.provider.run
    worker_id = list(case.provider.states)[1]

    def worker_metadata_drift(command: tuple[str, ...]) -> dict[str, object]:
        response = run(command)
        if command[3] == "patch" and worker_id in command[5]:
            worker = case.provider.states[worker_id]
            resources = update._object(update._object(update._containers(worker)[0])["resources"])
            resources.pop("ephemeralStorage")
            case.provider.pending = 1
        elif command[3] == "get" and worker_id in command[5]:
            observed = json.loads(str(response["stdout"]))
            if observed["properties"]["provisioningState"] == "Updating":
                observed["properties"]["provisioningState"] = "InProgress"
                response["stdout"] = json.dumps(observed)
        return response

    monkeypatch.setattr(case.provider, "run", worker_metadata_drift)
    preserved_check = update._preserved

    def former_preservation(before: dict[str, object], after: dict[str, object]) -> None:
        old_resources = update._object(update._object(update._containers(before)[0])["resources"])
        new_resources = update._object(update._object(update._containers(after)[0])["resources"])
        if old_resources.get("ephemeralStorage") == "" and "ephemeralStorage" not in new_resources:
            raise CampaignError("former strict empty ephemeral-storage preservation mismatch")
        preserved_check(before, after)

    before_ledger = (case.folder / "ledger.json").read_bytes()
    with monkeypatch.context() as historical:
        historical.setattr(update, "_preserved", former_preservation)
        assert invoke(case, prior_plan, prior_authorization, monkeypatch) == 2
    assert case.provider.patches == 1
    prior_workload = prior_plan.parent / "workload"
    assert (prior_workload / "013-completed.json").exists()
    assert not (prior_workload / "014-intent.json").exists()
    assert not (prior_workload / "completion.json").exists()
    assert (case.folder / "ledger.json").read_bytes() == before_ledger

    def validated_jobs(record: dict[str, object]) -> None:
        # The live predecessor's pinned identity is replaced by this synthetic
        # attempt; actual original authority and all thirteen requests are replayed.
        if (record["planFile"] != str(prior_plan.resolve())
                or record["planFileSha256"] != sha(prior_plan)
                or record["filesSha256"] != {
                    str(path): sha(path) for path in prior_plan.parent.rglob("*") if path.is_file()
                }):
            raise CampaignError("prior worker update changed")
        old_plan = continuation.load_plan(prior_plan)
        update.inspect_completed_job_prefix(
            case.runtime, case.config, previous_digest=continuation.ORIGINAL_IMAGE,
            digest=continuation.IMAGE, prior_output=case.plan.parent / "workload",
            api_readback_directory=case.plan.parent / "api-patch-readback", output=prior_workload,
            source_transition=continuation._workload_transition(old_plan, prior_plan.parent),
        )

    monkeypatch.setattr(continuation, "_validate_prior_jobs", validated_jobs)
    monkeypatch.setattr(continuation, "_source", lambda: "a" * 40)
    next_plan = continuation.build_plan(
        case.folder / "runtime.json", case.folder / "cost.json", case.folder / "ledger.json",
        cost_path=case.folder / "replacement-cost.json",
        retained_image=case.folder / "retained-image.json", prior_jobs_plan=prior_plan,
    )
    plan = original.write(case.folder / "image-continuation-r3/plan.json", next_plan)
    unsigned = json.loads(prior_authorization.read_text())
    del unsigned["authorizationSha256"]
    unsigned["sourceHead"] = "a" * 40
    authorization = original.write(case.folder / "eight-jobs-authorization.json", {
        **unsigned, "authorizationSha256": hashlib.sha256(
            b"m7.8/execution-authorization/v5\0"
            + json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    })
    preserved.update({path: path.read_bytes() for path in prior_plan.parent.rglob("*")
                      if path.is_file()})
    case.provider.commands.clear()
    case.provider.patches = 0
    return case, plan, authorization, prior_plan, preserved


def test_normal_operator_keeps_prior_api_and_worker_dispatches_and_admits_last_eight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, plan, authorization, prior_plan, preserved = setup_last_eight(tmp_path, monkeypatch)
    assert invoke(case, plan, authorization, monkeypatch) == 0
    assert case.provider.patches == 8
    assert [command[3] for command in case.provider.commands] == ["get"] * 10 + ["patch", "get"] * 8
    first_ids = list(case.provider.states)[:2]
    assert not any(resource_id in command[5] for command in case.provider.commands
                   if command[3] == "patch" for resource_id in first_ids)
    runtime, config, ledger = continuation.load_context(
        plan, case.folder / "runtime.json", case.folder / "cost.json",
        case.folder / "ledger.json", operation="bootstrap",
    )
    assert runtime["sourceHead"] == "a" * 40
    assert json.loads(prior_plan.read_text())["sourceHead"] == NEW_HEAD
    assert case.runtime["sourceHead"] == original.HEAD
    receipt = continuation.validate_admission(plan, runtime, config, ledger)
    workload = json.loads((plan.parent / "workload/completion.json").read_text())
    assert workload["completionSha256"] == receipt["workloadCompletionSha256"]
    assert workload["patchCount"] == 8
    assert ledger.image_scan_count == 2 and ledger.image_generation_count == 0
    assert all(path.read_bytes() == content for path, content in preserved.items())
    count = len(case.provider.commands)
    assert invoke(case, plan, authorization, monkeypatch, operation="bootstrap", execute=False) == 0
    assert invoke(case, plan, authorization, monkeypatch) == 2
    assert len(case.provider.commands) == count


@pytest.mark.parametrize("fault", ["worker-readback", "worker-dispatch", "worker-authorization"])
def test_last_eight_rejects_altered_successful_worker_history_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    case, plan, authorization, prior_plan, _ = setup_last_eight(tmp_path, monkeypatch)
    baseline_ledger = (case.folder / "ledger.json").read_bytes()
    if fault == "worker-readback":
        original.write(prior_plan.parent / "workload/013-response.json", {})
    elif fault == "worker-dispatch":
        (prior_plan.parent / "workload/011-dispatch.json").unlink()
    else:
        original.write(prior_plan.parent / "authorization.json", {})
    assert invoke(case, plan, authorization, monkeypatch) == 2
    assert case.provider.commands == []
    assert (case.folder / "ledger.json").read_bytes() == baseline_ledger
    assert not (plan.parent / "completed.json").exists()
