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
from infra.milestone_7_8.pilot import consolidated as scope, staging_exception as staging
from infra.milestone_7_8.pilot.integrity_windows import POINTS, signal_query
from infra.milestone_7_8.pilot.prepare_core_staging import CONTROLLER, price_footprint
from infra.milestone_7_8.pilot.prepare_staging_successor import PARENT, git, retained_images, write_json
from infra.milestone_7_8.pilot_cleanup import file_hash, read, validate_review, write_new
from infra.milestone_7_8.pilot_validation import ROOT, SCANNER_OBSERVATION

FULL = PARENT / "private-staging-v2"
NARROW = PARENT / "private-staging-v3"
PRIOR = PARENT / ("run-" + scope.PREDECESSOR[:8])
RUNBOOK = "docs/MILESTONE_7_8_CONSOLIDATED_STAGING.md"
FINAL = PARENT / scope.PACKAGE_ID
CENTI_MILL = Decimal("0.0001")


def costing(out: Path, retail_path: Path, remaining: dict) -> dict:
    retail = read(retail_path)
    rows, footprint = price_footprint(retail, read(FULL / "regional-pricing.json"), datetime.now(UTC))
    pg = sum(Decimal(r["costUsd"]) for r in rows if r["meter"] in {"pgVcore", "pgStorage", "pgBackup"})
    restore = (pg * 6 / 13).quantize(CENTI_MILL)
    text = 200 * (15000 * Decimal("2.50") + 1600 * Decimal("12")) / 1_000_000
    embedding = 160_000_000 * Decimal("0.02") / 1_000_000
    forecast = footprint + restore + text + embedding
    conservative = forecast * Decimal("1.25")
    prior = Decimal(str(read(NARROW / "review-package.json")["proposedCumulativeCeilingUsd"]))
    ceiling = Decimal("56.51")
    reserve = prior - Decimal("350.89")
    totals = {"estimatedAzureCoreFootprintUsd": footprint, "estimatedIsolatedRestoreAddonUsd": restore,
              "textReserveUsd": text, "embeddingReserveUsd": embedding, "conditionalForecastUsd": forecast,
              "forecastWith25PercentUsd": conservative.quantize(CENTI_MILL),
              "priorAuthorizedExposureUsd": prior, "proposedExecutionCeilingUsd": ceiling,
              "proposedCumulativeCeilingUsd": prior + ceiling}
    if (any(Decimal(remaining["pricing"][key]) != value for key, value in totals.items())
            or prior != Decimal("573.42") or conservative > ceiling):
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
        "maximumInputUsdPerMillion": "2.50", "outputTokensPerAttempt": 1600, "outputUsdPerMillion": "12",
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


