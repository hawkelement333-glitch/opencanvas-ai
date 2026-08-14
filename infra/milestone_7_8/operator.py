from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_8.automation_region import (
    automation_region_discovery_commands,
    generated_policy_read_contract,
    select_automation_region_from_results,
    selection_from_document,
)
from infra.milestone_7_8.campaign import (
    ORDER,
    RESIDUE_KEYS,
    CampaignConfig,
    CampaignError,
    CleanupBinding,
    Phase,
    SubprocessRunner,
    load_ledger,
    parse_utc,
    sanitize,
    save_ledger,
    terminal_receipt,
)

CONTROL_PLANE_FIELDS = {
    "primaryZone",
    "standbyZone",
    "haMode",
    "maintenanceDay",
    "maintenanceHour",
    "storageGiB",
    "storageTier",
    "backupRetentionDays",
    "geoBackup",
    "latencyP95Ms",
    "azureReservedConnections",
    "poolCeilings",
    "rolloutOverlap",
    "operatorConsumers",
    "observedPeak",
    "safetyReserve",
    "maxConnections",
}
IMAGE_SCAN_FIELDS = {
    "version",
    "sourceHead",
    "canonicalBuildInputSha256",
    "imageDigest",
    "scanner",
    "scannerVersion",
    "scannedAtUtc",
    "result",
    "criticalFindings",
    "highFindings",
}

RUNTIME_FIELDS = {
    "subscriptionId",
    "sourceHead",
    "canonicalBuildInputSha256",
    "dockerfileSha256",
    "cleanupScriptSha256",
    "cleanupRegion",
    "cleanupRegionSelectionSha256",
    "cleanupOfferClassification",
    "cleanupOfferEligibilityDisposition",
    "cleanupOfferEligibleRegions",
    "cleanupOfferEligibilitySource",
    "cleanupOfferEligibilitySha256",
    "cleanupRegionSelectionFile",
    "cleanupDeploymentName",
    "campaignDeploymentName",
    "automationAccountName",
    "runbookName",
    "scheduleName",
    "bootstrapJobName",
    "migrationJobName",
    "workerJobName",
    "evidenceJobName",
    "apiProbeJobName",
    "workerProbeJobName",
    "migrationProbeJobName",
    "recoveryJobName",
    "recoveryRestoreJobName",
    "postgresServerName",
    "registryName",
    "logAnalyticsWorkspaceName",
    "resourceGroupName",
    "cleanupResourceGroupName",
    "cleanupParametersFile",
    "campaignParametersFile",
}
CLEANUP_PARAMETER_FIELDS = {
    "campaignId",
    "generationId",
    "subscriptionCorrelation",
    "targetResourceGroupName",
    "cleanupResourceGroupName",
    "cleanupLocation",
    "cleanupRegionSelectionSha256",
    "cleanupOfferClassification",
    "cleanupOfferEligibilityDisposition",
    "cleanupOfferEligibleRegions",
    "cleanupOfferEligibilitySource",
    "cleanupOfferEligibilitySha256",
    "cleanupDeadlineUtc",
    "automationAccountName",
    "cleanupRunbookName",
    "cleanupScheduleName",
    "lifecycleTags",
}
CAMPAIGN_PARAMETER_FIELDS = {
    "campaignId",
    "generationId",
    "resourceNameSuffix",
    "subscriptionCorrelation",
    "targetResourceGroupName",
    "targetLocation",
    "postgresLocation",
    "cleanupLocation",
    "cleanupRegionSelectionSha256",
    "cleanupOfferClassification",
    "cleanupOfferEligibilityDisposition",
    "cleanupOfferEligibleRegions",
    "cleanupOfferEligibilitySource",
    "cleanupOfferEligibilitySha256",
    "cleanupResourceGroupName",
    "cleanupAutomationAccountName",
    "tenantId",
    "postgresServerName",
    "postgresPrimaryZone",
    "postgresStandbyZone",
    "maintenanceDay",
    "maintenanceHour",
    "registryName",
    "containerAppsEnvironmentName",
    "virtualNetworkName",
    "logAnalyticsWorkspaceName",
    "administratorIdentityName",
    "migrationIdentityName",
    "apiIdentityName",
    "workerIdentityName",
    "evidenceIdentityName",
    "cleanupIdentityName",
    "cleanupDeadlineUtc",
    "lifecycleTags",
}

OPERATION_PHASE = {
    "preflight": Phase.PREFLIGHT,
    "correlate": Phase.CORRELATED,
    "capacity-check": Phase.CAPACITY_CHECKED,
    "cost-gate": Phase.COST_GATED,
    "scope-create": Phase.SCOPE_CREATED,
    "cleanup-deploy": Phase.CLEANUP_DEPLOYED,
    "cleanup-arm": Phase.CLEANUP_ARMED,
    "cleanup-verify": Phase.CLEANUP_VERIFIED,
    "billable-start": Phase.BILLABLE_STARTED,
    "deploy": Phase.INFRASTRUCTURE_DEPLOYED,
    "image-decision": Phase.IMAGE_DECIDED,
    "bootstrap": Phase.DATABASE_BOOTSTRAPPED,
    "migrate": Phase.MIGRATED,
    "evidence": Phase.EVIDENCE_EXECUTED,
    "dispose": Phase.DISPOSED,
    "cleanup": Phase.CLEANING,
    "cleanup-wait": Phase.CLEANED,
    "residue": Phase.RESIDUE_VERIFIED,
    "finalize": Phase.FINALIZED,
}


