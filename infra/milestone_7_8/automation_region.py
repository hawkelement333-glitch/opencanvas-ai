from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, cast

from infra.milestone_7_8.campaign import CampaignError, parse_utc, utc

CLEANUP_REGION_CANDIDATES: Final = (
    "eastus2",
    "southcentralus",
    "westus2",
    "westus",
    "eastus",
    "northeurope",
    "southeastasia",
)
CLEANUP_CANDIDATE_REGIONS_BINDING: Final = ",".join(CLEANUP_REGION_CANDIDATES)
RESTRICTED_OFFER_ELIGIBLE_REGIONS: Final = (
    "eastus",
    "eastus2",
    "northeurope",
    "southeastasia",
    "westus",
)
OFFER_ELIGIBLE_REGIONS_BINDING: Final = ",".join(RESTRICTED_OFFER_ELIGIBLE_REGIONS)
OFFER_ELIGIBILITY_SOURCE: Final = (
    "microsoft-automation-restricted-public-offer-regions-2026-08-v1"
)
RESTRICTED_OFFER_CLASSIFICATION: Final = "restricted-public-offer"
UNCLASSIFIED_OFFER_CLASSIFICATION: Final = "unclassified"
RESTRICTED_OFFER_DISPOSITION: Final = "restricted-offer-metadata-confirmed"
BASELINE_OFFER_DISPOSITION: Final = "restrictive-public-baseline-applied"
SELECTION_VERSION: Final = "m7.8-cleanup-region-selection-v5"
REGION_PATTERN: Final = re.compile(r"^[a-z][a-z0-9]{2,31}$")
DEFINITION_API_VERSION: Final = "2023-04-01"
DELETED_ACCOUNTS_API_VERSION: Final = "2024-10-23"
SUBSCRIPTION_API_VERSION: Final = "2020-01-01"
RESOURCES_API_VERSION: Final = "2021-04-01"


class RegionCommandRunner(Protocol):
    def run(self, command: tuple[str, ...]) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    region: str
    provider_supported: bool
    offer_eligible: bool
    policy_allowed: bool
    active_account_count: int
    adoptable_controller_count: int
    soft_deleted_account_count: int
    status: str


