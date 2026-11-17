from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from infra.milestone_7_8.automation_region import (
    AutomationRegionSelection,
    automation_region_discovery_commands,
    generated_policy_read_contract,
    select_automation_region_from_results,
    selection_from_document,
)
from infra.milestone_7_8.azure_cli import AzureCliError
from infra.milestone_7_8.campaign import (
    ORDER,
    RESIDUE_KEYS,
    CampaignConfig,
    CampaignError,
    CleanupBinding,
    CommandRunner,
    Ledger,
    Phase,
    SubprocessRunner,
    load_ledger,
    parse_utc,
    sanitize,
    save_ledger,
    terminal_receipt,
)
from infra.milestone_7_8.cleanup_controller import (
    ARCHITECTURE,
    LOCAL_ARCHITECTURE_STATE,
    cleanup_authority_sha256,
    controller_binding_sha256,
    controller_local_auth_disabled,
    controller_names,
    load_execution_authorization,
    validate_controller_deadline_consistency,
)
from infra.milestone_7_8.controller_admission import (
    bootstrap_script_hash,
    load_authority_evidence,
    validate_authority_evidence,
    validate_controller_admission,
)
from infra.milestone_7_8.controller_renewal import _durable_record
from infra.milestone_7_8.evidence_console import (
    EvidenceConsole,
    evidence_hash,
    validate_failover,
    validate_probe_container,
    validate_proofs,
    validate_ready_readback,
    validate_worker_capture,
)
from infra.milestone_7_8.measurement_handoff import (
    CampaignMeasurement,
    start_evidence_job,
    validate_measurement_receipt,
)
from infra.milestone_7_8.predeployment import (
    EVIDENCE_CLASS as FRESH_CONTROLLER_ADMISSION_EVIDENCE_CLASS,
)
from infra.milestone_7_8.predeployment import (
    EVIDENCE_VERSION as FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION,
)
from infra.milestone_7_8.predeployment import (
    PredeploymentVerificationError,
    load_validated_admission,
)
from infra.milestone_7_8.replica_readback import collect_worker_replicas, worker_replica_url

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
    "azureReservedConnections",
    "poolCeilings",
    "rolloutOverlap",
    "operatorConsumers",
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
    "automationApiVersion",
    "cleanupControllerArchitecture",
    "cleanupControllerArmability",
    "controllerBindingSha256",
    "controllerAuthorityEvidenceFile",
    "controllerAuthorityEvidenceSha256",
    "controllerAuthorizedUntilUtc",
    "cleanupAuthorityExpiresUtc",
    "cleanupRegion",
    "cleanupRegionSelectionSha256",
    "cleanupCandidateRegions",
    "cleanupOfferClassification",
    "cleanupOfferEligibilityDisposition",
    "cleanupOfferEligibleRegions",
    "cleanupOfferEligibilitySource",
    "cleanupOfferEligibilitySha256",
    "freshControllerAdmissionEvidenceSha256",
    "freshControllerAdmissionEvidenceVersion",
    "freshControllerAdmissionEvidenceClass",
    "freshControllerAdmissionEvidenceObservedAtUtc",
    "freshControllerAdmissionRuntimeFile",
    "freshControllerAdmissionAuthorizationFile",
    "freshControllerAdmissionEvidenceFile",
    "cleanupRegionSelectionFile",
    "cleanupDeploymentName",
    "campaignDeploymentName",
    "automationAccountName",
    "runbookName",
    "scheduleName",
    "bindingName",
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
    "cleanupCandidateRegions",
    "cleanupOfferClassification",
    "cleanupOfferEligibilityDisposition",
    "cleanupOfferEligibleRegions",
    "cleanupOfferEligibilitySource",
    "cleanupOfferEligibilitySha256",
    "freshControllerAdmissionEvidenceSha256",
    "cleanupDeadlineUtc",
    "cleanupAuthorityExpiresUtc",
    "automationAccountName",
    "cleanupRunbookName",
    "cleanupScheduleName",
    "cleanupBindingName",
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
    "cleanupCandidateRegions",
    "cleanupOfferClassification",
    "cleanupOfferEligibilityDisposition",
    "cleanupOfferEligibleRegions",
    "cleanupOfferEligibilitySource",
    "cleanupOfferEligibilitySha256",
    "freshControllerAdmissionEvidenceSha256",
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
    "cleanup-disarm": Phase.CLEANUP_DISARMED,
    "residue": Phase.RESIDUE_VERIFIED,
    "finalize": Phase.FINALIZED,
}


def required_execution_authorizations(
    operation: str, current_phase: Phase
) -> frozenset[str]:
    required = {operation}
    target = OPERATION_PHASE[operation]
    target_can_require_cleanup = (
        ORDER.index(Phase.SCOPE_CREATED)
        <= ORDER.index(target)
        <= ORDER.index(Phase.CLEANED)
    )
    current_can_require_cleanup = (
        ORDER.index(Phase.SCOPE_CREATED)
        <= ORDER.index(current_phase)
        < ORDER.index(Phase.CLEANED)
    )
    if target_can_require_cleanup or current_can_require_cleanup:
        required.add("cleanup")
    return frozenset(required)


def load_runtime(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or not RUNTIME_FIELDS <= set(value) <= RUNTIME_FIELDS | {
            "controllerBootstrapScriptSha256", "deadlineRenewalEvidenceFile",
            "deadlineRenewalEvidenceSha256", "pilotCleanupWindowFile",
        }
        or not all(isinstance(item, str) and item for item in value.values())
    ):
        raise CampaignError("operator runtime fields are incomplete")
    value = cast(dict[str, str], value)
    if ("deadlineRenewalEvidenceFile" in value) != ("deadlineRenewalEvidenceSha256" in value):
        raise CampaignError("operator deadline renewal evidence fields must occur together")
    for field in (
        "bootstrapJobName",
        "migrationJobName",
        "workerJobName",
        "evidenceJobName",
        "apiProbeJobName",
        "workerProbeJobName",
        "migrationProbeJobName",
        "recoveryJobName",
        "recoveryRestoreJobName",
    ):
        name = value[field]
        if (
            not 2 <= len(name) <= 32
            or re.fullmatch(r"[a-z][a-z0-9-]*[a-z0-9]", name) is None
            or "--" in name
        ):
            raise CampaignError(f"operator Container Apps job name is invalid: {field}")
    try:
        uuid.UUID(value["subscriptionId"])
    except ValueError as exc:
        raise CampaignError("operator subscription binding is malformed") from exc
    if (
        re.fullmatch(r"[a-f0-9]{40}", value["sourceHead"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["canonicalBuildInputSha256"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["dockerfileSha256"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["cleanupScriptSha256"]) is None
        or re.fullmatch(
            r"[a-f0-9]{64}",
            value.get("controllerBootstrapScriptSha256", value["cleanupScriptSha256"]),
        ) is None
        or value["automationApiVersion"] != "2024-10-23"
        or value["cleanupControllerArchitecture"] != ARCHITECTURE
        or value["cleanupControllerArmability"] != LOCAL_ARCHITECTURE_STATE
        or re.fullmatch(r"[a-f0-9]{64}", value["controllerBindingSha256"]) is None
        or re.fullmatch(r"[a-f0-9]{64}", value["controllerAuthorityEvidenceSha256"]) is None
        or parse_utc(value["controllerAuthorizedUntilUtc"])
        < parse_utc(value["cleanupAuthorityExpiresUtc"])
        or re.fullmatch(
            r"[a-f0-9]{64}", value["freshControllerAdmissionEvidenceSha256"]
        )
        is None
        or value["freshControllerAdmissionEvidenceVersion"]
        != FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION
        or value["freshControllerAdmissionEvidenceClass"]
        != FRESH_CONTROLLER_ADMISSION_EVIDENCE_CLASS
        or parse_utc(value["freshControllerAdmissionEvidenceObservedAtUtc"])
        <= parse_utc("2000-01-01T00:00:00Z")
        or parse_utc(value["cleanupAuthorityExpiresUtc"])
        <= parse_utc("2000-01-01T00:00:00Z")
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            value["bindingName"],
        )
        is None
    ):
        raise CampaignError("operator source or image binding is malformed")
    return value


def _load_arm_parameter_values(
    path: Path, *, expected: set[str], extended: set[str] | None = None
) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {"$schema", "contentVersion", "parameters"}
        or value.get("contentVersion") != "1.0.0.0"
        or not isinstance(value.get("parameters"), dict)
        or set(value["parameters"]) not in (expected, expected | (extended or set()))
    ):
        raise CampaignError("operator parameter bundle fields are invalid")
    result: dict[str, object] = {}
    for name, item in value["parameters"].items():
        if not isinstance(item, dict) or set(item) != {"value"}:
            raise CampaignError("operator parameter value is malformed")
        result[name] = item["value"]
    return result


def load_bound_fresh_controller_admission(
    runtime_path: Path,
    runtime: dict[str, str],
    config: CampaignConfig,
) -> None:
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
                "fresh controller admission evidence escaped its private generation"
            )
        return resolved

    try:
        campaign_id, generation_id = config.campaign_id, config.generation_id
        if "pilotCleanupWindowFile" in runtime:
            from infra.milestone_7_8.pilot_cleanup import validate_window

            validate_window(runtime_path, runtime, config)
            origin = validate_authority_evidence(
                load_bound_controller_authority(runtime_path, runtime, config)
            )
            campaign_id, generation_id = origin.campaign_id, origin.generation_id
        binding = load_validated_admission(
            runtime_path=sibling("freshControllerAdmissionRuntimeFile"),
            authorization_path=sibling("freshControllerAdmissionAuthorizationFile"),
            evidence_path=sibling("freshControllerAdmissionEvidenceFile"),
            subscription_id=runtime["subscriptionId"],
            tenant_id=_load_fresh_scope_tenant(
                sibling("freshControllerAdmissionRuntimeFile")
            ),
            campaign_id=campaign_id,
            generation_id=generation_id,
            region=config.cleanup_region,
            controller_resource_group_name=runtime["cleanupResourceGroupName"],
            automation_account_name=runtime["automationAccountName"],
        )
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        PredeploymentVerificationError,
    ) as exc:
        raise CampaignError(str(exc)) from exc
    if (
        binding.evidence_sha256 != config.fresh_controller_admission_evidence_sha256
        or runtime["freshControllerAdmissionEvidenceSha256"] != binding.evidence_sha256
        or runtime["freshControllerAdmissionEvidenceVersion"]
        != binding.document.get("version")
        or runtime["freshControllerAdmissionEvidenceClass"]
        != binding.document.get("evidenceClass")
        or runtime["freshControllerAdmissionEvidenceObservedAtUtc"]
        != binding.observed_at_utc
    ):
        raise CampaignError("fresh controller admission evidence binding differs")


def _load_fresh_scope_tenant(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError("fresh controller admission runtime is unreadable") from exc
    tenant_id = value.get("tenantId") if isinstance(value, dict) else None
    if not isinstance(tenant_id, str):
        raise CampaignError("fresh controller admission runtime is malformed")
    return tenant_id


def validate_bound_controller_authority(
    value: object, runtime: dict[str, str], config: CampaignConfig
) -> dict[str, object]:
    anchor = validate_authority_evidence(value)
    authority_hash = validate_controller_admission(
        value,
        subscription_id=runtime["subscriptionId"],
        subscription_correlation=config.subscription_correlation,
        resource_group=config.cleanup_resource_group,
        account=runtime["automationAccountName"],
        cleanup_script_sha256=runtime["cleanupScriptSha256"],
        fresh_evidence_sha256=config.fresh_controller_admission_evidence_sha256,
        location=config.cleanup_region,
        observed_deadline=anchor.controller_authorized_until_utc,
    )
    if (
        authority_hash != runtime["controllerAuthorityEvidenceSha256"]
        or runtime.get("controllerBootstrapScriptSha256", runtime["cleanupScriptSha256"])
        != bootstrap_script_hash(cast(dict[str, object], value))
        or anchor.controller_authorized_until_utc != runtime["controllerAuthorizedUntilUtc"]
        or anchor.runbook_name != runtime["runbookName"]
        or (
            "pilotCleanupWindowFile" not in runtime
            and (anchor.campaign_id, anchor.generation_id)
            != (config.campaign_id, config.generation_id)
        )
        or sanitize(anchor.tenant_id, domain="tenant") != config.tenant_correlation
    ):
        raise CampaignError("controller authority evidence binding differs")
    return cast(dict[str, object], value)


def load_bound_controller_authority(
    runtime_path: Path, runtime: dict[str, str], config: CampaignConfig
) -> dict[str, object]:
    candidate = Path(runtime["controllerAuthorityEvidenceFile"]).resolve()
    if candidate.parent != runtime_path.resolve().parent:
        raise CampaignError("controller authority evidence escaped its private generation")
    return validate_bound_controller_authority(
        load_authority_evidence(candidate), runtime, config
    )


def validate_prepared_bundle(
    runtime_path: Path,
    runtime: dict[str, str],
    config: CampaignConfig,
) -> None:
    if "deadlineRenewalEvidenceFile" in runtime:
        from infra.milestone_7_8.campaign_deadline_renewal import origin_context

        original_runtime, original_config = origin_context(runtime, config)
        validate_prepared_bundle(runtime_path, original_runtime, original_config)
        return
    load_bound_fresh_controller_admission(
        runtime_path,
        runtime,
        config,
    )
    load_bound_controller_authority(runtime_path, runtime, config)
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
    if suffix_match is None:
        raise CampaignError("operator campaign scope is not one generation")
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
        sibling("cleanupParametersFile"), expected=CLEANUP_PARAMETER_FIELDS,
        extended={"costCeilingCents"}
    )
    campaign = _load_arm_parameter_values(
        sibling("campaignParametersFile"), expected=CAMPAIGN_PARAMETER_FIELDS,
        extended={"costCeilingCents", "maximumHours"}
    )
    selection_path = sibling("cleanupRegionSelectionFile")
    selection = selection_from_document(
        json.loads(selection_path.read_text(encoding="utf-8"))
    )
    selection_sha256 = selection.sha256()
    candidate_regions = ",".join(selection.candidate_order)
    offer_eligible_regions = ",".join(selection.offer_eligible_regions)
    if (
        selection.selected_region != config.cleanup_region
        or selection_sha256 != config.cleanup_region_selection_sha256
        or candidate_regions != config.cleanup_candidate_regions
        or selection.offer_classification != config.cleanup_offer_classification
        or selection.offer_eligibility_disposition
        != config.cleanup_offer_eligibility_disposition
        or offer_eligible_regions != config.cleanup_offer_eligible_regions
        or selection.offer_eligibility_source != config.cleanup_offer_eligibility_source
        or selection.offer_eligibility_sha256 != config.cleanup_offer_eligibility_sha256
        or selection.fresh_controller_admission_evidence_sha256
        != config.fresh_controller_admission_evidence_sha256
        or runtime["cleanupRegion"] != config.cleanup_region
        or runtime["cleanupRegionSelectionSha256"] != selection_sha256
        or runtime["cleanupCandidateRegions"] != config.cleanup_candidate_regions
        or runtime["cleanupOfferClassification"] != config.cleanup_offer_classification
        or runtime["cleanupOfferEligibilityDisposition"]
        != config.cleanup_offer_eligibility_disposition
        or runtime["cleanupOfferEligibleRegions"]
        != config.cleanup_offer_eligible_regions
        or runtime["cleanupOfferEligibilitySource"]
        != config.cleanup_offer_eligibility_source
        or runtime["cleanupOfferEligibilitySha256"]
        != config.cleanup_offer_eligibility_sha256
        or runtime["freshControllerAdmissionEvidenceSha256"]
        != config.fresh_controller_admission_evidence_sha256
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
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
    }
    if any(
        cleanup.get(key) != expected for key, expected in common_expected.items()
    ) or any(
        campaign.get(key) != expected for key, expected in common_expected.items()
    ):
        raise CampaignError("operator parameter campaign binding differs")
    if cleanup.get("cleanupAuthorityExpiresUtc") != runtime[
        "cleanupAuthorityExpiresUtc"
    ] or parse_utc(runtime["cleanupAuthorityExpiresUtc"]) != parse_utc(
        config.cleanup_deadline_utc
    ) + timedelta(hours=1):
        raise CampaignError("operator cleanup authority lifetime differs")
    expected_runtime = {
        "cleanupDeploymentName": f"m78-cleanup-{suffix}",
        "campaignDeploymentName": f"m78-campaign-{suffix}",
        "automationAccountName": controller_names(
            config.subscription_correlation
        ).account,
        "runbookName": controller_names(config.subscription_correlation).runbook,
        "scheduleName": f"m78-deadline-{suffix}",
        "bootstrapJobName": f"job-m78-{suffix}-bootstrap",
        "migrationJobName": f"job-m78-{suffix}-migration",
        "workerJobName": f"job-m78-{suffix}-worker",
        "evidenceJobName": f"job-m78-{suffix}-evidence",
        "apiProbeJobName": f"job-m78-{suffix}-probe-api",
        "workerProbeJobName": f"job-m78-{suffix}-probe-worker",
        "migrationProbeJobName": f"job-m78-{suffix}-probe-migrate",
        "recoveryJobName": f"job-m78-{suffix}-revoke",
        "recoveryRestoreJobName": f"job-m78-{suffix}-restore",
        "postgresServerName": f"pgm78{suffix}",
        "registryName": f"acrm78{suffix}",
        "logAnalyticsWorkspaceName": f"law-m78-{suffix}",
    }
    if "pilotCleanupWindowFile" in runtime:
        expected_runtime.update(
            postgresServerName=f"pg-m78o-{suffix}",
            registryName=f"crm78o{suffix}",
            logAnalyticsWorkspaceName=f"law-m78o-{suffix}",
        )
    if any(runtime.get(key) != expected for key, expected in expected_runtime.items()):
        raise CampaignError("operator runtime generation name differs")
    if runtime["controllerBindingSha256"] != controller_binding_sha256(
        runtime["subscriptionId"],
        resource_group=config.cleanup_resource_group,
        account=runtime["automationAccountName"],
        runbook=runtime["runbookName"],
    ):
        raise CampaignError("operator reusable controller binding differs")
    identity_names = {
        "bootstrap": campaign.get("administratorIdentityName"),
        "migration": campaign.get("migrationIdentityName"),
        "api": campaign.get("apiIdentityName"),
        "worker": campaign.get("workerIdentityName"),
        "evidence": campaign.get("evidenceIdentityName"),
    }
    if (
        campaign.get("costCeilingCents", 5000) != config.cost_ceiling_cents
        or cleanup.get("costCeilingCents", 5000) != config.cost_ceiling_cents
        or campaign.get("maximumHours", 4) != config.maximum_hours
        or campaign.get("resourceNameSuffix") != suffix
        or campaign.get("cleanupIdentityName") != runtime["automationAccountName"]
        or any(
            identity_names[role] != f"id-m78-{suffix}-{role}" for role in identity_names
        )
        or len(set(identity_names.values())) != 5
        or campaign.get("targetLocation") != config.target_region
        or campaign.get("postgresLocation") != config.postgres_region
        or campaign.get("cleanupLocation") != config.cleanup_region
        or campaign.get("cleanupRegionSelectionSha256")
        != config.cleanup_region_selection_sha256
        or campaign.get("cleanupCandidateRegions") != config.cleanup_candidate_regions
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
        or campaign.get("freshControllerAdmissionEvidenceSha256")
        != config.fresh_controller_admission_evidence_sha256
        or campaign.get("postgresPrimaryZone") != "1"
        or campaign.get("postgresStandbyZone") != "2"
        or campaign.get("maintenanceDay") != 0
        or campaign.get("maintenanceHour") != 7
        or campaign.get("containerAppsEnvironmentName") != f"cae-m78-{suffix}"
        or campaign.get("virtualNetworkName") != f"vnet-m78-{suffix}"
        or cleanup.get("cleanupLocation") != config.cleanup_region
        or cleanup.get("cleanupRegionSelectionSha256")
        != config.cleanup_region_selection_sha256
        or cleanup.get("cleanupCandidateRegions") != config.cleanup_candidate_regions
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
        or cleanup.get("freshControllerAdmissionEvidenceSha256")
        != config.fresh_controller_admission_evidence_sha256
        or campaign.get("cleanupAutomationAccountName")
        != runtime["automationAccountName"]
        or cleanup.get("automationAccountName") != runtime["automationAccountName"]
        or cleanup.get("cleanupRunbookName") != runtime["runbookName"]
        or cleanup.get("cleanupScheduleName") != runtime["scheduleName"]
        or cleanup.get("cleanupBindingName") != runtime["bindingName"]
        or cleanup.get("cleanupAuthorityExpiresUtc")
        != runtime["cleanupAuthorityExpiresUtc"]
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
        "mobius.cost-ceiling-cents": str(config.cost_ceiling_cents),
        "mobius.cleanup-region-selection-sha256": config.cleanup_region_selection_sha256,
        "mobius.cleanup-candidate-regions": config.cleanup_candidate_regions,
        "mobius.cleanup-offer-classification": config.cleanup_offer_classification,
        "mobius.cleanup-offer-disposition": (
            config.cleanup_offer_eligibility_disposition
        ),
        "mobius.cleanup-offer-regions": config.cleanup_offer_eligible_regions,
        "mobius.cleanup-offer-source": config.cleanup_offer_eligibility_source,
        "mobius.cleanup-offer-eligibility-sha256": (
            config.cleanup_offer_eligibility_sha256
        ),
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "mobius.fresh-controller-admission-version": (
            runtime["freshControllerAdmissionEvidenceVersion"]
        ),
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.expiry": config.cleanup_deadline_utc,
    }
    if campaign.get("lifecycleTags") != expected_tags:
        raise CampaignError("operator lifecycle tags differ")
    planned = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "principals": identity_names,
        "cleanup": runtime["automationAccountName"],
    }
    if (
        hashlib.sha256(
            json.dumps(planned, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        != config.principal_manifest_sha256
    ):
        raise CampaignError("operator prepared principal plan differs")


def cleanup_job_parameters(
    config: CampaignConfig, runtime: dict[str, str]
) -> dict[str, str]:
    return {
        "CampaignId": config.campaign_id,
        "GenerationId": config.generation_id,
        "SubscriptionCorrelation": config.subscription_correlation,
        "TargetResourceGroupName": config.target_resource_group,
        "ControllerResourceGroupName": config.cleanup_resource_group,
        "AutomationAccountName": runtime["automationAccountName"],
        "CleanupRunbookName": runtime["runbookName"],
        "CleanupScheduleName": runtime["scheduleName"],
        "CleanupBindingName": runtime["bindingName"],
        "CleanupDeadlineUtc": config.cleanup_deadline_utc,
        "CleanupAuthorityExpiresUtc": runtime["cleanupAuthorityExpiresUtc"],
        "CostCeilingCents": str(config.cost_ceiling_cents),
        "ControllerBindingSha256": runtime["controllerBindingSha256"],
        "FreshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "FreshControllerAdmissionEvidenceVersion": (
            runtime["freshControllerAdmissionEvidenceVersion"]
        ),
        "CleanupAuthoritySha256": cleanup_authority_sha256(config, runtime),
        "CleanupAuthorized": "true",
    }


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
    automation_base = ""
    api_version = ""
    if operation in {
        "cleanup-deploy",
        "cleanup-arm",
        "cleanup-verify",
        "cleanup-disarm",
        "residue",
    }:
        automation_base = (
            "https://management.azure.com/subscriptions/"
            + runtime["subscriptionId"]
            + "/resourceGroups/"
            + cleanup_rg
            + "/providers/Microsoft.Automation/automationAccounts/"
            + account
        )
        api_version = runtime["automationApiVersion"]
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
                "Microsoft.Storage",
                "Microsoft.Network",
            )
        )
        automation_region_commands = automation_region_discovery_commands(
            runtime["subscriptionId"]
        )
        controller_base = (
            "https://management.azure.com/subscriptions/"
            + runtime["subscriptionId"]
            + "/resourceGroups/"
            + cleanup_rg
            + "/providers/Microsoft.Automation/automationAccounts/"
            + account
        )
        controller_commands = (
            ("az", "group", "show", "--name", cleanup_rg, "--output", "json"),
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
                "role",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{cleanup_rg}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{controller_base}/runbooks/{runbook}?api-version=2024-10-23",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{controller_base}/runbooks/{runbook}/content?api-version=2024-10-23",
                "--output",
                "tsv",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{controller_base}/schedules?api-version=2024-10-23",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{controller_base}/jobSchedules?api-version=2024-10-23",
                "--output",
                "json",
            ),
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
            *(
                (
                    "az", "rest", "--method", "get", "--url",
                    f"https://management.azure.com/subscriptions/{runtime['subscriptionId']}"
                    f"/providers/{provider}/locations/{region}/{path}"
                    f"?api-version={version}", "--output", "json",
                )
                for provider, region, path, version in (
                    ("Microsoft.DBforPostgreSQL", config.postgres_region,
                     "resourceType/flexibleServers/usages", "2025-08-01"),
                    ("Microsoft.App", config.target_region, "usages", "2026-01-01"),
                )
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
            *controller_commands,
            *(
                ("az", "provider", "show", "--namespace", namespace, "--output", "json")
                for namespace in required_pilot_regional_providers(config)
            ),
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
                f"mobius.cost-ceiling-cents={config.cost_ceiling_cents}",
                (
                    "mobius.cleanup-region-selection-sha256="
                    + config.cleanup_region_selection_sha256
                ),
                (
                    "mobius.cleanup-candidate-regions="
                    + config.cleanup_candidate_regions
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
                (
                    "mobius.fresh-controller-admission-sha256="
                    + config.fresh_controller_admission_evidence_sha256
                ),
                *(
                    ("mobius.fresh-controller-admission-version="
                     + runtime["freshControllerAdmissionEvidenceVersion"],)
                    if "pilotCleanupWindowFile" in runtime else ()
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
                "group",
                "show",
                "--name",
                cleanup_rg,
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
                "role",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{cleanup_rg}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/runbooks/{runbook}?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/runbooks/{runbook}/content?api-version={api_version}",
                "--output",
                "tsv",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/schedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/jobSchedules?api-version={api_version}",
                "--output",
                "json",
            ),
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
                "role",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{rg}",
                "--output",
                "json",
            ),
            (
                "az",
                "role",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{cleanup_rg}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/runbooks/{runbook}?api-version={api_version}",
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
                    f"{automation_base}/runbooks/{runbook}/content?api-version={api_version}"
                ),
                "--output",
                "tsv",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/schedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/jobSchedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "put",
                "--url",
                (
                    f"{automation_base}/schedules/{runtime['scheduleName']}"
                    f"?api-version={api_version}"
                ),
                "--body",
                json.dumps(
                    {
                        "properties": {
                            "description": (
                                "One-time immutable Milestone 7.8 cleanup deadline."
                            ),
                            "frequency": "OneTime",
                            "interval": 1,
                            "isEnabled": True,
                            "startTime": config.cleanup_deadline_utc,
                            "timeZone": "Etc/UTC",
                        },
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
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
                    f"{automation_base}/schedules/{runtime['scheduleName']}"
                    f"?api-version={api_version}"
                ),
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "put",
                "--url",
                (
                    f"{automation_base}/jobSchedules/{runtime['bindingName']}"
                    f"?api-version={api_version}"
                ),
                "--body",
                json.dumps(
                    {
                        "properties": {
                            "parameters": cleanup_job_parameters(config, runtime),
                            "runbook": {"name": runtime["runbookName"]},
                            "schedule": {"name": runtime["scheduleName"]},
                        }
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/jobSchedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az", "rest", "--method", "get", "--url",
                f"{automation_base}/jobSchedules/{runtime['bindingName']}?api-version={api_version}",
                "--output", "json",
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
                "role",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{rg}",
                "--output",
                "json",
            ),
            (
                "az",
                "role",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{cleanup_rg}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/runbooks/{runbook}?api-version={api_version}",
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
                    f"{automation_base}/runbooks/{runbook}/content?api-version={api_version}"
                ),
                "--output",
                "tsv",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                (
                    f"{automation_base}/schedules/{runtime['scheduleName']}"
                    f"?api-version={api_version}"
                ),
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/jobSchedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az", "rest", "--method", "get", "--url",
                f"{automation_base}/jobSchedules/{runtime['bindingName']}?api-version={api_version}",
                "--output", "json",
            ),
        )
    if operation == "deploy":
        from infra.milestone_7_8.campaign_deadline_renewal import deployment_overrides

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
                *deployment_overrides(config, runtime),
                "--output",
                "json",
            ),
        )
    if operation == "image-decision":
        from infra.milestone_7_8.campaign_deadline_renewal import deployment_overrides

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
                *deployment_overrides(config, runtime),
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
                "--args=--phase=catalog",
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
                "--args=--phase=application",
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
                "--args=--phase=credential-denied",
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
                runtime["migrationProbeJobName"],
                "--args=--phase=failover-window",
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
                "--args=--phase=operations",
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
                "--parameters",
                *(
                    f"{key}={value}"
                    for key, value in cleanup_job_parameters(config, runtime).items()
                ),
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
        )
    if operation == "cleanup-disarm":
        from infra.milestone_7_8.campaign_deadline_renewal import retained_tuples

        predecessors = retained_tuples(runtime)
        predecessor_commands = tuple(
            ("az", "rest", "--method", "delete", "--url",
             "https://management.azure.com" + str(item[field]) + f"?api-version={api_version}",
             "--output", "none")
            for item in predecessors for field in ("bindingId", "scheduleId")
        )
        return (*predecessor_commands,
            (
                "az",
                "rest",
                "--method",
                "delete",
                "--url",
                f"{automation_base}/jobSchedules/{runtime['bindingName']}?api-version={api_version}",
                "--output",
                "none",
            ),
            (
                "az",
                "rest",
                "--method",
                "delete",
                "--url",
                f"{automation_base}/schedules/{runtime['scheduleName']}?api-version={api_version}",
                "--output",
                "none",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/schedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/jobSchedules?api-version={api_version}",
                "--output",
                "json",
            ),
        )
    if operation == "residue":
        return (
            ("az", "group", "exists", "--name", rg),
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
                ("[?contains(scope, '" + rg + "')]"),
                "--output",
                "json",
            ),
            (
                "az",
                "group",
                "show",
                "--name",
                cleanup_rg,
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
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/schedules?api-version={api_version}",
                "--output",
                "json",
            ),
            (
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                f"{automation_base}/jobSchedules?api-version={api_version}",
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
                    + "/providers/Microsoft.Automation/automationAccounts"
                    + f"?api-version={api_version}"
                ),
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
                    + "/providers/Microsoft.Automation/deletedAutomationAccounts"
                    + f"?api-version={api_version}"
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
    runner: CommandRunner, command: tuple[str, ...]
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


