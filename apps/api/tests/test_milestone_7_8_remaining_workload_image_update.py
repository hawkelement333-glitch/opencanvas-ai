from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import _runtime, _write_execution_authorization
from test_milestone_7_8_workload_image_update import NEW, NOW, OLD, Clock, Provider, fixture

from infra.milestone_7_8 import workload_image_update as update
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError


@dataclass
class Remaining:
    runtime: dict[str, str]
    config: CampaignConfig
    prior: Path
    readback: Path
    output: Path
    transition: dict[str, object]
    provider: Provider
    original_files: dict[Path, bytes]

    def execute(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "previous_digest": OLD, "digest": NEW, "prior_output": self.prior,
            "api_readback_directory": self.readback, "output": self.output,
            "source_transition": self.transition, "runner": self.provider,
            "clock": lambda: NOW + timedelta(seconds=2), "check_authority": lambda: None,
        }
        values.update(overrides)
        return update.execute_remaining_jobs(self.runtime, self.config, **values)  # type: ignore[arg-type]


def make_remaining(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Remaining:
    partial, config, _scope = fixture(tmp_path)
    runtime = {**_runtime(), **partial}
    scope = update._scope(runtime, config, OLD, NEW)
    prior = tmp_path / "old/workload"
    prior.parent.mkdir()
    _write_execution_authorization(
        prior.parent / "authorization.json", config, runtime,
        expires_at="2030-01-01T05:00:00Z", operations=["image-decision", "cleanup"],
    )

    class EmptyPatchProvider(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            result = super().run(command)
            if command[3] == "patch":
                result["stdout"] = ""
            return result

    provider = EmptyPatchProvider(runtime, config, scope)
    for resource in provider.states.values():
        if resource["type"] == "Microsoft.App/jobs":
            update._object(update._object(update._containers(resource)[0])["resources"])[
                "ephemeralStorage"
            ] = ""
    def old_decoder(result: dict[str, object], target: dict[str, str]) -> dict[str, object]:
        value = update._decoded(result)
        update._patch_response(value, target)
        return value
    with monkeypatch.context() as historical:
        historical.setattr(update, "_acknowledgement", old_decoder)
        with pytest.raises(CampaignError, match="response is malformed"):
            update.execute_updates(runtime, config, previous_digest=OLD, digest=NEW, output=prior,
                                   runner=provider, clock=Clock(), check_authority=lambda: None)
    assert provider.patches == 1
    assert not (prior / "012-intent.json").exists()
    readback = tmp_path / "old/api-patch-readback"
    readback.mkdir()
    target = cast(list[dict[str, str]], scope["targets"])[0]
    response = provider.run(update._command(runtime, target, None))
    response["completedAtUtc"] = (NOW + timedelta(seconds=1)).isoformat()
    (readback / "intent.json").write_text(json.dumps({
        "command": update._command(runtime, target, None), "atUtc": NOW.isoformat(),
        "purpose": "exact API preservation readback",
    }))
    (readback / "response.json").write_text(json.dumps(response))
    (readback / "result.json").write_text(json.dumps({
        "method": "GET", "mutationCount": 0, "provisioningState": "Succeeded",
        "responseSha256": hashlib.sha256((readback / "response.json").read_bytes()).hexdigest(),
        "status": "observed-correct-image-and-preservation",
    }))
    transition: dict[str, object] = {
        "sourceHead": "e" * 40, "planSha256": "f" * 64, "authorizationSha256": "a" * 64,
        "priorAuthorizationFile": str((prior.parent / "authorization.json").resolve()),
    }
    original_files = {path: path.read_bytes() for path in prior.parent.rglob("*") if path.is_file()}
    provider.commands.clear()
    provider.patches = 0
    return Remaining(runtime, config, prior, readback, tmp_path / "remaining", transition,
                     provider, original_files)


@pytest.fixture
def remaining(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Remaining:
    return make_remaining(tmp_path, monkeypatch)


def test_empty_acknowledgement_resumes_only_nine_jobs(remaining: Remaining) -> None:
    receipt = remaining.execute()
    assert receipt["patchCount"] == 9
    assert receipt["priorApiPatchCount"] == 1
    assert receipt["resourceCount"] == 10
    assert receipt["jobStartCount"] == receipt["baseResourceMutationCount"] == 0
    assert [cmd[3] for cmd in remaining.provider.commands] == ["get"] * 10 + ["patch", "get"] * 9
    assert all("/containerApps/" not in cmd[5] for cmd in remaining.provider.commands
               if cmd[3] == "patch")
    assert all(path.read_bytes() == content for path, content in remaining.original_files.items())
    assert update.validate_remaining_completion(
        remaining.runtime, remaining.config, previous_digest=OLD, digest=NEW,
        prior_output=remaining.prior, api_readback_directory=remaining.readback,
        output=remaining.output, source_transition=remaining.transition,
    ) == receipt
    with pytest.raises(FileExistsError):
        remaining.execute()
    assert remaining.provider.patches == 9


@pytest.mark.parametrize("fault", ["missing", "extra", "indeterminate", "body", "authority"])
def test_invalid_original_dispatch_history_blocks_before_any_request(
    remaining: Remaining, fault: str,
) -> None:
    if fault == "missing":
        (remaining.prior / "011-dispatch.json").unlink()
    elif fault == "extra":
        (remaining.prior / "012-intent.json").write_text("{}")
    elif fault == "indeterminate":
        (remaining.prior / "011-indeterminate.json").write_text("{}")
    elif fault == "body":
        (remaining.prior / "target-01-body.json").write_text("{}")
    else:
        (remaining.prior.parent / "authorization.json").write_text("{}")
    with pytest.raises(CampaignError):
        remaining.execute()
    assert remaining.provider.commands == []


@pytest.mark.parametrize("fault", ["api-old", "job-new", "tag", "allocation"])
def test_fresh_drift_blocks_all_remaining_mutations(remaining: Remaining, fault: str) -> None:
    states = list(remaining.provider.states.values())
    if fault in {"api-old", "job-new"}:
        update._object(update._containers(states[0 if fault == "api-old" else 1])[0])["image"] = (
            remaining.provider.image(OLD if fault == "api-old" else NEW))
    elif fault == "tag":
        update._object(states[1]["tags"])["extra"] = "drift"
    else:
        update._object(update._object(update._containers(states[1])[0])["resources"])["cpu"] = 8
    with pytest.raises(CampaignError):
        remaining.execute()
    assert remaining.provider.patches == 0


@pytest.mark.parametrize("lost", [False, True])
def test_failed_or_lost_job_patch_is_not_repeated(remaining: Remaining, lost: bool) -> None:
    remaining.provider.failure = 2
    remaining.provider.lost = lost
    with pytest.raises(CampaignError):
        remaining.execute()
    assert remaining.provider.patches == 2
    assert not (remaining.output / "completion.json").exists()
    with pytest.raises(FileExistsError):
        remaining.execute()
    assert remaining.provider.patches == 2


def test_expired_current_authority_dispatches_nothing(remaining: Remaining) -> None:
    def expired() -> None:
        raise CampaignError("expired")
    with pytest.raises(CampaignError, match="expired"):
        remaining.execute(check_authority=expired)
    assert remaining.provider.commands == []


def test_wrong_source_transition_blocks(remaining: Remaining) -> None:
    remaining.transition["sourceHead"] = remaining.runtime["sourceHead"]
    with pytest.raises(CampaignError, match="source transition"):
        remaining.execute()
    assert remaining.provider.commands == []


def test_changed_readback_or_rehashed_completion_does_not_admit(remaining: Remaining) -> None:
    receipt = remaining.execute()
    path = remaining.output / "012-response.json"
    value = json.loads(path.read_text())
    observed = json.loads(value["stdout"])
    observed["properties"]["template"]["containers"][0]["image"] = remaining.provider.image(OLD)
    value["stdout"] = json.dumps(observed)
    path.write_text(json.dumps(value))
    changed = copy.deepcopy(receipt)
    update._object(changed["filesSha256"])[path.name] = (
        hashlib.sha256(path.read_bytes()).hexdigest()
    )
    changed["completionSha256"] = update._hash({
        key: val for key, val in changed.items() if key != "completionSha256"
    })
    (remaining.output / "completion.json").write_text(json.dumps(changed))
    with pytest.raises(CampaignError):
        update.validate_remaining_completion(
            remaining.runtime, remaining.config, previous_digest=OLD, digest=NEW,
            prior_output=remaining.prior, api_readback_directory=remaining.readback,
            output=remaining.output, source_transition=remaining.transition,
        )


@pytest.mark.parametrize("kind", ["Microsoft.App/jobs", "Microsoft.App/containerApps"])
@pytest.mark.parametrize("before_value,after_value,allowed", [
    ("", None, True), (None, "", True), ("", "1Gi", False), ("1Gi", None, False),
    (None, "1Gi", False), ("1Gi", "2Gi", False), ("1Gi", "1Gi", True),
])
def test_only_job_empty_ephemeral_storage_shape_is_normalized(
    kind: str, before_value: str | None, after_value: str | None, allowed: bool,
) -> None:
    before: dict[str, object] = {"type": kind, "properties": {"template": {"containers": [
        {"image": OLD, "resources": {"cpu": 2, "memory": "4Gi"}},
    ]}}}
    after = copy.deepcopy(before)
    for resource, value in ((before, before_value), (after, after_value)):
        if value is not None:
            update._object(update._object(update._containers(resource)[0])["resources"])[
                "ephemeralStorage"
            ] = value
    if allowed and (kind.endswith("jobs") or before_value == after_value):
        update._preserved(before, after)
    else:
        with pytest.raises(CampaignError, match="another property"):
            update._preserved(before, after)


def test_verified_worker_prefix_continues_only_eight_jobs(
    remaining: Remaining, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_authority = remaining.output.parent / "authorization.json"
    _write_execution_authorization(
        prior_authority, remaining.config,
        {**remaining.runtime, "sourceHead": str(remaining.transition["sourceHead"])},
        expires_at="2030-01-01T05:00:00Z", operations=["image-decision", "cleanup"],
    )
    remaining.transition["authorizationSha256"] = hashlib.sha256(
        prior_authority.read_bytes()).hexdigest()
    remaining.provider.pending = 1
    original_preserved = update._preserved

    class OmittedDefault:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            result = remaining.provider.run(command)
            if command[3] == "get" and "/jobs/" in command[5]:
                resource = update._decoded(result)
                properties = update._object(resource["properties"])
                if properties["provisioningState"] == "Updating":
                    properties["provisioningState"] = "InProgress"
                if update._object(update._containers(resource)[0])["image"] == (
                    remaining.provider.image(NEW)
                ):
                    update._object(update._object(update._containers(resource)[0])["resources"]).pop(
                        "ephemeralStorage", None,
                    )
                    saved = remaining.provider.states[str(resource["id"])]
                    update._object(update._object(update._containers(saved)[0])["resources"]).pop(
                        "ephemeralStorage", None,
                    )
                    result["stdout"] = json.dumps(resource)
            return result

    def old_preserved(before: dict[str, object], after: dict[str, object]) -> None:
        left = update._object(update._object(update._containers(before)[0])["resources"])
        right = update._object(update._object(update._containers(after)[0])["resources"])
        if left != right:
            raise CampaignError("historical read-only default presence mismatch")
        original_preserved(before, after)

    runner = OmittedDefault()
    with monkeypatch.context() as historical:
        historical.setattr(update, "_preserved", old_preserved)
        with pytest.raises(CampaignError, match="historical read-only"):
            remaining.execute(runner=runner)
    assert remaining.provider.patches == 1
    assert (remaining.output / "013-completed.json").exists()
    assert not (remaining.output / "014-intent.json").exists()
    proof = update.inspect_completed_job_prefix(
        remaining.runtime, remaining.config, previous_digest=OLD, digest=NEW,
        prior_output=remaining.prior, api_readback_directory=remaining.readback,
        output=remaining.output, source_transition=remaining.transition,
    )
    old_files = {p: p.read_bytes() for p in remaining.output.iterdir()}
    remaining.provider.commands.clear()
    remaining.provider.patches = 0
    transition = {**remaining.transition, "sourceHead": "f" * 40, "planSha256": "c" * 64}
    final = remaining.output.parent / "final-eight"
    receipt = remaining.execute(
        runner=runner, output=final, source_transition=transition,
        prior_remaining=(remaining.output, remaining.transition),
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert receipt["patchCount"] == 8
    assert receipt["priorJobPatchCount"] == receipt["priorApiPatchCount"] == 1
    assert receipt["completedJobPrefixSha256"] == proof["prefixSha256"]
    assert [c[3] for c in remaining.provider.commands] == ["get"] * 10 + ["patch", "get"] * 8
    worker_suffix = "/" + remaining.runtime["workerJobName"]
    assert all("/containerApps/" not in c[5] and not c[5].split("?")[0].endswith(worker_suffix)
               for c in remaining.provider.commands if c[3] == "patch")
    assert all(p.read_bytes() == data for p, data in old_files.items())
    assert update.validate_remaining_completion(
        remaining.runtime, remaining.config, previous_digest=OLD, digest=NEW,
        prior_output=remaining.prior, api_readback_directory=remaining.readback, output=final,
        source_transition=transition, prior_remaining=(remaining.output, remaining.transition),
    ) == receipt
