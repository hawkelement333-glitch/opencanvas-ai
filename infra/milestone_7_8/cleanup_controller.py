from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, parse_utc

ARCHITECTURE: Final = "reusable-automation-controller-v1"
LOCAL_ARCHITECTURE_STATE: Final = "architecture-corrected-live-execution-not-authorized"
CONTROLLER_RUNBOOK_NAME: Final = "Remove-M78Campaign"
CONTROLLER_GROUP_PATTERN: Final = re.compile(r"^rg-m78-controller-[a-f0-9]{10}$")
CONTROLLER_ACCOUNT_PATTERN: Final = re.compile(r"^aa-m78-controller-[a-f0-9]{10}$")
AUTHORIZABLE_OPERATIONS: Final = frozenset(
    {
        "preflight",
        "correlate",
        "capacity-check",
        "cost-gate",
        "scope-create",
        "cleanup-deploy",
        "cleanup-arm",
        "cleanup-verify",
        "billable-start",
        "deploy",
        "image-decision",
        "bootstrap",
        "migrate",
        "evidence",
        "dispose",
        "cleanup",
        "cleanup-wait",
        "cleanup-disarm",
        "residue",
        "finalize",
    }
)


@dataclass(frozen=True, slots=True)
class ControllerNames:
    resource_group: str
    account: str
    runbook: str = CONTROLLER_RUNBOOK_NAME


def controller_local_auth_disabled(account: dict[str, object]) -> bool:
    """Accept CLI/REST shapes only when every supplied setting is boolean true."""
    properties = account.get("properties")
    if "properties" in account and not isinstance(properties, dict):
        return False
    values = []
    if "disableLocalAuth" in account:
        values.append(account["disableLocalAuth"])
    if isinstance(properties, dict) and "disableLocalAuth" in properties:
        values.append(properties["disableLocalAuth"])
    return bool(values) and all(value is True for value in values)


def validate_controller_deadline_consistency(
    group: object,
    account: object,
    runbook: object,
    *,
    names: ControllerNames,
    expected_deadline: str,
) -> None:
    """Require the exact controller's three authority tags to agree."""
    parse_utc(expected_deadline)
    for resource, name in (
        (group, names.resource_group),
        (account, names.account),
        (runbook, names.runbook),
    ):
        if not isinstance(resource, dict) or resource.get("name") != name:
            raise CampaignError("controller deadline identity differs")
        tags = resource.get("tags")
        if (
            not isinstance(tags, dict)
            or tags.get("mobius.controller-authorized-until-utc") != expected_deadline
        ):
            raise CampaignError("controller authority deadlines differ")


def validate_renewal_completion_receipt(
    receipt: object,
    *,
    controller_binding: str,
    original_config_sha256: str,
    renewed_config_sha256: str,
    renewal_approval_sha256: str,
    baseline_preservation_sha256: str,
    original_deadline: str,
    observed_deadline: str,
) -> str:
    """Validate an exact, completed private renewal record; never infer completion."""
    expected = {
        "version": "m7.8-controller-renewal-completion-v1",
        "status": "complete",
        "controllerBindingSha256": controller_binding,
        "originalConfigSha256": original_config_sha256,
        "renewedConfigSha256": renewed_config_sha256,
        "renewalApprovalSha256": renewal_approval_sha256,
        "baselinePreservationSha256": baseline_preservation_sha256,
        "originalDeadlineUtc": original_deadline,
        "observedDeadlineUtc": observed_deadline,
        "allResourcesReadBack": True,
        "otherTagsAndPropertiesPreserved": True,
    }
    hashes = (
        controller_binding,
        original_config_sha256,
        renewed_config_sha256,
        renewal_approval_sha256,
        baseline_preservation_sha256,
    )
    if any(re.fullmatch(r"[a-f0-9]{64}", item) is None for item in hashes):
        raise CampaignError("controller renewal binding is malformed")
    if parse_utc(observed_deadline) <= parse_utc(original_deadline):
        raise CampaignError("controller renewal deadline is invalid")
    if not isinstance(receipt, dict) or set(receipt) != {*expected, "receiptSha256"}:
        raise CampaignError("controller renewal completion is incomplete")
    if any(
        type(receipt[key]) is not type(value) or receipt[key] != value
        for key, value in expected.items()
    ):
        raise CampaignError("controller renewal completion binding differs")
    digest = hashlib.sha256(
        b"m7.8/controller-renewal-completion/v1\0"
        + json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if receipt["receiptSha256"] != digest:
        raise CampaignError("controller renewal completion hash differs")
    return digest


def controller_names(subscription_correlation: str) -> ControllerNames:
    if re.fullmatch(r"[a-f0-9]{16}", subscription_correlation) is None:
        raise CampaignError("controller subscription correlation is malformed")
    suffix = subscription_correlation[:10]
    return ControllerNames(
        resource_group=f"rg-m78-controller-{suffix}",
        account=f"aa-m78-controller-{suffix}",
    )


def controller_binding_sha256(
    subscription_id: str,
    *,
    resource_group: str,
    account: str,
    runbook: str,
) -> str:
    try:
        parsed_subscription = uuid.UUID(subscription_id)
    except ValueError as exc:
        raise CampaignError("controller subscription binding is malformed") from exc
    if (
        parsed_subscription.int == 0
        or CONTROLLER_GROUP_PATTERN.fullmatch(resource_group) is None
        or CONTROLLER_ACCOUNT_PATTERN.fullmatch(account) is None
        or runbook != CONTROLLER_RUNBOOK_NAME
    ):
        raise CampaignError("controller identity is malformed")
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
        f"Microsoft.Automation/automationAccounts/{account}/runbooks/{runbook}"
    ).casefold()
    return hashlib.sha256(
        b"m7.8/reusable-cleanup-controller/v1\0" + resource_id.encode()
    ).hexdigest()


