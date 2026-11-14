from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import test_milestone_7_8_local_image as original
import test_milestone_7_8_retained_image_admission as retained

from infra.milestone_7_8 import image_continuation, local_image
from infra.milestone_7_8.campaign import CampaignError, Phase


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> original.Case:
    # Reuse the existing source/archive and registry fixture, including its real
    # executor runner. Only the separately tested continuation boundary is faked.
    factory = cast(Callable[..., original.Case], original.case._get_wrapped_function())
    value = factory(tmp_path, monkeypatch)
    value.ledger.transitions.append({
        "from": Phase.INFRASTRUCTURE_DEPLOYED.value,
        "to": Phase.IMAGE_DECIDED.value,
        "atUtc": "2030-01-01T00:00:00Z",
    })
    value.ledger.phase = Phase.IMAGE_DECIDED.value
    value.ledger.image_digest = "sha256:" + "a" * 64
    value.ledger.required_scan_count = 1
    value.ledger.image_scan_count = 1
    value.ledger.image_scan_evidence_sha256 = "b" * 64
    value.ledger.validate_resume(value.config)
    old_runtime = {**value.runtime, "sourceHead": "8" * 40}
    value.runtime_path.write_text(json.dumps(old_runtime), encoding="utf-8")
    folder = value.runtime_path.parent
    (folder / "local-image").mkdir()
    (folder / "local-image/completed.json").write_text('{"original":"preserved"}')
    (folder / "local-image-attempt.json").write_text('{"original":"preserved"}')
    (folder / "ledger.json").write_text('{"original":"preserved"}')
    return value


@pytest.fixture
def retained_path(case: original.Case, monkeypatch: pytest.MonkeyPatch) -> Path:
    factory = cast(Callable[..., Path], retained.retained_path._get_wrapped_function())
    return factory(case, monkeypatch)


