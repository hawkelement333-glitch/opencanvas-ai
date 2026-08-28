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
        config.retention_absence_evidence_sha256,
    )
    return hashlib.sha256(
        b"m7.8/cleanup-authority/v2\0" + "\0".join(values).encode()
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
        "retentionAbsenceEvidenceSha256",
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
        b"m7.8/execution-authorization/v2\0"
        + json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        value.get("version") != "m7.8-execution-authorization-v2"
        or value.get("disposition") != "separately-authorized-azure-execution"
        or value.get("campaignId") != config.campaign_id
        or value.get("generationId") != config.generation_id
        or value.get("subscriptionCorrelation") != config.subscription_correlation
        or value.get("sourceHead") != runtime["sourceHead"]
        or value.get("controllerArchitecture") != ARCHITECTURE
        or value.get("controllerBindingSha256") != runtime["controllerBindingSha256"]
        or value.get("retentionAbsenceEvidenceSha256")
        != config.retention_absence_evidence_sha256
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