def cleanup_authority_sha256(
    config: CampaignConfig,
    runtime: dict[str, str],
) -> str:
    values = (
        ARCHITECTURE,
        config.campaign_id,
        config.generation_id,
        config.subscription_correlation,
        config.target_resource_group,
        config.cleanup_resource_group,
        runtime["automationAccountName"],
        runtime["runbookName"],
        runtime["scheduleName"],
        runtime["bindingName"],
        config.cleanup_deadline_utc,
        runtime["cleanupAuthorityExpiresUtc"],
        "5000",
        runtime["controllerBindingSha256"],
        config.fresh_controller_admission_evidence_sha256,
        runtime["freshControllerAdmissionEvidenceVersion"],
    )
    return hashlib.sha256(
        b"m7.8/cleanup-authority/v4\0" + "\0".join(values).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionAuthorization:
    allowed_operations: frozenset[str]
    expires_at_utc: str
    authorization_sha256: str


def load_execution_authorization(
    path: Path,
    *,
    config: CampaignConfig,
    runtime: dict[str, str],
    operation: str,
    now: datetime | None = None,
) -> ExecutionAuthorization:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError("Azure execution authorization is unreadable") from exc
    required = {
        "version",
        "disposition",
        "campaignId",
        "generationId",
        "subscriptionCorrelation",
        "sourceHead",
        "controllerArchitecture",
        "controllerBindingSha256",
        "controllerAuthorityEvidenceSha256",
        "freshControllerAdmissionEvidenceSha256",
        "freshControllerAdmissionEvidenceVersion",
        "cleanupDeadlineUtc",
        "expiresAtUtc",
        "allowedOperations",
        "authorizationSha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CampaignError("Azure execution authorization fields are invalid")
    operations = value.get("allowedOperations")
    unsigned = {
        key: item for key, item in value.items() if key != "authorizationSha256"
    }
    expected_hash = hashlib.sha256(
        b"m7.8/execution-authorization/v5\0"
        + json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        value.get("version") != "m7.8-execution-authorization-v5"
        or value.get("disposition") != "separately-authorized-azure-execution"
        or value.get("campaignId") != config.campaign_id
        or value.get("generationId") != config.generation_id
        or value.get("subscriptionCorrelation") != config.subscription_correlation
        or value.get("sourceHead") != runtime["sourceHead"]
        or value.get("controllerArchitecture") != ARCHITECTURE
        or value.get("controllerBindingSha256") != runtime["controllerBindingSha256"]
        or value.get("controllerAuthorityEvidenceSha256")
        != runtime["controllerAuthorityEvidenceSha256"]
        or value.get("freshControllerAdmissionEvidenceSha256")
        != config.fresh_controller_admission_evidence_sha256
        or value.get("freshControllerAdmissionEvidenceVersion")
        != runtime["freshControllerAdmissionEvidenceVersion"]
        or value.get("cleanupDeadlineUtc") != config.cleanup_deadline_utc
        or not isinstance(operations, list)
        or not operations
        or len(set(operations)) != len(operations)
        or any(
            not isinstance(item, str) or item not in AUTHORIZABLE_OPERATIONS
            for item in operations
        )
        or operation not in operations
        or value.get("authorizationSha256") != expected_hash
    ):
        raise CampaignError("Azure execution authorization is not exact")
    expires = value.get("expiresAtUtc")
    if not isinstance(expires, str):
        raise CampaignError("Azure execution authorization expiry is malformed")
    parsed_expiry = parse_utc(expires)
    authority_expiry = parse_utc(runtime["cleanupAuthorityExpiresUtc"])
    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    if parsed_expiry <= observed_now or parsed_expiry > authority_expiry:
        raise CampaignError("Azure execution authorization is expired or overbroad")
    return ExecutionAuthorization(
        allowed_operations=frozenset(operations),
        expires_at_utc=expires,
        authorization_sha256=expected_hash,
    )
