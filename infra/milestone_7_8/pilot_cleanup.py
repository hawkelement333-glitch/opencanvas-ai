"""Bind the full-closure target to the reusable cleanup operator.

The retained controller evidence identifies the controller's origin. The
pilot campaign is a separate target with its own ledger and execution grant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    Phase,
    SubprocessRunner,
    load_ledger,
    parse_utc,
    sanitize,
    save_ledger,
    utc,
)
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.cleanup_controller import ARCHITECTURE
from infra.milestone_7_8.controller_admission import (
    bootstrap_script_hash,
    digest,
    latest_readback,
    load_authority_evidence,
    validate_authority_evidence,
)
from infra.milestone_7_8.pilot_validation import ROOT, write_new

SUFFIX = "a712b8c940"
TARGET = f"rg-m78-{SUFFIX}-target"
CAMPAIGN = f"m78-full-closure-{SUFFIX}"
GENERATION = f"g1-{SUFFIX}00"
MINUTE_REVIEW_SCHEMA = "m78-full-closure-regional-minute-v1"
ALERT_REPAIR_REVIEW_SCHEMA = "m78-full-closure-alert-repair-v1"
SIGNUP_REVIEW_SCHEMA = "m78-full-closure-signup-recovery-v1"
MINUTE_REVIEW_SCHEMAS = {MINUTE_REVIEW_SCHEMA, ALERT_REPAIR_REVIEW_SCHEMA, SIGNUP_REVIEW_SCHEMA}
RESERVE_REVIEW_SCHEMAS = {ALERT_REPAIR_REVIEW_SCHEMA, SIGNUP_REVIEW_SCHEMA}
MINUTE_START_RULE = "first-whole-utc-minute-after-approval"
OPERATIONS = (
    "preflight",
    "correlate",
    "capacity-check",
    "cost-gate",
    "scope-create",
    "cleanup-deploy",
    "cleanup-arm",
    "cleanup-verify",
    "billable-start",
    "cleanup",
    "cleanup-wait",
    "cleanup-disarm",
)


def read(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise CampaignError(f"expected JSON object in {path.name}")
    return result


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def window(
    approved_at: str, execution_start_at: str | None = None, *,
    signup_recovery: bool = False,
) -> dict[str, str]:
    receipt = parse_utc(approved_at)
    start = receipt
    values = {"approvedAt": utc(receipt)}
    if execution_start_at is not None:
        start = receipt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        if execution_start_at != utc(start):
            raise CampaignError("execution start must be the first whole UTC minute after approval")
        values["executionStartAt"] = execution_start_at
    elif receipt.microsecond:
        raise CampaignError("approval timestamp must resolve to whole seconds")
    stop = 11 if signup_recovery else 10
    values.update({
        key: utc(start + timedelta(hours=hours))
        for key, hours in (
            ("readyBy", 2),
            ("stopProofBy", stop),
            ("automationBindingExpiresAt", stop + 1),
            ("operatorCleanupExpiresAt", stop + 2),
        )
    })
    if signup_recovery:
        values["coreReadyBy"] = utc(start + timedelta(hours=3))
    return values


def approved_window(review: dict, approval: dict) -> dict[str, str]:
    execution_start_at = approval.get("executionStartAt")
    if review["schema"] in MINUTE_REVIEW_SCHEMAS:
        if (
            review.get("executionStartRule") != MINUTE_START_RULE
            or not isinstance(execution_start_at, str)
        ):
            raise CampaignError("explicit whole-minute execution start required")
    elif execution_start_at is not None:
        raise CampaignError("unexpected execution start for historical review")
    return window(
        approval["approvedAt"], execution_start_at,
        signup_recovery=review["schema"] == SIGNUP_REVIEW_SCHEMA,
    )


def binding_name(deadline: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"m78/{CAMPAIGN}/{GENERATION}/{deadline}")
    )


def validate_window(runtime_path: Path, runtime: dict, config: CampaignConfig) -> dict:
    path = Path(runtime["pilotCleanupWindowFile"]).resolve()
    if path != runtime_path.resolve().with_name("window.json"):
        raise CampaignError("pilot cleanup window escaped its bound runtime")
    value = read(path)
    signup_recovery = config.maximum_hours == 11
    expected = window(
        value["approvedAt"], value.get("executionStartAt"), signup_recovery=signup_recovery,
    )
    if any(value.get(k) != v for k, v in expected.items()):
        raise CampaignError("pilot cleanup deadlines differ from the recorded window")
    if (
        (config.campaign_id, config.generation_id, config.target_resource_group)
        != (CAMPAIGN, GENERATION, TARGET)
        or value["targetResourceGroup"] != TARGET
        or runtime["resourceGroupName"] != TARGET
        or config.target_region not in {"eastus", "canadacentral"}
        or config.postgres_region != config.target_region
        or value.get("targetRegion", "eastus") != config.target_region
        or config.maximum_hours not in {10, 11}
        or config.authorized_ceiling_usd != ("56.51" if signup_recovery else "50.00")
        or config.cleanup_deadline_utc != expected["stopProofBy"]
        or runtime["cleanupAuthorityExpiresUtc"]
        != expected["automationBindingExpiresAt"]
        or runtime["scheduleName"] != f"m78-deadline-{SUFFIX}"
        or runtime["bindingName"] != binding_name(expected["stopProofBy"])
    ):
        raise CampaignError("pilot cleanup target, schedule, or binding differs")
    return value


def validate_review(package: Path, approval: dict) -> dict:
    review_path = package / "review-package.json"
    review = read(review_path)
    schema = review.get("schema")
    if schema in {"m78-full-closure-regional-v1", *MINUTE_REVIEW_SCHEMAS}:
        pricing = read(package / "regional-pricing.json")
        forecast = review.get("forecastUsd")
        region_valid = (
            type(forecast) in {int, float}
            and 0 < forecast <= (56.51 if schema == SIGNUP_REVIEW_SCHEMA else 50)
            and forecast == pricing.get("forecastUsd")
            and review.get("targetRegion") == "canadacentral"
            and review.get("redisRegion") == "eastus"
            and "regional-pricing.json" in review["files"]
            and (
                schema not in MINUTE_REVIEW_SCHEMAS
                or review.get("spendingApprovalReady") is True
            )
        )
    else:
        region_valid = (
            schema == "m78-full-closure-replacement-v1"
            and review.get("forecastUsd") == 36.6423
        )
    cumulative_valid = review.get("proposedCumulativeCeilingUsd") == 400.89
    if schema in RESERVE_REVIEW_SCHEMAS:
        reconciliation = read(package / "cost-reconciliation.json")
        try:
            reserve = Decimal(str(review["priorAttemptReserveUsd"]))
            allowance = Decimal(str(review["successorExecutionAllowanceUsd"]))
            combined = reserve + allowance
            cumulative = Decimal("350.89") + combined
            cumulative_valid = (
                reserve.is_finite()
                and allowance == Decimal("56.51" if schema == SIGNUP_REVIEW_SCHEMA else "49.75")
                and reserve > 0
                and combined == Decimal(str(review["combinedCeilingUsd"]))
                and cumulative == Decimal(str(review["proposedCumulativeCeilingUsd"]))
                and combined - Decimal("50") == Decimal(str(review["netCeilingIncreaseProposedUsd"]))
                and reserve == Decimal(reconciliation["priorReserveUsd"])
                and allowance == Decimal(reconciliation["nextExecutionCeilingUsd"])
                and cumulative == Decimal(reconciliation["cumulativeCeilingProposedUsd"])
                and file_hash(package / "cost-reconciliation.json")
                == review["costReconciliationSha256"]
                and "cost-reconciliation.json" in review["files"]
            )
            exception_schema = (review.get("stagingException") or {}).get("schema")
            prior_by_exception = {
                "m78-private-synthetic-staging-exception-v2": Decimal("460.40"),
                "m78-private-synthetic-staging-exception-v3": Decimal("516.91"),
            }
            if exception_schema in prior_by_exception:
                # Preserve the entire previous ceiling while the ledger is unsettled.
                prior_ceiling = Decimal(reconciliation["priorAuthorizedCumulativeUsd"])
                cumulative_valid = (
                    cumulative_valid
                    and prior_ceiling == prior_by_exception[exception_schema]
                    and Decimal(str(review["increaseOverLastApprovalUsd"])) == allowance
                    and cumulative == prior_ceiling + allowance
                    and reconciliation["billing"] == "unsettled"
                    and reconciliation["actualChargesUsd"] is None
                )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            cumulative_valid = False
    if (
        approval.get("approved") is not True
        or approval.get("reviewPackageSha256") != file_hash(review_path)
        or approval.get("sourceHead") != review["sourceCommit"]
        or not region_valid
        or review.get("incrementalCeilingUsd") != (56.51 if schema == SIGNUP_REVIEW_SCHEMA else 50)
        or not cumulative_valid
        or any(
            file_hash(package / name) != sha for name, sha in review["files"].items()
        )
    ):
        raise CampaignError("exact replacement review approval required")
    scanner_policy = review.get("scannerRecoveryPolicy")
    telemetry_policy = review.get("telemetryFirstPolicy")
    staging_exception = review.get("stagingException")
    if staging_exception is not None and (scanner_policy is None or telemetry_policy is None):
        raise CampaignError("staging exception requires both proof policies")
    if scanner_policy is not None:
        from infra.milestone_7_8.pilot.scanner_hold import POLICY

        source_bindings = review.get("operatorSourceBindings")
        expected_sources = {
            "infra/milestone_7_8/pilot/core_proof_operator.py",
            "infra/milestone_7_8/pilot/scanner_hold.py",
            "infra/milestone_7_8/pilot/scanner_read_diagnostic.py",
            "infra/milestone_7_8/pilot/scanner_operator.py",
            "infra/milestone_7_8/pilot_cleanup.py",
        }
        if telemetry_policy is not None:
            from infra.milestone_7_8.pilot import telemetry_first

            expected_sources.add("infra/milestone_7_8/pilot/telemetry_first.py")
            if (
                telemetry_policy != telemetry_first.POLICY
                or read(package / "telemetry-first-policy.json") != telemetry_first.POLICY
                or "telemetry-first-policy.json" not in review["files"]
                or approval.get("approveExactQuotaFallback") is not True
            ):
                raise CampaignError("exact telemetry-first and quota fallback approval required")
            if staging_exception is None:
                telemetry_first.validate_release(package)
            else:
                from infra.milestone_7_8.pilot.staging_exception import validate_staging_admission

                expected_sources.add("infra/milestone_7_8/pilot/staging_exception.py")
                validate_staging_admission(package, review, approval)
        if (
            review["schema"] != SIGNUP_REVIEW_SCHEMA
            or scanner_policy != POLICY
            or read(package / "scanner-recovery-policy.json") != POLICY
            or not isinstance(source_bindings, dict)
            or set(source_bindings) != expected_sources
            or any(file_hash(ROOT / name) != sha for name, sha in source_bindings.items())
        ):
            raise CampaignError("exact scanner hold policy and operator source required")
    elif telemetry_policy is not None:
        raise CampaignError("telemetry-first requires the bound scanner recovery policy")
    approved_window(review, approval)
    return review


def successor_smtp_password(package: Path, approval: dict) -> str:
    review = read(package / "review-package.json")
    filename = (
        "smtp-scanner-successor.private.json" if review.get("scannerRecoveryPolicy")
        else "smtp-signup-successor.private.json"
    )
    path = package.parent / filename
    if not path.is_file() or file_hash(path) != approval.get("smtpCredentialSha256"):
        raise CampaignError("replacement Gmail credential must be supplied and privately bound")
    value = read(path)
    if set(value) != {"password"} or not isinstance(value["password"], str):
        raise CampaignError("replacement Gmail credential file is malformed")
    password = value["password"].replace(" ", "")
    if len(password) != 16 or not password.isascii() or not password.isalpha():
        raise CampaignError("replacement Gmail app password must be 16 ASCII letters")
    return password


def prepare_renewal(package: Path, approval: dict, output: Path) -> None:
    from infra.milestone_7_8.controller_renewal import build_plan

    review = validate_review(package, approval)
    if review["schema"] == SIGNUP_REVIEW_SCHEMA and "telemetryFirstPolicy" not in review:
        successor_smtp_password(package, approval)
    times = approved_window(review, approval)
    if (
        not parse_utc(times.get("executionStartAt", times["approvedAt"]))
        <= datetime.now(UTC)
        < parse_utc(times["readyBy"])
    ):
        raise CampaignError("controller renewal is outside the readiness window")
    prior = load_authority_evidence(package / "controller-prior-authority.json")
    plan = build_plan(
        prior,
        source_head=review["sourceCommit"],
        deadline=times["automationBindingExpiresAt"],
    )
    renewed = plan["renewedConfig"]
    read_authority = {
        key: renewed[key]
        for key in (
            "subscriptionCorrelation",
            "sourceHead",
            "controllerLocation",
            "controllerResourceGroupName",
            "automationAccountName",
            "controllerAuthorizedUntilUtc",
            "freshControllerAdmissionEvidenceSha256",
            "freshControllerAdmissionEvidenceVersion",
        )
    }
    read_authority.update(
        version="m7.8-controller-execution-authorization-v4",
        disposition="separately-authorized-controller-execution",
        operation="controller-verify",
        controllerArchitecture=ARCHITECTURE,
        expiresAtUtc=times["readyBy"],
    )
    write_new(output / "controller-renewal-plan.json", plan)
    write_new(
        output / "controller-renewal-read-approval.json",
        {
            **read_authority,
            "authorizationSha256": digest(
                "m7.8/controller-execution-authorization/v4",
                read_authority,
            ),
        },
    )


def bind_renewal_write(package: Path, approval: dict, output: Path) -> None:
    from infra.milestone_7_8.controller_renewal import build_approval

    review = validate_review(package, approval)
    plan = read(output / "controller-renewal-plan.json")
    times = approved_window(review, approval)
    if (
        plan["renewedConfig"]["sourceHead"] != review["sourceCommit"]
        or plan["renewedDeadlineUtc"] != times["automationBindingExpiresAt"]
    ):
        raise CampaignError("renewal plan differs from exact approval")
    now = datetime.now(UTC)
    result = build_approval(
        load_authority_evidence(package / "controller-prior-authority.json"),
        plan,
        json.loads(
            (output / "controller-renewal-before.json").read_text(encoding="utf-8")
        ),
        issued_at=utc(now),
        expires_at=times["readyBy"],
        now=now,
    )
    write_new(output / "controller-renewal-approval.json", result)


def bind_renewal_reconcile(package: Path, approval: dict, output: Path) -> None:
    from infra.milestone_7_8.controller_renewal import (
        build_reconciliation_approval,
        load_executor_journal,
    )

    review = validate_review(package, approval)
    times = approved_window(review, approval)
    plan = read(output / "controller-renewal-plan.json")
    if (
        plan["renewedConfig"]["sourceHead"] != review["sourceCommit"]
        or plan["renewedDeadlineUtc"] != times["automationBindingExpiresAt"]
    ):
        raise CampaignError("renewal plan differs from exact approval")
    before = json.loads(
        (output / "controller-renewal-before.json").read_text(encoding="utf-8")
    )
    write_approval = read(output / "controller-renewal-approval.json")
    journal = load_executor_journal(output / "journal", plan, write_approval, before)
    now = datetime.now(UTC)
    result = build_reconciliation_approval(
        load_authority_evidence(package / "controller-prior-authority.json"),
        plan,
        before,
        write_approval,
        journal,
        issued_at=utc(now),
        expires_at=times["readyBy"],
        now=now,
        source_head=review["sourceCommit"],
    )
    write_new(output / "controller-reconciliation-approval.json", result)


def validate_live(runtime_path: Path, runtime: dict, config: CampaignConfig) -> dict:
    value = validate_window(runtime_path, runtime, config)
    if value.get("simulation") is not False:
        raise CampaignError("offline cleanup rehearsal cannot execute")
    directory = runtime_path.resolve().parent
    approval = read(directory / "replacement-approval.json")
    package = Path(value["packageDirectory"]).resolve()
    review = validate_review(package, approval)
    times = approved_window(review, approval)
    from infra.milestone_7_8.controller import local_source_binding

    source, script_hash = local_source_binding()
    if (
        source != review["sourceCommit"]
        or config.target_region != review.get("targetRegion", "eastus")
        or runtime["sourceHead"] != source
        or runtime["cleanupScriptSha256"] != script_hash
        or any(value.get(key) != expected for key, expected in times.items())
        or value["cleanupExecutorObjectId"]
        != read(package / "cleanup-plan.json")["executorObjectId"]
        or datetime.now(UTC) < parse_utc(times.get("executionStartAt", times["approvedAt"]))
        or datetime.now(UTC) >= parse_utc(value["operatorCleanupExpiresAt"])
    ):
        raise CampaignError("pilot cleanup approval, source, or executor differs")
    return value


def validate_operator_invocation(
    runtime_path: Path,
    runtime: dict,
    config: CampaignConfig,
    ledger_path: Path,
    operation: str,
    execute: bool,
) -> None:
    if operation not in OPERATIONS:
        raise CampaignError(
            "pilot cleanup bundle cannot run legacy workload operations"
        )
    if (
        ledger_path.resolve() != runtime_path.resolve().with_name("ledger.json")
        or not ledger_path.is_file()
    ):
        raise CampaignError("pilot cleanup namespace requires its exact ledger.json")
    if execute:
        from infra.milestone_7_8.campaign import ORDER
        from infra.milestone_7_8.operator import OPERATION_PHASE, pilot_cleanup_journal

        value = validate_live(runtime_path, runtime, config)
        journal = pilot_cleanup_journal(runtime)
        failure_path = journal / "failure.json" if journal is not None else None
        failure = read(failure_path) if failure_path is not None and failure_path.is_file() else None
        if failure is not None and operation not in {"cleanup", "cleanup-wait", "cleanup-disarm"}:
            raise CampaignError("campaign admission failed; reconcile cleanup before any further operation")
        if operation in {"cleanup-wait", "cleanup-disarm"}:
            cutoff = "operatorCleanupExpiresAt"
        elif operation == "cleanup":
            cutoff = "automationBindingExpiresAt"
        else:
            cutoff = "readyBy"
        if datetime.now(UTC) >= parse_utc(value[cutoff]):
            raise CampaignError(
                "operator deadline reached; use the approved cleanup procedure"
            )
        current = Phase(load_ledger(ledger_path, config).phase)
        target = OPERATION_PHASE[operation]
        if operation == "cleanup":
            if (
                not ORDER.index(Phase.SCOPE_CREATED)
                <= ORDER.index(current)
                < ORDER.index(Phase.CLEANING)
                and not (
                    current is Phase.COST_GATED
                    and failure is not None
                    and failure.get("operation") == "scope-create"
                )
            ):
                raise CampaignError(
                    "reconcile the campaign phase before dispatching cleanup"
                )
        elif ORDER.index(target) != ORDER.index(current) + 1:
            raise CampaignError(
                "pilot cleanup operation requires its previous ledger phase"
            )


def at_directory(template: dict, directory: Path) -> dict:
    """Resolve only the bundle's directory marker in the runtime JSON."""
    return {
        key: value.replace("${cleanupDirectory}", directory.as_posix())
        for key, value in template.items()
    }