PROTECTED_STAGE_OPERATIONS = frozenset(
    {
        "local-image",
        "deploy",
        "image-decision",
        "bootstrap",
        "migrate",
        "evidence",
        "dispose",
    }
)


class ProtectedStagePersistenceError(CampaignError):
    """Protection remains armed, but an uncertain local record forbids retry."""


class _ProtectedStagePaused(CampaignError):
    pass


class _ProtectedStageExpired(CampaignError):
    pass


class _CleanupAuthorizationBlocked(CampaignError):
    pass


def _stage_hash(domain: str, value: object) -> str:
    return hashlib.sha256(
        f"m7.8/{domain}/v1\0".encode()
        + json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _stage_bindings(
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
) -> dict[str, object]:
    return {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "sourceHead": runtime["sourceHead"],
        "runtimeSha256": _stage_hash("stage-runtime", runtime),
        "configSha256": _stage_hash("stage-config", config.binding_document()),
        "imageDigest": config.image_digest or ledger.image_digest,
        "ledgerPhase": ledger.phase,
        "cleanupArmSha256": ledger.cleanup_arm_evidence_sha256,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
    }


def _stage_is_protected(
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
) -> bool:
    now = datetime.now(UTC)
    try:
        config.validate(allow_expired=True)
    except CampaignError:
        return False
    return (
        ORDER.index(Phase.CLEANUP_VERIFIED)
        <= ORDER.index(Phase(ledger.phase))
        < ORDER.index(Phase.DISPOSED)
        and isinstance(ledger.cleanup_arm_evidence_sha256, str)
        and re.fullmatch(r"[a-f0-9]{64}", ledger.cleanup_arm_evidence_sha256) is not None
        and parse_utc(config.cleanup_deadline_utc) > now
        and parse_utc(runtime["cleanupAuthorityExpiresUtc"]) > now
        and (
            ledger.actual_cost_usd is None
            or Decimal(ledger.actual_cost_usd) < Decimal(ledger.authorized_ceiling_usd)
        )
    )


def _stage_record(path: Path, domain: str, value: dict[str, object]) -> dict[str, object]:
    from infra.milestone_7_8.controller_renewal import _durable_record

    record = {**value, "recordSha256": _stage_hash(domain, value)}
    try:
        _durable_record(path, record)
    except Exception as exc:
        raise ProtectedStagePersistenceError(
            "protected stage record is uncertain; preserve resources and do not retry"
        ) from exc
    return record


def _read_stage_record(path: Path, domain: str) -> dict[str, object]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError
        body = {key: value for key, value in record.items() if key != "recordSha256"}
        if record.get("recordSha256") != _stage_hash(domain, body):
            raise ValueError
        return cast(dict[str, object], record)
    except (OSError, ValueError) as exc:
        raise _ProtectedStagePaused(
            "protected stage record is missing or invalid; do not retry"
        ) from exc


def preserve_protected_stage_failure(
    operation: str,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    private_directory: Path,
    attempt_sha256: str,
    authorization_sha256: str,
    *,
    failed_execution: str | None = None,
    terminal_failure: bool = False,
) -> Path | None:
    """Keep one protected campaign stage paused; this never admits or retries work."""
    if terminal_failure or not _stage_is_protected(config, runtime, ledger):
        return None
    if operation not in PROTECTED_STAGE_OPERATIONS or any(
        re.fullmatch(r"[a-f0-9]{64}", value) is None
        for value in (attempt_sha256, authorization_sha256)
    ):
        raise ProtectedStagePersistenceError("protected stage attempt binding is unavailable")
    path = private_directory / f"{operation}-stage-pause.json"
    if path.exists():
        record = _read_stage_record(path, "stage-pause")
        if record.get("bindings") != _stage_bindings(config, runtime, ledger):
            raise _ProtectedStagePaused("protected stage pause binding differs")
        if parse_utc(str(record.get("recoveryUntilUtc", ""))) <= datetime.now(UTC):
            return None
        return path
    now = datetime.now(UTC)
    _stage_record(
        path,
        "stage-pause",
        {
            "version": "m7.8-protected-stage-pause-v1",
            "operation": operation,
            "bindings": _stage_bindings(config, runtime, ledger),
            "attemptSha256": attempt_sha256,
            "authorizationSha256": authorization_sha256,
            "failedExecution": failed_execution,
            "failedAtUtc": now.isoformat(),
            "recoveryUntilUtc": min(
                now + timedelta(minutes=15), parse_utc(config.cleanup_deadline_utc)
            ).isoformat(),
            "maximumRetryDispatches": 1,
        },
    )
    return path


class _JobExecutionFailure(CampaignError):
    def __init__(
        self,
        message: str,
        command: tuple[str, ...],
        start: dict[str, object],
        last: dict[str, object],
        execution: str,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.start = start
        self.last = last
        self.execution = execution


def _capture_failed_job_diagnostics(
    failure: _JobExecutionFailure,
    *,
    runtime: dict[str, str],
    deadline: datetime,
    private_directory: Path,
    purpose: str = "failure",
) -> Path:
    """Best-effort, bounded exact-execution reads before destructive cleanup.

    Raw responses are private diagnostics, never admitting campaign evidence.
    """
    from infra.milestone_7_8.controller_renewal import _durable_record

    directory = private_directory / f"job-{purpose}-{uuid.uuid4().hex}"
    directory.mkdir(mode=0o700)
    persistence_failed = False

    def record(name: str, value: object) -> None:
        nonlocal persistence_failed
        try:
            _durable_record(directory / name, value)
        except Exception:
            persistence_failed = True
            raise

    record(
        "execution.json",
        {
            "sourceHead": runtime["sourceHead"],
            "executionName": failure.execution,
            "command": failure.command,
            "startResult": failure.start,
            "lastResult": failure.last,
            "observedAtUtc": datetime.now(UTC).isoformat(),
        },
    )
    command = failure.command
    group = command[command.index("--resource-group") + 1]
    job = command[command.index("--name") + 1]
    subscription = runtime["subscriptionId"]
    if (
        group != runtime["resourceGroupName"]
        or job not in {value for key, value in runtime.items() if key.endswith("JobName")}
        or (
            "--subscription" in command
            and command[command.index("--subscription") + 1] != subscription
        )
    ):
        raise CampaignError("failed job diagnostic scope differs")
    # Validate all endpoint segments before any request or KQL interpolation.
    worker_replica_url(subscription, group, job, failure.execution)
    expected_execution_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.App/jobs/{job}/executions/{failure.execution}"
    )
    for raw in (failure.start, failure.last):
        value = _json_result(raw)
        if not isinstance(value, dict) or (
            value.get("name", failure.execution) != failure.execution
            or ("id" in value and str(value["id"]).casefold() != expected_execution_id.casefold())
        ):
            raise CampaignError("failed job diagnostic execution identity differs")
    expires = time.monotonic() + 60
    count = 0

    class Capture:
        def run(self, request: tuple[str, ...]) -> dict[str, object]:
            nonlocal count
            remaining = min(
                expires - time.monotonic(),
                (deadline - datetime.now(UTC)).total_seconds(),
            )
            if count >= 6 or remaining <= 10 or persistence_failed:
                raise CampaignError("failed job diagnostic read budget exhausted")
            count += 1
            scoped = (*request, "--subscription", subscription)
            record(
                f"{count:02d}-intent.json",
                {
                    "command": scoped,
                    "requestedAtUtc": datetime.now(UTC).isoformat(),
                },
            )
            remaining = min(
                expires - time.monotonic(),
                (deadline - datetime.now(UTC)).total_seconds(),
            )
            if remaining <= 10:
                raise CampaignError("failed job diagnostic read budget exhausted")
            try:
                response = SubprocessRunner(
                    timeout_seconds=min(15, remaining - 10),
                    diagnostic_capture_directory=directory,
                ).run(scoped)
            except Exception as exc:
                record(f"{count:02d}-exception.json", {"errorClass": type(exc).__name__})
                raise
            record(f"{count:02d}-result.json", response)
            return response

    capture = Capture()
    status = {"replicas": "unavailable", "console": "unavailable"}
    names: list[str] = []
    try:
        replicas = collect_worker_replicas(
            capture,
            subscription=subscription,
            group=group,
            job=job,
            execution=failure.execution,
        )
        pages = cast(list[dict[str, object]], replicas["pages"])
        names = [
            str(item["name"])
            for page in pages
            for item in cast(list[dict[str, object]], page["value"])
        ]
        if (
            not names
            or len(names) > 32
            or any(not name.startswith(f"{failure.execution}-") for name in names)
        ):
            raise CampaignError("failed job replica identity differs")
        record("replicas.json", replicas)
        status["replicas"] = "captured"
    except Exception:
        if persistence_failed:
            raise
    try:
        if status["replicas"] != "captured":
            raise CampaignError("exact failed job console scope is unavailable")
        workspace = runtime["logAnalyticsWorkspaceName"]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", workspace) is None:
            raise CampaignError("failed job workspace identity is invalid")
        shown = capture.run(
            (
                "az",
                "monitor",
                "log-analytics",
                "workspace",
                "show",
                "--resource-group",
                group,
                "--workspace-name",
                workspace,
                "--output",
                "json",
            )
        )
        value = _json_result(shown)
        expected_workspace_id = (
            f"/subscriptions/{subscription}/resourceGroups/{group}"
            f"/providers/Microsoft.OperationalInsights/workspaces/{workspace}"
        )
        if (
            shown.get("exitCode") != 0
            or not isinstance(value, dict)
            or (str(value.get("id", "")).casefold() != expected_workspace_id.casefold())
        ):
            raise CampaignError("failed job workspace readback differs")
        customer = uuid.UUID(str(value.get("customerId", "")))
        if customer.int == 0:
            raise CampaignError("failed job workspace identity is invalid")
        exact_names = ",".join(f"'{name}'" for name in names)
        query = (
            "ContainerAppConsoleLogs_CL"
            f" | where ContainerGroupName_s in ({exact_names})"
            " | project TimeGenerated, ContainerGroupName_s, ContainerName_s, Log_s | take 1001"
        )
        logs = capture.run(
            (
                "az",
                "monitor",
                "log-analytics",
                "query",
                "--workspace",
                str(customer),
                "--analytics-query",
                query,
                "--timespan",
                "PT30M",
                "--output",
                "json",
            )
        )
        rows = _json_result(logs)
        if (
            logs.get("exitCode") != 0
            or not isinstance(rows, list)
            or len(rows) > 1001
            or any(
                not isinstance(row, dict) or row.get("ContainerGroupName_s") not in names
                for row in rows
            )
        ):
            raise CampaignError("failed job console read failed or returned another replica")
        # A bounded console capture is diagnostic only; never claim completeness.
        record("console.json", rows)
        status["console"] = "captured-bounded"
    except Exception:
        if persistence_failed:
            raise
    record("capture-status.json", {**status, "readAttempts": count, "admissionEvidence": False})
    return directory


def _wait_for_job(
    runner: CommandRunner,
    start_command: tuple[str, ...],
    start_result: dict[str, object],
    *,
    deadline: datetime | None = None,
    maximum_wait_seconds: int = 900,
) -> dict[str, object]:
    value = _json_result(start_result)
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise CampaignError("container job execution identity is missing")
    execution_name = str(value["name"])
    status = _job_status(value)
    last_result = start_result
    resource_group = start_command[start_command.index("--resource-group") + 1]
    job_name = start_command[start_command.index("--name") + 1]
    subscription: tuple[str, ...] = ()
    if "--subscription" in start_command:
        index = start_command.index("--subscription")
        subscription = start_command[index:index + 2]
    for _ in range((maximum_wait_seconds + 4) // 5):
        if deadline is not None and datetime.now(UTC) >= deadline:
            raise _ProtectedStageExpired("database retry cleanup deadline expired")
        if status == "Succeeded":
            return {
                "executionName": execution_name,
                "terminalStatus": status,
                "executionReadback": last_result,
            }
        if status in {"Failed", "Stopped", "Degraded"}:
            raise _JobExecutionFailure(
                "container job evidence failed",
                start_command,
                start_result,
                last_result,
                execution_name,
            )
        time.sleep(
            min(5, max(0, (deadline - datetime.now(UTC)).total_seconds()))
            if deadline is not None
            else 5
        )
        if deadline is not None and datetime.now(UTC) >= deadline:
            raise _ProtectedStageExpired("database retry cleanup deadline expired")
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
                *subscription,
                "--output",
                "json",
            ),
        )
        last_result = shown
        status = _job_status(_json_result(shown))
    raise _JobExecutionFailure(
        "container job evidence timed out",
        start_command,
        start_result,
        last_result,
        execution_name,
    )


