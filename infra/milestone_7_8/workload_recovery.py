"""Replay one failed mount deployment and repair its proved-missing resources only."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    CommandRunner,
    Ledger,
    Phase,
    parse_utc,
    save_ledger,
)
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.controller import REPOSITORY_ROOT, local_source_binding
from infra.milestone_7_8.controller_admission import digest as domain_hash
from infra.milestone_7_8.controller_renewal import _durable_record

ORIGINAL_HEAD = "e2b81a5bf03e83a5ad3f1287522cf1a6aa763cdb"
PRIVATE = REPOSITORY_ROOT / ".runtime/milestone_7_8/p-five/ca"
APPROVAL_DIRECTORY = REPOSITORY_ROOT / ".runtime/milestone_7_8/p-five-plan/execution-approved-01"
APPROVAL_FILE_SHA256 = "4af57705603ceb629726c516154ea4a61a93277ae3f11818e8fbe341b4b5726d"
VERSION = "m7.8-workload-mount-recovery-v1"
OPERATIONS = frozenset({"image-decision", "bootstrap", "migrate", "evidence", "dispose"})
SOURCE_PATHS = {
    "infra/milestone_7_8/modules/campaign-resources.bicep",
    "infra/milestone_7_8/operator.py",
    "infra/milestone_7_8/workload_recovery.py",
    "infra/milestone_7_8/workload_repair_template.py",
    "apps/api/tests/test_milestone_7_8_workload_recovery.py",
    "apps/api/tests/test_milestone_7_8_workload_repair_template.py",
    "apps/api/tests/test_milestone_7_8_shared_storage.py",
    "docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md",
}
HISTORY = (
    "runtime.json", "campaign-cost.json", "campaign.parameters.json",
    "image-decision-stage-attempt.json", "image-decision-stage-pause.json",
    "phases/image-decision/authorization.json", "phases/image-decision/001-intent.json",
    "phases/image-decision/001-result.json", "phases/deploy/001-result.json",
    "local-image/completed.json", "local-image/image-scan.json",
)
JOB_FIELDS = (
    ("workerJob", "workerJobName"), ("bootstrapJob", "bootstrapJobName"),
    ("migrationJob", "migrationJobName"), ("evidenceJob", "evidenceJobName"),
    ("apiProbeJob", "apiProbeJobName"), ("workerProbeJob", "workerProbeJobName"),
    ("migrationProbeJob", "migrationProbeJobName"), ("recoveryJob", "recoveryJobName"),
    ("recoveryRestoreJob", "recoveryRestoreJobName"),
)
MISSING = ("apiApp", "workerJob", "evidenceJob", "migrationProbeJob")
NESTED_ORIGINAL = "m78-campaign-u5uce6pmivap4"
REPAIR_NAME = "m78-campaign-64c74e2e74-storage-workload-repair"


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CampaignError("workload recovery evidence is malformed")
    return cast(dict[str, object], value)


def _hash(path: Path) -> str:
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(PRIVATE):
        raise CampaignError("workload recovery path escaped the private bundle")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(runtime: dict[str, str]) -> dict[str, str]:
    head, cleanup = local_source_binding()

    def git(*args: str) -> str:
        result = subprocess.run(("git", *args), cwd=REPOSITORY_ROOT, check=False,
                                capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise CampaignError("workload recovery source inspection failed")
        return result.stdout.strip()

    paths = set(git("diff", "--name-only", ORIGINAL_HEAD, head).splitlines())
    canonical = canonical_snapshot(head)
    stashes = git("stash", "list", "--format=%H").splitlines()
    if (
        runtime["sourceHead"] != ORIGINAL_HEAD
        or git("rev-list", "--parents", "-n", "1", head).split() != [head, ORIGINAL_HEAD]
        or not paths <= SOURCE_PATHS
        or "infra/milestone_7_8/modules/campaign-resources.bicep" not in paths
        or cleanup != runtime["cleanupScriptSha256"]
        or canonical != canonical_snapshot(ORIGINAL_HEAD)
        or canonical["buildInputSha256"] != runtime["canonicalBuildInputSha256"]
        or len(stashes) != 5
    ):
        raise CampaignError("workload recovery changed source, image inputs or protected stashes")
    return {"operatorSourceHead": head, "protectedStashesSha256": domain_hash(VERSION, stashes)}


def _targets(runtime: dict[str, str], config: CampaignConfig) -> dict[str, str]:
    group = config.target_resource_group
    suffix = group.removeprefix("rg-m78-").removesuffix("-target")
    base = f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{group}/providers/Microsoft.App/"
    return {
        "apiApp": base + f"containerApps/app-m78-{suffix}",
        **{key: base + "jobs/" + runtime[field] for key, field in JOB_FIELDS},
    }


def _show(runtime: dict[str, str], config: CampaignConfig, target: str) -> tuple[str, ...]:
    kind = ("job",) if "/jobs/" in target else ()
    return ("az", "containerapp", *kind, "show", "--resource-group", config.target_resource_group,
            "--name", target.rsplit("/", 1)[1], "--subscription", runtime["subscriptionId"],
            "--output", "json", "--only-show-errors")


def _absent(value: dict[str, object], target: str) -> bool:
    return (value.get("exitCode") == 1 and not str(value.get("stdout", "")).strip()
            and "(ResourceNotFound)" in str(value.get("stderr", ""))
            and target.rsplit("/", 1)[1] in str(value.get("stderr", "")))


def _observed_workload(
    value: dict[str, object], *, key: str, runtime: dict[str, str],
    config: CampaignConfig, image_digest: str,
) -> dict[str, object]:
    from infra.milestone_7_8 import workload_image_update as workload

    scope = workload._scope(runtime, config, "sha256:" + "0" * 64, image_digest)
    target_id = _targets(runtime, config)[key]
    target = next(item for item in cast(list[dict[str, str]], scope["targets"])
                  if item["id"] == target_id)
    resource = workload._decoded(value)
    workload._validate_resource(resource, target, scope, runtime, config, image_digest)
    if workload._object(resource.get("properties")).get("provisioningState") != "Succeeded":
        raise CampaignError("workload recovery resource is not provisioned successfully")
    return resource


def _diagnosis(runtime: dict[str, str], config: CampaignConfig,
               image_digest: str) -> dict[str, str]:
    targets = _targets(runtime, config)
    observed = {"apiApp": "02", **{key: "resources/" + name for key, name in JOB_FIELDS}}
    observed["workerJob"] = "03"
    folder = PRIVATE / "workload-mount-diagnosis"
    hashes = {}

    def read_pair(label: str, command: tuple[str, ...]) -> dict[str, object]:
        intent, result = folder / (label + "-intent.json"), folder / (label + "-result.json")
        hashes[str(intent.relative_to(PRIVATE).as_posix())] = _hash(intent)
        hashes[str(result.relative_to(PRIVATE).as_posix())] = _hash(result)
        request = _read(intent)
        if request.get("command") != list(command):
            raise CampaignError("original workload diagnosis request differs")
        parse_utc(str(request.get("observedAtUtc")))
        return _read(result)

    listing = read_pair("01", (
        "az", "deployment", "operation", "group", "list", "--resource-group",
        config.target_resource_group, "--name", NESTED_ORIGINAL, "--subscription",
        runtime["subscriptionId"], "--output", "json", "--only-show-errors",
    ))
    entries = json.loads(str(listing.get("stdout")))
    if listing.get("exitCode") != 0 or not isinstance(entries, list) or not entries:
        raise CampaignError("original workload operations are unavailable")
    failed: set[str] = set()
    completed: set[str] = set()
    for entry in entries:
        fields = entry["properties"]
        target = fields["targetResource"]["id"].casefold()
        state = fields["provisioningState"]
        if state == "Failed":
            error = fields["statusMessage"]["error"]
            if (fields["provisioningOperation"] != "Create"
                    or error["code"] != "ContainerAppVolumeMountOptionsNotSupported"
                    or "'seal'" not in error["message"] or target in failed):
                raise CampaignError("original workload failure is not the reviewed mount defect")
            failed.add(target)
        elif state == "Succeeded":
            if fields["provisioningOperation"] == "Create":
                completed.add(target)
        else:
            raise CampaignError("original workload deployment operation outcome is uncertain")
    if (failed != {targets[key].casefold() for key in ("apiApp", "workerJob")}
            or any((target.casefold() in completed) != (key not in MISSING)
                   for key, target in targets.items())):
        raise CampaignError("original workload operation identities or status differ")
    for key, label in observed.items():
        target = targets[key]
        result = read_pair(label, _show(runtime, config, target))
        if key in MISSING:
            if not _absent(result, target):
                raise CampaignError("original failed or skipped workload target absence is unproved")
        else:
            _observed_workload(result, key=key, runtime=runtime, config=config,
                               image_digest=image_digest)
    return hashes


def _binding(path: Path, runtime: dict[str, str], config: CampaignConfig) -> dict[str, object]:
    from infra.milestone_7_8 import operator
    from infra.milestone_7_8.local_image import validate_completion

    if path.resolve() != PRIVATE / "workload-recovery/plan.json":
        raise CampaignError("workload recovery plan destination differs")
    approval = APPROVAL_DIRECTORY / "user-approval.json"
    if (approval.is_symlink() or approval.parent.resolve() != APPROVAL_DIRECTORY
            or hashlib.sha256(approval.read_bytes()).hexdigest() != APPROVAL_FILE_SHA256):
        raise CampaignError("workload recovery standing human approval differs")
    files = {name: _hash(PRIVATE / name) for name in HISTORY}
    attempt = operator._read_stage_record(PRIVATE / HISTORY[3], "stage-attempt")
    pause = operator._read_stage_record(PRIVATE / HISTORY[4], "stage-pause")
    failed = _read(PRIVATE / HISTORY[7])
    image = _read(PRIVATE / "local-image/completed.json")
    image_digest = str(image.get("imageDigest"))
    scan = PRIVATE / "local-image/image-scan.json"
    bound_config = replace(config, image_digest=image_digest)
    bindings = cast(dict[str, object], pause.get("bindings"))
    prior = Ledger(config.campaign_id, config.generation_id)
    prior.phase = Phase.INFRASTRUCTURE_DEPLOYED.value
    prior.cleanup_arm_evidence_sha256 = cast(str, bindings["cleanupArmSha256"])
    original = list(operator.command_plan("image-decision", bound_config, runtime)[0])
    intent = _read(PRIVATE / "phases/image-decision/001-intent.json")
    if (
        pause.get("operation") != "image-decision" or pause.get("failedExecution") is not None
        or pause.get("attemptSha256") != attempt.get("recordSha256")
        or attempt.get("operation") != "image-decision"
        or attempt.get("authorizationSha256") != files[HISTORY[5]]
        or pause.get("authorizationSha256") != files[HISTORY[5]]
        or bindings != operator._stage_bindings(bound_config, runtime, prior)
        or attempt.get("bindings") != bindings
        or attempt.get("commandSha256") != operator._stage_hash("stage-command", [original])
        or intent.get("command") != original
        or failed.get("exitCode") != 1
        or str(failed.get("stderr", "")).count("ContainerAppVolumeMountOptionsNotSupported") != 2
        or "'seal'" not in str(failed.get("stderr", ""))
        or validate_completion(PRIVATE / "runtime.json", runtime, config,
                               digest=image_digest, scan_path=scan) != 0
    ):
        raise CampaignError("original failed workload attempt or retained image differs")
    scan_sha = operator.load_image_scan_evidence(scan, digest=image_digest, runtime=runtime)
    base_result = _read(PRIVATE / HISTORY[8])
    operator.validate_operation_results("deploy", [base_result], config, runtime)
    files.update(_diagnosis(runtime, config, image_digest))
    return {"originalSourceHead": ORIGINAL_HEAD, **_source(runtime), "filesSha256": files,
            "standingApprovalFileSha256": APPROVAL_FILE_SHA256,
            "cleanupArmEvidenceSha256": prior.cleanup_arm_evidence_sha256,
            "imageDigest": image_digest, "scanSha256": scan_sha,
            "cleanupDeadlineUtc": config.cleanup_deadline_utc}


def build_plan(path: Path, runtime: dict[str, str], config: CampaignConfig,
               ledger: Ledger, *, deploy_until: str) -> dict[str, object]:
    binding = _binding(path, runtime, config)
    if (
        Phase(ledger.phase) is not Phase.INFRASTRUCTURE_DEPLOYED or ledger.image_digest is not None
        or ledger.cleanup_arm_evidence_sha256 != binding["cleanupArmEvidenceSha256"]
        or not datetime.now(UTC) < parse_utc(deploy_until) <= (
            parse_utc(config.cleanup_deadline_utc) - timedelta(minutes=45)
        )
    ):
        raise CampaignError("workload recovery requires the original protected ledger and live window")
    body = {"version": VERSION, **binding, "deployUntilUtc": deploy_until,
            "targets": _targets(runtime, config), "repairName": REPAIR_NAME,
            "missing": list(MISSING)}
    body.update(_derived_hashes(_template(body)))
    return {**body, "planSha256": domain_hash(VERSION, body)}


def load_plan(path: Path, runtime: dict[str, str], config: CampaignConfig) -> dict[str, object]:
    plan = _read(path)
    body = {"version": VERSION, **_binding(path, runtime, config),
            "deployUntilUtc": plan.get("deployUntilUtc"), "targets": _targets(runtime, config),
            "repairName": REPAIR_NAME, "missing": list(MISSING)}
    body.update(_derived_hashes(_template(body)))
    if plan != {**body, "planSha256": domain_hash(VERSION, body)} or (
        parse_utc(str(plan["deployUntilUtc"])) >
        parse_utc(config.cleanup_deadline_utc) - timedelta(minutes=45)
    ):
        raise CampaignError("workload recovery plan differs from retained evidence")
    return plan


def _template(plan: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    from infra.milestone_7_8.workload_repair_template import compile_main, derive_template

    return derive_template(
        compile_main(), _read(PRIVATE / "campaign.parameters.json"),
        image_digest=str(plan["imageDigest"]), missing=MISSING, repair_name=REPAIR_NAME,
    )


def _derived_hashes(derived: tuple[dict[str, object], dict[str, object]]) -> dict[str, str]:
    return {key: domain_hash(VERSION, value) for key, value in zip(
        ("templateSha256", "parametersSha256"), derived, strict=True,
    )}


def _deploy_command(runtime: dict[str, str], config: CampaignConfig, folder: Path) -> tuple[str, ...]:
    return (
        "az", "deployment", "sub", "create", "--name", REPAIR_NAME + "-outer",
        "--location", config.target_region, "--template-file", str(folder / "template.json"),
        "--parameters", "@" + str(folder / "parameters.json"),
        "--subscription", runtime["subscriptionId"], "--output", "json", "--only-show-errors",
    )


def _artifact_hashes(folder: Path) -> dict[str, str]:
    paths = ("template.json", "parameters.json", "authorization.json", "before.json",
             "intent.json", "deployment-result.json", "after.json")
    return {name: _hash(folder / name) for name in paths}


def _check_reads(before: Mapping[str, object], after: Mapping[str, object] | None, *,
                 plan: dict[str, object], runtime: dict[str, str], config: CampaignConfig) -> None:
    from infra.milestone_7_8.workload_repair_template import validate_repaired_mount

    targets = _targets(runtime, config)
    image_digest = str(plan["imageDigest"])
    if set(before) != set(targets) or (after is not None and set(after) != set(targets)):
        raise CampaignError("workload recovery readback targets differ")
    for key, target in targets.items():
        prior = cast(dict[str, object], before[key])
        if key in MISSING:
            if not _absent(prior, target):
                raise CampaignError("planned workload target is no longer proved absent")
        else:
            original = _observed_workload(prior, key=key, runtime=runtime, config=config,
                                          image_digest=image_digest)
            field = dict(JOB_FIELDS)[key]
            previous = _read(PRIVATE / f"workload-mount-diagnosis/resources/{field}-result.json")
            if original != _observed_workload(previous, key=key, runtime=runtime, config=config,
                                              image_digest=image_digest):
                raise CampaignError("previously successful job changed before workload recovery")
        if after is not None:
            observed = _observed_workload(cast(dict[str, object], after[key]), key=key,
                                          runtime=runtime, config=config, image_digest=image_digest)
            if key in {"apiApp", "workerJob"}:
                validate_repaired_mount(observed)
            if key not in MISSING:
                if observed != original:
                    raise CampaignError("previously successful job changed during workload recovery")


def _validate_completion(
    path: Path, plan: dict[str, object], runtime: dict[str, str], config: CampaignConfig,
    *, draft: dict[str, object] | None = None,
) -> None:
    from infra.milestone_7_8 import operator
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization

    folder = path.parent
    proof = _read(folder / "completed.json") if draft is None else draft
    body = {"version": VERSION, "planSha256": plan["planSha256"],
            "filesSha256": _artifact_hashes(folder)}
    if proof != {**body, "completionSha256": domain_hash(VERSION, body)}:
        raise CampaignError("workload recovery completion evidence differs")
    if any(plan.get(key) != expected for key, expected in _derived_hashes((
        _read(folder / "template.json"), _read(folder / "parameters.json"),
    )).items()):
        raise CampaignError("workload recovery template replay differs")
    intent = _read(folder / "intent.json")
    if (set(intent) != {"planSha256", "command", "dispatchedAtUtc", "inputsSha256"}
            or intent["planSha256"] != plan["planSha256"]
            or intent["inputsSha256"] != {name: _hash(folder / name) for name in (
                "template.json", "parameters.json", "authorization.json", "before.json",
            )}
            or intent["command"] != list(_deploy_command(runtime, config, folder))):
        raise CampaignError("workload recovery intent command differs")
    dispatched = parse_utc(str(intent["dispatchedAtUtc"]))
    if dispatched >= parse_utc(str(plan["deployUntilUtc"])):
        raise CampaignError("workload recovery dispatch was outside its window")
    for operation in ("image-decision", "cleanup"):
        load_execution_authorization(folder / "authorization.json", config=config,
                                     runtime=runtime, operation=operation, now=dispatched)
    result = _read(folder / "deployment-result.json")
    response = operator._json_result(result)
    if (not isinstance(response, dict) or response.get("name") != REPAIR_NAME + "-outer"
            or not isinstance(response.get("properties"), dict)
            or response["properties"].get("provisioningState") != "Succeeded"):
        raise CampaignError("workload recovery deployment result is not exact terminal success")
    operator.validate_operation_results(
        "image-decision", [result], replace(config, image_digest=str(plan["imageDigest"])), runtime,
    )
    _check_reads(_read(folder / "before.json"), _read(folder / "after.json"),
                 plan=plan, runtime=runtime, config=config)


def resume_pause(
    path: Path, plan: dict[str, object], runtime: dict[str, str], config: CampaignConfig,
    ledger: Ledger,
) -> str:
    """Validate the separate repair receipt before later phases use historical bindings."""
    if (ledger.image_digest != plan["imageDigest"]
            or ledger.image_scan_evidence_sha256 != plan["scanSha256"]
            or ledger.image_generation_count != 0 or ledger.image_scan_count != 1
            or ledger.image_replacement is not None
            or ledger.cleanup_arm_evidence_sha256 != plan["cleanupArmEvidenceSha256"]):
        raise CampaignError("workload recovery ledger does not bind the original image and scan")
    _validate_completion(path, plan, runtime, config)
    files = cast(dict[str, str], plan["filesSha256"])
    return files["image-decision-stage-pause.json"]


def execute(
    path: Path, plan: dict[str, object], runtime: dict[str, str], config: CampaignConfig,
    ledger: Ledger, *, authorization: Path, runner: CommandRunner, authorize: Callable[[], None],
) -> None:
    from infra.milestone_7_8 import operator

    folder = path.parent
    if (Phase(ledger.phase) is not Phase.INFRASTRUCTURE_DEPLOYED or ledger.image_digest is not None
            or ledger.cleanup_arm_evidence_sha256 != plan["cleanupArmEvidenceSha256"]):
        raise CampaignError("workload recovery ledger no longer matches the paused phase")

    def guard() -> None:
        if not operator._stage_is_protected(config, runtime, ledger):
            raise operator._ProtectedStageExpired("workload recovery cleanup protection expired")
        if datetime.now(UTC) >= parse_utc(str(plan["deployUntilUtc"])):
            raise CampaignError("workload recovery dispatch or readback window is exhausted")
        authorize()

    guard()
    if (folder / "completed.json").exists():
        _validate_completion(path, plan, runtime, config)
    else:
        if (folder / "intent.json").exists():
            raise CampaignError("workload recovery dispatch already recorded; never repeat it")
        template, parameters = _template(plan)
        if any(plan.get(key) != expected for key, expected in _derived_hashes((
            template, parameters,
        )).items()):
            raise CampaignError("workload recovery template plan binding differs")
        _durable_record(folder / "template.json", template)
        _durable_record(folder / "parameters.json", parameters)
        _durable_record(folder / "authorization.json", _read(authorization))
        # The old protected ARM invocation is never resubmitted.
        guard()
        operator._verify_retry_protection(runner, config, runtime, ledger)
        targets = _targets(runtime, config)
        def observe() -> dict[str, dict[str, object]]:
            values = {}
            for key, target in targets.items():
                guard()
                values[key] = runner.run(_show(runtime, config, target))
            return values

        before = observe()
        _check_reads(before, None, plan=plan, runtime=runtime, config=config)
        _durable_record(folder / "before.json", before)
        command = _deploy_command(runtime, config, folder)
        guard()
        _durable_record(folder / "intent.json", {
            "planSha256": plan["planSha256"], "command": command,
            "dispatchedAtUtc": datetime.now(UTC).isoformat(),
            "inputsSha256": {name: _hash(folder / name) for name in (
                "template.json", "parameters.json", "authorization.json", "before.json",
            )},
        })
        guard()
        result = runner.run(command)
        _durable_record(folder / "deployment-result.json", result)
        if result.get("exitCode") != 0:
            raise CampaignError("workload recovery deployment failed or is ambiguous; preserve intent")
        guard()
        after = observe()
        _durable_record(folder / "after.json", after)
        body = {"version": VERSION, "planSha256": plan["planSha256"],
                "filesSha256": _artifact_hashes(folder)}
        proof = {**body, "completionSha256": domain_hash(VERSION, body)}
        _validate_completion(path, plan, runtime, config, draft=proof)
        _durable_record(folder / "completed.json", proof)
    guard()
    ledger.record_image(str(plan["imageDigest"]), built=False)
    ledger.record_image_scan(str(plan["imageDigest"]), str(plan["scanSha256"]))
    ledger.transition(Phase.IMAGE_DECIDED, datetime.now(UTC))
    save_ledger(PRIVATE / "ledger.json", ledger)