def materialize(
    package: Path,
    directory: Path,
    *,
    authority_file: Path,
    approval_file: Path | None,
) -> None:
    """Create a fresh runtime bundle from the approval and controller renewal."""
    package, directory = package.resolve(), directory.resolve()
    if not directory.is_relative_to((ROOT / ".runtime").resolve()):
        raise CampaignError("pilot cleanup output must be private")
    template = package / "cleanup"
    prior = load_authority_evidence(package / "controller-prior-authority.json")
    evidence = load_authority_evidence(authority_file)
    controller = validate_authority_evidence(evidence)
    simulation = approval_file is None
    if simulation:
        review = read(package / "review-package.json")
        if evidence != prior:
            raise CampaignError(
                "offline rehearsal requires the exact retained controller"
            )
        signup_recovery = review["schema"] == SIGNUP_REVIEW_SCHEMA
        start = parse_utc(controller.controller_authorized_until_utc) - timedelta(
            hours=12 if signup_recovery else 11
        )
        if review["schema"] in MINUTE_REVIEW_SCHEMAS:
            start = start.replace(second=0, microsecond=0)
            values = window(
                utc(start - timedelta(seconds=1)), utc(start), signup_recovery=signup_recovery,
            )
        else:
            values = window(utc(start))
    else:
        approval = read(approval_file)
        review = validate_review(package, approval)
        values = approved_window(review, approval)
        if (
            evidence.get("renewal", {}).get("priorAuthorityEvidence") != prior
            or controller.source_head != review["sourceCommit"]
            or datetime.now(UTC) < parse_utc(values.get("executionStartAt", values["approvedAt"]))
            or datetime.now(UTC) >= parse_utc(values["readyBy"])
        ):
            raise CampaignError(
                "fresh deadline renewal against the bound controller required"
            )
    if parse_utc(controller.controller_authorized_until_utc) < parse_utc(
        values["automationBindingExpiresAt"]
    ):
        raise CampaignError(
            "Automation controller does not cover the +11 binding expiry"
        )
    deadline = values["stopProofBy"]
    config = read(template / "campaign.template.json")
    config["cleanupDeadlineUtc"] = deadline
    runtime = at_directory(read(template / "runtime.template.json"), directory)
    image_inputs = canonical_snapshot(review["sourceCommit"])
    runtime.update(
        sourceHead=review["sourceCommit"],
        canonicalBuildInputSha256=image_inputs["buildInputSha256"],
        dockerfileSha256=image_inputs["dockerfileSha256"],
        cleanupScriptSha256=controller.cleanup_script_sha256,
        controllerBootstrapScriptSha256=bootstrap_script_hash(evidence),
        controllerAuthorizedUntilUtc=controller.controller_authorized_until_utc,
        controllerAuthorityEvidenceSha256=digest(
            "m7.8/controller-authority-evidence/v1", evidence
        ),
        cleanupAuthorityExpiresUtc=values["automationBindingExpiresAt"],
        scheduleName=f"m78-deadline-{SUFFIX}",
        bindingName=binding_name(deadline),
    )
    config_model = CampaignConfig.from_document(config, allow_expired=simulation)
    if review["schema"] in RESERVE_REVIEW_SCHEMAS and (
        Decimal(config_model.conservative_estimate_usd)
        > Decimal(str(review["successorExecutionAllowanceUsd"]))
    ):
        raise CampaignError("successor estimate exceeds its reconciled remaining allowance")
    if config_model.target_region != review.get("targetRegion", "eastus"):
        raise CampaignError("campaign region differs from the sealed review")
    initial = read(template / "ledger.json")
    directory.mkdir(parents=True, exist_ok=False)
    for name in (
        "fresh-subscription-runtime.json",
        "predeployment-read-authorization.json",
        "predeployment-absence-evidence.json",
        "cleanup-region-selection.json",
    ):
        write_new(directory / name, read(template / name))
    for name in ("cleanup.parameters.json", "campaign.parameters.json"):
        data = read(template / name)
        params = data["parameters"]
        replacements = {
            "cleanupDeadlineUtc": deadline,
            "cleanupAuthorityExpiresUtc": runtime["cleanupAuthorityExpiresUtc"],
            "cleanupScheduleName": runtime["scheduleName"],
            "cleanupBindingName": runtime["bindingName"],
        }
        for key, item in replacements.items():
            if key in params:
                params[key]["value"] = item
        if "lifecycleTags" in params:
            tags = params["lifecycleTags"]["value"]
            tags["mobius.cleanup-deadline-utc"] = tags["mobius.expiry"] = deadline
        write_new(directory / name, data)
    write_new(directory / "campaign.json", config)
    write_new(directory / "runtime.json", runtime)
    write_new(directory / "ledger.json", initial)
    write_new(directory / "controller-authority-evidence.json", evidence)
    write_new(
        directory / "window.json",
        {
            **values,
            "simulation": simulation,
            "targetResourceGroup": TARGET,
            "targetRegion": config_model.target_region,
            "packageDirectory": str(package),
            "cleanupExecutorObjectId": read(package / "cleanup-plan.json")[
                "executorObjectId"
            ],
        },
    )

    from infra.milestone_7_8.operator import load_runtime, validate_prepared_bundle

    runtime_path = directory / "runtime.json"
    validate_prepared_bundle(runtime_path, load_runtime(runtime_path), config_model)
    load_ledger(directory / "ledger.json", config_model)
    if not simulation:
        write_new(directory / "replacement-approval.json", approval)
        unsigned = {
            "version": "m7.8-execution-authorization-v6",
            "disposition": "separately-authorized-azure-execution",
            "campaignId": CAMPAIGN,
            "generationId": GENERATION,
            "subscriptionCorrelation": config_model.subscription_correlation,
            "sourceHead": review["sourceCommit"],
            "controllerArchitecture": ARCHITECTURE,
            "controllerBindingSha256": runtime["controllerBindingSha256"],
            "controllerAuthorityEvidenceSha256": runtime[
                "controllerAuthorityEvidenceSha256"
            ],
            "freshControllerAdmissionEvidenceSha256": config_model.fresh_controller_admission_evidence_sha256,
            "freshControllerAdmissionEvidenceVersion": runtime[
                "freshControllerAdmissionEvidenceVersion"
            ],
            "cleanupDeadlineUtc": deadline,
            "expiresAtUtc": values["automationBindingExpiresAt"],
            "allowedOperations": list(OPERATIONS),
            "authorizedCeilingUsd": config_model.authorized_ceiling_usd,
            "maximumHours": config_model.maximum_hours,
        }
        write_new(
            directory / "operator-approval.json",
            {
                **unsigned,
                "authorizationSha256": digest(
                    "m7.8/execution-authorization/v6", unsigned
                ),
            },
        )
        fallback = {
            **unsigned,
            "allowedOperations": ["cleanup-wait", "cleanup-disarm"],
            "expiresAtUtc": values["operatorCleanupExpiresAt"],
        }
        write_new(
            directory / "cleanup-verification-approval.json",
            {
                **fallback,
                "authorizationSha256": digest(
                    "m7.8/execution-authorization/v6", fallback
                ),
            },
        )
        for filename, binding in (
            ("approval", "planned-bindings.json"),
            ("index-approval", "index-bindings.json"),
            ("capacity-approval", "planned-bindings.json"),
        ):
            probe = read(package / f"{filename}.unapproved.json")
            if probe["packageSha256"] != file_hash(package / "manifest.json") or probe[
                "bindingsSha256"
            ] != file_hash(package / binding):
                raise CampaignError(
                    "proof dispatch template differs from approved file"
                )
            write_new(
                directory / f"{filename}.json",
                {
                    **probe,
                    "approved": True,
                    "approvedAt": values.get("executionStartAt", values["approvedAt"]),
                },
            )