def _active_protected_pause(
    directory: Path,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    source_transition: dict[str, object] | None = None,
    *, resolved_image_pause_sha256: str | None = None,
    resolved_workload_pause_sha256: str | None = None,
) -> dict[str, object] | None:
    grant_only = _grant_only_transition(source_transition)
    active: list[dict[str, object]] = []
    for operation in sorted(PROTECTED_STAGE_OPERATIONS):
        history_directory = directory
        if grant_only and operation == "migrate":
            assert source_transition is not None
            history_directory = Path(str(source_transition["recoveryDirectory"]))
        path = history_directory / f"{operation}-stage-pause.json"
        if grant_only and operation == "migrate":
            assert source_transition is not None
            if path.exists():
                raise _ProtectedStagePaused(
                    "grant-only recovery must preserve its plan-bound pause"
                )
            pause = _grant_recovery_pause(source_transition)
        elif not path.exists():
            continue
        else:
            pause = _read_stage_record(path, "stage-pause")
        if (
            set(pause)
            != {
                "version",
                "operation",
                "bindings",
                "attemptSha256",
                "authorizationSha256",
                "failedExecution",
                "failedAtUtc",
                "recoveryUntilUtc",
                "maximumRetryDispatches",
                "recordSha256",
            }
            or pause["version"] != "m7.8-protected-stage-pause-v1"
            or pause["operation"] != operation
        ):
            raise _ProtectedStagePaused("protected stage pause contract differs")
        if (operation == "local-image" and resolved_image_pause_sha256 is not None
                and hashlib.sha256(path.read_bytes()).hexdigest() == resolved_image_pause_sha256):
            # Supplied only after the complete predecessor-bound image admission
            # has replayed. The failed attempt and its original window stay intact.
            continue
        if (operation == "image-decision" and resolved_workload_pause_sha256 is not None
                and hashlib.sha256(path.read_bytes()).hexdigest()
                == resolved_workload_pause_sha256):
            continue
        migration_history = (
            operation == "migrate" and _migration_image_transition(source_transition)
        )
        if migration_history:
            assert source_transition is not None
            if grant_only:
                _grant_recovery_pause(source_transition)
            elif (
                hashlib.sha256(path.read_bytes()).hexdigest()
                != source_transition["migrationPauseSha256"]
                or pause["bindings"] != source_transition["originalBindings"]
            ):
                raise _ProtectedStagePaused("migration continuation original pause differs")
            if not grant_only:
                original = _database_attempt_history(directory, operation, pause)
                if original["recordSha256"] != source_transition["originalAttemptSha256"]:
                    raise _ProtectedStagePaused("migration continuation original attempt differs")
        completed_path = history_directory / f"{operation}-stage-recovery-completed.json"
        if completed_path.exists():
            if operation == "evidence":
                _reconcile_evidence_stage_completion(directory, config, runtime, ledger)
                continue
            if operation not in {"bootstrap", "migrate"}:
                raise _ProtectedStagePaused("this stage has no supported completion reconciliation")
            if not grant_only:
                _database_attempt_history(directory, operation, pause)
            retry = _read_stage_record(
                history_directory / f"{operation}-stage-retry-intent.json", "stage-retry-intent"
            )
            started = _read_stage_record(
                history_directory / f"{operation}-stage-retry-start.json", "stage-retry-start"
            )
            completed = _read_stage_record(completed_path, "stage-recovery-completed")
            if grant_only:
                _validate_committed_grant_proof(completed.get("runtimeGrantProof"))
            _require_retry_source(retry, source_transition)
            _require_retry_source(completed, source_transition)
            if (
                completed.get("retryIntentSha256") != retry["recordSha256"]
                or retry.get("pauseSha256") != pause["recordSha256"]
                or started.get("retryIntentSha256") != retry["recordSha256"]
            ):
                raise _ProtectedStagePaused("database completion history binding differs")
            capture_name = completed.get("capture")
            if (
                not isinstance(capture_name, str)
                or re.fullmatch(r"job-recovery-[a-f0-9]{32}", capture_name) is None
            ):
                raise _ProtectedStagePaused("database completion capture binding differs")
            capture = history_directory / capture_name
            try:
                hashes = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in capture.iterdir()
                    if path.is_file()
                }
            except OSError as exc:
                raise _ProtectedStagePaused("database completion capture is unavailable") from exc
            if not hashes or hashes != completed.get("captureFilesSha256"):
                raise _ProtectedStagePaused("database completion capture was altered")
            bindings = pause.get("bindings")
            if (
                completed.get("pauseSha256") != pause["recordSha256"]
                or completed.get("sourceHead") != runtime["sourceHead"]
                or not isinstance(bindings, dict)
                or ORDER.index(Phase(ledger.phase))
                <= ORDER.index(Phase(str(bindings["ledgerPhase"])))
            ):
                raise _ProtectedStagePaused("protected stage completion or ledger is inconsistent")
            continue
        if not migration_history and pause["bindings"] != _stage_bindings(config, runtime, ledger):
            raise _ProtectedStagePaused("protected stage pause binding differs")
        active.append(pause)
    if len(active) > 1:
        raise _ProtectedStagePaused("multiple protected stages are paused")
    return active[0] if active else None


def _migration_image_transition(transition: dict[str, object] | None) -> bool:
    return transition is not None and transition.get("kind") == "migration-image-continuation"


def _grant_only_transition(transition: dict[str, object] | None) -> bool:
    return _migration_image_transition(transition) and transition is not None and (
        transition.get("grantOnly") is True
    )


def _grant_recovery_pause(transition: dict[str, object]) -> dict[str, object]:
    pause = transition.get("recoveryPause")
    if not isinstance(pause, dict):
        raise _ProtectedStagePaused("grant recovery has no bound failed retry")
    body = {key: value for key, value in pause.items() if key != "recordSha256"}
    if (pause.get("recordSha256") != _stage_hash("stage-pause", body)
            or pause.get("bindings") != transition.get("originalBindings")
            or pause.get("attemptSha256") != transition.get("originalConsumedRetryIntentSha256")
            or pause.get("attemptSha256") != transition.get("originalAttemptSha256")
            or type(pause.get("maximumRetryDispatches")) is not int
            or pause.get("maximumRetryDispatches") != 1):
        raise _ProtectedStagePaused("grant recovery consumed retry binding differs")
    return cast(dict[str, object], pause)


def _source_transition_metadata(
    transition: dict[str, object] | None,
) -> dict[str, object]:
    if transition is None:
        return {}
    key = ("migrationImageTransitionSha256" if _migration_image_transition(transition)
           else "bootstrapSourceTransitionSha256")
    return {
        "operatorSourceHead": transition["operatorSourceHead"],
        key: transition["transitionSha256"],
        **({"grantOnly": True} if _grant_only_transition(transition) else {}),
    }


def _require_retry_source(
    record: dict[str, object], transition: dict[str, object] | None,
) -> None:
    names = {
        "operatorSourceHead", "bootstrapSourceTransitionSha256", "migrationImageTransitionSha256",
        "grantOnly",
    }
    actual = {name: record[name] for name in names if name in record}
    if actual != _source_transition_metadata(transition):
        raise _ProtectedStagePaused("database retry executing-source transition differs")


def _validate_transition_dispatch(transition: dict[str, object]) -> None:
    from infra.milestone_7_8.bootstrap_transition import validate_dispatch_window

    try:
        if _grant_only_transition(transition) and datetime.now(UTC) >= parse_utc(
            str(transition["cleanupMustBeginByUtc"])
        ):
            raise CampaignError("grant-only recovery cleanup-start cutoff is closed")
        if _migration_image_transition(transition):
            from infra.milestone_7_8.image_continuation import validate_migration_retry_window

            validate_migration_retry_window(transition, now=datetime.now(UTC))
        else:
            validate_dispatch_window(transition, datetime.now(UTC))
    except CampaignError as exc:
        # An expired retry permission does not itself revoke cleanup protection.
        raise _ProtectedStagePaused(str(exc)) from exc


def _database_recovery_deadline(
    config: CampaignConfig, transition: dict[str, object] | None,
) -> datetime:
    deadline = parse_utc(config.cleanup_deadline_utc)
    if _grant_only_transition(transition):
        assert transition is not None
        deadline = min(deadline, parse_utc(str(transition["cleanupMustBeginByUtc"])))
    return deadline


def _validate_committed_grant_proof(value: object) -> dict[str, object]:
    if (not isinstance(value, dict)
            or set(value) != {"version", "status", "alembicRevision", "routines"}
            or value["version"] != "m7.8-runtime-grant-reconciliation-v1"
            or value["status"] != "committed" or value["alembicRevision"] != "20260726_0029"
            or not isinstance(value["routines"], dict)
            or set(value["routines"]) != {"api", "worker"}):
        raise _ProtectedStagePaused("grant-only recovery commit proof is incomplete")
    expected = {"public.vector(public.vector, pg_catalog.int4, pg_catalog.bool)"}
    fields = {"functionObjectsChecked", "effectiveExecuteCount", "requiredVectorSignatures",
              "providerPublicVectorRoutineCount", "providerPublicVectorExtensionVersion",
              "providerPublicVectorInventorySha256"}
    observations: list[tuple[object, object, object]] = []
    for role, profile in value["routines"].items():
        signatures = expected | (
            {"public.cosine_distance(public.vector, public.vector)"} if role == "api" else set()
        )
        if (not isinstance(profile, dict) or set(profile) != fields
                or type(profile["functionObjectsChecked"]) is not int
                or profile["functionObjectsChecked"] < 118
                or type(profile["effectiveExecuteCount"]) is not int
                or profile["effectiveExecuteCount"] != 118
                or type(profile["providerPublicVectorRoutineCount"]) is not int
                or profile["providerPublicVectorRoutineCount"] != 118
                or profile["requiredVectorSignatures"] != sorted(signatures)
                or not isinstance(profile["providerPublicVectorExtensionVersion"], str)
                or not profile["providerPublicVectorExtensionVersion"]
                or re.fullmatch(r"[a-f0-9]{64}", str(
                    profile["providerPublicVectorInventorySha256"]
                )) is None):
            raise _ProtectedStagePaused("grant-only recovery routine baseline differs")
        observations.append((profile["functionObjectsChecked"],
                             profile["providerPublicVectorExtensionVersion"],
                             profile["providerPublicVectorInventorySha256"]))
    if observations[0] != observations[1]:
        raise _ProtectedStagePaused("grant-only recovery role baselines disagree")
    return cast(dict[str, object], value)


def _retry_template_semantics(value: object) -> dict[str, object]:
    """Normalize provider-only empty fields in copies; retain every raw observation."""
    if not isinstance(value, dict):
        raise _ProtectedStagePaused("database retry template is malformed")
    normalized = dict(value)
    for field in ("initContainers", "volumes"):
        observed = value.get(field)
        if observed is None:
            normalized[field] = []
        elif not isinstance(observed, list):
            raise _ProtectedStagePaused("database retry optional template collection is malformed")
    containers = value.get("containers")
    if not isinstance(containers, list):
        raise _ProtectedStagePaused("database retry template containers are malformed")
    normalized_containers: list[dict[str, object]] = []
    for container in containers:
        resources = container.get("resources") if isinstance(container, dict) else None
        if not isinstance(container, dict) or not isinstance(resources, dict):
            raise _ProtectedStagePaused("database retry container allocation is malformed")
        # ARM declares ephemeralStorage read-only. The same bounded job/execution
        # returns its unspecified value as absent, null, or empty string. Never
        # accept a nonempty allocation or coerce another value into this default.
        ephemeral = resources.get("ephemeralStorage")
        if ephemeral is not None and ephemeral != "":
            raise _ProtectedStagePaused("database retry ephemeral storage is not empty")
        normalized_containers.append({
            **container,
            "resources": {key: observed for key, observed in resources.items()
                          if key != "ephemeralStorage"},
        })
    normalized["containers"] = normalized_containers
    return normalized


def _validate_retry_job_limits(
    operation: str,
    resource: dict[str, object],
    failed_template: object,
    *, source_transition: dict[str, object] | None = None,
) -> tuple[dict[str, object], str]:
    properties = resource.get("properties")
    configuration = properties.get("configuration") if isinstance(properties, dict) else None
    template = properties.get("template") if isinstance(properties, dict) else None
    manual = configuration.get("manualTriggerConfig") if isinstance(configuration, dict) else None
    containers = template.get("containers") if isinstance(template, dict) else None
    prior_containers = (
        failed_template.get("containers") if isinstance(failed_template, dict) else None
    )
    timeout = 900 if operation == "bootstrap" else 1800
    if (
        not isinstance(configuration, dict)
        or configuration.get("triggerType") != "Manual"
        or type(configuration.get("replicaTimeout")) is not int
        or not 0 < configuration["replicaTimeout"] <= timeout
        or type(configuration.get("replicaRetryLimit")) is not int
        or configuration["replicaRetryLimit"] != 0
        or not isinstance(manual, dict)
        or type(manual.get("parallelism")) is not int
        or manual["parallelism"] != 1
        or type(manual.get("replicaCompletionCount")) is not int
        or manual["replicaCompletionCount"] != 1
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(prior_containers, list)
        or len(prior_containers) != 1
        or not isinstance(containers[0], dict)
        or not isinstance(prior_containers[0], dict)
    ):
        raise _ProtectedStagePaused("database retry workload limits or history are unproved")
    container = containers[0]
    previous = prior_containers[0]
    assert isinstance(template, dict) and isinstance(failed_template, dict)
    if template.get("initContainers") not in (None, []) or failed_template.get(
        "initContainers"
    ) not in (None, []):
        raise _ProtectedStagePaused("database retry contains unpriced initialization containers")
    normalized = _retry_template_semantics(template)
    normalized_prior = _retry_template_semantics(failed_template)
    for representation in (normalized, normalized_prior):
        normalized_container = cast(list[dict[str, object]], representation["containers"])[0]
        representation["containers"] = [
            {key: value for key, value in normalized_container.items() if key != "args"},
        ]
    if _migration_image_transition(source_transition):
        assert source_transition is not None
        if (operation != "migrate"
                or previous.get("image") != source_transition["previousImageReference"]
                or container.get("image") != source_transition["replacementImageReference"]
                or previous.get("image") == container.get("image")):
            raise _ProtectedStagePaused("migration retry accepted image transition differs")
        normalized_prior["containers"] = [{
            **cast(dict[str, object], cast(list[object], normalized_prior["containers"])[0]),
            "image": source_transition["replacementImageReference"],
        }]
    if normalized != normalized_prior:
        raise _ProtectedStagePaused(
            "database retry image, command, environment, or template drifted"
        )
    resources = container.get("resources")
    if not isinstance(resources, dict):
        raise _ProtectedStagePaused("database retry allocation is missing")
    cpu, memory = resources.get("cpu"), resources.get("memory")
    memory_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(Gi|Mi)", str(memory))
    if type(cpu) not in (int, float) or not 0 < float(cast(float, cpu)) <= 0.5 or not memory_match:
        raise _ProtectedStagePaused("database retry allocation exceeds the reviewed allowance")
    gib = Decimal(memory_match[1]) / (1024 if memory_match[2] == "Mi" else 1)
    if not 0 < gib <= 1:
        raise _ProtectedStagePaused("database retry allocation exceeds the reviewed allowance")
    env = container.get("env")
    manifests = (
        [
            item.get("value")
            for item in env
            if isinstance(item, dict)
            and item.get("name") == "OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST"
        ]
        if isinstance(env, list)
        else []
    )
    if len(manifests) != 1 or not isinstance(manifests[0], str):
        raise _ProtectedStagePaused("database retry manifest is missing or ambiguous")
    manifest = json.loads(manifests[0])
    if not isinstance(manifest, dict):
        raise _ProtectedStagePaused("database retry manifest is malformed")
    return cast(dict[str, object], manifest), _stage_hash("database-recovery-manifest", manifest)


def _database_prerequisites(
    runner: SubprocessRunner,
    command: tuple[str, ...],
    *,
    operation: str,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    directory: Path,
    authorization_path: Path,
    retry: bool,
    allow_fresh_retry: bool = False,
    source_transition: dict[str, object] | None = None,
) -> None:
    from infra.milestone_7_8.database_prerequisites import (
        PREREQUISITE_MARKER,
        PREREQUISITE_TOKEN,
        validate_database_template,
        validate_prerequisite_marker,
    )
    from infra.milestone_7_8.evidence_console import read_job_marker

    deadline = _database_recovery_deadline(config, source_transition)
    receipt = directory / f"{operation}-prerequisites.json"
    intent = directory / f"{operation}-prerequisite-intent.json"
    bindings = _stage_bindings(config, runtime, ledger)
    if receipt.exists():
        record = _read_stage_record(receipt, "database-prerequisites")
        request = _read_stage_record(intent, "database-prerequisite-intent")
        if (
            record.get("bindings") != bindings
            or record.get("operation") != operation
            or record.get("intentSha256") != request["recordSha256"]
        ):
            raise _ProtectedStagePaused("database prerequisite receipt binding differs")
        marker = validate_prerequisite_marker(
            record.get("marker"), operation=operation,
            campaign_id=config.campaign_id, generation_id=config.generation_id,
        )
        if retry and marker["listingRead"] is not True:
            raise _ProtectedStagePaused("migration identity listing is unproved for guarded retry")
        return
    if allow_fresh_retry and (operation != "migrate" or not retry):
        raise _ProtectedStagePaused("corrected prerequisite is limited to the migration retry")
    if intent.exists() or (retry and not allow_fresh_retry):
        raise _ProtectedStagePaused("database prerequisite evidence is incomplete")
    if allow_fresh_retry:
        allocation = ("grant-recovery-prerequisite" if _grant_only_transition(source_transition)
                      else "corrected-migration-prerequisite")
        corrected = [item for item in config.resource_items
                     if item.name == allocation]
        if len(corrected) != 1 or corrected[0].maximum() < Decimal("0.0378"):
            raise _ProtectedStagePaused("corrected migration prerequisite allowance is missing")
    allocated = [
        item for item in config.resource_items if item.name == "database-prerequisites"
    ]
    if len(allocated) != 1 or allocated[0].maximum() < Decimal("0.0567"):
        raise _ProtectedStagePaused("two database prerequisite jobs are not covered by cost gate")
    if not ledger.image_digest:
        raise _ProtectedStagePaused("database prerequisite image is missing")
    _verify_retry_protection(runner, config, runtime, ledger)
    token = uuid.uuid4().hex
    started_by = time.monotonic() + 600
    job = runtime["bootstrapJobName" if operation == "bootstrap" else "migrationJobName"]
    container = ""
    intent_sha256 = ""
    diagnostic_command = (
        *command,
        "--args=--diagnose-prerequisites",
        "--env-vars",
        f"{PREREQUISITE_TOKEN}={token}",
    )
    if "--subscription" not in diagnostic_command:
        diagnostic_command += ("--subscription", runtime["subscriptionId"])

    def check_authority() -> None:
        if not _stage_is_protected(config, runtime, ledger):
            raise _ProtectedStageExpired("database prerequisite protection expired")
        if allow_fresh_retry:
            if not _migration_image_transition(source_transition):
                raise _ProtectedStagePaused("corrected prerequisite transition is missing")
            assert source_transition is not None
            _validate_transition_dispatch(source_transition)
        for required in (operation, "cleanup"):
            load_execution_authorization(
                authorization_path, config=config, runtime=runtime, operation=required,
            )

    class DiagnosticRunner:
        def run(self, request: tuple[str, ...]) -> dict[str, object]:
            remaining = min(
                started_by - time.monotonic(), (deadline - datetime.now(UTC)).total_seconds(),
            )
            if remaining <= 0:
                raise CampaignError("database prerequisite time budget is exhausted")
            return SubprocessRunner(
                timeout_seconds=min(30, remaining),
                diagnostic_capture_directory=directory,
            ).run(request)

    diagnostic_runner = DiagnosticRunner()
    def before_dispatch(resource: dict[str, object]) -> None:
        nonlocal container, intent_sha256
        properties = resource.get("properties")
        template = properties.get("template") if isinstance(properties, dict) else None
        manifest, _ = _validate_retry_job_limits(operation, resource, template)
        if (
            manifest.get("campaignId") != config.campaign_id
            or manifest.get("generationId") != config.generation_id
            or manifest.get("subscriptionCorrelation") != config.subscription_correlation
        ):
            raise _ProtectedStagePaused("database prerequisite manifest binding differs")
        container = validate_database_template(
            resource, manifest, operation=operation, subscription=runtime["subscriptionId"],
            group=runtime["resourceGroupName"], server=runtime["postgresServerName"],
            registry=runtime["registryName"], image_digest=str(ledger.image_digest),
        )
        check_authority()
        request = _stage_record(intent, "database-prerequisite-intent", {
            "operation": operation, "bindings": bindings, "token": token,
            "authorizationSha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
            "templateSha256": _stage_hash("stage-template", resource),
            "startedAtUtc": datetime.now(UTC).isoformat(),
        })
        intent_sha256 = str(request["recordSha256"])
        check_authority()

    module = (
        "scripts.bootstrap_postgres" if operation == "bootstrap" else "scripts.migrate_and_grant"
    )
    try:
        started = start_evidence_job(
            diagnostic_runner, diagnostic_command, private_directory=directory,
            image_digest=ledger.image_digest, expected_command=("python", "-m", module),
            before_dispatch=before_dispatch,
        )
        if started.get("exitCode") != 0:
            raise CampaignError("database prerequisite dispatch is unproved")
        _stage_record(directory / f"{operation}-prerequisite-start.json",
                      "database-prerequisite-start", started)
        waited = _wait_for_job(
            diagnostic_runner, diagnostic_command, started, deadline=deadline,
            maximum_wait_seconds=240,
        )
        execution = str(waited["executionName"])
        response = _json_result(cast(dict[str, object], waited["executionReadback"]))
        expected_id = (
            f"/subscriptions/{runtime['subscriptionId']}"
            f"/resourceGroups/{runtime['resourceGroupName']}"
            f"/providers/Microsoft.App/jobs/{job}/executions/{execution}"
        )
        if (
            not isinstance(response, dict)
            or response.get("name") != execution
            or str(response.get("id", "")).casefold() != expected_id.casefold()
        ):
            raise CampaignError("database prerequisite execution readback differs")
        marker = validate_prerequisite_marker(
            read_job_marker(
                diagnostic_runner,
                subscription=runtime["subscriptionId"], group=runtime["resourceGroupName"],
                workspace=runtime["logAnalyticsWorkspaceName"], job=job, execution=execution,
                container=container, marker=PREREQUISITE_MARKER, token=token, deadline=deadline,
                maximum_wait_seconds=240,
            ),
            operation=operation, campaign_id=config.campaign_id, generation_id=config.generation_id,
        )
        if retry and marker["listingRead"] is not True:
            raise _ProtectedStagePaused("migration identity listing is unproved for guarded retry")
        check_authority()
    except _ProtectedStageExpired:
        raise
    except _JobExecutionFailure as exc:
        _capture_failed_job_diagnostics(
            exc, runtime=runtime, deadline=deadline, private_directory=directory,
            purpose="database-prerequisite",
        )
        raise _ProtectedStagePaused("database prerequisite failed before the mutation job") from exc
    except (AzureCliError, CampaignError, ValueError) as exc:
        raise _ProtectedStagePaused(str(exc)) from exc
    _stage_record(receipt, "database-prerequisites", {
        "operation": operation, "bindings": bindings, "execution": execution,
        "intentSha256": intent_sha256,
        "marker": marker, "completedAtUtc": datetime.now(UTC).isoformat(),
    })


