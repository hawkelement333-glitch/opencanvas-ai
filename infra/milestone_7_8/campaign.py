from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, cast

from infra.milestone_7_8.azure_cli import (
    AZURE_CLI_TOKEN,
    AzureCliError,
    AzureCliLauncher,
)

HARD_CEILING: Final = Decimal("50.00")
DEFAULT_ESTIMATE: Final = Decimal("25.6832")
MAX_HOURS: Final = 4
CAMPAIGN_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]{7,47}$")
GENERATION_PATTERN: Final = re.compile(r"^g[1-9][0-9]{0,5}-[a-f0-9]{12}$")
DIGEST_PATTERN: Final = re.compile(r"^sha256:[a-f0-9]{64}$")
HASH_PATTERN: Final = re.compile(r"^[a-f0-9]{64}$")
CORRELATION_PATTERN: Final = re.compile(r"^[a-f0-9]{16}$")
TARGET_RESOURCE_GROUP_PATTERN: Final = re.compile(r"^rg-m78-[a-f0-9]{10}-target$")
CLEANUP_RESOURCE_GROUP_PATTERN: Final = re.compile(r"^rg-m78-controller-[a-f0-9]{10}$")
RESIDUE_KEYS: Final = (
    "targetResourceGroups",
    "cleanupResourceGroups",
    "roleAssignments",
    "cleanupSchedules",
    "managedIdentities",
    "postgresServers",
    "containerRegistries",
    "containerAppsEnvironments",
    "containerAppsJobs",
    "virtualNetworks",
    "privateEndpoints",
    "privateDnsZones",
    "diagnosticSettings",
    "syntheticRows",
)
RESIDUE_DISPOSITIONS: Final = {
    "pending",
    "zero-residue",
    "nonzero-residue",
}
CLEANUP_CANDIDATE_REGIONS_BINDING: Final = (
    "eastus2,southcentralus,westus2,westus,eastus,northeurope,southeastasia"
)


class CampaignError(RuntimeError):
    pass


class Phase(StrEnum):
    NEW = "new"
    PREFLIGHT = "preflight"
    CORRELATED = "correlated"
    CAPACITY_CHECKED = "capacity-checked"
    COST_GATED = "cost-gated"
    SCOPE_CREATED = "scope-created"
    CLEANUP_DEPLOYED = "cleanup-deployed"
    CLEANUP_ARMED = "cleanup-armed"
    CLEANUP_VERIFIED = "cleanup-verified"
    BILLABLE_STARTED = "billable-started"
    INFRASTRUCTURE_DEPLOYED = "infrastructure-deployed"
    IMAGE_DECIDED = "image-decided"
    DATABASE_BOOTSTRAPPED = "database-bootstrapped"
    MIGRATED = "migrated"
    EVIDENCE_EXECUTED = "evidence-executed"
    DISPOSED = "disposed"
    CLEANING = "cleaning"
    CLEANED = "cleaned"
    CLEANUP_DISARMED = "cleanup-disarmed"
    RESIDUE_VERIFIED = "residue-verified"
    FINALIZED = "finalized"


ORDER: Final = (
    Phase.NEW,
    Phase.PREFLIGHT,
    Phase.CORRELATED,
    Phase.CAPACITY_CHECKED,
    Phase.COST_GATED,
    Phase.SCOPE_CREATED,
    Phase.CLEANUP_DEPLOYED,
    Phase.CLEANUP_ARMED,
    Phase.CLEANUP_VERIFIED,
    Phase.BILLABLE_STARTED,
    Phase.INFRASTRUCTURE_DEPLOYED,
    Phase.IMAGE_DECIDED,
    Phase.DATABASE_BOOTSTRAPPED,
    Phase.MIGRATED,
    Phase.EVIDENCE_EXECUTED,
    Phase.DISPOSED,
    Phase.CLEANING,
    Phase.CLEANED,
    Phase.CLEANUP_DISARMED,
    Phase.RESIDUE_VERIFIED,
    Phase.FINALIZED,
)


