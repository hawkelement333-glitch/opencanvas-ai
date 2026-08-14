from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from infra.milestone_7_8.automation_region import (
    CLEANUP_CANDIDATE_REGIONS_BINDING,
    discover_automation_region,
)
from infra.milestone_7_8.campaign import (
    CAMPAIGN_PATTERN,
    CampaignError,
    SubprocessRunner,
    sanitize,
    utc,
)
from infra.milestone_7_8.canonical_inputs import canonical_snapshot

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise CampaignError("campaign Git preflight failed")
    return completed.stdout.strip()


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise CampaignError(f"refusing to replace existing generation file: {path.name}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parameters(values: dict[str, object]) -> dict[str, object]:
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {name: {"value": value} for name, value in values.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one immutable untracked M7.8 runtime bundle"
    )
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output", type=Path, default=Path(".runtime/milestone_7_8"))
    parser.add_argument("--target-region", default="centralus")
    parser.add_argument("--postgres-region", default="centralus")
    args = parser.parse_args()
    try:
        if CAMPAIGN_PATTERN.fullmatch(args.campaign_id) is None:
            raise CampaignError("campaign identity is malformed")
        if args.target_region != args.postgres_region:
            raise CampaignError("single-VNet campaign resources must share a region")
        if args.output.exists():
            raise FileExistsError(args.output)
        if _git("status", "--porcelain=v1"):
            raise CampaignError("campaign preparation requires a clean repository")
        if _git("branch", "--show-current") != "milestone-7-8-production-readiness-audit-local":
            raise CampaignError("campaign preparation branch is invalid")
        if _git(
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        ):
            raise CampaignError("campaign preparation refuses an upstream")
        if len(_git("stash", "list", "--format=%H").splitlines()) != 5:
            raise CampaignError("protected stash boundary differs")
        source_head = _git("rev-parse", "HEAD")
        image_inputs = canonical_snapshot(source_head)
        cleanup_script_sha256 = hashlib.sha256(
            (Path(__file__).resolve().parent / "scripts/Remove-M78Campaign.ps1").read_bytes()
        ).hexdigest()
        subscription_id = os.environ.get("M78_SUBSCRIPTION_ID", "")
        tenant_id = os.environ.get("M78_TENANT_ID", "")
        try:
            uuid.UUID(subscription_id)
            uuid.UUID(tenant_id)
        except ValueError as exc:
            raise CampaignError("runtime subscription or tenant binding is missing") from exc
        observed_at = datetime.now(UTC).replace(microsecond=0)
        region_selection = discover_automation_region(
            SubprocessRunner(), subscription_id, observed_at=observed_at
        )
        cleanup_region = region_selection.selected_region
        region_selection_sha256 = region_selection.sha256()
        candidate_regions = ",".join(region_selection.candidate_order)
        if candidate_regions != CLEANUP_CANDIDATE_REGIONS_BINDING:
            raise CampaignError("cleanup candidate region binding differs")
        offer_eligible_regions = ",".join(region_selection.offer_eligible_regions)
        generation_id = f"g1-{secrets.token_hex(6)}"
        suffix = hashlib.sha256(f"{args.campaign_id}\0{generation_id}".encode()).hexdigest()[:10]
        deadline = utc(observed_at + timedelta(hours=4))
        target_rg = f"rg-m78-{suffix}-target"
        cleanup_rg = f"rg-m78-{suffix}-cleanup"
        account = f"aa-m78-{suffix}"
        runbook = f"Remove-M78Campaign-{suffix}"
        schedule = f"m78-deadline-{suffix}"
        binding = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    "solarplexus-mobius/milestone-7.8/cleanup-binding/"
                    f"{args.campaign_id}/{generation_id}/{deadline}"
                ),
            )
        )
        deleted_account_resource_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{cleanup_rg}"
            "/providers/Microsoft.Automation/automationAccounts/"
            f"{account}"
        ).casefold()
        deleted_account_binding_sha256 = hashlib.sha256(
            b"m7.8/deleted-automation-account/v1\0" + deleted_account_resource_id.encode()
        ).hexdigest()
        identity_names = {
            role: f"id-m78-{suffix}-{role}"
            for role in ("bootstrap", "migration", "api", "worker", "evidence")
        }
        manifest_binding = hashlib.sha256(
            json.dumps(
                {
                    "campaignId": args.campaign_id,
                    "generationId": generation_id,
                    "principals": identity_names,
                    "cleanup": f"cleanup-{suffix}",
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        tags = {
            "mobius.milestone": "7.8",
            "mobius.campaign": args.campaign_id,
            "mobius.generation": generation_id,
            "mobius.cleanup-deadline-utc": deadline,
            "mobius.cost-ceiling-cents": "5000",
            "mobius.cleanup-region-selection-sha256": region_selection_sha256,
            "mobius.cleanup-candidate-regions": candidate_regions,
            "mobius.cleanup-offer-classification": (region_selection.offer_classification),
            "mobius.cleanup-offer-disposition": (region_selection.offer_eligibility_disposition),
            "mobius.cleanup-offer-regions": offer_eligible_regions,
            "mobius.cleanup-offer-source": region_selection.offer_eligibility_source,
            "mobius.cleanup-offer-eligibility-sha256": (region_selection.offer_eligibility_sha256),
            "mobius.owner": "managed-postgresql-evidence",
            "mobius.expiry": deadline,
        }
        args.output.mkdir(parents=True, exist_ok=False)
        config_path = args.output / "campaign.json"
        runtime_path = args.output / "runtime.json"
        cleanup_path = args.output / "cleanup.parameters.json"
        campaign_path = args.output / "campaign.parameters.json"
        region_selection_path = args.output / "cleanup-region-selection.json"
        ledger_path = args.output / "ledger.json"
        config = {
            "campaignId": args.campaign_id,
            "generationId": generation_id,
            "subscriptionCorrelation": sanitize(subscription_id, domain="subscription"),
            "tenantCorrelation": sanitize(tenant_id, domain="tenant"),
            "targetResourceGroup": target_rg,
            "cleanupResourceGroup": cleanup_rg,
            "targetRegion": args.target_region,
            "cleanupRegion": cleanup_region,
            "postgresRegion": args.postgres_region,
            "cleanupDeadlineUtc": deadline,
            "conservativeEstimateUsd": "25.6832",
            "contingencyPercent": "25",
            "resourceItems": [
                {
                    "name": "complete-bounded-campaign-subtotal",
                    "hourlyUsd": "5.13664",
                    "hours": 4,
                    "fixedUsd": "0",
                    "pricedAtUtc": "2026-08-13T00:00:00Z",
                }
            ],
            "principalManifestSha256": manifest_binding,
            "cleanupRegionSelectionSha256": region_selection_sha256,
            "cleanupCandidateRegions": candidate_regions,
            "cleanupOfferClassification": region_selection.offer_classification,
            "cleanupOfferEligibilityDisposition": (region_selection.offer_eligibility_disposition),
            "cleanupOfferEligibleRegions": offer_eligible_regions,
            "cleanupOfferEligibilitySource": region_selection.offer_eligibility_source,
            "cleanupOfferEligibilitySha256": (region_selection.offer_eligibility_sha256),
            "imageDigest": None,
        }
        cleanup_parameters = _parameters(
            {
                "campaignId": args.campaign_id,
                "generationId": generation_id,
                "subscriptionCorrelation": config["subscriptionCorrelation"],
                "targetResourceGroupName": target_rg,
                "cleanupResourceGroupName": cleanup_rg,
                "cleanupLocation": cleanup_region,
                "cleanupRegionSelectionSha256": region_selection_sha256,
                "cleanupCandidateRegions": candidate_regions,
                "cleanupOfferClassification": region_selection.offer_classification,
                "cleanupOfferEligibilityDisposition": (
                    region_selection.offer_eligibility_disposition
                ),
                "cleanupOfferEligibleRegions": offer_eligible_regions,
                "cleanupOfferEligibilitySource": (region_selection.offer_eligibility_source),
                "cleanupOfferEligibilitySha256": (region_selection.offer_eligibility_sha256),
                "cleanupDeadlineUtc": deadline,
                "automationAccountName": account,
                "cleanupRunbookName": runbook,
                "cleanupScheduleName": schedule,
                "cleanupBindingName": binding,
                "lifecycleTags": tags,
            }
        )
        campaign_parameters = _parameters(
            {
                "campaignId": args.campaign_id,
                "generationId": generation_id,
                "resourceNameSuffix": suffix,
                "subscriptionCorrelation": config["subscriptionCorrelation"],
                "targetResourceGroupName": target_rg,
                "targetLocation": args.target_region,
                "postgresLocation": args.postgres_region,
                "cleanupLocation": cleanup_region,
                "cleanupRegionSelectionSha256": region_selection_sha256,
                "cleanupCandidateRegions": candidate_regions,
                "cleanupOfferClassification": region_selection.offer_classification,
                "cleanupOfferEligibilityDisposition": (
                    region_selection.offer_eligibility_disposition
                ),
                "cleanupOfferEligibleRegions": offer_eligible_regions,
                "cleanupOfferEligibilitySource": (region_selection.offer_eligibility_source),
                "cleanupOfferEligibilitySha256": (region_selection.offer_eligibility_sha256),
                "cleanupResourceGroupName": cleanup_rg,
                "cleanupAutomationAccountName": account,
                "tenantId": tenant_id,
                "postgresServerName": f"pgm78{suffix}",
                "postgresPrimaryZone": "1",
                "postgresStandbyZone": "2",
                "maintenanceDay": 0,
                "maintenanceHour": 7,
                "registryName": f"acrm78{suffix}",
                "containerAppsEnvironmentName": f"cae-m78-{suffix}",
                "virtualNetworkName": f"vnet-m78-{suffix}",
                "logAnalyticsWorkspaceName": f"law-m78-{suffix}",
                "administratorIdentityName": identity_names["bootstrap"],
                "migrationIdentityName": identity_names["migration"],
                "apiIdentityName": identity_names["api"],
                "workerIdentityName": identity_names["worker"],
                "evidenceIdentityName": identity_names["evidence"],
                "cleanupIdentityName": f"cleanup-{suffix}",
                "cleanupDeadlineUtc": deadline,
                "lifecycleTags": tags,
            }
        )
        runtime = {
            "subscriptionId": subscription_id,
            "sourceHead": source_head,
            "canonicalBuildInputSha256": str(image_inputs["buildInputSha256"]),
            "dockerfileSha256": str(image_inputs["dockerfileSha256"]),
            "cleanupScriptSha256": cleanup_script_sha256,
            "automationApiVersion": "2024-10-23",
            "cleanupControllerArmability": "blocked-provider-retention",
            "deletedAutomationAccountBindingSha256": (deleted_account_binding_sha256),
            "cleanupRegion": cleanup_region,
            "cleanupRegionSelectionSha256": region_selection_sha256,
            "cleanupCandidateRegions": candidate_regions,
            "cleanupOfferClassification": region_selection.offer_classification,
            "cleanupOfferEligibilityDisposition": (region_selection.offer_eligibility_disposition),
            "cleanupOfferEligibleRegions": offer_eligible_regions,
            "cleanupOfferEligibilitySource": region_selection.offer_eligibility_source,
            "cleanupOfferEligibilitySha256": (region_selection.offer_eligibility_sha256),
            "cleanupRegionSelectionFile": str(region_selection_path),
            "cleanupDeploymentName": f"m78-cleanup-{suffix}",
            "campaignDeploymentName": f"m78-campaign-{suffix}",
            "automationAccountName": account,
            "runbookName": runbook,
            "scheduleName": schedule,
            "bindingName": binding,
            "bootstrapJobName": f"job-m78-{suffix}-bootstrap",
            "migrationJobName": f"job-m78-{suffix}-migration",
            "workerJobName": f"job-m78-{suffix}-worker",
            "evidenceJobName": f"job-m78-{suffix}-evidence",
            "apiProbeJobName": f"job-m78-{suffix}-probe-api",
            "workerProbeJobName": f"job-m78-{suffix}-probe-worker",
            "migrationProbeJobName": f"job-m78-{suffix}-probe-migration",
            "recoveryJobName": f"job-m78-{suffix}-revoke",
            "recoveryRestoreJobName": f"job-m78-{suffix}-restore",
            "postgresServerName": f"pgm78{suffix}",
            "registryName": f"acrm78{suffix}",
            "logAnalyticsWorkspaceName": f"law-m78-{suffix}",
            "resourceGroupName": target_rg,
            "cleanupResourceGroupName": cleanup_rg,
            "cleanupParametersFile": str(cleanup_path),
            "campaignParametersFile": str(campaign_path),
        }
        _write_new(region_selection_path, region_selection.document())
        _write_new(config_path, config)
        _write_new(runtime_path, runtime)
        _write_new(cleanup_path, cleanup_parameters)
        _write_new(campaign_path, campaign_parameters)
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "campaignCorrelation": sanitize(args.campaign_id, domain="campaign"),
                    "generationCorrelation": sanitize(generation_id, domain="generation"),
                    "cleanupRegion": cleanup_region,
                    "cleanupRegionSelectionSha256": region_selection_sha256,
                    "cleanupCandidateRegions": candidate_regions,
                    "cleanupOfferClassification": (region_selection.offer_classification),
                    "cleanupOfferEligibilityDisposition": (
                        region_selection.offer_eligibility_disposition
                    ),
                    "cleanupOfferEligibleRegions": offer_eligible_regions,
                    "cleanupOfferEligibilitySource": (region_selection.offer_eligibility_source),
                    "cleanupOfferEligibilitySha256": (region_selection.offer_eligibility_sha256),
                    "config": str(config_path),
                    "runtime": str(runtime_path),
                    "ledger": str(ledger_path),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except (CampaignError, FileExistsError, OSError) as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
