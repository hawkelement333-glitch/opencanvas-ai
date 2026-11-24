"""Admission of the shared staging fixture and its Core-dependent operations."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from uuid import UUID

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.pilot_cleanup import file_hash, read
from infra.milestone_7_8.pilot_validation import (
    APPLICATION_OPERATIONS, DELIVERY_OPERATIONS, INTERVENTION_OPERATIONS, SCANNER_OBSERVATION,
)

PACKAGE_ID = "private-staging-v5"
BOUND = ".runtime/milestone_7_8/psv5"
PREDECESSOR = "c82665416a05a4d3427e88fc62c8cf04836cf96b108f41765e12a125224965e0"
V4_ID = "private-staging-v4"
V4_BOUND = ".runtime/milestone_7_8/psv4"
V4_PREDECESSOR = "f5797e580aee7c35b823bb33ea3b2c77e45988c32db88f65f7c1e95d6c9a74d0"
V3_CLEANUP = "e555cb4cba133922e410a27846b6bb3e2247031cf87850a6fd777e1e751b7493"
CLEANUP = "4b8b2ff1cfa0963b0b178a48ec16d8c76a7a63d3981352673ab3a0544390f63f"
LAST_MONITORING = "bd48370ed54ecc9f2a25af668dd537711b2669e100c1abf149ead30217a9c1bb"
MONITORING = "c4a8414b2d525403c94b058bb8f685cc5f25257a176420f96f375f89f26dbb53"
MODE = "consolidated-full-core-v1"
INDEPENDENT = ("query", "telemetry", "alerts", "provider-observation")
OPERATIONS = [
    *INDEPENDENT, *APPLICATION_OPERATIONS,
    *(op for op in DELIVERY_OPERATIONS if op.startswith("activity-delivery-")), *INTERVENTION_OPERATIONS,
]
DEPENDENTS = ["delivery", "isolated-restore", "capacity", "editable-ai"]
FIXTURE = {
    "coreAccounts": ["primary", "secondary"], "distinctUsersAndWorkspaces": True,
    "initialUpload": "primary", "remainingCoreDocuments": ["queued", "deletion"],
    "capacityAdditionalAccountsAfterCore": 4,
}
OPERATOR_FILES = {
    "infra/milestone_7_8/pilot/consolidated.py",
    "infra/milestone_7_8/pilot/integrity_windows.py",
    "infra/milestone_7_8/pilot/pack_execution.py",
    "infra/milestone_7_8/pilot/helper_job_patch.py",
    "infra/milestone_7_8/pilot_application_probe.py",
    "infra/milestone_7_8/pilot_validation.py",
}


def validate_package(package: Path, review: dict) -> None:
    from infra.milestone_7_8.pilot.integrity_windows import POINTS, signal_query
    from infra.milestone_7_8.destination_acceptance import METRIC_VALUE_PROJECTION

    plan = read(package / "planned-bindings.json")
    scope = read(package / "successor-scope.json")
    manifest = read(package / "manifest.json")
    index = read(package / "index-bindings.json")
    current = review.get("packageId") == PACKAGE_ID
    expected = (PACKAGE_ID, BOUND, PREDECESSOR, CLEANUP) if current else (
        V4_ID, V4_BOUND, V4_PREDECESSOR, V3_CLEANUP
    )
    if (
        (review.get("packageId"), review.get("boundRuntimeDirectory"),
         review.get("supersedesReviewSha256"), scope.get("priorCleanupSha256")) != expected
        or not {"consolidated-plan.json", "carried-acceptance.json", "nov24-monitoring.json",
                "current-retail-rates.json", "local-verification.json"} <= review["files"].keys()
        or file_hash(package / "nov24-monitoring.json") != MONITORING
        or scope.get("requiresCore") != DEPENDENTS
        or scope.get("maximumDeployments") != 1 or scope.get("maximumPrimaryUploads") != 1
        or scope.get("maximumDiagnosticExecutions") != 1 or scope.get("retry") is not False
        or scope.get("integrityCapturePoints") != list(POINTS)
        or any(p.get("consolidatedScope") != MODE or p.get("accountFixture") != FIXTURE
               or p.get("sourceCommit") != review["sourceCommit"] or "coreDiagnosticScope" in p
               for p in (plan, index, scope, manifest))
        or any(p.get("scannerObservation") != SCANNER_OBSERVATION for p in (plan, scope))
        or manifest["operations"] != OPERATIONS or plan["enabledOperations"] != OPERATIONS
        or plan.get("scannerDecisionPolicy", {}).get("totalSeconds") != 900
        or index.get("enabledOperations") != ["capacity"]
        or review.get("modelAttemptsIncludingRetries") != 200 or review.get("embeddingTokens") != 160_000_000
    ):
        raise CampaignError("consolidated scope, accounts or Core dependencies differ")
    if current:
        metric_query = package / "queries/production-signals.kql"
        if (plan.get("verifyWorkerQueryBeforeUpload") is not True or index.get("verifyWorkerQueryBeforeUpload") is not True
                or file_hash(package / "prior-cleanup.json") != CLEANUP
                or file_hash(package / "prior-monitoring.json") != LAST_MONITORING
                or not metric_query.read_text(encoding="utf-8").rstrip().endswith(METRIC_VALUE_PROJECTION)
                or plan["queryFiles"].get("production-signals") != file_hash(metric_query)
                or manifest["compiledTemplateSha256"] != file_hash(package / "compiled/pilot.json")):
            raise CampaignError("predecessor evidence, scanner template or exact metric query differs")
    query = package / "queries/integrity-source-rows.kql"
    if (query.read_text(encoding="utf-8") != signal_query(plan["release"], plan["deployment"])
            or plan["queryFiles"].get("integrity-source-rows") != file_hash(query)
            or index["queryFiles"] != plan["queryFiles"] or index["approvedQueryHashes"] != plan["approvedQueryHashes"]):
        raise CampaignError("integrity source capture must bind the deployed release and queries")
    for name, bound, operations in (
        ("approval", "planned-bindings", OPERATIONS), ("capacity-approval", "planned-bindings", ["capacity"]),
        ("index-approval", "index-bindings", ["capacity"]),
    ):
        approval = read(package / (name + ".unapproved.json"))
        if (approval.get("approved") is not False or approval["operations"] != operations
                or approval["bindingsSha256"] != file_hash(package / (bound + ".json"))
                or approval["packageSha256"] != file_hash(package / "manifest.json")):
            raise CampaignError("consolidated proof template does not bind its exact scope")

    credentials = package / "credentials/application-secrets.parameters.json"
    data = read(credentials)["parameters"]["applicationSecrets"]["value"]
    capacity = package / "timed/capacity/retained-00.json"
    auxiliary = read(capacity)["accounts"]
    provider = read(package / "credentials/provider-bindings.json")
    addresses = [data["opencanvas-pilot-email"], data["opencanvas-pilot-secondary-email"],
                 *(row["email"] for row in auxiliary)]
    if (file_hash(credentials) != plan["credentialParameterFileSha256"]
            or file_hash(capacity) != plan["capacityFixturePackageSha256"] or len(auxiliary) != 4
            or any(not isinstance(x, str) or not x.strip() for x in addresses)
            or len({address.strip().casefold() for address in addresses}) != 6
            or not all([data["opencanvas-pilot-password"], data["opencanvas-pilot-secondary-password"],
                        *(row["password"] for row in auxiliary)])
            or provider["openai"]["entitlementConfirmedByOwner"] is not True
            or provider["noProviderAuthenticationPerformed"] is not True
            or not data.get("openai-api-key") or data["openai-api-key"] == "unused-no-model-credential"):
        raise CampaignError("two Core and four conditional capacity identities must be available")


def accepted_export(run: Path, plan: dict, operation: str) -> tuple[Path, dict]:
    from infra.milestone_7_8.pilot.core_proof_operator import proof_disposition

    root = run / ("proof-" + operation)
    path = root / "export" / (operation + ".json")
    receipt = read(path)
    marker = read(root / "accepted.json")
    execution = read(root / "evidence-execution.json")["execution"]
    terminal = read(root / "evidence-terminal.json")
    if (marker.get("operation") != operation or marker.get("resultSha256") != file_hash(path)
            or marker.get("execution") != execution or terminal["name"] != execution
            or proof_disposition(receipt, plan, execution, operation, terminal["properties"]["status"]) != "accepted"):
        raise CampaignError("the current run needs an accepted native " + operation + " export")
    return path, receipt


def require_two_signups(receipt: dict) -> tuple[str, str]:
    ids = receipt.get("userId"), receipt.get("secondaryUserId")
    try:
        valid = all(isinstance(value, str) and str(UUID(value)) == value for value in ids)
    except ValueError:
        valid = False
    if (receipt.get("accountsReady") is not True or receipt.get("accountCreated") is not True
            or receipt.get("accountActions") != {"primary": "signup", "secondary": "signup"}
            or ids[0] == ids[1] or not valid):
        raise CampaignError("two distinct same-run synthetic account signups required")
    return ids


def accepted_accounts(run: Path, plan: dict) -> tuple[str, str]:
    _, receipt = accepted_export(run, plan, "account")
    return require_two_signups(receipt)


def accepted_core(run: Path, plan: dict) -> Path:
    from infra.milestone_7_8.pilot.scanner_operator import job_binding, job_state

    primary, secondary = accepted_accounts(run, plan)
    path, receipt = accepted_export(run, plan, "core")
    fixture = receipt["fixture"]
    foreign = fixture["foreign"]
    if (fixture["userId"] != primary or foreign["userId"] != secondary
            or any(not fixture.get(k) or not foreign.get(k) or foreign[k] == fixture[k]
                   for k in ("workspaceId", "canvasId"))):
        raise CampaignError("the accepted Core fixture needs both admitted identities and independent scopes")
    root = run / "scanner-in-window"
    restore = read(root / "worker-read-restoration.json")
    last = restore.get("lastNativeReadback", "")
    if (restore.get("verified") is not True or restore.get("lastProvisioningState") != "Succeeded"
            or restore.get("differencesFromOriginal") != [] or restore.get("executionPendingOrUnknown") is not False
            or not re.fullmatch(r"worker-read-restored-[0-9]+\.native\.json", last)):
        raise CampaignError("verified helper restoration required for dependent proof")
    def native(name):
        record = read(root / name)
        if record["exitCode"] != 0:
            raise CampaignError("helper native read failed")
        body = json.loads(record["stdout"])
        if body["properties"]["provisioningState"] != "Succeeded" or body["id"].casefold() != plan["helperJobResourceId"].casefold():
            raise CampaignError("helper native readback does not match")
        return job_state(body)
    before, after = native("worker-read-original.native.json"), native(last)
    if job_binding(before) != job_binding(after) or before["properties"]["template"] != after["properties"]["template"]:
        raise CampaignError("helper native configuration or template differs")
    return path


def guard_dispatch(package: Path, arguments: list[str], inputs: dict[str, str]) -> None:
    operation = arguments[0]
    if operation not in OPERATIONS:
        raise CampaignError("operation outside consolidated approval")
    review = package / "review-package.json"
    run = package.parent / ("run-" + file_hash(review)[:8])
    if (run / "stop-proof-intent.json").exists():
        raise CampaignError("proof has stopped")
    if operation == "account" or operation in INDEPENDENT:
        return
    plan = read(package / "planned-bindings.json")
    if operation == "core":
        accepted_accounts(run, plan)
        return
    fixture_path = accepted_core(run, plan)
    if "--fixture" in arguments:
        name = Path(arguments[arguments.index("--fixture") + 1]).name
        if name not in inputs or file_hash(Path(inputs[name])) != file_hash(fixture_path):
            raise CampaignError("downstream transport requires this run's accepted Core fixture")


def main() -> None:
    from infra.milestone_7_8.pilot.core_proof_operator import Campaign

    parser = argparse.ArgumentParser(description="Read the current run's dependent-stage admission.")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--bound", type=Path, required=True)
    parser.add_argument("--stage", choices=DEPENDENTS, required=True)
    args = parser.parse_args()
    context = Campaign(args.package, args.bound)
    context.policy.check()
    context.admit()
    if context.plan.get("consolidatedScope") != MODE:
        raise CampaignError("the consolidated package is required")
    fixture = accepted_core(context.run, context.plan)
    print(json.dumps({"stage": args.stage, "coreGate": "passed", "coreExportSha256": file_hash(fixture)}))


if __name__ == "__main__":
    main()
