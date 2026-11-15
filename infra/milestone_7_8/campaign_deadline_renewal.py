"""Journaled pre-expiry replacement of a cleanup schedule, without ARM CAS.

The operator serializes campaign writes. A replacement is staged alongside its
predecessor; one tag update selects it. Unknown writes are never replayed.
No workload may resume from uncertain classification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from infra.milestone_7_8.campaign import (
    ORDER,
    CampaignConfig,
    CampaignError,
    CommandRunner,
    CostItem,
    Ledger,
    Phase,
    parse_utc,
    utc,
)
from infra.milestone_7_8.cleanup_controller import cleanup_authority_sha256
from infra.milestone_7_8.controller import local_source_binding
from infra.milestone_7_8.controller_renewal import _durable_record

DEADLINE_TAG = "mobius.cleanup-deadline-utc"
EXPIRY_TAG = "mobius.expiry"
SCHEDULE_TAG = "mobius.cleanup-schedule"
BINDING_TAG = "mobius.cleanup-binding"
AUTHORITY_TAG = "mobius.cleanup-authority-sha256"
RENEWED_TAG = "mobius.cleanup-renewal-planned-utc"
PARENT_BINDING_TAG = "mobius.cleanup-parent-binding"
PARENT_AUTHORITY_TAG = "mobius.cleanup-parent-authority-sha256"
ACTIVATION_TAGS = frozenset(
    {
        DEADLINE_TAG,
        EXPIRY_TAG,
        SCHEDULE_TAG,
        BINDING_TAG,
        AUTHORITY_TAG,
        RENEWED_TAG,
        PARENT_BINDING_TAG,
        PARENT_AUTHORITY_TAG,
    }
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        b"m7.8/campaign-deadline-renewal/v1\0"
        + json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parameters(config: CampaignConfig, runtime: dict[str, str]) -> dict[str, str]:
    # Import at call time so the existing operator can consume this pure module.
    from infra.milestone_7_8.operator import cleanup_job_parameters

    return cleanup_job_parameters(config, runtime)


def _base(config: CampaignConfig, runtime: dict[str, str]) -> str:
    return (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
        f"automationAccounts/{runtime['automationAccountName']}"
    )


def _tuple(config: CampaignConfig, runtime: dict[str, str]) -> dict[str, Any]:
    base = _base(config, runtime)
    return {
        "scheduleId": f"{base}/schedules/{runtime['scheduleName']}",
        "bindingId": f"{base}/jobSchedules/{runtime['bindingName']}",
        "scheduleName": runtime["scheduleName"],
        "bindingName": runtime["bindingName"],
        "deadlineUtc": config.cleanup_deadline_utc,
        "authoritySha256": cleanup_authority_sha256(config, runtime),
        "parameters": _parameters(config, runtime),
    }


def _schedule_matches(value: object, expected: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    p = value.get("properties", {})
    try:
        return (
            value.get("id", "").casefold() == expected["scheduleId"].casefold()
            and value.get("name") == expected["scheduleName"]
            and p.get("frequency") == "OneTime"
            and p.get("isEnabled") is True
            and parse_utc(p.get("startTime", "")) == parse_utc(expected["deadlineUtc"])
        )
    except (AttributeError, TypeError, ValueError, CampaignError):
        return False


def _binding_matches(value: object, expected: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    p = value.get("properties", {})
    if not isinstance(p, dict):
        return False
    return (
        isinstance(value.get("id"), str)
        and value["id"].casefold() == expected["bindingId"].casefold()
        and p.get("jobScheduleId") == expected["bindingName"]
        and value.get("name", expected["bindingName"]) == expected["bindingName"]
        and p.get("runbook") == {"name": expected["parameters"]["CleanupRunbookName"]}
        and p.get("schedule") == {"name": expected["scheduleName"]}
        and p.get("parameters") == expected["parameters"]
        and p.get("runOn") in (None, "")
    )


def _no_active_cleanup_jobs(snapshot: dict[str, Any]) -> bool:
    jobs = snapshot.get("cleanupJobs")
    return (
        snapshot.get("cleanupJobsComplete") is True
        and isinstance(jobs, list)
        and all(
            isinstance(job, dict)
            and isinstance(job.get("properties"), dict)
            and isinstance(job["properties"].get("status"), str)
            and job["properties"]["status"] in {"Completed", "Failed", "Stopped"}
            for job in jobs
        )
    )


def _snapshot_safe(snapshot: dict[str, Any], *, now: datetime) -> bool:
    """Snapshot must explicitly prove complete cleanup-job inventory and freshness."""
    try:
        observed = parse_utc(snapshot["observedAtUtc"])
        target = snapshot["target"]
        return (
            timedelta(0) <= now - observed <= timedelta(minutes=2)
            and _no_active_cleanup_jobs(snapshot)
            and target.get("properties", {}).get("provisioningState") == "Succeeded"
            and target.get("tags", {}).get("mobius.cleanup-started-utc") is None
        )
    except (KeyError, AttributeError, TypeError, ValueError, CampaignError):
        return False


def build_plan(
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    *,
    new_deadline: str,
    authorized_not_after_utc: str,
    baseline: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Inputs are already locally validated; baseline is a complete live GET set.

    baseline keys: observedAtUtc, target (ARM RG), schedule (ARM schedule),
    binding (exact ARM jobSchedule), cleanupJobs (complete controller job GETs),
    cleanupJobsComplete, controllerAuthorizedUntilUtc. This performs no I/O.
    """
    config.validate(allow_expired=True)
    if (
        (ledger.campaign_id, ledger.generation_id) != (config.campaign_id, config.generation_id)
        or not ORDER.index(Phase.BILLABLE_STARTED)
        <= ORDER.index(Phase(ledger.phase))
        < ORDER.index(Phase.CLEANING)
        or ledger.cleanup_started_utc is not None
        or ledger.cleanup_completed_utc is not None
        or ledger.cleanup_deadline_utc != config.cleanup_deadline_utc
        or ledger.first_billable_mutation_utc is None
    ):
        raise CampaignError("campaign deadline renewal requires an active bound campaign")
    old = parse_utc(config.cleanup_deadline_utc)
    new = parse_utc(new_deadline)
    if re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:00Z", new_deadline) is None:
        raise CampaignError("renewed cleanup deadline must be whole-minute UTC")
    maximum = parse_utc(authorized_not_after_utc)
    if old - now < timedelta(minutes=30):
        raise CampaignError("campaign renewal requires thirty minutes before the old deadline")
    if (
        not old
        < new
        <= maximum
        <= (parse_utc(ledger.first_billable_mutation_utc) + timedelta(hours=config.maximum_hours))
    ):
        raise CampaignError("campaign renewal exceeds the authorized execution window")
    if (
        new + timedelta(hours=1) > parse_utc(runtime["controllerAuthorizedUntilUtc"])
        or baseline.get("controllerAuthorizedUntilUtc") != runtime["controllerAuthorizedUntilUtc"]
    ):
        raise CampaignError("campaign renewal lacks matching controller coverage")
    before = _tuple(config, runtime)
    target_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.target_resource_group}"
    )
    target = baseline.get("target", {})
    if not isinstance(target, dict):
        raise CampaignError("campaign renewal target resource group is absent or unreadable")
    tags = target.get("tags", {})
    required_tags = {
        "mobius.campaign": config.campaign_id,
        "mobius.generation": config.generation_id,
        DEADLINE_TAG: config.cleanup_deadline_utc,
        EXPIRY_TAG: config.cleanup_deadline_utc,
        "mobius.cost-ceiling-cents": str(config.cost_ceiling_cents),
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
    }
    if (
        not _snapshot_safe(baseline, now=now)
        or target.get("id", "").casefold() != target_id.casefold()
        or target.get("name") != config.target_resource_group
        or any(tags.get(k) != v for k, v in required_tags.items())
        or not _schedule_matches(baseline.get("schedule"), before)
        or not _binding_matches(baseline.get("binding"), before)
    ):
        raise CampaignError("campaign renewal baseline is incomplete or drifted")
    pointer = {
        SCHEDULE_TAG: before["scheduleName"],
        BINDING_TAG: before["bindingName"],
        AUTHORITY_TAG: before["authoritySha256"],
    }
    if any(k in tags for k in pointer) and any(tags.get(k) != v for k, v in pointer.items()):
        raise CampaignError("campaign renewal active predecessor differs")
    seed = _hash(
        {"authority": before["authoritySha256"], "deadline": utc(new), "plannedAtUtc": utc(now)}
    )
    after_runtime = dict(runtime)
    after_runtime.update(
        {
            "scheduleName": "m78-deadline-" + seed[:10],
            "bindingName": str(uuid.uuid5(uuid.NAMESPACE_URL, "m7.8/renewal/" + seed)),
            "cleanupAuthorityExpiresUtc": utc(new + timedelta(hours=1)),
        }
    )
    after_config = replace(config, cleanup_deadline_utc=utc(new))
    after = _tuple(after_config, after_runtime)
    activation = {
        DEADLINE_TAG: utc(new),
        EXPIRY_TAG: utc(new),
        SCHEDULE_TAG: after["scheduleName"],
        BINDING_TAG: after["bindingName"],
        AUTHORITY_TAG: after["authoritySha256"],
        RENEWED_TAG: utc(now),
        PARENT_BINDING_TAG: before["bindingName"],
        PARENT_AUTHORITY_TAG: before["authoritySha256"],
    }
    after_tags = {**tags, **activation}
    if len(after_tags) > 50 or any(len(v) > 256 for v in activation.values()):
        raise CampaignError("campaign renewal tags exceed Azure limits")
    api = runtime["automationApiVersion"]
    plan: dict[str, Any] = {
        "version": "m7.8-campaign-deadline-renewal-plan-v1",
        "model": "pre-expiry-single-writer-no-CAS",
        "createdAtUtc": utc(now),
        "authorizedNotAfterUtc": authorized_not_after_utc,
        "before": before,
        "after": after,
        "beforeConfig": asdict(config),
        "beforeRuntime": dict(runtime),
        "beforeLedger": _ledger_snapshot(ledger),
        "baseline": copy.deepcopy(baseline),
        "beforeConfigSha256": _hash(asdict(config)),
        "beforeRuntimeSha256": _hash(runtime),
        "beforeLedgerSha256": _hash(_ledger_snapshot(ledger)),
        "baselineSha256": _hash(baseline),
        "afterConfig": asdict(after_config),
        "afterRuntime": after_runtime,
        "targetId": target_id,
        "targetName": config.target_resource_group,
        "beforeTags": copy.deepcopy(tags),
        "afterTags": after_tags,
        "activationTags": activation,
        "controllerAuthorizedUntilUtc": runtime["controllerAuthorizedUntilUtc"],
        "stageRequests": [
            {
                "method": "PUT",
                "url": "https://management.azure.com" + after["scheduleId"] + "?api-version=" + api,
                "body": {
                    "properties": {
                        "description": "Replacement cleanup; predecessor retained until activation",
                        "frequency": "OneTime",
                        "interval": 1,
                        "isEnabled": True,
                        "startTime": utc(new),
                        "timeZone": "Etc/UTC",
                    }
                },
            },
            {
                "method": "PUT",
                "url": "https://management.azure.com" + after["bindingId"] + "?api-version=" + api,
                "body": {
                    "properties": {
                        "parameters": after["parameters"],
                        "runbook": {"name": runtime["runbookName"]},
                        "schedule": {"name": after["scheduleName"]},
                    }
                },
            },
        ],
        "activationRequest": {
            "method": "PATCH",
            "url": "https://management.azure.com"
            + target_id
            + "/providers/Microsoft.Resources/tags/default?api-version=2021-04-01",
            "body": {"operation": "Merge", "properties": {"tags": activation}},
        },
    }
    plan["planSha256"] = _hash(plan)
    return json.loads(json.dumps(plan))


