from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, cast

from infra.milestone_7_8.campaign import CampaignError, utc

CLEANUP_REGION_CANDIDATES: Final = (
    "eastus2",
    "southcentralus",
    "westus2",
    "westus",
)
SELECTION_VERSION: Final = "m7.8-cleanup-region-selection-v1"
REGION_PATTERN: Final = re.compile(r"^[a-z][a-z0-9]{2,31}$")
DEFINITION_API_VERSION: Final = "2023-04-01"
DELETED_ACCOUNTS_API_VERSION: Final = "2024-10-23"


class RegionCommandRunner(Protocol):
    def run(self, command: tuple[str, ...]) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    region: str
    provider_supported: bool
    policy_allowed: bool
    active_account_count: int
    soft_deleted_account_count: int
    status: str


@dataclass(frozen=True, slots=True)
class AutomationRegionSelection:
    version: str
    candidate_order: tuple[str, ...]
    selected_region: str
    provider_registration_state: str
    capacity_basis: str
    policy_assignment_count: int
    policy_definition_count: int
    provider_locations_sha256: str
    active_occupancy_sha256: str
    soft_deleted_occupancy_sha256: str
    policy_evidence_sha256: str
    observed_at_utc: str
    candidates: tuple[CandidateEvidence, ...]

    def validate(self) -> None:
        _validate_candidate_order(self.candidate_order)
        if (
            self.version != SELECTION_VERSION
            or self.provider_registration_state != "Registered"
            or self.capacity_basis
            != "provider-policy-zero-active-and-soft-deleted-accounts"
            or type(self.policy_assignment_count) is not int
            or type(self.policy_definition_count) is not int
            or self.policy_assignment_count < 0
            or self.policy_definition_count < 0
            or any(
                re.fullmatch(r"[a-f0-9]{64}", value) is None
                for value in (
                    self.provider_locations_sha256,
                    self.active_occupancy_sha256,
                    self.soft_deleted_occupancy_sha256,
                    self.policy_evidence_sha256,
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
            "policy-disallowed",
            "occupied",
        }
        for item in self.candidates:
            if (
                item.status not in allowed_statuses
                or type(item.provider_supported) is not bool
                or type(item.policy_allowed) is not bool
                or type(item.active_account_count) is not int
                or type(item.soft_deleted_account_count) is not int
                or item.active_account_count < 0
                or item.soft_deleted_account_count < 0
            ):
                raise CampaignError(
                    "Automation cleanup candidate evidence is malformed"
                )
            expected_status = (
                "unsupported"
                if not item.provider_supported
                else "policy-disallowed"
                if not item.policy_allowed
                else "occupied"
                if item.active_account_count + item.soft_deleted_account_count > 0
                else "viable"
            )
            if item.status != expected_status:
                raise CampaignError(
                    "Automation cleanup candidate classification differs"
                )
            if item.status == "viable":
                viable.append(item.region)
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
            "policyAssignmentCount": self.policy_assignment_count,
            "policyDefinitionCount": self.policy_definition_count,
            "providerLocationsSha256": self.provider_locations_sha256,
            "activeOccupancySha256": self.active_occupancy_sha256,
            "softDeletedOccupancySha256": self.soft_deleted_occupancy_sha256,
            "policyEvidenceSha256": self.policy_evidence_sha256,
            "observedAtUtc": self.observed_at_utc,
            "candidates": [
                {
                    "region": item.region,
                    "providerSupported": item.provider_supported,
                    "policyAllowed": item.policy_allowed,
                    "activeAccountCount": item.active_account_count,
                    "softDeletedAccountCount": item.soft_deleted_account_count,
                    "status": item.status,
                }
                for item in self.candidates
            ],
        }

    def sha256(self) -> str:
        encoded = json.dumps(
            self.document(), separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(
            b"m7.8/cleanup-region-selection/v1\0" + encoded
        ).hexdigest()


def selection_from_document(value: object) -> AutomationRegionSelection:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "candidateOrder",
        "selectedRegion",
        "providerRegistrationState",
        "capacityBasis",
        "policyAssignmentCount",
        "policyDefinitionCount",
        "providerLocationsSha256",
        "activeOccupancySha256",
        "softDeletedOccupancySha256",
        "policyEvidenceSha256",
        "observedAtUtc",
        "candidates",
    }:
        raise CampaignError("Automation cleanup region receipt fields are invalid")
    raw_candidates = value["candidates"]
    if not isinstance(value["candidateOrder"], list) or not isinstance(
        raw_candidates, list
    ):
        raise CampaignError("Automation cleanup region receipt arrays are invalid")
    candidates: list[CandidateEvidence] = []
    for item in raw_candidates:
        if not isinstance(item, dict) or set(item) != {
            "region",
            "providerSupported",
            "policyAllowed",
            "activeAccountCount",
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
                policy_allowed=cast(bool, item["policyAllowed"]),
                active_account_count=cast(int, item["activeAccountCount"]),
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
        policy_assignment_count=cast(int, value["policyAssignmentCount"]),
        policy_definition_count=cast(int, value["policyDefinitionCount"]),
        provider_locations_sha256=cast(str, value["providerLocationsSha256"]),
        active_occupancy_sha256=cast(str, value["activeOccupancySha256"]),
        soft_deleted_occupancy_sha256=cast(str, value["softDeletedOccupancySha256"]),
        policy_evidence_sha256=cast(str, value["policyEvidenceSha256"]),
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
            "resource",
            "list",
            "--resource-type",
            "Microsoft.Automation/automationAccounts",
            "--query",
            "[].{location:location}",
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
    )


def select_automation_region_from_results(
    runner: RegionCommandRunner,
    results: tuple[dict[str, object], ...],
    *,
    observed_at: datetime | None = None,
    candidate_order: tuple[str, ...] = CLEANUP_REGION_CANDIDATES,
) -> AutomationRegionSelection:
    _validate_candidate_order(candidate_order)
    if len(results) != 5:
        raise CampaignError("Automation cleanup regional discovery is incomplete")
    account = _json_result(results[0])
    provider = _json_result(results[1])
    active = _json_result(results[2])
    deleted = _json_result(results[3])
    assignments = _json_result(results[4])
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
    active_counts = _location_counts(active, supported=supported, label="active")
    if (
        not isinstance(deleted, dict)
        or set(deleted) != {"accounts", "nextLink"}
        or (deleted["nextLink"] is not None and deleted["nextLink"] != "")
    ):
        raise CampaignError(
            "automation-region-discovery-failed: soft-deleted account inventory is incomplete"
        )
    deleted_counts = _location_counts(
        deleted["accounts"], supported=supported, label="soft-deleted"
    )
    if not isinstance(assignments, list):
        raise CampaignError("Automation location policy discovery is malformed")
    policy_allowed, definition_count, policy_evidence_sha256 = _policy_allowance(
        runner,
        assignments,
        candidate_order=candidate_order,
    )
    evidence: list[CandidateEvidence] = []
    for region in candidate_order:
        provider_supported = region in supported
        allowed = policy_allowed[region]
        active_count = active_counts.get(region, 0)
        deleted_count = deleted_counts.get(region, 0)
        status = (
            "unsupported"
            if not provider_supported
            else "policy-disallowed"
            if not allowed
            else "occupied"
            if active_count + deleted_count > 0
            else "viable"
        )
        evidence.append(
            CandidateEvidence(
                region=region,
                provider_supported=provider_supported,
                policy_allowed=allowed,
                active_account_count=active_count,
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
        capacity_basis="provider-policy-zero-active-and-soft-deleted-accounts",
        policy_assignment_count=len(assignments),
        policy_definition_count=definition_count,
        provider_locations_sha256=_evidence_hash(
            "provider-locations", sorted(supported)
        ),
        active_occupancy_sha256=_evidence_hash("active-occupancy", active_counts),
        soft_deleted_occupancy_sha256=_evidence_hash(
            "soft-deleted-occupancy", deleted_counts
        ),
        policy_evidence_sha256=policy_evidence_sha256,
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
        statuses <= {"unsupported", "policy-disallowed"}
        and "policy-disallowed" in statuses
    ):
        code = "automation-region-policy-disallowed"
    else:
        code = "automation-region-occupied-capacity-unproved"
    raise CampaignError(f"{code}: no reviewed cleanup region is armable")
