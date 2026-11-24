"""Seal the full Core fixture, remaining proof and teardown for one private deployment."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignConfig, CampaignError
from infra.milestone_7_8.destination_acceptance import METRIC_VALUE_PROJECTION, V5_METRIC_VALUE_PROJECTION
from infra.milestone_7_8.pilot import consolidated as scope, staging_exception as staging
from infra.milestone_7_8.pilot.integrity_windows import POINTS, signal_query
from infra.milestone_7_8.pilot.prepare_core_staging import CONTROLLER, price_footprint
from infra.milestone_7_8.pilot.prepare_staging_successor import PARENT, git, replace_once, retained_images, write_json
from infra.milestone_7_8.pilot_cleanup import file_hash, read, validate_review, write_new
from infra.milestone_7_8.pilot_validation import ROOT, SCANNER_OBSERVATION

REGIONAL = PARENT / "private-staging-v2/regional-pricing.json"
PREVIOUS = PARENT / scope.V5_ID
PRIOR = PARENT / ("run-" + scope.PREDECESSOR[:8])
RUNBOOK = "docs/MILESTONE_7_8_CONSOLIDATED_STAGING.md"
FINAL = PARENT / scope.PACKAGE_ID
CENTI_MILL = Decimal("0.0001")


def costing(out: Path, retail_path: Path, remaining: dict) -> dict:
    retail = read(retail_path)
    rows, footprint = price_footprint(retail, read(REGIONAL), datetime.now(UTC))
    pg = sum(Decimal(r["costUsd"]) for r in rows if r["meter"] in {"pgVcore", "pgStorage", "pgBackup"})
    restore = (pg * 6 / 13).quantize(CENTI_MILL)
    input_rate = Decimal("2.00")
    text = 200 * (15000 * input_rate + 1600 * Decimal("12")) / 1_000_000
    embedding = 160_000_000 * Decimal("0.02") / 1_000_000
    forecast = footprint + restore + text + embedding
    conservative = forecast * Decimal("1.25")
    prior = Decimal(str(read(PREVIOUS / "review-package.json")["proposedCumulativeCeilingUsd"]))
    ceiling = Decimal("56.51")
    reserve = prior - Decimal("350.89")
    totals = {"estimatedAzureCoreFootprintUsd": footprint, "estimatedIsolatedRestoreAddonUsd": restore,
              "textReserveUsd": text, "embeddingReserveUsd": embedding, "conditionalForecastUsd": forecast,
              "forecastWith25PercentUsd": conservative.quantize(CENTI_MILL),
              "priorAuthorizedExposureUsd": prior, "proposedExecutionCeilingUsd": ceiling,
              "proposedCumulativeCeilingUsd": prior + ceiling}
    if (any(Decimal(remaining["pricing"][key]) != value for key, value in totals.items())
            or remaining["pricing"]["pricingReceiptSha256"] != file_hash(retail_path)
            or prior != Decimal("686.44") or conservative > ceiling):
        raise CampaignError("the complete footprint and funding reconciliation need fresh review")
    budget = {"forecastUsd": float(forecast), "priorAttemptReserveUsd": float(reserve),
              "combinedCeilingUsd": float(reserve + ceiling), "proposedCumulativeCeilingUsd": float(prior + ceiling),
              "netCeilingIncreaseProposedUsd": float(reserve + ceiling - 50), "increaseOverLastApprovalUsd": float(ceiling)}
    meter_hash = file_hash(retail_path)
    shutil.copyfile(retail_path, out / "current-retail-rates.json")
    write_json(out / "regional-pricing.json", budget | {
        "schema": "m78-consolidated-retail-v1", "currency": "USD", "pricedAtUtc": retail["fetchedAtUtc"],
        "currentRetailSha256": meter_hash, "pricedHours": 13, "rows": rows, "billing": "unsettled",
        "componentsUsd": {key: str(value) for key, value in totals.items()}, "azureHelperAndControllerReserveUsd": "0.26",
        "isolatedRestoreHours": 6, "textAttemptsIncludingRetries": 200, "inputTokensPerAttempt": 15000,
        "maximumInputUsdPerMillion": str(input_rate), "outputTokensPerAttempt": 1600, "outputUsdPerMillion": "12",
        "embeddingTokens": 160000000, "embeddingUsdPerMillion": "0.02", "sourceUrls": remaining["pricing"]["referenceUrls"],
    })
    prior_cost = {"priorAuthorizedCumulativeUsd": str(prior), "billing": "unsettled", "actualChargesUsd": None,
                  "priorCleanupTerminalSha256": scope.CLEANUP, "priorReviewSha256": scope.PREDECESSOR}
    write_json(out / "prior-cost-reconciliation.json", prior_cost)
    write_json(out / "cost-reconciliation.json", prior_cost | {
        "currentRetailSha256": meter_hash, "newSpendingAuthorized": False, "priorReserveUsd": str(reserve),
        "combinedCeilingUsd": str(reserve + ceiling), "nextExecutionCeilingUsd": str(ceiling),
        "cumulativeCeilingProposedUsd": str(prior + ceiling), "nextExecutionForecastUsd": str(forecast),
        "nextExecutionConservativeUsd": str(conservative), "rateSnapshot": retail["fetchedAtUtc"],
    })
    config = out / "cleanup/campaign.template.json"
    write_json(config, read(config) | {"conservativeEstimateUsd": str(conservative), "resourceItems": [{
        "name": "consolidated-azure-restore-and-provider-footprint", "pricedAtUtc": retail["fetchedAtUtc"],
        "hours": 13, "hourlyUsd": "0", "fixedUsd": str(forecast)}]})
    CampaignConfig.from_document(read(config) | {"cleanupDeadlineUtc": "2030-01-01T11:01:00Z"}, allow_expired=True)
    ledger = out / "cleanup/ledger.json"
    write_json(ledger, read(ledger) | {"conservative_estimate_usd": str(conservative)})
    return budget


def reviewed_copy(package: Path, review: dict, name: str, out: Path) -> None:
    original = (package / name).resolve()
    target = (out / name).resolve()
    if (not original.is_relative_to(package.resolve()) or not target.is_relative_to(out.resolve())
            or file_hash(original) != review["files"][name]):
        raise CampaignError(f"reviewed input differs: {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, target)


def prepare(verification_path: Path, retail_path: Path, remaining_path: Path, template: Path) -> Path:
    source = git("rev-parse", "HEAD")
    verification = read(verification_path)
    if (git("status", "--porcelain") or git("branch", "--show-current") != "milestone-7-8-production-readiness-audit-local"
            or git("merge-base", source, "94175f9b") != git("rev-parse", "94175f9b")
            or verification["sourceCommit"] != source or verification["failed"] != 0 or verification["passed"] < 1
            or file_hash(verification_path.parent / verification["log"]) != verification["logSha256"]):
        raise CampaignError("current clean source and its focused rehearsal receipt are required")
    if (file_hash(PREVIOUS / "review-package.json") != scope.PREDECESSOR
            or file_hash(PRIOR / "verified-full-residue.json") != scope.CLEANUP
            or file_hash(PRIOR / "local-reconciliation/monitoring.json") != scope.LAST_MONITORING
            or file_hash(template) != staging.METRIC_READBACK_POLICY["compiledScannerTemplateSha256"]
            or FINAL.exists() or (ROOT / scope.BOUND).exists()):
        raise CampaignError("predecessors, historical receipts or unused target paths differ")
    cleanup = read(PRIOR / "verified-full-residue.json")
    if (len(cleanup["counters"]) != 48 or any(type(v) is not int or v != 0 for v in cleanup["counters"].values())
            or cleanup["controllerPreserved"] is not True or cleanup["namedVaultPurged"] is not True):
        raise CampaignError("previous teardown is incomplete")
    images = retained_images(source)
    review = read(PREVIOUS / "review-package.json")
    remaining = read(remaining_path)
    identity = {"sourceCommit": source, "accountFixture": scope.FIXTURE, "consolidatedScope": scope.MODE}
    out = Path(tempfile.mkdtemp(prefix="consolidated-seal-", dir=PARENT))
    for name in review["files"]:
        if name != "kql-semantics.json":
            reviewed_copy(PREVIOUS, review, name, out)

    def update(name, values):
        write_json(out / name, read(out / name) | values)

    for name in ("compiled-template-review.json", "private-replay.json", "local-engine-proof.json",
                 "emulator-terminal.json"):
        evidence = verification_path.parent / name
        if file_hash(evidence) != verification["rehearsalEvidenceSha256"][name]:
            raise CampaignError("local staging rehearsal evidence differs")
        shutil.copyfile(evidence, out / name)
    for name, original in {
        "controller-prior-authority.json": CONTROLLER,
        "prior-cleanup.json": "verified-full-residue.json",
        "prior-monitoring.json": "local-reconciliation/monitoring.json",
    }.items():
        shutil.copyfile(PRIOR / original, out / name)
    shutil.copyfile(template, out / "compiled/pilot.json")
    for name, digest in remaining["predecessorReceipts"].items():
        path = (PRIOR / name).resolve()
        if not path.is_relative_to(PRIOR.resolve()) or file_hash(path) != digest:
            raise CampaignError("previous execution receipt differs")
    update("carried-acceptance.json", remaining["carryForward"] | {
        "priorCleanupSha256": scope.CLEANUP, "latestMonitoringSha256": scope.LAST_MONITORING,
        "predecessorReceipts": remaining["predecessorReceipts"]})
    write_json(out / "local-verification.json", verification | {"retainedImages": images})
    remaining.update(identity | {"status": "sealed-awaiting-exact-approval", "priorReviewSha256": scope.PREDECESSOR,
                                 "nov24MonitoringSha256": scope.MONITORING, "integrityCapturePoints": list(POINTS)})
    write_json(out / "consolidated-plan.json", remaining)
    budget = costing(out, retail_path, remaining)
    primary = read(out / "planned-bindings.json")
    query = out / "queries/integrity-source-rows.kql"
    query.write_bytes(signal_query(primary["release"], primary["deployment"]).encode())
    metric_query = out / "queries/production-signals.kql"
    original = metric_query.read_text(encoding="utf-8")
    engine = read(out / "local-engine-proof.json")
    terminal = read(out / "emulator-terminal.json")
    if (engine["originalQuerySha256"] != file_hash(metric_query)
            or terminal["engineProofSha256"] != file_hash(out / "local-engine-proof.json")
            or terminal["remainingTestContainers"] != 0 or terminal["releasedLoopbackPort"] is not True):
        raise CampaignError("the engine rehearsal must bind the previous query and local teardown")
    metric_query.write_bytes(replace_once(original, V5_METRIC_VALUE_PROJECTION, METRIC_VALUE_PROJECTION).encode())
    if engine["querySha256"] != file_hash(metric_query):
        raise CampaignError("packaged query differs from the query executed by the local engine")
    queries = primary["queryFiles"] | {"integrity-source-rows": file_hash(query),
                                       "production-signals": file_hash(metric_query)}
    approved_queries = set()
    for name, checksum in queries.items():
        path = out / "queries" / (name + ".kql")
        if file_hash(path) != checksum:
            raise CampaignError(f"packaged verification query differs: {name}")
        approved_queries.add(hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest())
    documents = {RUNBOOK, "docs/MILESTONE_7_8_FULL_CLOSURE_LEDGER.md", "docs/MILESTONE_7_8_EDITABLE_AI_RELEASE_CHECKPOINT.md",
                 "docs/MILESTONE_7_8_OPERATOR_ACCESS_EXECUTION.md", *primary["reviewDocumentBindings"]}
    docs = {name: file_hash(ROOT / name) for name in documents}
    for name, operations in (("planned-bindings", scope.OPERATIONS), ("index-bindings", ["capacity"])):
        plan = read(out / (name + ".json"))
        plan.update(identity | budget | {
            "sourceCommitStatus": "committed-consolidated-operator-source", "scannerObservation": SCANNER_OBSERVATION,
            "verifyWorkerQueryBeforeUpload": True,
            "requireNativeMetricReadiness": True,
            "previousAttemptReserveUsd": budget["priorAttemptReserveUsd"], "enabledOperations": operations,
            "credentialParameterFile": primary["credentialParameterFile"].replace(PREVIOUS.name, FINAL.name),
            "credentialParameterFileSha256": file_hash(out / "credentials/application-secrets.parameters.json"),
            "queryFiles": queries, "approvedQueryHashes": sorted(approved_queries),
            "reviewDocumentBindings": docs, "temporaryCredentialCleanup": {
                "mail": "no mail credential issued", "restrictedQueryUser": primary["temporaryCredentialCleanup"]["restrictedQueryUser"]},
        })
        plan.pop("passwordResetProof", None)
        write_json(out / (name + ".json"), plan)
    update("destination-plan.bound.json", {"sourceCommit": source})
    update("candidate-gate.json", {"sourceCommit": source, "operatorSource": source})
    for path in (out / "execute").glob("*.py"):
        script = path.read_text(encoding="utf-8").replace(PREVIOUS.name, FINAL.name).replace(scope.V5_BOUND, scope.BOUND)
        if path.name == "prepare_vpn_profile.py":
            script = replace_once(script, 'out/"m78p-a712b8c940-successor-azurevpn.xml"',
                                  'out/("m78-" + run.name.removeprefix("run-") + ".xml")')
        elif path.name == "admit_private_route.py":
            script = replace_once(script, 'out=run/"vpn/private-route-admission"',
                'from infra.milestone_7_8.pilot.windows_vpn_profile import observe\n'
                'installed=observe(Path(__file__).resolve().parent.parent)\nout=run/"vpn/private-route-admission"')
            script = replace_once(script, 'def ps(label,command):',
                                  'write_new(out/"installed-profile.json",installed)\ndef ps(label,command):')
        elif path.name == "verify_full_residue.py":
            script = replace_once(script, '    client=read(run/"vpn/client-terminal-v2.json")',
                '    from infra.milestone_7_8.pilot.windows_vpn_profile import observe\n'
                '    observe(pkg, absent=True)\n    client=read(run/"vpn/client-terminal-v2.json")')
        compile(script, str(path), "exec")
        path.write_bytes(script.encode())
    foundation = (out / "FOUNDATION.md").read_text(encoding="utf-8").replace(scope.V5_BOUND, scope.BOUND).replace(PREVIOUS.name, FINAL.name)
    (out / "FOUNDATION.md").write_bytes(foundation.encode())
    shutil.copyfile(ROOT / RUNBOOK, out / "EXECUTION.md")
    (out / "APPROVAL.md").write_bytes(("Private staging requires one fresh approval binding this review, source, "
        "exception, limits and fallback. See EXECUTION.md and the sealed cost reconciliation.\n").encode())
    for name in ("operator-schedule.json", "timed/operator-schedule.json"):
        schedule = read(out / name)
        prices = remaining["pricing"]
        schedule["hardGates"]["remainingCost"] = (
            f"USD {prices['priorAuthorizedExposureUsd']} previously reserved, "
            f"{prices['proposedExecutionCeilingUsd']} execution, {prices['proposedCumulativeCeilingUsd']} cumulative."
        )
        schedule.update(identity | {"integrityCapturePoints": list(POINTS), "requiresCore": scope.DEPENDENTS,
            "scannerHold": SCANNER_OBSERVATION | {"deadlineSeconds": 900, "retry": False, "runDuringCore": True,
                                                   "prepareAndVerifyBeforeUpload": True, "postDeadlineDispatch": False}})
        write_json(out / name, schedule)
    write_json(out / "successor-scope.json", identity | {
        "scannerObservation": SCANNER_OBSERVATION, "scannerDecisionSeconds": 900, "priorCleanupSha256": scope.CLEANUP,
        "maximumDeployments": 1, "maximumPrimaryUploads": 1, "remainingCoreUploadsAfterProgress": ["queued", "deletion"],
        "maximumDiagnosticExecutions": 1, "retry": False, "requiresCore": scope.DEPENDENTS,
        "independent": remaining["independentWhileCoreHeld"], "integrityCapturePoints": list(POINTS),
        "operatorRuntime": scope.BOUND, "cleanupCounters": 48, "cleanupFallback": remaining["cleanup"]})
    write_json(out / "staging-exception.json", staging.METRIC_READBACK_POLICY)
    manifest = read(out / "manifest.json")
    update("manifest.json", identity | {"operations": scope.OPERATIONS, "compiledTemplateSha256": file_hash(template),
            "sourceBindings": {name: file_hash(ROOT / name) for name in manifest["sourceBindings"]}})
    for name, binding in (("approval", "planned-bindings"), ("index-approval", "index-bindings"), ("capacity-approval", "planned-bindings")):
        update(name + ".unapproved.json", {"approved": False, "operations": scope.OPERATIONS if name == "approval" else ["capacity"],
               "bindingsSha256": file_hash(out / (binding + ".json")), "packageSha256": file_hash(out / "manifest.json")})
    review.pop("newCumulativeAllowanceUsd", None)
    review.update(budget | {"sourceCommit": source, "packageId": scope.PACKAGE_ID, "status": "sealed-awaiting-separate-approval",
        "approved": False, "boundRuntimeDirectory": scope.BOUND, "supersedesReviewSha256": scope.PREDECESSOR,
        "stagingException": staging.METRIC_READBACK_POLICY, "modelAttemptsIncludingRetries": 200, "embeddingTokens": 160000000,
        "operatorSourceBindings": {name: file_hash(ROOT / name) for name in set(review["operatorSourceBindings"]) | scope.V6_OPERATOR_FILES},
        "candidateGateSha256": file_hash(out / "candidate-gate.json"),
        "priorCostReconciliationSha256": file_hash(out / "prior-cost-reconciliation.json"),
        "costReconciliationSha256": file_hash(out / "cost-reconciliation.json"),
        "files": {p.relative_to(out).as_posix(): file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    write_new(out / "review-package.json", review)
    digest = file_hash(out / "review-package.json")
    validate_review(out, {"approved": True, "reviewPackageSha256": digest, "sourceHead": source,
        "approveStagingExceptionSha256": file_hash(out / "staging-exception.json"), "approveExactQuotaFallback": True,
        "approvedAt": "2030-01-01T00:00:30Z", "executionStartAt": "2030-01-01T00:01:00Z"})
    if (PARENT / ("run-" + digest[:8])).exists():
        raise CampaignError("proposed journal is already used")
    out.rename(FINAL)
    return FINAL


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", required=True, type=Path)
    parser.add_argument("--retail", type=Path, default=PARENT / "consolidated-v6-preparation/retail-current.json")
    parser.add_argument("--remaining", type=Path, default=PARENT / "consolidated-v6-preparation/remaining-plan.json")
    parser.add_argument("--template", type=Path, default=PREVIOUS / "compiled/pilot.json")
    args = parser.parse_args()
    result = prepare(args.verification, args.retail, args.remaining, args.template)
    print(json.dumps({"package": result.name, "reviewSha256": file_hash(result / "review-package.json"),
                      "exceptionSha256": file_hash(result / "staging-exception.json")}))


if __name__ == "__main__":
    main()