@dataclass(frozen=True, slots=True)
class CostItem:
    name: str
    hourly_usd: str
    hours: int
    fixed_usd: str = "0"
    priced_at_utc: str = "2026-08-13T00:00:00Z"

    def maximum(self) -> Decimal:
        if not self.name or not isinstance(self.hours, int) or self.hours <= 0:
            raise CampaignError("cost item is malformed")
        parse_utc(self.priced_at_utc)
        rounded_hours = Decimal(self.hours).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
        hourly = Decimal(self.hourly_usd)
        fixed = Decimal(self.fixed_usd)
        if not hourly.is_finite() or not fixed.is_finite() or hourly < 0 or fixed < 0:
            raise CampaignError("cost item is malformed")
        return hourly * rounded_hours + fixed


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    campaign_id: str
    generation_id: str
    subscription_correlation: str
    tenant_correlation: str
    target_resource_group: str
    cleanup_resource_group: str
    target_region: str
    cleanup_region: str
    postgres_region: str
    cleanup_deadline_utc: str
    conservative_estimate_usd: str
    contingency_percent: str
    resource_items: tuple[CostItem, ...]
    principal_manifest_sha256: str
    cleanup_region_selection_sha256: str
    cleanup_candidate_regions: str
    cleanup_offer_classification: str
    cleanup_offer_eligibility_disposition: str
    cleanup_offer_eligible_regions: str
    cleanup_offer_eligibility_source: str
    cleanup_offer_eligibility_sha256: str
    fresh_controller_admission_evidence_sha256: str
    image_digest: str | None = None

    @classmethod
    def from_json(cls, path: Path, *, allow_expired: bool = False) -> CampaignConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "campaignId",
            "generationId",
            "subscriptionCorrelation",
            "tenantCorrelation",
            "targetResourceGroup",
            "cleanupResourceGroup",
            "targetRegion",
            "cleanupRegion",
            "postgresRegion",
            "cleanupDeadlineUtc",
            "conservativeEstimateUsd",
            "contingencyPercent",
            "resourceItems",
            "principalManifestSha256",
            "cleanupRegionSelectionSha256",
            "cleanupCandidateRegions",
            "cleanupOfferClassification",
            "cleanupOfferEligibilityDisposition",
            "cleanupOfferEligibleRegions",
            "cleanupOfferEligibilitySource",
            "cleanupOfferEligibilitySha256",
            "freshControllerAdmissionEvidenceSha256",
            "imageDigest",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise CampaignError("campaign configuration fields are invalid")
        if not isinstance(raw["resourceItems"], list):
            raise CampaignError("resourceItems must be an array")
        items = tuple(
            CostItem(
                name=item["name"],
                hourly_usd=item["hourlyUsd"],
                hours=item["hours"],
                fixed_usd=item["fixedUsd"],
                priced_at_utc=item["pricedAtUtc"],
            )
            for item in raw["resourceItems"]
        )
        config = cls(
            campaign_id=raw["campaignId"],
            generation_id=raw["generationId"],
            subscription_correlation=raw["subscriptionCorrelation"],
            tenant_correlation=raw["tenantCorrelation"],
            target_resource_group=raw["targetResourceGroup"],
            cleanup_resource_group=raw["cleanupResourceGroup"],
            target_region=raw["targetRegion"],
            cleanup_region=raw["cleanupRegion"],
            postgres_region=raw["postgresRegion"],
            cleanup_deadline_utc=raw["cleanupDeadlineUtc"],
            conservative_estimate_usd=raw["conservativeEstimateUsd"],
            contingency_percent=raw["contingencyPercent"],
            resource_items=items,
            principal_manifest_sha256=raw["principalManifestSha256"],
            cleanup_region_selection_sha256=raw["cleanupRegionSelectionSha256"],
            cleanup_candidate_regions=raw["cleanupCandidateRegions"],
            cleanup_offer_classification=raw["cleanupOfferClassification"],
            cleanup_offer_eligibility_disposition=raw[
                "cleanupOfferEligibilityDisposition"
            ],
            cleanup_offer_eligible_regions=raw["cleanupOfferEligibleRegions"],
            cleanup_offer_eligibility_source=raw["cleanupOfferEligibilitySource"],
            cleanup_offer_eligibility_sha256=raw["cleanupOfferEligibilitySha256"],
            fresh_controller_admission_evidence_sha256=raw[
                "freshControllerAdmissionEvidenceSha256"
            ],
            image_digest=raw["imageDigest"],
        )
        config.validate(allow_expired=allow_expired)
        return config

    def validate(self, *, allow_expired: bool = False) -> None:
        if CAMPAIGN_PATTERN.fullmatch(self.campaign_id) is None:
            raise CampaignError("campaign identity is malformed")
        if GENERATION_PATTERN.fullmatch(self.generation_id) is None:
            raise CampaignError("generation identity is malformed")
        if any(
            CORRELATION_PATTERN.fullmatch(item) is None
            for item in (self.subscription_correlation, self.tenant_correlation)
        ):
            raise CampaignError("cloud correlation is unsanitized")
        if self.target_resource_group == self.cleanup_resource_group:
            raise CampaignError("cleanup must be outside the target deletion boundary")
        if (
            TARGET_RESOURCE_GROUP_PATTERN.fullmatch(self.target_resource_group) is None
            or CLEANUP_RESOURCE_GROUP_PATTERN.fullmatch(self.cleanup_resource_group)
            is None
            or self.cleanup_resource_group
            != f"rg-m78-controller-{self.subscription_correlation[:10]}"
        ):
            raise CampaignError("campaign resource-group scope is malformed")
        if self.target_region != self.postgres_region:
            raise CampaignError("single-VNet campaign resources must share a region")
        if re.fullmatch(r"[a-z][a-z0-9]{2,31}", self.cleanup_region) is None:
            raise CampaignError("cleanup region binding is malformed")
        if HASH_PATTERN.fullmatch(self.principal_manifest_sha256) is None:
            raise CampaignError("principal manifest binding is invalid")
        if HASH_PATTERN.fullmatch(self.cleanup_region_selection_sha256) is None:
            raise CampaignError("cleanup region selection binding is invalid")
        if (
            HASH_PATTERN.fullmatch(self.fresh_controller_admission_evidence_sha256)
            is None
        ):
            raise CampaignError("fresh controller admission evidence binding is invalid")
        if (
            self.cleanup_candidate_regions != CLEANUP_CANDIDATE_REGIONS_BINDING
            or self.cleanup_region not in self.cleanup_candidate_regions.split(",")
        ):
            raise CampaignError("cleanup candidate region binding is invalid")
        if (
            self.cleanup_offer_eligible_regions
            != "eastus,eastus2,northeurope,southeastasia,westus"
            or self.cleanup_region not in self.cleanup_offer_eligible_regions.split(",")
            or self.cleanup_offer_eligibility_source
            != "microsoft-automation-restricted-public-offer-regions-2026-08-v1"
            or (
                self.cleanup_offer_classification,
                self.cleanup_offer_eligibility_disposition,
            )
            not in {
                (
                    "restricted-public-offer",
                    "restricted-offer-metadata-confirmed",
                ),
                ("unclassified", "restrictive-public-baseline-applied"),
            }
            or HASH_PATTERN.fullmatch(self.cleanup_offer_eligibility_sha256) is None
        ):
            raise CampaignError("cleanup offer eligibility binding is invalid")
        if (
            self.image_digest is not None
            and DIGEST_PATTERN.fullmatch(self.image_digest) is None
        ):
            raise CampaignError("image reference is not immutable")
        deadline = parse_utc(self.cleanup_deadline_utc)
        if not allow_expired and deadline <= datetime.now(UTC):
            raise CampaignError("cleanup deadline is expired")
        subtotal = sum((item.maximum() for item in self.resource_items), Decimal("0"))
        contingency = Decimal(self.contingency_percent)
        estimate = Decimal(self.conservative_estimate_usd)
        if not contingency.is_finite() or not estimate.is_finite() or estimate < 0:
            raise CampaignError("cost values are malformed")
        if contingency < Decimal("25"):
            raise CampaignError("cost contingency is below 25 percent")
        if estimate < subtotal * (Decimal("1") + contingency / Decimal("100")):
            raise CampaignError("conservative estimate does not cover itemized cost")
        if estimate > HARD_CEILING:
            raise CampaignError("cost ceiling exceeded")