@dataclass(frozen=True, slots=True)
class OfferEligibility:
    classification: str
    disposition: str
    eligible_regions: tuple[str, ...]
    source: str
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class AutomationRegionSelection:
    version: str
    candidate_order: tuple[str, ...]
    selected_region: str
    provider_registration_state: str
    capacity_basis: str
    controller_disposition: str
    controller_region: str
    policy_assignment_count: int
    policy_definition_count: int
    provider_locations_sha256: str
    offer_classification: str
    offer_eligibility_disposition: str
    offer_eligible_regions: tuple[str, ...]
    offer_eligibility_source: str
    offer_eligibility_sha256: str
    active_occupancy_sha256: str
    soft_deleted_occupancy_sha256: str
    policy_evidence_sha256: str
    retention_absence_evidence_sha256: str
    observed_at_utc: str
    candidates: tuple[CandidateEvidence, ...]

    def validate(self) -> None:
        _validate_candidate_order(self.candidate_order)
        if (
            self.version != SELECTION_VERSION
            or self.provider_registration_state != "Registered"
            or self.capacity_basis
            != "provider-offer-policy-exact-controller-or-zero-occupancy"
            or self.controller_disposition
            not in {"controller-absent", "exact-controller-adoptable"}
            or (
                self.controller_disposition == "controller-absent"
                and self.controller_region != ""
            )
            or (
                self.controller_disposition == "exact-controller-adoptable"
                and REGION_PATTERN.fullmatch(self.controller_region) is None
            )
            or self.offer_eligible_regions != RESTRICTED_OFFER_ELIGIBLE_REGIONS
            or self.offer_eligibility_source != OFFER_ELIGIBILITY_SOURCE
            or (
                self.offer_classification,
                self.offer_eligibility_disposition,
            )
            not in {
                (
                    RESTRICTED_OFFER_CLASSIFICATION,
                    RESTRICTED_OFFER_DISPOSITION,
                ),
                (
                    UNCLASSIFIED_OFFER_CLASSIFICATION,
                    BASELINE_OFFER_DISPOSITION,
                ),
            }
            or type(self.policy_assignment_count) is not int
            or type(self.policy_definition_count) is not int
            or self.policy_assignment_count < 0
            or self.policy_definition_count < 0
            or any(
                re.fullmatch(r"[a-f0-9]{64}", value) is None
                for value in (
                    self.provider_locations_sha256,
                    self.offer_eligibility_sha256,
                    self.active_occupancy_sha256,
                    self.soft_deleted_occupancy_sha256,
                    self.policy_evidence_sha256,
                    self.retention_absence_evidence_sha256,
                )
            )
        ):
            raise CampaignError("Automation cleanup region selection is malformed")
        _parse_observed_at(self.observed_at_utc)
        if tuple(item.region for item in self.candidates) != self.candidate_order:
            raise CampaignError("Automation cleanup candidate evidence order differs")
        viable: list[str] = []
        allowed_statuses = {
            "viable",
            "unsupported",
            "offer-ineligible",
            "policy-disallowed",
            "occupied",
            "controller-region-mismatch",
        }
        for item in self.candidates:
            if (
                item.status not in allowed_statuses
                or type(item.provider_supported) is not bool
                or type(item.offer_eligible) is not bool
                or type(item.policy_allowed) is not bool
                or type(item.active_account_count) is not int
                or type(item.adoptable_controller_count) is not int
                or type(item.soft_deleted_account_count) is not int
                or item.active_account_count < 0
                or item.adoptable_controller_count not in {0, 1}
                or item.adoptable_controller_count > item.active_account_count
                or item.soft_deleted_account_count < 0
            ):
                raise CampaignError(
                    "Automation cleanup candidate evidence is malformed"
                )
            unrelated_active_count = (
                item.active_account_count - item.adoptable_controller_count
            )
            expected_status = (
                "unsupported"
                if not item.provider_supported
                else "offer-ineligible"
                if not item.offer_eligible
                else "policy-disallowed"
                if not item.policy_allowed
                else "occupied"
                if unrelated_active_count + item.soft_deleted_account_count > 0
                else "controller-region-mismatch"
                if self.controller_region and item.region != self.controller_region
                else "viable"
            )
            if item.status != expected_status:
                raise CampaignError(
                    "Automation cleanup candidate classification differs"
                )
            if item.status == "viable":
                viable.append(item.region)
        adoptable_count = sum(
            item.adoptable_controller_count for item in self.candidates
        )
        if (
            self.controller_disposition == "controller-absent" and adoptable_count != 0
        ) or (
            self.controller_disposition == "exact-controller-adoptable"
            and (
                adoptable_count != 1
                or next(
                    (
                        item.region
                        for item in self.candidates
                        if item.adoptable_controller_count == 1
                    ),
                    None,
                )
                != self.controller_region
            )
        ):
            raise CampaignError("Automation reusable controller evidence differs")
        if not viable:
            _raise_no_viable(self.candidates)
        if self.selected_region != viable[0]:
            raise CampaignError(
                "Automation cleanup region selection is not deterministic"
            )

    def document(self) -> dict[str, object]:
        self.validate()
        return {
            "version": self.version,
            "candidateOrder": list(self.candidate_order),
            "selectedRegion": self.selected_region,
            "providerRegistrationState": self.provider_registration_state,
            "capacityBasis": self.capacity_basis,
            "controllerDisposition": self.controller_disposition,
            "controllerRegion": self.controller_region,
            "policyAssignmentCount": self.policy_assignment_count,
            "policyDefinitionCount": self.policy_definition_count,
            "providerLocationsSha256": self.provider_locations_sha256,
            "offerClassification": self.offer_classification,
            "offerEligibilityDisposition": self.offer_eligibility_disposition,
            "offerEligibleRegions": list(self.offer_eligible_regions),
            "offerEligibilitySource": self.offer_eligibility_source,
            "offerEligibilitySha256": self.offer_eligibility_sha256,
            "activeOccupancySha256": self.active_occupancy_sha256,
            "softDeletedOccupancySha256": self.soft_deleted_occupancy_sha256,
            "policyEvidenceSha256": self.policy_evidence_sha256,
            "retentionAbsenceEvidenceSha256": self.retention_absence_evidence_sha256,
            "observedAtUtc": self.observed_at_utc,
            "candidates": [
                {
                    "region": item.region,
                    "providerSupported": item.provider_supported,
                    "offerEligible": item.offer_eligible,
                    "policyAllowed": item.policy_allowed,
                    "activeAccountCount": item.active_account_count,
                    "adoptableControllerCount": item.adoptable_controller_count,
                    "softDeletedAccountCount": item.soft_deleted_account_count,
                    "status": item.status,
                }
                for item in self.candidates
            ],
        }

    def sha256(self) -> str:
        document = self.document()
        # Observation time is retained in the receipt but excluded from the
        # replay binding so an immediate capacity-check can prove the exact
        # decision and every evidence hash at a later timestamp.
        document.pop("observedAtUtc")
        encoded = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(
            b"m7.8/cleanup-region-selection/v4\0" + encoded
        ).hexdigest()