def stage_parameters(package: Path, directory: Path, stage: str, native: dict) -> dict:
    """Build the exact ARM parameter envelope using private inputs and admitted IDs."""
    from infra.milestone_7_8.operator import load_runtime, validate_prepared_bundle

    runtime_path = directory / "runtime.json"
    cfg = CampaignConfig.from_json(directory / "campaign.json", allow_expired=True)
    rt = load_runtime(runtime_path)
    validate_prepared_bundle(runtime_path, rt, cfg)
    keys = {"operatorVpnAudienceAppId", "operatorPrincipalId", "cleanupPrincipal"}
    if stage != "foundation":
        keys |= {"bootstrapPrincipalId", "storageDataScannerResourceId"}
    if set(native) != keys:
        raise CampaignError("exact stage native values required")
    for name in ("operatorVpnAudienceAppId", "operatorPrincipalId"):
        uuid.UUID(native[name])
    if stage != "foundation":
        uuid.UUID(native["bootstrapPrincipalId"])
        scanner = native["storageDataScannerResourceId"]
        if not isinstance(scanner, str) or not scanner.startswith(
            f"/subscriptions/{rt['subscriptionId']}/"
        ):
            raise CampaignError("scanner resource differs from bound subscription")
    authority = read(directory / "controller-authority-evidence.json")
    retained = validate_authority_evidence(authority)
    account = json.loads(latest_readback(authority)[1]["stdout"])
    expected_principal = native["cleanupPrincipal"]
    if expected_principal != {
        "name": retained.automation_account_name,
        "principalId": account["identity"]["principalId"],
    }:
        raise CampaignError("cleanup principal name differs from renewed controller")
    uuid.UUID(expected_principal["principalId"])
    output = read(package / "parameters.bound.json")
    output["$schema"] = (
        "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
    )
    output["contentVersion"] = "1.0.0.0"
    parameters = output["parameters"]
    review = read(package / "review-package.json")
    if (
        parameters.get("location", {}).get("value") != cfg.target_region
        or cfg.target_region != review.get("targetRegion", "eastus")
        or parameters.get("redisLocation", parameters["location"]).get("value")
        != review.get("redisRegion", cfg.target_region)
    ):
        raise CampaignError("deployment locations differ from the bound campaign")
    tags = read(directory / "campaign.parameters.json")["parameters"]["lifecycleTags"][
        "value"
    ]
    values = {
        **native,
        "campaignId": CAMPAIGN,
        "generationId": GENERATION,
        "stage": stage,
        "subscriptionCorrelation": cfg.subscription_correlation,
        "lifecycleTags": tags,
    }
    parameters.update({key: {"value": value} for key, value in values.items()})
    if stage != "foundation":
        parameters.update(
            read(package / "credentials/application-secrets.parameters.json")[
                "parameters"
            ]
        )
        if review.get("schema") == SIGNUP_REVIEW_SCHEMA:
            from infra.milestone_7_8.signup_reconcile import STAGING_OPERATOR_DENY_ALL

            if parameters["applicationSecrets"]["value"].get(
                "opencanvas-observability-operator-user-ids"
            ) != json.dumps([STAGING_OPERATOR_DENY_ALL], separators=(",", ":")):
                raise CampaignError("approved initial staging allowlist is missing")
            if "telemetryFirstPolicy" in review:
                secrets = parameters["applicationSecrets"]["value"]
                if (
                    parameters["smtpHost"]["value"] != "disabled.mail.invalid"
                    or secrets.get("opencanvas-smtp-username") != "unused@example.invalid"
                    or secrets.get("opencanvas-smtp-password") != "unused-no-mail"
                ):
                    raise CampaignError("telemetry-first package requires inert mail settings")
            elif read(directory / "window.json")["simulation"] is False:
                approval = read(directory / "replacement-approval.json")
                parameters["applicationSecrets"]["value"]["opencanvas-smtp-password"] = (
                    successor_smtp_password(package, approval)
                )
    template = read(package / "compiled/pilot.json")
    declarations = template["parameters"]
    if set(parameters) - set(declarations) or any(
        key not in parameters
        for key, declared in declarations.items()
        if "defaultValue" not in declared
    ):
        raise CampaignError(
            "stage parameters do not match compiled deployment template"
        )
    if "${" in json.dumps(parameters):
        raise CampaignError("unresolved stage parameter slot")
    return output


