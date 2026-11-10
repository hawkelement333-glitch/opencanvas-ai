from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    GENERATION_PATTERN,
    SubprocessRunner,
    sanitize,
    utc,
)
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.cleanup_controller import (
    ARCHITECTURE,
    LOCAL_ARCHITECTURE_STATE,
    controller_binding_sha256,
    controller_names,
)
from infra.milestone_7_8.controller_admission import (
    digest,
    load_authority_evidence,
    validate_authority_evidence,
)
from infra.milestone_7_8.predeployment import (
    EVIDENCE_CLASS as FRESH_CONTROLLER_ADMISSION_EVIDENCE_CLASS,
    EVIDENCE_VERSION as FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION,
    PredeploymentVerificationError,
    load_validated_admission,
)

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
        raise CampaignError(
            f"refusing to replace existing generation file: {path.name}"
        )
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--output", type=Path, default=Path(".runtime/milestone_7_8"))
    parser.add_argument("--target-region", default="centralus")
    parser.add_argument("--postgres-region", default="centralus")
    parser.add_argument("--controller-region", required=True)
    parser.add_argument("--fresh-subscription-runtime", type=Path, required=True)
    parser.add_argument("--fresh-subscription-authorization", type=Path, required=True)
    parser.add_argument("--fresh-subscription-evidence", type=Path, required=True)
    parser.add_argument("--controller-authority-evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        if CAMPAIGN_PATTERN.fullmatch(args.campaign_id) is None:
            raise CampaignError("campaign identity is malformed")
        if GENERATION_PATTERN.fullmatch(args.generation_id) is None:
            raise CampaignError("generation identity is malformed")
        if args.target_region != args.postgres_region:
            raise CampaignError("single-VNet campaign resources must share a region")
        if args.output.exists():
            raise FileExistsError(args.output)
        if _git("status", "--porcelain=v1"):
            raise CampaignError("campaign preparation requires a clean repository")
        if (
            _git("branch", "--show-current")
            != "milestone-7-8-production-readiness-audit-local"
        ):
            raise CampaignError("campaign preparation branch is invalid")
        if _git(
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        ) != "refs/remotes/origin/milestone-7-8-production-readiness-audit-local":
            raise CampaignError("campaign preparation upstream is invalid")
        if len(_git("stash", "list", "--format=%H").splitlines()) != 5:
            raise CampaignError("protected stash boundary differs")
        source_head = _git("rev-parse", "HEAD")
        image_inputs = canonical_snapshot(source_head)
        cleanup_script_sha256 = hashlib.sha256(
            (
                Path(__file__).resolve().parent / "scripts/Remove-M78Campaign.ps1"
            ).read_bytes()
        ).hexdigest()
        subscription_id = os.environ.get("M78_SUBSCRIPTION_ID", "")
        tenant_id = os.environ.get("M78_TENANT_ID", "")
        try:
            uuid.UUID(subscription_id)
            uuid.UUID(tenant_id)
        except ValueError as exc:
            raise CampaignError(
                "runtime subscription or tenant binding is missing"
            ) from exc
        subscription_correlation = sanitize(subscription_id, domain="subscription")
        names = controller_names(subscription_correlation)
        try:
            admission = load_validated_admission(
                runtime_path=args.fresh_subscription_runtime,
                authorization_path=args.fresh_subscription_authorization,
                evidence_path=args.fresh_subscription_evidence,
                subscription_id=subscription_id,
                tenant_id=tenant_id,
                campaign_id=args.campaign_id,
                generation_id=args.generation_id,
                region=args.controller_region,
                controller_resource_group_name=names.resource_group,
                automation_account_name=names.account,
            )
        except PredeploymentVerificationError as exc:
            raise CampaignError(str(exc)) from exc
        observed_at = datetime.now(UTC).replace(microsecond=0)
        controller_authority = load_authority_evidence(args.controller_authority_evidence)
        verified_controller = validate_authority_evidence(controller_authority)
        if (
            verified_controller.tenant_id != tenant_id
            or verified_controller.campaign_id != args.campaign_id
            or verified_controller.generation_id != args.generation_id
        ):
            raise CampaignError("controller authority scope differs from fresh scope")
        cleanup_authority_expires = utc(observed_at + timedelta(hours=5))
        region_selection = discover_automation_region(
            SubprocessRunner(),
            subscription_id,
            observed_at=observed_at,
            controller_resource_group=names.resource_group,
            controller_account=names.account,
            subscription_correlation=subscription_correlation,
            cleanup_script_sha256=cleanup_script_sha256,
            fresh_controller_admission_evidence_sha256=admission.evidence_sha256,
            controller_required_until_utc=cleanup_authority_expires,
            controller_authority_evidence=controller_authority,
        )
        if region_selection.controller_disposition != "exact-controller-adoptable":
            raise CampaignError(
                "reusable cleanup controller must be separately provisioned and proved "
                "before campaign preparation"
            )
        cleanup_region = region_selection.selected_region
        if cleanup_region != args.controller_region:
            raise CampaignError(
                "fresh controller region differs from deterministic region selection"
            )
        region_selection_sha256 = region_selection.sha256()
        if (
            region_selection.fresh_controller_admission_evidence_sha256
            != admission.evidence_sha256
        ):
            raise CampaignError("fresh controller admission region-selection binding differs")
        candidate_regions = ",".join(region_selection.candidate_order)
        if candidate_regions != CLEANUP_CANDIDATE_REGIONS_BINDING:
            raise CampaignError("cleanup candidate region binding differs")
        offer_eligible_regions = ",".join(region_selection.offer_eligible_regions)
        generation_id = args.generation_id
        suffix = hashlib.sha256(
            f"{args.campaign_id}\0{generation_id}".encode()
        ).hexdigest()[:10]
        deadline = utc(observed_at + timedelta(hours=4))
        target_rg = f"rg-m78-{suffix}-target"
        cleanup_rg = names.resource_group
        account = names.account
        runbook = names.runbook
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
        controller_binding = controller_binding_sha256(
            subscription_id,
            resource_group=cleanup_rg,
            account=account,
            runbook=runbook,
        )
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
                    "cleanup": account,
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
            "mobius.cleanup-offer-classification": (
                region_selection.offer_classification
            ),
            "mobius.cleanup-offer-disposition": (
                region_selection.offer_eligibility_disposition
            ),
            "mobius.cleanup-offer-regions": offer_eligible_regions,
            "mobius.cleanup-offer-source": region_selection.offer_eligibility_source,
            "mobius.cleanup-offer-eligibility-sha256": (
                region_selection.offer_eligibility_sha256
            ),
            "mobius.fresh-controller-admission-sha256": admission.evidence_sha256,
            "mobius.fresh-controller-admission-version": (
                FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION
            ),
            "mobius.owner": "managed-postgresql-evidence",
            "mobius.expiry": deadline,
        }
        args.output.mkdir(parents=True, exist_ok=False)
        config_path = args.output / "campaign.json"
        runtime_path = args.output / "runtime.json"
        cleanup_path = args.output / "cleanup.parameters.json"
        campaign_path = args.output / "campaign.parameters.json"
        region_selection_path = args.output / "cleanup-region-selection.json"
        fresh_runtime_path = args.output / "fresh-subscription-runtime.json"
        fresh_authorization_path = args.output / "predeployment-read-authorization.json"
        fresh_evidence_path = args.output / "predeployment-absence-evidence.json"
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
            "cleanupOfferEligibilityDisposition": (
                region_selection.offer_eligibility_disposition
            ),
            "cleanupOfferEligibleRegions": offer_eligible_regions,
            "cleanupOfferEligibilitySource": region_selection.offer_eligibility_source,
            "cleanupOfferEligibilitySha256": (
                region_selection.offer_eligibility_sha256
            ),
            "freshControllerAdmissionEvidenceSha256": admission.evidence_sha256,
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
                "cleanupOfferEligibilitySource": (
                    region_selection.offer_eligibility_source
                ),
                "cleanupOfferEligibilitySha256": (
                    region_selection.offer_eligibility_sha256
                ),
                "freshControllerAdmissionEvidenceSha256": admission.evidence_sha256,
                "cleanupDeadlineUtc": deadline,
                "cleanupAuthorityExpiresUtc": cleanup_authority_expires,
                "automationAccountName": account,
                "cleanupRunbookName": runbook,
                "cleanupScheduleName": schedule,
                "cleanupBindingName": binding,
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
                "cleanupOfferEligibilitySource": (
                    region_selection.offer_eligibility_source
                ),
                "cleanupOfferEligibilitySha256": (
                    region_selection.offer_eligibility_sha256
                ),
                "freshControllerAdmissionEvidenceSha256": admission.evidence_sha256,
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
                "cleanupIdentityName": account,
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
            "cleanupControllerArchitecture": ARCHITECTURE,
            "cleanupControllerArmability": LOCAL_ARCHITECTURE_STATE,
            "controllerBindingSha256": controller_binding,
            "controllerAuthorityEvidenceFile": str(
                args.output / "controller-authority-evidence.json"
            ),
            "controllerAuthorityEvidenceSha256": digest(
                "m7.8/controller-authority-evidence/v1", controller_authority
            ),
            "controllerAuthorizedUntilUtc": verified_controller.controller_authorized_until_utc,
            "cleanupAuthorityExpiresUtc": cleanup_authority_expires,
            "cleanupRegion": cleanup_region,
            "cleanupRegionSelectionSha256": region_selection_sha256,
            "cleanupCandidateRegions": candidate_regions,
            "cleanupOfferClassification": region_selection.offer_classification,
            "cleanupOfferEligibilityDisposition": (
                region_selection.offer_eligibility_disposition
            ),
            "cleanupOfferEligibleRegions": offer_eligible_regions,
            "cleanupOfferEligibilitySource": region_selection.offer_eligibility_source,
            "cleanupOfferEligibilitySha256": (
                region_selection.offer_eligibility_sha256
            ),
            "freshControllerAdmissionEvidenceSha256": admission.evidence_sha256,
            "freshControllerAdmissionEvidenceVersion": (
                FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION
            ),
            "freshControllerAdmissionEvidenceClass": (
                FRESH_CONTROLLER_ADMISSION_EVIDENCE_CLASS
            ),
            "freshControllerAdmissionEvidenceObservedAtUtc": admission.observed_at_utc,
            "freshControllerAdmissionRuntimeFile": str(fresh_runtime_path),
            "freshControllerAdmissionAuthorizationFile": str(fresh_authorization_path),
            "freshControllerAdmissionEvidenceFile": str(fresh_evidence_path),
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
        _write_new(
            fresh_runtime_path,
            json.loads(args.fresh_subscription_runtime.read_text(encoding="utf-8")),
        )
        _write_new(
            fresh_authorization_path,
            json.loads(
                args.fresh_subscription_authorization.read_text(encoding="utf-8")
            ),
        )
        _write_new(fresh_evidence_path, admission.document)
        _write_new(args.output / "controller-authority-evidence.json", controller_authority)
        _write_new(region_selection_path, region_selection.document())
        _write_new(config_path, config)
        _write_new(runtime_path, runtime)
        _write_new(cleanup_path, cleanup_parameters)
        _write_new(campaign_path, campaign_parameters)
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "cleanupControllerArmability": LOCAL_ARCHITECTURE_STATE,
                    "campaignCorrelation": sanitize(
                        args.campaign_id, domain="campaign"
                    ),
                    "generationCorrelation": sanitize(
                        generation_id, domain="generation"
                    ),
                    "cleanupRegion": cleanup_region,
                    "cleanupRegionSelectionSha256": region_selection_sha256,
                    "cleanupCandidateRegions": candidate_regions,
                    "cleanupOfferClassification": (
                        region_selection.offer_classification
                    ),
                    "cleanupOfferEligibilityDisposition": (
                        region_selection.offer_eligibility_disposition
                    ),
                    "cleanupOfferEligibleRegions": offer_eligible_regions,
                    "cleanupOfferEligibilitySource": (
                        region_selection.offer_eligibility_source
                    ),
                    "cleanupOfferEligibilitySha256": (
                        region_selection.offer_eligibility_sha256
                    ),
                    "freshControllerAdmissionEvidenceSha256": admission.evidence_sha256,
                    "config": str(config_path),
                    "runtime": str(runtime_path),
                    "ledger": str(ledger_path),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except (
        CampaignError,
        FileExistsError,
        OSError,
        PredeploymentVerificationError,
    ) as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
