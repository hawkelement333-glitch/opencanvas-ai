"""Rebind the approved full-closure candidate to its corrected local cleanup path."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignConfig, load_ledger, save_ledger
from infra.milestone_7_8.pilot_cleanup import (
    CAMPAIGN,
    GENERATION,
    SUFFIX,
    TARGET,
    file_hash,
    read,
)
from infra.milestone_7_8.pilot_validation import ROOT, write_new

ORIGINAL = "6cb5bd784855d77cbcabd4af0f517b579c8796b439ae3e0afd2ddb0072670dc2"
MARKER = "${cleanupDirectory}/"
ORIGIN_FILES = (
    "fresh-subscription-runtime.json",
    "predeployment-read-authorization.json",
    "predeployment-absence-evidence.json",
    "cleanup-region-selection.json",
)


def write_cleanup_templates(package: Path, origin: Path) -> None:
    output = package / "cleanup"
    old = read(origin / "campaign.json")
    origin_runtime = read(origin / "runtime.json")
    runtime = dict(origin_runtime)
    origin_suffix = old["targetResourceGroup"].split("-")[2]
    for key, value in runtime.items():
        if key.endswith("File"):
            name = Path(value).name
            runtime[key] = MARKER + name
        elif origin_suffix in value:
            runtime[key] = value.replace(origin_suffix, SUFFIX)
    runtime["pilotCleanupWindowFile"] = MARKER + "window.json"
    runtime["resourceGroupName"] = TARGET
    runtime.update(
        postgresServerName=f"pg-m78o-{SUFFIX}",
        registryName=f"crm78o{SUFFIX}",
        logAnalyticsWorkspaceName=f"law-m78o-{SUFFIX}",
    )
    names = {
        role: f"id-m78-{SUFFIX}-{role}"
        for role in ("bootstrap", "migration", "api", "worker", "evidence")
    }
    identities = {
        "campaignId": CAMPAIGN,
        "generationId": GENERATION,
        "principals": names,
        "cleanup": runtime["automationAccountName"],
    }
    config = {
        **old,
        "campaignId": CAMPAIGN,
        "generationId": GENERATION,
        "targetResourceGroup": TARGET,
        "targetRegion": "eastus",
        "postgresRegion": "eastus",
        "cleanupDeadlineUtc": "${stopProofBy}",
        "authorizedCeilingUsd": "50.00",
        "maximumHours": 10,
        "imageDigest": None,
        "contingencyPercent": "25",
        "conservativeEstimateUsd": "45.802875",
        "resourceItems": [
            {
                "name": "selected-full-closure-forecast-including-private-operator-access",
                "hourlyUsd": "0",
                "hours": 12,
                "fixedUsd": "36.6423",
                "pricedAtUtc": "2026-11-16T00:00:00Z",
            }
        ],
        "principalManifestSha256": hashlib.sha256(
            json.dumps(identities, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
    }
    # Dynamic values are produced once from the new approval and controller renewal.
    for key in (
        "sourceHead",
        "controllerAuthorizedUntilUtc",
        "cleanupAuthorityExpiresUtc",
        "controllerAuthorityEvidenceSha256",
        "bindingName",
    ):
        runtime[key] = "${" + key + "}"
    write_new(output / "campaign.template.json", config)
    write_new(output / "runtime.template.json", runtime)
    for name in ORIGIN_FILES:
        shutil.copy2(origin / name, output / name)
    common = {
        "campaignId": CAMPAIGN,
        "generationId": GENERATION,
        "targetResourceGroupName": TARGET,
        "cleanupDeadlineUtc": "${stopProofBy}",
        "costCeilingCents": 5000,
    }
    for name in ("cleanup.parameters.json", "campaign.parameters.json"):
        document = read(origin / name)
        params = document["parameters"]
        replacements = dict(common)
        if name.startswith("cleanup."):
            replacements.update(
                cleanupScheduleName=f"m78-deadline-{SUFFIX}",
                cleanupBindingName="${bindingName}",
                cleanupAuthorityExpiresUtc="${automationBindingExpiresAt}",
            )
        else:
            tags = params["lifecycleTags"]["value"]
            tags.update(
                {
                    "mobius.campaign": CAMPAIGN,
                    "mobius.generation": GENERATION,
                    "mobius.cleanup-deadline-utc": "${stopProofBy}",
                    "mobius.expiry": "${stopProofBy}",
                    "mobius.cost-ceiling-cents": "5000",
                }
            )
            replacements.update(
                lifecycleTags=tags,
                maximumHours=10,
                resourceNameSuffix=SUFFIX,
                targetLocation="eastus",
                postgresLocation="eastus",
                administratorIdentityName=names["bootstrap"],
                migrationIdentityName=names["migration"],
                apiIdentityName=names["api"],
                workerIdentityName=names["worker"],
                evidenceIdentityName=names["evidence"],
                containerAppsEnvironmentName=f"cae-m78-{SUFFIX}",
                virtualNetworkName=f"vnet-m78-{SUFFIX}",
                postgresServerName=runtime["postgresServerName"],
                registryName=runtime["registryName"],
                logAnalyticsWorkspaceName=runtime["logAnalyticsWorkspaceName"],
            )
        params.update({key: {"value": value} for key, value in replacements.items()})
        write_new(output / name, document)
    model = CampaignConfig.from_document(
        {**config, "cleanupDeadlineUtc": "2026-11-16T00:00:00Z"}, allow_expired=True
    )
    ledger_path = output / "ledger.json"
    save_ledger(ledger_path, load_ledger(ledger_path, model))


def assemble(original: Path, output: Path, origin: Path, wheels: Path) -> dict:
    original, output, origin, wheels = (
        p.resolve() for p in (original, output, origin, wheels)
    )
    original_review = read(original / "review-package.json")
    if file_hash(original / "review-package.json") != ORIGINAL or any(
        file_hash(original / name) != sha
        for name, sha in original_review["files"].items()
    ):
        raise ValueError("original approved package differs")
    if not output.is_relative_to((ROOT / ".runtime").resolve()) or output.exists():
        raise ValueError("new private package directory required")
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip():
        raise ValueError("replacement package must bind a clean source checkpoint")
    output.mkdir(parents=True, exist_ok=False)
    replace = {
        "manifest.json",
        "planned-bindings.json",
        "index-bindings.json",
        "release-bindings.json",
        "parameters.bound.json",
        "destination-plan.bound.json",
        "approval.unapproved.json",
        "index-approval.unapproved.json",
        "capacity-approval.unapproved.json",
    }
    discarded = {
        "base-review.unapproved.json",
        "parameters.partial.json",
        "destination-plan.partial.json",
        "access/EXECUTION.md",
    }
    for relative in original_review["files"]:
        if relative in replace | discarded:
            continue
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original / relative, destination)
    write_cleanup_templates(output, origin)

    manifest = read(original / "manifest.json")
    manifest["sourceCommit"] = source
    # Probe validation reads these files from the packed archive. Keep control
    # plane sources bound by the review rather than packing the entire operator.
    manifest["sourceBindings"] = {
        relative: file_hash(ROOT / relative) for relative in manifest["sourceBindings"]
    }
    manifest["remainingBindings"] = [
        "replacement approval time and fresh controller deadline renewal",
        "native provider readbacks and synthetic application account IDs",
    ]
    write_new(output / "manifest.json", manifest)
    for name in (
        "planned-bindings.json",
        "index-bindings.json",
        "destination-plan.bound.json",
    ):
        data = read(original / name)
        data["sourceCommit"] = source
        data.update(campaignId=CAMPAIGN, generationId=GENERATION)
        if name != "destination-plan.bound.json":
            scope = data["targetResourceGroupId"]
            if not scope.endswith("/" + TARGET):
                raise ValueError("original target differs")
            data["frontendResourceId"] = (
                scope
                + f"/providers/Microsoft.App/containerApps/ca-m78p-{SUFFIX}-frontend"
            )
        write_new(output / name, data)
    data = read(original / "parameters.bound.json")
    data["parameters"].update(
        campaignId={"value": CAMPAIGN}, generationId={"value": GENERATION}
    )
    write_new(output / "parameters.bound.json", data)
    shutil.copy2(original / "release-bindings.json", output / "release-bindings.json")
    for name, binding in (
        ("approval", "planned-bindings.json"),
        ("index-approval", "index-bindings.json"),
        ("capacity-approval", "planned-bindings.json"),
    ):
        approval = read(original / f"{name}.unapproved.json")
        approval.update(
            packageSha256=file_hash(output / "manifest.json"),
            bindingsSha256=file_hash(output / binding),
            approved=False,
        )
        write_new(output / f"{name}.unapproved.json", approval)
    wheel_manifest = wheels / "probe-wheels-manifest.json"
    shutil.copy2(wheel_manifest, output / "wheel-manifest.json")
    for wheel in read(wheel_manifest)["wheels"]:
        filename = wheel["name"]
        data = wheels / "probe-wheels-universal" / filename
        if Path(filename).name != filename or file_hash(data) != wheel["sha256"]:
            raise ValueError("retained wheel differs from lock")
        destination = output / "wheels" / filename
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(data, destination)
    companion = ROOT / "docs/MILESTONE_7_8_FULL_CLOSURE_REPLACEMENT.md"
    shutil.copy2(companion, output / "EXECUTION.md")
    review = {
        **original_review,
        "schema": "m78-full-closure-replacement-v1",
        "supersedesReviewSha256": ORIGINAL,
        "sourceCommit": source,
        "status": "prepared-for-replacement-approval",
        "approved": False,
        "operatorWindowHours": {
            "readiness": 2,
            "proofStop": 10,
            "automationExpiry": 11,
            "operatorCleanupExpiry": 12,
        },
        "campaignId": CAMPAIGN,
        "generationId": GENERATION,
        "targetResourceGroup": TARGET,
        "runtimeDelivery": "bind from replacement approval and fresh controller renewal",
        "files": {
            path.relative_to(output).as_posix(): file_hash(path)
            for path in output.rglob("*")
            if path.is_file()
        },
    }
    write_new(output / "review-package.json", review)
    return {
        "reviewPackageSha256": file_hash(output / "review-package.json"),
        "sourceCommit": source,
        "fileCount": len(review["files"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("original", "output", "origin", "wheels"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(assemble(args.original, args.output, args.origin, args.wheels)))


if __name__ == "__main__":
    main()