def _database_attempt_history(
    directory: Path,
    operation: str,
    pause: dict[str, object],
) -> dict[str, object]:
    original = _read_stage_record(directory / f"{operation}-stage-attempt.json", "stage-attempt")
    if (
        set(original)
        != {
            "version",
            "operation",
            "bindings",
            "commandSha256",
            "authorizationSha256",
            "startedAtUtc",
            "recordSha256",
        }
        or original.get("version") != "m7.8-protected-stage-attempt-v1"
        or original.get("operation") != operation
        or original.get("bindings") != pause["bindings"]
        or original.get("recordSha256") != pause["attemptSha256"]
        or original.get("authorizationSha256") != pause["authorizationSha256"]
    ):
        raise _ProtectedStagePaused("database original attempt history is missing or mismatched")
    return original


def _verify_retry_protection(
    runner: CommandRunner,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
) -> list[dict[str, object]]:
    results = execute_commands(
        runner,
        tuple(
            (*read, "--subscription", runtime["subscriptionId"])
            for read in command_plan("cleanup-verify", config, runtime)
        ),
    )
    try:
        arm_hash = validate_cleanup_readback(results, config, runtime)
    except CampaignError as exc:
        raise _ProtectedStageExpired("database retry cleanup protection is invalid") from exc
    if arm_hash != ledger.cleanup_arm_evidence_sha256:
        raise _ProtectedStageExpired("database retry cleanup protection changed")
    if not _stage_is_protected(config, runtime, ledger):
        raise _ProtectedStageExpired("database retry protection expired")
    return results


def _execute_database_retry(
    runner: SubprocessRunner,
    command: tuple[str, ...],
    *,
    operation: str,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    pause: dict[str, object],
    directory: Path,
    authorization_path: Path,
    source_transition: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    transition_window = source_transition if (
        operation == "bootstrap" or (operation == "migrate"
                                    and _migration_image_transition(source_transition))
    ) else None
    window_start = parse_utc(str(
        transition_window["issuedAtUtc"] if transition_window else pause["failedAtUtc"]
    ))
    window_end = parse_utc(str(
        transition_window["expiresAtUtc"] if transition_window else pause["recoveryUntilUtc"]
    ))
    failed = pause.get("failedExecution")
    if (
        not isinstance(failed, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", failed) is None
    ):
        raise _ProtectedStagePaused("database retry lacks an exact failed execution")
    if pause.get("maximumRetryDispatches") != 1:
        raise _ProtectedStagePaused("database retry attempt bound differs")
    grant_only = _grant_only_transition(source_transition)
    if grant_only:
        assert source_transition is not None
        if operation != "migrate" or pause != _grant_recovery_pause(source_transition):
            raise _ProtectedStagePaused("grant-only recovery failed-attempt binding differs")
    else:
        _database_attempt_history(directory, operation, pause)
    retry_path = directory / f"{operation}-stage-retry-intent.json"
    if (directory / f"{operation}-stage-retry-start.json").exists() and not retry_path.exists():
        raise _ProtectedStagePaused("database retry intent history is missing")
    retry_command = (
        *command,
        *(("--subscription", runtime["subscriptionId"]) if "--subscription" not in command else ()),
        f"--args=--retry-after-execution={failed}",
    )
    if retry_path.exists():
        attempt = _read_stage_record(retry_path, "stage-retry-intent")
        _require_retry_source(attempt, source_transition)
        saved = _read_stage_record(
            directory / f"{operation}-stage-retry-start.json", "stage-retry-start"
        )
        if (
            attempt.get("version") != "m7.8-stage-retry-intent-v1"
            or attempt.get("operation") != operation
            or attempt.get("pauseSha256") != pause["recordSha256"]
            or attempt.get("bindings") != _stage_bindings(config, runtime, ledger)
            or attempt.get("commandSha256") != _stage_hash("stage-command", retry_command)
            or saved.get("retryIntentSha256") != attempt["recordSha256"]
            or not isinstance(saved.get("startResult"), dict)
            or not isinstance(attempt.get("validatedJob"), dict)
            or attempt.get("templateSha256")
            != _stage_hash("stage-template", attempt["validatedJob"])
            or not window_start
            <= parse_utc(str(attempt["startedAtUtc"]))
            < window_end
        ):
            raise _ProtectedStagePaused(
                "database retry dispatch history is incomplete or mismatched"
            )
        previous = _json_result(cast(dict[str, object], attempt["oldExecution"]))
        props = previous.get("properties") if isinstance(previous, dict) else None
        template = props.get("template") if isinstance(props, dict) else None
        _, manifest_hash = _validate_retry_job_limits(
            operation,
            cast(dict[str, object], attempt["validatedJob"]),
            template,
            source_transition=source_transition,
        )
        _verify_retry_protection(runner, config, runtime, ledger)
        for required in (operation, "cleanup"):
            load_execution_authorization(
                authorization_path, config=config, runtime=runtime, operation=required
            )
        return _finish_database_retry(
            retry_command,
            cast(dict[str, object], saved["startResult"]),
            attempt,
            operation=operation,
            config=config,
            runtime=runtime,
            ledger=ledger,
            pause=pause,
            directory=directory,
            failed=failed,
            expected_manifest_hash=manifest_hash,
            source_transition=source_transition,
        )
    allocation = "grant-recovery-job" if grant_only else "database-recovery-job-allowance"
    allowance = [item for item in config.resource_items if item.name == allocation]
    minimum = Decimal("0.0378") if grant_only else Decimal("0.0567")
    if len(allowance) != 1 or allowance[0].maximum() < minimum:
        raise _ProtectedStagePaused(
            "database retry cost allowance is missing from the gated config"
        )
    group, subscription = runtime["resourceGroupName"], runtime["subscriptionId"]
    job = runtime["bootstrapJobName" if operation == "bootstrap" else "migrationJobName"]
    shown = _run_required(
        runner,
        (
            "az",
            "containerapp",
            "job",
            "execution",
            "show",
            "--resource-group",
            group,
            "--name",
            job,
            "--job-execution-name",
            failed,
            "--subscription",
            subscription,
            "--output",
            "json",
        ),
    )
    old = _json_result(shown)
    expected_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.App/jobs/{job}/executions/{failed}"
    )
    if (
        not isinstance(old, dict)
        or old.get("name") != failed
        or str(old.get("id", "")).casefold() != expected_id.casefold()
        or _job_status(old) not in {"Failed", "Stopped", "Degraded"}
    ):
        raise _ProtectedStagePaused("previous database execution is not exactly terminal")
    properties = old.get("properties")
    failed_template = properties.get("template") if isinstance(properties, dict) else None
    cleanup_results = _verify_retry_protection(runner, config, runtime, ledger)
    retry_command = (
        *command,
        *(("--subscription", subscription) if "--subscription" not in command else ()),
        f"--args=--retry-after-execution={failed}",
    )
    attempt = {}
    expected_manifest_hash = ""

    def before_dispatch(resource: dict[str, object]) -> None:
        nonlocal attempt, expected_manifest_hash
        manifest, expected_manifest_hash = _validate_retry_job_limits(
            operation, resource, failed_template, source_transition=source_transition,
        )
        if (
            manifest.get("campaignId") != config.campaign_id
            or manifest.get("generationId") != config.generation_id
        ):
            raise _ProtectedStagePaused("database retry manifest campaign differs")
        if not _stage_is_protected(config, runtime, ledger):
            raise _ProtectedStageExpired("database recovery protection expired")
        if transition_window is not None:
            _validate_transition_dispatch(transition_window)
        elif window_end <= datetime.now(UTC):
            raise _ProtectedStageExpired("database recovery window expired")
        for required in (operation, "cleanup"):
            load_execution_authorization(
                authorization_path,
                config=config,
                runtime=runtime,
                operation=required,
            )
        attempt = _stage_record(
            retry_path,
            "stage-retry-intent",
            {
                "version": "m7.8-stage-retry-intent-v1",
                "operation": operation,
                "pauseSha256": pause["recordSha256"],
                "bindings": _stage_bindings(config, runtime, ledger),
                "commandSha256": _stage_hash("stage-command", retry_command),
                "templateSha256": _stage_hash("stage-template", resource),
                "validatedJob": resource,
                "authorizationSha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
                "startedAtUtc": datetime.now(UTC).isoformat(),
                "oldExecution": shown,
                "cleanupReadbacks": cleanup_results,
                **_source_transition_metadata(source_transition),
            },
        )
        if not _stage_is_protected(config, runtime, ledger):
            raise _ProtectedStageExpired("database recovery protection expired before dispatch")
        if transition_window is not None:
            _validate_transition_dispatch(transition_window)
        elif window_end <= datetime.now(UTC):
            raise _ProtectedStageExpired("database recovery window expired before dispatch")
        for required in (operation, "cleanup"):
            load_execution_authorization(
                authorization_path,
                config=config,
                runtime=runtime,
                operation=required,
            )

    module = (
        "scripts.bootstrap_postgres" if operation == "bootstrap" else "scripts.migrate_and_grant"
    )
    started = start_evidence_job(
        runner,
        retry_command,
        private_directory=directory,
        image_digest=str(ledger.image_digest),
        expected_command=("python", "-m", module),
        before_dispatch=before_dispatch,
        database_grants_only=grant_only,
    )
    if started.get("exitCode") != 0:
        raise _ProtectedStagePaused("database retry dispatch outcome is uncertain")
    _stage_record(
        directory / f"{operation}-stage-retry-start.json",
        "stage-retry-start",
        {
            "retryIntentSha256": attempt["recordSha256"],
            "startResult": started,
        },
    )
    return _finish_database_retry(
        retry_command,
        started,
        attempt,
        operation=operation,
        config=config,
        runtime=runtime,
        ledger=ledger,
        pause=pause,
        directory=directory,
        failed=failed,
        expected_manifest_hash=expected_manifest_hash,
        source_transition=source_transition,
    )


def _finish_database_retry(
    retry_command: tuple[str, ...],
    started: dict[str, object],
    attempt: dict[str, object],
    *,
    operation: str,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    pause: dict[str, object],
    directory: Path,
    failed: str,
    expected_manifest_hash: str,
    source_transition: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    job = runtime["bootstrapJobName" if operation == "bootstrap" else "migrationJobName"]
    expected_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{runtime['resourceGroupName']}"
        f"/providers/Microsoft.App/jobs/{job}/executions/{failed}"
    )
    started_value = _json_result(started)
    if (
        started.get("exitCode") != 0
        or not isinstance(started_value, dict)
        or started_value.get("name") == failed
    ):
        raise _ProtectedStagePaused("database retry did not start a distinct execution")
    deadline = _database_recovery_deadline(config, source_transition)

    class RetryReadRunner:
        def run(self, request: tuple[str, ...]) -> dict[str, object]:
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 10:
                raise _ProtectedStageExpired("database retry cleanup deadline is exhausted")
            return SubprocessRunner(
                timeout_seconds=min(15, remaining - 10),
                diagnostic_capture_directory=directory,
            ).run(request)

    waited = _wait_for_job(
        RetryReadRunner(),
        retry_command,
        started,
        deadline=deadline,
        maximum_wait_seconds=900 if operation == "bootstrap" else 1800,
    )
    execution = str(waited["executionName"])
    last = _json_result(cast(dict[str, object], waited["executionReadback"]))
    expected_retry_id = expected_id.rsplit("/", 1)[0] + "/" + execution
    validated = cast(dict[str, object], attempt["validatedJob"])
    validated_properties = cast(dict[str, object], validated["properties"])
    last_properties = last.get("properties") if isinstance(last, dict) else None
    if not isinstance(last, dict) or (
        last.get("name") != execution
        or execution == failed
        or not isinstance(last_properties, dict)
        or _retry_template_semantics(last_properties.get("template"))
        != _retry_template_semantics(validated_properties["template"])
        or str(last.get("id", "")).casefold() != expected_retry_id.casefold()
    ):
        raise _ProtectedStagePaused("database retry terminal execution identity differs")
    if not _stage_is_protected(config, runtime, ledger):
        raise _ProtectedStageExpired("database retry protection expired before admission")
    capture = _capture_failed_job_diagnostics(
        _JobExecutionFailure(
            "database retry readback",
            retry_command,
            started,
            cast(dict[str, object], waited["executionReadback"]),
            execution,
        ),
        runtime=runtime,
        deadline=deadline,
        private_directory=directory,
        purpose="recovery",
    )
    try:
        rows = json.loads((capture / "console.json").read_text(encoding="utf-8"))
        messages = [
            str(row["Log_s"])[len("M78_DATABASE_RECOVERY ") :]
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("Log_s"), str)
            and str(row["Log_s"]).startswith("M78_DATABASE_RECOVERY ")
        ]
        marker = json.loads(messages[0]) if len(messages) == 1 else None
    except (OSError, ValueError) as exc:
        raise _ProtectedStagePaused("database retry partial-state proof is unavailable") from exc
    committed_grants: dict[str, object] | None = None
    if _grant_only_transition(source_transition):
        try:
            grants = [json.loads(row["Log_s"][len("M78_RUNTIME_GRANTS "):]) for row in rows
                      if isinstance(row, dict) and isinstance(row.get("Log_s"), str)
                      and row["Log_s"].startswith("M78_RUNTIME_GRANTS ")]
        except ValueError as exc:
            raise _ProtectedStagePaused("grant-only recovery commit proof is malformed") from exc
        committed_grants = _validate_committed_grant_proof(grants[0] if len(grants) == 1 else None)
    states = (
        {"bootstrap-empty", "bootstrap-partial", "bootstrap-existing"}
        if operation == "bootstrap"
        else {"migration-empty", "migration-grants-reconcile"}
    )
    if (
        not isinstance(marker, dict)
        or set(marker)
        != {
            "version",
            "operation",
            "previousExecution",
            "campaignId",
            "generationId",
            "manifestSha256",
            "observedRevision",
            "state",
            "principalCount",
            "applicationRelationCount",
            "snapshotSha256",
            "status",
        }
        or marker.get("version") != "m7.8-database-recovery-observation-v1"
        or marker.get("operation") != operation
        or marker.get("previousExecution") != failed
        or marker.get("campaignId") != config.campaign_id
        or marker.get("generationId") != config.generation_id
        or marker.get("manifestSha256") != expected_manifest_hash
        or marker.get("observedRevision") not in {"base", "20260726_0029"}
        or (operation == "bootstrap" and marker.get("observedRevision") != "base")
        or marker.get("state") not in states
        or type(marker.get("principalCount")) is not int
        or not 0 <= marker["principalCount"] <= 4
        or type(marker.get("applicationRelationCount")) is not int
        or marker["applicationRelationCount"] < 0
        or re.fullmatch(r"[a-f0-9]{64}", str(marker.get("snapshotSha256", ""))) is None
        or marker.get("status") != "retry-preflight-passed"
    ):
        raise _ProtectedStagePaused(
            "database retry partial-state proof is mismatched or incomplete"
        )
    state, revision = marker["state"], marker["observedRevision"]
    principals, relations = marker["principalCount"], marker["applicationRelationCount"]
    if _grant_only_transition(source_transition) and (
        state != "migration-grants-reconcile" or revision != "20260726_0029"
        or principals != 4 or relations <= 0
    ):
        raise _ProtectedStagePaused("grant-only recovery did not establish the existing exact head")
    if (
        operation == "bootstrap"
        and (
            revision != "base"
            or relations != 0
            or (state == "bootstrap-empty" and principals != 0)
            or (state == "bootstrap-partial" and not 0 < principals < 4)
            or (state == "bootstrap-existing" and principals != 4)
        )
    ) or (
        operation == "migrate"
        and (
            principals != 4
            or (state == "migration-empty" and (revision != "base" or relations != 0))
            or (
                state == "migration-grants-reconcile"
                and (revision != "20260726_0029" or relations <= 0)
            )
        )
    ):
        raise _ProtectedStagePaused("database retry state observation is contradictory")
    if not _stage_is_protected(config, runtime, ledger):
        raise _ProtectedStageExpired("database retry protection expired before admission")
    _stage_record(
        directory / f"{operation}-stage-recovery-completed.json",
        "stage-recovery-completed",
        {
            "pauseSha256": pause["recordSha256"],
            "retryIntentSha256": attempt["recordSha256"],
            "sourceHead": runtime["sourceHead"],
            "resultSha256": _stage_hash("stage-result", waited),
            "marker": marker,
            **({"runtimeGrantProof": committed_grants} if committed_grants is not None else {}),
            "capture": str(capture.name),
            "captureFilesSha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in capture.iterdir()
                if path.is_file()
            },
            "completedAtUtc": datetime.now(UTC).isoformat(),
            **_source_transition_metadata(source_transition),
        },
    )
    return {**started, **waited}, attempt


