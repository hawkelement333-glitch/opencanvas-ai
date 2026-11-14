"""One retained-image correction within the already provisioned startup campaign.

This is an append-only admission exception, not another campaign generation.
Original prepared inputs and the failed prerequisite remain immutable. Only an
accepted replacement and its preservation readbacks can unlock normal bootstrap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    load_ledger,
    parse_utc,
)
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.controller import local_source_binding
from infra.milestone_7_8.controller_renewal import _durable_record
from infra.milestone_7_8.retained_image import load_retained_image

ROOT = Path(__file__).resolve().parents[2]
IMAGE_BUILD_HEAD = "3e451e87b1f572b0ead310bb55c31063dc22e34f"
CANONICAL = "11b16bc8f40915461dc358aeed64e5b4635565b4eb5af9d8637036926d5c4805"
IMAGE = "sha256:446eb66272d63682d70a6eac89a1ce7e6f279a4a75d5fa6751d7ac99a2cc1210"
ORIGINAL_HEAD = "5bdf99638144bc6739d899ad5b4426ed0d855a60"
ORIGINAL_IMAGE = "sha256:aff9174a884dc2a50fa60d34f5efd106041e93f9113c05130a2b29175c8b5bcd"
AMENDMENT = "aaa3d1083b5cc3cb5386f4f3ca49bd3cdbb2b62398b7aa7c396c09e3bdba16c7"
ALLOWED_OPERATIONS = frozenset({
    "image", "image-decision", "bootstrap", "migrate", "startup",
    "cleanup", "cleanup-wait", "cleanup-disarm", "residue", "finalize",
})
CLEANUP_OPERATIONS = frozenset({
    "cleanup", "cleanup-wait", "cleanup-disarm", "residue", "finalize",
})
FIELDS = frozenset({
    "version", "runtimeFile", "configFile", "ledgerFile", "costFile", "retainedImageFile",
    "sourceHead", "imageBuildSourceHead", "canonicalBuildInputSha256", "retainedImageId",
    "baselineLedger", "baselineLedgerFileSha256", "boundFilesSha256",
    "historicalSubtotalUsd", "aggregateEstimateUsd", "aggregateCeilingUsd",
    "scannerReserveCoversReplacement", "amendmentSha256", "planSha256",
})


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CampaignError("image continuation object is malformed")
    return cast(dict[str, object], value)


def _read(path: Path) -> dict[str, object]:
    return _object(json.loads(path.read_text(encoding="utf-8")))


def _hash(value: object) -> str:
    return hashlib.sha256(
        b"m7.8/image-continuation/v1\0"
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(ROOT / ".runtime/milestone_7_8"):
        raise CampaignError("image continuation evidence must remain private")
    return resolved


def _source() -> str:
    head, _ = local_source_binding()
    ancestor = subprocess.run(
        ("git", "merge-base", "--is-ancestor", IMAGE_BUILD_HEAD, head),
        cwd=ROOT, capture_output=True, check=False, timeout=30,
    )
    if ancestor.returncode or canonical_snapshot(head)["buildInputSha256"] != CANONICAL:
        raise CampaignError("continuation changed the corrected image inputs or source ancestry")
    return head


def _cost(original: Path, replacement: Path, budget: Path) -> tuple[CampaignConfig, Decimal]:
    before, after = _read(original), _read(replacement)
    changed = {key for key in before | after if before.get(key) != after.get(key)}
    if not changed <= {"resourceItems", "contingencyPercent", "conservativeEstimateUsd"}:
        raise CampaignError("continuation cost changed campaign scope")
    config = CampaignConfig.from_json(replacement, allow_expired=True)
    prior_items = before.get("resourceItems")
    items = after.get("resourceItems")
    if (not isinstance(prior_items, list) or not isinstance(items, list)
            or items[:len(prior_items)] != prior_items):
        raise CampaignError("continuation removed previous cost allowances")
    additions = items[len(prior_items):]
    names = {
        "completed-extra-prerequisite-diagnostic", "completed-create-signature-diagnostic",
        "proposed-corrected-bootstrap-prerequisite",
    }
    if (len(additions) != 3 or {_object(item).get("name") for item in additions} != names
            or any(Decimal(str(_object(item).get("fixedUsd"))) < Decimal("0.0189")
                   for item in additions)):
        raise CampaignError("continuation does not cover the three additional executions")
    history = _read(budget)
    historical = Decimal(str(history["historicalSubtotalUsd"]))
    for name, expected in _object(history["inputs"]).items():
        if _file_hash(_private(ROOT / name)) != expected:
            raise CampaignError("historical spending evidence changed")
    aggregate = (
        historical + sum((item.maximum() for item in config.resource_items), Decimal(0))
    ) * (1 + Decimal(config.contingency_percent) / 100)
    if aggregate > 94 or Decimal(config.conservative_estimate_usd) > 50:
        raise CampaignError("continuation exceeds the existing cumulative or bundle ceiling")
    return config, aggregate


def build_plan(
    runtime_path: Path, config_path: Path, ledger_path: Path, *,
    cost_path: Path, retained_image: Path, previous_plan: Path | None = None,
) -> dict[str, object]:
    from infra.milestone_7_8 import operator

    runtime_path, config_path, ledger_path, cost_path, retained_image = map(
        _private, (runtime_path, config_path, ledger_path, cost_path, retained_image),
    )
    runtime = operator.load_runtime(runtime_path)
    original = CampaignConfig.from_json(config_path, allow_expired=True)
    operator.validate_prepared_bundle(runtime_path, runtime, original)
    ledger = load_ledger(ledger_path, original)
    head = _source()
    provenance = load_retained_image(
        retained_image, operator_head=head, canonical_input_sha256=CANONICAL,
    )
    if (runtime["sourceHead"] != ORIGINAL_HEAD or ledger.image_digest != ORIGINAL_IMAGE
            or ledger.phase != Phase.IMAGE_DECIDED.value or ledger.image_scan_count != 1
            or ledger.image_generation_count != 0 or ledger.image_replacement is not None
            or not ledger.cleanup_arm_evidence_sha256
            or provenance["imageId"] != IMAGE
            or provenance["imageBuildSourceHead"] != IMAGE_BUILD_HEAD):
        raise CampaignError("continuation requires the exact original unused-bootstrap attempt")
    folder = runtime_path.parent
    if ledger_path.parent != folder or config_path.parent != folder:
        raise CampaignError("continuation original inputs must be one existing bundle")
    if any((folder / name).exists() for name in (
        "bootstrap-stage-attempt.json", "bootstrap-prerequisites.json",
        "bootstrap-stage-retry-intent.json", "migrate-stage-attempt.json",
    )):
        raise CampaignError("normal bootstrap or a prerequisite has already been admitted")
    failed = operator._read_stage_record(
        folder / "bootstrap-prerequisite-intent.json", "database-prerequisite-intent",
    )
    if failed.get("operation") != "bootstrap" or failed.get("bindings") != operator._stage_bindings(
        original, runtime, ledger,
    ):
        raise CampaignError("original failed prerequisite binding differs")
    budget = folder / "budget-continuity.json"
    _, aggregate = _cost(config_path, cost_path, budget)
    from infra.milestone_7_8.local_image import validate_completion

    validate_completion(
        runtime_path, runtime, original, digest=ORIGINAL_IMAGE,
        scan_path=folder / "local-image/image-scan.json",
    )
    paths = [runtime_path, config_path, cost_path, budget, retained_image]
    paths += [folder / name for name in (
        "bootstrap-prerequisite-intent.json", "local-image/completed.json",
        "local-image/image-scan.json", "prerequisite-diagnosis-r1/diagnostic-only-result.json",
        "create-signature-diagnostic/diagnostic-only-result.json",
    )]
    old_image_files = _object(_read(folder / "local-image/completed.json")["filesSha256"])
    paths += [folder / "local-image" / name for name in old_image_files]
    retained_folders = [folder / "phases/bootstrap", *folder.glob("job-database-prerequisite-*")]
    for retained_folder in retained_folders:
        if retained_folder.is_dir():
            paths += [item for item in retained_folder.rglob("*") if item.is_file()]
    plan: dict[str, object] = {
        "version": "m7.8-image-continuation-plan-v1", "runtimeFile": str(runtime_path),
        "configFile": str(config_path), "ledgerFile": str(ledger_path),
        "costFile": str(cost_path), "retainedImageFile": str(retained_image),
        "sourceHead": head, "imageBuildSourceHead": IMAGE_BUILD_HEAD,
        "canonicalBuildInputSha256": CANONICAL, "retainedImageId": IMAGE,
        "baselineLedger": _read(ledger_path), "baselineLedgerFileSha256": _file_hash(ledger_path),
        "boundFilesSha256": {str(path): _file_hash(path) for path in paths},
        "historicalSubtotalUsd": _read(budget)["historicalSubtotalUsd"],
        "aggregateEstimateUsd": str(aggregate), "aggregateCeilingUsd": "94",
        "scannerReserveCoversReplacement": True,
        "amendmentSha256": AMENDMENT,
    }
    if previous_plan is not None:
        from infra.milestone_7_8.image_continuation_recovery import build_prior

        plan["priorImageAttempt"] = build_prior(previous_plan)
    return {**plan, "planSha256": _hash(plan)}


def load_plan(path: Path) -> dict[str, object]:
    plan = _read(_private(path))
    body = {key: value for key, value in plan.items() if key != "planSha256"}
    if (set(plan) not in (FIELDS, FIELDS | {"priorImageAttempt"})
            or plan["planSha256"] != _hash(body)
            or plan["version"] != "m7.8-image-continuation-plan-v1"
            or plan["imageBuildSourceHead"] != IMAGE_BUILD_HEAD
            or plan["canonicalBuildInputSha256"] != CANONICAL or plan["retainedImageId"] != IMAGE
            or plan["aggregateCeilingUsd"] != "94"
            or plan["amendmentSha256"] != AMENDMENT
            or plan["scannerReserveCoversReplacement"] is not True):
        raise CampaignError("image continuation plan is malformed or differs")
    for name, expected in _object(plan["boundFilesSha256"]).items():
        if _file_hash(_private(Path(name))) != expected:
            raise CampaignError("image continuation historical evidence changed")
    required_files = {str(plan[name]) for name in (
        "runtimeFile", "configFile", "costFile", "retainedImageFile",
    )}
    folder = Path(str(plan["runtimeFile"])).parent
    slot = "image-continuation-r1" if "priorImageAttempt" in plan else "image-continuation"
    if path.resolve() != folder / slot / "plan.json":
        raise CampaignError("continuation plan is outside its exact private attempt slot")
    if "priorImageAttempt" in plan:
        from infra.milestone_7_8.image_continuation_recovery import validate_prior

        validate_prior(_object(plan["priorImageAttempt"]))
    required_files |= {str(folder / name) for name in (
        "budget-continuity.json", "bootstrap-prerequisite-intent.json",
        "local-image/completed.json", "local-image/image-scan.json",
        "prerequisite-diagnosis-r1/diagnostic-only-result.json",
        "create-signature-diagnostic/diagnostic-only-result.json",
    )}
    if not required_files <= set(_object(plan["boundFilesSha256"])):
        raise CampaignError("continuation omitted a required original evidence binding")
    from infra.milestone_7_8 import local_image, operator

    original_runtime = operator.load_runtime(Path(str(plan["runtimeFile"])))
    original_config = CampaignConfig.from_json(Path(str(plan["configFile"])), allow_expired=True)
    if original_runtime["sourceHead"] != ORIGINAL_HEAD:
        raise CampaignError("continuation original executing source differs")
    local_image.validate_completion(
        Path(str(plan["runtimeFile"])), original_runtime, original_config,
        digest=ORIGINAL_IMAGE, scan_path=folder / "local-image/image-scan.json",
    )
    return plan


def _effective(plan: dict[str, object]) -> tuple[dict[str, str], CampaignConfig]:
    from infra.milestone_7_8 import operator

    path = Path(str(plan["runtimeFile"]))
    runtime = operator.load_runtime(path)
    original = CampaignConfig.from_json(Path(str(plan["configFile"])), allow_expired=True)
    operator.validate_prepared_bundle(path, runtime, original)
    config, aggregate = _cost(
        Path(str(plan["configFile"])), Path(str(plan["costFile"])),
        path.parent / "budget-continuity.json",
    )
    if str(aggregate) != plan["aggregateEstimateUsd"]:
        raise CampaignError("continuation cumulative cost binding differs")
    return {**runtime, "sourceHead": str(plan["sourceHead"]),
            "canonicalBuildInputSha256": CANONICAL}, config


def load_context(
    path: Path, runtime_path: Path, config_path: Path, ledger_path: Path, *, operation: str,
) -> tuple[dict[str, str], CampaignConfig, Ledger]:
    plan = load_plan(path)
    if (operation not in ALLOWED_OPERATIONS
            or str(runtime_path.resolve()) != plan["runtimeFile"]
            or str(config_path.resolve()) != plan["configFile"]
            or str(ledger_path.resolve()) != plan["ledgerFile"]
            or _source() != plan["sourceHead"]):
        raise CampaignError("continuation operation, files, or executing source differs")
    runtime, config = _effective(plan)
    raw = _read(ledger_path)
    replaced = raw.get("image_replacement") is not None
    if not replaced:
        if (operation not in CLEANUP_OPERATIONS and (raw != plan["baselineLedger"]
                or _file_hash(ledger_path) != plan["baselineLedgerFileSha256"])):
            raise CampaignError("continuation original ledger changed before admission")
        original = CampaignConfig.from_json(config_path, allow_expired=True)
        ledger = load_ledger(ledger_path, original)
        if operation in CLEANUP_OPERATIONS:
            config = original
        if operation not in {"image", "image-decision", *CLEANUP_OPERATIONS}:
            raise CampaignError("replacement image and workload admission is incomplete")
    else:
        ledger = load_ledger(ledger_path, config)
        if operation in {"image", "image-decision"}:
            raise CampaignError("one corrected image admission has already been consumed")
        if operation not in CLEANUP_OPERATIONS:
            validate_admission(path, runtime, config, ledger)
    # Operator phases use their existing expiry-to-cleanup handler. Standalone
    # image tooling and the private startup probe have no such dispatch branch.
    if (operation in {"image", "startup"}
            and parse_utc(config.cleanup_deadline_utc) <= datetime.now(UTC)):
        raise CampaignError("continuation cleanup deadline has expired")
    return runtime, config, ledger


def validate_image_completion_context(
    runtime: dict[str, str], config: CampaignConfig, image_plan: dict[str, object],
    continuation: Path,
) -> None:
    plan = load_plan(continuation)
    effective_runtime, effective_config = _effective(plan)
    if (runtime != effective_runtime or config != effective_config
            or image_plan.get("continuationFile") != str(continuation.resolve())
            or image_plan.get("continuationPlanSha256") != plan["planSha256"]):
        raise CampaignError("replacement image continuation context differs")
    retained = _object(image_plan.get("retainedImage"))
    if (retained.get("imageId") != IMAGE or retained.get("imageBuildSourceHead") != IMAGE_BUILD_HEAD
            or retained.get("provenanceFile") != plan["retainedImageFile"]):
        raise CampaignError("replacement image provenance differs from approved correction")


def validate_image_request(
    runtime: dict[str, str], config: CampaignConfig, ledger: Ledger,
    image_plan: dict[str, object], approval: dict[str, object], now: datetime,
) -> None:
    path = Path(str(image_plan.get("continuationFile")))
    validate_image_completion_context(runtime, config, image_plan, path)
    plan = load_plan(path)
    baseline = _object(plan["baselineLedger"])
    if (asdict(ledger) != asdict(Ledger(**baseline))  # type: ignore[arg-type]
            or ledger.phase != Phase.IMAGE_DECIDED.value
            or ledger.image_replacement is not None or _source() != plan["sourceHead"]
            or now >= parse_utc(config.cleanup_deadline_utc)
            or now >= parse_utc(str(approval["expiresAtUtc"]))):
        raise CampaignError("replacement image original admission or dispatch window differs")


def validate_admission(
    path: Path, runtime: dict[str, str], config: CampaignConfig, ledger: Ledger,
) -> dict[str, object]:
    from infra.milestone_7_8 import local_image, workload_image_update

    plan = load_plan(path)
    folder = path.resolve().parent
    receipt = _read(folder / "completed.json")
    body = {key: value for key, value in receipt.items() if key != "continuationSha256"}
    if (set(receipt) != {"planSha256", "imageDigest", "scanEvidenceSha256",
                         "workloadCompletionSha256", "continuationSha256", "admissionIntentSha256"}
            or receipt["continuationSha256"] != _hash(body)
            or receipt["planSha256"] != plan["planSha256"]
            or ledger.image_replacement is None
            or ledger.image_replacement["continuationSha256"] != receipt["continuationSha256"]
            or ledger.image_digest != receipt["imageDigest"]
            or ledger.image_scan_evidence_sha256 != receipt["scanEvidenceSha256"]):
        raise CampaignError("replacement admission receipt or ledger binding differs")
    baseline = _object(plan["baselineLedger"])
    if (ledger.image_replacement["previousImageDigest"] != baseline.get("image_digest")
            or ledger.image_replacement["previousScanEvidenceSha256"]
            != baseline.get("image_scan_evidence_sha256")
            or ledger.image_replacement["previousConservativeEstimateUsd"]
            != baseline.get("conservative_estimate_usd")
            or ledger.resource_generation_count != baseline.get("resource_generation_count")
            or ledger.image_generation_count != baseline.get("image_generation_count")
            or ledger.cleanup_arm_evidence_sha256 != baseline.get("cleanup_arm_evidence_sha256")):
        raise CampaignError("replacement admission spliced original image or generation history")
    before_transitions = baseline.get("transitions")
    if (not isinstance(before_transitions, list)
            or ledger.transitions[:len(before_transitions)] != before_transitions):
        raise CampaignError("replacement admission changed original phase history")
    intent = _read(folder / "admission-intent.json")
    if (receipt["admissionIntentSha256"] != _file_hash(folder / "admission-intent.json")
            or intent.get("planSha256") != plan["planSha256"]
            or intent.get("imageDigest") != receipt["imageDigest"]
            or intent.get("scanEvidenceSha256") != receipt["scanEvidenceSha256"]
            or intent.get("originalLedger") != baseline
            or intent.get("authorizationSha256") != _file_hash(folder / "authorization.json")):
        raise CampaignError("replacement admission dispatch or approval history differs")
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization

    for operation in ("image-decision", "cleanup"):
        load_execution_authorization(
            folder / "authorization.json", config=config, runtime=runtime,
            operation=operation, now=parse_utc(str(intent.get("startedAtUtc"))),
        )
    local_image.validate_completion(
        Path(str(plan["runtimeFile"])), runtime, replace(config, image_digest=None),
        digest=str(receipt["imageDigest"]), scan_path=folder / "local-image/image-scan.json",
        continuation=path,
    )
    workload = workload_image_update.validate_completion(
        runtime, config, previous_digest=ORIGINAL_IMAGE, digest=str(receipt["imageDigest"]),
        output=folder / "workload",
    )
    if workload["completionSha256"] != receipt["workloadCompletionSha256"]:
        raise CampaignError("workload preservation receipt differs")
    # Preservation replay proves ordered exact requests, but the saved approval
    # must independently cover every dispatch, not only admission's start.
    for dispatch_path in sorted((folder / "workload").glob("*-dispatch.json")):
        dispatched = parse_utc(str(_read(dispatch_path)["dispatchedAtUtc"]))
        for operation in ("image-decision", "cleanup"):
            load_execution_authorization(
                folder / "authorization.json", config=config, runtime=runtime,
                operation=operation, now=dispatched,
            )
    return receipt


def prerequisite_directory(path: Path, runtime: dict[str, str], config: CampaignConfig,
                           ledger: Ledger) -> Path:
    validate_admission(path, runtime, config, ledger)
    folder = path.resolve().parent / "prerequisites"
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def resolved_image_pause(
    path: Path, runtime: dict[str, str], config: CampaignConfig, ledger: Ledger,
) -> str | None:
    plan = load_plan(path)
    if "priorImageAttempt" not in plan:
        return None
    validate_admission(path, runtime, config, ledger)
    pause_path = Path(str(plan["runtimeFile"])).parent / "local-image-stage-pause.json"
    from infra.milestone_7_8.image_continuation_recovery import bound_pause_matches

    if not bound_pause_matches(_object(plan["priorImageAttempt"]), _read(pause_path)):
        raise CampaignError("replacement completion differs from the retained image pause")
    return _file_hash(pause_path)


def execute_admission(
    path: Path, runtime: dict[str, str], config: CampaignConfig, ledger: Ledger, *,
    digest: str, scan_path: Path, authorization: Path, execute: bool,
) -> int:
    """Enter through operator image-decision; never resubmit the Bicep base."""
    from infra.milestone_7_8 import local_image, operator, workload_image_update
    from infra.milestone_7_8.campaign import SubprocessRunner, save_ledger
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization

    plan = load_plan(path)
    runtime_path = Path(str(plan["runtimeFile"]))
    folder = path.resolve().parent
    if local_image.validate_completion(
        runtime_path, runtime, replace(config, image_digest=None), digest=digest,
        scan_path=scan_path, continuation=path,
    ) != 0:
        raise CampaignError("corrected retained image must not claim another campaign build")
    scan_sha256 = operator.load_image_scan_evidence(scan_path, digest=digest, runtime=runtime)
    if not execute:
        print(json.dumps({"status": "valid", "mutationAuthorized": False,
                          "operation": "image-decision", "baseDeployment": False,
                          "planSha256": plan["planSha256"]}))
        return 0

    def check_authority() -> None:
        if not operator._stage_is_protected(config, runtime, ledger):
            raise operator._ProtectedStageExpired("replacement cleanup protection expired")
        if _source() != plan["sourceHead"]:
            raise CampaignError("replacement executing source changed")
        for operation in ("image-decision", "cleanup"):
            load_execution_authorization(
                authorization, config=config, runtime=runtime, operation=operation,
            )

    runner = SubprocessRunner(timeout_seconds=45)
    try:
        check_authority()
        operator._verify_retry_protection(runner, config, runtime, ledger)
        check_authority()
        # An existing attempt always needs investigation; never silently retry
        # updates. Preserve the exact authorization independently of its caller.
        with (folder / "authorization.json").open("xb") as stream:
            stream.write(authorization.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        _durable_record(folder / "admission-intent.json", {
            "planSha256": plan["planSha256"], "imageDigest": digest,
            "scanEvidenceSha256": scan_sha256, "authorizationSha256": _file_hash(authorization),
            "originalLedger": plan["baselineLedger"], "startedAtUtc": datetime.now(UTC).isoformat(),
        })
        updates = workload_image_update.execute_updates(
            runtime, config, previous_digest=ORIGINAL_IMAGE, digest=digest,
            output=folder / "workload", runner=runner, clock=lambda: datetime.now(UTC),
            check_authority=check_authority,
        )
        check_authority()
        replay = workload_image_update.validate_completion(
            runtime, config, previous_digest=ORIGINAL_IMAGE, digest=digest,
            output=folder / "workload",
        )
        if replay != updates:
            raise CampaignError("replacement workload result differs from recorded evidence")
        body = {
            "planSha256": plan["planSha256"], "imageDigest": digest,
            "scanEvidenceSha256": scan_sha256,
            "workloadCompletionSha256": replay["completionSha256"],
            "admissionIntentSha256": _file_hash(folder / "admission-intent.json"),
        }
        receipt = {**body, "continuationSha256": _hash(body)}
        _durable_record(folder / "completed.json", receipt)
        ledger.record_image_replacement(
            digest, scan_sha256, str(receipt["continuationSha256"]),
            conservative_estimate_usd=config.conservative_estimate_usd, now=datetime.now(UTC),
        )
        validate_admission(path, runtime, config, ledger)
        save_ledger(Path(str(plan["ledgerFile"])), ledger)
    except Exception as exc:
        if operator._stage_is_protected(config, runtime, ledger):
            raise operator._ProtectedStagePaused(
                "replacement admission paused; retained attempt requires investigation"
            ) from exc
        # The existing mandatory cleanup authority remains effective at expiry.
        def cleanup_authority() -> None:
            load_execution_authorization(
                authorization, config=config, runtime=runtime, operation="cleanup",
            )
        cleanup_authority()
        operator.start_failure_cleanup(runner, config, runtime, cleanup_authority)
        ledger.transition(Phase.CLEANING, datetime.now(UTC))
        save_ledger(Path(str(plan["ledgerFile"])), ledger)
        raise
    print(json.dumps({"status": "passed", "phase": ledger.phase,
                      "continuationSha256": receipt["continuationSha256"]}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "validate"))
    for name in ("runtime", "config", "ledger", "cost", "retained-image", "plan"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--previous-plan", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "plan":
            plan = build_plan(
                args.runtime, args.config, args.ledger, cost_path=args.cost,
                retained_image=args.retained_image, previous_plan=args.previous_plan,
            )
            slot = (
                "image-continuation-r1" if args.previous_plan is not None else "image-continuation"
            )
            folder = args.runtime.resolve().parent / slot
            if args.plan.resolve().parent != folder:
                raise CampaignError("continuation plan must use its exact private directory")
            folder.mkdir(mode=0o700, exist_ok=True)
            _durable_record(args.plan, plan)
        else:
            load_context(args.plan, args.runtime, args.config, args.ledger, operation="image")
            plan = load_plan(args.plan)
        print(json.dumps({"status": "valid", "planSha256": plan["planSha256"],
                          "azureOperations": 0, "authorizationIssued": False}))
        return 0
    except (CampaignError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