@pytest.fixture
def continuation(case: original.Case, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = case.runtime_path.with_name("continuation.json")
    document = {"planSha256": "7" * 64}
    path.write_text(json.dumps(document), encoding="utf-8")

    def load_plan(candidate: Path) -> dict[str, object]:
        if candidate.resolve() != path.resolve() or json.loads(candidate.read_text()) != document:
            raise CampaignError("continuation fixture binding differs")
        return dict(document)

    def validate_context(
        runtime: dict[str, str], config: object, plan: dict[str, object], candidate: Path
    ) -> None:
        assert runtime == case.runtime and config == case.config
        if (
            plan.get("continuationFile") != str(path.resolve())
            or plan.get("continuationPlanSha256") != load_plan(candidate)["planSha256"]
            or cast(dict[str, object], plan["retainedImage"])["imageId"] != retained.IMAGE_ID
        ):
            raise CampaignError("continuation fixture image binding differs")

    def validate_request(
        runtime: dict[str, str], config: object, ledger: object,
        plan: dict[str, object], approval: object, now: datetime,
    ) -> None:
        assert ledger is case.ledger and approval == case.approval and now == original.NOW
        assert case.ledger.phase == Phase.IMAGE_DECIDED.value
        assert case.ledger.image_digest == "sha256:" + "a" * 64
        validate_context(runtime, config, plan, path)

    monkeypatch.setattr(image_continuation, "load_plan", load_plan)
    monkeypatch.setattr(image_continuation, "validate_image_request", validate_request)
    monkeypatch.setattr(image_continuation, "validate_image_completion_context", validate_context)
    return path


def prepare(case: original.Case, retained_path: Path, continuation: Path) -> None:
    case.plan = local_image.build_plan(
        case.runtime, case.config, case.plan["before"], egress_ipv4="8.8.4.4",
        retained_image=retained_path, continuation=continuation,
    )
    case.approval = local_image.build_approval(
        case.plan, issued_at="2030-01-01T00:00:00Z", expires_at="2030-01-01T01:00:00Z",
        restore_until="2030-01-01T05:00:00Z",
    )


def execute(case: original.Case, provider: retained.RetainedProvider) -> dict[str, object]:
    return local_image.execute_local_image(
        case.runtime_path, case.runtime, case.config, case.ledger, case.plan, case.approval,
        output=case.runtime_path.parent / "image-continuation/local-image",
        runner=provider, clock=lambda: original.NOW,
    )


def originals(case: original.Case) -> dict[str, bytes]:
    folder = case.runtime_path.parent
    return {
        name: (folder / name).read_bytes()
        for name in ("runtime.json", "ledger.json", "local-image-attempt.json",
                     "local-image/completed.json")
    }


def test_replacement_cli_pushes_exact_retained_image_and_preserves_originals(
    case: original.Case, retained_path: Path, continuation: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = originals(case)
    folder = case.runtime_path.parent
    calls: list[str] = []

    def load_context(
        path: Path, runtime: Path, config: Path, ledger: Path, *, operation: str
    ) -> tuple[dict[str, str], object, object]:
        assert path == continuation and runtime == case.runtime_path
        assert config == folder / "config.json" and ledger == folder / "ledger.json"
        calls.append(operation)
        return case.runtime, case.config, case.ledger

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> FrozenDateTime:
            return cls(2030, 1, 1, tzinfo=UTC)

    provider = retained.RetainedProvider(case)
    monkeypatch.setattr(image_continuation, "load_context", load_context)
    monkeypatch.setattr(local_image, "datetime", FrozenDateTime)
    monkeypatch.setattr(local_image, "SubprocessRunner", lambda **_kwargs: provider)
    monkeypatch.setattr(local_image, "load_execution_authorization", lambda *_args, **_kwargs: {})
    (folder / "before.json").write_text(json.dumps(case.plan["before"]), encoding="utf-8")
    common = [
        "--runtime", str(case.runtime_path), "--config", str(folder / "config.json"),
        "--ledger", str(folder / "ledger.json"), "--plan", str(folder / "replacement-plan.json"),
        "--image-continuation", str(continuation),
    ]
    monkeypatch.setattr(sys, "argv", [
        "local_image", "plan", *common, "--registry-before", str(folder / "before.json"),
        "--egress-ipv4", "8.8.4.4", "--retained-image", str(retained_path),
    ])
    assert local_image.main() == 0
    case.plan = json.loads((folder / "replacement-plan.json").read_text())
    case.approval = local_image.build_approval(
        case.plan, issued_at="2030-01-01T00:00:00Z", expires_at="2030-01-01T01:00:00Z",
        restore_until="2030-01-01T05:00:00Z",
    )
    approval = ["--approval", str(folder / "replacement-approval.json")]
    monkeypatch.setattr(sys, "argv", [
        "local_image", "approve", *common, *approval,
        "--expires-at", "2030-01-01T01:00:00Z", "--restore-until", "2030-01-01T05:00:00Z",
    ])
    assert local_image.main() == 0
    case.approval = json.loads((folder / "replacement-approval.json").read_text())
    monkeypatch.setattr(sys, "argv", [
        "local_image", "execute", *common, *approval, "--execute",
        "--cleanup-authorization", str(folder / "cleanup.json"),
    ])
    assert local_image.main() == 0
    assert calls == ["image", "image", "image"]
    output = folder / "image-continuation/local-image"
    receipt = json.loads((output / "completed.json").read_text())
    assert receipt["imageBuildCount"] == 0 and receipt["retainedImageId"] == retained.IMAGE_ID
    assert receipt["imageDigest"] == original.DIGEST
    assert not any(command[:2] == ("docker", "build") for command in provider.commands)
    assert provider.patch_count == 2 and provider.registry == case.plan["before"]
    assert json.loads((output / "scout-runtime.json").read_text()) == case.runtime
    assert local_image.validate_completion(
        case.runtime_path, case.runtime, case.config, digest=original.DIGEST,
        scan_path=output / "image-scan.json", continuation=continuation,
    ) == 0
    assert originals(case) == before
    assert (output.parent / "local-image-attempt.json").is_file()
    prior_commands = list(provider.commands)
    with pytest.raises(CampaignError, match="attempt already exists"):
        execute(case, provider)
    assert provider.commands == prior_commands


def test_replacement_plan_requires_retained_provenance(
    case: original.Case, continuation: Path,
) -> None:
    with pytest.raises(CampaignError, match="requires exact retained-image"):
        local_image.build_plan(
            case.runtime, case.config, case.plan["before"], egress_ipv4="8.8.4.4",
            continuation=continuation,
        )


@pytest.mark.parametrize("fault", ["image-id", "changed-inputs", "detached-push", "scan-failure"])
def test_replacement_misbound_or_failed_image_blocks_and_preserves_originals(
    case: original.Case, retained_path: Path, continuation: Path, fault: str,
) -> None:
    before = originals(case)
    prepare(case, retained_path, continuation)
    provider = retained.RetainedProvider(case, fault=fault)
    with pytest.raises(CampaignError):
        execute(case, provider)
    assert provider.registry == case.plan["before"]
    assert not (case.runtime_path.parent / "image-continuation/local-image/completed.json").exists()
    assert originals(case) == before


@pytest.mark.parametrize("fault", ["missing", "changed", "wrong-output"])
def test_replacement_cannot_bypass_bound_continuation_or_overwrite_original(
    case: original.Case, retained_path: Path, continuation: Path, fault: str,
) -> None:
    before = originals(case)
    prepare(case, retained_path, continuation)
    provider = retained.RetainedProvider(case)
    if fault == "missing":
        case.plan = local_image.build_plan(
            case.runtime, case.config, case.plan["before"], egress_ipv4="8.8.4.4",
            retained_image=retained_path,
        )
        case.approval = local_image.build_approval(
            case.plan, issued_at="2030-01-01T00:00:00Z", expires_at="2030-01-01T01:00:00Z",
            restore_until="2030-01-01T05:00:00Z",
        )
    elif fault == "changed":
        continuation.write_text('{"planSha256":"different"}', encoding="utf-8")
    with pytest.raises(CampaignError):
        if fault == "wrong-output":
            local_image.execute_local_image(
                case.runtime_path, case.runtime, case.config, case.ledger, case.plan, case.approval,
                output=case.runtime_path.parent / "local-image", runner=provider,
                clock=lambda: original.NOW,
            )
        else:
            execute(case, provider)
    assert provider.commands == [] and originals(case) == before


def test_replacement_restoration_failure_never_produces_completion(
    case: original.Case, retained_path: Path, continuation: Path,
) -> None:
    prepare(case, retained_path, continuation)
    provider = retained.RetainedProvider(case, fault="restore-failure")
    with pytest.raises(local_image.RegistryRestorationUnproved):
        execute(case, provider)
    output = case.runtime_path.parent / "image-continuation/local-image"
    assert (output / "scan-pending.json").is_file()
    assert not (output / "image-scan.json").exists()
    assert not (output / "completed.json").exists()


@pytest.mark.parametrize("fault", ["wrong-continuation", "scanner-runtime"])
def test_replacement_completion_replays_context_beyond_file_inventory(
    case: original.Case, retained_path: Path, continuation: Path, fault: str,
) -> None:
    prepare(case, retained_path, continuation)
    execute(case, retained.RetainedProvider(case))
    output = case.runtime_path.parent / "image-continuation/local-image"
    selected = continuation
    if fault == "wrong-continuation":
        selected = continuation.with_name("unbound-continuation.json")
        selected.write_bytes(continuation.read_bytes())
    else:
        runtime = copy.deepcopy(case.runtime)
        runtime["sourceHead"] = "8" * 40
        path = output / "scout-runtime.json"
        path.write_text(json.dumps(runtime), encoding="utf-8")
        receipt_path = output / "completed.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["filesSha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError):
        local_image.validate_completion(
            case.runtime_path, case.runtime, case.config, digest=original.DIGEST,
            scan_path=output / "image-scan.json", continuation=selected,
        )