def selection_from_document(value: object) -> AutomationRegionSelection:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "candidateOrder",
        "selectedRegion",
        "providerRegistrationState",
        "capacityBasis",
        "controllerDisposition",
        "controllerRegion",
        "policyAssignmentCount",
        "policyDefinitionCount",
        "providerLocationsSha256",
        "offerClassification",
        "offerEligibilityDisposition",
        "offerEligibleRegions",
        "offerEligibilitySource",
        "offerEligibilitySha256",
        "activeOccupancySha256",
        "softDeletedOccupancySha256",
        "policyEvidenceSha256",
        "retentionAbsenceEvidenceSha256",
        "observedAtUtc",
        "candidates",
    }:
        raise CampaignError("Automation cleanup region receipt fields are invalid")
    raw_candidates = value["candidates"]
    if (
        not isinstance(value["candidateOrder"], list)
        or not isinstance(value["offerEligibleRegions"], list)
        or not isinstance(raw_candidates, list)
    ):
        raise CampaignError("Automation cleanup region receipt arrays are invalid")
    candidates: list[CandidateEvidence] = []
    for item in raw_candidates:
        if not isinstance(item, dict) or set(item) != {
            "region",
            "providerSupported",
            "offerEligible",
            "policyAllowed",
            "activeAccountCount",
            "adoptableControllerCount",
            "softDeletedAccountCount",
            "status",
        }:
            raise CampaignError(
                "Automation cleanup candidate receipt fields are invalid"
            )
        candidates.append(
            CandidateEvidence(
                region=cast(str, item["region"]),
                provider_supported=cast(bool, item["providerSupported"]),
                offer_eligible=cast(bool, item["offerEligible"]),
                policy_allowed=cast(bool, item["policyAllowed"]),
                active_account_count=cast(int, item["activeAccountCount"]),
                adoptable_controller_count=cast(int, item["adoptableControllerCount"]),
                soft_deleted_account_count=cast(int, item["softDeletedAccountCount"]),
                status=cast(str, item["status"]),
            )
        )
    selection = AutomationRegionSelection(
        version=cast(str, value["version"]),
        candidate_order=tuple(cast(list[str], value["candidateOrder"])),
        selected_region=cast(str, value["selectedRegion"]),
        provider_registration_state=cast(str, value["providerRegistrationState"]),
        capacity_basis=cast(str, value["capacityBasis"]),
        controller_disposition=cast(str, value["controllerDisposition"]),
        controller_region=cast(str, value["controllerRegion"]),
        policy_assignment_count=cast(int, value["policyAssignmentCount"]),
        policy_definition_count=cast(int, value["policyDefinitionCount"]),
        provider_locations_sha256=cast(str, value["providerLocationsSha256"]),
        offer_classification=cast(str, value["offerClassification"]),
        offer_eligibility_disposition=cast(str, value["offerEligibilityDisposition"]),
        offer_eligible_regions=tuple(cast(list[str], value["offerEligibleRegions"])),
        offer_eligibility_source=cast(str, value["offerEligibilitySource"]),
        offer_eligibility_sha256=cast(str, value["offerEligibilitySha256"]),
        active_occupancy_sha256=cast(str, value["activeOccupancySha256"]),
        soft_deleted_occupancy_sha256=cast(str, value["softDeletedOccupancySha256"]),
        policy_evidence_sha256=cast(str, value["policyEvidenceSha256"]),
        retention_absence_evidence_sha256=cast(
            str, value["retentionAbsenceEvidenceSha256"]
        ),
        observed_at_utc=cast(str, value["observedAtUtc"]),
        candidates=tuple(candidates),
    )
    selection.validate()
    return selection


def automation_region_discovery_commands(
    subscription_id: str,
) -> tuple[tuple[str, ...], ...]:
    if not subscription_id:
        raise CampaignError("Automation cleanup subscription binding is absent")
    try:
        parsed_subscription = uuid.UUID(subscription_id)
    except ValueError as exc:
        raise CampaignError(
            "automation-region-malformed-unknown: subscription binding is malformed"
        ) from exc
    if parsed_subscription.int == 0:
        raise CampaignError(
            "automation-region-malformed-unknown: subscription binding is malformed"
        )
    subscription_url = (
        "https://management.azure.com/subscriptions/"
        + subscription_id
        + f"?api-version={SUBSCRIPTION_API_VERSION}"
    )
    active_url = (
        "https://management.azure.com/subscriptions/"
        + subscription_id
        + "/resources"
        + f"?api-version={RESOURCES_API_VERSION}"
        + "&$filter=resourceType%20eq%20"
        + "%27Microsoft.Automation%2FautomationAccounts%27"
    )
    deleted_url = (
        "https://management.azure.com/subscriptions/"
        + subscription_id
        + "/providers/Microsoft.Automation/deletedAutomationAccounts"
        + f"?api-version={DELETED_ACCOUNTS_API_VERSION}"
    )
    return (
        (
            "az",
            "account",
            "show",
            "--subscription",
            subscription_id,
            "--query",
            "{environmentName:environmentName,state:state}",
            "--output",
            "json",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            subscription_url,
            "--query",
            "{subscriptionPolicies:subscriptionPolicies}",
            "--output",
            "json",
        ),
        (
            "az",
            "provider",
            "show",
            "--namespace",
            "Microsoft.Automation",
            "--subscription",
            subscription_id,
            "--output",
            "json",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            active_url,
            "--query",
            "{accounts:value[].{id:id,name:name,resourceGroup:resourceGroup,"
            "location:location,tags:tags},nextLink:nextLink}",
            "--output",
            "json",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            deleted_url,
            "--query",
            "{accounts:value[].{location:Location},nextLink:nextLink}",
            "--output",
            "json",
        ),
        (
            "az",
            "policy",
            "assignment",
            "list",
            "--scope",
            f"/subscriptions/{subscription_id}",
            "--disable-scope-strict-match",
            "--query",
            "[].{enforcementMode:enforcementMode,parameters:parameters,"
            "policyDefinitionId:policyDefinitionId}",
            "--output",
            "json",
        ),
    )