def fallback_plan(runtime_path: Path, runtime: dict, config: CampaignConfig) -> dict:
    value = validate_window(runtime_path, runtime, config)
    return {
        "targetResourceGroup": TARGET,
        "targetRegion": config.target_region,
        "earliestUtc": value["automationBindingExpiresAt"],
        "expiresAtUtc": value["operatorCleanupExpiresAt"],
        "executorObjectId": value["cleanupExecutorObjectId"],
        "controllerBinding": runtime["bindingName"],
        "delete": [
            "az",
            "group",
            "delete",
            "--name",
            TARGET,
            "--yes",
            "--no-wait",
            "--subscription",
            runtime["subscriptionId"],
        ],
    }


def fallback_decision(
    group: dict, jobs: dict, plan: dict, config: CampaignConfig, runtime: dict
) -> str:
    """Admit one exact target after the controller's outstanding work is reconciled."""
    from infra.milestone_7_8.operator import _collection, validate_operation_results

    validate_operation_results(
        "scope-create",
        [{"stdout": json.dumps(group)}],
        config,
        runtime,
    )
    target_id = f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{TARGET}"
    if (
        str(group.get("id", "")).casefold() != target_id.casefold()
        or group.get("location") != config.target_region
        or plan["targetRegion"] != config.target_region
        or plan["targetResourceGroup"] != TARGET
    ):
        raise CampaignError("fallback target readback differs")
    state = group.get("properties", {}).get("provisioningState")
    if state == "Deleting":
        return "wait"
    if state not in {"Succeeded", "Failed", "Canceled"}:
        raise CampaignError("fallback resource group state is unresolved")
    for job in _collection(jobs, label="Automation job"):
        props = job.get("properties", {})
        runbook = props.get("runbook", {}).get("name")
        if not runbook or (
            runbook == runtime["runbookName"]
            and props.get("status") not in {"Completed", "Failed", "Stopped"}
        ):
            raise CampaignError("reconcile existing controller job before fallback")
    return "delete"


