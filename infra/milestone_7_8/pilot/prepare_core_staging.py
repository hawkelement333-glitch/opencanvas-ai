"""Seal a single scanner diagnostic run without creating live authority."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError, parse_utc
from infra.milestone_7_8.pilot import staging_exception as staging
from infra.milestone_7_8.pilot.prepare_staging_successor import PARENT, git, retained_images, write_json
from infra.milestone_7_8.pilot_cleanup import file_hash, read, validate_review, write_new
from infra.milestone_7_8.pilot_validation import CORE_DIAGNOSTIC_SCOPE, ROOT, SCANNER_OBSERVATION

PREDECESSOR = PARENT / "private-staging-v2"
PACKAGE = PARENT / "private-staging-v3"
PRIOR = PARENT / "run-0b0335d2"
TERMINAL_SHA = "605ab2a2bd27b633ec9fe02586a298792f963219854063b823c0143a741bf6e8"
CONTROLLER = "renew/reconciliation/02-completed-authority-evidence.json"
EXECUTION_CEILING = Decimal("56.51")
PRIOR_CEILING = Decimal("516.91")


def price_footprint(retail: dict, regional: dict, now: datetime) -> tuple[list[dict], Decimal]:
    checked = parse_utc(retail["fetchedAtUtc"])
    if retail["currency"] != "USD" or not 0 <= (now - checked).total_seconds() < 86400:
        raise CampaignError("Core staging needs current USD retail prices")
    rate_entries = retail["rates"]
    hours, month = Decimal(13), Decimal(730)
    quantities = {
        "acaCpu": Decimal("3.75") * hours * 3600,
        "acaMemory": Decimal("7.5") * hours * 3600,
        "pgVcore": 2 * hours,
        "pgStorage": 32 * hours / month,
        "pgBackup": 32 * hours / month,
        "redis": 2 * hours,
        "blob": 10 * hours / month,
        "defenderBase": hours,
        "alert5min": 16 * hours / month,
        "pe": 6 * hours,
        "eventhub": hours,
        "publicIp": hours,
        "vpn": hours,
    }
    rows = []

    def add(name, group, meter_id, quantity, *, region=None, location=None, tier=0):
        entry = rate_entries[group]
        candidates = [
            row for row in entry["items"]
            if row["meterId"] == meter_id and row["currencyCode"] == "USD"
            and row["type"] == "Consumption" and row["tierMinimumUnits"] == tier
            and (region is None or row["armRegionName"] == region)
            and (location is None or row["location"] == location)
            and parse_utc(row["effectiveStartDate"]) <= now
        ]
        if entry["unreadNextPage"] or not candidates:
            raise CampaignError(f"Core staging retail meter is unproved: {name}")
        effective = max(row["effectiveStartDate"] for row in candidates)
        values = {
            (Decimal(str(row["retailPrice"])), row["unitOfMeasure"])
            for row in candidates if row["effectiveStartDate"] == effective
        }
        if len(values) != 1:
            raise CampaignError(f"Core staging retail meter is ambiguous: {name}")
        (rate, unit), = values
        rows.append({
            "meter": name, "meterId": meter_id, "region": region, "location": location,
            "tierMinimumUnits": tier, "effectiveStartDate": effective,
            "unitOfMeasure": unit, "units": str(quantity), "rateUsd": str(rate),
            "costUsd": str(quantity * rate),
        })

    for prior in regional["rows"]:
        name = prior["meter"]
        units = quantities.get(name, Decimal(prior["units"]))
        add(name, name, prior["meterId"], units, region=prior["region"], tier=5 if name == "logs" else 0)
    add("dnsResolverInbound", "privateDns", "75134e89-9779-5c46-867e-c02460344857",
        hours / month, location="Zone 1")
    add("dnsZones", "privateDns", "0b608a26-f611-4232-8192-ce81b6b57194",
        Decimal(11) * 2 / 30, location="Zone 1")
    add("dnsQueries", "privateDns", "46cff9cb-4b15-4af0-bf41-25143827fef8", Decimal(1), location="Zone 1")
    add("redisCrossRegion", "bandwidth", "767e59b7-0335-5391-adaa-5fee530face2",
        Decimal(10), region="canadacentral")
    add("internetEgress", "bandwidth", "9995d93a-7d35-4d3f-9c69-7a7fea447ef4",
        Decimal(10), region="canadacentral", tier=100)
    # Allow for controller operations and brief helper/proof overlap.
    total = sum((Decimal(row["costUsd"]) for row in rows), Decimal("0.26"))
    return rows, total.quantize(Decimal("0.0001"))


def prepare(retail_path: Path, verification_path: Path) -> Path:
    source = git("rev-parse", "HEAD")
    if git("status", "--porcelain") or git("merge-base", source, "2f64704") != git("rev-parse", "2f64704"):
        raise CampaignError("seal from the clean corrected staging source commit")
    previous_review = PREDECESSOR / "review-package.json"
    cleanup_receipt = PRIOR / "verified-full-residue.json"
    cleanup = read(cleanup_receipt)
    if (
        file_hash(previous_review) != staging.CORE_PREDECESSOR
        or file_hash(cleanup_receipt) != TERMINAL_SHA
        or len(cleanup["counters"]) != 48 or set(cleanup["counters"].values()) != {0}
        or cleanup["controllerPreserved"] is not True
        or (ROOT / staging.CORE_BOUND).exists()
        or PACKAGE.exists()
    ):
        raise CampaignError("require verified predecessor cleanup and unused package and runtime paths")
    images = retained_images(source)
    verification = read(verification_path)
    if verification["sourceCommit"] != source or verification["failed"] != 0:
        raise CampaignError("current source's local rehearsal is required")
    review = read(previous_review)
    regional = read(PREDECESSOR / "regional-pricing.json")
    retail = read(retail_path)
    rows, forecast = price_footprint(retail, regional, datetime.now(UTC))
    conservative = (forecast * Decimal("1.25")).quantize(Decimal("0.000001"))
    if conservative > EXECUTION_CEILING:
        raise CampaignError("the current estimate exceeds the supported execution ceiling")
    previous_reserve = PRIOR_CEILING - Decimal("350.89")
    combined = previous_reserve + EXECUTION_CEILING
    cumulative = PRIOR_CEILING + EXECUTION_CEILING
    budget = {
        "forecastUsd": float(forecast), "priorAttemptReserveUsd": float(previous_reserve),
        "combinedCeilingUsd": float(combined), "proposedCumulativeCeilingUsd": float(cumulative),
        "netCeilingIncreaseProposedUsd": float(combined - 50),
        "increaseOverLastApprovalUsd": float(EXECUTION_CEILING),
    }
    out = Path(tempfile.mkdtemp(prefix="core-seal-", dir=PARENT))
    for name, expected in review["files"].items():
        original, target = PREDECESSOR / name, out / name
        if not target.resolve().is_relative_to(out.resolve()) or file_hash(original) != expected:
            raise CampaignError(f"predecessor artifact differs: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)

    def update(name, values):
        file = out / name
        write_json(file, read(file) | values)

    shutil.copyfile(PRIOR / CONTROLLER, out / "controller-prior-authority.json")
    shutil.copyfile(retail_path, out / "current-retail-rates.json")
    price_hash = file_hash(out / "current-retail-rates.json")
    write_json(out / "regional-pricing.json", budget | {
        "schema": "m78-core-staging-retail-v1", "currency": "USD", "pricedAtUtc": retail["fetchedAtUtc"],
        "rows": rows, "currentRetailSha256": price_hash, "reserveUsd": "0.26",
        "conservativeEstimateUsd": str(conservative), "pricedHours": 13,
        "modelRequests": 0, "approved": False,
    })
    write_json(out / "prior-cost-reconciliation.json", {
        "priorAuthorizedCumulativeUsd": str(PRIOR_CEILING),
        "latestCleanupTerminalSha256": TERMINAL_SHA, "billing": "unsettled",
        "priorReviewSha256": staging.CORE_PREDECESSOR, "actualChargesUsd": None,
    })
    write_json(out / "cost-reconciliation.json", {
        "schema": "m78-core-staging-cost-v1", "currency": "USD", "billing": "unsettled",
        "actualChargesUsd": None, "newSpendingAuthorized": False,
        "priorAuthorizedCumulativeUsd": str(PRIOR_CEILING), "priorReserveUsd": str(previous_reserve),
        "nextExecutionCeilingUsd": str(EXECUTION_CEILING), "cumulativeCeilingProposedUsd": str(cumulative),
        "combinedCeilingUsd": str(combined), "nextExecutionForecastUsd": str(forecast),
        "nextExecutionConservativeUsd": str(conservative), "rateSnapshot": retail["fetchedAtUtc"],
        "currentRetailSha256": price_hash, "priorCleanupTerminalSha256": TERMINAL_SHA,
    })
    update("cleanup/campaign.template.json", {"conservativeEstimateUsd": str(conservative)})
    update("cleanup/ledger.json", {"conservative_estimate_usd": str(conservative)})
    plan = read(out / "planned-bindings.json")
    plan.update(budget | {
        "previousAttemptReserveUsd": float(previous_reserve),
        "credentialParameterFile": plan["credentialParameterFile"].replace(PREDECESSOR.name, PACKAGE.name),
        "sourceCommit": source, "scannerObservation": SCANNER_OBSERVATION,
        "coreDiagnosticScope": CORE_DIAGNOSTIC_SCOPE, "enabledOperations": staging.CORE_OPERATIONS,
    })
    write_json(out / "planned-bindings.json", plan)
    update("index-bindings.json", {"sourceCommit": source, "enabledOperations": []})
    update("destination-plan.bound.json", {"sourceCommit": source})
    update("candidate-gate.json", {"sourceCommit": source})
    credential_path = out / "credentials/application-secrets.parameters.json"
    credential = read(credential_path)
    credential["parameters"]["applicationSecrets"]["value"]["openai-api-key"] = staging.INERT_MODEL_KEY
    write_json(credential_path, credential)

    for path in (out / "execute").glob("*.py"):
        script = path.read_text(encoding="utf-8").replace(PREDECESSOR.name, PACKAGE.name)
        script = script.replace(".runtime/milestone_7_8/psv2", staging.CORE_BOUND)
        compile(script, str(path), "exec")
        path.write_bytes(script.encode())
    foundation = (out / "FOUNDATION.md").read_text(encoding="utf-8")
    foundation = foundation.replace(".runtime/milestone_7_8/psv2", staging.CORE_BOUND)
    foundation = foundation.replace("Index and capacity use the separately bound child files in the same approval.",
                                    "The Core diagnostic package admits account and core only.")
    (out / "FOUNDATION.md").write_bytes(foundation.encode())
    runbook = ROOT / "docs/MILESTONE_7_8_CORE_DIAGNOSTIC_STAGING.md"
    shutil.copyfile(runbook, out / "EXECUTION.md")
    for schedule in ("operator-schedule.json", "timed/operator-schedule.json"):
        write_json(out / schedule, {
            "sourceCommit": source, "scope": CORE_DIAGNOSTIC_SCOPE,
            "deadlineHoursAfterStart": review["operatorWindowHours"],
            "orderedProof": ["private-readiness", "account", "core", "stop", "verified-teardown"],
        })
    write_json(out / "staging-exception.json", staging.CORE_POLICY)
    write_json(out / "local-verification.json", verification | {"retainedImages": images})
    blob_run = PARENT / "run-51a21bf2/native-infrastructure-diagnostics"
    blob_summary = blob_run / "dedicated-native-rows-summary.json"
    observed_blob = {
        row["Category"]: row["Count"] for row in read(blob_summary)["observed"]
        if row["Table"] == "StorageBlobLogs" and row["Category"] in {"StorageRead", "StorageWrite"}
        and row["Count"] > 0
    }
    if set(observed_blob) != {"StorageRead", "StorageWrite"}:
        raise CampaignError("accepted Blob evidence is missing")
    write_json(out / "carried-acceptance.json", {
        "closed": ["PostgreSQL", "M78-D-001", "M78-D-002", "prior accepted signups"],
        "blobAccepted": observed_blob,
        "blobConfigSha256": file_hash(blob_run / "blob.json"),
        "blobRowsSha256": file_hash(blob_run / "dedicated-native-rows.native.json"),
        "blobSummarySha256": file_hash(blob_summary),
        "blobDelete": "unproved",
        "priorCleanupSha256": TERMINAL_SHA,
    })
    write_json(out / "successor-scope.json", {
        "coreDiagnosticScope": CORE_DIAGNOSTIC_SCOPE, "scannerObservation": SCANNER_OBSERVATION,
        "sourceCommit": source, "sourceReviewSha256": staging.CORE_PREDECESSOR,
        "maximumDeployments": 1, "maximumUploads": 1, "maximumDiagnosticExecutions": 1,
        "scannerDecisionSeconds": 900, "operatorRuntime": staging.CORE_BOUND,
        "cleanupCounters": 48, "cleanupFallback": ["monthly-quota-429-with-no-job", "automation-expiry"],
    })
    manifest = read(out / "manifest.json")
    update("manifest.json", {
        "sourceCommit": source, "operations": staging.CORE_OPERATIONS,
        "sourceBindings": {name: file_hash(ROOT / name) for name in manifest["sourceBindings"]},
    })
    for name, binding in (
        ("approval", "planned-bindings.json"), ("index-approval", "index-bindings.json"),
        ("capacity-approval", "planned-bindings.json"),
    ):
        update(name + ".unapproved.json", {
            "approved": False, "operations": staging.CORE_OPERATIONS if name == "approval" else [],
            "packageSha256": file_hash(out / "manifest.json"), "bindingsSha256": file_hash(out / binding),
        })
    review.update(budget | {
        "sourceCommit": source, "packageId": PACKAGE.name, "status": "sealed-awaiting-separate-approval",
        "approved": False, "modelAttemptsIncludingRetries": 0, "embeddingTokens": 0,
        "fixedHttpPartitions": {"core": 400, "account": 18, "readinessAndCleanup": 1800},
        "boundRuntimeDirectory": staging.CORE_BOUND, "stagingException": staging.CORE_POLICY,
        "supersedesReviewSha256": staging.CORE_PREDECESSOR,
        "operatorSourceBindings": {
            name: file_hash(ROOT / name) for name in review["operatorSourceBindings"]
        },
        "candidateGateSha256": file_hash(out / "candidate-gate.json"),
        "priorCostReconciliationSha256": file_hash(out / "prior-cost-reconciliation.json"),
        "costReconciliationSha256": file_hash(out / "cost-reconciliation.json"),
        "files": {p.relative_to(out).as_posix(): file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()},
    })
    path = out / "review-package.json"
    write_new(path, review)
    validate_review(out, {
        "approved": True, "reviewPackageSha256": file_hash(path), "sourceHead": source,
        "approveStagingExceptionSha256": file_hash(out / "staging-exception.json"),
        "approveExactQuotaFallback": True, "approvedAt": "2030-01-01T00:00:30Z",
        "executionStartAt": "2030-01-01T00:01:00Z",
    })
    out.rename(PACKAGE)
    return PACKAGE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retail", required=True, type=Path)
    parser.add_argument("--verification", required=True, type=Path)
    args = parser.parse_args()
    package = prepare(args.retail, args.verification)
    print(json.dumps({"package": str(package), "reviewSha256": file_hash(package / "review-package.json")}))


if __name__ == "__main__":
    main()
