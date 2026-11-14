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
from datetime import UTC, datetime, timedelta
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
MIGRATION_VERSION = "m7.8-migration-image-continuation-plan-v1"
MIGRATION_ORIGINAL_HEAD = "e2b81a5bf03e83a5ad3f1287522cf1a6aa763cdb"
MIGRATION_PREVIOUS_HEAD = "be3caf3a6f4b8a0426dc6855d7105389fb9754bb"
MIGRATION_WORKLOAD_PLAN = "2f21eb9fceabb5569e3208964b58b48b4d13f6748e69bb211523326cc8620cda"
MIGRATION_FIELDS = FIELDS | {
    "originalImageDigest", "workloadRecoveryPlanFile", "workloadRecoveryPlanSha256",
    "migrationPauseSha256", "failedMigrationExecution", "protectedStashesSha256",
}
MIGRATION_OPERATIONS = ALLOWED_OPERATIONS | {"evidence", "dispose"}
GRANT_VERSION = "m7.8-grant-recovery-image-continuation-v1"
GRANT_PREVIOUS_HEAD = "9ee46ba7d7431ca44ee1aa85a18adce031543daf"
GRANT_PREVIOUS_PLAN = "e0384bb35a10d5a4df7cae56d1a5d5d7250c6cf9fc64bc465fecec93f60ce12d"
GRANT_APPROVAL = "f7ff3f7a827e9fd31e5787bd66e4e7b69552f9b8ba036196c486ed7e879cd116"
GRANT_FIELDS = FIELDS | {
    "previousPlanFile", "previousPlanSha256", "originalImageDigest", "grantApprovalFile",
    "consumedRetryIntentSha256", "consumedRetryExecution", "failedExecutionReadbackFile",
    "protectedStashesSha256", "cleanupMustBeginByUtc",
}