def quota_fallback_stop(
    approval_path: Path | None,
    runtime_path: Path,
    runtime: dict,
    config: CampaignConfig,
    window_record: dict,
    now: datetime,
) -> tuple[datetime, dict[str, str]]:
    """Bind early fallback to this run's proof stop, quota rejection and approval."""
    from infra.milestone_7_8.operator import command_plan, pilot_cleanup_journal

    bound_path = runtime_path.parent / "replacement-approval.json"
    bound = read(bound_path)
    review_sha = bound["reviewPackageSha256"]
    package = Path(window_record["packageDirectory"]).resolve()
    run = package.parent / ("run-" + review_sha[:8])
    if file_hash(package / "review-package.json") != review_sha:
        raise CampaignError("quota fallback review differs from the bound runtime")
    if approval_path is None:
        review = validate_review(package, bound)
        if (
            "telemetryFirstPolicy" not in review
            or bound.get("approveExactQuotaFallback") is not True
        ):
            raise CampaignError("this execution approval does not cover early quota fallback")
        approval = None
    else:
        approval = read(approval_path)
        if (
            approval_path.resolve().parent != run
            or approval.get("approved") is not True
            or approval.get("reviewPackageSha256") != review_sha
            or approval.get("targetResourceGroup") != config.target_resource_group
            or approval.get("automationBinding") != runtime["bindingName"]
            or approval.get("cleanupDeadlineUtc")
            != window_record["operatorCleanupExpiresAt"]
        ):
            raise CampaignError("separate exact quota fallback approval required")
    stop_path = run / "stop-proof-intent.json"
    stop = read(stop_path)
    stopped_at = parse_utc(stop["atUtc"])
    if (
        stop["scheduledCleanupAtUtc"] != window_record["stopProofBy"]
        or not parse_utc(window_record["executionStartAt"])
        <= stopped_at
        <= now
        or (
            approval is not None and (
                approval.get("stopProofSha256") != file_hash(stop_path)
                or not stopped_at <= parse_utc(approval["approvedAt"]) <= now
            )
        )
    ):
        raise CampaignError("quota fallback does not bind the recorded proof stop")
    journal = pilot_cleanup_journal(runtime)
    if journal is None:
        raise CampaignError("quota fallback requires the bound cleanup journal")
    (command,) = command_plan("cleanup", config, runtime)
    if read(journal / "runbook-intent.json") != {
        "command": [*command, "--subscription", runtime["subscriptionId"]]
    }:
        raise CampaignError("quota fallback must bind the exact runbook dispatch")
    response_path = journal / "runbook-response.json"
    response = read(response_path)
    stderr = response.get("stderr", "")
    if (
        (approval is not None and approval.get("quotaResponseSha256") != file_hash(response_path))
        or type(response.get("exitCode")) is not int
        or response["exitCode"] != 1
        or not isinstance(stderr, str)
        or "Code: 429" not in stderr.splitlines()
        or "The maximum monthly job execution time limit for free subs has been reached."
        not in stderr
    ):
        raise CampaignError("Automation execution quota rejection is unverified")
    return stopped_at, {
        "quotaApprovalSha256": file_hash(approval_path or bound_path),
        "stopProofSha256": file_hash(stop_path),
        "quotaResponseSha256": file_hash(response_path),
    }