def execute_commands(
    runner: CommandRunner, commands: tuple[tuple[str, ...], ...]
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for command in commands:
        result = _run_required(runner, command)
        if command[:4] == ("az", "containerapp", "job", "start"):
            result = {**result, **_wait_for_job(runner, command, result)}
        results.append(result)
    return results


def _execute_paginated_inventory(
    runner: SubprocessRunner, command: tuple[str, ...]
) -> dict[str, object]:
    if command[:3] != ("az", "rest", "--method") or "--url" not in command:
        raise CampaignError("Automation inventory command is not a REST read")
    pages = 0
    values: list[object] = []
    next_command = command
    visited: set[str] = set()
    while True:
        result = _run_required(runner, next_command)
        page = _json_result(result)
        if not isinstance(page, dict) or not isinstance(page.get("value"), list):
            raise CampaignError("Automation inventory page is malformed")
        pages += 1
        if pages > 100:
            raise CampaignError("Automation inventory pagination exceeded its bound")
        values.extend(page["value"])
        next_link = page.get("nextLink")
        if next_link in {None, ""}:
            break
        if (
            not isinstance(next_link, str)
            or not next_link.startswith("https://management.azure.com/")
            or next_link in visited
        ):
            raise CampaignError("Automation inventory pagination is unsafe")
        visited.add(next_link)
        next_command = (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            next_link,
            "--output",
            "json",
        )
    return {
        "exitCode": 0,
        "stdout": json.dumps(
            {"complete": True, "pageCount": pages, "value": values},
            separators=(",", ":"),
            sort_keys=True,
        ),
        "stderr": "",
    }


def execute_residue_commands(
    runner: SubprocessRunner, commands: tuple[tuple[str, ...], ...]
) -> list[dict[str, object]]:
    if len(commands) != 9:
        raise CampaignError("residue command sequence is incomplete")
    results = [_run_required(runner, command) for command in commands[:7]]
    results.extend(
        _execute_paginated_inventory(runner, command) for command in commands[7:]
    )
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
        or binding.get("maximumHours") != config.maximum_hours
        or binding.get("costCeilingCents") != config.cost_ceiling_cents
        or binding.get("cleanupResourceGroupName") != config.cleanup_resource_group
        or binding.get("cleanupLocation") != config.cleanup_region
        or binding.get("cleanupRegionSelectionSha256")
        != config.cleanup_region_selection_sha256
        or binding.get("cleanupCandidateRegions") != config.cleanup_candidate_regions
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
        or binding.get("freshControllerAdmissionEvidenceSha256")
        != config.fresh_controller_admission_evidence_sha256
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
        "cleanupCandidateRegions",
        "cleanupOfferClassification",
        "cleanupOfferEligibilityDisposition",
        "cleanupOfferEligibleRegions",
        "cleanupOfferEligibilitySource",
        "cleanupOfferEligibilitySha256",
        "freshControllerAdmissionEvidenceSha256",
        "cleanupDeadlineUtc",
        "cleanupAuthorityExpiresUtc",
        "automationAccountName",
        "runbookName",
        "costCeilingCents",
        "scheduleCount",
        "bindingCount",
    }
    if not required <= set(outputs) or not isinstance(
        outputs["cleanupPrincipalId"], str
    ):
        raise CampaignError("cleanup deployment binding is incomplete")
    cost_ceiling_cents = outputs["costCeilingCents"]
    schedule_count = outputs["scheduleCount"]
    binding_count = outputs["bindingCount"]
    if (
        type(cost_ceiling_cents) is not int
        or type(schedule_count) is not int
        or type(binding_count) is not int
    ):
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
        binding_count=binding_count,
        cleanup_region=str(outputs["cleanupLocation"]),
        cleanup_region_selection_sha256=str(outputs["cleanupRegionSelectionSha256"]),
        cleanup_candidate_regions=str(outputs["cleanupCandidateRegions"]),
        cleanup_offer_classification=str(outputs["cleanupOfferClassification"]),
        cleanup_offer_eligibility_disposition=str(
            outputs["cleanupOfferEligibilityDisposition"]
        ),
        cleanup_offer_eligible_regions=str(outputs["cleanupOfferEligibleRegions"]),
        cleanup_offer_eligibility_source=str(outputs["cleanupOfferEligibilitySource"]),
        cleanup_offer_eligibility_sha256=str(outputs["cleanupOfferEligibilitySha256"]),
        fresh_controller_admission_evidence_sha256=str(
            outputs["freshControllerAdmissionEvidenceSha256"]
        ),
    )
    binding.validate(config)
    if (
        outputs["cleanupAuthorityExpiresUtc"] != runtime_authority_expiry(config)
        or outputs["automationAccountName"]
        != controller_names(config.subscription_correlation).account
        or outputs["runbookName"]
        != controller_names(config.subscription_correlation).runbook
    ):
        raise CampaignError("reusable cleanup controller deployment binding differs")
    return binding


def runtime_authority_expiry(config: CampaignConfig) -> str:
    return (
        (parse_utc(config.cleanup_deadline_utc) + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_cleanup_readback(
    results: list[dict[str, object]], config: CampaignConfig, runtime: dict[str, str],
    *,
    renewal_context: tuple[dict[str, str], CampaignConfig, list[dict[str, object]]] | None = None,
) -> str:
    if len(results) != 9:
        raise CampaignError("cleanup readback is incomplete")
    from infra.milestone_7_8.campaign_deadline_renewal import origin_context, retained_tuples

    if renewal_context is None:
        foundation_runtime, foundation_config = origin_context(runtime, config)
        retained = retained_tuples(runtime)
    else:
        foundation_runtime, foundation_config, retained = renewal_context
    expected_binding, deployment_outputs, _account = validate_cleanup_foundation(
        results[:4], foundation_config, foundation_runtime
    )
    runbook = _json_result(results[4])
    content = results[5].get("stdout")
    schedule = _json_result(results[6])
    binding_response = _json_result(results[7])
    published_modified_utc = validate_published_runbook(
        runbook, content, runtime=runtime
    )
    validate_cleanup_schedule(schedule, config=config, runtime=runtime)
    validate_cleanup_bindings(
        binding_response, config=config, runtime=runtime, exact_binding=_json_result(results[8]),
        retained=retained,
    )
    proof = {
        "version": "m7.8-cleanup-arm-proof-v1",
        "deploymentName": runtime["cleanupDeploymentName"],
        "cleanupPrincipalSha256": expected_binding.cleanup_principal_sha256,
        "targetRoleAssignmentIdsSha256": _identifier_set_sha256(
            deployment_outputs["targetRoleAssignmentIds"]
        ),
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "cleanupAuthoritySha256": cleanup_authority_sha256(config, runtime),
        "publishedModifiedUtc": published_modified_utc,
        "cleanupScriptSha256": runtime["cleanupScriptSha256"],
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "scheduleNameSha256": hashlib.sha256(
            b"m7.8/schedule-name/v1\0" + runtime["scheduleName"].encode()
        ).hexdigest(),
        "bindingNameSha256": hashlib.sha256(
            b"m7.8/binding-name/v1\0" + runtime["bindingName"].encode()
        ).hexdigest(),
    }
    return hashlib.sha256(
        b"m7.8/cleanup-arm-proof/v1\0"
        + json.dumps(proof, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _identifier_set_sha256(value: object) -> str:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CampaignError("cleanup assignment identifiers are malformed")
    return hashlib.sha256(
        b"m7.8/role-assignment-set/v1\0"
        + json.dumps(
            sorted(item.casefold() for item in value), separators=(",", ":")
        ).encode()
    ).hexdigest()


def _validate_assignment_set(
    value: object,
    *,
    expected_ids: object,
    expected_role_definition_ids: object,
    principal_id: str,
    scope: str,
) -> None:
    if (
        not isinstance(value, list)
        or not isinstance(expected_ids, list)
        or not isinstance(expected_role_definition_ids, dict)
        or set(expected_role_definition_ids) != {"contributor", "rbacAdministrator"}
        or len(value) != 2
        or len(expected_ids) != 2
    ):
        raise CampaignError("cleanup role assignment readback is incomplete")
    expected_id_set = {str(item).casefold() for item in expected_ids}
    expected_role_set = {
        str(item).casefold() for item in expected_role_definition_ids.values()
    }
    observed_ids: set[str] = set()
    observed_roles: set[str] = set()
    for assignment in value:
        if not isinstance(assignment, dict):
            raise CampaignError("cleanup role assignment readback is malformed")
        assignment_id = assignment.get("id")
        role_definition_id = assignment.get("roleDefinitionId")
        observed_principal = assignment.get("principalId")
        observed_scope = assignment.get("scope")
        if not all(
            isinstance(item, str)
            for item in (
                assignment_id,
                role_definition_id,
                observed_principal,
                observed_scope,
            )
        ):
            raise CampaignError("cleanup role assignment readback is malformed")
        if (
            str(observed_principal).casefold() != principal_id.casefold()
            or str(observed_scope).rstrip("/").casefold()
            != scope.rstrip("/").casefold()
        ):
            raise CampaignError("cleanup role assignment scope or principal differs")
        observed_ids.add(str(assignment_id).casefold())
        observed_roles.add(str(role_definition_id).casefold())
    if observed_ids != expected_id_set or observed_roles != expected_role_set:
        raise CampaignError("cleanup role assignment authority differs")


def _validate_controller_tags(
    value: object, *, config: CampaignConfig, runtime: dict[str, str]
) -> None:
    if not isinstance(value, dict):
        raise CampaignError("reusable cleanup controller ownership is missing")
    expected = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": ARCHITECTURE,
        "mobius.subscription-correlation": config.subscription_correlation,
        "mobius.cleanup-script-sha256": runtime.get(
            "controllerBootstrapScriptSha256", runtime["cleanupScriptSha256"]
        ),
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise CampaignError("reusable cleanup controller ownership differs")
    authorized_until = value.get("mobius.controller-authorized-until-utc")
    if not isinstance(authorized_until, str) or parse_utc(authorized_until) < parse_utc(
        runtime["cleanupAuthorityExpiresUtc"]
    ):
        raise CampaignError("reusable cleanup controller authority is expired")


def _collection(value: object, *, label: str) -> list[object]:
    if (
        not isinstance(value, dict)
        or set(value) - {"value", "nextLink"}
        or value.get("nextLink") not in {None, ""}
        or not isinstance(value.get("value"), list)
    ):
        raise CampaignError(f"{label} collection is incomplete")
    return cast(list[object], value["value"])


def _validate_controller_reader(
    value: object,
    *,
    principal_id: str,
    config: CampaignConfig,
    runtime: dict[str, str],
) -> None:
    if not isinstance(value, list):
        raise CampaignError("reusable cleanup controller Reader proof is malformed")
    principal_assignments = [
        item
        for item in value
        if isinstance(item, dict)
        and str(item.get("principalId", "")).casefold() == principal_id.casefold()
    ]
    expected_scope = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.cleanup_resource_group}"
    )
    if (
        len(principal_assignments) != 1
        or str(principal_assignments[0].get("scope", "")).casefold()
        != expected_scope.casefold()
        or not str(principal_assignments[0].get("roleDefinitionId", ""))
        .casefold()
        .endswith("acdd72a7-3385-48ef-bd42-f606fba81ae7")
    ):
        raise CampaignError("reusable cleanup controller permanent Reader differs")


def validate_controller_baseline(
    results: list[dict[str, object]], config: CampaignConfig, runtime: dict[str, str]
) -> None:
    if len(results) != 7:
        raise CampaignError("reusable cleanup controller preflight is incomplete")
    group = _json_result(results[0])
    account = _json_result(results[1])
    assignments = _json_result(results[2])
    runbook = _json_result(results[3])
    content = results[4].get("stdout")
    schedules = _collection(_json_result(results[5]), label="cleanup schedule")
    bindings = _collection(_json_result(results[6]), label="cleanup binding")
    validate_controller_deadline_consistency(
        group, account, runbook,
        names=controller_names(config.subscription_correlation),
        expected_deadline=runtime["controllerAuthorizedUntilUtc"],
    )
    if (
        not isinstance(group, dict)
        or group.get("name") != config.cleanup_resource_group
        or not isinstance(account, dict)
        or account.get("name") != runtime["automationAccountName"]
        or _normalized_region(group.get("location")) != config.cleanup_region
        or _normalized_region(account.get("location")) != config.cleanup_region
        or schedules
        or bindings
    ):
        raise CampaignError("reusable cleanup controller is not exclusively adoptable")
    _validate_controller_tags(group.get("tags"), config=config, runtime=runtime)
    _validate_controller_tags(account.get("tags"), config=config, runtime=runtime)
    identity = account.get("identity")
    if (
        not isinstance(identity, dict)
        or not isinstance(identity.get("principalId"), str)
        or not controller_local_auth_disabled(account)
    ):
        raise CampaignError(
            "reusable cleanup controller identity or local-auth policy differs"
        )
    _validate_controller_reader(
        assignments,
        principal_id=str(identity["principalId"]),
        config=config,
        runtime=runtime,
    )
    validate_published_runbook(runbook, content, runtime=runtime)


def execute_cleanup_deploy_commands(
    runner: SubprocessRunner,
    commands: tuple[tuple[str, ...], ...],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> list[dict[str, object]]:
    if len(commands) != 8:
        raise CampaignError(
            "reusable cleanup controller deployment sequence is incomplete"
        )
    results = [_run_required(runner, command) for command in commands[:7]]
    validate_controller_baseline(results, config, runtime)
    results.append(_run_required(runner, commands[7]))
    return results


def validate_cleanup_foundation(
    results: list[dict[str, object]],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> tuple[CleanupBinding, dict[str, object], dict[str, object]]:
    if len(results) != 4:
        raise CampaignError("cleanup deployment and authority proof is incomplete")
    expected_binding = validate_cleanup_deployment(results[0], config)
    outputs = _deployment_outputs(results[0])
    account = _json_result(results[1])
    target_assignments = _json_result(results[2])
    controller_assignments = _json_result(results[3])
    if not isinstance(account, dict):
        raise CampaignError("cleanup identity readback is malformed")
    identity = account.get("identity")
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
    account_location = account.get("location")
    normalized_account_location = (
        re.sub(r"[^a-z0-9]", "", account_location.casefold())
        if isinstance(account_location, str)
        else None
    )
    if normalized_account_location != config.cleanup_region:
        raise CampaignError("cleanup account region readback was substituted")
    if account.get("name") != runtime["automationAccountName"]:
        raise CampaignError("cleanup account identity readback was substituted")
    _validate_controller_tags(account.get("tags"), config=config, runtime=runtime)
    _validate_controller_reader(
        controller_assignments,
        principal_id=observed_principal,
        config=config,
        runtime=runtime,
    )
    if (
        outputs.get("scheduleName") != runtime["scheduleName"]
        or outputs.get("bindingName") != runtime["bindingName"]
    ):
        raise CampaignError("cleanup schedule or binding identity differs")
    role_definitions = outputs.get("cleanupRoleDefinitionIds")
    target_scope = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.target_resource_group}"
    )
    _validate_assignment_set(
        target_assignments,
        expected_ids=outputs.get("targetRoleAssignmentIds"),
        expected_role_definition_ids=role_definitions,
        principal_id=observed_principal,
        scope=target_scope,
    )
    return expected_binding, outputs, account


def validate_published_runbook(
    runbook: object, content: object, *, runtime: dict[str, str]
) -> str:
    if not isinstance(runbook, dict) or runbook.get("name") != runtime["runbookName"]:
        raise CampaignError("published runbook identity differs")
    properties = runbook.get("properties", runbook)
    if not isinstance(properties, dict) or properties.get("state") != "Published":
        raise CampaignError("cleanup runbook is not published")
    modified = properties.get("lastModifiedTime")
    if not isinstance(modified, str):
        raise CampaignError("cleanup runbook publication evidence is stale or missing")
    published_modified_utc = parse_utc(modified).isoformat().replace("+00:00", "Z")
    if (
        not isinstance(content, str)
        or hashlib.sha256(content.encode()).hexdigest()
        != runtime["cleanupScriptSha256"]
    ):
        raise CampaignError("published cleanup content differs")
    return published_modified_utc


def validate_cleanup_schedule(
    schedule: object, *, config: CampaignConfig, runtime: dict[str, str]
) -> None:
    if (
        not isinstance(schedule, dict)
        or schedule.get("name") != runtime["scheduleName"]
    ):
        raise CampaignError("cleanup schedule identity differs")
    properties = schedule.get("properties", schedule)
    if not isinstance(properties, dict):
        raise CampaignError("cleanup schedule readback drifted: properties")
    mismatches = []
    if properties.get("frequency") != "OneTime":
        mismatches.append("frequency")
    if properties.get("timeZone") != "Etc/UTC":
        mismatches.append("timeZone")
    if properties.get("isEnabled") is not True:
        mismatches.append("isEnabled")
    interval = properties.get("interval")
    if "interval" not in properties or not (
        interval is None or (type(interval) is int and interval == 1)
    ):
        mismatches.append("interval")
    start_time = properties.get("startTime")
    try:
        start_matches = isinstance(start_time, str) and parse_utc(start_time) == parse_utc(
            config.cleanup_deadline_utc
        )
    except CampaignError:
        start_matches = False
    if not start_matches:
        mismatches.append("startTime")
    if mismatches:
        raise CampaignError("cleanup schedule readback drifted: " + ", ".join(mismatches))


def validate_cleanup_bindings(
    response: object,
    *,
    config: CampaignConfig,
    runtime: dict[str, str],
    exact_binding: object | None = None,
    retained: list[dict[str, object]] | None = None,
) -> None:
    if not isinstance(response, dict) or set(response) - {"value", "nextLink"}:
        raise CampaignError("cleanup binding collection is malformed")
    bindings = response.get("value")
    if response.get("nextLink") not in {None, ""} or not isinstance(bindings, list):
        raise CampaignError("cleanup binding collection is incomplete")
    if retained is None:
        from infra.milestone_7_8.campaign_deadline_renewal import retained_tuples

        retained = retained_tuples(runtime)
    for previous in retained:
        matches = [item for item in bindings if isinstance(item, dict)
                   and str(item.get("id", "")).casefold() == str(previous["bindingId"]).casefold()]
        if len(matches) != 1:
            raise CampaignError("retained cleanup binding inventory differs")
        previous_binding = matches[0]
        properties = previous_binding.get("properties", {})
        parameters = properties.get("parameters")
        if (
            properties.get("jobScheduleId") != previous["bindingName"]
            or properties.get("schedule") != {"name": previous["scheduleName"]}
            or properties.get("runbook") != {"name": runtime["runbookName"]}
            or (parameters is not None and parameters != previous["parameters"])
            or properties.get("runOn") not in (None, "")
        ):
            raise CampaignError("retained cleanup binding was substituted")
        bindings = [item for item in bindings if item is not previous_binding]
    binding = bindings[0] if len(bindings) == 1 else None
    if not isinstance(binding, dict):
        raise CampaignError("exactly one expected cleanup binding is required")
    binding_properties = binding.get("properties", binding)
    expected_name = runtime["bindingName"].casefold()
    expected_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.cleanup_resource_group}"
        f"/providers/Microsoft.Automation/automationAccounts/{runtime['automationAccountName']}"
        f"/jobSchedules/{runtime['bindingName']}"
    )
    name = binding.get("name")
    resource_id = binding.get("id")
    job_schedule_id = (
        binding_properties.get("jobScheduleId") if isinstance(binding_properties, dict) else None
    )
    if (
        (name is not None and (not isinstance(name, str) or name.casefold() != expected_name))
        or (
            resource_id is not None
            and (
                not isinstance(resource_id, str)
                or resource_id.casefold() != expected_id.casefold()
            )
        )
        or (
            job_schedule_id is not None
            and (
                not isinstance(job_schedule_id, str)
                or job_schedule_id.casefold() != expected_name
            )
        )
        or (name is None and (resource_id is None or job_schedule_id is None))
    ):
        raise CampaignError("exactly one expected cleanup binding is required")
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
    parameters = (
        binding_properties.get("parameters") if isinstance(binding_properties, dict) else None
    )
    if (
        bound_runbook_name != runtime["runbookName"]
        or bound_schedule_name != runtime["scheduleName"]
        or not isinstance(binding_properties, dict)
        or (parameters is None and exact_binding is None)
        or (parameters is not None and parameters != cleanup_job_parameters(config, runtime))
    ):
        raise CampaignError("cleanup binding readback drifted")
    if exact_binding is not None:
        validate_cleanup_bindings(
            {"value": [exact_binding]}, config=config, runtime=runtime, retained=[]
        )


