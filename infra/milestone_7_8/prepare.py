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

from infra.milestone_7_8.campaign import CAMPAIGN_PATTERN, CampaignError, sanitize, utc
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
    parser.add_argument("--cleanup-region", default="westus")
    args = parser.parse_args()
    try:
        if CAMPAIGN_PATTERN.fullmatch(args.campaign_id) is None:
            raise CampaignError("campaign identity is malformed")
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
        generation_id = f"g1-{secrets.token_hex(6)}"
        suffix = hashlib.sha256(f"{args.campaign_id}\0{generation_id}".encode()).hexdigest()[:10]
        deadline = utc(datetime.now(UTC).replace(microsecond=0) + timedelta(hours=4))
        target_rg = f"rg-m78-{suffix}-target"
        cleanup_rg = f"rg-m78-{suffix}-cleanup"
        account = f"aa-m78-{suffix}"
        runbook = f"Remove-M78Campaign-{suffix}"
        schedule = f"m78-deadline-{suffix}"
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
            "mobius.owner": "managed-postgresql-evidence",
            "mobius.expiry": deadline,
        }
        args.output.mkdir(parents=True, exist_ok=False)
        config_path = args.output / "campaign.json"
        runtime_path = args.output / "runtime.json"
        cleanup_path = args.output / "cleanup.parameters.json"
        campaign_path = args.output / "campaign.parameters.json"
        ledger_path = args.output / "ledger.json"
        config = {
            "campaignId": args.campaign_id,
            "generationId": generation_id,
            "subscriptionCorrelation": sanitize(subscription_id, domain="subscription"),
            "tenantCorrelation": sanitize(tenant_id, domain="tenant"),
            "targetResourceGroup": target_rg,
            "cleanupResourceGroup": cleanup_rg,
            "targetRegion": args.target_region,
            "cleanupRegion": args.cleanup_region,
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
            "imageDigest": None,
        }
        cleanup_parameters = _parameters(
            {
                "campaignId": args.campaign_id,
                "generationId": generation_id,
                "subscriptionCorrelation": config["subscriptionCorrelation"],
                "targetResourceGroupName": target_rg,
                "cleanupResourceGroupName": cleanup_rg,
                "cleanupLocation": args.cleanup_region,
                "cleanupDeadlineUtc": deadline,
                "automationAccountName": account,
                "cleanupRunbookName": runbook,
                "cleanupScheduleName": schedule,
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
            "cleanupDeploymentName": f"m78-cleanup-{suffix}",
            "campaignDeploymentName": f"m78-campaign-{suffix}",
            "automationAccountName": account,
            "runbookName": runbook,
            "scheduleName": schedule,
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