def _migration_source(plan: dict[str, object] | None = None) -> dict[str, str]:
    head, cleanup = local_source_binding()
    def git(*arguments: str) -> str:
        result = subprocess.run(("git", *arguments), cwd=ROOT, check=False,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise CampaignError("migration image source inspection failed")
        return result.stdout.strip()
    allowed = {
        "apps/api/alembic/versions/20260716_0001_initial_mvp.py",
        "apps/api/tests/test_migration_0001_postgres.py",
        "infra/milestone_7_8/image_continuation.py",
        "infra/milestone_7_8/operator.py", "infra/milestone_7_8/campaign.py",
        "infra/milestone_7_8/schemas/ledger.schema.json",
        "infra/milestone_7_8/schemas/terminal-receipt.schema.json",
        "scripts/validate_migrations.py",
        "apps/api/tests/test_milestone_7_8_migration_image_continuation.py",
        "apps/api/tests/test_milestone_7_8_migration_operator_continuation.py",
        "apps/api/tests/test_milestone_7_8_image_replacement_ledger.py",
        "apps/api/tests/test_milestone_7_8_campaign_enablement.py",
        "apps/api/tests/test_milestone_7_8_job_diagnostics.py",
        "docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md",
    }
    changes = set(git("diff", "--name-only", MIGRATION_PREVIOUS_HEAD, head).splitlines())
    stashes = git("stash", "list", "--format=%H").splitlines()
    if (git("rev-list", "--parents", "-n", "1", head).split() != [head, MIGRATION_PREVIOUS_HEAD]
            or not changes <= allowed
            or "apps/api/alembic/versions/20260716_0001_initial_mvp.py" not in changes
            or len(stashes) != 5):
        raise CampaignError("migration image source transition is not the reviewed correction")
    result = {"sourceHead": head, "cleanupScriptSha256": cleanup,
              "canonicalBuildInputSha256": str(canonical_snapshot(head)["buildInputSha256"]),
              "protectedStashesSha256": _hash(stashes)}
    if plan is not None and any(result[key] != plan[key] for key in (
        "sourceHead", "canonicalBuildInputSha256", "protectedStashesSha256",
    )):
        raise CampaignError("migration image executing source or protected stashes changed")
    return result


def _migration_cost(original: Path, replacement: Path) -> tuple[CampaignConfig, Decimal]:
    before, after = _read(original), _read(replacement)
    if {key for key in before | after if before.get(key) != after.get(key)} - {
        "resourceItems", "conservativeEstimateUsd",
    }:
        raise CampaignError("migration image cost changed original campaign scope")
    old_items, items = before.get("resourceItems"), after.get("resourceItems")
    if (not isinstance(old_items, list) or not isinstance(items, list)
            or items[:len(old_items)] != old_items or len(items) != len(old_items) + 1):
        raise CampaignError("migration image cost did not preserve all prior allowances")
    addition = _object(items[-1])
    if (addition.get("name") != "corrected-migration-prerequisite"
            or Decimal(str(addition.get("fixedUsd"))) < Decimal("0.0378")):
        raise CampaignError("corrected migration prerequisite allowance is missing")
    config = CampaignConfig.from_json(replacement, allow_expired=True)
    aggregate = Decimal("46.723665") * Decimal("1.25") + Decimal(config.conservative_estimate_usd)
    if aggregate > 108 or Decimal(config.conservative_estimate_usd) > 50:
        raise CampaignError("migration image correction exceeds the approved budget")
    return config, aggregate


def _migration_history(folder: Path, original: CampaignConfig,
                       runtime: dict[str, str], baseline: Ledger) -> dict[str, object]:
    from infra.milestone_7_8 import local_image, operator, workload_recovery
    workload_path = folder / "workload-recovery/plan.json"
    workload = _read(workload_path)
    if (workload.get("planSha256") != MIGRATION_WORKLOAD_PLAN
            or workload.get("operatorSourceHead") != MIGRATION_PREVIOUS_HEAD):
        raise CampaignError("migration image predecessor is not the accepted workload repair")
    for relative, expected in _object(workload["filesSha256"]).items():
        if _file_hash(_private(folder / relative)) != expected:
            raise CampaignError("accepted workload repair historical evidence changed")
    workload_recovery._validate_completion(workload_path, workload, runtime, original)
    local_image.validate_completion(
        folder / "runtime.json", runtime, original, digest=str(baseline.image_digest),
        scan_path=folder / "local-image/image-scan.json",
    )
    pause = operator._read_stage_record(folder / "migrate-stage-pause.json", "stage-pause")
    attempt = operator._read_stage_record(folder / "migrate-stage-attempt.json", "stage-attempt")
    expected = operator._stage_bindings(original, runtime, baseline)
    if (pause.get("operation") != "migrate" or pause.get("bindings") != expected
            or attempt.get("operation") != "migrate" or attempt.get("bindings") != expected
            or pause.get("attemptSha256") != attempt.get("recordSha256")
            or pause.get("authorizationSha256") != attempt.get("authorizationSha256")
            or type(pause.get("maximumRetryDispatches")) is not int
            or pause["maximumRetryDispatches"] != 1
            or not isinstance(pause.get("failedExecution"), str)):
        raise CampaignError("migration correction failed-attempt history differs")
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization

    authority = folder / "phases/migrate/authorization.json"
    if _file_hash(authority) != attempt.get("authorizationSha256"):
        raise CampaignError("migration correction original authorization differs")
    for operation in ("migrate", "cleanup"):
        load_execution_authorization(
            authority, config=original, runtime=runtime, operation=operation,
            now=parse_utc(str(attempt.get("startedAtUtc"))),
        )
    for operation in ("bootstrap", "migrate"):
        prerequisite = operator._read_stage_record(
            folder / f"{operation}-prerequisites.json", "database-prerequisites",
        )
        bindings = {**expected, "ledgerPhase": (
            Phase.IMAGE_DECIDED.value if operation == "bootstrap" else baseline.phase
        )}
        if prerequisite.get("bindings") != bindings or prerequisite.get("operation") != operation:
            raise CampaignError("migration correction prior prerequisite binding differs")
    bootstrap_result = _read(folder / "phases/bootstrap/command-result.json")
    if bootstrap_result.get("exitCode") != 0:
        raise CampaignError("migration correction bootstrap success is unproved")
    return pause


def _migration_bound_paths(folder: Path, paths: set[Path]) -> set[Path]:
    for name in ("bootstrap-stage-attempt.json", "bootstrap-prerequisite-intent.json",
                 "bootstrap-prerequisite-start.json", "bootstrap-prerequisites.json",
                 "migrate-stage-attempt.json", "migrate-stage-pause.json",
                 "migrate-prerequisite-intent.json", "migrate-prerequisite-start.json",
                 "migrate-prerequisites.json", "image-decision-stage-pause.json",
                 "local-image/completed.json", "local-image/image-scan.json"):
        paths.add(folder / name)
    for directory in (folder / "workload-recovery", folder / "phases/bootstrap",
                      folder / "phases/migrate", folder / "local-image"):
        paths.update(item for item in directory.rglob("*")
                     if item.is_file() and "source" not in item.relative_to(directory).parts)
    return paths


def build_migration_plan(
    runtime_path: Path, config_path: Path, ledger_path: Path, *,
    cost_path: Path, retained_image: Path,
) -> dict[str, object]:
    """Bind one corrected image to this bootstrapped, failed-migration campaign."""
    from infra.milestone_7_8 import operator, workload_recovery
    runtime_path, config_path, ledger_path, cost_path, retained_image = map(
        _private, (runtime_path, config_path, ledger_path, cost_path, retained_image),
    )
    folder = runtime_path.parent
    if folder != ROOT / ".runtime/milestone_7_8/p-five/ca" or (
        config_path != folder / "campaign-cost.json" or ledger_path != folder / "ledger.json"
    ):
        raise CampaignError("migration image correction requires its exact original bundle")
    runtime = operator.load_runtime(runtime_path)
    original = CampaignConfig.from_json(config_path, allow_expired=True)
    operator.validate_prepared_bundle(runtime_path, runtime, original)
    ledger = load_ledger(ledger_path, original)
    source = _migration_source()
    if (runtime["sourceHead"] != MIGRATION_ORIGINAL_HEAD
            or runtime["cleanupScriptSha256"] != source["cleanupScriptSha256"]
            or ledger.phase != Phase.DATABASE_BOOTSTRAPPED.value
            or ledger.image_digest is None or ledger.image_scan_count != 1
            or ledger.image_generation_count != 0 or ledger.image_replacement is not None
            or any((folder / name).exists() for name in (
                "migrate-stage-retry-intent.json", "migrate-stage-retry-start.json",
            ))):
        raise CampaignError("migration image correction is not the unused guarded retry")
    pause = _migration_history(folder, original, runtime, ledger)
    provenance = load_retained_image(
        retained_image, operator_head=source["sourceHead"],
        canonical_input_sha256=source["canonicalBuildInputSha256"],
    )
    if (provenance["imageBuildSourceHead"] != source["sourceHead"]
            or provenance["imageId"] == ledger.image_digest):
        raise CampaignError("migration corrected image is not built from its executing source")
    _, aggregate = _migration_cost(config_path, cost_path)
    approval = workload_recovery.APPROVAL_DIRECTORY / "user-approval.json"
    if _file_hash(approval) != workload_recovery.APPROVAL_FILE_SHA256:
        raise CampaignError("migration correction standing approval changed")
    paths = _migration_bound_paths(
        folder, {runtime_path, config_path, cost_path, retained_image, approval},
    )
    plan: dict[str, object] = {
        "version": MIGRATION_VERSION, "runtimeFile": str(runtime_path),
        "configFile": str(config_path), "ledgerFile": str(ledger_path),
        "costFile": str(cost_path), "retainedImageFile": str(retained_image),
        "sourceHead": source["sourceHead"],
        "imageBuildSourceHead": provenance["imageBuildSourceHead"],
        "canonicalBuildInputSha256": source["canonicalBuildInputSha256"],
        "retainedImageId": provenance["imageId"], "originalImageDigest": ledger.image_digest,
        "protectedStashesSha256": source["protectedStashesSha256"],
        "baselineLedger": _read(ledger_path), "baselineLedgerFileSha256": _file_hash(ledger_path),
        "boundFilesSha256": {str(item): _file_hash(item) for item in sorted(paths)},
        "historicalSubtotalUsd": "46.723665", "aggregateEstimateUsd": str(aggregate),
        "aggregateCeilingUsd": "108", "scannerReserveCoversReplacement": True,
        "amendmentSha256": _file_hash(approval),
        "workloadRecoveryPlanFile": str(folder / "workload-recovery/plan.json"),
        "workloadRecoveryPlanSha256": MIGRATION_WORKLOAD_PLAN,
        "migrationPauseSha256": _file_hash(folder / "migrate-stage-pause.json"),
        "failedMigrationExecution": pause["failedExecution"],
    }
    return {**plan, "planSha256": _hash(plan)}


def _load_migration_plan(path: Path, plan: dict[str, object]) -> dict[str, object]:
    from infra.milestone_7_8 import operator, workload_recovery
    body = {key: value for key, value in plan.items() if key != "planSha256"}
    if (set(plan) != MIGRATION_FIELDS or plan["planSha256"] != _hash(body)
            or plan["aggregateCeilingUsd"] != "108"
            or plan["historicalSubtotalUsd"] != "46.723665"
            or plan["scannerReserveCoversReplacement"] is not True
            or plan["amendmentSha256"] != workload_recovery.APPROVAL_FILE_SHA256
            or plan["workloadRecoveryPlanSha256"] != MIGRATION_WORKLOAD_PLAN):
        raise CampaignError("migration image continuation plan differs")
    folder = Path(str(plan["runtimeFile"])).parent
    if (folder != ROOT / ".runtime/milestone_7_8/p-five/ca"
            or path.resolve() != folder / "migration-image-continuation/plan.json"
            or Path(str(plan["runtimeFile"])) != folder / "runtime.json"
            or Path(str(plan["configFile"])) != folder / "campaign-cost.json"
            or Path(str(plan["ledgerFile"])) != folder / "ledger.json"
            or Path(str(plan["workloadRecoveryPlanFile"]))
            != folder / "workload-recovery/plan.json"):
        raise CampaignError("migration continuation private scope differs")
    required = _migration_bound_paths(folder, {
        Path(str(plan[key]))
        for key in ("runtimeFile", "configFile", "costFile", "retainedImageFile")
    } | {workload_recovery.APPROVAL_DIRECTORY / "user-approval.json"})
    if set(_object(plan["boundFilesSha256"])) != {str(item) for item in required}:
        raise CampaignError("migration continuation historical inventory differs")
    for name, expected in _object(plan["boundFilesSha256"]).items():
        if _file_hash(_private(Path(name))) != expected:
            raise CampaignError("migration continuation historical evidence changed")
    runtime = operator.load_runtime(Path(str(plan["runtimeFile"])))
    original = CampaignConfig.from_json(Path(str(plan["configFile"])), allow_expired=True)
    baseline = Ledger(**_object(plan["baselineLedger"]))  # type: ignore[arg-type]
    baseline.validate_resume(original)
    if (baseline.phase != Phase.DATABASE_BOOTSTRAPPED.value
            or baseline.image_digest != plan["originalImageDigest"]
            or baseline.image_replacement is not None or baseline.image_scan_count != 1
            or baseline.image_generation_count != 0 or baseline.resource_generation_count != 1
            or runtime["sourceHead"] != MIGRATION_ORIGINAL_HEAD):
        raise CampaignError("migration continuation original ledger or source differs")
    pause = _migration_history(folder, original, runtime, baseline)
    if (plan["migrationPauseSha256"] != _file_hash(folder / "migrate-stage-pause.json")
            or plan["failedMigrationExecution"] != pause["failedExecution"]):
        raise CampaignError("migration continuation changed the original failed execution")
    provenance = load_retained_image(
        Path(str(plan["retainedImageFile"])), operator_head=str(plan["sourceHead"]),
        canonical_input_sha256=str(plan["canonicalBuildInputSha256"]),
    )
    if (provenance["imageId"] != plan["retainedImageId"]
            or provenance["imageBuildSourceHead"] != plan["imageBuildSourceHead"]
            or plan["sourceHead"] != plan["imageBuildSourceHead"]):
        raise CampaignError("migration continuation retained image provenance changed")
    return plan


def _grant_source(
    previous: dict[str, object], plan: dict[str, object] | None = None
) -> dict[str, str]:
    head, cleanup = local_source_binding()

    def git(*args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()

    allowed = {
        "infra/milestone_7_8/image_continuation.py",
        "infra/milestone_7_8/campaign.py",
        "infra/milestone_7_8/operator.py",
        "infra/milestone_7_8/measurement_handoff.py",
        "infra/milestone_7_8/schemas/ledger.schema.json",
        "infra/milestone_7_8/schemas/terminal-receipt.schema.json",
        "apps/api/opencanvas_api/db/role_privileges.py",
        "apps/api/scripts/bootstrap_postgres.py",
        "apps/api/scripts/migrate_and_grant.py",
        "apps/api/scripts/managed_postgres_evidence.py",
        "apps/api/scripts/m78_database_recovery.py",
        "apps/api/tests/test_milestone_7_8_migration_image_continuation.py",
        "apps/api/tests/test_milestone_7_8_migration_operator_continuation.py",
        "apps/api/tests/test_milestone_7_8_image_replacement_ledger.py",
        "apps/api/tests/test_milestone_7_8_managed_extension_baseline.py",
        "apps/api/tests/test_milestone_7_8_vector_grants_postgres.py",
        "apps/api/tests/test_milestone_7_8_database_recovery.py",
        "apps/api/tests/test_milestone_7_8_grant_recovery.py",
        "docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md",
    }
    changes = set(git("diff", "--name-only", GRANT_PREVIOUS_HEAD, head).splitlines())
    runtime = _read(Path(str(previous["runtimeFile"])))
    stashes = _hash(git("stash", "list", "--format=%H").splitlines())
    if (
        git("rev-list", "--parents", "-n", "1", head).split() != [head, GRANT_PREVIOUS_HEAD]
        or not changes <= allowed
        or "apps/api/opencanvas_api/db/role_privileges.py" not in changes
        or cleanup != runtime["cleanupScriptSha256"]
        or stashes != previous["protectedStashesSha256"]
    ):
        raise CampaignError("grant correction executing source is not the reviewed direct child")
    result = {
        "sourceHead": head,
        "canonicalBuildInputSha256": str(canonical_snapshot(head)["buildInputSha256"]),
        "protectedStashesSha256": stashes,
    }
    if plan is not None and any(plan[key] != value for key, value in result.items()):
        raise CampaignError("grant correction executing source or canonical inputs changed")
    return result


def _grant_approval(path: Path, previous: dict[str, object]) -> dict[str, object]:
    approval = _read(_private(path))
    if (
        _file_hash(path) != GRANT_APPROVAL
        or approval.get("priorPlanSha256") != previous["planSha256"]
        or approval.get("priorOperatorSourceHead") != GRANT_PREVIOUS_HEAD
        or approval.get("bootstrapReplayAllowed") is not False
        or approval.get("alembicReplayAllowed") is not False
        or approval.get("maximumAdditionalGrantRecoveryDispatches") != 1
        or approval.get("maximumAdditionalCorrectedPrerequisiteDispatches") != 1
    ):
        raise CampaignError("grant recovery explicit contract/attempt amendment differs")
    for prefix in ("catalog", "owner"):
        evidence = _private(Path(str(approval[prefix + "EvidenceFile"])))
        if _file_hash(evidence) != approval[prefix + "EvidenceSha256"]:
            raise CampaignError("approved managed-extension catalog evidence changed")
    return approval


def _grant_cost(previous: dict[str, object], path: Path) -> tuple[CampaignConfig, Decimal]:
    original, after = _read(Path(str(previous["costFile"]))), _read(path)
    if {key for key in original | after if original.get(key) != after.get(key)} - {
        "resourceItems",
        "conservativeEstimateUsd",
    }:
        raise CampaignError("grant recovery changed original campaign scope")
    prior = original.get("resourceItems")
    items = after.get("resourceItems")
    if (
        not isinstance(prior, list)
        or not isinstance(items, list)
        or items[: len(prior)] != prior
        or len(items) != len(prior) + 4
    ):
        raise CampaignError("grant recovery did not preserve all prior allowances")
    additions = [_object(item) for item in items[len(prior) :]]
    if {item.get("name") for item in additions} != {
        "completed-grant-diagnostic",
        "completed-grant-owner-diagnostic",
        "grant-recovery-prerequisite",
        "grant-recovery-job",
    } or any(Decimal(str(item.get("fixedUsd"))) < Decimal("0.0378") for item in additions):
        raise CampaignError("grant recovery diagnostic and two-start allowance is incomplete")
    config = CampaignConfig.from_json(path, allow_expired=True)
    aggregate = Decimal("46.723665") * Decimal("1.25") + Decimal(config.conservative_estimate_usd)
    if aggregate > 108 or Decimal(config.conservative_estimate_usd) > 50:
        raise CampaignError("grant recovery exceeds the approved budget")
    return config, aggregate


def _grant_consumed_history(
    previous_path: Path, previous: dict[str, object], ledger: Ledger
) -> tuple[dict[str, object], dict[str, object], Path]:
    from infra.milestone_7_8 import operator
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization

    runtime, config = _effective(previous)
    validate_admission(previous_path, runtime, config, ledger)
    folder = Path(str(previous["runtimeFile"])).parent
    intent = operator._read_stage_record(
        folder / "migrate-stage-retry-intent.json", "stage-retry-intent"
    )
    start = operator._read_stage_record(
        folder / "migrate-stage-retry-start.json", "stage-retry-start"
    )
    value = operator._json_result(_object(start["startResult"]))
    execution = str(_object(value).get("name"))
    if (
        intent.get("operation") != "migrate"
        or intent.get("operatorSourceHead") != GRANT_PREVIOUS_HEAD
        or start.get("retryIntentSha256") != intent["recordSha256"]
        or intent.get("bindings") != operator._stage_bindings(config, runtime, ledger)
    ):
        raise CampaignError("consumed migration retry source, image or journal differs")
    authority = previous_path.parent / "captures/migrate-resume-01/authorization.json"
    if _file_hash(authority) != intent.get("authorizationSha256"):
        raise CampaignError("consumed migration retry authorization differs")
    for operation in ("migrate", "cleanup"):
        load_execution_authorization(
            authority,
            config=config,
            runtime=runtime,
            operation=operation,
            now=parse_utc(str(intent["startedAtUtc"])),
        )
    matches = []
    for file in folder.glob("job-failure-*/execution.json"):
        saved = _read(file)
        if saved.get("executionName") == execution:
            terminal = _object(operator._json_result(_object(saved["lastResult"])))
            expected = (
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
                f"{runtime['resourceGroupName']}/providers/Microsoft.App/jobs/"
                f"{runtime['migrationJobName']}/executions/{execution}"
            )
            if (
                terminal.get("name") != execution
                or str(terminal.get("id")).casefold() != expected.casefold()
                or _object(terminal.get("properties")).get("status") != "Failed"
            ):
                raise CampaignError("consumed migration retry terminal identity differs")
            matches.append((saved, file))
    if len(matches) != 1:
        raise CampaignError("one exact consumed migration failure readback is required")
    return intent, matches[0][0], matches[0][1]


def build_grant_cleanup_source_amendment(
    previous_plan: Path,
    *,
    explicit_approval: Path,
) -> dict[str, object]:
    previous = load_plan(previous_plan)
    if previous.get("planSha256") != GRANT_PREVIOUS_PLAN:
        raise CampaignError("grant cleanup source amendment predecessor differs")
    approval = _grant_approval(explicit_approval, previous)
    source = _grant_source(previous)
    runtime, config = _effective(previous)
    validate_admission(
        previous_plan, runtime, config, load_ledger(Path(str(previous["ledgerFile"])), config)
    )
    body = {
        "version": "m7.8-grant-cleanup-source-amendment-v1",
        "previousPlanSha256": previous["planSha256"],
        **source,
        "approvalFile": str(_private(explicit_approval)),
        "approvalSha256": GRANT_APPROVAL,
        "cleanupMustBeginByUtc": approval["cleanupMustBeginByUtc"],
    }
    return {**body, "amendmentSha256": _hash(body)}


def _grant_cleanup_source(previous: dict[str, object]) -> bool:
    path = (
        Path(str(previous["runtimeFile"])).parent
        / "migration-image-continuation"
        / "grant-cleanup-source-amendment.json"
    )
    if not path.exists():
        return False
    record = _read(path)
    expected = build_grant_cleanup_source_amendment(
        path.parent / "plan.json",
        explicit_approval=Path(str(record["approvalFile"])),
    )
    if record != expected:
        raise CampaignError("grant cleanup-only executing source amendment differs")
    return True


def build_grant_recovery_plan(
    previous_plan: Path,
    *,
    cost_path: Path,
    retained_image: Path,
    explicit_approval: Path,
) -> dict[str, object]:
    previous = load_plan(previous_plan)
    if previous.get("planSha256") != GRANT_PREVIOUS_PLAN:
        raise CampaignError("grant recovery predecessor is not the accepted image correction")
    approval = _grant_approval(explicit_approval, previous)
    source = _grant_source(previous)
    _, prior_config = _effective(previous)
    ledger_path = Path(str(previous["ledgerFile"]))
    ledger = load_ledger(ledger_path, prior_config)
    if (
        ledger.phase != Phase.DATABASE_BOOTSTRAPPED.value
        or ledger.image_replacement is None
        or ledger.previous_image_replacement is not None
        or ledger.image_scan_count != 2
    ):
        raise CampaignError(
            "grant recovery requires exactly one accepted migration image correction"
        )
    intent, failed, failed_file = _grant_consumed_history(previous_plan, previous, ledger)
    provenance = load_retained_image(
        retained_image,
        operator_head=source["sourceHead"],
        canonical_input_sha256=source["canonicalBuildInputSha256"],
    )
    if provenance["imageBuildSourceHead"] != source["sourceHead"]:
        raise CampaignError("grant recovery image was not built from the corrected source")
    _, aggregate = _grant_cost(previous, cost_path)
    folder = Path(str(previous["runtimeFile"])).parent
    files = {Path(str(previous[key])) for key in ("runtimeFile", "configFile", "costFile")}
    files.update(
        {
            _private(cost_path),
            _private(retained_image),
            _private(explicit_approval),
            failed_file,
            folder / "migrate-stage-retry-intent.json",
            folder / "migrate-stage-retry-start.json",
        }
    )
    for directory in (
        previous_plan.parent,
        folder / "grant-diagnostic-01",
        folder / "grant-owner-diagnostic-01",
        failed_file.parent,
    ):
        files.update(
            item
            for item in directory.rglob("*")
            if item.is_file() and "source" not in item.relative_to(directory).parts
        )
    body: dict[str, object] = {
        "version": GRANT_VERSION,
        **source,
        "runtimeFile": previous["runtimeFile"],
        "configFile": previous["configFile"],
        "ledgerFile": str(ledger_path),
        "costFile": str(_private(cost_path)),
        "retainedImageFile": str(_private(retained_image)),
        "imageBuildSourceHead": provenance["imageBuildSourceHead"],
        "retainedImageId": provenance["imageId"],
        "originalImageDigest": ledger.image_digest,
        "baselineLedger": _read(ledger_path),
        "baselineLedgerFileSha256": _file_hash(ledger_path),
        "boundFilesSha256": {str(item): _file_hash(item) for item in sorted(files)},
        "previousPlanFile": str(previous_plan.resolve()),
        "previousPlanSha256": previous["planSha256"],
        "grantApprovalFile": str(_private(explicit_approval)),
        "amendmentSha256": GRANT_APPROVAL,
        "historicalSubtotalUsd": "46.723665",
        "aggregateEstimateUsd": str(aggregate),
        "aggregateCeilingUsd": "108",
        "scannerReserveCoversReplacement": True,
        "consumedRetryIntentSha256": intent["recordSha256"],
        "consumedRetryExecution": failed["executionName"],
        "failedExecutionReadbackFile": str(failed_file),
        "cleanupMustBeginByUtc": approval["cleanupMustBeginByUtc"],
    }
    return {**body, "planSha256": _hash(body)}


def _load_grant_plan(path: Path, plan: dict[str, object]) -> dict[str, object]:
    body = {key: value for key, value in plan.items() if key != "planSha256"}
    if (
        set(plan) != GRANT_FIELDS
        or plan["planSha256"] != _hash(body)
        or plan["amendmentSha256"] != GRANT_APPROVAL
        or plan["previousPlanSha256"] != GRANT_PREVIOUS_PLAN
        or plan["aggregateCeilingUsd"] != "108"
        or plan["historicalSubtotalUsd"] != "46.723665"
    ):
        raise CampaignError("grant recovery plan shape or exact amendment differs")
    previous_path = _private(Path(str(plan["previousPlanFile"])))
    previous = load_plan(previous_path)
    approval = _grant_approval(Path(str(plan["grantApprovalFile"])), previous)
    folder = Path(str(previous["runtimeFile"])).parent
    if (
        path.resolve() != folder / "grant-image-continuation/plan.json"
        or any(plan[key] != previous[key] for key in ("runtimeFile", "configFile", "ledgerFile"))
        or plan["cleanupMustBeginByUtc"] != approval["cleanupMustBeginByUtc"]
    ):
        raise CampaignError("grant recovery exact existing bundle differs")
    files = _object(plan["boundFilesSha256"])
    for name, digest in files.items():
        if _file_hash(_private(Path(name))) != digest:
            raise CampaignError("grant recovery retained predecessor evidence changed")
    required = {
        str(previous_path),
        str(Path(str(plan["failedExecutionReadbackFile"]))),
        str(folder / "migrate-stage-retry-intent.json"),
        str(folder / "migrate-stage-retry-start.json"),
        str(plan["grantApprovalFile"]),
        str(plan["retainedImageFile"]),
        str(plan["costFile"]),
    }
    if not required <= set(files):
        raise CampaignError("grant recovery predecessor evidence inventory is incomplete")
    baseline = Ledger(**_object(plan["baselineLedger"]))  # type: ignore[arg-type]
    _, prior_config = _effective(previous)
    baseline.validate_resume(prior_config)
    intent, failed, failed_file = _grant_consumed_history(previous_path, previous, baseline)
    if (
        intent["recordSha256"] != plan["consumedRetryIntentSha256"]
        or failed["executionName"] != plan["consumedRetryExecution"]
        or str(failed_file) != plan["failedExecutionReadbackFile"]
        or baseline.image_digest != plan["originalImageDigest"]
        or baseline.previous_image_replacement is not None
    ):
        raise CampaignError("grant recovery consumed attempt or prior image differs")
    retained = load_retained_image(
        Path(str(plan["retainedImageFile"])),
        operator_head=str(plan["sourceHead"]),
        canonical_input_sha256=str(plan["canonicalBuildInputSha256"]),
    )
    if (
        retained["imageId"] != plan["retainedImageId"]
        or retained["imageBuildSourceHead"] != plan["sourceHead"]
    ):
        raise CampaignError("grant recovery corrected image source differs")
    return plan


def _grant_retry_body(
    path: Path, *, issued_at: datetime, expires_at: datetime
) -> dict[str, object]:
    plan = load_plan(path)
    if plan.get("version") != GRANT_VERSION:
        raise CampaignError("head-only grant recovery requires its exact second-image plan")
    if (
        issued_at.tzinfo is None
        or expires_at.tzinfo is None
        or not issued_at
        < expires_at
        <= min(issued_at + timedelta(minutes=15), parse_utc(str(plan["cleanupMustBeginByUtc"])))
    ):
        raise CampaignError("grant recovery dispatch window exceeds its approved cutoff")
    admitted = _read(path.parent / "completed.json")
    return {
        "version": "m7.8-grant-only-retry-approval-v1",
        "planSha256": plan["planSha256"],
        "operatorSourceHead": plan["sourceHead"],
        "explicitAmendmentSha256": GRANT_APPROVAL,
        "consumedRetryIntentSha256": plan["consumedRetryIntentSha256"],
        "failedExecution": plan["consumedRetryExecution"],
        "imageDigest": admitted["imageDigest"],
        "admissionReceiptSha256": _file_hash(path.parent / "completed.json"),
        "issuedAtUtc": issued_at.isoformat(),
        "expiresAtUtc": expires_at.isoformat(),
        "cleanupMustBeginByUtc": plan["cleanupMustBeginByUtc"],
        "maximumPrerequisiteDispatches": 1,
        "maximumGrantRecoveryDispatches": 1,
        "requiredRevision": "20260726_0029",
        "bootstrapReplayAllowed": False,
        "alembicReplayAllowed": False,
    }


def build_grant_retry_approval(
    path: Path, *, issued_at: datetime, expires_at: datetime
) -> dict[str, object]:
    plan = load_plan(path)
    _plan_source(plan)
    runtime, config = _effective(plan)
    validate_admission(path, runtime, config, load_ledger(Path(str(plan["ledgerFile"])), config))
    slot = path.parent / "grant-recovery"
    if (
        any(
            (slot / name).exists()
            for name in (
                "migrate-stage-retry-intent.json",
                "migrate-stage-retry-start.json",
            )
        )
        or (path.parent / "grant-retry-approval.json").exists()
    ):
        raise CampaignError("the one additional grant recovery approval or dispatch already exists")
    body = _grant_retry_body(path, issued_at=issued_at, expires_at=expires_at)
    return {**body, "authorizationSha256": _hash(body)}


def grant_retry_transition(
    path: Path, runtime: dict[str, str], config: CampaignConfig, ledger: Ledger
) -> dict[str, object]:
    from infra.milestone_7_8 import operator

    plan = load_plan(path)
    _plan_source(plan)
    validate_admission(path, runtime, config, ledger)
    authority = _read(path.parent / "grant-retry-approval.json")
    body = _grant_retry_body(
        path,
        issued_at=parse_utc(str(authority["issuedAtUtc"])),
        expires_at=parse_utc(str(authority["expiresAtUtc"])),
    )
    if authority != {**body, "authorizationSha256": _hash(body)}:
        raise CampaignError("grant recovery authority or accepted image differs")
    original_folder = Path(str(plan["runtimeFile"])).parent
    intent = operator._read_stage_record(
        original_folder / "migrate-stage-retry-intent.json", "stage-retry-intent"
    )
    failed = _read(Path(str(plan["failedExecutionReadbackFile"])))
    pause_body = {
        "version": "m7.8-protected-stage-pause-v1",
        "operation": "migrate",
        "bindings": intent["bindings"],
        "attemptSha256": intent["recordSha256"],
        "authorizationSha256": intent["authorizationSha256"],
        "failedExecution": plan["consumedRetryExecution"],
        "failedAtUtc": failed["observedAtUtc"],
        "recoveryUntilUtc": authority["expiresAtUtc"],
        "maximumRetryDispatches": 1,
    }
    pause = {**pause_body, "recordSha256": operator._stage_hash("stage-pause", pause_body)}
    previous = load_plan(Path(str(plan["previousPlanFile"])))
    workload = _read(Path(str(previous["workloadRecoveryPlanFile"])))
    prefix = f"{runtime['registryName']}.azurecr.io/mobius-api@"
    return {
        "kind": "migration-image-continuation",
        "grantOnly": True,
        "operatorSourceHead": plan["sourceHead"],
        "transitionSha256": authority["authorizationSha256"],
        "issuedAtUtc": authority["issuedAtUtc"],
        "expiresAtUtc": authority["expiresAtUtc"],
        "cleanupMustBeginByUtc": plan["cleanupMustBeginByUtc"],
        "recoveryDirectory": str(path.parent / "grant-recovery"),
        "recoveryPause": pause,
        "originalBindings": intent["bindings"],
        "migrationPauseSha256": _hash(pause),
        "originalAttemptSha256": intent["recordSha256"],
        "originalConsumedRetryIntentSha256": intent["recordSha256"],
        "previousImageReference": prefix + str(plan["originalImageDigest"]),
        "replacementImageReference": prefix + str(authority["imageDigest"]),
        "resolvedWorkloadPauseSha256": _object(workload["filesSha256"])[
            "image-decision-stage-pause.json"
        ],
    }


def _plan_source(plan: dict[str, object]) -> str:
    if plan.get("version") == GRANT_VERSION:
        previous = load_plan(Path(str(plan["previousPlanFile"])))
        return _grant_source(previous, plan)["sourceHead"]
    if plan.get("version") != MIGRATION_VERSION:
        return _source()
    amendment = _source_amendment(plan)
    return (str(amendment["operatorSourceHead"]) if amendment is not None
            else _migration_source(plan)["sourceHead"])


def _inspect_amended_source(plan: dict[str, object]) -> str:
    head, cleanup = local_source_binding()
    def git(*args: str) -> str:
        return subprocess.run(("git", *args), cwd=ROOT, capture_output=True, text=True,
                              check=True, timeout=30).stdout.strip()
    allowed = {
        "infra/milestone_7_8/operator.py", "infra/milestone_7_8/image_continuation.py",
        "apps/api/tests/test_milestone_7_8_migration_operator_continuation.py",
        "apps/api/tests/test_milestone_7_8_migration_image_continuation.py",
        "docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md",
    }
    original = str(plan["sourceHead"])
    runtime = _read(Path(str(plan["runtimeFile"])))
    changes = set(git("diff", "--name-only", original, head).splitlines())
    if (git("rev-list", "--parents", "-n", "1", head).split() != [head, original]
            or not changes <= allowed or "infra/milestone_7_8/operator.py" not in changes
            or cleanup != runtime["cleanupScriptSha256"]
            or canonical_snapshot(head)["buildInputSha256"] != plan["canonicalBuildInputSha256"]
            or _hash(git("stash", "list", "--format=%H").splitlines())
            != plan["protectedStashesSha256"]):
        raise CampaignError("migration operator-only correction changed its permitted source")
    return head


def _predispatch_capture_files(path: Path, plan: dict[str, object]) -> dict[str, str]:
    from infra.milestone_7_8 import operator

    folder = path.parent
    capture = folder / "captures/migrate"
    intents = sorted(capture.glob("[0-9][0-9][0-9]-intent.json"))
    if len(intents) != 31:
        raise CampaignError("migration predispatch history is incomplete")
    starts = []
    for index, intent in enumerate(intents, 1):
        if intent.name != f"{index:03d}-intent.json":
            raise CampaignError("migration predispatch history is not ordered")
        command = _read(intent).get("command")
        response = _read(capture / f"{index:03d}-result.json")
        if not isinstance(command, list) or response.get("exitCode") != 0:
            raise CampaignError("migration predispatch command result is incomplete")
        if command[:4] == ["az", "containerapp", "job", "start"]:
            starts.append(response)
        elif not (
            command[:4] in (["az", "deployment", "sub", "show"],
                            ["az", "containerapp", "job", "show"],
                            ["az", "automation", "account", "show"],
                            ["az", "role", "assignment", "list"],
                            ["az", "monitor", "log-analytics", "query"])
            or command[:5] == ["az", "monitor", "log-analytics", "workspace", "show"]
            or command[:5] == ["az", "containerapp", "job", "execution", "show"]
            or command[:6] == ["az", "containerapp", "job", "replica", "list", "--name"]
            or command[:4] == ["az", "rest", "--method", "get"]
        ):
            raise CampaignError("migration predispatch history contains another mutation")
    result = _read(capture / "command-result.json")
    failure = "database retry image, command, environment, or template drifted"
    if (result.get("exitCode") != 2
            or failure not in str(result.get("stdout")) + str(result.get("stderr"))):
        raise CampaignError("migration stop is not the reviewed predispatch comparison")
    prefix = folder / "prerequisites"
    start = operator._read_stage_record(prefix / "migrate-prerequisite-start.json",
                                       "database-prerequisite-start")
    proof = operator._read_stage_record(prefix / "migrate-prerequisites.json",
                                       "database-prerequisites")
    prerequisite_intent = operator._read_stage_record(
        prefix / "migrate-prerequisite-intent.json", "database-prerequisite-intent",
    )
    runtime, config = _effective(plan)
    baseline = Ledger(**_object(plan["baselineLedger"]))  # type: ignore[arg-type]
    receipt = _read(folder / "completed.json")
    baseline.image_digest = str(receipt["imageDigest"])
    expected = operator._stage_bindings(config, runtime, baseline)
    if (len(starts) != 1 or starts[0].get("stdout") != start.get("stdout")
            or proof.get("bindings") != expected or prerequisite_intent.get("bindings") != expected
            or proof.get("intentSha256") != prerequisite_intent.get("recordSha256")
            or _object(proof.get("marker")).get("listingRead") is not True):
        raise CampaignError("corrected migration prerequisite or sole dispatch differs")
    files = {item for directory in (capture, prefix) for item in directory.iterdir()
             if item.is_file()}
    files.update(folder / name for name in ("completed.json", "migration-retry-approval.json"))
    return {str(item): _file_hash(item) for item in sorted(files)}


def _retry_not_dispatched(plan: dict[str, object]) -> None:
    folder = Path(str(plan["runtimeFile"])).parent
    if any((folder / name).exists() for name in (
        "migrate-stage-retry-intent.json", "migrate-stage-retry-start.json",
    )):
        raise CampaignError("migration retry is already dispatched or indeterminate")


def build_operator_source_amendment(path: Path, *, approval: Path) -> dict[str, object]:
    plan = load_plan(path)
    if plan.get("version") != MIGRATION_VERSION:
        raise CampaignError("operator-only amendment requires the migration correction")
    _retry_not_dispatched(plan)
    if (path.parent / "operator-source-amendment.json").exists():
        raise CampaignError("operator source amendment already exists")
    head = _inspect_amended_source(plan)
    runtime, config = _effective(plan)
    validate_admission(path, runtime, config, load_ledger(Path(str(plan["ledgerFile"])), config))
    approval = _private(approval)
    explicit = _read(approval)
    if (explicit.get("planSha256") != plan["planSha256"]
            or explicit.get("scope") != "unused-migration-retry-operator-correction"
            or not isinstance(explicit.get("userText"), str) or not explicit["userText"]):
        raise CampaignError("operator source correction lacks its exact standing approval")
    body = {"version": "m7.8-migration-operator-source-amendment-v1",
            "planSha256": plan["planSha256"], "originalSourceHead": plan["sourceHead"],
            "standingApprovalSha256": plan["amendmentSha256"],
            "operatorSourceHead": head,
            "canonicalBuildInputSha256": plan["canonicalBuildInputSha256"],
            "approvalFile": str(approval), "approvalFileSha256": _file_hash(approval),
            "filesSha256": _predispatch_capture_files(path, plan)}
    return {**body, "amendmentSha256": _hash(body)}


def _source_amendment(plan: dict[str, object]) -> dict[str, object] | None:
    folder = Path(str(plan["runtimeFile"])).parent / "migration-image-continuation"
    path = folder / "operator-source-amendment.json"
    if not path.exists():
        return None
    record = _read(path)
    body = {key: value for key, value in record.items() if key != "amendmentSha256"}
    if (set(record) != {"version", "planSha256", "originalSourceHead", "operatorSourceHead",
                        "canonicalBuildInputSha256", "approvalFile", "approvalFileSha256",
                        "filesSha256", "amendmentSha256", "standingApprovalSha256"}
            or record["version"] != "m7.8-migration-operator-source-amendment-v1"
            or record["amendmentSha256"] != _hash(body)
            or record["planSha256"] != plan["planSha256"]
            or record["originalSourceHead"] != plan["sourceHead"]
            or record["standingApprovalSha256"] != plan["amendmentSha256"]
            or record["canonicalBuildInputSha256"] != plan["canonicalBuildInputSha256"]
            or record["operatorSourceHead"] != _inspect_amended_source(plan)
            or record["filesSha256"] != _predispatch_capture_files(folder / "plan.json", plan)
            or record["approvalFileSha256"]
            != _file_hash(_private(Path(str(record["approvalFile"]))))):
        raise CampaignError("migration operator source amendment or retained history differs")
    explicit = _read(Path(str(record["approvalFile"])))
    if (explicit.get("planSha256") != plan["planSha256"]
            or explicit.get("scope") != "unused-migration-retry-operator-correction"):
        raise CampaignError("migration operator source approval scope differs")
    return record


def _previous_image(plan: dict[str, object]) -> str:
    return str(plan.get("originalImageDigest", ORIGINAL_IMAGE))


MIGRATION_RETRY_VERSION = "m7.8-migration-image-retry-approval-v1"
MIGRATION_RETRY_FIELDS = frozenset({
    "version", "planSha256", "operatorSourceHead", "originalPauseFileSha256",
    "originalAttemptFileSha256", "originalAttemptSha256", "originalAuthorizationFileSha256",
    "failedExecution", "imageDigest", "issuedAtUtc", "expiresAtUtc", "cleanupDeadlineUtc",
    "admissionReceiptFileSha256",
    "maximumRetryDispatches", "explicitApprovalFile", "explicitApprovalFileSha256",
    "authorizationSha256",
})


def _migration_retry_body(
    path: Path, *, explicit_approval: Path, issued_at: datetime, expires_at: datetime,
) -> dict[str, object]:
    from infra.milestone_7_8 import operator

    plan = load_plan(path)
    if plan.get("version") != MIGRATION_VERSION:
        raise CampaignError("migration retry approval requires its corrected-image plan")
    folder = Path(str(plan["runtimeFile"])).parent
    original = CampaignConfig.from_json(Path(str(plan["configFile"])), allow_expired=True)
    if (issued_at.tzinfo is None or expires_at.tzinfo is None
            or not issued_at < expires_at <= min(
                issued_at + timedelta(minutes=15), parse_utc(original.cleanup_deadline_utc),
            )):
        raise CampaignError("migration retry approval exceeds its bounded dispatch window")
    explicit_approval = _private(explicit_approval)
    explicit = _read(explicit_approval)
    if (set(explicit) != {"version", "planSha256", "operatorSourceHead", "failedExecution",
                         "scope", "maximumRetryDispatches", "userText"}
            or explicit.get("version") != "m7.8-explicit-migration-retry-approval-v1"
            or explicit.get("planSha256") != plan["planSha256"]
            or explicit.get("operatorSourceHead") != plan["sourceHead"]
            or explicit.get("failedExecution") != plan["failedMigrationExecution"]
            or explicit.get("scope") != "one-guarded-migration-retry"
            or type(explicit.get("maximumRetryDispatches")) is not int
            or explicit["maximumRetryDispatches"] != 1
            or not isinstance(explicit.get("userText"), str)
            or not str(explicit["userText"]).strip()):
        raise CampaignError("migration retry requires separate exact explicit approval")
    attempt = operator._read_stage_record(folder / "migrate-stage-attempt.json", "stage-attempt")
    admitted = _read(path.parent / "completed.json")
    return {
        "version": MIGRATION_RETRY_VERSION, "planSha256": plan["planSha256"],
        "operatorSourceHead": plan["sourceHead"],
        "originalPauseFileSha256": _file_hash(folder / "migrate-stage-pause.json"),
        "originalAttemptFileSha256": _file_hash(folder / "migrate-stage-attempt.json"),
        "originalAttemptSha256": attempt["recordSha256"],
        "originalAuthorizationFileSha256": attempt["authorizationSha256"],
        "failedExecution": plan["failedMigrationExecution"],
        "imageDigest": admitted["imageDigest"],
        "admissionReceiptFileSha256": _file_hash(path.parent / "completed.json"),
        "issuedAtUtc": issued_at.isoformat(),
        "expiresAtUtc": expires_at.isoformat(), "cleanupDeadlineUtc": original.cleanup_deadline_utc,
        "maximumRetryDispatches": 1, "explicitApprovalFile": str(explicit_approval),
        "explicitApprovalFileSha256": _file_hash(explicit_approval),
    }


def build_migration_retry_approval(
    path: Path, *, explicit_approval: Path, issued_at: datetime, expires_at: datetime,
) -> dict[str, object]:
    """Bind a separately approved, unused retry; this builder never writes or dispatches."""
    plan = load_plan(path)
    _plan_source(plan)
    runtime, config = _effective(plan)
    ledger = load_ledger(Path(str(plan["ledgerFile"])), config)
    validate_admission(path, runtime, config, ledger)
    folder = Path(str(plan["runtimeFile"])).parent
    if any((folder / name).exists() for name in (
        "migrate-stage-retry-intent.json", "migrate-stage-retry-start.json",
    )) or (path.parent / "migration-retry-approval.json").exists():
        raise CampaignError("migration retry approval or dispatch has already been consumed")
    body = _migration_retry_body(
        path, explicit_approval=explicit_approval, issued_at=issued_at, expires_at=expires_at,
    )
    return {**body, "authorizationSha256": _hash(body)}


def build_migration_retry_supersession(
    path: Path, *, explicit_approval: Path, issued_at: datetime, expires_at: datetime,
) -> dict[str, object]:
    """Replace one expired, unused dispatch window without replacing any historical record."""
    plan = load_plan(path)
    amendment = _source_amendment(plan)
    if amendment is None:
        raise CampaignError("retry supersession requires the reviewed operator source correction")
    _retry_not_dispatched(plan)
    if (path.parent / "migration-retry-supersession.json").exists():
        raise CampaignError("migration retry supersession already exists")
    previous = _read(path.parent / "migration-retry-approval.json")
    if issued_at < parse_utc(str(previous["expiresAtUtc"])):
        raise CampaignError("the original migration retry window is still open")
    if explicit_approval.resolve() == Path(str(previous["explicitApprovalFile"])).resolve():
        raise CampaignError("retry supersession requires a separately retained approval record")
    runtime, config = _effective(plan)
    validate_admission(path, runtime, config, load_ledger(Path(str(plan["ledgerFile"])), config))
    approval_body = _migration_retry_body(
        path, explicit_approval=explicit_approval, issued_at=issued_at, expires_at=expires_at,
    )
    body = {
        "version": "m7.8-migration-unused-retry-supersession-v1",
        "planSha256": plan["planSha256"], "operatorSourceHead": amendment["operatorSourceHead"],
        "sourceAmendmentSha256": amendment["amendmentSha256"],
        "previousApprovalFileSha256": _file_hash(path.parent / "migration-retry-approval.json"),
        "approval": {**approval_body, "authorizationSha256": _hash(approval_body)},
    }
    return {**body, "supersessionSha256": _hash(body)}


def _load_retry_supersession(
    path: Path, plan: dict[str, object], amendment: dict[str, object] | None,
) -> dict[str, object]:
    record = _read(path.parent / "migration-retry-supersession.json")
    body = {key: value for key, value in record.items() if key != "supersessionSha256"}
    previous = _read(path.parent / "migration-retry-approval.json")
    approval = _object(record.get("approval"))
    if (amendment is None
            or set(record) != {"version", "planSha256", "operatorSourceHead",
                               "sourceAmendmentSha256", "previousApprovalFileSha256", "approval",
                               "supersessionSha256"}
            or record["version"] != "m7.8-migration-unused-retry-supersession-v1"
            or record["planSha256"] != plan["planSha256"]
            or record["operatorSourceHead"] != amendment["operatorSourceHead"]
            or record["sourceAmendmentSha256"] != amendment["amendmentSha256"]
            or record["supersessionSha256"] != _hash(body)
            or record["previousApprovalFileSha256"]
            != _file_hash(path.parent / "migration-retry-approval.json")
            or parse_utc(str(approval.get("issuedAtUtc")))
            < parse_utc(str(previous["expiresAtUtc"]))):
        raise CampaignError("migration unused-retry supersession history differs")
    return record


def migration_retry_transition(
    path: Path, runtime: dict[str, str], config: CampaignConfig, ledger: Ledger,
) -> dict[str, object] | None:
    """Replay an accepted image and exact separate approval, allowing later read-only completion."""
    from infra.milestone_7_8 import operator

    plan = load_plan(path)
    if plan.get("version") == GRANT_VERSION:
        return grant_retry_transition(path, runtime, config, ledger)
    if plan.get("version") != MIGRATION_VERSION:
        return None
    executing_head = _plan_source(plan)
    validate_admission(path, runtime, config, ledger)
    approval = _read(path.parent / "migration-retry-approval.json")
    amendment = _source_amendment(plan)
    supersession_path = path.parent / "migration-retry-supersession.json"
    supersession: dict[str, object] | None = None
    if supersession_path.exists():
        supersession = _load_retry_supersession(path, plan, amendment)
        approval = _object(supersession["approval"])
    if set(approval) != MIGRATION_RETRY_FIELDS:
        raise CampaignError("migration retry approval fields differ")
    body = _migration_retry_body(
        path, explicit_approval=Path(str(approval["explicitApprovalFile"])),
        issued_at=parse_utc(str(approval["issuedAtUtc"])),
        expires_at=parse_utc(str(approval["expiresAtUtc"])),
    )
    if approval != {**body, "authorizationSha256": _hash(body)}:
        raise CampaignError("migration retry approval or original evidence binding differs")
    folder = Path(str(plan["runtimeFile"])).parent
    pause = operator._read_stage_record(folder / "migrate-stage-pause.json", "stage-pause")
    workload = _read(Path(str(plan["workloadRecoveryPlanFile"])))
    image_prefix = f"{runtime['registryName']}.azurecr.io/mobius-api@"
    return {
        "kind": "migration-image-continuation", "operatorSourceHead": executing_head,
        "transitionSha256": (approval["authorizationSha256"] if amendment is None else _hash({
            "retryAuthorizationSha256": approval["authorizationSha256"],
            "operatorSourceAmendmentSha256": amendment["amendmentSha256"],
            "supersessionSha256": (supersession["supersessionSha256"] if supersession else None),
        })),
        "issuedAtUtc": approval["issuedAtUtc"], "expiresAtUtc": approval["expiresAtUtc"],
        "originalBindings": pause["bindings"], "migrationPauseSha256": plan["migrationPauseSha256"],
        "originalAttemptSha256": approval["originalAttemptSha256"],
        "previousImageReference": image_prefix + str(plan["originalImageDigest"]),
        "replacementImageReference": image_prefix + str(approval["imageDigest"]),
        "resolvedWorkloadPauseSha256": _object(workload["filesSha256"])[
            "image-decision-stage-pause.json"
        ],
    }


def validate_migration_retry_window(
    transition: dict[str, object], *, now: datetime | None = None,
) -> None:
    current = datetime.now(UTC) if now is None else now
    if (transition.get("kind") != "migration-image-continuation"
            or not parse_utc(str(transition.get("issuedAtUtc")))
            <= current < parse_utc(str(transition.get("expiresAtUtc")))):
        raise CampaignError("separately approved migration retry dispatch window is closed")


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
    completed_image_plan: Path | None = None,
    prior_jobs_plan: Path | None = None,
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
    if prior_jobs_plan is not None:
        if previous_plan is not None or completed_image_plan is not None:
            raise CampaignError("remaining job predecessors cannot be combined")
        prior_jobs = load_plan(prior_jobs_plan)
        completed_image_plan = Path(str(_object(prior_jobs["completedImagePlan"])["planFile"]))
        record: dict[str, object] = {
            "planFile": str(prior_jobs_plan.resolve()),
            "planFileSha256": _file_hash(prior_jobs_plan),
            "filesSha256": {str(item): _file_hash(item)
                            for item in prior_jobs_plan.resolve().parent.rglob("*")
                            if item.is_file()},
        }
        _validate_prior_jobs(record)
        plan["priorJobUpdateAttempt"] = record
    if completed_image_plan is not None:
        if previous_plan is not None:
            raise CampaignError("independent image continuation predecessors cannot be combined")
        predecessor = load_plan(completed_image_plan)
        plan["priorImageAttempt"] = predecessor["priorImageAttempt"]
        old_folder = completed_image_plan.resolve().parent
        completed: dict[str, object] = {
            "planFile": str(completed_image_plan.resolve()),
            "planFileSha256": _file_hash(completed_image_plan),
            "filesSha256": {str(item): _file_hash(item)
                            for item in old_folder.rglob("*") if item.is_file()},
        }
        _validate_completed_image(completed)
        plan["completedImagePlan"] = completed
    return {**plan, "planSha256": _hash(plan)}


def load_plan(path: Path) -> dict[str, object]:
    plan = _read(_private(path))
    if plan.get("version") == MIGRATION_VERSION:
        return _load_migration_plan(path, plan)
    if plan.get("version") == GRANT_VERSION:
        return _load_grant_plan(path, plan)
    body = {key: value for key, value in plan.items() if key != "planSha256"}
    if (set(plan) not in (FIELDS, FIELDS | {"priorImageAttempt"},
                         FIELDS | {"priorImageAttempt", "completedImagePlan"},
                         FIELDS | {"priorImageAttempt", "completedImagePlan",
                                   "priorJobUpdateAttempt"})
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
    slot = ("image-continuation-r3" if "priorJobUpdateAttempt" in plan else
            "image-continuation-r2" if "completedImagePlan" in plan else
            "image-continuation-r1" if "priorImageAttempt" in plan else "image-continuation")
    if path.resolve() != folder / slot / "plan.json":
        raise CampaignError("continuation plan is outside its exact private attempt slot")
    if "priorImageAttempt" in plan:
        from infra.milestone_7_8.image_continuation_recovery import validate_prior

        validate_prior(_object(plan["priorImageAttempt"]))
    if "completedImagePlan" in plan:
        _validate_completed_image(_object(plan["completedImagePlan"]))
    if "priorJobUpdateAttempt" in plan:
        _validate_prior_jobs(_object(plan["priorJobUpdateAttempt"]))
        prior_jobs = load_plan(Path(str(_object(plan["priorJobUpdateAttempt"])["planFile"])))
        if prior_jobs["completedImagePlan"] != plan["completedImagePlan"]:
            raise CampaignError("remaining jobs changed the original completed image binding")
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


def _validate_completed_image(record: dict[str, object]) -> None:
    from infra.milestone_7_8 import local_image, operator, workload_image_update

    if set(record) != {"planFile", "planFileSha256", "filesSha256"}:
        raise CampaignError("completed image predecessor fields differ")
    path = _private(Path(str(record["planFile"])))
    old = load_plan(path)
    if ("completedImagePlan" in old or old["sourceHead"] !=
            "8d6be93e18923c0377eea5142f61f4ed95568155"
            or old["planSha256"] !=
            "0d4b9d53debc94351237d6206fae9c6058a6906a5df50403603712ba3bb09098"
            or _file_hash(path) != record["planFileSha256"]):
        raise CampaignError("completed image predecessor is not the exact reviewed attempt")
    actual = {str(item): _file_hash(item) for item in path.parent.rglob("*") if item.is_file()}
    if actual != record["filesSha256"]:
        raise CampaignError("completed image or dispatched workload history changed")
    runtime, config = _effective(old)
    completed = _read(path.parent / "local-image/completed.json")
    digest = str(completed["imageDigest"])
    local_image.validate_completion(
        Path(str(old["runtimeFile"])), runtime, config, digest=digest,
        scan_path=path.parent / "local-image/image-scan.json", continuation=path,
    )
    intent = _read(path.parent / "admission-intent.json")
    if (intent.get("planSha256") != old["planSha256"]
            or intent.get("originalLedger") != old["baselineLedger"]
            or intent.get("imageDigest") != digest
            or intent.get("authorizationSha256") != _file_hash(path.parent / "authorization.json")
            or intent.get("scanEvidenceSha256") != operator.load_image_scan_evidence(
                path.parent / "local-image/image-scan.json", digest=digest, runtime=runtime,
            )):
        raise CampaignError("completed image original admission intent differs")
    workload_image_update.inspect_remaining_prefix(
        runtime, config, previous_digest=ORIGINAL_IMAGE, digest=digest,
        prior_output=path.parent / "workload",
        api_readback_directory=path.parent / "api-patch-readback",
    )


def image_evidence_context(path: Path) -> tuple[Path, dict[str, str], CampaignConfig]:
    plan = load_plan(path)
    selected = (Path(str(_object(plan["completedImagePlan"])["planFile"]))
                if "completedImagePlan" in plan else path)
    runtime, config = _effective(load_plan(selected))
    return selected, runtime, config


def _validate_prior_jobs(record: dict[str, object]) -> None:
    from infra.milestone_7_8 import operator, workload_image_update

    if set(record) != {"planFile", "planFileSha256", "filesSha256"}:
        raise CampaignError("prior job update fields differ")
    path = _private(Path(str(record["planFile"])))
    old = load_plan(path)
    if ("priorJobUpdateAttempt" in old or old["sourceHead"] !=
            "3411578555bb89fd44e2d5ebd53400085e6106f5"
            or old["planSha256"] !=
            "05a1a607857f1427862c6b7a7a75e2ec16de4de7b298978ce1e00cc8fdb4ed4a"
            or _file_hash(path) != record["planFileSha256"]):
        raise CampaignError("prior job update is not the exact reviewed attempt")
    actual = {str(item): _file_hash(item) for item in path.parent.rglob("*") if item.is_file()}
    if actual != record["filesSha256"]:
        raise CampaignError("prior job update history changed")
    image_plan, runtime, config = image_evidence_context(path)
    completed = _read(image_plan.parent / "local-image/completed.json")
    intent = _read(path.parent / "admission-intent.json")
    if (intent.get("planSha256") != old["planSha256"]
            or intent.get("originalLedger") != old["baselineLedger"]
            or intent.get("imageDigest") != completed["imageDigest"]
            or intent.get("authorizationSha256") != _file_hash(path.parent / "authorization.json")
            or intent.get("scanEvidenceSha256") != operator.load_image_scan_evidence(
                image_plan.parent / "local-image/image-scan.json",
                digest=str(completed["imageDigest"]), runtime=runtime,
            )):
        raise CampaignError("prior job update admission intent differs")
    workload_image_update.inspect_completed_job_prefix(
        runtime, config, previous_digest=ORIGINAL_IMAGE, digest=str(completed["imageDigest"]),
        prior_output=image_plan.parent / "workload",
        api_readback_directory=image_plan.parent / "api-patch-readback",
        output=path.parent / "workload", source_transition=_workload_transition(old, path.parent),
    )


def _prior_remaining(plan: dict[str, object]) -> tuple[Path, dict[str, object]] | None:
    if "priorJobUpdateAttempt" not in plan:
        return None
    path = Path(str(_object(plan["priorJobUpdateAttempt"])["planFile"]))
    old = load_plan(path)
    return path.parent / "workload", _workload_transition(old, path.parent)


def _effective(plan: dict[str, object]) -> tuple[dict[str, str], CampaignConfig]:
    from infra.milestone_7_8 import operator

    path = Path(str(plan["runtimeFile"]))
    runtime = operator.load_runtime(path)
    original = CampaignConfig.from_json(Path(str(plan["configFile"])), allow_expired=True)
    operator.validate_prepared_bundle(path, runtime, original)
    config, aggregate = (
        _grant_cost(load_plan(Path(str(plan["previousPlanFile"]))), Path(str(plan["costFile"])))
        if plan.get("version") == GRANT_VERSION else
        _migration_cost(Path(str(plan["configFile"])), Path(str(plan["costFile"])))
        if plan.get("version") == MIGRATION_VERSION else _cost(
            Path(str(plan["configFile"])), Path(str(plan["costFile"])),
            path.parent / "budget-continuity.json",
        )
    )
    if str(aggregate) != plan["aggregateEstimateUsd"]:
        raise CampaignError("continuation cumulative cost binding differs")
    return {**runtime, "sourceHead": str(plan["sourceHead"]),
            "canonicalBuildInputSha256": str(plan["canonicalBuildInputSha256"])}, config


def load_context(
    path: Path, runtime_path: Path, config_path: Path, ledger_path: Path, *, operation: str,
) -> tuple[dict[str, str], CampaignConfig, Ledger]:
    plan = load_plan(path)
    if not (operation in CLEANUP_OPERATIONS and plan.get("version") == MIGRATION_VERSION
            and _grant_cleanup_source(plan)):
        _plan_source(plan)
    allowed_operations = (MIGRATION_OPERATIONS - {"bootstrap", "startup"}
                          if plan.get("version") in {MIGRATION_VERSION, GRANT_VERSION}
                          else ALLOWED_OPERATIONS)
    if (operation not in allowed_operations
            or str(runtime_path.resolve()) != plan["runtimeFile"]
            or str(config_path.resolve()) != plan["configFile"]
            or str(ledger_path.resolve()) != plan["ledgerFile"]):
        raise CampaignError("continuation operation, files, or executing source differs")
    runtime, config = _effective(plan)
    if operation == "image" and "completedImagePlan" in plan:
        raise CampaignError("this continuation reuses completed image admission; no image replay")
    raw = _read(ledger_path)
    replaced = (raw.get("previous_image_replacement") is not None
                if plan.get("version") == GRANT_VERSION
                else raw.get("image_replacement") is not None)
    if not replaced:
        if (operation not in CLEANUP_OPERATIONS and (raw != plan["baselineLedger"]
                or _file_hash(ledger_path) != plan["baselineLedgerFileSha256"])):
            raise CampaignError("continuation original ledger changed before admission")
        original = (_effective(load_plan(Path(str(plan["previousPlanFile"]))))[1]
                    if plan.get("version") == GRANT_VERSION
                    else CampaignConfig.from_json(config_path, allow_expired=True))
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
    if (retained.get("imageId") != plan["retainedImageId"]
            or retained.get("imageBuildSourceHead") != plan["imageBuildSourceHead"]
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
            or ledger.phase != (Phase.DATABASE_BOOTSTRAPPED.value
                                if plan.get("version") in {MIGRATION_VERSION, GRANT_VERSION}
                                else Phase.IMAGE_DECIDED.value)
            or (ledger.previous_image_replacement is not None
                if plan.get("version") == GRANT_VERSION
                else ledger.image_replacement is not None)
            or _plan_source(plan) != plan["sourceHead"]
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
    if (plan.get("version") == GRANT_VERSION
            and ledger.previous_image_replacement != baseline.get("image_replacement")):
        raise CampaignError("grant image admission changed its prior replacement record")
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
    image_plan, image_runtime, image_config = image_evidence_context(path)
    local_image.validate_completion(
        Path(str(plan["runtimeFile"])), image_runtime, replace(image_config, image_digest=None),
        digest=str(receipt["imageDigest"]),
        scan_path=image_plan.parent / "local-image/image-scan.json", continuation=image_plan,
    )
    if "completedImagePlan" in plan:
        workload = workload_image_update.validate_remaining_completion(
            image_runtime, image_config, previous_digest=_previous_image(plan),
            digest=str(receipt["imageDigest"]), prior_output=image_plan.parent / "workload",
            api_readback_directory=image_plan.parent / "api-patch-readback",
            output=folder / "workload", source_transition=_workload_transition(plan, folder),
            prior_remaining=_prior_remaining(plan),
        )
    else:
        workload = workload_image_update.validate_completion(
            runtime, config, previous_digest=_previous_image(plan),
            digest=str(receipt["imageDigest"]),
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


def _workload_transition(plan: dict[str, object], folder: Path) -> dict[str, object]:
    old = Path(str(_object(plan["completedImagePlan"])["planFile"])).parent
    return {
        "sourceHead": str(plan["sourceHead"]), "planSha256": str(plan["planSha256"]),
        "authorizationSha256": _file_hash(folder / "authorization.json"),
        "priorAuthorizationFile": str(old / "authorization.json"),
    }


def prerequisite_directory(path: Path, runtime: dict[str, str], config: CampaignConfig,
                           ledger: Ledger) -> Path:
    validate_admission(path, runtime, config, ledger)
    plan = load_plan(path)
    folder = path.resolve().parent / (
        "grant-recovery" if plan.get("version") == GRANT_VERSION else "prerequisites"
    )
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
    image_plan, image_runtime, image_config = image_evidence_context(path)
    if scan_path.resolve() != image_plan.parent / "local-image/image-scan.json":
        raise CampaignError("continuation scan path differs from its completed image attempt")
    if local_image.validate_completion(
        runtime_path, image_runtime, replace(image_config, image_digest=None), digest=digest,
        scan_path=scan_path, continuation=image_plan,
    ) != 0:
        raise CampaignError("corrected retained image must not claim another campaign build")
    scan_sha256 = operator.load_image_scan_evidence(scan_path, digest=digest, runtime=image_runtime)
    if not execute:
        print(json.dumps({"status": "valid", "mutationAuthorized": False,
                          "operation": "image-decision", "baseDeployment": False,
                          "planSha256": plan["planSha256"]}))
        return 0

    def check_authority() -> None:
        if not operator._stage_is_protected(config, runtime, ledger):
            raise operator._ProtectedStageExpired("replacement cleanup protection expired")
        if _plan_source(plan) != plan["sourceHead"]:
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
        if "completedImagePlan" in plan:
            updates = workload_image_update.execute_remaining_jobs(
                image_runtime, image_config, previous_digest=_previous_image(plan), digest=digest,
                prior_output=image_plan.parent / "workload",
                api_readback_directory=image_plan.parent / "api-patch-readback",
                output=folder / "workload", source_transition=_workload_transition(plan, folder),
                prior_remaining=_prior_remaining(plan),
                runner=runner, clock=lambda: datetime.now(UTC), check_authority=check_authority,
            )
        else:
            updates = workload_image_update.execute_updates(
                runtime, config, previous_digest=_previous_image(plan), digest=digest,
                output=folder / "workload", runner=runner, clock=lambda: datetime.now(UTC),
                check_authority=check_authority,
            )
        check_authority()
        if "completedImagePlan" in plan:
            replay = workload_image_update.validate_remaining_completion(
                image_runtime, image_config, previous_digest=_previous_image(plan), digest=digest,
                prior_output=image_plan.parent / "workload",
                api_readback_directory=image_plan.parent / "api-patch-readback",
                output=folder / "workload", source_transition=_workload_transition(plan, folder),
                prior_remaining=_prior_remaining(plan),
            )
        else:
            replay = workload_image_update.validate_completion(
                runtime, config, previous_digest=_previous_image(plan), digest=digest,
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
            at_phase=(Phase.DATABASE_BOOTSTRAPPED
                      if plan.get("version") in {MIGRATION_VERSION, GRANT_VERSION}
                      else Phase.IMAGE_DECIDED),
            grant_recovery=plan.get("version") == GRANT_VERSION,
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
    parser.add_argument("--completed-image-plan", type=Path)
    parser.add_argument("--prior-jobs-plan", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "plan":
            plan = build_plan(
                args.runtime, args.config, args.ledger, cost_path=args.cost,
                retained_image=args.retained_image, previous_plan=args.previous_plan,
                completed_image_plan=args.completed_image_plan,
                prior_jobs_plan=args.prior_jobs_plan,
            )
            slot = (
                "image-continuation-r3" if args.prior_jobs_plan is not None else
                "image-continuation-r2" if args.completed_image_plan is not None else
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