def execute_fallback(
    runtime_path: Path,
    runtime: dict,
    config: CampaignConfig,
    *,
    quota_approval: Path | None = None,
    use_execution_quota_approval: bool = False,
) -> str:
    value = validate_live(runtime_path, runtime, config)
    plan = fallback_plan(runtime_path, runtime, config)
    now = datetime.now(UTC)
    stopped_at = None
    quota_binding = {}
    if quota_approval is not None and use_execution_quota_approval:
        raise CampaignError("select exactly one early fallback authority")
    if quota_approval is not None or use_execution_quota_approval:
        stopped_at, quota_binding = quota_fallback_stop(
            quota_approval, runtime_path, runtime, config, value, now
        )
    elif now < parse_utc(plan["earliestUtc"]):
        raise CampaignError("Automation binding has not expired")
    directory = runtime_path.resolve().parent
    ledger_path = directory / "ledger.json"
    if not ledger_path.is_file():
        raise CampaignError("fallback requires the bound campaign ledger")
    ledger = load_ledger(ledger_path, config)

    def record_cleanup() -> None:
        if ledger.phase in {Phase.CLEANING, Phase.CLEANED, Phase.CLEANUP_DISARMED}:
            return
        ledger.transition(Phase.CLEANING, datetime.now(UTC))
        save_ledger(ledger_path, ledger)

    def run(args: tuple[str, ...]) -> dict:
        remaining = (
            parse_utc(value["operatorCleanupExpiresAt"]) - datetime.now(UTC)
        ).total_seconds()
        if remaining <= 0:
            raise CampaignError("operator fallback authority expired")
        return SubprocessRunner(timeout_seconds=min(remaining, 60)).run(args)

    def document(args: tuple[str, ...]):
        result = run(args)
        if result.get("exitCode") != 0:
            raise CampaignError("fallback native read failed")
        return json.loads(result["stdout"])

    sub = runtime["subscriptionId"]
    scope = ("--subscription", sub, "--output", "json")
    account_info = document(("az", "account", "show", *scope))
    if (
        account_info.get("id") != sub
        or account_info.get("state") != "Enabled"
        or sanitize(sub, domain="subscription") != config.subscription_correlation
        or sanitize(account_info.get("tenantId", ""), domain="tenant")
        != config.tenant_correlation
    ):
        raise CampaignError("fallback subscription or tenant differs")
    # Microsoft Graph uses the signed-in tenant. This command rejects --subscription.
    signed_in = document(("az", "ad", "signed-in-user", "show", "--output", "json"))
    if signed_in.get("id") != plan["executorObjectId"]:
        raise CampaignError("fallback requires the approved current executor")
    exists = document(("az", "group", "exists", "--name", TARGET, *scope))
    if exists is False:
        record_cleanup()
        return "target-absent"
    if exists is not True:
        raise CampaignError("fallback target presence is unresolved")
    group = document(("az", "group", "show", "--name", TARGET, *scope))
    account = (
        f"/subscriptions/{sub}/resourceGroups/{config.cleanup_resource_group}"
        f"/providers/Microsoft.Automation/automationAccounts/{runtime['automationAccountName']}"
    )
    jobs = document(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"https://management.azure.com{account}/jobs?api-version=2024-10-23",
            *scope,
        )
    )
    decision = fallback_decision(group, jobs, plan, config, runtime)
    if decision == "wait":
        record_cleanup()
        return "target-deletion-in-progress"
    if stopped_at is not None:
        for job in jobs["value"]:
            props = job["properties"]
            if props["runbook"]["name"] == runtime["runbookName"] and (
                not props.get("creationTime")
                or parse_utc(props["creationTime"]) >= stopped_at.replace(microsecond=0)
            ):
                raise CampaignError(
                    "Automation job outcome requires reconciliation after quota rejection"
                )
    record_cleanup()
    intent = directory / "fallback-delete-intent.json"
    record = {
        "atUtc": utc(datetime.now(UTC)),
        "target": group["id"],
        "binding": plan["controllerBinding"],
        **quota_binding,
    }
    try:
        write_new(intent, record)
    except FileExistsError as error:
        raise CampaignError(
            "previous fallback deletion requires native reconciliation"
        ) from error
    result = run(tuple(plan["delete"]))
    write_new(directory / "fallback-delete-response.json", result)
    if result.get("exitCode") != 0:
        raise CampaignError("fallback deletion outcome requires native reconciliation")
    return "target-deletion-dispatched"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)
    bind = steps.add_parser("bind")
    for option in ("package", "output", "controller-authority"):
        bind.add_argument("--" + option, required=True, type=Path)
    bind.add_argument("--approval", type=Path, help="Omit for offline-only rehearsal")
    fallback = steps.add_parser("fallback-plan")
    fallback.add_argument("--runtime", required=True, type=Path)
    fallback.add_argument("--config", required=True, type=Path)
    fallback.add_argument("--execute", action="store_true")
    fallback.add_argument(
        "--quota-approval",
        type=Path,
        help="Separate approval for an early fallback after verified Automation quota rejection",
    )
    fallback.add_argument("--use-execution-quota-approval", action="store_true")
    arm = steps.add_parser("stage-parameters")
    for option in ("package", "directory", "native-values", "output"):
        arm.add_argument("--" + option, type=Path, required=True)
    arm.add_argument(
        "--stage", choices=("foundation", "jobs", "application"), required=True
    )
    renewal_commands = {
        "renewal-inputs": prepare_renewal,
        "renewal-write-approval": bind_renewal_write,
        "renewal-reconcile-approval": bind_renewal_reconcile,
    }
    for name in renewal_commands:
        renewal = steps.add_parser(name)
        for option in ("package", "approval", "output"):
            renewal.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    if args.step == "bind":
        materialize(
            args.package,
            args.output,
            authority_file=args.controller_authority,
            approval_file=args.approval,
        )
        print(json.dumps({"status": "bound", "simulation": args.approval is None}))
    elif args.step == "stage-parameters":
        if not args.output.resolve().is_relative_to((ROOT / ".runtime").resolve()):
            raise CampaignError("ARM parameters must stay private")
        write_new(
            args.output,
            stage_parameters(
                args.package, args.directory, args.stage, read(args.native_values)
            ),
        )
        print(json.dumps({"status": "parameters-bound", "stage": args.stage}))
    elif args.step in renewal_commands:
        if not args.output.resolve().is_relative_to((ROOT / ".runtime").resolve()):
            raise CampaignError("controller renewal inputs must stay private")
        renewal_commands[args.step](args.package, read(args.approval), args.output)
        print(json.dumps({"status": "renewal-inputs-bound", "step": args.step}))
    else:
        from infra.milestone_7_8.operator import load_runtime, validate_prepared_bundle

        cfg = CampaignConfig.from_json(args.config, allow_expired=True)
        rt = load_runtime(args.runtime)
        validate_prepared_bundle(args.runtime, rt, cfg)
        if args.execute:
            result = execute_fallback(
                args.runtime, rt, cfg, quota_approval=args.quota_approval,
                use_execution_quota_approval=args.use_execution_quota_approval,
            )
            print(json.dumps({"status": result}))
        else:
            if args.quota_approval is not None or args.use_execution_quota_approval:
                fallback.error("early fallback authorization options require --execute")
            output = fallback_plan(args.runtime, rt, cfg)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in output.items()
                        if k not in {"executorObjectId", "delete"}
                    }
                )
            )


if __name__ == "__main__":
    main()