def generated_policy_read_contract() -> tuple[str, ...]:
    return (
        "one GET per enforced policy assignment definition",
        "one GET per deny-capable initiative member definition",
    )


def discover_automation_region(
    runner: RegionCommandRunner,
    subscription_id: str,
    *,
    observed_at: datetime | None = None,
    candidate_order: tuple[str, ...] = CLEANUP_REGION_CANDIDATES,
    controller_resource_group: str | None = None,
    controller_account: str | None = None,
    subscription_correlation: str | None = None,
    cleanup_script_sha256: str | None = None,
    retention_absence_evidence_sha256: str | None = None,
    controller_required_until_utc: str | None = None,
) -> AutomationRegionSelection:
    results = tuple(
        _run_required(runner, command)
        for command in automation_region_discovery_commands(subscription_id)
    )
    return select_automation_region_from_results(
        runner,
        results,
        observed_at=observed_at,
        candidate_order=candidate_order,
        controller_resource_group=controller_resource_group,
        controller_account=controller_account,
        subscription_correlation=subscription_correlation,
        cleanup_script_sha256=cleanup_script_sha256,
        retention_absence_evidence_sha256=retention_absence_evidence_sha256,
        controller_required_until_utc=controller_required_until_utc,
    )


def select_automation_region_from_results(
    runner: RegionCommandRunner,
    results: tuple[dict[str, object], ...],
    *,
    observed_at: datetime | None = None,
    candidate_order: tuple[str, ...] = CLEANUP_REGION_CANDIDATES,
    controller_resource_group: str | None = None,
    controller_account: str | None = None,
    subscription_correlation: str | None = None,
    cleanup_script_sha256: str | None = None,
    retention_absence_evidence_sha256: str | None = None,
    controller_required_until_utc: str | None = None,
) -> AutomationRegionSelection:
    _validate_candidate_order(candidate_order)
    if len(results) != 6:
        raise CampaignError("Automation cleanup regional discovery is incomplete")
    account = _json_result(results[0])
    subscription = _json_result(results[1])
    provider = _json_result(results[2])
    active = _json_result(results[3])
    deleted = _json_result(results[4])
    assignments = _json_result(results[5])
    if not isinstance(account, dict) or account != {
        "environmentName": "AzureCloud",
        "state": "Enabled",
    }:
        raise CampaignError(
            "automation-region-discovery-failed: Azure subscription context is unavailable"
        )
    if (
        not isinstance(provider, dict)
        or provider.get("registrationState") != "Registered"
    ):
        raise CampaignError("Automation provider registration is unavailable")
    resource_types = provider.get("resourceTypes")
    if not isinstance(resource_types, list):
        raise CampaignError("Automation provider region discovery is malformed")
    account_type = next(
        (
            item
            for item in resource_types
            if isinstance(item, dict)
            and str(item.get("resourceType", "")).casefold() == "automationaccounts"
        ),
        None,
    )
    locations = (
        account_type.get("locations") if isinstance(account_type, dict) else None
    )
    supported = _normalized_region_set(locations, label="provider")
    offer = _subscription_offer_eligibility(subscription)
    active_accounts = _complete_account_inventory(active, label="active")
    deleted_accounts = _complete_account_inventory(deleted, label="soft-deleted")
    controller_region = _adoptable_controller_region(
        active_accounts,
        controller_resource_group=controller_resource_group,
        controller_account=controller_account,
        subscription_correlation=subscription_correlation,
        cleanup_script_sha256=cleanup_script_sha256,
        retention_absence_evidence_sha256=retention_absence_evidence_sha256,
        controller_required_until_utc=controller_required_until_utc,
    )
    active_counts = _location_counts(
        active_accounts, supported=supported, label="active"
    )
    deleted_counts = _location_counts(
        deleted_accounts, supported=supported, label="soft-deleted"
    )
    if not isinstance(assignments, list):
        raise CampaignError("Automation location policy discovery is malformed")
    policy_allowed, definition_count, policy_evidence_sha256 = _policy_allowance(
        runner,
        assignments,
        candidate_order=candidate_order,
    )
    evidence: list[CandidateEvidence] = []
    offer_eligible = set(offer.eligible_regions)
    for region in candidate_order:
        provider_supported = region in supported
        subscription_offer_eligible = region in offer_eligible
        allowed = policy_allowed[region]
        active_count = active_counts.get(region, 0)
        adoptable_controller_count = int(controller_region == region)
        deleted_count = deleted_counts.get(region, 0)
        status = (
            "unsupported"
            if not provider_supported
            else "offer-ineligible"
            if not subscription_offer_eligible
            else "policy-disallowed"
            if not allowed
            else "occupied"
            if active_count - adoptable_controller_count + deleted_count > 0
            else "controller-region-mismatch"
            if controller_region and region != controller_region
            else "viable"
        )
        evidence.append(
            CandidateEvidence(
                region=region,
                provider_supported=provider_supported,
                offer_eligible=subscription_offer_eligible,
                policy_allowed=allowed,
                active_account_count=active_count,
                adoptable_controller_count=adoptable_controller_count,
                soft_deleted_account_count=deleted_count,
                status=status,
            )
        )
    viable = [item.region for item in evidence if item.status == "viable"]
    if not viable:
        _raise_no_viable(tuple(evidence))
    selection = AutomationRegionSelection(
        version=SELECTION_VERSION,
        candidate_order=candidate_order,
        selected_region=viable[0],
        provider_registration_state="Registered",
        capacity_basis="provider-offer-policy-exact-controller-or-zero-occupancy",
        controller_disposition=(
            "exact-controller-adoptable" if controller_region else "controller-absent"
        ),
        controller_region=controller_region or "",
        policy_assignment_count=len(assignments),
        policy_definition_count=definition_count,
        provider_locations_sha256=_evidence_hash(
            "provider-locations", sorted(supported)
        ),
        offer_classification=offer.classification,
        offer_eligibility_disposition=offer.disposition,
        offer_eligible_regions=offer.eligible_regions,
        offer_eligibility_source=offer.source,
        offer_eligibility_sha256=offer.evidence_sha256,
        active_occupancy_sha256=_evidence_hash("active-occupancy", active_counts),
        soft_deleted_occupancy_sha256=_evidence_hash(
            "soft-deleted-occupancy", deleted_counts
        ),
        policy_evidence_sha256=policy_evidence_sha256,
        retention_absence_evidence_sha256=(
            retention_absence_evidence_sha256 or "0" * 64
        ),
        observed_at_utc=utc(observed_at or datetime.now(UTC)),
        candidates=tuple(evidence),
    )
    selection.validate()
    return selection