def load_runtime(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != RUNTIME_FIELDS
        or not all(isinstance(item, str) and item for item in value.values())
    ):
        raise CampaignError("operator runtime fields are incomplete")
    try:
        uuid.UUID(value["subscriptionId"])
    except ValueError as exc:
        raise CampaignError("operator subscription binding is malformed") from exc
    if (
        re.fullmatch(r"[a-f0-9]{40}", value["sourceHead"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["canonicalBuildInputSha256"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["dockerfileSha256"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["cleanupScriptSha256"]) is None
    ):
        raise CampaignError("operator source or image binding is malformed")
    return value


def _load_arm_parameter_values(path: Path, *, expected: set[str]) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {"$schema", "contentVersion", "parameters"}
        or value.get("contentVersion") != "1.0.0.0"
        or not isinstance(value.get("parameters"), dict)
        or set(value["parameters"]) != expected
    ):
        raise CampaignError("operator parameter bundle fields are invalid")
    result: dict[str, object] = {}
    for name, item in value["parameters"].items():
        if not isinstance(item, dict) or set(item) != {"value"}:
            raise CampaignError("operator parameter value is malformed")
        result[name] = item["value"]
    return result


def validate_prepared_bundle(
    runtime_path: Path,
    runtime: dict[str, str],
    config: CampaignConfig,
) -> None:
    if (
        runtime["resourceGroupName"] != config.target_resource_group
        or runtime["cleanupResourceGroupName"] != config.cleanup_resource_group
        or sanitize(runtime["subscriptionId"], domain="subscription")
        != config.subscription_correlation
    ):
        raise CampaignError("operator runtime scope or correlation differs")
    suffix_match = re.fullmatch(
        r"rg-m78-([a-f0-9]{10})-target", config.target_resource_group
    )
    if suffix_match is None or config.cleanup_resource_group != (
        f"rg-m78-{suffix_match.group(1)}-cleanup"
    ):
        raise CampaignError("operator campaign scopes are not one generation")
    suffix = suffix_match.group(1)
    runtime_directory = runtime_path.resolve().parent

    def sibling(name: str) -> Path:
        candidate = Path(runtime[name])
        resolved = (
            (Path.cwd() / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
        if resolved.parent != runtime_directory:
            raise CampaignError(
                "operator parameter file escaped its private generation"
            )
        return resolved

    cleanup = _load_arm_parameter_values(
        sibling("cleanupParametersFile"), expected=CLEANUP_PARAMETER_FIELDS
    )
    campaign = _load_arm_parameter_values(
        sibling("campaignParametersFile"), expected=CAMPAIGN_PARAMETER_FIELDS
    )
    selection_path = sibling("cleanupRegionSelectionFile")
    selection = selection_from_document(
        json.loads(selection_path.read_text(encoding="utf-8"))
    )
    selection_sha256 = selection.sha256()
    offer_eligible_regions = ",".join(selection.offer_eligible_regions)
    if (
        selection.selected_region != config.cleanup_region
        or selection_sha256 != config.cleanup_region_selection_sha256
        or selection.offer_classification != config.cleanup_offer_classification
        or selection.offer_eligibility_disposition
        != config.cleanup_offer_eligibility_disposition
        or offer_eligible_regions != config.cleanup_offer_eligible_regions
        or selection.offer_eligibility_source != config.cleanup_offer_eligibility_source
        or selection.offer_eligibility_sha256 != config.cleanup_offer_eligibility_sha256
        or runtime["cleanupRegion"] != config.cleanup_region
        or runtime["cleanupRegionSelectionSha256"] != selection_sha256
        or runtime["cleanupOfferClassification"] != config.cleanup_offer_classification
        or runtime["cleanupOfferEligibilityDisposition"]
        != config.cleanup_offer_eligibility_disposition
        or runtime["cleanupOfferEligibleRegions"]
        != config.cleanup_offer_eligible_regions
        or runtime["cleanupOfferEligibilitySource"]
        != config.cleanup_offer_eligibility_source
        or runtime["cleanupOfferEligibilitySha256"]
        != config.cleanup_offer_eligibility_sha256
    ):
        raise CampaignError(
            "operator cleanup region or offer selection binding differs"
        )
    common_expected = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "targetResourceGroupName": config.target_resource_group,
        "cleanupResourceGroupName": config.cleanup_resource_group,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
    }
    if any(
        cleanup.get(key) != expected for key, expected in common_expected.items()
    ) or any(
        campaign.get(key) != expected for key, expected in common_expected.items()
    ):
        raise CampaignError("operator parameter campaign binding differs")
    expected_runtime = {
        "cleanupDeploymentName": f"m78-cleanup-{suffix}",
        "campaignDeploymentName": f"m78-campaign-{suffix}",
        "automationAccountName": f"aa-m78-{suffix}",
        "runbookName": f"Remove-M78Campaign-{suffix}",
        "scheduleName": f"m78-deadline-{suffix}",
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
    }
    if any(runtime.get(key) != expected for key, expected in expected_runtime.items()):
        raise CampaignError("operator runtime generation name differs")
    identity_names = {
        "bootstrap": campaign.get("administratorIdentityName"),
        "migration": campaign.get("migrationIdentityName"),
        "api": campaign.get("apiIdentityName"),
        "worker": campaign.get("workerIdentityName"),
        "evidence": campaign.get("evidenceIdentityName"),
    }
    if (
        campaign.get("resourceNameSuffix") != suffix
        or campaign.get("cleanupIdentityName") != f"cleanup-{suffix}"
        or any(
            identity_names[role] != f"id-m78-{suffix}-{role}" for role in identity_names
        )
        or len(set(identity_names.values())) != 5
        or campaign.get("targetLocation") != config.target_region
        or campaign.get("postgresLocation") != config.postgres_region
        or campaign.get("cleanupLocation") != config.cleanup_region
        or campaign.get("cleanupRegionSelectionSha256")
        != config.cleanup_region_selection_sha256
        or campaign.get("cleanupOfferClassification")
        != config.cleanup_offer_classification
        or campaign.get("cleanupOfferEligibilityDisposition")
        != config.cleanup_offer_eligibility_disposition
        or campaign.get("cleanupOfferEligibleRegions")
        != config.cleanup_offer_eligible_regions
        or campaign.get("cleanupOfferEligibilitySource")
        != config.cleanup_offer_eligibility_source
        or campaign.get("cleanupOfferEligibilitySha256")
        != config.cleanup_offer_eligibility_sha256
        or campaign.get("postgresPrimaryZone") != "1"
        or campaign.get("postgresStandbyZone") != "2"
        or campaign.get("maintenanceDay") != 0
        or campaign.get("maintenanceHour") != 7
        or campaign.get("containerAppsEnvironmentName") != f"cae-m78-{suffix}"
        or campaign.get("virtualNetworkName") != f"vnet-m78-{suffix}"
        or cleanup.get("cleanupLocation") != config.cleanup_region
        or cleanup.get("cleanupRegionSelectionSha256")
        != config.cleanup_region_selection_sha256
        or cleanup.get("cleanupOfferClassification")
        != config.cleanup_offer_classification
        or cleanup.get("cleanupOfferEligibilityDisposition")
        != config.cleanup_offer_eligibility_disposition
        or cleanup.get("cleanupOfferEligibleRegions")
        != config.cleanup_offer_eligible_regions
        or cleanup.get("cleanupOfferEligibilitySource")
        != config.cleanup_offer_eligibility_source
        or cleanup.get("cleanupOfferEligibilitySha256")
        != config.cleanup_offer_eligibility_sha256
        or campaign.get("cleanupAutomationAccountName")
        != runtime["automationAccountName"]
        or cleanup.get("automationAccountName") != runtime["automationAccountName"]
        or cleanup.get("cleanupRunbookName") != runtime["runbookName"]
        or cleanup.get("cleanupScheduleName") != runtime["scheduleName"]
        or campaign.get("postgresServerName") != runtime["postgresServerName"]
        or campaign.get("registryName") != runtime["registryName"]
        or campaign.get("logAnalyticsWorkspaceName")
        != runtime["logAnalyticsWorkspaceName"]
    ):
        raise CampaignError("operator parameter resource or identity binding differs")
    tenant_id = campaign.get("tenantId")
    if not isinstance(tenant_id, str):
        raise CampaignError("operator tenant binding is malformed")
    try:
        uuid.UUID(tenant_id)
    except ValueError as exc:
        raise CampaignError("operator tenant binding is malformed") from exc
    if sanitize(tenant_id, domain="tenant") != config.tenant_correlation:
        raise CampaignError("operator tenant correlation differs")
    expected_tags = {
        "mobius.milestone": "7.8",
        "mobius.campaign": config.campaign_id,
        "mobius.generation": config.generation_id,
        "mobius.cleanup-deadline-utc": config.cleanup_deadline_utc,
        "mobius.cost-ceiling-cents": "5000",
        "mobius.cleanup-region-selection-sha256": config.cleanup_region_selection_sha256,
        "mobius.cleanup-offer-classification": config.cleanup_offer_classification,
        "mobius.cleanup-offer-disposition": (
            config.cleanup_offer_eligibility_disposition
        ),
        "mobius.cleanup-offer-regions": config.cleanup_offer_eligible_regions,
        "mobius.cleanup-offer-source": config.cleanup_offer_eligibility_source,
        "mobius.cleanup-offer-eligibility-sha256": (
            config.cleanup_offer_eligibility_sha256
        ),
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.expiry": config.cleanup_deadline_utc,
    }
    if (
        cleanup.get("lifecycleTags") != expected_tags
        or campaign.get("lifecycleTags") != expected_tags
    ):
        raise CampaignError("operator lifecycle tags differ")
    planned = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "principals": identity_names,
        "cleanup": f"cleanup-{suffix}",
    }
    if (
        hashlib.sha256(
            json.dumps(planned, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        != config.principal_manifest_sha256
    ):
        raise CampaignError("operator prepared principal plan differs")


def command_plan(
    operation: str,
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    control_plane_evidence: str | None = None,
) -> tuple[tuple[str, ...], ...]:
    rg = runtime["resourceGroupName"]
    cleanup_rg = runtime["cleanupResourceGroupName"]
    account = runtime["automationAccountName"]
    runbook = runtime["runbookName"]
    if operation == "preflight":
        return (
            ("git", "status", "--porcelain=v1"),
            ("git", "rev-parse", "HEAD"),
            ("git", "branch", "--show-current"),
            (
                "git",
                "for-each-ref",
                "--format=%(upstream)",
                "refs/heads/milestone-7-8-production-readiness-audit-local",
            ),
            ("git", "stash", "list", "--format=%H"),
            ("az", "version", "--output", "json"),
            (
                sys.executable,
                "-m",
                "infra.milestone_7_8.canonical_inputs",
                "--treeish",
                "HEAD",
            ),
        )
    if operation == "correlate":
        return (("az", "account", "show", "--output", "json"),)
    if operation == "capacity-check":
        providers = tuple(
            (
                "az",
                "provider",
                "show",
                "--namespace",
                namespace,
                "--output",
                "json",
            )
            for namespace in (
                "Microsoft.DBforPostgreSQL",
                "Microsoft.App",
                "Microsoft.ContainerRegistry",
                "Microsoft.ManagedIdentity",
                "Microsoft.Automation",
                "Microsoft.OperationalInsights",
            )
        )
        automation_region_commands = automation_region_discovery_commands(
            runtime["subscriptionId"]
        )
        return (
            *providers,
            (
                "az",
                "postgres",
                "flexible-server",
                "list-skus",
                "--location",
                config.postgres_region,
                "--output",
                "json",
            ),
            (
                "az",
                "vm",
                "list-usage",
                "--location",
                config.target_region,
                "--output",
                "json",
            ),
            (
                "az",
                "acr",
                "check-name",
                "--name",
                runtime["registryName"],
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "post",
                "--url",
                (
                    "https://management.azure.com/subscriptions/"
                    + runtime["subscriptionId"]
                    + "/providers/Microsoft.DBforPostgreSQL/checkNameAvailability"
                    + "?api-version=2024-08-01"
                ),
                "--body",
                json.dumps(
                    {
                        "name": runtime["postgresServerName"],
                        "type": "Microsoft.DBforPostgreSQL/flexibleServers",
                    },
                    separators=(",", ":"),
                ),
                "--output",
                "json",
            ),
            *automation_region_commands,
        )
    if operation in {"cost-gate", "billable-start", "dispose", "finalize"}:
        return ()
    if operation == "scope-create":
        return (
            (
                "az",
                "group",
                "create",
                "--name",
                rg,
                "--location",
                config.target_region,
                "--tags",
                "mobius.milestone=7.8",
                f"mobius.campaign={config.campaign_id}",
                f"mobius.generation={config.generation_id}",
                f"mobius.cleanup-deadline-utc={config.cleanup_deadline_utc}",
                "mobius.cost-ceiling-cents=5000",
                (
                    "mobius.cleanup-region-selection-sha256="
                    + config.cleanup_region_selection_sha256
                ),
                (
                    "mobius.cleanup-offer-classification="
                    + config.cleanup_offer_classification
                ),
                (
                    "mobius.cleanup-offer-disposition="
                    + config.cleanup_offer_eligibility_disposition
                ),
                (
                    "mobius.cleanup-offer-regions="
                    + config.cleanup_offer_eligible_regions
                ),
                (
                    "mobius.cleanup-offer-source="
                    + config.cleanup_offer_eligibility_source
                ),
                (
                    "mobius.cleanup-offer-eligibility-sha256="
                    + config.cleanup_offer_eligibility_sha256
                ),
                "mobius.owner=managed-postgresql-evidence",
                f"mobius.expiry={config.cleanup_deadline_utc}",
                "--output",
                "json",
            ),
        )
    if operation == "cleanup-deploy":
        return (
            (
                "az",
                "deployment",
                "sub",
                "create",
                "--name",
                runtime["cleanupDeploymentName"],
                "--location",
                config.cleanup_region,
                "--template-file",
                "infra/milestone_7_8/cleanup.bicep",
                "--parameters",
                "@" + runtime["cleanupParametersFile"],
                "--output",
                "json",
            ),
        )
    if operation == "cleanup-arm":
        return (
            (
                "az",
                "automation",
                "runbook",
                "replace-content",
                "--resource-group",
                cleanup_rg,
                "--automation-account-name",
                account,
                "--name",
                runbook,
                "--content",
                "@infra/milestone_7_8/scripts/Remove-M78Campaign.ps1",
            ),
            (
                "az",
                "automation",
                "runbook",
                "publish",
                "--resource-group",
                cleanup_rg,
                "--automation-account-name",
                account,
                "--name",
                runbook,
            ),
        )
    if operation == "cleanup-verify":
        return (
            (
                "az",
                "deployment",
                "sub",
                "show",
                "--name",
                runtime["cleanupDeploymentName"],
                "--output",
                "json",
            ),
            (
                "az",
                "automation",
                "account",
                "show",
                "--resource-group",
                cleanup_rg,
                "--name",
                account,
                "--output",
                "json",
            ),
            (
                "az",
                "automation",
                "runbook",
                "show",
                "--resource-group",
                cleanup_rg,
                "--automation-account-name",
                account,
                "--name",
                runbook,
                "--output",
                "json",
            ),
            (
                "az",
                "automation",
                "schedule",
                "show",
                "--resource-group",
                cleanup_rg,
                "--automation-account-name",
                account,
                "--name",
                runtime["scheduleName"],
                "--output",
                "json",
            ),
            (
                "az",
                "automation",
                "job-schedule",
                "list",
                "--resource-group",
                cleanup_rg,
                "--automation-account-name",
                account,
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                (
                    "https://management.azure.com/subscriptions/"
                    + runtime["subscriptionId"]
                    + "/resourceGroups/"
                    + cleanup_rg
                    + "/providers/Microsoft.Automation/automationAccounts/"
                    + account
                    + "/runbooks/"
                    + runbook
                    + "/content?api-version=2023-11-01"
                ),
                "--output",
                "tsv",
            ),
        )
    if operation == "deploy":
        return (
            (
                "az",
                "deployment",
                "sub",
                "create",
                "--name",
                runtime["campaignDeploymentName"],
                "--location",
                config.target_region,
                "--template-file",
                "infra/milestone_7_8/main.bicep",
                "--parameters",
                "@" + runtime["campaignParametersFile"],
                "deploymentStage=base",
                "--output",
                "json",
            ),
        )
    if operation == "image-decision":
        digest = config.image_digest
        if digest is None:
            return ()
        return (
            (
                "az",
                "deployment",
                "sub",
                "create",
                "--name",
                runtime["campaignDeploymentName"] + "-workload",
                "--location",
                config.target_region,
                "--template-file",
                "infra/milestone_7_8/main.bicep",
                "--parameters",
                "@" + runtime["campaignParametersFile"],
                "deploymentStage=workload",
                f"imageDigest={digest}",
                "--output",
                "json",
            ),
        )
    if operation in {"bootstrap", "migrate"}:
        job = (
            runtime["bootstrapJobName"]
            if operation == "bootstrap"
            else runtime["migrationJobName"]
        )
        return (
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                job,
                "--output",
                "json",
            ),
        )
    if operation == "evidence":
        evidence = runtime["evidenceJobName"]
        operations_override: tuple[str, ...] = ()
        if control_plane_evidence is not None:
            operations_override = (
                "--env-vars",
                f"M78_CONTROL_PLANE_EVIDENCE={control_plane_evidence}",
            )
        return (
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["apiProbeJobName"],
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["workerProbeJobName"],
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                evidence,
                "--args",
                "--phase",
                "catalog",
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                evidence,
                "--args",
                "--phase",
                "application",
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["migrationProbeJobName"],
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["recoveryJobName"],
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["apiProbeJobName"],
                "--args",
                "--phase",
                "credential-denied",
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["recoveryRestoreJobName"],
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                runtime["apiProbeJobName"],
                "--output",
                "json",
            ),
            (
                "az",
                "postgres",
                "flexible-server",
                "restart",
                "--resource-group",
                rg,
                "--name",
                runtime["postgresServerName"],
                "--failover",
                "Forced",
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                evidence,
                "--args",
                "--phase",
                "post-failover",
                "--output",
                "json",
            ),
            (
                "az",
                "containerapp",
                "job",
                "start",
                "--resource-group",
                rg,
                "--name",
                evidence,
                "--args",
                "--phase",
                "operations",
                *operations_override,
                "--output",
                "json",
            ),
        )
    if operation == "cleanup":
        return (
            (
                "az",
                "automation",
                "runbook",
                "start",
                "--resource-group",
                cleanup_rg,
                "--automation-account-name",
                account,
                "--name",
                runbook,
                "--output",
                "json",
            ),
        )
    if operation == "cleanup-wait":
        return (
            (
                "az",
                "group",
                "wait",
                "--deleted",
                "--name",
                rg,
                "--interval",
                "15",
                "--timeout",
                "1800",
            ),
            (
                "az",
                "group",
                "wait",
                "--deleted",
                "--name",
                cleanup_rg,
                "--interval",
                "15",
                "--timeout",
                "1800",
            ),
        )
    if operation == "residue":
        return (
            ("az", "group", "exists", "--name", rg),
            ("az", "group", "exists", "--name", cleanup_rg),
            (
                "az",
                "resource",
                "list",
                "--tag",
                f"mobius.campaign={config.campaign_id}",
                "--output",
                "json",
            ),
            (
                "az",
                "role",
                "assignment",
                "list",
                "--all",
                "--query",
                (
                    "[?contains(scope, '"
                    + rg
                    + "') || contains(scope, '"
                    + cleanup_rg
                    + "')]"
                ),
                "--output",
                "json",
            ),
        )
    raise CampaignError("unknown operator operation")


def _json_result(result: dict[str, object]) -> object:
    raw = result.get("stdout")
    if not isinstance(raw, str):
        raise CampaignError("operator command output is unavailable")
    try:
        return cast(object, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise CampaignError("operator command output is not valid JSON") from exc


def _run_required(
    runner: SubprocessRunner, command: tuple[str, ...]
) -> dict[str, object]:
    result = runner.run(command)
    if result.get("exitCode") != 0:
        raise CampaignError("operator command failed safely")
    return result


def _job_status(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    properties = value.get("properties")
    if isinstance(properties, dict) and isinstance(properties.get("status"), str):
        return str(properties["status"])
    return str(value["status"]) if isinstance(value.get("status"), str) else None


def _wait_for_job(
    runner: SubprocessRunner,
    start_command: tuple[str, ...],
    start_result: dict[str, object],
) -> dict[str, str]:
    value = _json_result(start_result)
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise CampaignError("container job execution identity is missing")
    execution_name = str(value["name"])
    status = _job_status(value)
    resource_group = start_command[start_command.index("--resource-group") + 1]
    job_name = start_command[start_command.index("--name") + 1]
    for _ in range(180):
        if status == "Succeeded":
            return {"executionName": execution_name, "terminalStatus": status}
        if status in {"Failed", "Stopped", "Degraded"}:
            raise CampaignError("container job evidence failed")
        time.sleep(5)
        shown = _run_required(
            runner,
            (
                "az",
                "containerapp",
                "job",
                "execution",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                job_name,
                "--job-execution-name",
                execution_name,
                "--output",
                "json",
            ),
        )
        status = _job_status(_json_result(shown))
    raise CampaignError("container job evidence timed out")


def execute_commands(
    runner: SubprocessRunner, commands: tuple[tuple[str, ...], ...]
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for command in commands:
        result = _run_required(runner, command)
        if command[:4] == ("az", "containerapp", "job", "start"):
            result = {**result, **_wait_for_job(runner, command, result)}
        results.append(result)
    return results


def _deployment_outputs(result: dict[str, object]) -> dict[str, object]:
    value = _json_result(result)
    if not isinstance(value, dict):
        raise CampaignError("deployment output is malformed")
    properties = value.get("properties")
    raw_outputs = properties.get("outputs") if isinstance(properties, dict) else None
    if not isinstance(raw_outputs, dict):
        raise CampaignError("deployment output is missing")
    outputs: dict[str, object] = {}
    for key, item in raw_outputs.items():
        if (
            not isinstance(key, str)
            or not isinstance(item, dict)
            or "value" not in item
        ):
            raise CampaignError("deployment output is malformed")
        outputs[key] = item["value"]
    return outputs


def validate_deployed_principal_manifest(
    outputs: dict[str, object], config: CampaignConfig
) -> None:
    binding = outputs.get("campaignBinding")
    raw = binding.get("principalManifest") if isinstance(binding, dict) else None
    try:
        manifest = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as exc:
        raise CampaignError("deployed principal manifest is invalid JSON") from exc
    expected_slots = {"bootstrap", "migration", "api", "worker", "evidence", "cleanup"}
    principals = manifest.get("principals") if isinstance(manifest, dict) else None
    if (
        not isinstance(binding, dict)
        or binding.get("campaignId") != config.campaign_id
        or binding.get("generationId") != config.generation_id
        or binding.get("subscriptionCorrelation") != config.subscription_correlation
        or binding.get("cleanupDeadlineUtc") != config.cleanup_deadline_utc
        or binding.get("maximumHours") != 4
        or binding.get("costCeilingCents") != 5000
        or binding.get("cleanupResourceGroupName") != config.cleanup_resource_group
        or binding.get("cleanupLocation") != config.cleanup_region
        or binding.get("cleanupRegionSelectionSha256")
        != config.cleanup_region_selection_sha256
        or binding.get("cleanupOfferClassification")
        != config.cleanup_offer_classification
        or binding.get("cleanupOfferEligibilityDisposition")
        != config.cleanup_offer_eligibility_disposition
        or binding.get("cleanupOfferEligibleRegions")
        != config.cleanup_offer_eligible_regions
        or binding.get("cleanupOfferEligibilitySource")
        != config.cleanup_offer_eligibility_source
        or binding.get("cleanupOfferEligibilitySha256")
        != config.cleanup_offer_eligibility_sha256
        or not isinstance(manifest, dict)
        or set(manifest)
        != {
            "version",
            "campaignId",
            "generationId",
            "subscriptionCorrelation",
            "principals",
        }
        or manifest.get("version") != "m7.8-principal-manifest-v1"
        or manifest.get("campaignId") != config.campaign_id
        or manifest.get("generationId") != config.generation_id
        or manifest.get("subscriptionCorrelation") != config.subscription_correlation
        or not isinstance(principals, dict)
        or set(principals) != expected_slots
    ):
        raise CampaignError("deployed campaign or principal binding differs")
    names: dict[str, str] = {}
    object_ids: list[str] = []
    for slot in sorted(expected_slots):
        item = principals[slot]
        if (
            not isinstance(item, dict)
            or set(item) != {"role", "name", "objectId"}
            or item.get("role") != slot
            or not isinstance(item.get("name"), str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{2,62}", item["name"]) is None
            or not isinstance(item.get("objectId"), str)
        ):
            raise CampaignError("deployed principal semantic binding is malformed")
        try:
            parsed = uuid.UUID(item["objectId"])
        except ValueError as exc:
            raise CampaignError(
                "deployed principal object binding is malformed"
            ) from exc
        if parsed.int == 0:
            raise CampaignError("deployed principal object binding is malformed")
        names[slot] = item["name"]
        object_ids.append(item["objectId"])
    if len(set(names.values())) != 6 or len(set(object_ids)) != 6:
        raise CampaignError("deployed principal bindings are not distinct")
    planned = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "principals": {
            slot: names[slot]
            for slot in ("bootstrap", "migration", "api", "worker", "evidence")
        },
        "cleanup": names["cleanup"],
    }
    observed_plan_sha256 = hashlib.sha256(
        json.dumps(planned, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if observed_plan_sha256 != config.principal_manifest_sha256:
        raise CampaignError("deployed principal plan binding differs")


def validate_cleanup_deployment(
    result: dict[str, object], config: CampaignConfig
) -> CleanupBinding:
    outputs = _deployment_outputs(result)
    required = {
        "campaignId",
        "generationId",
        "subscriptionCorrelation",
        "targetResourceGroupName",
        "cleanupResourceGroupName",
        "cleanupPrincipalId",
        "cleanupLocation",
        "cleanupRegionSelectionSha256",
        "cleanupOfferClassification",
        "cleanupOfferEligibilityDisposition",
        "cleanupOfferEligibleRegions",
        "cleanupOfferEligibilitySource",
        "cleanupOfferEligibilitySha256",
        "cleanupDeadlineUtc",
        "costCeilingCents",
        "scheduleCount",
    }
    if not required <= set(outputs) or not isinstance(
        outputs["cleanupPrincipalId"], str
    ):
        raise CampaignError("cleanup deployment binding is incomplete")
    cost_ceiling_cents = outputs["costCeilingCents"]
    schedule_count = outputs["scheduleCount"]
    if type(cost_ceiling_cents) is not int or type(schedule_count) is not int:
        raise CampaignError("cleanup deployment numeric binding is malformed")
    principal_sha256 = hashlib.sha256(
        b"m7.8/cleanup-principal/v1\0" + str(outputs["cleanupPrincipalId"]).encode()
    ).hexdigest()
    binding = CleanupBinding(
        campaign_id=str(outputs["campaignId"]),
        generation_id=str(outputs["generationId"]),
        subscription_correlation=str(outputs["subscriptionCorrelation"]),
        target_resource_group=str(outputs["targetResourceGroupName"]),
        cleanup_resource_group=str(outputs["cleanupResourceGroupName"]),
        cleanup_principal_sha256=principal_sha256,
        deadline_utc=str(outputs["cleanupDeadlineUtc"]),
        ceiling_usd=f"{cost_ceiling_cents / 100:.2f}",
        schedule_count=schedule_count,
        cleanup_region=str(outputs["cleanupLocation"]),
        cleanup_region_selection_sha256=str(outputs["cleanupRegionSelectionSha256"]),
        cleanup_offer_classification=str(outputs["cleanupOfferClassification"]),
        cleanup_offer_eligibility_disposition=str(
            outputs["cleanupOfferEligibilityDisposition"]
        ),
        cleanup_offer_eligible_regions=str(outputs["cleanupOfferEligibleRegions"]),
        cleanup_offer_eligibility_source=str(outputs["cleanupOfferEligibilitySource"]),
        cleanup_offer_eligibility_sha256=str(outputs["cleanupOfferEligibilitySha256"]),
    )
    binding.validate(config)
    return binding


def validate_cleanup_readback(
    results: list[dict[str, object]], config: CampaignConfig, runtime: dict[str, str]
) -> None:
    if len(results) != 6:
        raise CampaignError("cleanup readback is incomplete")
    expected_binding = validate_cleanup_deployment(results[0], config)
    account = _json_result(results[1])
    runbook = _json_result(results[2])
    schedule = _json_result(results[3])
    bindings = _json_result(results[4])
    if (
        not isinstance(runbook, dict)
        or not isinstance(schedule, dict)
        or not isinstance(bindings, list)
    ):
        raise CampaignError("cleanup readback is malformed")
    identity = account.get("identity") if isinstance(account, dict) else None
    observed_principal = (
        identity.get("principalId") if isinstance(identity, dict) else None
    )
    if (
        not isinstance(observed_principal, str)
        or hashlib.sha256(
            b"m7.8/cleanup-principal/v1\0" + observed_principal.encode()
        ).hexdigest()
        != expected_binding.cleanup_principal_sha256
    ):
        raise CampaignError("cleanup identity readback was substituted")
    account_location = account.get("location") if isinstance(account, dict) else None
    normalized_account_location = (
        re.sub(r"[^a-z0-9]", "", account_location.casefold())
        if isinstance(account_location, str)
        else None
    )
    if normalized_account_location != config.cleanup_region:
        raise CampaignError("cleanup account region readback was substituted")
    runbook_properties = runbook.get("properties", runbook)
    schedule_properties = schedule.get("properties", schedule)
    binding = bindings[0] if len(bindings) == 1 else None
    binding_properties = (
        binding.get("properties", binding) if isinstance(binding, dict) else None
    )
    bound_runbook = (
        binding_properties.get("runbook")
        if isinstance(binding_properties, dict)
        else None
    )
    bound_schedule = (
        binding_properties.get("schedule")
        if isinstance(binding_properties, dict)
        else None
    )
    bound_runbook_name = (
        bound_runbook.get("name") if isinstance(bound_runbook, dict) else bound_runbook
    )
    bound_schedule_name = (
        bound_schedule.get("name")
        if isinstance(bound_schedule, dict)
        else bound_schedule
    )
    if (
        runbook.get("name") != runtime["runbookName"]
        or not isinstance(runbook_properties, dict)
        or runbook_properties.get("state") != "Published"
        or schedule.get("name") != runtime["scheduleName"]
        or not isinstance(schedule_properties, dict)
        or schedule_properties.get("frequency") != "OneTime"
        or not isinstance(schedule_properties.get("startTime"), str)
        or parse_utc(str(schedule_properties["startTime"]))
        != parse_utc(config.cleanup_deadline_utc)
        or len(bindings) != 1
        or bound_runbook_name != runtime["runbookName"]
        or bound_schedule_name != runtime["scheduleName"]
    ):
        raise CampaignError("cleanup identity, schedule, or binding readback drifted")
    content = results[5].get("stdout")
    if (
        not isinstance(content, str)
        or hashlib.sha256(content.encode()).hexdigest()
        != runtime["cleanupScriptSha256"]
    ):
        raise CampaignError("published cleanup content differs")


def load_control_plane_evidence(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != CONTROL_PLANE_FIELDS:
        raise CampaignError("control-plane evidence is incomplete")
    return cast(dict[str, object], value)


def _completed_control_plane_evidence(
    value: dict[str, object], *, recovery_seconds: float
) -> str:
    completed = {
        **value,
        "recoverySeconds": recovery_seconds,
        "failoverObserved": True,
        "credentialRecoveryObserved": True,
        "postFailoverTenantIsolationObserved": True,
    }
    return json.dumps(completed, separators=(",", ":"), sort_keys=True)


def execute_evidence_commands(
    runner: SubprocessRunner,
    commands: tuple[tuple[str, ...], ...],
    control_plane_evidence: dict[str, object],
) -> list[dict[str, object]]:
    if len(commands) != 12:
        raise CampaignError("managed evidence command sequence is incomplete")
    results: list[dict[str, object]] = []
    recovery_seconds: float | None = None
    failover_started: float | None = None
    for index, original in enumerate(commands):
        command = original
        if index == 9:
            failover_started = time.monotonic()
        if index == 11:
            if recovery_seconds is None:
                raise CampaignError("managed failover duration is unavailable")
            payload = _completed_control_plane_evidence(
                control_plane_evidence, recovery_seconds=recovery_seconds
            )
            if "--env-vars" not in command:
                raise CampaignError("managed operations evidence injection is absent")
            env_index = command.index("--env-vars") + 1
            command = (
                *command[:env_index],
                f"M78_CONTROL_PLANE_EVIDENCE={payload}",
                *command[env_index + 1 :],
            )
        result = _run_required(runner, command)
        if command[:4] == ("az", "containerapp", "job", "start"):
            result = {**result, **_wait_for_job(runner, command, result)}
        results.append(result)
        if index == 9:
            if failover_started is None:
                raise CampaignError("managed failover start time is unavailable")
            recovery_seconds = max(time.monotonic() - failover_started, 0.000001)
    return results


def persist_evidence_execution_receipt(
    path: Path,
    *,
    config: CampaignConfig,
    runtime: dict[str, str],
    commands: tuple[tuple[str, ...], ...],
    results: list[dict[str, object]],
    control_plane_evidence: dict[str, object],
) -> None:
    if len(commands) != len(results) or len(results) != 12:
        raise CampaignError("managed evidence execution receipt is incomplete")
    observations: list[dict[str, str]] = []
    for command, result in zip(commands, results, strict=True):
        stdout = result.get("stdout")
        if not isinstance(stdout, str) or result.get("exitCode") != 0:
            raise CampaignError("managed evidence command receipt is malformed")
        if command[:4] == ("az", "containerapp", "job", "start"):
            execution_name = result.get("executionName")
            terminal_status = result.get("terminalStatus")
            if not isinstance(execution_name, str) or terminal_status != "Succeeded":
                raise CampaignError(
                    "managed evidence job receipt is not terminal-success"
                )
            identity = f"job:{command[command.index('--name') + 1]}"
            if "--phase" in command:
                identity += f":{command[command.index('--phase') + 1]}"
        else:
            execution_name = "control-plane"
            terminal_status = "Succeeded"
            identity = "postgres:forced-failover"
        observations.append(
            {
                "identity": identity,
                "executionName": execution_name,
                "terminalStatus": terminal_status,
                "outputSha256": hashlib.sha256(
                    b"m7.8/operator-command-output/v1\0" + stdout.encode()
                ).hexdigest(),
            }
        )
    receipt = {
        "version": "m7.8-managed-evidence-execution-v1",
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "sourceHead": runtime["sourceHead"],
        "imageDigest": config.image_digest,
        "controlPlaneEvidenceSha256": hashlib.sha256(
            json.dumps(
                control_plane_evidence, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest(),
        "observations": observations,
    }
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise CampaignError(
                "managed evidence execution receipt substitution rejected"
            )
        return
    path.write_text(encoded, encoding="utf-8")


def validate_evidence_execution_receipt(
    path: Path,
    *,
    config: CampaignConfig,
    runtime: dict[str, str],
    control_plane_evidence: dict[str, object],
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    observations = value.get("observations") if isinstance(value, dict) else None
    control_sha256 = hashlib.sha256(
        json.dumps(
            control_plane_evidence, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "campaignId",
            "generationId",
            "sourceHead",
            "imageDigest",
            "controlPlaneEvidenceSha256",
            "observations",
        }
        or value["version"] != "m7.8-managed-evidence-execution-v1"
        or value["campaignId"] != config.campaign_id
        or value["generationId"] != config.generation_id
        or value["sourceHead"] != runtime["sourceHead"]
        or value["imageDigest"] != config.image_digest
        or value["controlPlaneEvidenceSha256"] != control_sha256
        or not isinstance(observations, list)
        or len(observations) != 12
        or any(
            not isinstance(item, dict)
            or set(item)
            != {"identity", "executionName", "terminalStatus", "outputSha256"}
            or item["terminalStatus"] != "Succeeded"
            or not isinstance(item["identity"], str)
            or not item["identity"]
            or not isinstance(item["executionName"], str)
            or not item["executionName"]
            or not isinstance(item["outputSha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", item["outputSha256"]) is None
            for item in observations
        )
    ):
        raise CampaignError("managed evidence execution receipt is invalid")


def load_image_scan_evidence(
    path: Path, *, digest: str, runtime: dict[str, str]
) -> str:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != IMAGE_SCAN_FIELDS:
        raise CampaignError("image admission evidence is incomplete")
    if (
        value["version"] != "m7.8-image-admission-v1"
        or value["sourceHead"] != runtime["sourceHead"]
        or value["canonicalBuildInputSha256"] != runtime["canonicalBuildInputSha256"]
        or value["imageDigest"] != digest
        or not isinstance(value["scanner"], str)
        or not value["scanner"]
        or not isinstance(value["scannerVersion"], str)
        or not value["scannerVersion"]
        or value["result"] != "passed"
        or type(value["criticalFindings"]) is not int
        or type(value["highFindings"]) is not int
        or value["criticalFindings"] != 0
        or value["highFindings"] != 0
        or not isinstance(value["scannedAtUtc"], str)
    ):
        raise CampaignError("image admission evidence failed its binding or policy")
    parse_utc(value["scannedAtUtc"])
    return hashlib.sha256(raw).hexdigest()


def verify_zero_residue(results: list[dict[str, object]]) -> dict[str, int]:
    if len(results) != 4:
        raise CampaignError("residue readback is incomplete")
    target_exists = _json_result(results[0])
    cleanup_exists = _json_result(results[1])
    resources = _json_result(results[2])
    assignments = _json_result(results[3])
    if (
        target_exists is not False
        or cleanup_exists is not False
        or resources != []
        or assignments != []
    ):
        raise CampaignError("campaign residue is nonzero")
    return dict.fromkeys(RESIDUE_KEYS, 0)


def start_failure_cleanup(
    runner: SubprocessRunner, config: CampaignConfig, runtime: dict[str, str]
) -> None:
    try:
        for command in command_plan("cleanup", config, runtime):
            _run_required(runner, command)
        return
    except CampaignError:
        pass
    start_direct_cleanup(runner, config)


def start_direct_cleanup(runner: SubprocessRunner, config: CampaignConfig) -> None:
    for group_name in (config.target_resource_group, config.cleanup_resource_group):
        _run_required(
            runner,
            (
                "az",
                "group",
                "delete",
                "--name",
                group_name,
                "--yes",
                "--no-wait",
                "--output",
                "none",
            ),
        )


def validate_operation_results(
    operation: str,
    results: list[dict[str, object]],
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    runner: SubprocessRunner | None = None,
) -> None:
    if operation == "preflight":
        if len(results) != 7:
            raise CampaignError("local preflight is incomplete")
        text_values = [result.get("stdout") for result in results[:5]]
        if (
            text_values[0] != ""
            or str(text_values[1]).strip() != runtime["sourceHead"]
            or str(text_values[2]).strip()
            != "milestone-7-8-production-readiness-audit-local"
            or str(text_values[3]).strip()
            or len(str(text_values[4]).strip().splitlines()) != 5
            or not isinstance(_json_result(results[5]), dict)
        ):
            raise CampaignError("local preflight boundary differs")
        canonical = _json_result(results[6])
        if (
            not isinstance(canonical, dict)
            or canonical.get("buildInputSha256") != runtime["canonicalBuildInputSha256"]
            or canonical.get("dockerfileSha256") != runtime["dockerfileSha256"]
        ):
            raise CampaignError("canonical image inputs changed after preparation")
    elif operation == "correlate":
        if len(results) != 1:
            raise CampaignError("Azure correlation is incomplete")
        account = _json_result(results[0])
        if (
            not isinstance(account, dict)
            or not isinstance(account.get("id"), str)
            or not isinstance(account.get("tenantId"), str)
            or account["id"] != runtime["subscriptionId"]
            or sanitize(str(account["id"]), domain="subscription")
            != config.subscription_correlation
            or sanitize(str(account["tenantId"]), domain="tenant")
            != config.tenant_correlation
        ):
            raise CampaignError("Azure campaign correlation differs")
    elif operation == "capacity-check":
        if len(results) != 16:
            raise CampaignError(
                "provider, quota, region, SKU, or name proof is incomplete"
            )
        providers = [_json_result(result) for result in results[:6]]
        if any(
            not isinstance(provider, dict)
            or provider.get("registrationState") != "Registered"
            for provider in providers
        ):
            raise CampaignError("required Azure provider is not registered")
        skus = _json_result(results[6])
        quota = _json_result(results[7])
        registry_name = _json_result(results[8])
        postgres_name = _json_result(results[9])
        if "Standard_D2ds_v5" not in json.dumps(skus, separators=(",", ":")):
            raise CampaignError("required PostgreSQL SKU is unavailable")
        if not isinstance(quota, list) or not quota:
            raise CampaignError("regional compute quota is unproved")
        if (
            not isinstance(registry_name, dict)
            or registry_name.get("nameAvailable") is not True
            or not isinstance(postgres_name, dict)
            or postgres_name.get("nameAvailable") is not True
        ):
            raise CampaignError("campaign-global resource name is unavailable")
        if runner is None:
            raise CampaignError(
                "Automation cleanup policy discovery runner is unavailable"
            )
        refreshed_selection = select_automation_region_from_results(
            runner,
            tuple(results[10:16]),
        )
        if (
            refreshed_selection.selected_region != config.cleanup_region
            or refreshed_selection.sha256() != config.cleanup_region_selection_sha256
            or refreshed_selection.offer_classification
            != config.cleanup_offer_classification
            or refreshed_selection.offer_eligibility_disposition
            != config.cleanup_offer_eligibility_disposition
            or ",".join(refreshed_selection.offer_eligible_regions)
            != config.cleanup_offer_eligible_regions
            or refreshed_selection.offer_eligibility_source
            != config.cleanup_offer_eligibility_source
            or refreshed_selection.offer_eligibility_sha256
            != config.cleanup_offer_eligibility_sha256
        ):
            raise CampaignError(
                "prepared Automation cleanup region or offer proof is no longer armable"
            )
    elif operation == "scope-create":
        if len(results) != 1:
            raise CampaignError("campaign scope creation is unproved")
        group = _json_result(results[0])
        tags = group.get("tags") if isinstance(group, dict) else None
        if (
            not isinstance(group, dict)
            or group.get("name") != config.target_resource_group
            or not isinstance(tags, dict)
            or tags.get("mobius.campaign") != config.campaign_id
            or tags.get("mobius.generation") != config.generation_id
            or tags.get("mobius.milestone") != "7.8"
            or tags.get("mobius.cleanup-deadline-utc") != config.cleanup_deadline_utc
            or tags.get("mobius.cost-ceiling-cents") != "5000"
            or tags.get("mobius.cleanup-region-selection-sha256")
            != config.cleanup_region_selection_sha256
            or tags.get("mobius.cleanup-offer-classification")
            != config.cleanup_offer_classification
            or tags.get("mobius.cleanup-offer-disposition")
            != config.cleanup_offer_eligibility_disposition
            or tags.get("mobius.cleanup-offer-regions")
            != config.cleanup_offer_eligible_regions
            or tags.get("mobius.cleanup-offer-source")
            != config.cleanup_offer_eligibility_source
            or tags.get("mobius.cleanup-offer-eligibility-sha256")
            != config.cleanup_offer_eligibility_sha256
        ):
            raise CampaignError("campaign scope readback differs")
    elif operation in {"deploy", "image-decision"}:
        if len(results) != 1:
            raise CampaignError("campaign deployment result is missing")
        outputs = _deployment_outputs(results[0])
        expected_stage = "base" if operation == "deploy" else "workload"
        if (
            outputs.get("campaignId") != config.campaign_id
            or outputs.get("generationId") != config.generation_id
            or outputs.get("deploymentStage") != expected_stage
            or (
                operation == "image-decision"
                and outputs.get("imageDigest") != config.image_digest
            )
        ):
            raise CampaignError("campaign deployment binding differs")
        validate_deployed_principal_manifest(outputs, config)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute one restart-safe M7.8 operator phase"
    )
    parser.add_argument("operation", choices=tuple(OPERATION_PHASE))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image-digest")
    parser.add_argument("--image-built", action="store_true")
    parser.add_argument("--image-scan-evidence", type=Path)
    parser.add_argument("--control-plane-evidence", type=Path)
    args = parser.parse_args()
    try:
        cleanup_only = args.operation in {
            "cleanup",
            "cleanup-wait",
            "residue",
            "finalize",
        }
        config = CampaignConfig.from_json(args.config, allow_expired=True)
        runtime = load_runtime(args.runtime)
        validate_prepared_bundle(args.runtime, runtime, config)
        ledger = load_ledger(args.ledger, config)
        if not cleanup_only and parse_utc(config.cleanup_deadline_utc) <= datetime.now(
            UTC
        ):
            if ORDER.index(Phase(ledger.phase)) >= ORDER.index(
                Phase.SCOPE_CREATED
            ) and Phase(ledger.phase) not in {
                Phase.CLEANING,
                Phase.CLEANED,
                Phase.RESIDUE_VERIFIED,
                Phase.FINALIZED,
            }:
                expiry_runner = SubprocessRunner()
                start_failure_cleanup(expiry_runner, config, runtime)
                ledger.transition(Phase.CLEANING, datetime.now(UTC))
                save_ledger(args.ledger, ledger)
            raise CampaignError("cleanup deadline is expired; cleanup is required")
        target = OPERATION_PHASE[args.operation]
        image_scan_sha256 = None
        if target is Phase.IMAGE_DECIDED and args.image_digest is not None:
            config = replace(config, image_digest=args.image_digest)
            config.validate()
            if args.image_scan_evidence is not None:
                image_scan_sha256 = load_image_scan_evidence(
                    args.image_scan_evidence,
                    digest=args.image_digest,
                    runtime=runtime,
                )
        control_evidence = None
        if args.control_plane_evidence is not None:
            control_evidence = load_control_plane_evidence(args.control_plane_evidence)
        rendered_control_evidence = (
            "<derived-after-successful-managed-probes>"
            if control_evidence is not None
            else None
        )
        evidence_receipt_path = args.ledger.with_name("managed-evidence-execution.json")
        if (
            args.execute
            and args.operation == "evidence"
            and evidence_receipt_path.exists()
        ):
            if control_evidence is None:
                raise CampaignError(
                    "control-plane evidence is required to resume managed evidence"
                )
            validate_evidence_execution_receipt(
                evidence_receipt_path,
                config=config,
                runtime=runtime,
                control_plane_evidence=control_evidence,
            )
            if Phase(ledger.phase) is not Phase.MIGRATED:
                raise CampaignError("managed evidence receipt phase is inconsistent")
            ledger.transition(Phase.EVIDENCE_EXECUTED, datetime.now(UTC))
            save_ledger(args.ledger, ledger)
            print(
                json.dumps(
                    {"status": "passed", "phase": Phase.EVIDENCE_EXECUTED.value},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        commands = command_plan(
            args.operation,
            config,
            runtime,
            control_plane_evidence=rendered_control_evidence,
        )
        if not args.execute:
            display_commands = tuple(
                tuple(
                    part.replace(runtime["subscriptionId"], "<runtime-subscription-id>")
                    for part in command
                )
                for command in commands
            )
            print(
                json.dumps(
                    {
                        "operation": args.operation,
                        "commands": display_commands,
                        "generatedCommands": (
                            generated_policy_read_contract()
                            if args.operation == "capacity-check"
                            else ()
                        ),
                        "mutationAuthorized": False,
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        runner = SubprocessRunner()
        try:
            if target is Phase.IMAGE_DECIDED and (
                args.image_digest is None or image_scan_sha256 is None
            ):
                raise CampaignError(
                    "immutable image decision or admission scan is missing"
                )
            if args.operation == "evidence" and control_evidence is None:
                raise CampaignError(
                    "control-plane evidence is required for managed evidence"
                )
            results = (
                execute_evidence_commands(runner, commands, control_evidence)
                if args.operation == "evidence" and control_evidence is not None
                else execute_commands(runner, commands)
            )
            validate_operation_results(
                args.operation,
                results,
                config,
                runtime,
                runner=runner,
            )
            if args.operation == "evidence" and control_evidence is not None:
                persist_evidence_execution_receipt(
                    evidence_receipt_path,
                    config=config,
                    runtime=runtime,
                    commands=commands,
                    results=results,
                    control_plane_evidence=control_evidence,
                )
            if target is Phase.COST_GATED:
                config.validate()
                ledger.bind_deadline(config.cleanup_deadline_utc)
            if target is Phase.IMAGE_DECIDED:
                if args.image_digest is None or image_scan_sha256 is None:
                    raise CampaignError(
                        "immutable image decision or admission scan is missing"
                    )
                ledger.record_image(args.image_digest, built=args.image_built)
                ledger.record_image_scan(args.image_digest, image_scan_sha256)
            if target is Phase.CLEANUP_DEPLOYED:
                if len(results) != 1:
                    raise CampaignError("cleanup deployment result is missing")
                validate_cleanup_deployment(results[0], config)
            if target is Phase.CLEANUP_VERIFIED:
                validate_cleanup_readback(results, config, runtime)
            if target is Phase.RESIDUE_VERIFIED:
                ledger.verify_residue(verify_zero_residue(results))
            ledger.transition(target, datetime.now(UTC))
            save_ledger(args.ledger, ledger)
            output: object = (
                terminal_receipt(ledger)
                if target is Phase.FINALIZED
                else {"status": "passed", "phase": target.value}
            )
            print(json.dumps(output, separators=(",", ":"), sort_keys=True))
            return 0
        except Exception:
            if (
                args.operation == "cleanup-wait"
                and Phase(ledger.phase) is Phase.CLEANING
            ):
                start_direct_cleanup(runner, config)
            if ORDER.index(Phase(ledger.phase)) >= ORDER.index(
                Phase.SCOPE_CREATED
            ) and Phase(ledger.phase) not in {
                Phase.CLEANING,
                Phase.CLEANED,
                Phase.RESIDUE_VERIFIED,
                Phase.FINALIZED,
            }:
                start_failure_cleanup(runner, config, runtime)
                ledger.transition(Phase.CLEANING, datetime.now(UTC))
                save_ledger(args.ledger, ledger)
            raise
    except Exception as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