def classify_readback(plan: dict[str, Any], snapshot: dict[str, Any], *, now: datetime) -> str:
    """Classify GET results, never infer a failed/absent mutation from a timeout.

    Snapshot includes the baseline keys plus newSchedule/newBinding; None means a
    confirmed absence from complete inventory, not an unavailable response. Every outcome must
    have an entry in readStatus with value 'found' or 'absent'.
    """
    unsigned = {k: v for k, v in plan.items() if k != "planSha256"}
    if plan.get("planSha256") != _hash(unsigned):
        raise CampaignError("campaign renewal plan hash differs")
    if (
        not _snapshot_safe(snapshot, now=now)
        or now >= parse_utc(plan["before"]["deadlineUtc"])
        or snapshot.get("controllerAuthorizedUntilUtc") != plan["controllerAuthorizedUntilUtc"]
    ):
        return "uncertain"
    target = snapshot["target"]
    if (
        target.get("id", "").casefold() != plan["targetId"].casefold()
        or target.get("name") != plan["targetName"]
    ):
        return "uncertain"
    status = snapshot.get("readStatus", {})
    if any(status.get(key) != "found" for key in ("target", "schedule", "binding")):
        return "uncertain"
    if not _schedule_matches(snapshot.get("schedule"), plan["before"]) or not _binding_matches(
        snapshot.get("binding"), plan["before"]
    ):
        return "uncertain"
    matches: list[bool] = []
    for key, check in (("newSchedule", _schedule_matches), ("newBinding", _binding_matches)):
        if status.get(key) == "absent" and snapshot.get(key) is None:
            matches.append(False)
        elif status.get(key) == "found" and check(snapshot.get(key), plan["after"]):
            matches.append(True)
        else:
            return "uncertain"
    tags = target.get("tags")
    if tags == plan["afterTags"] and all(matches):
        return "new-active"
    if tags == plan["beforeTags"]:
        if all(matches):
            return "new-staged"
        if matches in ([False, False], [True, False]):
            return "old-active"
    return "uncertain"