def _validate_candidate_order(candidate_order: tuple[str, ...]) -> None:
    if candidate_order != CLEANUP_REGION_CANDIDATES:
        raise CampaignError(
            "automation-region-malformed-unknown: candidate order is not the reviewed contract"
        )
    if not set(RESTRICTED_OFFER_ELIGIBLE_REGIONS).issubset(candidate_order):
        raise CampaignError(
            "automation-region-malformed-unknown: offer-safe candidate is absent"
        )
    normalized = tuple(_normalize_region(item) for item in candidate_order)
    if normalized != candidate_order or len(set(normalized)) != len(normalized):
        raise CampaignError(
            "automation-region-malformed-unknown: candidate order is malformed or duplicated"
        )


def _normalize_region(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignError(
            "automation-region-malformed-unknown: location is malformed"
        )
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if REGION_PATTERN.fullmatch(normalized) is None:
        raise CampaignError(
            "automation-region-malformed-unknown: location is malformed"
        )
    return normalized


def _normalized_region_set(value: object, *, label: str) -> set[str]:
    if not isinstance(value, list) or not value:
        raise CampaignError(f"Automation {label} location discovery is incomplete")
    return {_normalize_region(item) for item in value}


def _subscription_offer_eligibility(value: object) -> OfferEligibility:
    policies = value.get("subscriptionPolicies") if isinstance(value, dict) else None
    quota = policies.get("quotaId") if isinstance(policies, dict) else None
    normalized_quota = (
        re.sub(r"[^a-z0-9]", "", quota.casefold()) if isinstance(quota, str) else ""
    )
    restricted_signal = any(
        marker in normalized_quota for marker in ("freetrial", "student")
    )
    classification = (
        RESTRICTED_OFFER_CLASSIFICATION
        if restricted_signal
        else UNCLASSIFIED_OFFER_CLASSIFICATION
    )
    disposition = (
        RESTRICTED_OFFER_DISPOSITION
        if restricted_signal
        else BASELINE_OFFER_DISPOSITION
    )
    material = {
        "subscriptionMetadata": value,
        "classification": classification,
        "disposition": disposition,
        "eligibleRegions": list(RESTRICTED_OFFER_ELIGIBLE_REGIONS),
        "source": OFFER_ELIGIBILITY_SOURCE,
        # The documented JapanWest2 token normalizes to japanwest2, while current
        # provider evidence exposes Japan West as japanwest. No alias is guessed.
        "excludedUnresolvedRegionAliases": ["japanwest2"],
    }
    return OfferEligibility(
        classification=classification,
        disposition=disposition,
        eligible_regions=RESTRICTED_OFFER_ELIGIBLE_REGIONS,
        source=OFFER_ELIGIBILITY_SOURCE,
        evidence_sha256=_evidence_hash("offer-eligibility", material),
    )


def _complete_account_inventory(value: object, *, label: str) -> list[object]:
    if (
        not isinstance(value, dict)
        or set(value) != {"accounts", "nextLink"}
        or not isinstance(value["accounts"], list)
        or (value["nextLink"] is not None and value["nextLink"] != "")
    ):
        raise CampaignError(
            f"automation-region-discovery-failed: {label} account inventory is incomplete"
        )
    return cast(list[object], value["accounts"])


def _adoptable_controller_region(
    accounts: list[object],
    *,
    controller_resource_group: str | None,
    controller_account: str | None,
    subscription_correlation: str | None,
    cleanup_script_sha256: str | None,
    retention_absence_evidence_sha256: str | None,
    controller_required_until_utc: str | None,
) -> str | None:
    expected = (
        controller_resource_group,
        controller_account,
        subscription_correlation,
        cleanup_script_sha256,
        retention_absence_evidence_sha256,
    )
    if all(value is None for value in expected):
        return None
    if any(value is None for value in expected):
        raise CampaignError("reusable Automation controller expectation is incomplete")
    if (
        re.fullmatch(
            r"^rg-m78-controller-[a-f0-9]{10}$", str(controller_resource_group)
        )
        is None
        or re.fullmatch(r"^aa-m78-controller-[a-f0-9]{10}$", str(controller_account))
        is None
        or re.fullmatch(r"^[a-f0-9]{16}$", str(subscription_correlation)) is None
        or re.fullmatch(r"^[a-f0-9]{64}$", str(cleanup_script_sha256)) is None
        or re.fullmatch(r"^[a-f0-9]{64}$", str(retention_absence_evidence_sha256))
        is None
        or controller_resource_group
        != f"rg-m78-controller-{str(subscription_correlation)[:10]}"
        or controller_account
        != f"aa-m78-controller-{str(subscription_correlation)[:10]}"
    ):
        raise CampaignError("reusable Automation controller expectation is malformed")
    matches = [
        item
        for item in accounts
        if isinstance(item, dict)
        and (
            item.get("name") == controller_account
            or item.get("resourceGroup") == controller_resource_group
        )
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise CampaignError("reusable Automation controller identity is ambiguous")
    match = matches[0]
    tags = match.get("tags")
    expected_tags = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": "reusable-automation-controller-v1",
        "mobius.subscription-correlation": subscription_correlation,
        "mobius.cleanup-script-sha256": cleanup_script_sha256,
        "mobius.retention-absence-sha256": retention_absence_evidence_sha256,
    }
    resource_id = match.get("id")
    expected_suffix = (
        f"/resourcegroups/{controller_resource_group}/providers/microsoft.automation/"
        f"automationaccounts/{controller_account}"
    ).casefold()
    if (
        match.get("name") != controller_account
        or match.get("resourceGroup") != controller_resource_group
        or not isinstance(resource_id, str)
        or not resource_id.casefold().endswith(expected_suffix)
        or not isinstance(tags, dict)
        or any(tags.get(key) != value for key, value in expected_tags.items())
        or not isinstance(tags.get("mobius.controller-authorized-until-utc"), str)
    ):
        raise CampaignError("reusable Automation controller identity or tags drifted")
    try:
        authorized_until = parse_utc(
            str(tags["mobius.controller-authorized-until-utc"])
        )
    except CampaignError as exc:
        raise CampaignError(
            "reusable Automation controller authorization is malformed"
        ) from exc
    if controller_required_until_utc is not None and authorized_until < parse_utc(
        controller_required_until_utc
    ):
        raise CampaignError("reusable Automation controller authority is insufficient")
    return _normalize_region(match.get("location"))


def _location_counts(
    value: object,
    *,
    supported: set[str],
    label: str,
) -> dict[str, int]:
    if not isinstance(value, list):
        raise CampaignError(f"Automation {label} account discovery is incomplete")
    counts: dict[str, int] = {}
    for item in value:
        raw_location = item.get("location") if isinstance(item, dict) else item
        location = _normalize_region(raw_location)
        if location not in supported:
            raise CampaignError(
                f"automation-region-malformed-unknown: {label} account location is unknown"
            )
        counts[location] = counts.get(location, 0) + 1
    return counts


def _policy_allowance(
    runner: RegionCommandRunner,
    assignments: list[object],
    *,
    candidate_order: tuple[str, ...],
) -> tuple[dict[str, bool], int, str]:
    allowed = dict.fromkeys(candidate_order, True)
    definition_cache: dict[str, dict[str, object]] = {}
    inspected: set[str] = set()
    for raw_assignment in assignments:
        if not isinstance(raw_assignment, dict):
            raise CampaignError("Automation location policy assignment is malformed")
        if raw_assignment.get("enforcementMode") == "DoNotEnforce":
            continue
        definition_id = raw_assignment.get("policyDefinitionId")
        parameters = raw_assignment.get("parameters") or {}
        if not isinstance(definition_id, str) or not definition_id.startswith("/"):
            raise CampaignError(
                "Automation location policy definition binding is malformed"
            )
        if not isinstance(parameters, dict):
            raise CampaignError("Automation location policy parameters are malformed")
        definition = _read_definition(runner, definition_id, definition_cache)
        inspected.add(definition_id.casefold())
        for policy, bound_parameters, child_id in _expanded_policies(
            runner,
            definition,
            assignment_parameters=parameters,
            definition_cache=definition_cache,
        ):
            if child_id is not None:
                inspected.add(child_id.casefold())
            rule = policy.get("policyRule")
            definition_parameters = policy.get("parameters") or {}
            if not isinstance(rule, dict) or not isinstance(
                definition_parameters, dict
            ):
                raise CampaignError(
                    "Automation location policy definition is malformed"
                )
            resolved_parameters = _resolved_definition_parameters(
                definition_parameters,
                bound_parameters,
            )
            effect = _resolve_value(
                rule.get("then", {}).get("effect"), resolved_parameters
            )
            if not isinstance(effect, str):
                raise CampaignError("Automation location policy effect is unresolved")
            if effect.casefold() != "deny":
                continue
            condition = rule.get("if")
            if not _condition_references_location(condition):
                continue
            for region in candidate_order:
                result = _evaluate_condition(
                    condition,
                    fields={
                        "location": region,
                        "type": "Microsoft.Automation/automationAccounts",
                    },
                    parameters=resolved_parameters,
                )
                if result is None:
                    raise CampaignError(
                        "automation-region-discovery-failed: location policy cannot be evaluated safely"
                    )
                if result:
                    allowed[region] = False
    canonical_assignments = sorted(
        assignments,
        key=lambda item: json.dumps(item, separators=(",", ":"), sort_keys=True),
    )
    policy_material = {
        "assignments": canonical_assignments,
        "definitions": {key: definition_cache[key] for key in sorted(definition_cache)},
    }
    return (
        allowed,
        len(inspected),
        _evidence_hash("policy", policy_material),
    )


def _read_definition(
    runner: RegionCommandRunner,
    definition_id: str,
    cache: dict[str, dict[str, object]],
) -> dict[str, object]:
    key = definition_id.casefold()
    if key in cache:
        return cache[key]
    url = (
        "https://management.azure.com"
        + definition_id
        + f"?api-version={DEFINITION_API_VERSION}"
    )
    value = _json_result(
        _run_required(
            runner,
            ("az", "rest", "--method", "get", "--url", url, "--output", "json"),
        )
    )
    properties = value.get("properties") if isinstance(value, dict) else None
    if not isinstance(properties, dict):
        raise CampaignError("Automation location policy definition is malformed")
    cache[key] = cast(dict[str, object], properties)
    return cache[key]


def _expanded_policies(
    runner: RegionCommandRunner,
    definition: dict[str, object],
    *,
    assignment_parameters: dict[str, object],
    definition_cache: dict[str, dict[str, object]],
) -> tuple[tuple[dict[str, object], dict[str, object], str | None], ...]:
    if isinstance(definition.get("policyRule"), dict):
        return ((definition, assignment_parameters, None),)
    members = definition.get("policyDefinitions")
    initiative_parameters = definition.get("parameters") or {}
    if not isinstance(members, list) or not isinstance(initiative_parameters, dict):
        raise CampaignError("Automation location policy initiative is malformed")
    parent_values = _resolved_definition_parameters(
        initiative_parameters, assignment_parameters
    )
    expanded: list[tuple[dict[str, object], dict[str, object], str | None]] = []
    for member in members:
        if not isinstance(member, dict):
            raise CampaignError(
                "Automation location policy initiative member is malformed"
            )
        child_id = member.get("policyDefinitionId")
        bindings = member.get("parameters") or {}
        if (
            not isinstance(child_id, str)
            or not child_id.startswith("/")
            or not isinstance(bindings, dict)
        ):
            raise CampaignError(
                "Automation location policy initiative member is malformed"
            )
        child_values: dict[str, dict[str, object]] = {
            key: {"value": _resolve_value(item.get("value"), parent_values)}
            for key, item in bindings.items()
            if isinstance(key, str)
            and isinstance(item, dict)
            and set(item) == {"value"}
        }
        if len(child_values) != len(bindings):
            raise CampaignError(
                "Automation location policy initiative binding is malformed"
            )
        effect_values = [
            item["value"]
            for key, item in child_values.items()
            if "effect" in key.casefold()
        ]
        if effect_values and all(
            isinstance(value, str) and value.casefold() != "deny"
            for value in effect_values
        ):
            continue
        child = _read_definition(runner, child_id, definition_cache)
        expanded.append((child, cast(dict[str, object], child_values), child_id))
    return tuple(expanded)


def _resolved_definition_parameters(
    definitions: dict[str, object],
    bindings: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    unknown_bindings = set(bindings) - set(definitions)
    if unknown_bindings:
        raise CampaignError("Automation location policy has unknown parameter bindings")
    for name, definition in definitions.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            raise CampaignError(
                "Automation location policy parameter definition is malformed"
            )
        bound = bindings.get(name)
        if bound is not None:
            if not isinstance(bound, dict) or set(bound) != {"value"}:
                raise CampaignError(
                    "Automation location policy parameter binding is malformed"
                )
            result[name] = bound["value"]
        elif "defaultValue" in definition:
            result[name] = definition["defaultValue"]
        else:
            raise CampaignError("Automation location policy parameter is unresolved")
    return result


def _resolve_value(value: object, parameters: dict[str, object]) -> object:
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\[parameters\('([^']+)'\)\]", value, flags=re.IGNORECASE)
    if match is None:
        return value
    name = match.group(1)
    if name not in parameters:
        raise CampaignError(
            "Automation location policy parameter reference is unresolved"
        )
    return parameters[name]


def _condition_references_location(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "field" and isinstance(item, str) and item.casefold() == "location")
            or _condition_references_location(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_condition_references_location(item) for item in value)
    return False


def _evaluate_condition(
    value: object,
    *,
    fields: dict[str, object],
    parameters: dict[str, object],
) -> bool | None:
    if not isinstance(value, dict):
        return None
    if set(value) == {"allOf"} and isinstance(value["allOf"], list):
        results = [
            _evaluate_condition(item, fields=fields, parameters=parameters)
            for item in value["allOf"]
        ]
        if False in results:
            return False
        return True if all(item is True for item in results) else None
    if set(value) == {"anyOf"} and isinstance(value["anyOf"], list):
        results = [
            _evaluate_condition(item, fields=fields, parameters=parameters)
            for item in value["anyOf"]
        ]
        if True in results:
            return True
        return False if all(item is False for item in results) else None
    if set(value) == {"not"}:
        result = _evaluate_condition(value["not"], fields=fields, parameters=parameters)
        return None if result is None else not result
    field_name = value.get("field")
    if not isinstance(field_name, str) or field_name.casefold() not in fields:
        return None
    operators = set(value) - {"field"}
    if len(operators) != 1:
        return None
    operator = next(iter(operators))
    expected = _resolve_value(value[operator], parameters)
    actual = fields[field_name.casefold()]
    normalize = _normalize_policy_value
    if operator in {"equals", "notEquals"}:
        result = normalize(actual) == normalize(expected)
        return result if operator == "equals" else not result
    if operator in {"in", "notIn"} and isinstance(expected, list):
        result = normalize(actual) in {normalize(item) for item in expected}
        return result if operator == "in" else not result
    if operator == "exists" and type(expected) is bool:
        return expected
    return None


def _normalize_policy_value(value: object) -> object:
    return value.casefold().replace(" ", "") if isinstance(value, str) else value


def _evidence_hash(domain: str, value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(
        f"m7.8/automation-{domain}/v1\0".encode() + encoded
    ).hexdigest()


def _run_required(
    runner: RegionCommandRunner,
    command: tuple[str, ...],
) -> dict[str, object]:
    result = runner.run(command)
    if result.get("exitCode") != 0:
        raise CampaignError(
            "automation-region-discovery-failed: regional discovery command failed safely"
        )
    return result


def _json_result(result: dict[str, object]) -> object:
    raw = result.get("stdout")
    if not isinstance(raw, str):
        raise CampaignError(
            "Automation cleanup regional discovery output is unavailable"
        )
    try:
        return cast(object, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise CampaignError(
            "Automation cleanup regional discovery output is malformed"
        ) from exc


def _parse_observed_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CampaignError(
            "Automation cleanup region observation time is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CampaignError("Automation cleanup region observation time is invalid")
    return parsed.astimezone(UTC)


def _raise_no_viable(candidates: tuple[CandidateEvidence, ...]) -> None:
    statuses = {item.status for item in candidates}
    if statuses == {"unsupported"}:
        code = "automation-region-unsupported"
    elif (
        statuses <= {"unsupported", "offer-ineligible"}
        and "offer-ineligible" in statuses
    ):
        code = "automation-region-offer-ineligible"
    elif (
        statuses <= {"unsupported", "offer-ineligible", "policy-disallowed"}
        and "policy-disallowed" in statuses
    ):
        code = "automation-region-policy-disallowed"
    else:
        code = "automation-region-occupied-capacity-unproved"
    disposition = ",".join(f"{item.region}:{item.status}" for item in candidates)
    raise CampaignError(
        f"{code}: no reviewed cleanup region is armable; candidates={disposition}"
    )
