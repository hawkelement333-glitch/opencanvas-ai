"""Seal the one locally authorized successor from retained staging evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from decimal import Decimal
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.pilot import staging_exception
from infra.milestone_7_8.pilot_cleanup import (
    approved_window,
    file_hash,
    read,
    validate_review,
    write_new,
)
from infra.milestone_7_8.pilot_validation import ROOT, SCANNER_OBSERVATION

RUNTIME = ROOT / ".runtime/milestone_7_8"
PARENT = RUNTIME / "full-closure-prerequisites"
OLD = PARENT / "private-staging-v1"
NEW = PARENT / "private-staging-v2"
PRIOR_RUN = PARENT / "run-51a21bf2"
BASE = "53cfa0073f40856644359946fc334875263c3a2f"
BOUND = ".runtime/milestone_7_8/psv2"
SCOPE_DOC = "docs/MILESTONE_7_8_PRIVATE_STAGING_SUCCESSOR.md"
TERMINAL_SHA = "b5dd40d2fe1e3b3a93b93bfc97c9ab226ddad96a82fd967c4054cd7e35e1d245"


def git(*args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=ROOT, text=True).strip()


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise CampaignError("exact retained script block differs")
    return source.replace(before, after, 1)


def sealed_copy(review: dict, out: Path) -> None:
    for name, expected in review["files"].items():
        target = out / name
        if not target.resolve().is_relative_to(out.resolve()) or file_hash(OLD / name) != expected:
            raise CampaignError("retained staging package file differs")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(OLD / name, target)


def retained_images(source: str) -> dict:
    bindings = read(OLD / "release-bindings.json")
    if canonical_snapshot(source) != canonical_snapshot(BASE):
        raise CampaignError("API image build inputs changed since the checkpoint")
    if git(
        "diff",
        "--name-only",
        BASE,
        source,
        "--",
        "apps/web",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "package.json",
        "LICENSE",
        "COPYRIGHT",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
    ):
        raise CampaignError("frontend runtime build inputs changed since the checkpoint")
    staging_exception.verify_frontend_endorsement(OLD / "signing")
    receipts = {}
    for kind, relative in (
        ("api", "a6/image.tar"),
        ("frontend", "full-closure-local/web3/image.tar"),
    ):
        archive = RUNTIME / relative
        expected = bindings[kind]["imageIndexDigest"]
        index_hash = expected.removeprefix("sha256:")
        with tarfile.open(archive, "r:") as tar:
            (index,) = [m for m in tar.getmembers() if m.name == f"blobs/sha256/{index_hash}"]
            if not index.isfile() or not 0 < index.size <= 65_536:
                raise CampaignError("retained OCI index entry differs")
            with tar.extractfile(index) as stream:
                digest = f"sha256:{hashlib.sha256(stream.read()).hexdigest()}"
        staging_exception.validate_local_image(kind, archive, {"digest": digest}, bindings[kind])
        receipts[kind] = {
            "indexDigest": digest,
            "archiveSha256": bindings[kind]["archiveSha256"],
            "archive": relative,
        }
    return receipts


def update_queries(out: Path, plan: dict) -> None:
    verified = RUNTIME / "local-53cfa007/verification"
    record = read(verified / "verification-queries.json")
    catalog = verified / "catalog.json"
    if (
        record["sourceReviewSha256"] != staging_exception.PRIOR_REVIEW
        or record["release"] != plan["release"]
        or record["deployment"] != plan["deployment"]
        or file_hash(catalog) != record["catalogSha256"]
        or read(catalog) != read(out / "parameters.bound.json")["parameters"]["catalog"]["value"]
    ):
        raise CampaignError("local verification catalog differs from the sealed ARM parameters")
    shutil.copyfile(catalog, out / "catalog.json")
    query_paths = {path.relative_to(out).as_posix() for path in (out / "queries").glob("*.kql")}
    for name, expected in record["querySha256"].items():
        if name not in query_paths or file_hash(verified / name) != expected:
            raise CampaignError("retained verification query differs")
        shutil.copyfile(verified / name, out / name)
    pg = plan["databaseResourceId"]
    blob = plan["targetResourceGroupId"] + (
        "/providers/Microsoft.Storage/storageAccounts/stm78oa712b8c940"
    )
    for name, query in {
        "postgresql-logs": (
            f"PostgreSQLFlexServerLogs\n| where _ResourceId =~ {json.dumps(pg)}\n"
            '| extend Category=tostring(column_ifexists("Category", "PostgreSQLLogs"))\n'
            '| where Category == "PostgreSQLLogs"\n'
        ),
        "blob-delete": (
            "StorageBlobLogs\n| where _ResourceId in~ ("
            f"{json.dumps(blob)}, {json.dumps(blob + '/blobServices/default')})\n"
            '| where Category == "StorageDelete"\n'
        ),
    }.items():
        target = out / "queries" / (name + ".kql")
        target.write_bytes(
            (
                query + "| summarize Count=count(), First=min(TimeGenerated), "
                "Last=max(TimeGenerated) by Category\n"
            ).encode()
        )
    queries = sorted((out / "queries").glob("*.kql"))
    plan["queryFiles"] = {path.stem: file_hash(path) for path in queries}
    plan["approvedQueryHashes"] = sorted(
        {hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest() for path in queries}
    )


def cost_records(out: Path, review: dict, plan: dict) -> None:
    prior = read(out / "cost-reconciliation.json")
    # One 0.5-vCPU/1-GiB 90-second execution costs at most $0.00189 in the
    # retained meter snapshot. Round to one cent for the helper and query margin.
    addition = Decimal("0.01")
    forecast = Decimal(prior["nextExecutionForecastUsd"]) + addition
    conservative = Decimal(prior["nextExecutionConservativeUsd"]) + addition
    allowance = Decimal(prior["nextExecutionCeilingUsd"])
    old_ceiling = Decimal(prior["cumulativeCeilingProposedUsd"])
    reserve = Decimal(prior["priorReserveUsd"]) + allowance
    combined = reserve + allowance
    cumulative = old_ceiling + allowance
    update = {
        "priorAttemptReserveUsd": float(reserve),
        "combinedCeilingUsd": float(combined),
        "forecastUsd": float(forecast),
        "increaseOverLastApprovalUsd": float(allowance),
        "netCeilingIncreaseProposedUsd": float(cumulative - Decimal("400.89")),
        "proposedCumulativeCeilingUsd": float(cumulative),
    }
    review.update(update)
    plan.update(
        forecastUsd=float(forecast),
        previousAttemptReserveUsd=float(reserve),
        combinedCeilingUsd=float(combined),
        proposedCumulativeCeilingUsd=float(cumulative),
        netCeilingIncreaseProposedUsd=update["netCeilingIncreaseProposedUsd"],
    )
    write_json(
        out / "prior-cost-reconciliation.json",
        {
            "billing": "unsettled",
            "latestCleanupTerminalSha256": TERMINAL_SHA,
            "priorReviewSha256": staging_exception.PRIOR_REVIEW,
            "priorCostReconciliationSha256": file_hash(OLD / "cost-reconciliation.json"),
            "priorRunForecastUsd": prior["nextExecutionForecastUsd"],
            "priorRunCeilingUsd": str(allowance),
            "priorAuthorizedCumulativeUsd": str(old_ceiling),
            "postedCostIsUnattributed": True,
            "settledActualChargesUsd": None,
        },
    )
    write_json(
        out / "cost-reconciliation.json",
        {
            "schema": "m78-private-staging-successor-cost-v1",
            "currency": "USD",
            "billing": "unsettled",
            "actualChargesUsd": None,
            "newSpendingAuthorized": False,
            "priorAuthorizedCumulativeUsd": str(old_ceiling),
            "priorReserveUsd": str(reserve),
            "nextExecutionCeilingUsd": str(allowance),
            "combinedCeilingUsd": str(combined),
            "cumulativeCeilingProposedUsd": str(cumulative),
            "nextExecutionForecastUsd": str(forecast),
            "nextExecutionConservativeUsd": str(conservative),
            "incrementForOneHelperUsd": str(addition),
            "rateSnapshot": prior["rateSnapshot"],
            "priorCleanupTerminalSha256": TERMINAL_SHA,
            "coverage": (
                "full prior authorization carried once; "
                "no settled or overlapping posted costs added"
            ),
        },
    )
    pricing_path = out / "regional-pricing.json"
    price = read(pricing_path)
    price.update(
        update,
        conservativeEstimateUsd=str(conservative),
        combinedConservativeEstimateUsd=str(reserve + conservative),
        combinedCeilingProposedUsd=float(combined),
        successorHelperAllowanceUsd=str(addition),
    )
    write_json(pricing_path, price)
    campaign_path = out / "cleanup/campaign.template.json"
    campaign = read(campaign_path)
    campaign["conservativeEstimateUsd"] = str(conservative)
    write_json(campaign_path, campaign)
    ledger_path = out / "cleanup/ledger.json"
    ledger = read(ledger_path)
    ledger["conservative_estimate_usd"] = str(conservative)
    write_json(ledger_path, ledger)


def write_json(path: Path, value: dict) -> None:
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def update_scripts(out: Path) -> None:
    for path in (out / "execute").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        source = source.replace("private-staging-v1", NEW.name).replace(
            ".runtime/milestone_7_8/psv1", BOUND
        )
        if path.name == "verify_full_residue.py":
            source = replace_once(
                source,
                'CampaignConfig.from_json(b/"campaign.json")',
                'CampaignConfig.from_json(b/"campaign.json",allow_expired=True)',
            )
            # Reuse the native-proved alias reconciliation from the prior cleanup,
            # keeping the full terminal verifier and its accounting checks.
            reconciliation = (PRIOR_RUN / "resume-terminal-residue-role-alias.py").read_text(
                encoding="utf-8"
            )
            retained = read(PRIOR_RUN / "terminal-residue-role-alias-reconciliation-source.json")
            if (
                file_hash(PRIOR_RUN / "resume-terminal-residue-role-alias.py")
                != retained["localReconcilerSha256"]
            ):
                raise CampaignError("native-proved role alias reconciliation differs")
            detail = reconciliation.split("require_exact='''", 1)[1].split("'''", 1)[0]
            source = replace_once(
                source,
                '    assert observed_role["id"].casefold()'
                '==prior_role["id"].casefold()==role.casefold()',
                detail,
            )
        compile(source, str(path), "exec")
        path.write_bytes(source.encode())
    path = out / "FOUNDATION.md"
    path.write_bytes(
        path.read_text(encoding="utf-8").replace(".runtime/milestone_7_8/psv1", BOUND).encode()
    )
    path = out / "EXECUTION.md"
    old_instructions = path.read_text(encoding="utf-8").split("## Exact command order", 1)[1]
    instructions = replace_once(
        old_instructions,
        "Use the same core operator for\n"
        "diagnose, repair and core-retry only on its declared scanner path.",
        "Use the core operator's in-window observation. Use diagnose only for the primary hold "
        "and only if no in-window start was attempted. "
        "The successor excludes repair and core-retry.",
    ).replace(".runtime/milestone_7_8/psv1", BOUND)
    path.write_bytes(
        (
            (ROOT / SCOPE_DOC).read_text(encoding="utf-8")
            + "\n## Exact command order"
            + instructions
        ).encode()
    )
    (out / "APPROVAL.md").write_bytes(
        b"# Separate successor execution approval\n\n"
        b"Bind approval to the exact review, source commit and staging exception SHA-256. "
        b"Approval covers the single private deployment, its sealed proof scope, private "
        b"registry publication and interactive access, the cost ceilings, and exact cleanup "
        b"including the early monthly-quota fallback. Record the actual approval time "
        b"and the first whole UTC minute after it. No approved runtime files exist yet.\n"
    )


def prepare(local_evidence: Path) -> dict:
    source = git("rev-parse", "HEAD")
    if git("status", "--porcelain") or git("merge-base", BASE, source) != BASE:
        raise CampaignError("seal only the clean reviewed successor commit")
    old_review_path = OLD / "review-package.json"
    if file_hash(old_review_path) != staging_exception.PRIOR_REVIEW:
        raise CampaignError("the exact prior staging package is required")
    cleanup_path = PRIOR_RUN / "verified-full-residue.json"
    cleanup = read(cleanup_path)
    if (
        file_hash(cleanup_path) != TERMINAL_SHA
        or len(cleanup["counters"]) != 48
        or set(cleanup["counters"].values()) != {0}
        or cleanup["controllerPreserved"] is not True
    ):
        raise CampaignError("prior campaign removal is unproved")
    local = read(local_evidence)
    if local["baseline"] != BASE or local["baselineReproduced"] != 3 or not local["focusedPassed"]:
        raise CampaignError("successor rehearsal is missing")
    images = retained_images(source)
    review = read(old_review_path)
    if NEW.exists():
        raise CampaignError("successor package already exists; reconcile it")
    out = Path(tempfile.mkdtemp(prefix="s2-", dir=PARENT))
    sealed_copy(review, out)
    plan = read(out / "planned-bindings.json")
    plan.update(sourceCommit=source, scannerObservation=SCANNER_OBSERVATION)
    plan["credentialParameterFile"] = plan["credentialParameterFile"].replace(OLD.name, NEW.name)
    plan["sourceCommitStatus"] = "committed-successor-operator-source"
    cost_records(out, review, plan)
    update_queries(out, plan)
    write_json(out / "planned-bindings.json", plan)
    update_scripts(out)

    for filename in (
        "destination-plan.bound.json",
        "index-bindings.json",
        "operator-schedule.json",
        "timed/operator-schedule.json",
        "candidate-gate.json",
    ):
        path = out / filename
        data = path.read_text(encoding="utf-8").replace(review["sourceCommit"], source)
        if filename.endswith("operator-schedule.json"):
            schedule = json.loads(data)
            schedule["scannerHold"] = {
                **SCANNER_OBSERVATION,
                "deadlineSeconds": 900,
                "retry": False,
                "runDuringCore": True,
                "postDeadlineOnlyIfNeverDispatched": True,
            }
            write_json(path, schedule)
        elif filename == "index-bindings.json":
            index = json.loads(data)
            for key in (
                "forecastUsd",
                "combinedCeilingUsd",
                "previousAttemptReserveUsd",
                "proposedCumulativeCeilingUsd",
                "netCeilingIncreaseProposedUsd",
                "approvedQueryHashes",
                "credentialParameterFile",
            ):
                index[key] = plan[key]
            write_json(path, index)
        else:
            path.write_bytes(data.encode())
    controller = PRIOR_RUN / "renew/reconciliation/02-completed-authority-evidence.json"
    shutil.copyfile(controller, out / "controller-prior-authority.json")
    write_json(out / "staging-exception.json", staging_exception.SUCCESSOR_POLICY)
    write_json(out / "local-verification.json", local | {"retainedImages": images})
    write_json(
        out / "successor-scope.json",
        {
            "scannerObservation": SCANNER_OBSERVATION,
            "cleanupCounters": 48,
            "scannerDecisionSeconds": 900,
            "operatorRuntime": BOUND,
            "freshApprovals": 1,
            "sourceCommit": source,
            "sourceReviewSha256": staging_exception.PRIOR_REVIEW,
            "independent": ["transport", "workbook-render", "eligible-alerts", "infrastructure"],
            "requiresCore": ["delivery", "isolated-restore", "capacity", "editable-ai"],
            "closed": ["PostgreSQL", "M78-D-001", "M78-D-002", "accepted-signups"],
            "historicalCleanupSha256": TERMINAL_SHA,
        },
    )

    manifest = read(out / "manifest.json")
    manifest.update(
        sourceCommit=source,
        catalogSha256=file_hash(out / "catalog.json"),
        sourceBindings={name: file_hash(ROOT / name) for name in manifest["sourceBindings"]},
    )
    write_json(out / "manifest.json", manifest)
    for filename, binding in (
        ("approval", "planned-bindings.json"),
        ("index-approval", "index-bindings.json"),
        ("capacity-approval", "planned-bindings.json"),
    ):
        path = out / (filename + ".unapproved.json")
        child = read(path)
        child.update(
            approved=False,
            packageSha256=file_hash(out / "manifest.json"),
            bindingsSha256=file_hash(out / binding),
        )
        write_json(path, child)
    review.update(
        sourceCommit=source,
        operatorSourceBindings={
            name: file_hash(ROOT / name) for name in review["operatorSourceBindings"]
        },
        stagingException=staging_exception.SUCCESSOR_POLICY,
        supersedesReviewSha256=staging_exception.PRIOR_REVIEW,
        boundRuntimeDirectory=BOUND,
        candidateGateSha256=file_hash(out / "candidate-gate.json"),
        priorCostReconciliationSha256=file_hash(out / "prior-cost-reconciliation.json"),
        costReconciliationSha256=file_hash(out / "cost-reconciliation.json"),
        status="sealed-successor-awaiting-separate-approval",
        approved=False,
        files={
            path.relative_to(out).as_posix(): file_hash(path)
            for path in sorted(out.rglob("*"))
            if path.is_file()
        },
    )
    review_path = out / "review-package.json"
    write_new(review_path, review)
    approval = {
        "approved": True,
        "reviewPackageSha256": file_hash(review_path),
        "sourceHead": source,
        "approveStagingExceptionSha256": file_hash(out / "staging-exception.json"),
        "approveExactQuotaFallback": True,
        "approvedAt": "2030-01-01T00:00:30Z",
        "executionStartAt": "2030-01-01T00:01:00Z",
    }
    validate_review(out, approval)
    approved_window(review, approval)
    out.rename(NEW)
    return {
        "reviewSha256": approval["reviewPackageSha256"],
        "exceptionSha256": approval["approveStagingExceptionSha256"],
        "sourceCommit": source,
        "files": len(review["files"]),
        "approved": False,
        "package": str(NEW),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-evidence", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.local_evidence)))


if __name__ == "__main__":
    main()