def prepare(verification_path: Path, retail_path: Path, remaining_path: Path) -> Path:
    source = git("rev-parse", "HEAD")
    verification = read(verification_path)
    if (git("status", "--porcelain") or git("branch", "--show-current") != "milestone-7-8-production-readiness-audit-local"
            or git("merge-base", source, "c7930284") != git("rev-parse", "c7930284")
            or verification["sourceCommit"] != source or verification["failed"] != 0 or verification["passed"] < 1
            or file_hash(verification_path.parent / verification["log"]) != verification["logSha256"]):
        raise CampaignError("current clean source and its focused rehearsal receipt are required")
    if (file_hash(FULL / "review-package.json") != staging.CORE_PREDECESSOR
            or file_hash(NARROW / "review-package.json") != scope.PREDECESSOR
            or file_hash(PRIOR / "verified-full-residue.json") != scope.CLEANUP
            or file_hash(PRIOR / "alert-reconciliation/run-monitoring-reconciliation.json") != scope.MONITORING
            or FINAL.exists() or (ROOT / scope.BOUND).exists()):
        raise CampaignError("predecessors, historical receipts or unused target paths differ")
    cleanup = read(PRIOR / "verified-full-residue.json")
    if len(cleanup["counters"]) != 48 or any(cleanup["counters"].values()) or not cleanup["controllerPreserved"]:
        raise CampaignError("previous teardown is incomplete")
    images = retained_images(source)
    review, last = read(FULL / "review-package.json"), read(NARROW / "review-package.json")
    remaining = read(remaining_path)
    identity = {"sourceCommit": source, "accountFixture": scope.FIXTURE, "consolidatedScope": scope.MODE}
    out = Path(tempfile.mkdtemp(prefix="consolidated-seal-", dir=PARENT))
    for name in review["files"]:
        reviewed_copy(FULL, review, name, out)

    def update(name, values):
        write_json(out / name, read(out / name) | values)

    for name in ("controller-prior-authority.json", "nov24-monitoring.json"):
        original = PRIOR / (CONTROLLER if name.startswith("controller") else "alert-reconciliation/run-monitoring-reconciliation.json")
        shutil.copyfile(original, out / name)
    reviewed_copy(NARROW, last, "carried-acceptance.json", out)
    update("carried-acceptance.json", remaining["carryForward"] | {
        "priorCleanupSha256": scope.CLEANUP, "nov24MonitoringSha256": scope.MONITORING,
        "accountAdmissionReconciliationSha256": file_hash(PRIOR / "account-gate-reconciliation.json")})
    write_json(out / "local-verification.json", verification | {"retainedImages": images})
    remaining.update(identity | {"status": "sealed-awaiting-exact-approval", "priorReviewSha256": scope.PREDECESSOR,
                                 "nov24MonitoringSha256": scope.MONITORING, "integrityCapturePoints": list(POINTS)})
    write_json(out / "consolidated-plan.json", remaining)
    budget = costing(out, retail_path, remaining)
    primary = read(out / "planned-bindings.json")
    query = out / "queries/integrity-source-rows.kql"
    query.write_bytes(signal_query(primary["release"], primary["deployment"]).encode())
    queries = primary["queryFiles"] | {"integrity-source-rows": file_hash(query)}
    approved_queries = set()
    for name, checksum in queries.items():
        path = out / "queries" / (name + ".kql")
        if file_hash(path) != checksum:
            raise CampaignError(f"packaged verification query differs: {name}")
        approved_queries.add(hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest())
    documents = {RUNBOOK, "docs/MILESTONE_7_8_EDITABLE_AI_RELEASE_CHECKPOINT.md",
                 "docs/MILESTONE_7_8_OPERATOR_ACCESS_EXECUTION.md", *primary["reviewDocumentBindings"]}
    docs = {name: file_hash(ROOT / name) for name in documents}
    for name, operations in (("planned-bindings", scope.OPERATIONS), ("index-bindings", ["capacity"])):
        plan = read(out / (name + ".json"))
        plan.update(identity | budget | {
            "sourceCommitStatus": "committed-consolidated-operator-source", "scannerObservation": SCANNER_OBSERVATION,
            "previousAttemptReserveUsd": budget["priorAttemptReserveUsd"], "enabledOperations": operations,
            "credentialParameterFile": primary["credentialParameterFile"].replace(FULL.name, FINAL.name),
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
        reviewed_copy(NARROW, last, path.relative_to(out).as_posix(), out)
        script = path.read_text(encoding="utf-8").replace(NARROW.name, FINAL.name).replace(staging.CORE_BOUND, scope.BOUND)
        compile(script, str(path), "exec")
        path.write_bytes(script.encode())
    foundation = (out / "FOUNDATION.md").read_text(encoding="utf-8").replace(".runtime/milestone_7_8/psv2", scope.BOUND)
    (out / "FOUNDATION.md").write_bytes(foundation.encode())
    shutil.copyfile(ROOT / RUNBOOK, out / "EXECUTION.md")
    (out / "APPROVAL.md").write_bytes(("Private staging requires one fresh approval binding this review, source, "
        "exception, limits and fallback. See EXECUTION.md and the sealed cost reconciliation.\n").encode())
    for name in ("operator-schedule.json", "timed/operator-schedule.json"):
        schedule = read(out / name)
        schedule["hardGates"]["remainingCost"] = "USD 573.42 previously reserved, 56.51 execution, 629.93 cumulative."
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
    write_json(out / "staging-exception.json", staging.CONSOLIDATED_POLICY)
    manifest = read(out / "manifest.json")
    update("manifest.json", identity | {"operations": scope.OPERATIONS,
            "sourceBindings": {name: file_hash(ROOT / name) for name in manifest["sourceBindings"]}})
    for name, binding in (("approval", "planned-bindings"), ("index-approval", "index-bindings"), ("capacity-approval", "planned-bindings")):
        update(name + ".unapproved.json", {"approved": False, "operations": scope.OPERATIONS if name == "approval" else ["capacity"],
               "bindingsSha256": file_hash(out / (binding + ".json")), "packageSha256": file_hash(out / "manifest.json")})
    review.pop("newCumulativeAllowanceUsd", None)
    review.update(budget | {"sourceCommit": source, "packageId": scope.PACKAGE_ID, "status": "sealed-awaiting-separate-approval",
        "approved": False, "boundRuntimeDirectory": scope.BOUND, "supersedesReviewSha256": scope.PREDECESSOR,
        "stagingException": staging.CONSOLIDATED_POLICY, "modelAttemptsIncludingRetries": 200, "embeddingTokens": 160000000,
        "operatorSourceBindings": {name: file_hash(ROOT / name) for name in set(review["operatorSourceBindings"]) | scope.OPERATOR_FILES},
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
    parser.add_argument("--retail", type=Path, default=PARENT / "core-staging-preparation/retail-current.json")
    parser.add_argument("--remaining", type=Path, default=PARENT / "consolidated-staging-preparation/remaining-plan.json")
    args = parser.parse_args()
    result = prepare(args.verification, args.retail, args.remaining)
    print(json.dumps({"package": result.name, "reviewSha256": file_hash(result / "review-package.json"),
                      "exceptionSha256": file_hash(result / "staging-exception.json")}))


if __name__ == "__main__":
    main()