@dataclass(slots=True)
class Ledger:
    campaign_id: str
    generation_id: str
    phase: str = Phase.NEW.value
    authorized_ceiling_usd: str = "50.00"
    conservative_estimate_usd: str = str(DEFAULT_ESTIMATE)
    contingency_percent: str = "25"
    first_billable_mutation_utc: str | None = None
    cleanup_deadline_utc: str | None = None
    original_cleanup_deadline_utc: str | None = None
    resource_generation_count: int = 0
    image_generation_count: int = 0
    image_digest: str | None = None
    required_scan_count: int = 0
    image_scan_count: int = 0
    image_scan_evidence_sha256: str | None = None
    transitions: list[dict[str, str]] = field(default_factory=list)
    cleanup_started_utc: str | None = None
    cleanup_completed_utc: str | None = None
    actual_cost_usd: str | None = None
    cleanup_arm_evidence_sha256: str | None = None
    cleanup_disarm_evidence_sha256: str | None = None
    cleanup_disposition: str = "pending"
    residue_evidence_sha256: str | None = None
    residue: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(RESIDUE_KEYS, 0)
    )
    cleanup_region: str | None = None
    cleanup_region_selection_sha256: str | None = None
    cleanup_candidate_regions: str | None = None
    cleanup_offer_classification: str | None = None
    cleanup_offer_eligibility_disposition: str | None = None
    cleanup_offer_eligible_regions: str | None = None
    cleanup_offer_eligibility_source: str | None = None
    cleanup_offer_eligibility_sha256: str | None = None
    fresh_controller_admission_evidence_sha256: str | None = None

    def bind_cleanup_region(self, config: CampaignConfig) -> None:
        expected = (
            config.cleanup_region,
            config.cleanup_region_selection_sha256,
            config.cleanup_candidate_regions,
            config.cleanup_offer_classification,
            config.cleanup_offer_eligibility_disposition,
            config.cleanup_offer_eligible_regions,
            config.cleanup_offer_eligibility_source,
            config.cleanup_offer_eligibility_sha256,
            config.fresh_controller_admission_evidence_sha256,
        )
        observed = (
            self.cleanup_region,
            self.cleanup_region_selection_sha256,
            self.cleanup_candidate_regions,
            self.cleanup_offer_classification,
            self.cleanup_offer_eligibility_disposition,
            self.cleanup_offer_eligible_regions,
            self.cleanup_offer_eligibility_source,
            self.cleanup_offer_eligibility_sha256,
            self.fresh_controller_admission_evidence_sha256,
        )
        if (
            observed == (None, None, None, None, None, None, None, None, None)
            and self.phase == Phase.NEW.value
            and not self.transitions
        ):
            (
                self.cleanup_region,
                self.cleanup_region_selection_sha256,
                self.cleanup_candidate_regions,
                self.cleanup_offer_classification,
                self.cleanup_offer_eligibility_disposition,
                self.cleanup_offer_eligible_regions,
                self.cleanup_offer_eligibility_source,
                self.cleanup_offer_eligibility_sha256,
                self.fresh_controller_admission_evidence_sha256,
            ) = expected
            return
        if observed != expected:
            raise CampaignError(
                "resume cleanup region selection or offer eligibility was substituted"
            )

    def validate_resume(self, config: CampaignConfig) -> None:
        if (
            self.cleanup_region != config.cleanup_region
            or self.cleanup_region_selection_sha256
            != config.cleanup_region_selection_sha256
            or self.cleanup_candidate_regions != config.cleanup_candidate_regions
            or self.cleanup_offer_classification != config.cleanup_offer_classification
            or self.cleanup_offer_eligibility_disposition
            != config.cleanup_offer_eligibility_disposition
            or self.cleanup_offer_eligible_regions
            != config.cleanup_offer_eligible_regions
            or self.cleanup_offer_eligibility_source
            != config.cleanup_offer_eligibility_source
            or self.cleanup_offer_eligibility_sha256
            != config.cleanup_offer_eligibility_sha256
            or self.fresh_controller_admission_evidence_sha256
            != config.fresh_controller_admission_evidence_sha256
        ):
            raise CampaignError(
                "resume cleanup region selection or offer eligibility was substituted"
            )
        if (self.campaign_id, self.generation_id) != (
            config.campaign_id,
            config.generation_id,
        ):
            raise CampaignError("resume campaign or generation does not match")
        if (
            Decimal(self.authorized_ceiling_usd) != HARD_CEILING
            or Decimal(self.conservative_estimate_usd)
            != Decimal(config.conservative_estimate_usd)
            or Decimal(self.contingency_percent) < Decimal("25")
            or self.resource_generation_count not in {0, 1}
            or self.image_generation_count not in {0, 1}
            or self.required_scan_count not in {0, 1}
            or self.image_scan_count not in {0, 1}
            or self.cleanup_disposition not in RESIDUE_DISPOSITIONS
            or (
                self.cleanup_arm_evidence_sha256 is not None
                and HASH_PATTERN.fullmatch(self.cleanup_arm_evidence_sha256) is None
            )
            or (
                self.residue_evidence_sha256 is not None
                and HASH_PATTERN.fullmatch(self.residue_evidence_sha256) is None
            )
            or (
                self.cleanup_disarm_evidence_sha256 is not None
                and HASH_PATTERN.fullmatch(self.cleanup_disarm_evidence_sha256) is None
            )
            or set(self.residue) != set(RESIDUE_KEYS)
            or any(
                not isinstance(value, int) or value < 0
                for value in self.residue.values()
            )
        ):
            raise CampaignError("resume ledger limits or counters are invalid")
        current = Phase.NEW
        reached: set[Phase] = set()
        for transition in self.transitions:
            if set(transition) != {"from", "to", "atUtc"}:
                raise CampaignError("resume transition is malformed")
            source = Phase(transition["from"])
            target = Phase(transition["to"])
            parse_utc(transition["atUtc"])
            if source is not current:
                raise CampaignError("resume transition chain is discontinuous")
            normal = ORDER.index(target) == ORDER.index(source) + 1
            cleanup_jump = target is Phase.CLEANING and ORDER.index(
                source
            ) >= ORDER.index(Phase.COST_GATED)
            if not normal and not cleanup_jump:
                raise CampaignError("resume transition chain is invalid")
            current = target
            reached.add(target)
        if self.phase != current.value:
            raise CampaignError("resume phase differs from its transition chain")
        if self.original_cleanup_deadline_utc is not None and (
            self.cleanup_deadline_utc != self.original_cleanup_deadline_utc
            or self.cleanup_deadline_utc != config.cleanup_deadline_utc
        ):
            raise CampaignError("resume cleanup deadline was substituted")
        billable_reached = Phase.BILLABLE_STARTED in reached
        if self.resource_generation_count != int(billable_reached):
            raise CampaignError("resume resource generation count is inconsistent")
        image_reached = Phase.IMAGE_DECIDED in reached
        if image_reached != (self.image_digest is not None):
            raise CampaignError("resume image state is inconsistent")
        if image_reached and (
            self.required_scan_count != 1
            or self.image_scan_count != 1
            or self.image_scan_evidence_sha256 is None
        ):
            raise CampaignError("resume image scan state is inconsistent")
        if (
            self.actual_cost_usd is not None
            and Decimal(self.actual_cost_usd) > HARD_CEILING
        ):
            raise CampaignError("resume actual cost exceeds the ceiling")
        cleanup_armed_reached = Phase.CLEANUP_ARMED in reached
        if cleanup_armed_reached != (self.cleanup_arm_evidence_sha256 is not None):
            raise CampaignError("resume cleanup arming evidence is inconsistent")
        cleanup_disarmed_reached = Phase.CLEANUP_DISARMED in reached
        if cleanup_disarmed_reached != (
            self.cleanup_disarm_evidence_sha256 is not None
        ):
            raise CampaignError("resume cleanup disarming evidence is inconsistent")
        residue_verified_reached = Phase.RESIDUE_VERIFIED in reached
        if residue_verified_reached != (
            self.cleanup_disposition == "zero-residue"
            and self.residue_evidence_sha256 is not None
            and not any(self.residue.values())
        ):
            raise CampaignError("resume residue disposition is inconsistent")

    def transition(
        self, target: Phase, now: datetime, *, scope_write_attempted: bool = False
    ) -> None:
        current = Phase(self.phase)
        valid = target is Phase.CLEANING and ORDER.index(current) >= ORDER.index(
            Phase.SCOPE_CREATED
        )
        if target is Phase.CLEANING and current is Phase.COST_GATED:
            valid = scope_write_attempted
        if not valid:
            valid = ORDER.index(target) == ORDER.index(current) + 1
        if not valid:
            raise CampaignError(f"invalid lifecycle transition: {current} -> {target}")
        if target is Phase.IMAGE_DECIDED and (
            self.image_digest is None
            or self.required_scan_count != 1
            or self.image_scan_count != 1
            or self.image_scan_evidence_sha256 is None
        ):
            raise CampaignError("image digest and one admission scan are required")
        if target is Phase.CLEANUP_ARMED and self.cleanup_arm_evidence_sha256 is None:
            raise CampaignError("cleanup arming evidence is required")
        if (
            target is Phase.CLEANUP_DISARMED
            and self.cleanup_disarm_evidence_sha256 is None
        ):
            raise CampaignError("cleanup disarming evidence is required")
        if target is Phase.RESIDUE_VERIFIED and (
            self.cleanup_disposition != "zero-residue"
            or self.residue_evidence_sha256 is None
            or any(self.residue.values())
        ):
            raise CampaignError("zero-residue evidence is required")
        self._assert_time(
            now,
            cleanup_transition=target
            in {
                Phase.CLEANING,
                Phase.CLEANED,
                Phase.CLEANUP_DISARMED,
                Phase.RESIDUE_VERIFIED,
                Phase.FINALIZED,
            },
        )
        self.transitions.append(
            {"from": current.value, "to": target.value, "atUtc": utc(now)}
        )
        self.phase = target.value
        if target is Phase.BILLABLE_STARTED:
            if self.resource_generation_count != 0:
                raise CampaignError("second resource generation rejected")
            self.resource_generation_count = 1
            self.first_billable_mutation_utc = utc(now)
        if target is Phase.CLEANING:
            self.cleanup_started_utc = utc(now)
        if target is Phase.CLEANED:
            self.cleanup_completed_utc = utc(now)

    def bind_deadline(self, deadline: str) -> None:
        parsed = parse_utc(deadline)
        if (
            self.original_cleanup_deadline_utc is not None
            and deadline != self.original_cleanup_deadline_utc
        ):
            raise CampaignError("cleanup deadline extension or substitution rejected")
        self.cleanup_deadline_utc = utc(parsed)
        self.original_cleanup_deadline_utc = utc(parsed)

    def record_image(self, digest: str, *, built: bool) -> None:
        if DIGEST_PATTERN.fullmatch(digest) is None:
            raise CampaignError("image digest is invalid")
        if self.image_digest is not None and self.image_digest != digest:
            raise CampaignError("second image digest rejected")
        if built:
            if self.image_generation_count != 0:
                raise CampaignError("second image generation rejected")
            self.image_generation_count = 1
        self.required_scan_count = 1
        self.image_digest = digest

    def record_image_scan(self, digest: str, evidence_sha256: str) -> None:
        if (
            digest != self.image_digest
            or HASH_PATTERN.fullmatch(evidence_sha256) is None
        ):
            raise CampaignError(
                "image admission scan is not bound to the selected digest"
            )
        if self.image_scan_count != 0:
            raise CampaignError("second image admission scan rejected")
        self.image_scan_count = 1
        self.image_scan_evidence_sha256 = evidence_sha256

    def record_cleanup_arm_evidence(self, evidence_sha256: str) -> None:
        if HASH_PATTERN.fullmatch(evidence_sha256) is None:
            raise CampaignError("cleanup arming evidence hash is invalid")
        if (
            self.cleanup_arm_evidence_sha256 is not None
            and self.cleanup_arm_evidence_sha256 != evidence_sha256
        ):
            raise CampaignError("cleanup arming evidence substitution rejected")
        self.cleanup_arm_evidence_sha256 = evidence_sha256

    def record_cleanup_disarm_evidence(self, evidence_sha256: str) -> None:
        if HASH_PATTERN.fullmatch(evidence_sha256) is None:
            raise CampaignError("cleanup disarming evidence hash is invalid")
        if (
            self.cleanup_disarm_evidence_sha256 is not None
            and self.cleanup_disarm_evidence_sha256 != evidence_sha256
        ):
            raise CampaignError("cleanup disarming evidence substitution rejected")
        self.cleanup_disarm_evidence_sha256 = evidence_sha256

    def record_residue(self, counters: dict[str, int], *, evidence_sha256: str) -> str:
        if set(counters) != set(RESIDUE_KEYS) or any(
            not isinstance(value, int) or value < 0 for value in counters.values()
        ):
            raise CampaignError("campaign residue is malformed or incomplete")
        if HASH_PATTERN.fullmatch(evidence_sha256) is None:
            raise CampaignError("campaign residue evidence hash is invalid")
        self.residue = counters.copy()
        self.residue_evidence_sha256 = evidence_sha256
        nonzero = {name for name, value in counters.items() if value != 0}
        if not nonzero:
            self.cleanup_disposition = "zero-residue"
        else:
            self.cleanup_disposition = "nonzero-residue"
        return self.cleanup_disposition

    def verify_residue(self, counters: dict[str, int]) -> None:
        evidence_sha256 = hashlib.sha256(
            b"m7.8/residue-counters/v1\0"
            + json.dumps(counters, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        if self.record_residue(counters, evidence_sha256=evidence_sha256) != (
            "zero-residue"
        ):
            raise CampaignError("campaign residue is nonzero")

    def _assert_time(self, now: datetime, *, cleanup_transition: bool = False) -> None:
        if (
            not cleanup_transition
            and self.cleanup_deadline_utc is not None
            and now >= parse_utc(self.cleanup_deadline_utc)
        ):
            raise CampaignError("cleanup deadline has expired")
        if not cleanup_transition and self.first_billable_mutation_utc is not None:
            started = parse_utc(self.first_billable_mutation_utc)
            if now > started + timedelta(hours=MAX_HOURS):
                raise CampaignError("four-hour lifecycle limit exceeded")


@dataclass(frozen=True, slots=True)
class CleanupBinding:
    campaign_id: str
    generation_id: str
    subscription_correlation: str
    target_resource_group: str
    cleanup_resource_group: str
    cleanup_principal_sha256: str
    deadline_utc: str
    ceiling_usd: str
    schedule_count: int
    binding_count: int
    cleanup_region: str
    cleanup_region_selection_sha256: str
    cleanup_candidate_regions: str
    cleanup_offer_classification: str
    cleanup_offer_eligibility_disposition: str
    cleanup_offer_eligible_regions: str
    cleanup_offer_eligibility_source: str
    cleanup_offer_eligibility_sha256: str
    fresh_controller_admission_evidence_sha256: str

    def validate(self, config: CampaignConfig) -> None:
        if (
            self.campaign_id != config.campaign_id
            or self.generation_id != config.generation_id
            or self.subscription_correlation != config.subscription_correlation
            or self.target_resource_group != config.target_resource_group
            or self.cleanup_resource_group != config.cleanup_resource_group
            or self.deadline_utc != config.cleanup_deadline_utc
            or Decimal(self.ceiling_usd) != HARD_CEILING
            or self.schedule_count != 0
            or self.binding_count != 0
            or HASH_PATTERN.fullmatch(self.cleanup_principal_sha256) is None
            or self.cleanup_region != config.cleanup_region
            or self.cleanup_region_selection_sha256
            != config.cleanup_region_selection_sha256
            or self.cleanup_candidate_regions != config.cleanup_candidate_regions
            or self.cleanup_offer_classification != config.cleanup_offer_classification
            or self.cleanup_offer_eligibility_disposition
            != config.cleanup_offer_eligibility_disposition
            or self.cleanup_offer_eligible_regions
            != config.cleanup_offer_eligible_regions
            or self.cleanup_offer_eligibility_source
            != config.cleanup_offer_eligibility_source
            or self.cleanup_offer_eligibility_sha256
            != config.cleanup_offer_eligibility_sha256
            or self.fresh_controller_admission_evidence_sha256
            != config.fresh_controller_admission_evidence_sha256
        ):
            raise CampaignError("cleanup binding readback is inconsistent")


class CommandRunner(Protocol):
    def run(self, command: tuple[str, ...]) -> dict[str, object]: ...


class SubprocessRunner:
    def __init__(
        self,
        *,
        azure_cli: AzureCliLauncher | None = None,
        timeout_seconds: int | float = 900,
        encoding: str = "utf-8",
    ) -> None:
        self._azure_cli = azure_cli
        self._timeout_seconds = timeout_seconds
        self._encoding = encoding

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        if command and command[0] == AZURE_CLI_TOKEN:
            try:
                if self._azure_cli is None:
                    self._azure_cli = AzureCliLauncher.resolve()
                completed = self._azure_cli.run(
                    command[1:],
                    timeout=self._timeout_seconds,
                    encoding=self._encoding,
                )
            except AzureCliError:
                raise
            except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
                raise AzureCliError("Azure CLI process failed safely") from exc
        else:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding=self._encoding,
                errors="strict",
                timeout=self._timeout_seconds,
                shell=False,
            )
        return {
            "exitCode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }


class SimulatedRunner:
    def __init__(self, *, fail_operation: str | None = None) -> None:
        self.fail_operation = fail_operation
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        if self.fail_operation and self.fail_operation in command:
            return {"exitCode": 1, "stdout": "", "stderr": "simulated failure"}
        return {"exitCode": 0, "stdout": "{}", "stderr": ""}


class Lifecycle:
    def __init__(
        self, config: CampaignConfig, ledger: Ledger, runner: CommandRunner
    ) -> None:
        config.validate()
        ledger.bind_cleanup_region(config)
        ledger.validate_resume(config)
        self.config = config
        self.ledger = ledger
        self.runner = runner

    def run_simulation(self, *, now: datetime) -> Ledger:
        self.ledger.bind_deadline(self.config.cleanup_deadline_utc)
        for phase in ORDER[1:]:
            if phase is Phase.CLEANUP_ARMED:
                self.ledger.record_cleanup_arm_evidence("c" * 64)
            if phase is Phase.IMAGE_DECIDED:
                self.ledger.record_image("sha256:" + "a" * 64, built=True)
                self.ledger.record_image_scan("sha256:" + "a" * 64, "b" * 64)
            if phase is Phase.RESIDUE_VERIFIED:
                self.ledger.verify_residue(dict.fromkeys(RESIDUE_KEYS, 0))
            if phase is Phase.CLEANUP_DISARMED:
                self.ledger.record_cleanup_disarm_evidence("d" * 64)
            self.ledger.transition(phase, now)
            now += timedelta(seconds=1)
        return self.ledger

    def fail_and_cleanup(self, failed_at: Phase, *, now: datetime) -> Ledger:
        self.ledger.bind_deadline(self.config.cleanup_deadline_utc)
        for phase in ORDER[1 : ORDER.index(failed_at) + 1]:
            if phase is Phase.CLEANUP_ARMED:
                self.ledger.record_cleanup_arm_evidence("c" * 64)
            if phase is Phase.RESIDUE_VERIFIED:
                self.ledger.verify_residue(dict.fromkeys(RESIDUE_KEYS, 0))
            if phase is Phase.CLEANUP_DISARMED:
                self.ledger.record_cleanup_disarm_evidence("d" * 64)
            if phase is Phase.IMAGE_DECIDED:
                self.ledger.record_image("sha256:" + "a" * 64, built=True)
                self.ledger.record_image_scan("sha256:" + "a" * 64, "b" * 64)
            self.ledger.transition(phase, now)
            now += timedelta(seconds=1)
        if ORDER.index(failed_at) >= ORDER.index(Phase.SCOPE_CREATED):
            current = Phase(self.ledger.phase)
            if ORDER.index(current) < ORDER.index(Phase.CLEANING):
                self.ledger.transition(Phase.CLEANING, now)
                current = Phase.CLEANING
                now += timedelta(seconds=1)
            if ORDER.index(current) < ORDER.index(Phase.CLEANED):
                self.ledger.transition(Phase.CLEANED, now)
                current = Phase.CLEANED
                now += timedelta(seconds=1)
            if ORDER.index(current) < ORDER.index(Phase.RESIDUE_VERIFIED):
                if ORDER.index(current) < ORDER.index(Phase.CLEANUP_DISARMED):
                    self.ledger.record_cleanup_disarm_evidence("d" * 64)
                    self.ledger.transition(Phase.CLEANUP_DISARMED, now)
                    current = Phase.CLEANUP_DISARMED
                    now += timedelta(seconds=1)
                self.ledger.verify_residue(dict.fromkeys(RESIDUE_KEYS, 0))
                self.ledger.transition(Phase.RESIDUE_VERIFIED, now)
                current = Phase.RESIDUE_VERIFIED
                now += timedelta(seconds=1)
            if ORDER.index(current) < ORDER.index(Phase.FINALIZED):
                self.ledger.transition(Phase.FINALIZED, now)
        return self.ledger


def sanitize(value: str, *, domain: str) -> str:
    return hashlib.sha256(f"m7.8/{domain}\0{value}".encode()).hexdigest()[:16]


def terminal_receipt(ledger: Ledger) -> dict[str, object]:
    if (
        Phase(ledger.phase) is not Phase.FINALIZED
        or ledger.cleanup_disposition != "zero-residue"
        or ledger.cleanup_disarm_evidence_sha256 is None
        or ledger.residue_evidence_sha256 is None
        or any(ledger.residue.values())
    ):
        raise CampaignError("terminal receipt requires finalized zero residue")
    return {
        "version": "m7.8-terminal-receipt-v7",
        "campaignCorrelation": sanitize(ledger.campaign_id, domain="campaign"),
        "generationCorrelation": sanitize(ledger.generation_id, domain="generation"),
        "resourceGenerationCount": ledger.resource_generation_count,
        "imageGenerationCount": ledger.image_generation_count,
        "cleanupCompletedUtc": ledger.cleanup_completed_utc,
        "cleanupRegion": ledger.cleanup_region,
        "cleanupRegionSelectionSha256": ledger.cleanup_region_selection_sha256,
        "cleanupCandidateRegions": ledger.cleanup_candidate_regions,
        "cleanupOfferClassification": ledger.cleanup_offer_classification,
        "cleanupOfferEligibilityDisposition": (
            ledger.cleanup_offer_eligibility_disposition
        ),
        "cleanupOfferEligibleRegions": ledger.cleanup_offer_eligible_regions,
        "cleanupOfferEligibilitySource": ledger.cleanup_offer_eligibility_source,
        "cleanupOfferEligibilitySha256": ledger.cleanup_offer_eligibility_sha256,
        "freshControllerAdmissionEvidenceSha256": (
            ledger.fresh_controller_admission_evidence_sha256
        ),
        "cleanupArmEvidenceSha256": ledger.cleanup_arm_evidence_sha256,
        "cleanupDisarmEvidenceSha256": ledger.cleanup_disarm_evidence_sha256,
        "cleanupDisposition": ledger.cleanup_disposition,
        "residueEvidenceSha256": ledger.residue_evidence_sha256,
        "residue": ledger.residue,
        "status": "zero-residue",
    }


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CampaignError("timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CampaignError("timestamp must be absolute UTC")
    return parsed.astimezone(UTC)


def utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise CampaignError("naive timestamps are forbidden")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load_ledger(path: Path, config: CampaignConfig) -> Ledger:
    if not path.exists():
        ledger = Ledger(
            config.campaign_id,
            config.generation_id,
            conservative_estimate_usd=config.conservative_estimate_usd,
        )
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        ledger = Ledger(**cast(dict[str, object], value))  # type: ignore[arg-type]
    ledger.bind_cleanup_region(config)
    ledger.validate_resume(config)
    return ledger


def save_ledger(path: Path, ledger: Ledger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".next")
    temporary.write_text(
        json.dumps(asdict(ledger), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Milestone 7.8 campaign lifecycle")
    parser.add_argument(
        "operation", choices=("validate", "simulate", "failure-matrix", "receipt")
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = CampaignConfig.from_json(args.config)
        ledger = load_ledger(args.ledger, config)
        lifecycle = Lifecycle(config, ledger, SimulatedRunner())
        now = datetime.now(UTC)
        if args.operation == "validate":
            output: object = {"status": "valid", "mutationAuthorized": False}
        elif args.operation == "simulate":
            output = terminal_receipt(lifecycle.run_simulation(now=now))
            save_ledger(args.ledger, ledger)
        elif args.operation == "failure-matrix":
            results = {}
            for phase in ORDER[1:-1]:
                candidate = Ledger(config.campaign_id, config.generation_id)
                result = Lifecycle(
                    config, candidate, SimulatedRunner()
                ).fail_and_cleanup(phase, now=now)
                results[phase.value] = result.phase
            output = {"status": "passed", "phases": results}
        else:
            output = terminal_receipt(ledger)
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
        return 0
    except (CampaignError, KeyError, TypeError, ValueError) as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