def execute_cleanup_arm_commands(
    runner: SubprocessRunner,
    commands: tuple[tuple[str, ...], ...],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> tuple[list[dict[str, object]], str]:
    if len(commands) != 13:
        raise CampaignError("cleanup arming command sequence is incomplete")
    results = [_run_required(runner, command) for command in commands[:8]]
    validate_cleanup_foundation(results[:4], config, runtime)
    validate_published_runbook(
        _json_result(results[4]), results[5].get("stdout"), runtime=runtime
    )
    existing_schedules = _collection(_json_result(results[6]), label="cleanup schedule")
    existing_bindings = _collection(_json_result(results[7]), label="cleanup binding")
    if len(existing_schedules) > 1 or len(existing_bindings) > 1:
        raise CampaignError("another live cleanup schedule or binding exists")
    existing_schedule = existing_schedules[0] if existing_schedules else None
    if existing_schedule is not None:
        validate_cleanup_schedule(existing_schedule, config=config, runtime=runtime)
    if existing_bindings:
        if existing_schedule is None:
            raise CampaignError("cleanup binding exists without its exact schedule")
        schedule_result = {
            "exitCode": 0,
            "stdout": json.dumps(existing_schedule),
            "stderr": "",
        }
        binding_result = {
            "exitCode": 0,
            "stdout": json.dumps({"value": existing_bindings}),
            "stderr": "",
        }
    else:
        if existing_schedule is None:
            results.append(_run_required(runner, commands[8]))
            schedule_result = _run_required(runner, commands[9])
            results.append(schedule_result)
        else:
            schedule_result = {
                "exitCode": 0,
                "stdout": json.dumps(existing_schedule),
                "stderr": "",
            }
        validate_cleanup_schedule(
            _json_result(schedule_result), config=config, runtime=runtime
        )
        results.append(_run_required(runner, commands[10]))
        binding_result = _run_required(runner, commands[11])
        results.append(binding_result)
    detail_result = _run_required(runner, commands[12])
    results.append(detail_result)
    proof_results = [
        *results[:4],
        results[4],
        results[5],
        schedule_result,
        binding_result,
        detail_result,
    ]
    return results, validate_cleanup_readback(proof_results, config, runtime)


def execute_cleanup_disarm_commands(
    runner: SubprocessRunner,
    commands: tuple[tuple[str, ...], ...],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> tuple[list[dict[str, object]], str]:
    from infra.milestone_7_8.campaign_deadline_renewal import retained_tuples

    expected = 4 + 2 * len(retained_tuples(runtime))
    if len(commands) != expected:
        raise CampaignError("cleanup disarming command sequence is incomplete")
    results = [runner.run(command) for command in commands[:-2]]
    results.extend(_run_required(runner, command) for command in commands[-2:])
    return results, validate_disarm_readback(results[-2:], config, runtime)


def validate_disarm_readback(
    results: list[dict[str, object]], config: CampaignConfig, runtime: dict[str, str]
) -> str:
    """Validate the same complete disarm proof without dispatching any mutation."""
    if len(results) != 2 or any(result.get("exitCode") != 0 for result in results):
        raise CampaignError("cleanup disarming readback is incomplete")
    schedules = _collection(_json_result(results[0]), label="cleanup schedule")
    bindings = _collection(_json_result(results[1]), label="cleanup binding")
    if schedules or bindings:
        raise CampaignError("cleanup schedule or binding revocation failed")
    evidence = {
        "version": "m7.8-cleanup-disarm-proof-v1",
        "campaignCorrelation": sanitize(config.campaign_id, domain="campaign"),
        "generationCorrelation": sanitize(config.generation_id, domain="generation"),
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "scheduleNameSha256": hashlib.sha256(
            runtime["scheduleName"].encode()
        ).hexdigest(),
        "bindingNameSha256": hashlib.sha256(
            runtime["bindingName"].encode()
        ).hexdigest(),
        "scheduleCount": 0,
        "bindingCount": 0,
    }
    evidence_sha256 = hashlib.sha256(
        b"m7.8/cleanup-disarm-proof/v1\0"
        + json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return evidence_sha256


def load_control_plane_evidence(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) - {
        "observedPeak", "latencyP95Ms",
    } != CONTROL_PLANE_FIELDS:
        raise CampaignError("control-plane evidence is incomplete")
    # Older inputs can still be loaded, but only the live sampler supplies these metrics.
    value = {key: item for key, item in value.items() if key in CONTROL_PLANE_FIELDS}
    capacity_fields = (
        "azureReservedConnections", "poolCeilings", "rolloutOverlap", "operatorConsumers",
        "safetyReserve", "maxConnections",
    )
    if any(type(value[field]) is not int for field in capacity_fields):
        raise CampaignError("connection capacity evidence is malformed")
    reserved, pools, overlap, operators, safety, maximum = (
        cast(int, value[field]) for field in capacity_fields
    )
    if reserved < 0 or pools <= 0 or overlap <= 0 or operators <= 0:
        raise CampaignError("connection capacity evidence is invalid")
    if safety < 20:
        raise CampaignError("connection safety reserve is below the approved minimum of 20")
    committed = reserved + pools + overlap + operators + safety
    if committed >= maximum:
        raise CampaignError(f"connection budget shortfall: {committed - maximum + 1}")
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
    *,
    private_directory: Path,
    image_digest: str,
    runtime: dict[str, str],
    worker_execution: str,
    deadline: datetime,
    authorize: Callable[[], None],
) -> list[dict[str, object]]:
    if len(commands) != 12:
        raise CampaignError("managed evidence command sequence is incomplete")
    output = private_directory / "managed-assertion-captures"
    console = EvidenceConsole(
        runner, runtime, image_digest=image_digest, directory=output,
        deadline=deadline, authorize=authorize,
    )
    results: list[dict[str, object]] = []
    captures: list[dict[str, object]] = []
    phases = {0: "api", 1: "worker", 2: "catalog", 3: "application", 4: "migration",
              5: "revoke", 6: "credential-denied", 7: "restore", 8: "api",
              10: "failover-window", 11: "operations"}
    revoke_requested, restore_requested = False, False
    dispatch_times: dict[int, datetime] = {}

    def guard() -> None:
        if datetime.now(UTC) >= deadline:
            raise _ProtectedStageExpired("managed evidence cleanup deadline expired")
        authorize()

    def prepare_job(index: int, *, payload: str | None = None) -> tuple[tuple[str, ...], str]:
        nonlocal revoke_requested, restore_requested
        command = list(commands[index])
        if payload is not None:
            env_index = command.index("--env-vars") + 1
            command[env_index] = "M78_CONTROL_PLANE_EVIDENCE=" + payload
        token = uuid.uuid4().hex
        extra = ["M78_EVIDENCE_TOKEN=" + token]
        if index == 10:
            extra.append("M78_FAILOVER_WORKER_EXECUTION=" + worker_execution)
        if "--env-vars" in command:
            env_index = command.index("--env-vars") + 1
            command[env_index:env_index] = extra
        else:
            command.extend(("--env-vars", *extra))
        _durable_record(output / f"job-{index:02d}-intent.json", {
            "command": command, "phase": phases[index], "token": token,
            "sourceHead": runtime["sourceHead"], "imageDigest": image_digest,
            "requestedAtUtc": datetime.now(UTC).isoformat(),
        })
        if index == 5:
            revoke_requested = True
        if index == 7:
            restore_requested = True
        return tuple(command), token

    def start(index: int, *, payload: str | None = None) -> tuple[
        tuple[str, ...], str, dict[str, object],
    ]:
        command, token = prepare_job(index, payload=payload)
        guard()
        def before_dispatch(resource: dict[str, object]) -> None:
            properties = resource.get("properties")
            template = properties.get("template") if isinstance(properties, dict) else None
            containers = template.get("containers") if isinstance(template, dict) else None
            if (not isinstance(containers, list) or len(containers) != 1
                    or not isinstance(containers[0], dict)):
                raise CampaignError("managed evidence job container scope differs")
            validate_probe_container(
                containers[0], phase=phases[index], image_digest=image_digest, token=token,
            )
            guard()
            dispatched = datetime.now(UTC)
            _durable_record(output / f"job-{index:02d}-dispatch.json", {
                "command": command, "phase": phases[index], "token": token,
                "dispatchedAtUtc": dispatched.isoformat(),
            })
            guard()
            dispatch_times[index] = dispatched

        started = start_evidence_job(
            runner, command, private_directory=private_directory, image_digest=image_digest,
            before_dispatch=before_dispatch,
        )
        _durable_record(output / f"job-{index:02d}-start.json", started)
        if started.get("exitCode") != 0:
            raise CampaignError("managed evidence job start failed")
        return command, token, started

    def finish(index: int, command: tuple[str, ...], token: str,
               started: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
        waited = _wait_for_job(runner, command, started, deadline=deadline)
        guard()
        result = {**started, **waited}
        _durable_record(output / f"job-{index:02d}-terminal.json", result)
        capture = console.capture(
            command[command.index("--name") + 1], str(waited["executionName"]),
            token, phases[index],
            dispatched_at=dispatch_times[index],
        )
        return result, capture

    try:
        for index in range(9):
            command, token, started = start(index)
            result, capture = finish(index, command, token, started)
            results.append(result)
            captures.append(capture)
        # The probe must observe live API/worker state before the one restart.
        command, token, started = start(10)
        initial = _json_result(started)
        if not isinstance(initial, dict) or not isinstance(initial.get("name"), str):
            raise CampaignError("managed failover probe execution identity is missing")
        ready = console.capture(
            runtime["migrationProbeJobName"], str(initial["name"]), token, "failover-window",
            dispatched_at=dispatch_times[10], ready=True,
        )
        ready_payload = cast(dict[str, object], ready["payload"])
        if ready_payload.get("workerExecution") != worker_execution:
            raise CampaignError("failover ready marker names another worker execution")
        worker_before = collect_worker_replicas(
            console, subscription=runtime["subscriptionId"], group=runtime["resourceGroupName"],
            job=runtime["workerJobName"], execution=worker_execution,
        )
        validate_worker_capture(worker_before, runtime, worker_execution)
        probe_path = (
            f"/subscriptions/{runtime['subscriptionId']}"
            f"/resourceGroups/{runtime['resourceGroupName']}"
            f"/providers/Microsoft.App/jobs/{runtime['migrationProbeJobName']}"
            f"/executions/{initial['name']}"
        )
        probe_readback = console.run((
            "az", "rest", "--method", "get", "--url",
            "https://management.azure.com" + probe_path + "?api-version=2024-03-01",
            "--subscription", runtime["subscriptionId"], "--output", "json",
        ))
        probe_observed = datetime.now(UTC).isoformat()
        validate_ready_readback(ready, probe_readback, probe_observed, runtime, image_digest)
        guard()
        restart: dict[str, object] = {
            "command": commands[9], "dispatchedAtUtc": datetime.now(UTC).isoformat(),
            "probeReadback": probe_readback, "probeObservedAtUtc": probe_observed,
        }
        _durable_record(output / "forced-failover-intent.json", restart)
        guard()
        restart["dispatchedAtUtc"] = datetime.now(UTC).isoformat()
        _durable_record(output / "forced-failover-dispatch.json", restart)
        guard()
        restarted = runner.run(commands[9])
        restart.update(result=restarted, completedAtUtc=datetime.now(UTC).isoformat())
        _durable_record(output / "forced-failover-result.json", restart)
        if restarted.get("exitCode") != 0:
            raise CampaignError("forced managed failover failed")
        result, capture = finish(10, command, token, started)
        worker_after = collect_worker_replicas(
            console, subscription=runtime["subscriptionId"], group=runtime["resourceGroupName"],
            job=runtime["workerJobName"], execution=worker_execution,
        )
        validate_worker_capture(worker_after, runtime, worker_execution)
        recovery_seconds = validate_failover(
            cast(dict[str, object], ready["payload"]), cast(dict[str, object], capture["payload"]),
            restart, worker_execution=worker_execution,
        )
        results.extend((restarted, result))
        captures.append(capture)
        payload = _completed_control_plane_evidence(
            control_plane_evidence, recovery_seconds=recovery_seconds,
        )
        command, token, started = start(11, payload=payload)
        result, capture = finish(11, command, token, started)
        results.append(result)
        captures.append(capture)
        proof: dict[str, object] = {
            "version": "m7.8-managed-assertion-evidence-v1", "sourceHead": runtime["sourceHead"],
            "imageDigest": image_digest, "workerExecution": worker_execution,
            "control": control_plane_evidence, "captures": captures, "ready": ready,
            "restart": restart, "workerBefore": worker_before, "workerAfter": worker_after,
        }
        proof["evidenceSha256"] = evidence_hash(proof)
        validate_proofs(proof, runtime, image_digest=image_digest,
                        control=control_plane_evidence, worker_execution=worker_execution)
        _durable_record(private_directory / "managed-assertion-evidence.json", proof)
        return results
    except Exception:
        # Revocation and restoration are distinct approved operations. A failed
        # denial observation must not strand the API in NOLOGIN while protected.
        if revoke_requested and not restore_requested:
            try:
                command, token, started = start(7)
                finish(7, command, token, started)
            except Exception as restoration_error:
                # Preserve the original phase failure even if diagnostics cannot persist.
                with contextlib.suppress(Exception):
                    _durable_record(output / "credential-restoration-failed.json", {
                        "errorClass": type(restoration_error).__name__,
                        "observedAtUtc": datetime.now(UTC).isoformat(),
                    })
        raise


def persist_evidence_execution_receipt(
    path: Path,
    *,
    config: CampaignConfig,
    runtime: dict[str, str],
    commands: tuple[tuple[str, ...], ...],
    results: list[dict[str, object]],
    control_plane_evidence: dict[str, object],
    measurement: dict[str, object],
) -> None:
    measurement = validate_measurement_receipt(measurement, control_plane_evidence)
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
            phase_option = next(
                (part for part in command if part.startswith("--args=--phase=")), None
            )
            if phase_option is not None:
                identity += ":" + phase_option.removeprefix("--args=--phase=")
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
    proof_path = path.with_name("managed-assertion-evidence.json")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    if not isinstance(proof, dict) or config.image_digest is None:
        raise CampaignError("managed assertion evidence is absent")
    validate_proofs(
        proof, runtime, image_digest=config.image_digest,
        control={**control_plane_evidence, "observedPeak": measurement["observedPeak"],
                 "latencyP95Ms": measurement["latencyP95Ms"]},
        worker_execution=str(measurement["workerExecution"]),
    )
    for capture, observation in zip(
        proof["captures"], [item for i, item in enumerate(observations) if i != 9], strict=True,
    ):
        if (capture["execution"] != observation["executionName"]
                or observation["identity"].split(":")[1] != capture["job"]):
            raise CampaignError("assertion evidence belongs to another probe execution")
    receipt = {
        "version": "m7.8-managed-evidence-execution-v3",
        "assertionEvidenceSha256": proof["evidenceSha256"],
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "sourceHead": runtime["sourceHead"],
        "imageDigest": config.image_digest,
        "controlPlaneEvidenceSha256": hashlib.sha256(
            json.dumps(
                control_plane_evidence, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest(),
        "measurement": measurement,
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
    allow_historical: bool = False,
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    observations = value.get("observations") if isinstance(value, dict) else None
    historical = (
        isinstance(value, dict) and value.get("version") == "m7.8-managed-evidence-execution-v2"
    )
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
            "measurement",
            "observations",
        } | (set() if historical else {"assertionEvidenceSha256"})
        or (historical and not allow_historical)
        or value["version"] not in {
            "m7.8-managed-evidence-execution-v2", "m7.8-managed-evidence-execution-v3",
        }
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
    measurement = validate_measurement_receipt(value["measurement"], control_plane_evidence)
    if historical:
        return  # Explicit audit only; normal live admission never sets this flag.
    if config.image_digest is None:
        raise CampaignError("managed evidence admitted image is absent")
    proof_path = path.with_name("managed-assertion-evidence.json")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    if (not isinstance(proof, dict)
            or proof.get("evidenceSha256") != value["assertionEvidenceSha256"]):
        raise CampaignError("managed assertion evidence differs from the phase receipt")
    validate_proofs(
        proof, runtime, image_digest=config.image_digest,
        control={**control_plane_evidence, "observedPeak": measurement["observedPeak"],
                 "latencyP95Ms": measurement["latencyP95Ms"]},
        worker_execution=str(measurement["workerExecution"]),
    )
    for capture, observation in zip(
        proof["captures"], [item for i, item in enumerate(observations) if i != 9], strict=True,
    ):
        if (capture["execution"] != observation["executionName"]
                or observation["identity"].split(":")[1] != capture["job"]):
            raise CampaignError("managed assertion receipt execution differs")


def _reconcile_evidence_stage_completion(
    directory: Path,
    config: CampaignConfig,
    runtime: dict[str, str],
    ledger: Ledger,
    control_plane_evidence: dict[str, object] | None = None,
) -> None:
    """Reconcile only an already validated evidence receipt, never dispatch work."""
    completion_path = directory / "evidence-stage-recovery-completed.json"
    existing = (
        _read_stage_record(completion_path, "stage-recovery-completed")
        if completion_path.exists() else None
    )
    if control_plane_evidence is None:
        if existing is None or not isinstance(existing.get("controlPlaneEvidence"), dict):
            raise _ProtectedStagePaused("managed evidence completion control input is missing")
        control_plane_evidence = cast(dict[str, object], existing["controlPlaneEvidence"])
    config = replace(config, image_digest=ledger.image_digest)
    receipt = directory / "managed-evidence-execution.json"
    validate_evidence_execution_receipt(
        receipt, config=config, runtime=runtime, control_plane_evidence=control_plane_evidence,
    )
    attempt_path = directory / "evidence-stage-attempt.json"
    pause_path = directory / "evidence-stage-pause.json"
    readiness_replacement = (
        ledger.image_replacement is not None
        and ledger.image_replacement.get("replacementPhase") == Phase.MIGRATED.value
    )
    if readiness_replacement and (not attempt_path.exists() or not pause_path.exists()):
        raise _ProtectedStagePaused("corrected image completion requires its original history")
    if not attempt_path.exists() and not pause_path.exists() and existing is None:
        # Historical receipt-only recovery predates durable protected-stage records.
        return
    expected_bindings = _stage_bindings(
        config, runtime, replace(ledger, phase=Phase.MIGRATED.value),
    )
    image_origin = None
    if readiness_replacement:
        # A corrected image preserves its failed measurement or acceptance attempt.
        # Validate its explicit admission link before accepting the old bindings.
        from infra.milestone_7_8 import image_continuation

        image_origin = image_continuation.validate_readiness_evidence_origin(
            directory, config, runtime, ledger,
        )
    attempt_bindings = (
        image_origin["originalBindings"] if image_origin is not None else expected_bindings
    )
    attempt = _read_stage_record(attempt_path, "stage-attempt")
    commands = tuple(
        (*command, "--subscription", runtime["subscriptionId"])
        for command in command_plan(
            "evidence", config, runtime,
            control_plane_evidence="<derived-after-successful-managed-probes>",
        )
    )
    if (
        set(attempt) != {
            "version", "operation", "bindings", "commandSha256", "authorizationSha256",
            "startedAtUtc", "recordSha256",
        }
        or attempt["version"] != "m7.8-protected-stage-attempt-v1"
        or attempt["operation"] != "evidence"
        or attempt["bindings"] != attempt_bindings
        or attempt["commandSha256"] != (
            image_origin["originalCommandSha256"] if image_origin is not None
            else _stage_hash("stage-command", commands)
        )
        or (image_origin is not None
            and attempt["recordSha256"] != image_origin["originalAttemptSha256"])
        or re.fullmatch(r"[a-f0-9]{64}", str(attempt["authorizationSha256"])) is None
        or ORDER.index(Phase(ledger.phase)) < ORDER.index(Phase.MIGRATED)
    ):
        raise _ProtectedStagePaused("managed evidence original attempt binding differs")
    parse_utc(str(attempt["startedAtUtc"]))
    pause = _read_stage_record(pause_path, "stage-pause") if pause_path.exists() else None
    if pause is not None and (
        set(pause) != {
            "version", "operation", "bindings", "attemptSha256", "authorizationSha256",
            "failedExecution", "failedAtUtc", "recoveryUntilUtc", "maximumRetryDispatches",
            "recordSha256",
        }
        or pause["version"] != "m7.8-protected-stage-pause-v1"
        or pause["operation"] != "evidence"
        or pause["bindings"] not in (
            attempt_bindings, {**attempt_bindings, "ledgerPhase": Phase.EVIDENCE_EXECUTED.value},
        )
        or (image_origin is not None
            and pause["recordSha256"] != image_origin["originalPauseSha256"])
        or pause["attemptSha256"] != attempt["recordSha256"]
        or pause["authorizationSha256"] != attempt["authorizationSha256"]
        or pause["failedExecution"] != (
            image_origin.get("originalFailedExecution") if image_origin is not None else None
        )
        or pause["maximumRetryDispatches"] != 1
    ):
        raise _ProtectedStagePaused("managed evidence completion pause binding differs")
    if image_origin is not None and pause is None:
        raise _ProtectedStagePaused("corrected image completion requires its original pause")
    completed: dict[str, object] = {
        "version": "m7.8-managed-evidence-completion-reconciliation-v1",
        "bindings": expected_bindings,
        "attemptSha256": attempt["recordSha256"],
        "pauseSha256": pause["recordSha256"] if pause is not None else None,
        "receiptSha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "controlPlaneEvidence": control_plane_evidence,
    }
    if image_origin is not None:
        completed["imageContinuationSha256"] = image_origin["continuationSha256"]
    if existing is not None:
        if existing != {**completed, "recordSha256": _stage_hash(
            "stage-recovery-completed", completed,
        )}:
            raise _ProtectedStagePaused("managed evidence completion history differs")
    else:
        _stage_record(completion_path, "stage-recovery-completed", completed)


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


@dataclass(frozen=True, slots=True)
class ResidueObservation:
    counters: dict[str, int]
    evidence_sha256: str
    active_inventory_pages: int
    deleted_inventory_pages: int
    unrelated_deleted_identity_sha256: tuple[str, ...]


def _ci_get(value: dict[str, object], name: str) -> object:
    expected = name.casefold()
    for key, item in value.items():
        if key.casefold() == expected:
            return item
    return None


def _normalized_region(value: object) -> str | None:
    return (
        re.sub(r"[^a-z0-9]", "", value.casefold()) if isinstance(value, str) else None
    )


def _account_record(value: object, *, deleted: bool) -> tuple[str, str, str]:
    if not isinstance(value, dict):
        raise CampaignError("Automation inventory record is malformed")
    name = _ci_get(value, "name")
    location = _ci_get(value, "location")
    properties = _ci_get(value, "properties")
    resource_id = (
        _ci_get(properties, "automationAccountResourceId")
        if deleted and isinstance(properties, dict)
        else _ci_get(value, "id")
    )
    if (
        not isinstance(name, str)
        or not name
        or _normalized_region(location) is None
        or not isinstance(resource_id, str)
        or not resource_id.startswith("/")
    ):
        raise CampaignError("Automation inventory attribution is malformed")
    return name, str(_normalized_region(location)), resource_id.casefold()


def _complete_inventory(result: dict[str, object]) -> tuple[list[object], int]:
    value = _json_result(result)
    if (
        not isinstance(value, dict)
        or value.get("complete") is not True
        or type(value.get("pageCount")) is not int
        or int(value["pageCount"]) < 1
        or not isinstance(value.get("value"), list)
    ):
        raise CampaignError("Automation inventory is not completely paginated")
    return value["value"], int(value["pageCount"])


def observe_residue(
    results: list[dict[str, object]],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> ResidueObservation:
    if len(results) != 9:
        raise CampaignError("residue readback is incomplete")
    target_exists = _json_result(results[0])
    resources = _json_result(results[1])
    assignments = _json_result(results[2])
    controller_group = _json_result(results[3])
    controller_account = _json_result(results[4])
    schedules = _collection(_json_result(results[5]), label="cleanup schedule")
    bindings = _collection(_json_result(results[6]), label="cleanup binding")
    active, active_pages = _complete_inventory(results[7])
    deleted, deleted_pages = _complete_inventory(results[8])
    if (
        not isinstance(target_exists, bool)
        or not isinstance(resources, list)
        or not isinstance(assignments, list)
        or not isinstance(controller_group, dict)
        or controller_group.get("name") != config.cleanup_resource_group
        or not isinstance(controller_account, dict)
        or controller_account.get("name") != runtime["automationAccountName"]
    ):
        raise CampaignError("campaign residue readback is malformed")
    _validate_controller_tags(
        controller_group.get("tags"), config=config, runtime=runtime
    )
    _validate_controller_tags(
        controller_account.get("tags"), config=config, runtime=runtime
    )
    expected_name = runtime["automationAccountName"].casefold()
    expected_region = config.cleanup_region
    expected_resource_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
        f"automationAccounts/{runtime['automationAccountName']}"
    ).casefold()

    active_matches = 0
    for item in active:
        name, region, resource_id = _account_record(item, deleted=False)
        if resource_id == expected_resource_id:
            if name.casefold() != expected_name or region != expected_region:
                raise CampaignError(
                    "reusable Automation controller attribution differs"
                )
            active_matches += 1
        elif name.casefold() == expected_name and region == expected_region:
            raise CampaignError(
                "reusable Automation controller attribution is ambiguous"
            )
    deleted_matches = 0
    unrelated_hashes: list[str] = []
    for item in deleted:
        name, region, resource_id = _account_record(item, deleted=True)
        if resource_id == expected_resource_id:
            if name.casefold() != expected_name or region != expected_region:
                raise CampaignError("deleted reusable controller attribution differs")
            deleted_matches += 1
        else:
            if name.casefold() == expected_name and region == expected_region:
                raise CampaignError(
                    "deleted Automation campaign attribution is ambiguous"
                )
            unrelated_hashes.append(
                hashlib.sha256(
                    b"m7.8/unrelated-deleted-automation-account/v1\0"
                    + resource_id.encode()
                ).hexdigest()
            )
    if active_matches != 1 or deleted_matches:
        raise CampaignError("reusable cleanup controller was not retained exactly once")
    counters = dict.fromkeys(RESIDUE_KEYS, 0)
    counters["targetResourceGroups"] = int(target_exists)
    counters["roleAssignments"] = len(assignments)
    counters["cleanupSchedules"] = len(schedules) + len(bindings)
    tagged_types = {
        str(item.get("type", "")).casefold()
        for item in resources
        if isinstance(item, dict)
    }
    if len(tagged_types) != len(resources):
        raise CampaignError("tagged resource residue is malformed")
    resource_key_types = {
        "managedIdentities": "microsoft.managedidentity/userassignedidentities",
        "postgresServers": "microsoft.dbforpostgresql/flexibleservers",
        "containerRegistries": "microsoft.containerregistry/registries",
        "containerAppsEnvironments": "microsoft.app/managedenvironments",
        "containerAppsJobs": "microsoft.app/jobs",
        "virtualNetworks": "microsoft.network/virtualnetworks",
        "privateEndpoints": "microsoft.network/privateendpoints",
        "privateDnsZones": "microsoft.network/privatednszones",
        "diagnosticSettings": "microsoft.insights/diagnosticsettings",
    }
    for key, resource_type in resource_key_types.items():
        counters[key] = sum(
            1
            for item in resources
            if isinstance(item, dict)
            and str(item.get("type", "")).casefold() == resource_type
        )
    known_resource_types = {*resource_key_types.values()}
    if not tagged_types <= known_resource_types:
        raise CampaignError("unmodeled tagged campaign residue exists")
    evidence = {
        "version": "m7.8-residue-readback-v2",
        "campaignCorrelation": sanitize(config.campaign_id, domain="campaign"),
        "generationCorrelation": sanitize(config.generation_id, domain="generation"),
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "controllerActiveCount": active_matches,
        "controllerDeletedCount": deleted_matches,
        "activeInventoryPages": active_pages,
        "deletedInventoryPages": deleted_pages,
        "unrelatedDeletedIdentitySha256": sorted(unrelated_hashes),
        "counters": counters,
    }
    evidence_sha256 = hashlib.sha256(
        b"m7.8/residue-readback/v2\0"
        + json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return ResidueObservation(
        counters=counters,
        evidence_sha256=evidence_sha256,
        active_inventory_pages=active_pages,
        deleted_inventory_pages=deleted_pages,
        unrelated_deleted_identity_sha256=tuple(sorted(unrelated_hashes)),
    )


def verify_zero_residue(
    results: list[dict[str, object]],
    config: CampaignConfig,
    runtime: dict[str, str],
) -> dict[str, int]:
    observation = observe_residue(results, config, runtime)
    if any(observation.counters.values()):
        raise CampaignError("campaign residue is nonzero")
    return observation.counters


def start_failure_cleanup(
    runner: SubprocessRunner, config: CampaignConfig, runtime: dict[str, str],
    before_dispatch: Callable[[], None] | None = None,
) -> None:
    for command in command_plan("cleanup", config, runtime):
        if before_dispatch is not None:
            before_dispatch()
        try:
            _run_required(runner, command)
        except CampaignError:
            break
    else:
        return
    start_direct_cleanup(runner, config, runtime, before_dispatch)


def start_direct_cleanup(
    runner: SubprocessRunner, config: CampaignConfig, runtime: dict[str, str],
    before_dispatch: Callable[[], None] | None = None,
) -> None:
    account = _json_result(
        _run_required(runner, ("az", "account", "show", "--output", "json"))
    )
    if (
        not isinstance(account, dict)
        or account.get("id") != runtime["subscriptionId"]
        or sanitize(str(account.get("id", "")), domain="subscription")
        != config.subscription_correlation
    ):
        raise CampaignError("direct cleanup subscription correlation differs")
    exists_command = ("az", "group", "exists", "--name", config.target_resource_group)
    exists = _json_result(_run_required(runner, exists_command))
    if exists is False:
        return
    if exists is not True:
        raise CampaignError("direct cleanup target existence is malformed")
    group = _json_result(
        _run_required(
            runner,
            (
                "az",
                "group",
                "show",
                "--name",
                config.target_resource_group,
                "--output",
                "json",
            ),
        )
    )
    tags = group.get("tags") if isinstance(group, dict) else None
    if (
        not isinstance(group, dict)
        or group.get("name") != config.target_resource_group
        or not isinstance(tags, dict)
        or tags.get("mobius.milestone") != "7.8"
        or tags.get("mobius.campaign") != config.campaign_id
        or tags.get("mobius.generation") != config.generation_id
        or tags.get("mobius.cleanup-deadline-utc") != config.cleanup_deadline_utc
        or tags.get("mobius.cost-ceiling-cents") != str(config.cost_ceiling_cents)
    ):
        raise CampaignError("direct cleanup target ownership differs")
    properties = group.get("properties")
    if isinstance(properties, dict) and properties.get("provisioningState") == "Deleting":
        # An owned deletion is already in progress. Preserve it without another
        # delete request; cleanup-wait and residue must still prove absence.
        return
    if before_dispatch is not None:
        before_dispatch()
    delete_result = runner.run(
        (
            "az",
            "group",
            "delete",
            "--name",
            config.target_resource_group,
            "--yes",
            "--output",
            "none",
        )
    )
    final_exists = _json_result(_run_required(runner, exists_command))
    if final_exists is not False:
        if delete_result.get("exitCode") != 0:
            raise CampaignError("direct cleanup target delete failed safely")
        raise CampaignError("direct cleanup target residue is nonzero")
    print(
        json.dumps(
            {
                "status": "direct-cleanup-started",
                "targetResourceGroupDeletionStarted": True,
                "controllerDeletionStarted": False,
                "automationAccountDeletionStarted": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def required_pilot_regional_providers(config: CampaignConfig) -> tuple[str, ...]:
    if config.target_region == "canadacentral" and config.maximum_hours == 10:
        return ("Microsoft.EventHub", "Microsoft.KeyVault")
    return ()


def validate_campaign_provider_quotas(postgres: object, container_apps: object) -> None:
    """Require the named regional quotas for the fixed HA campaign topology."""
    for response, requirements, unit_required in (
        (postgres, {"cores": 4, "standardDDSv4Family": 4}, True),
        (container_apps, {"ManagedEnvironmentCount": 1}, False),
    ):
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("value"), list)
            or response.get("nextLink") not in (None, "")
        ):
            raise CampaignError("provider quota evidence is incomplete")
        values = response["value"]
        for name, required in requirements.items():
            matches = [
                item for item in values
                if isinstance(item, dict)
                and isinstance(item.get("name"), dict)
                and item["name"].get("value") == name
            ]
            if len(matches) != 1:
                raise CampaignError(f"required provider quota missing or ambiguous: {name}")
            item = matches[0]
            limit, current = item.get("limit"), item.get("currentValue")
            unit = item.get("unit")
            if (
                type(limit) is not int or type(current) is not int
                or limit < 0 or current < 0
                or (unit != "Count" if unit_required else unit not in (None, "Count"))
            ):
                raise CampaignError(f"provider quota fields malformed: {name}")
            if limit - current < required:
                raise CampaignError(f"provider quota headroom insufficient: {name}")


def validate_region_selection_refresh(
    refreshed: AutomationRegionSelection,
    config: CampaignConfig,
    runtime: dict[str, str],
) -> None:
    """Keep the prepared receipt exact while comparing the admitted region scope."""
    if refreshed.sha256() == config.cleanup_region_selection_sha256:
        return
    failure = "prepared Automation cleanup region or offer proof is no longer armable"
    try:
        prepared = selection_from_document(
            json.loads(Path(runtime["cleanupRegionSelectionFile"]).read_text(encoding="utf-8"))
        )
    except (KeyError, OSError, ValueError) as exc:
        raise CampaignError(f"{failure}: prepared receipt is unreadable") from exc
    if prepared.sha256() != config.cleanup_region_selection_sha256:
        raise CampaignError(f"{failure}: prepared receipt binding differs")
    # The complete provider location inventory can change outside the fixed
    # candidate set. Both validated documents bind support/status for every
    # admitted candidate and all policy, offer, occupancy and controller facts.
    # Preserve both full inventory hashes; do not substitute either one.
    audit_fields = {"observedAtUtc", "providerLocationsSha256"}
    prepared_decision = {
        key: value for key, value in prepared.document().items() if key not in audit_fields
    }
    refreshed_decision = {
        key: value for key, value in refreshed.document().items() if key not in audit_fields
    }
    if prepared_decision != refreshed_decision:
        raise CampaignError(failure)


def validate_operation_results(
    operation: str,
    results: list[dict[str, object]],
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    runner: SubprocessRunner | None = None,
    controller_authority_evidence: object = None,
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
            != "refs/remotes/origin/milestone-7-8-production-readiness-audit-local"
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
        validate_bound_controller_authority(controller_authority_evidence, runtime, config)
        pilot_providers = required_pilot_regional_providers(config)
        if len(results) != 26 + len(pilot_providers):
            raise CampaignError(
                "provider, quota, region, SKU, or name proof is incomplete"
            )
        providers = [_json_result(result) for result in results[:8]]
        if any(
            not isinstance(provider, dict)
            or provider.get("registrationState") != "Registered"
            for provider in providers
        ):
            raise CampaignError("required Azure provider is not registered")
        for namespace, result in zip(pilot_providers, results[26:], strict=True):
            provider = _json_result(result)
            if (
                not isinstance(provider, dict)
                or provider.get("namespace") != namespace
                or provider.get("registrationState") != "Registered"
            ):
                raise CampaignError(f"required Azure provider is not registered: {namespace}")
        skus = _json_result(results[8])
        postgres_quota = _json_result(results[9])
        app_quota = _json_result(results[10])
        registry_name = _json_result(results[11])
        postgres_name = _json_result(results[12])
        if "Standard_D2ds_v4" not in json.dumps(skus, separators=(",", ":")):
            raise CampaignError("required PostgreSQL SKU is unavailable")
        validate_campaign_provider_quotas(postgres_quota, app_quota)
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
            tuple(results[13:19]),
            subscription_id=runtime["subscriptionId"],
            controller_resource_group=config.cleanup_resource_group,
            controller_account=runtime["automationAccountName"],
            subscription_correlation=config.subscription_correlation,
            cleanup_script_sha256=runtime["cleanupScriptSha256"],
            fresh_controller_admission_evidence_sha256=(
                config.fresh_controller_admission_evidence_sha256
            ),
            controller_required_until_utc=runtime["cleanupAuthorityExpiresUtc"],
            controller_authority_evidence=controller_authority_evidence,
        )
        validate_region_selection_refresh(refreshed_selection, config, runtime)
        if (
            refreshed_selection.controller_disposition != "exact-controller-adoptable"
            or refreshed_selection.selected_region != config.cleanup_region
            or ",".join(refreshed_selection.candidate_order)
            != config.cleanup_candidate_regions
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
            or refreshed_selection.fresh_controller_admission_evidence_sha256
            != config.fresh_controller_admission_evidence_sha256
        ):
            raise CampaignError(
                "prepared Automation cleanup region or offer proof is no longer armable"
            )
        validate_controller_baseline(results[19:26], config, runtime)
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
            or tags.get("mobius.cost-ceiling-cents") != str(config.cost_ceiling_cents)
            or tags.get("mobius.cleanup-region-selection-sha256")
            != config.cleanup_region_selection_sha256
            or tags.get("mobius.cleanup-candidate-regions")
            != config.cleanup_candidate_regions
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
            or tags.get("mobius.fresh-controller-admission-sha256")
            != config.fresh_controller_admission_evidence_sha256
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
        from infra.milestone_7_8.campaign_deadline_renewal import origin_context

        origin_context(runtime, config)
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
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--image-digest")
    parser.add_argument("--image-built", action="store_true")
    parser.add_argument("--image-scan-evidence", type=Path)
    parser.add_argument("--control-plane-evidence", type=Path)
    parser.add_argument("--resume-database-job", action="store_true")
    parser.add_argument("--bootstrap-source-transition", type=Path)
    parser.add_argument("--image-continuation", type=Path)
    parser.add_argument("--workload-recovery", type=Path)
    parser.add_argument("--workload-recovery-sha256")
    args = parser.parse_args()
    try:
        if args.resume_database_job and args.operation not in {"bootstrap", "migrate"}:
            raise CampaignError("only bootstrap or migrate supports a guarded database retry")
        if args.workload_recovery is not None and (
            args.image_continuation is not None or args.bootstrap_source_transition is not None
        ):
            raise CampaignError("independent source transitions cannot be combined")
        if args.workload_recovery is None and args.workload_recovery_sha256 is not None:
            raise CampaignError("workload recovery hash requires its exact private plan")
        cleanup_only = args.operation in {
            "cleanup",
            "cleanup-wait",
            "cleanup-disarm",
            "residue",
            "finalize",
        }
        if args.image_continuation is not None:
            if args.bootstrap_source_transition is not None:
                raise CampaignError("independent source transitions cannot be combined")
            from infra.milestone_7_8 import image_continuation

            runtime, config, ledger = image_continuation.load_context(
                args.image_continuation, args.runtime, args.config, args.ledger,
                operation=args.operation,
            )
        else:
            config = CampaignConfig.from_json(args.config, allow_expired=True)
            runtime = load_runtime(args.runtime)
            validate_prepared_bundle(args.runtime, runtime, config)
            if "pilotCleanupWindowFile" in runtime:
                from infra.milestone_7_8.pilot_cleanup import validate_operator_invocation

                validate_operator_invocation(
                    args.runtime, runtime, config, args.ledger, args.operation, args.execute
                )
            ledger = load_ledger(args.ledger, config)
        from infra.milestone_7_8.campaign_deadline_renewal import validate_ledger_binding

        validate_ledger_binding(runtime, ledger)
        controller_authority = (
            load_bound_controller_authority(args.runtime, runtime, config)
            if args.operation == "capacity-check"
            else None
        )
        if args.execute:
            load_bound_fresh_controller_admission(
                args.runtime,
                runtime,
                config,
            )
        repaired_workload_pause = None
        if args.workload_recovery is not None:
            from infra.milestone_7_8 import workload_recovery

            if any(actual.resolve() != workload_recovery.PRIVATE / name for actual, name in (
                (args.runtime, "runtime.json"), (args.config, "campaign-cost.json"),
                (args.ledger, "ledger.json"),
            )):
                raise CampaignError("workload recovery requires the original prepared bundle files")
            if not cleanup_only:
                if args.operation not in workload_recovery.OPERATIONS:
                    raise CampaignError("workload recovery does not admit this phase")
                workload_plan = workload_recovery.load_plan(args.workload_recovery, runtime, config)
                if args.workload_recovery_sha256 != workload_plan["planSha256"]:
                    raise CampaignError("workload recovery plan does not match the approved hash")
                if args.operation != "image-decision":
                    repaired_workload_pause = workload_recovery.resume_pause(
                        args.workload_recovery, workload_plan, runtime, config, ledger,
                    )
            else:
                # Cleanup must remain possible after an incomplete repair. It
                # keeps the frozen runtime and never consumes a repair receipt.
                workload_recovery._source(runtime)
        source_transition = None
        if (args.image_continuation is not None
                and args.operation in {"migrate", "evidence", "dispose"}):
            source_transition = image_continuation.migration_retry_transition(
                args.image_continuation, runtime, config, ledger,
            )
            if _migration_image_transition(source_transition):
                assert source_transition is not None
                repaired_workload_pause = str(source_transition["resolvedWorkloadPauseSha256"])
        if args.bootstrap_source_transition is not None:
            from infra.milestone_7_8.bootstrap_transition import (
                load_bootstrap_transition,
                require_operation,
            )

            source_transition = load_bootstrap_transition(
                args.bootstrap_source_transition, args.runtime, args.config,
                runtime, config, ledger, args.operation, args.resume_database_job,
            )
            # Existing history/readback validators establish completion before
            # the separate executing-source authority can admit later phases.
            if not cleanup_only:
                _active_protected_pause(
                    args.ledger.parent, config, runtime, ledger, source_transition,
                )
            completed_transition = None
            completed_path = args.ledger.with_name("bootstrap-stage-recovery-completed.json")
            if completed_path.exists() and not cleanup_only:
                completed = _read_stage_record(completed_path, "stage-recovery-completed")
                completed_transition = str(completed.get("bootstrapSourceTransitionSha256", ""))
            require_operation(
                source_transition, args.operation, args.resume_database_job,
                completed_transition_sha256=completed_transition,
            )

        database_recovery_directory = args.ledger.parent
        if _grant_only_transition(source_transition):
            assert source_transition is not None and args.image_continuation is not None
            database_recovery_directory = Path(str(source_transition["recoveryDirectory"]))
            expected_recovery = args.image_continuation.resolve().parent / "grant-recovery"
            if database_recovery_directory.resolve() != expected_recovery:
                raise CampaignError("grant-only recovery output is outside its approved slot")

        def require_cleanup_authority() -> None:
            try:
                if args.authorization is None:
                    raise CampaignError("separate cleanup authorization is required")
                load_execution_authorization(
                    args.authorization, config=config, runtime=runtime, operation="cleanup",
                )
            except CampaignError as exc:
                print(json.dumps({
                    "status": "cleanup-dispatch-blocked", "error": str(exc),
                }), file=sys.stderr)
                raise _CleanupAuthorizationBlocked(str(exc)) from exc

        target = OPERATION_PHASE[args.operation]
        required_authorizations = required_execution_authorizations(
            args.operation, Phase(ledger.phase)
        )
        if "pilotCleanupWindowFile" in runtime and args.operation in {
            "cleanup-wait", "cleanup-disarm",
        }:
            required_authorizations = frozenset({args.operation})
        if args.execute and required_authorizations:
            if args.authorization is None:
                raise CampaignError(
                    "separate Azure execution authorization is required"
                )
            for authorized_operation in sorted(required_authorizations):
                load_execution_authorization(
                    args.authorization, config=config, runtime=runtime,
                    operation=authorized_operation,
                )
        if (
            (args.execute or "pilotCleanupWindowFile" not in runtime)
            and not cleanup_only
            and parse_utc(config.cleanup_deadline_utc) <= datetime.now(UTC)
        ):
            if args.execute and ORDER.index(Phase(ledger.phase)) >= ORDER.index(
                Phase.SCOPE_CREATED
            ) and Phase(ledger.phase) not in {
                Phase.CLEANING,
                Phase.CLEANED,
                Phase.CLEANUP_DISARMED,
                Phase.RESIDUE_VERIFIED,
                Phase.FINALIZED,
            }:
                expiry_runner = SubprocessRunner()
                require_cleanup_authority()
                start_failure_cleanup(expiry_runner, config, runtime, require_cleanup_authority)
                ledger.transition(Phase.CLEANING, datetime.now(UTC))
                save_ledger(args.ledger, ledger)
            raise CampaignError("cleanup deadline is expired; cleanup is required")
        if args.execute and args.operation == "scope-create":
            from infra.milestone_7_8.local_image import preflight_image_staging

            # A local filesystem failure must happen before the first target
            # write, outside the attempted-write failure-cleanup block below.
            preflight_image_staging(
                args.runtime.parent,
                source_head=runtime["sourceHead"],
                canonical_input_sha256=runtime["canonicalBuildInputSha256"],
            )
            # Full extraction can take time; the first write still needs current
            # authority and a live cleanup window after this local work.
            if parse_utc(config.cleanup_deadline_utc) <= datetime.now(UTC):
                raise CampaignError("cleanup deadline expired during local image path preflight")
            for authorized_operation in sorted(required_authorizations):
                load_execution_authorization(
                    args.authorization,
                    config=config,
                    runtime=runtime,
                    operation=authorized_operation,
                )
        if args.workload_recovery is not None and args.operation == "image-decision":
            if (args.image_built or args.image_digest is not None
                    or args.image_scan_evidence is not None):
                raise CampaignError(
                    "workload recovery uses only the retained admitted image evidence"
                )
            if not args.execute:
                print(json.dumps({"operation": "workload-recovery", "mutationAuthorized": False,
                                  "planSha256": workload_plan["planSha256"],
                                  "resourceCount": len(workload_recovery.MISSING)}))
                return 0
            if args.authorization is None:
                raise CampaignError("workload recovery authorization is missing")

            def authorize_workload_recovery() -> None:
                for permitted in ("image-decision", "cleanup"):
                    load_execution_authorization(
                        args.authorization, config=config, runtime=runtime, operation=permitted,
                    )

            recovery_seconds = (
                parse_utc(str(workload_plan["deployUntilUtc"])) - datetime.now(UTC)
            ).total_seconds()
            recovery_runner = SubprocessRunner(timeout_seconds=min(900, max(1, recovery_seconds)))
            try:
                workload_recovery.execute(
                    args.workload_recovery, workload_plan, runtime, config, ledger,
                    authorization=args.authorization, runner=recovery_runner,
                    authorize=authorize_workload_recovery,
                )
            except Exception as repair_error:
                if isinstance(repair_error, _ProtectedStageExpired) or not _stage_is_protected(
                    config, runtime, ledger,
                ):
                    try:
                        require_cleanup_authority()
                        start_failure_cleanup(SubprocessRunner(), config, runtime,
                                              require_cleanup_authority)
                        ledger.transition(Phase.CLEANING, datetime.now(UTC))
                        save_ledger(args.ledger, ledger)
                    except Exception as cleanup_error:
                        print(json.dumps({"status": "cleanup-recording-failed",
                                          "error": str(cleanup_error)}), file=sys.stderr)
                raise
            print(json.dumps({"status": "passed", "phase": ledger.phase}, sort_keys=True))
            return 0
        if args.image_continuation is not None and args.operation == "image-decision":
            if (args.image_digest is None or args.image_scan_evidence is None
                    or (args.execute and args.authorization is None) or args.image_built):
                raise CampaignError("replacement requires retained digest, scan and authority")
            return image_continuation.execute_admission(
                args.image_continuation, runtime, config, ledger,
                digest=args.image_digest, scan_path=args.image_scan_evidence,
                authorization=args.authorization or Path("unused-dry-run"), execute=args.execute,
            )
        image_scan_sha256 = None
        verified_image_build_count = None
        if target is Phase.IMAGE_DECIDED and args.image_digest is not None:
            config = replace(config, image_digest=args.image_digest)
            config.validate()
            if args.image_scan_evidence is not None:
                image_scan_sha256 = load_image_scan_evidence(
                    args.image_scan_evidence,
                    digest=args.image_digest,
                    runtime=runtime,
                )
                if (args.runtime.parent / "local-image-attempt.json").exists():
                    from infra.milestone_7_8.local_image import validate_completion

                    # Validate against the prepared configuration before attaching
                    # its selected digest; local-image never deploys the workload.
                    verified_image_build_count = validate_completion(
                        args.runtime,
                        runtime,
                        replace(config, image_digest=None),
                        digest=args.image_digest,
                        scan_path=args.image_scan_evidence,
                    )
                    if args.image_built and verified_image_build_count == 0:
                        raise CampaignError("retained image admission cannot claim a new build")
        control_evidence = None
        if args.control_plane_evidence is not None:
            control_evidence = load_control_plane_evidence(args.control_plane_evidence)
        rendered_control_evidence = (
            "<derived-after-successful-managed-probes>"
            if control_evidence is not None
            else None
        )
        evidence_receipt_path = args.ledger.with_name("managed-evidence-execution.json")
        if args.execute and args.operation == "evidence":
            if (
                ledger.image_digest is None
                or config.image_digest not in {None, ledger.image_digest}
            ):
                raise CampaignError("measurement image differs from the admitted ledger image")
            config = replace(config, image_digest=ledger.image_digest)
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
            _reconcile_evidence_stage_completion(
                args.ledger.parent, config, runtime, ledger, control_evidence,
            )
            if _active_protected_pause(
                args.ledger.parent, config, runtime, ledger, source_transition,
                resolved_workload_pause_sha256=repaired_workload_pause,
            ) is not None:
                raise _ProtectedStagePaused("another protected stage remains paused")
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
        if args.operation in {"bootstrap", "migrate", "evidence"}:
            commands = tuple(
                (*command, "--subscription", runtime["subscriptionId"]) for command in commands
            )
        if "pilotCleanupWindowFile" in runtime:
            commands = tuple(
                (*command, "--subscription", runtime["subscriptionId"])
                if command[0] == "az" and "--subscription" not in command else command
                for command in commands
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
                            else (
                                "start and stop the campaign worker execution",
                                "start and observe the steady-state sampler execution",
                                "copy the campaign API revision and split API traffic",
                                "start and observe the overlap sampler execution",
                                "read both sampler results from campaign Log Analytics",
                                "restore API traffic and deactivate the temporary revision",
                            )
                            if args.operation == "evidence"
                            else ()
                        ),
                        "mutationAuthorized": False,
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        if args.operation == "evidence" and control_evidence is not None:
            if Phase(ledger.phase) is not Phase.MIGRATED:
                raise CampaignError("managed evidence requires the migrated phase")
            attempt_path = args.ledger.with_name("managed-evidence-attempt.json")
            try:
                with attempt_path.open("x", encoding="utf-8") as attempt:
                    json.dump(
                        {
                            "campaignId": config.campaign_id,
                            "generationId": config.generation_id,
                            "sourceHead": runtime["sourceHead"],
                            "imageDigest": config.image_digest,
                        },
                        attempt,
                        sort_keys=True,
                    )
                    attempt.flush()
                    os.fsync(attempt.fileno())
            except FileExistsError as exc:
                raise CampaignError(
                    "managed evidence attempt already exists; preserve the protected scope "
                    "and reconcile retained evidence before any retry"
                ) from exc
        runner = SubprocessRunner()
        stage_attempt: dict[str, object] | None = None
        recovery_pause: dict[str, object] | None = None
        try:
            if _grant_only_transition(source_transition) and args.operation == "migrate":
                database_recovery_directory.mkdir(exist_ok=True)
            if not cleanup_only:
                expected_previous = {
                    "deploy": Phase.BILLABLE_STARTED,
                    "image-decision": Phase.INFRASTRUCTURE_DEPLOYED,
                    "bootstrap": Phase.IMAGE_DECIDED, "migrate": Phase.DATABASE_BOOTSTRAPPED,
                    "evidence": Phase.MIGRATED, "dispose": Phase.EVIDENCE_EXECUTED,
                }
                if (args.operation in expected_previous
                        and Phase(ledger.phase) is not expected_previous[args.operation]):
                    raise _ProtectedStagePaused("protected stage predecessor is not complete")
                recovery_pause = _active_protected_pause(
                    args.ledger.parent, config, runtime, ledger, source_transition,
                    resolved_image_pause_sha256=(
                        image_continuation.resolved_image_pause(
                            args.image_continuation, runtime, config, ledger,
                        ) if args.image_continuation is not None else None
                    ),
                    resolved_workload_pause_sha256=repaired_workload_pause,
                )
                if recovery_pause is not None:
                    already_dispatched = (
                        args.resume_database_job
                        and (database_recovery_directory
                             / f"{args.operation}-stage-retry-intent.json").exists()
                    )
                    amended_database = (
                        source_transition is not None
                        and (
                            (args.operation == "bootstrap"
                             and recovery_pause["operation"] == "bootstrap")
                            or (args.operation == "migrate"
                                and recovery_pause["operation"] == "migrate"
                                and _migration_image_transition(source_transition))
                        )
                    )
                    if amended_database and not already_dispatched:
                        assert source_transition is not None
                        _validate_transition_dispatch(source_transition)
                    if ((not already_dispatched and not amended_database
                         and parse_utc(str(recovery_pause["recoveryUntilUtc"]))
                         <= datetime.now(UTC))
                            or not _stage_is_protected(config, runtime, ledger)):
                        raise _ProtectedStageExpired("protected stage recovery window expired")
                    if (not args.resume_database_job
                            or recovery_pause["operation"] != args.operation):
                        raise _ProtectedStagePaused(
                            "campaign stage is paused; dependent work and plain retries are blocked"
                        )
                elif args.resume_database_job:
                    raise _ProtectedStagePaused(
                        "database retry requires a bound failed-stage pause"
                    )
                if args.operation in {"bootstrap", "migrate"}:
                    if len(commands) != 1 or args.authorization is None:
                        raise _ProtectedStagePaused("database stage authorization is missing")
                    prerequisite_folder = args.ledger.parent
                    if args.image_continuation is not None:
                        prerequisite_folder = image_continuation.prerequisite_directory(
                            args.image_continuation, runtime, config, ledger,
                        )
                    if (_grant_only_transition(source_transition)
                            and prerequisite_folder.resolve()
                            != database_recovery_directory.resolve()):
                        raise _ProtectedStagePaused("grant prerequisite escaped its approved slot")
                    _database_prerequisites(
                        runner, commands[0], operation=args.operation, config=config,
                        runtime=runtime, ledger=ledger, directory=prerequisite_folder,
                        authorization_path=args.authorization, retry=args.resume_database_job,
                        allow_fresh_retry=(
                            args.operation == "migrate" and args.resume_database_job
                            and _migration_image_transition(source_transition)
                        ),
                        source_transition=source_transition,
                    )
                if args.operation in PROTECTED_STAGE_OPERATIONS and recovery_pause is None:
                    attempt_path = args.ledger.parent / f"{args.operation}-stage-attempt.json"
                    if attempt_path.exists():
                        raise _ProtectedStagePaused(
                            "protected stage already has an attempt; "
                            "do not replay an uncertain dispatch"
                        )
                    if args.authorization is None:
                        raise CampaignError("protected stage authorization is missing")
                    stage_attempt = _stage_record(attempt_path, "stage-attempt", {
                        "version": "m7.8-protected-stage-attempt-v1", "operation": args.operation,
                        "bindings": _stage_bindings(config, runtime, ledger),
                        "commandSha256": _stage_hash("stage-command", commands),
                        "authorizationSha256": hashlib.sha256(
                            args.authorization.read_bytes()
                        ).hexdigest(),
                        "startedAtUtc": datetime.now(UTC).isoformat(),
                    })
            cleanup_arm_evidence_sha256: str | None = None
            cleanup_disarm_evidence_sha256: str | None = None
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
            measurement = None
            if args.operation == "evidence" and control_evidence is not None:
                if config.image_digest is None:
                    raise CampaignError("measurement image is missing")
                def authorize_evidence() -> None:
                    if args.authorization is None:
                        raise CampaignError("managed evidence authorization is missing")
                    if not _stage_is_protected(config, runtime, ledger):
                        raise _ProtectedStageExpired("managed evidence protection expired")
                    for permitted in ("evidence", "cleanup"):
                        load_execution_authorization(
                            args.authorization, config=config, runtime=runtime,
                            operation=permitted, now=datetime.now(UTC),
                        )

                sampler = CampaignMeasurement(
                    runner, runtime, config.cleanup_deadline_utc,
                    private_directory=args.ledger.parent, image_digest=config.image_digest,
                    authorize=authorize_evidence,
                )
                try:
                    measurement = sampler.run(control_evidence, keep_worker=True)
                    results = execute_evidence_commands(
                        runner, commands, {
                            **control_evidence,
                            "observedPeak": measurement["observedPeak"],
                            "latencyP95Ms": measurement["latencyP95Ms"],
                        },
                        private_directory=args.ledger.parent,
                        image_digest=config.image_digest, runtime=runtime,
                        worker_execution=str(measurement["workerExecution"]),
                        deadline=parse_utc(config.cleanup_deadline_utc),
                        authorize=authorize_evidence,
                    )
                except Exception:
                    if sampler.worker_execution is not None:
                        try:
                            sampler.stop_worker(sampler.worker_execution)
                        except Exception as stop_error:
                            with contextlib.suppress(Exception):
                                _stage_record(
                                    args.ledger.parent / "measurement-worker-stop-failed.json",
                                    "worker-stop-failed", {
                                        "errorClass": type(stop_error).__name__,
                                        "observedAtUtc": datetime.now(UTC).isoformat(),
                                    },
                                )
                    raise
                else:
                    if sampler.worker_execution is not None:
                        sampler.stop_worker(sampler.worker_execution)
            elif args.operation == "deploy":
                # ARM can outlive the ordinary command timeout. Only this base
                # deployment gets a longer wait, never beyond campaign expiry.
                remaining = (
                    parse_utc(config.cleanup_deadline_utc) - datetime.now(UTC)
                ).total_seconds()
                if remaining <= 0:
                    raise CampaignError("base deployment cleanup window is exhausted")
                deployment_runner = SubprocessRunner(timeout_seconds=min(3600, remaining))
                results = execute_commands(deployment_runner, commands)
            elif args.operation == "cleanup-deploy":
                results = execute_cleanup_deploy_commands(
                    runner, commands, config, runtime
                )
            elif args.operation == "cleanup-arm":
                results, cleanup_arm_evidence_sha256 = execute_cleanup_arm_commands(
                    runner, commands, config, runtime
                )
            elif args.operation == "cleanup-disarm":
                results, cleanup_disarm_evidence_sha256 = (
                    execute_cleanup_disarm_commands(runner, commands, config, runtime)
                )
            elif args.operation == "residue":
                results = execute_residue_commands(runner, commands)
            elif recovery_pause is not None and args.resume_database_job:
                if len(commands) != 1 or args.authorization is None:
                    raise _ProtectedStagePaused("database retry command binding differs")
                result, stage_attempt = _execute_database_retry(
                    runner, commands[0], operation=args.operation, config=config, runtime=runtime,
                    ledger=ledger, pause=recovery_pause, directory=database_recovery_directory,
                    authorization_path=args.authorization,
                    source_transition=source_transition,
                )
                results = [result]
            else:
                results = execute_commands(runner, commands)
            validate_operation_results(
                args.operation,
                results,
                config,
                runtime,
                runner=runner,
                controller_authority_evidence=controller_authority,
            )
            if measurement is not None and control_evidence is not None:
                persist_evidence_execution_receipt(
                    evidence_receipt_path,
                    config=config,
                    runtime=runtime,
                    commands=commands,
                    results=results,
                    control_plane_evidence=control_evidence,
                    measurement=measurement,
                )
            if target is Phase.COST_GATED:
                config.validate()
                ledger.bind_deadline(config.cleanup_deadline_utc)
            if target is Phase.IMAGE_DECIDED:
                if args.image_digest is None or image_scan_sha256 is None:
                    raise CampaignError(
                        "immutable image decision or admission scan is missing"
                    )
                ledger.record_image(
                    args.image_digest,
                    built=(verified_image_build_count == 1)
                    if verified_image_build_count is not None
                    else args.image_built,
                )
                ledger.record_image_scan(args.image_digest, image_scan_sha256)
            if target is Phase.CLEANUP_DEPLOYED:
                if len(results) != 8:
                    raise CampaignError("cleanup deployment result is missing")
                validate_cleanup_deployment(results[-1], config)
            if target is Phase.CLEANUP_ARMED:
                if cleanup_arm_evidence_sha256 is None:
                    raise CampaignError("cleanup arming proof is missing")
                ledger.record_cleanup_arm_evidence(cleanup_arm_evidence_sha256)
            if target is Phase.CLEANUP_VERIFIED:
                verified_arm_evidence = validate_cleanup_readback(
                    results, config, runtime
                )
                if verified_arm_evidence != ledger.cleanup_arm_evidence_sha256:
                    raise CampaignError("cleanup arming evidence changed after arming")
            if target is Phase.CLEANUP_DISARMED:
                if cleanup_disarm_evidence_sha256 is None:
                    raise CampaignError("cleanup disarming proof is missing")
                ledger.record_cleanup_disarm_evidence(cleanup_disarm_evidence_sha256)
            if target is Phase.RESIDUE_VERIFIED:
                observation = observe_residue(results, config, runtime)
                disposition = ledger.record_residue(
                    observation.counters,
                    evidence_sha256=observation.evidence_sha256,
                )
                if disposition != "zero-residue":
                    save_ledger(args.ledger, ledger)
                    print(
                        json.dumps(
                            {
                                "status": "blocked",
                                "phase": Phase.CLEANED.value,
                                "cleanupDisposition": disposition,
                                "residue": observation.counters,
                                "residueEvidenceSha256": (observation.evidence_sha256),
                                "activeInventoryPages": (
                                    observation.active_inventory_pages
                                ),
                                "deletedInventoryPages": (
                                    observation.deleted_inventory_pages
                                ),
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    )
                    return 3
            ledger.transition(target, datetime.now(UTC))
            save_ledger(args.ledger, ledger)
            output: object = (
                terminal_receipt(ledger)
                if target is Phase.FINALIZED
                else {"status": "passed", "phase": target.value}
            )
            print(json.dumps(output, separators=(",", ":"), sort_keys=True))
            return 0
        except Exception as phase_error:
            protected = _stage_is_protected(config, runtime, ledger)
            if (isinstance(phase_error, (_ProtectedStagePaused, ProtectedStagePersistenceError))
                    and protected):
                raise
            preserved = False
            if (args.operation in PROTECTED_STAGE_OPERATIONS and protected
                    and not isinstance(phase_error, _ProtectedStageExpired)):
                try:
                    if stage_attempt is None and recovery_pause is not None:
                        attempt_sha = str(recovery_pause["attemptSha256"])
                        authorization_sha = str(recovery_pause["authorizationSha256"])
                    elif stage_attempt is not None:
                        attempt_sha = str(stage_attempt["recordSha256"])
                        authorization_sha = str(stage_attempt["authorizationSha256"])
                    else:
                        raise ProtectedStagePersistenceError(
                            "protected stage attempt is unavailable"
                        )
                    if (source_transition is not None
                            and (args.operation == "bootstrap"
                                 or (args.operation == "migrate"
                                     and _migration_image_transition(source_transition)))
                            and recovery_pause is not None):
                        # Retain the original expired pause unchanged. This amendment
                        # permits one new dispatch, not teardown on an uncertain result.
                        preserved = True
                    else:
                        preserved = preserve_protected_stage_failure(
                            args.operation, config, runtime, ledger, args.ledger.parent,
                            attempt_sha, authorization_sha,
                            failed_execution=(
                                phase_error.execution
                                if isinstance(phase_error, _JobExecutionFailure) else None
                            ),
                        ) is not None
                except (ProtectedStagePersistenceError, _ProtectedStagePaused):
                    # The pre-dispatch attempt still prevents replay. A diagnostic
                    # or persistence failure alone never authorizes deleting healthy scope.
                    print(
                        json.dumps({"status": "stage-pause-recording-incomplete"}), file=sys.stderr,
                    )
                    raise phase_error from None
            if isinstance(phase_error, _JobExecutionFailure):
                try:
                    _capture_failed_job_diagnostics(
                        phase_error, runtime=runtime,
                        deadline=parse_utc(config.cleanup_deadline_utc),
                        private_directory=database_recovery_directory,
                    )
                except Exception:
                    print(json.dumps({"status": "job-diagnostics-incomplete"}), file=sys.stderr)
            if preserved and _stage_is_protected(config, runtime, ledger):
                print(
                    json.dumps({"status": "stage-paused", "phase": ledger.phase}), file=sys.stderr,
                )
                raise
            try:
                if (
                    args.operation == "cleanup-wait"
                    and Phase(ledger.phase) is Phase.CLEANING
                ):
                    require_cleanup_authority()
                    start_direct_cleanup(runner, config, runtime, require_cleanup_authority)
                if (
                    target is Phase.SCOPE_CREATED
                    or ORDER.index(Phase(ledger.phase)) >= ORDER.index(Phase.SCOPE_CREATED)
                ) and Phase(ledger.phase) not in {
                    Phase.CLEANING,
                    Phase.CLEANED,
                    Phase.CLEANUP_DISARMED,
                    Phase.RESIDUE_VERIFIED,
                    Phase.FINALIZED,
                }:
                    require_cleanup_authority()
                    try:
                        start_failure_cleanup(runner, config, runtime, require_cleanup_authority)
                    except _CleanupAuthorizationBlocked:
                        raise
                    except Exception as cleanup_error:
                        print(
                            json.dumps(
                                {"status": "cleanup-start-failed", "error": str(cleanup_error)}
                            ),
                            file=sys.stderr,
                        )
                    ledger.transition(
                        Phase.CLEANING, datetime.now(UTC),
                        scope_write_attempted=target is Phase.SCOPE_CREATED,
                    )
                    save_ledger(args.ledger, ledger)
            except Exception as cleanup_error:
                print(
                    json.dumps({"status": "cleanup-recording-failed", "error": str(cleanup_error)}),
                    file=sys.stderr,
                )
            raise
    except Exception as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