def activation_request(
    plan: dict[str, Any], snapshot: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Only release the activation request after fresh, complete staging proof."""
    if (
        parse_utc(plan["before"]["deadlineUtc"]) - now < timedelta(minutes=30)
        or classify_readback(plan, snapshot, now=now) != "new-staged"
    ):
        raise CampaignError("campaign renewal activation is not safely staged before expiry")
    return copy.deepcopy(plan["activationRequest"])


def config_from_snapshot(value: dict[str, Any]) -> CampaignConfig:
    fields = copy.deepcopy(value)
    fields["resource_items"] = tuple(CostItem(**item) for item in fields["resource_items"])
    return CampaignConfig(**fields)


def _ledger_snapshot(ledger: Ledger) -> dict[str, Any]:
    # Omit newly introduced empty history so immutable pre-feature plan hashes replay.
    snapshot = asdict(ledger)
    if not ledger.readiness_image_replacements:
        del snapshot["readiness_image_replacements"]
    return snapshot


def validate_plan(plan: dict[str, Any]) -> None:
    """Rebuild requests from their exact original inputs, not a caller-supplied URL."""
    try:
        rebuilt = build_plan(
            config_from_snapshot(plan["beforeConfig"]),
            plan["beforeRuntime"],
            Ledger(**plan["beforeLedger"]),
            new_deadline=plan["after"]["deadlineUtc"],
            authorized_not_after_utc=plan["authorizedNotAfterUtc"],
            baseline=plan["baseline"],
            now=parse_utc(plan["createdAtUtc"]),
        )
        if rebuilt["planSha256"] != plan["planSha256"] or _hash(rebuilt) != _hash(plan):
            raise CampaignError("campaign renewal plan differs from its bound inputs")
    except (KeyError, TypeError, ValueError) as exc:
        raise CampaignError("campaign renewal plan is incomplete") from exc


COMPLETION_FIELDS = frozenset(
    {
        "version",
        "planSha256",
        "beforeDeadlineUtc",
        "afterDeadlineUtc",
        "beforeCleanupArmSha256",
        "afterCleanupArmSha256",
        "completedAtUtc",
        "oldAuthorizationSha256",
        "newAuthorizationSha256",
        "journalSha256",
        "snapshotSha256",
        "receiptSha256",
    }
)


def validate_completion(receipt: dict[str, Any]) -> None:
    if (
        not isinstance(receipt, dict)
        or set(receipt) != COMPLETION_FIELDS
        or receipt.get("version") != "m7.8-campaign-deadline-renewal-completion-v1"
        or any(not isinstance(v, str) for v in receipt.values())
        or any(
            re.fullmatch(r"[a-f0-9]{64}", receipt[k]) is None
            for k in COMPLETION_FIELDS
            if k.endswith("Sha256")
        )
        or receipt["receiptSha256"]
        != _hash({k: v for k, v in receipt.items() if k != "receiptSha256"})
        or not parse_utc(receipt["completedAtUtc"])
        < parse_utc(receipt["beforeDeadlineUtc"])
        < parse_utc(receipt["afterDeadlineUtc"])
    ):
        raise CampaignError("campaign renewal completion is invalid")


def completion_record(
    plan: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    now: datetime,
    old_authorization_sha256: str,
    new_authorization_sha256: str,
    journal: dict[str, Any],
    after_cleanup_arm_sha256: str,
) -> dict[str, str]:
    validate_plan(plan)
    if classify_readback(plan, snapshot, now=now) != "new-active":
        raise CampaignError("campaign renewal activation has not been proved before expiry")
    receipt = {
        "version": "m7.8-campaign-deadline-renewal-completion-v1",
        "planSha256": plan["planSha256"],
        "beforeDeadlineUtc": plan["before"]["deadlineUtc"],
        "afterDeadlineUtc": plan["after"]["deadlineUtc"],
        "beforeCleanupArmSha256": plan["beforeLedger"]["cleanup_arm_evidence_sha256"],
        "afterCleanupArmSha256": after_cleanup_arm_sha256,
        "completedAtUtc": utc(now),
        "oldAuthorizationSha256": old_authorization_sha256,
        "newAuthorizationSha256": new_authorization_sha256,
        "journalSha256": _hash(journal),
        "snapshotSha256": _hash(snapshot),
    }
    receipt["receiptSha256"] = _hash(receipt)
    validate_completion(receipt)
    return receipt


EVIDENCE_FIELDS = {"deadlineRenewalEvidenceFile", "deadlineRenewalEvidenceSha256"}


def _configuration_binding(value: dict[str, Any]) -> str:
    # Image admission and ledger transitions bind the digest independently. Renewal
    # preserves the exact snapshot but owns every configuration field except image.
    return _hash({key: item for key, item in value.items() if key != "image_digest"})


def load_evidence(runtime: dict[str, str]) -> dict[str, Any] | None:
    """Validate every immutable renewal and its exact original/new binding."""
    if not EVIDENCE_FIELDS.intersection(runtime):
        return None
    if not runtime.keys() >= EVIDENCE_FIELDS:
        raise CampaignError("campaign renewal evidence binding is incomplete")
    path = Path(runtime["deadlineRenewalEvidenceFile"])
    if path.resolve().parent != Path(runtime["campaignParametersFile"]).resolve().parent:
        raise CampaignError("campaign renewal evidence escaped its private generation")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != runtime["deadlineRenewalEvidenceSha256"]:
        raise CampaignError("campaign renewal evidence file hash differs")
    value = json.loads(data)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "records"}
        or (
            value["version"] != "m7.8-campaign-deadline-renewal-evidence-v1"
            or not isinstance(value["records"], list)
            or not value["records"]
        )
    ):
        raise CampaignError("campaign renewal evidence is malformed")
    prior = None
    retained = []
    origin_runtime = value["records"][0]["plan"]["beforeRuntime"]
    origin_config = config_from_snapshot(value["records"][0]["plan"]["beforeConfig"])
    for record in value["records"]:
        if set(record) != {"plan", "completion", "snapshot", "journal", "cleanupReadback"}:
            raise CampaignError("campaign renewal evidence record is incomplete")
        plan, receipt = record["plan"], record["completion"]
        validate_plan(plan)
        validate_completion(receipt)
        retained.append(plan["before"])
        from infra.milestone_7_8.operator import validate_cleanup_readback

        actual_arm = validate_cleanup_readback(
            record["cleanupReadback"],
            config_from_snapshot(plan["afterConfig"]),
            plan["afterRuntime"],
            renewal_context=(origin_runtime, origin_config, retained),
        )
        if actual_arm != receipt["afterCleanupArmSha256"]:
            raise CampaignError("campaign renewal cleanup protection proof differs")
        if receipt != completion_record(
            plan,
            record["snapshot"],
            now=parse_utc(receipt["completedAtUtc"]),
            old_authorization_sha256=receipt["oldAuthorizationSha256"],
            new_authorization_sha256=receipt["newAuthorizationSha256"],
            journal=record["journal"],
            after_cleanup_arm_sha256=receipt["afterCleanupArmSha256"],
        ):
            raise CampaignError("campaign renewal completion evidence differs")
        if prior is not None and (
            _configuration_binding(plan["beforeConfig"])
            != _configuration_binding(prior["plan"]["afterConfig"])
            or {k: v for k, v in plan["beforeRuntime"].items() if k not in EVIDENCE_FIELDS}
            != {k: v for k, v in prior["plan"]["afterRuntime"].items() if k not in EVIDENCE_FIELDS}
            or plan["before"]["authoritySha256"] != prior["plan"]["after"]["authoritySha256"]
            or receipt["beforeCleanupArmSha256"] != prior["completion"]["afterCleanupArmSha256"]
        ):
            raise CampaignError("campaign renewal evidence chain is discontinuous")
        prior = record
    assert prior is not None
    expected = {k: v for k, v in prior["plan"]["afterRuntime"].items() if k not in EVIDENCE_FIELDS}
    if {k: v for k, v in runtime.items() if k not in EVIDENCE_FIELDS} != expected:
        raise CampaignError("campaign renewal active runtime was substituted")
    return value


def origin_context(
    runtime: dict[str, str],
    config: CampaignConfig,
) -> tuple[dict[str, str], CampaignConfig]:
    evidence = load_evidence(runtime)
    if evidence is None:
        return runtime, config
    records = evidence["records"]
    config.validate(allow_expired=True)
    if _configuration_binding(asdict(config)) != _configuration_binding(
        records[-1]["plan"]["afterConfig"]
    ):
        raise CampaignError("campaign renewal active configuration was substituted")
    first = records[0]["plan"]
    return first["beforeRuntime"], config_from_snapshot(first["beforeConfig"])


def retained_tuples(runtime: dict[str, str]) -> list[dict[str, Any]]:
    evidence = load_evidence(runtime)
    return [] if evidence is None else [r["plan"]["before"] for r in evidence["records"]]


def deployment_overrides(config: CampaignConfig, runtime: dict[str, str]) -> tuple[str, ...]:
    """Keep ARM deployments from restoring the immutable pre-renewal parameters."""
    evidence = load_evidence(runtime)
    if evidence is None:
        return ()
    plan = evidence["records"][-1]["plan"]
    if _configuration_binding(asdict(config)) != _configuration_binding(plan["afterConfig"]):
        raise CampaignError("campaign renewal active configuration was substituted")
    return (
        f"cleanupDeadlineUtc={config.cleanup_deadline_utc}",
        "lifecycleTags=" + json.dumps(plan["afterTags"], sort_keys=True, separators=(",", ":")),
    )


def validate_ledger_binding(runtime: dict[str, str], ledger: Ledger) -> None:
    evidence = load_evidence(runtime)
    receipts = [] if evidence is None else [r["completion"] for r in evidence["records"]]
    if ledger.deadline_renewals != receipts:
        raise CampaignError("campaign renewal ledger and runtime evidence disagree")


def execute_plan(
    plan: dict[str, Any],
    *,
    old_authorization: Path,
    new_authorization: Path,
    directory: Path,
    runner: CommandRunner,
    collect_snapshot: Callable[[], dict[str, Any]],
    collect_cleanup_readback: Callable[[], list[dict[str, object]]],
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    """Journal exactly two staging PUTs and one activation PATCH, with GET gates.

    The caller supplies the existing authenticated collectors for this exact
    plan. Both collectors must perform fresh reads, never replay saved output.
    No mutation is repeated after an intent exists. A restarted call can skip
    mutations freshly proved applied; an absent/unknown result after an intent
    requires separate authoritative reconciliation before any corrective attempt.
    """
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization
    from infra.milestone_7_8.operator import validate_cleanup_readback

    validate_plan(plan)
    before_config = config_from_snapshot(plan["beforeConfig"])
    after_config = config_from_snapshot(plan["afterConfig"])
    before_runtime, after_runtime = plan["beforeRuntime"], plan["afterRuntime"]
    directory.mkdir(parents=False, exist_ok=True)
    context = {"planSha256": plan["planSha256"]}
    context_file = directory / "context.json"
    if context_file.exists():
        if json.loads(context_file.read_text()) != context:
            raise CampaignError("campaign renewal journal belongs to another plan")
    else:
        _durable_record(context_file, context)

    def boundary(operation: str, *, active: bool) -> str:
        now = clock()
        if now >= parse_utc(plan["before"]["deadlineUtc"]):
            raise CampaignError("campaign renewal cannot dispatch or adopt after the old deadline")
        head, script = local_source_binding()
        if head != before_runtime["sourceHead"] or script != before_runtime["cleanupScriptSha256"]:
            raise CampaignError("campaign renewal source binding differs")
        config, runtime, authorization = (
            (after_config, after_runtime, new_authorization)
            if active
            else (before_config, before_runtime, old_authorization)
        )
        raw = json.loads(authorization.read_text())
        if raw.get("version") != "m7.8-execution-authorization-v6":
            raise CampaignError("campaign renewal requires fresh v6 authorizations")
        return load_execution_authorization(
            authorization,
            config=config,
            runtime=runtime,
            operation=operation,
            now=now,
        ).authorization_sha256

    def capture() -> dict[str, Any]:
        boundary("cleanup-verify", active=False)
        result = collect_snapshot()
        index = len(list(directory.glob("read-*.json")))
        _durable_record(directory / f"read-{index:04d}.json", result)
        return result

    old_hash = boundary("cleanup-arm", active=False)
    new_hash = boundary("cleanup-arm", active=True)
    requests = [*plan["stageRequests"], plan["activationRequest"]]
    for index, request in enumerate(requests):
        snapshot = capture()
        state = classify_readback(plan, snapshot, now=clock())
        if state == "uncertain":
            raise CampaignError("campaign renewal readback is uncertain; no write dispatched")
        applied = (
            snapshot.get("readStatus", {}).get("newSchedule") == "found"
            if index == 0
            else snapshot.get("readStatus", {}).get("newBinding") == "found"
            if index == 1
            else state == "new-active"
        )
        if applied:
            continue
        intent_path = directory / f"write-{index:02d}-intent.json"
        if intent_path.exists():
            raise CampaignError("campaign renewal prior dispatch is unresolved; refusing replay")
        if index == 2:
            activation_request(plan, snapshot, now=clock())
        elif parse_utc(plan["before"]["deadlineUtc"]) - clock() < timedelta(minutes=30):
            raise CampaignError("campaign renewal staging margin is exhausted")
        authorization_hash = boundary("cleanup-arm", active=index == 2)
        _durable_record(
            intent_path,
            {
                "request": request,
                "requestSha256": _hash(request),
                "authorizationSha256": authorization_hash,
                "intentAtUtc": utc(clock()),
            },
        )
        command = (
            "az",
            "rest",
            "--method",
            request["method"].lower(),
            "--url",
            request["url"],
            "--body",
            json.dumps(request["body"], separators=(",", ":")),
            "--subscription",
            before_runtime["subscriptionId"],
            "--output",
            "json",
        )
        boundary("cleanup-arm", active=index == 2)
        try:
            response = runner.run(command)
        except Exception as exc:
            response = {"outcome": "indeterminate", "errorClass": type(exc).__name__}
        _durable_record(directory / f"write-{index:02d}-response.json", response)
        # Even a CLI success is not a completion proof. Inspect the same resource.
        observed = capture()
        state = classify_readback(plan, observed, now=clock())
        expected = (
            observed.get("readStatus", {}).get("newSchedule") == "found"
            if index == 0
            else state in {"new-staged", "new-active"}
            if index == 1
            else state == "new-active"
        )
        if state == "uncertain" or not expected:
            raise CampaignError("campaign renewal dispatch outcome requires reconciliation")

    boundary("cleanup-verify", active=True)
    cleanup_results = collect_cleanup_readback()
    origin_runtime, origin_config = origin_context(before_runtime, before_config)
    retained = [*retained_tuples(before_runtime), plan["before"]]
    arm_hash = validate_cleanup_readback(
        cleanup_results,
        after_config,
        after_runtime,
        renewal_context=(origin_runtime, origin_config, retained),
    )
    snapshot = capture()
    journal = {
        "planSha256": plan["planSha256"],
        "filesSha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.glob("*.json"))
            if p.name != "completed.json"
        },
    }
    receipt = completion_record(
        plan,
        snapshot,
        now=clock(),
        old_authorization_sha256=old_hash,
        new_authorization_sha256=new_hash,
        journal=journal,
        after_cleanup_arm_sha256=arm_hash,
    )
    record = {
        "plan": plan,
        "completion": receipt,
        "snapshot": snapshot,
        "journal": journal,
        "cleanupReadback": cleanup_results,
    }
    completed = directory / "completed.json"
    if completed.exists():
        # A completed operation is reused verbatim rather than relabelled with a new time.
        previous = json.loads(completed.read_text())
        validate_completion(previous["completion"])
        if previous["plan"]["planSha256"] != plan["planSha256"]:
            raise CampaignError("completed campaign renewal belongs to another plan")
        return previous
    _durable_record(completed, record)
    return record


def adopt_completion(
    record: dict[str, Any],
    *,
    config_path: Path,
    runtime_path: Path,
    ledger_path: Path,
    output_prefix: str,
    now: datetime | None = None,
) -> dict[str, Path]:
    """Write new sibling inputs; original config/runtime/ledger are never overwritten."""
    from infra.milestone_7_8.campaign import load_ledger
    from infra.milestone_7_8.operator import load_runtime, validate_prepared_bundle

    if re.fullmatch(r"[a-z][a-z0-9-]{1,63}", output_prefix) is None:
        raise CampaignError("campaign renewal output prefix is invalid")
    directory = runtime_path.resolve().parent
    if config_path.resolve().parent != directory or ledger_path.resolve().parent != directory:
        raise CampaignError("campaign renewal input files must share their private generation")
    plan = record["plan"]
    validate_plan(plan)
    if (now or datetime.now(UTC)) >= parse_utc(plan["after"]["deadlineUtc"]):
        raise CampaignError("campaign renewal adoption execution window has expired")
    config = CampaignConfig.from_json(config_path, allow_expired=True)
    runtime = load_runtime(runtime_path)
    ledger = load_ledger(ledger_path, config)
    validate_prepared_bundle(runtime_path, runtime, config)
    if (
        _hash(asdict(config)) != plan["beforeConfigSha256"]
        or _hash(runtime) != plan["beforeRuntimeSha256"]
        or _hash(_ledger_snapshot(ledger)) != plan["beforeLedgerSha256"]
    ):
        raise CampaignError("campaign renewal adoption inputs changed after planning")
    old = load_evidence(runtime)
    evidence = {
        "version": "m7.8-campaign-deadline-renewal-evidence-v1",
        "records": [*(old["records"] if old else []), record],
    }
    paths = {
        name: directory / f"{output_prefix}-{name}.json"
        for name in ("evidence", "runtime", "config", "ledger")
    }

    def write(path: Path, value: object) -> None:
        if path.exists():
            if _hash(json.loads(path.read_text())) != _hash(value):
                raise CampaignError("campaign renewal adoption output already differs")
        else:
            _durable_record(path, value)

    write(paths["evidence"], evidence)
    renewed_runtime = {
        **plan["afterRuntime"],
        "deadlineRenewalEvidenceFile": str(paths["evidence"]),
        "deadlineRenewalEvidenceSha256": hashlib.sha256(paths["evidence"].read_bytes()).hexdigest(),
    }
    # Full proof validation occurs before the new runtime/config/ledger are exposed.
    load_evidence(renewed_runtime)
    raw_config = json.loads(config_path.read_text())
    raw_config["cleanupDeadlineUtc"] = plan["after"]["deadlineUtc"]
    ledger.record_deadline_renewal(record["completion"])
    raw_ledger = _ledger_snapshot(ledger)
    for key in ("image_replacement", "previous_image_replacement"):
        if raw_ledger[key] is None:
            del raw_ledger[key]
    write(paths["config"], raw_config)
    write(paths["runtime"], renewed_runtime)
    write(paths["ledger"], raw_ledger)
    renewed_config = CampaignConfig.from_json(paths["config"], allow_expired=True)
    validate_prepared_bundle(paths["runtime"], renewed_runtime, renewed_config)
    validate_ledger_binding(renewed_runtime, load_ledger(paths["ledger"], renewed_config))
    return paths


def collect_live_snapshot(
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    runner: CommandRunner,
    clock: Callable[[], datetime],
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use complete inventories to distinguish absence from failed exact GETs.

    Collection pagination is deliberately rejected. Every selected schedule and
    binding is fetched by its scoped ID; list summaries never prove parameters.
    The start timestamp bounds the age of the entire sequential read set.
    """
    from infra.milestone_7_8.operator import (
        _collection,
        _json_result,
        _validate_controller_tags,
    )

    started = clock()
    subscription = runtime["subscriptionId"]
    base = "https://management.azure.com" + _base(config, runtime)
    api = runtime["automationApiVersion"]

    def run(command: tuple[str, ...]) -> Any:
        result = runner.run((*command, "--subscription", subscription, "--output", "json"))
        if result.get("exitCode") != 0:
            raise CampaignError("campaign renewal GET failed; absence is not established")
        return _json_result(result)

    def get(url: str) -> Any:
        return run(("az", "rest", "--method", "get", "--url", url))

    target_exists = run(("az", "group", "exists", "--name", config.target_resource_group))
    if not isinstance(target_exists, bool):
        raise CampaignError("campaign renewal target existence response is malformed")
    target_id = f"/subscriptions/{subscription}/resourceGroups/{config.target_resource_group}"
    target = (
        get("https://management.azure.com" + target_id + "?api-version=2024-03-01")
        if target_exists
        else None
    )
    account = get(base + "?api-version=" + api)
    if not isinstance(account, dict) or str(account.get("id", "")).casefold() != (
        _base(config, runtime).casefold()
    ):
        raise CampaignError("campaign renewal controller account scope differs")
    _validate_controller_tags(account.get("tags"), config=config, runtime=runtime)
    inventories = {
        kind: _collection(get(base + "/" + kind + "?api-version=" + api), label=kind)
        for kind in ("schedules", "jobSchedules", "jobs")
    }
    cleanup_jobs = []
    for item in inventories["jobs"]:
        if not isinstance(item, dict) or not str(item.get("id", "")).casefold().startswith(
            (_base(config, runtime) + "/jobs/").casefold()
        ):
            raise CampaignError("campaign renewal job inventory scope is malformed")
        job = get("https://management.azure.com" + item["id"] + "?api-version=" + api)
        if not isinstance(job, dict) or str(job.get("id", "")).casefold() != item["id"].casefold():
            raise CampaignError("campaign renewal job detail is malformed")
        properties = job.get("properties", {})
        if not isinstance(properties, dict):
            raise CampaignError("campaign renewal job properties are malformed")
        # Preserve every exact GET, including terminal jobs with missing parameters.
        # Safety classification accepts only explicit terminal execution states.
        cleanup_jobs.append(job)
    observed: dict[str, Any] = {
        "observedAtUtc": utc(started),
        "target": target,
        "readStatus": {"target": "found" if target_exists else "absent"},
        "cleanupJobs": cleanup_jobs,
        "cleanupJobsComplete": True,
        "controllerAuthorizedUntilUtc": account["tags"].get(
            "mobius.controller-authorized-until-utc"
        ),
    }
    tuples = [("", _tuple(config, runtime))]
    if plan is not None:
        validate_plan(plan)
        if _hash(runtime) != plan["beforeRuntimeSha256"] or (
            _hash(asdict(config)) != plan["beforeConfigSha256"]
        ):
            raise CampaignError("campaign renewal collector input scope differs")
        tuples.append(("new", plan["after"]))
    for prefix, binding in tuples:
        for kind, member in (("schedules", "schedule"), ("jobSchedules", "binding")):
            key = prefix + member.capitalize() if prefix else member
            expected_id = binding[member + "Id"]
            items = inventories[kind]
            if any(
                not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in items
            ):
                raise CampaignError("campaign renewal inventory contains malformed IDs")
            matches = [item for item in items if item["id"].casefold() == expected_id.casefold()]
            if len(matches) > 1:
                raise CampaignError("campaign renewal inventory contains duplicate IDs")
            observed[key] = (
                get("https://management.azure.com" + expected_id + "?api-version=" + api)
                if matches
                else None
            )
            observed["readStatus"][key] = "found" if matches else "absent"
    if clock() - started > timedelta(minutes=2):
        raise CampaignError("campaign renewal snapshot collection exceeded freshness bound")
    return observed


def collect_live_cleanup_readback(
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    runner: CommandRunner,
) -> list[dict[str, object]]:
    from infra.milestone_7_8.operator import command_plan

    commands = command_plan("cleanup-verify", config, runtime)
    results = []
    for command in commands:
        result = runner.run((*command, "--subscription", runtime["subscriptionId"]))
        if result.get("exitCode") != 0:
            raise CampaignError("campaign renewal cleanup proof GET failed")
        results.append(result)
    return results


def discard_staged_plan(
    plan: dict[str, Any],
    *,
    authorization: Path,
    directory: Path,
    runner: CommandRunner,
    clock: Callable[[], datetime],
    collect_snapshot: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Remove only a proven unused replacement, or residue after target absence.

    This explicit path is required for an interrupted journal that never produced
    adopted runtime evidence. It never deletes a replacement selected by a live
    target. A target absent in a fresh successful exists GET has no workload left
    for either schedule to protect.
    """
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization

    validate_plan(plan)
    config = config_from_snapshot(plan["beforeConfig"])
    runtime = plan["beforeRuntime"]
    directory.mkdir(parents=False, exist_ok=True)

    def authorize() -> None:
        head, script = local_source_binding()
        if head != runtime["sourceHead"] or script != runtime["cleanupScriptSha256"]:
            raise CampaignError("campaign renewal discard source binding differs")
        load_execution_authorization(
            authorization,
            config=config,
            runtime=runtime,
            operation="cleanup-disarm",
            now=clock(),
        )

    def read() -> dict[str, Any]:
        authorize()
        result = collect_snapshot()
        stamp = parse_utc(result.get("observedAtUtc", ""))
        if stamp > clock() or clock() - stamp > timedelta(minutes=2):
            raise CampaignError("campaign renewal discard snapshot is stale")
        statuses = result.get("readStatus", {})
        absent = statuses.get("target") == "absent" and result.get("target") is None
        if absent:
            if not _no_active_cleanup_jobs(result):
                raise CampaignError("campaign renewal discard has unresolved cleanup jobs")
        elif classify_readback(plan, result, now=clock()) not in {"old-active", "new-staged"}:
            raise CampaignError("campaign renewal replacement is active or uncertain")
        for key, check in (("newBinding", _binding_matches), ("newSchedule", _schedule_matches)):
            if statuses.get(key) == "found":
                if not check(result.get(key), plan["after"]):
                    raise CampaignError("campaign renewal discard resource differs")
            elif statuses.get(key) != "absent" or result.get(key) is not None:
                raise CampaignError("campaign renewal discard resource existence is unknown")
        return result

    for key, member in (("newBinding", "bindingId"), ("newSchedule", "scheduleId")):
        before = read()
        if before["readStatus"][key] == "absent":
            continue
        intent = directory / f"discard-{key}-intent.json"
        if intent.exists():
            raise CampaignError("campaign renewal discard is unresolved; refusing replay")
        command = (
            "az",
            "rest",
            "--method",
            "delete",
            "--url",
            "https://management.azure.com"
            + plan["after"][member]
            + "?api-version="
            + runtime["automationApiVersion"],
            "--subscription",
            runtime["subscriptionId"],
            "--output",
            "json",
        )
        _durable_record(
            intent,
            {
                "planSha256": plan["planSha256"],
                "intentAtUtc": utc(clock()),
                "resourceId": plan["after"][member],
            },
        )
        authorize()
        try:
            response = runner.run(command)
        except Exception as exc:
            response = {"outcome": "indeterminate", "errorClass": type(exc).__name__}
        _durable_record(directory / f"discard-{key}-response.json", response)
        after = read()
        if after["readStatus"][key] != "absent":
            raise CampaignError("campaign renewal discard outcome requires reconciliation")
    final = read()
    record = {"planSha256": plan["planSha256"], "observedAtUtc": utc(clock()), "snapshot": final}
    path = directory / "discard-completed.json"
    if not path.exists():
        _durable_record(path, record)
    return json.loads(path.read_text())


def main() -> int:
    """Small operator entry point; all records stay in the ignored runtime tree."""
    import argparse
    import sys

    from infra.milestone_7_8.campaign import SubprocessRunner, load_ledger
    from infra.milestone_7_8.cleanup_controller import load_execution_authorization
    from infra.milestone_7_8.controller import REPOSITORY_ROOT
    from infra.milestone_7_8.operator import (
        load_runtime,
        validate_cleanup_readback,
        validate_prepared_bundle,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "execute", "adopt", "discard-staged"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--old-authorization", type=Path)
    parser.add_argument("--new-authorization", type=Path)
    parser.add_argument("--new-deadline")
    parser.add_argument("--authorized-not-after")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--completion", type=Path)
    parser.add_argument("--output-prefix")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        private = (REPOSITORY_ROOT / ".runtime").resolve()
        for path in (
            args.config,
            args.runtime,
            args.ledger,
            args.plan,
            args.old_authorization,
            args.new_authorization,
            args.output,
            args.journal,
            args.completion,
        ):
            if path is not None and (
                not path.resolve().is_relative_to(private) or path.resolve() == private
            ):
                raise CampaignError("campaign renewal paths must remain in private runtime")
        if args.operation == "adopt":
            if args.completion is None or args.output_prefix is None:
                raise CampaignError("campaign renewal adoption inputs are incomplete")
            paths = adopt_completion(
                json.loads(args.completion.read_text()),
                config_path=args.config,
                runtime_path=args.runtime,
                ledger_path=args.ledger,
                output_prefix=args.output_prefix,
            )
            print(json.dumps({"status": "adopted", "paths": {k: str(v) for k, v in paths.items()}}))
            return 0
        config = CampaignConfig.from_json(args.config, allow_expired=True)
        runtime = load_runtime(args.runtime)
        ledger = load_ledger(args.ledger, config)
        validate_prepared_bundle(args.runtime, runtime, config)
        validate_ledger_binding(runtime, ledger)
        head, script = local_source_binding()
        if head != runtime["sourceHead"] or script != runtime["cleanupScriptSha256"]:
            raise CampaignError("campaign renewal source binding differs")
        if args.old_authorization is None:
            raise CampaignError("campaign renewal requires the active campaign authorization")
        if json.loads(args.old_authorization.read_text()).get("version") != (
            "m7.8-execution-authorization-v6"
        ):
            raise CampaignError("campaign renewal requires v6 authorization")
        load_execution_authorization(
            args.old_authorization,
            config=config,
            runtime=runtime,
            operation="cleanup-verify" if args.operation != "discard-staged" else "cleanup-disarm",
            now=datetime.now(UTC),
        )
        runner = SubprocessRunner(timeout_seconds=60)

        def clock() -> datetime:
            return datetime.now(UTC)

        if args.operation == "plan":
            if (
                args.output is None
                or args.new_deadline is None
                or args.authorized_not_after is None
            ):
                raise CampaignError("campaign renewal planning inputs are incomplete")
            readback = collect_live_cleanup_readback(config, runtime, runner=runner)
            if (
                validate_cleanup_readback(readback, config, runtime)
                != ledger.cleanup_arm_evidence_sha256
            ):
                raise CampaignError("campaign renewal active cleanup proof differs from ledger")
            baseline = collect_live_snapshot(config, runtime, runner=runner, clock=clock)
            plan = build_plan(
                config,
                runtime,
                ledger,
                new_deadline=args.new_deadline,
                authorized_not_after_utc=args.authorized_not_after,
                baseline=baseline,
                now=clock(),
            )
            _durable_record(args.output, plan)
            print(json.dumps({"status": "planned", "planSha256": plan["planSha256"]}))
            return 0
        if not args.execute or args.plan is None or args.journal is None:
            raise CampaignError("campaign renewal dispatch requires plan, journal and --execute")
        plan = json.loads(args.plan.read_text())
        validate_plan(plan)
        if (
            _hash(asdict(config)) != plan["beforeConfigSha256"]
            or _hash(runtime) != plan["beforeRuntimeSha256"]
            or (args.operation == "execute"
                and _hash(_ledger_snapshot(ledger)) != plan["beforeLedgerSha256"])
        ):
            raise CampaignError("campaign renewal inputs changed after planning")

        def snapshot() -> dict[str, Any]:
            return collect_live_snapshot(config, runtime, runner=runner, clock=clock, plan=plan)

        if args.operation == "discard-staged":
            discard_staged_plan(
                plan,
                authorization=args.old_authorization,
                directory=args.journal,
                runner=runner,
                clock=clock,
                collect_snapshot=snapshot,
            )
            print(json.dumps({"status": "staged-replacement-absent"}))
            return 0
        if args.new_authorization is None:
            raise CampaignError("campaign renewal activation requires its new authorization")
        record = execute_plan(
            plan,
            old_authorization=args.old_authorization,
            new_authorization=args.new_authorization,
            directory=args.journal,
            runner=runner,
            clock=clock,
            collect_snapshot=snapshot,
            collect_cleanup_readback=lambda: collect_live_cleanup_readback(
                config_from_snapshot(plan["afterConfig"]),
                plan["afterRuntime"],
                runner=runner,
            ),
        )
        print(
            json.dumps(
                {
                    "status": "activation-proved",
                    "receiptSha256": record["completion"]["receiptSha256"],
                }
            )
        )
        return 0
    except (CampaignError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
