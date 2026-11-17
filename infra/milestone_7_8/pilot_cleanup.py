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
from pathlib import Path

from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    Phase,
    SubprocessRunner,
    load_ledger,
    parse_utc,
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


def window(approved_at: str) -> dict[str, str]:
    start = parse_utc(approved_at)
    if start.microsecond:
        raise CampaignError("approval timestamp must resolve to whole seconds")
    return {
        key: utc(start + timedelta(hours=hours))
        for key, hours in (
            ("approvedAt", 0),
            ("readyBy", 2),
            ("stopProofBy", 10),
            ("automationBindingExpiresAt", 11),
            ("operatorCleanupExpiresAt", 12),
        )
    }


def binding_name(deadline: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"m78/{CAMPAIGN}/{GENERATION}/{deadline}")
    )


def validate_window(runtime_path: Path, runtime: dict, config: CampaignConfig) -> dict:
    path = Path(runtime["pilotCleanupWindowFile"]).resolve()
    if path != runtime_path.resolve().with_name("window.json"):
        raise CampaignError("pilot cleanup window escaped its bound runtime")
    value = read(path)
    expected = window(value["approvedAt"])
    if any(value.get(k) != v for k, v in expected.items()):
        raise CampaignError("pilot cleanup deadlines must be +2/+10/+11/+12")
    if (
        (config.campaign_id, config.generation_id, config.target_resource_group)
        != (CAMPAIGN, GENERATION, TARGET)
        or value["targetResourceGroup"] != TARGET
        or runtime["resourceGroupName"] != TARGET
        or config.target_region != "eastus"
        or config.maximum_hours != 10
        or config.authorized_ceiling_usd != "50.00"
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
    if (
        approval.get("approved") is not True
        or approval.get("reviewPackageSha256") != file_hash(review_path)
        or approval.get("sourceHead") != review["sourceCommit"]
        or review.get("schema") != "m78-full-closure-replacement-v1"
        or review.get("forecastUsd") != 36.6423
        or review.get("incrementalCeilingUsd") != 50
        or review.get("proposedCumulativeCeilingUsd") != 400.89
        or any(
            file_hash(package / name) != sha for name, sha in review["files"].items()
        )
    ):
        raise CampaignError("exact replacement review approval required")
    return review


def prepare_renewal(package: Path, approval: dict, output: Path) -> None:
    from infra.milestone_7_8.controller_renewal import build_plan

    review = validate_review(package, approval)
    times = window(approval["approvedAt"])
    if (
        not parse_utc(times["approvedAt"])
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
    times = window(approval["approvedAt"])
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
    times = window(approval["approvedAt"])
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
    from infra.milestone_7_8.controller import local_source_binding

    source, script_hash = local_source_binding()
    if (
        source != review["sourceCommit"]
        or runtime["sourceHead"] != source
        or runtime["cleanupScriptSha256"] != script_hash
        or window(approval["approvedAt"])["approvedAt"] != value["approvedAt"]
        or value["cleanupExecutorObjectId"]
        != read(package / "cleanup-plan.json")["executorObjectId"]
        or datetime.now(UTC) < parse_utc(value["approvedAt"])
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
        from infra.milestone_7_8.operator import OPERATION_PHASE

        value = validate_live(runtime_path, runtime, config)
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
        start = utc(
            parse_utc(controller.controller_authorized_until_utc) - timedelta(hours=11)
        )
    else:
        approval = read(approval_file)
        review = validate_review(package, approval)
        start = approval["approvedAt"]
        if (
            evidence.get("renewal", {}).get("priorAuthorityEvidence") != prior
            or controller.source_head != review["sourceCommit"]
            or datetime.now(UTC) < parse_utc(start)
            or datetime.now(UTC) >= parse_utc(window(start)["readyBy"])
        ):
            raise CampaignError(
                "fresh deadline renewal against the bound controller required"
            )
    values = window(start)
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
            "authorizedCeilingUsd": "50.00",
            "maximumHours": 10,
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
                    "approvedAt": values["approvedAt"],
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
        or group.get("location") != "eastus"
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


def execute_fallback(runtime_path: Path, runtime: dict, config: CampaignConfig) -> str:
    value = validate_live(runtime_path, runtime, config)
    plan = fallback_plan(runtime_path, runtime, config)
    if datetime.now(UTC) < parse_utc(plan["earliestUtc"]):
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
    signed_in = document(("az", "ad", "signed-in-user", "show", "--output", "json"))
    if signed_in.get("id") != plan["executorObjectId"]:
        raise CampaignError("fallback requires the approved current executor")
    scope = ("--subscription", sub, "--output", "json")
    if document(("az", "group", "exists", "--name", TARGET, *scope)) is False:
        record_cleanup()
        return "target-absent"
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
    record_cleanup()
    intent = directory / "fallback-delete-intent.json"
    write_new(
        intent,
        {
            "atUtc": utc(datetime.now(UTC)),
            "target": group["id"],
            "binding": plan["controllerBinding"],
        },
    )
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
            print(json.dumps({"status": execute_fallback(args.runtime, rt, cfg)}))
        else:
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
