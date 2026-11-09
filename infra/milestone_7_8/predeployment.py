"""Fail-closed fresh-subscription predeployment inventory verification.

This module is deliberately separate from M78-PG-012 retention verification.
It proves only that one planned reusable controller account is absent from a
complete current deleted-account inventory before deployment.  It grants no
controller, campaign, or Azure mutation authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse

from infra.milestone_7_8.azure_cli import AzureCliLauncher
from infra.milestone_7_8.campaign import (
    CAMPAIGN_PATTERN,
    GENERATION_PATTERN,
    sanitize,
)
from infra.milestone_7_8.cleanup_controller import controller_names

RUNTIME_VERSION = "m7.8-fresh-subscription-predeployment-runtime-v1"
AUTHORIZATION_VERSION = "m7.8-fresh-subscription-predeployment-read-authorization-v1"
EVIDENCE_VERSION = "m7.8-fresh-subscription-predeployment-absence-evidence-v1"
EVIDENCE_CLASS = "managed-provider-predeployment-get-only"
EVIDENCE_STATUS = "fresh-subscription-predeployment-inventory-clear"
AUTHORIZATION_DISPOSITION = (
    "separately-authorized-fresh-subscription-predeployment-read"
)
RESOURCE_TYPE = "Microsoft.Automation/deletedAutomationAccounts"
API_VERSION = "2024-10-23"
MANAGEMENT_HOST = "management.azure.com"
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 2_000_000
MAX_AUTHORIZATION_LIFETIME = timedelta(hours=1)
RUNTIME_FIELDS = {
    "version",
    "subscriptionId",
    "tenantId",
    "campaignId",
    "generationId",
    "region",
    "controllerResourceGroupName",
    "automationAccountName",
}
AUTHORIZATION_FIELDS = {
    "version",
    "disposition",
    "subscriptionCorrelation",
    "subscriptionIdentitySha256",
    "tenantCorrelation",
    "campaignCorrelation",
    "generationCorrelation",
    "region",
    "plannedAccountIdentitySha256",
    "runtimeBindingSha256",
    "allowedOperations",
    "issuedAtUtc",
    "expiresAtUtc",
    "authorizationSha256",
}
EVIDENCE_FIELDS = {
    "version",
    "evidenceClass",
    "status",
    "subscriptionCorrelation",
    "subscriptionIdentitySha256",
    "tenantCorrelation",
    "campaignCorrelation",
    "generationCorrelation",
    "region",
    "plannedAccountIdentitySha256",
    "runtimeBindingSha256",
    "authorizationSha256",
    "authorizationExpiresAtUtc",
    "observedAtUtc",
    "providerResourceType",
    "providerEndpointTemplate",
    "providerApiVersion",
    "providerEndpointSha256",
    "httpMethods",
    "paginationComplete",
    "deletedInventoryPages",
    "continuationCount",
    "inventoryPages",
    "deletedInventorySha256",
    "deletedAccountCount",
    "plannedAccountCandidates",
    "azureGetOperations",
    "azureMutationCount",
    "repositoryMutationCount",
    "supportTicketOperationCount",
    "controllerMutationCount",
    "campaignMutationCount",
    "remoteGitMutationCount",
    "milestone8MutationCount",
}
MUTATION_FIELDS = (
    "azureMutationCount",
    "repositoryMutationCount",
    "supportTicketOperationCount",
    "controllerMutationCount",
    "campaignMutationCount",
    "remoteGitMutationCount",
    "milestone8MutationCount",
)
ALLOWED_OPERATIONS = (
    "authenticated-subscription-read",
    "deleted-automation-inventory-read",
)
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
REGION_PATTERN = re.compile(r"^[a-z][a-z0-9]{2,31}$")
ACCOUNT_PATTERN = re.compile(r"^[a-z0-9-]{6,50}$")
SUBSCRIPTION_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
ENDPOINT_TEMPLATE = (
    "https://management.azure.com/subscriptions/{subscriptionId}/providers/"
    "Microsoft.Automation/deletedAutomationAccounts?api-version=2024-10-23"
)


class PredeploymentVerificationError(RuntimeError):
    """A non-sensitive predeployment verification failure."""


class AzureCliRunner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: int | float = 900,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class FreshSubscriptionScope:
    subscription_id: str
    tenant_id: str
    campaign_id: str
    generation_id: str
    region: str
    controller_resource_group_name: str
    automation_account_name: str


@dataclass(frozen=True, slots=True)
class PredeploymentEvidenceBinding:
    evidence_sha256: str
    authorization_sha256: str
    observed_at_utc: str
    document: dict[str, object]


def load_validated_admission(
    *,
    runtime_path: Path,
    authorization_path: Path,
    evidence_path: Path,
    subscription_id: str,
    tenant_id: str,
    campaign_id: str,
    generation_id: str,
    region: str,
    controller_resource_group_name: str,
    automation_account_name: str,
    require_current: bool = False,
) -> PredeploymentEvidenceBinding:
    """Bind completed fresh-scope inventory evidence to one live admission.

    The short-lived read authorization is validated for its original issuance
    window by :func:`validate_evidence`; it is deliberately *not* required to
    still be current here.  A completed GET-only observation remains evidence,
    but it is never execution authority.
    """
    scope = load_runtime(runtime_path)
    if (
        scope.subscription_id != subscription_id
        or scope.tenant_id != tenant_id
        or scope.campaign_id != campaign_id
        or scope.generation_id != generation_id
        or scope.region != region
        or scope.controller_resource_group_name != controller_resource_group_name
        or scope.automation_account_name != automation_account_name
    ):
        raise PredeploymentVerificationError("predeployment-live-admission-binding-invalid")
    authorization = _load_json(
        authorization_path, "predeployment-authorization-unreadable"
    )
    evidence = _load_json(evidence_path, "predeployment-evidence-unreadable")
    if require_current:
        validate_read_authorization(authorization, scope=scope, require_current=True)
    return validate_evidence(evidence, scope=scope, authorization=authorization)


def _hash(domain: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(f"m7.8/{domain}/v1\0".encode() + encoded).hexdigest()


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _parse_utc(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise PredeploymentVerificationError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PredeploymentVerificationError(code) from exc
    if parsed.tzinfo is None:
        raise PredeploymentVerificationError(code)
    return parsed.astimezone(UTC)


def _require_string(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise PredeploymentVerificationError(code)
    return value


def _require_dict(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PredeploymentVerificationError(code)
    return cast(dict[str, object], value)


def _load_json(path: Path, code: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PredeploymentVerificationError(code)
        return _require_dict(json.loads(raw), code)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PredeploymentVerificationError(code) from exc


def endpoint(subscription_id: str) -> str:
    return ENDPOINT_TEMPLATE.replace("{subscriptionId}", subscription_id.casefold())


def request_sha256(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    normalized = (
        f"https://{MANAGEMENT_HOST}"
        + parsed.path.casefold()
        + "?"
        + urlencode(
            sorted((key, item) for key, values in query.items() for item in values)
        )
    )
    return _hash("fresh-predeployment-provider-request", normalized)


def _scope_runtime_value(scope: FreshSubscriptionScope) -> dict[str, str]:
    return {
        "version": RUNTIME_VERSION,
        "subscriptionId": scope.subscription_id,
        "tenantId": scope.tenant_id,
        "campaignId": scope.campaign_id,
        "generationId": scope.generation_id,
        "region": scope.region,
        "controllerResourceGroupName": scope.controller_resource_group_name,
        "automationAccountName": scope.automation_account_name,
    }


def _validate_uuid(value: str, code: str) -> str:
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise PredeploymentVerificationError(code) from exc
    if parsed != value.casefold() or uuid.UUID(parsed).int == 0:
        raise PredeploymentVerificationError(code)
    return parsed


def build_runtime_document(
    *,
    subscription_id: str,
    tenant_id: str,
    campaign_id: str,
    generation_id: str,
    region: str,
) -> dict[str, str]:
    subscription_id = _validate_uuid(
        subscription_id, "predeployment-subscription-invalid"
    )
    tenant_id = _validate_uuid(tenant_id, "predeployment-tenant-invalid")
    if (
        CAMPAIGN_PATTERN.fullmatch(campaign_id) is None
        or GENERATION_PATTERN.fullmatch(generation_id) is None
        or REGION_PATTERN.fullmatch(region) is None
    ):
        raise PredeploymentVerificationError("predeployment-runtime-binding-invalid")
    names = controller_names(sanitize(subscription_id, domain="subscription"))
    return {
        "version": RUNTIME_VERSION,
        "subscriptionId": subscription_id,
        "tenantId": tenant_id,
        "campaignId": campaign_id,
        "generationId": generation_id,
        "region": region,
        "controllerResourceGroupName": names.resource_group,
        "automationAccountName": names.account,
    }


def load_runtime(path: Path) -> FreshSubscriptionScope:
    value = _load_json(path, "predeployment-runtime-unreadable")
    if set(value) != RUNTIME_FIELDS:
        raise PredeploymentVerificationError("predeployment-runtime-fields-invalid")
    expected = build_runtime_document(
        subscription_id=_require_string(
            value.get("subscriptionId"), "predeployment-subscription-invalid"
        ),
        tenant_id=_require_string(
            value.get("tenantId"), "predeployment-tenant-invalid"
        ),
        campaign_id=_require_string(
            value.get("campaignId"), "predeployment-runtime-binding-invalid"
        ),
        generation_id=_require_string(
            value.get("generationId"), "predeployment-runtime-binding-invalid"
        ),
        region=_require_string(
            value.get("region"), "predeployment-runtime-binding-invalid"
        ),
    )
    if value != expected:
        raise PredeploymentVerificationError("predeployment-runtime-binding-invalid")
    return FreshSubscriptionScope(
        subscription_id=expected["subscriptionId"],
        tenant_id=expected["tenantId"],
        campaign_id=expected["campaignId"],
        generation_id=expected["generationId"],
        region=expected["region"],
        controller_resource_group_name=expected["controllerResourceGroupName"],
        automation_account_name=expected["automationAccountName"],
    )


def planned_account_resource_id(scope: FreshSubscriptionScope) -> str:
    return (
        f"/subscriptions/{scope.subscription_id}/resourceGroups/"
        f"{scope.controller_resource_group_name}/providers/Microsoft.Automation/"
        f"automationAccounts/{scope.automation_account_name}"
    ).casefold()


def scope_bindings(scope: FreshSubscriptionScope) -> dict[str, str]:
    return {
        "subscriptionCorrelation": sanitize(
            scope.subscription_id, domain="subscription"
        ),
        "subscriptionIdentitySha256": _hash(
            "fresh-predeployment-subscription", scope.subscription_id
        ),
        "tenantCorrelation": sanitize(scope.tenant_id, domain="tenant"),
        "campaignCorrelation": sanitize(scope.campaign_id, domain="campaign"),
        "generationCorrelation": sanitize(scope.generation_id, domain="generation"),
        "region": scope.region,
        "plannedAccountIdentitySha256": _hash(
            "fresh-predeployment-deleted-automation-account",
            planned_account_resource_id(scope),
        ),
        "runtimeBindingSha256": _hash(
            "fresh-predeployment-runtime-binding", _scope_runtime_value(scope)
        ),
    }


def authorization_sha256(value: dict[str, object]) -> str:
    if set(value) != AUTHORIZATION_FIELDS:
        raise PredeploymentVerificationError(
            "predeployment-authorization-fields-invalid"
        )
    payload = {key: item for key, item in value.items() if key != "authorizationSha256"}
    return _hash("fresh-predeployment-read-authorization", payload)


def build_read_authorization(
    scope: FreshSubscriptionScope,
    *,
    issued_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    issued_at = issued_at.astimezone(UTC)
    expires_at = expires_at.astimezone(UTC)
    if expires_at <= issued_at or expires_at - issued_at > MAX_AUTHORIZATION_LIFETIME:
        raise PredeploymentVerificationError(
            "predeployment-authorization-expiry-invalid"
        )
    value: dict[str, object] = {
        "version": AUTHORIZATION_VERSION,
        "disposition": AUTHORIZATION_DISPOSITION,
        **scope_bindings(scope),
        "allowedOperations": list(ALLOWED_OPERATIONS),
        "issuedAtUtc": _utc_text(issued_at),
        "expiresAtUtc": _utc_text(expires_at),
        "authorizationSha256": "",
    }
    value["authorizationSha256"] = authorization_sha256(value)
    return value


def validate_read_authorization(
    value: dict[str, object],
    *,
    scope: FreshSubscriptionScope,
    now: datetime | None = None,
    require_current: bool,
) -> str:
    bindings = scope_bindings(scope)
    if (
        set(value) != AUTHORIZATION_FIELDS
        or value.get("version") != AUTHORIZATION_VERSION
        or value.get("disposition") != AUTHORIZATION_DISPOSITION
        or any(value.get(key) != expected for key, expected in bindings.items())
        or value.get("allowedOperations") != list(ALLOWED_OPERATIONS)
    ):
        raise PredeploymentVerificationError("predeployment-authorization-not-exact")
    issued_at = _parse_utc(
        value.get("issuedAtUtc"), "predeployment-authorization-time-invalid"
    )
    expires_at = _parse_utc(
        value.get("expiresAtUtc"), "predeployment-authorization-time-invalid"
    )
    if expires_at <= issued_at or expires_at - issued_at > MAX_AUTHORIZATION_LIFETIME:
        raise PredeploymentVerificationError(
            "predeployment-authorization-expiry-invalid"
        )
    expected_hash = authorization_sha256(value)
    if value.get("authorizationSha256") != expected_hash:
        raise PredeploymentVerificationError("predeployment-authorization-not-exact")
    if require_current:
        observed_now = (now or datetime.now(UTC)).astimezone(UTC)
        if observed_now < issued_at or observed_now >= expires_at:
            raise PredeploymentVerificationError(
                "predeployment-authorization-not-current"
            )
    return expected_hash


def _safe_next_link(value: str, scope: FreshSubscriptionScope) -> str:
    parsed = urlparse(value)
    expected_path = (
        f"/subscriptions/{scope.subscription_id}/providers/"
        "Microsoft.Automation/deletedAutomationAccounts"
    )
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != MANAGEMENT_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path.casefold() != expected_path.casefold()
        or parsed.fragment
        or query.get("api-version") != [API_VERSION]
    ):
        raise PredeploymentVerificationError("predeployment-next-link-invalid")
    return value


def _ci_get(value: dict[str, object], name: str) -> object:
    lowered = name.casefold()
    if len({key.casefold() for key in value}) != len(value):
        raise PredeploymentVerificationError("predeployment-record-ambiguous-fields")
    for key, item in value.items():
        if key.casefold() == lowered:
            return item
    return None


def _record_identity(
    value: object, scope: FreshSubscriptionScope
) -> tuple[str, str, str]:
    item = _require_dict(value, "predeployment-record-invalid")
    properties = _require_dict(
        _ci_get(item, "properties"), "predeployment-record-properties-invalid"
    )
    name = _require_string(
        _ci_get(item, "name"), "predeployment-record-name-invalid"
    ).casefold()
    deleted_id = _require_string(
        _ci_get(item, "id"), "predeployment-record-id-invalid"
    ).casefold()
    original_id = _require_string(
        _ci_get(properties, "automationAccountResourceId"),
        "predeployment-record-original-id-invalid",
    ).casefold()
    if ACCOUNT_PATTERN.fullmatch(name) is None:
        raise PredeploymentVerificationError("predeployment-record-name-invalid")
    expected_deleted_id = (
        f"/subscriptions/{scope.subscription_id}/providers/microsoft.automation/"
        f"deletedautomationaccounts/{name}"
    )
    expected_original = re.fullmatch(
        rf"/subscriptions/{re.escape(scope.subscription_id)}/resourcegroups/[^/]+/"
        rf"providers/microsoft\.automation/automationaccounts/{re.escape(name)}",
        original_id,
    )
    if deleted_id != expected_deleted_id or expected_original is None:
        raise PredeploymentVerificationError("predeployment-record-scope-invalid")
    return (
        _hash("fresh-predeployment-deleted-automation-account", original_id),
        deleted_id,
        name,
    )


def evidence_sha256(value: dict[str, object]) -> str:
    if value.get("version") != EVIDENCE_VERSION:
        raise PredeploymentVerificationError("predeployment-evidence-version-invalid")
    return _hash("fresh-predeployment-absence-evidence", value)


def build_evidence_document(
    scope: FreshSubscriptionScope,
    *,
    authorization: dict[str, object],
    observed_at: datetime,
    pages: list[dict[str, object]],
) -> dict[str, object]:
    authorization_hash = validate_read_authorization(
        authorization, scope=scope, require_current=False
    )
    if not pages:
        raise PredeploymentVerificationError("predeployment-pagination-invalid")
    identities = sorted(
        item for page in pages for item in cast(list[str], page["recordIdentitySha256"])
    )
    if len(set(identities)) != len(identities):
        raise PredeploymentVerificationError(
            "predeployment-deleted-inventory-duplicate"
        )
    bindings = scope_bindings(scope)
    return {
        "version": EVIDENCE_VERSION,
        "evidenceClass": EVIDENCE_CLASS,
        "status": EVIDENCE_STATUS,
        **bindings,
        "authorizationSha256": authorization_hash,
        "authorizationExpiresAtUtc": authorization["expiresAtUtc"],
        "observedAtUtc": _utc_text(observed_at),
        "providerResourceType": RESOURCE_TYPE,
        "providerEndpointTemplate": ENDPOINT_TEMPLATE,
        "providerApiVersion": API_VERSION,
        "providerEndpointSha256": request_sha256(endpoint(scope.subscription_id)),
        "httpMethods": ["GET"],
        "paginationComplete": True,
        "deletedInventoryPages": len(pages),
        "continuationCount": len(pages) - 1,
        "inventoryPages": pages,
        "deletedInventorySha256": _hash(
            "fresh-predeployment-deleted-inventory", identities
        ),
        "deletedAccountCount": len(identities),
        "plannedAccountCandidates": 0,
        "azureGetOperations": len(pages) + 1,
        **dict.fromkeys(MUTATION_FIELDS, 0),
    }


def validate_evidence(
    value: dict[str, object],
    *,
    scope: FreshSubscriptionScope,
    authorization: dict[str, object],
) -> PredeploymentEvidenceBinding:
    authorization_hash = validate_read_authorization(
        authorization, scope=scope, require_current=False
    )
    bindings = scope_bindings(scope)
    if (
        set(value) != EVIDENCE_FIELDS
        or value.get("version") != EVIDENCE_VERSION
        or value.get("evidenceClass") != EVIDENCE_CLASS
        or value.get("status") != EVIDENCE_STATUS
        or any(value.get(key) != expected for key, expected in bindings.items())
        or value.get("authorizationSha256") != authorization_hash
        or value.get("authorizationExpiresAtUtc") != authorization.get("expiresAtUtc")
        or value.get("providerResourceType") != RESOURCE_TYPE
        or value.get("providerEndpointTemplate") != ENDPOINT_TEMPLATE
        or value.get("providerApiVersion") != API_VERSION
        or value.get("providerEndpointSha256")
        != request_sha256(endpoint(scope.subscription_id))
        or value.get("httpMethods") != ["GET"]
        or value.get("paginationComplete") is not True
        or value.get("plannedAccountCandidates") != 0
    ):
        raise PredeploymentVerificationError("predeployment-evidence-not-exact")
    observed_at = _parse_utc(
        value.get("observedAtUtc"), "predeployment-observed-time-invalid"
    )
    issued_at = _parse_utc(
        authorization.get("issuedAtUtc"), "predeployment-authorization-time-invalid"
    )
    expires_at = _parse_utc(
        authorization.get("expiresAtUtc"), "predeployment-authorization-time-invalid"
    )
    if observed_at < issued_at or observed_at > expires_at:
        raise PredeploymentVerificationError("predeployment-observation-not-authorized")
    pages = value.get("inventoryPages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise PredeploymentVerificationError("predeployment-pagination-invalid")
    if (
        value.get("deletedInventoryPages") != len(pages)
        or value.get("continuationCount") != len(pages) - 1
        or value.get("azureGetOperations") != len(pages) + 1
    ):
        raise PredeploymentVerificationError("predeployment-evidence-not-exact")
    expected_request: object = request_sha256(endpoint(scope.subscription_id))
    seen_requests: set[str] = set()
    identities: list[str] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != {
            "requestSha256",
            "recordIdentitySha256",
            "nextRequestSha256",
        }:
            raise PredeploymentVerificationError("predeployment-evidence-not-exact")
        request = page["requestSha256"]
        records = page["recordIdentitySha256"]
        next_request = page["nextRequestSha256"]
        if (
            not isinstance(request, str)
            or HASH_PATTERN.fullmatch(request) is None
            or request != expected_request
            or request in seen_requests
            or not isinstance(records, list)
            or any(
                not isinstance(item, str) or HASH_PATTERN.fullmatch(item) is None
                for item in records
            )
            or records != sorted(records)
            or (index == len(pages) - 1 and next_request is not None)
            or (
                index < len(pages) - 1
                and (
                    not isinstance(next_request, str)
                    or HASH_PATTERN.fullmatch(next_request) is None
                )
            )
        ):
            raise PredeploymentVerificationError("predeployment-evidence-not-exact")
        seen_requests.add(request)
        identities.extend(cast(list[str], records))
        expected_request = next_request
    identities.sort()
    if (
        len(set(identities)) != len(identities)
        or bindings["plannedAccountIdentitySha256"] in identities
        or value.get("deletedAccountCount") != len(identities)
        or value.get("deletedInventorySha256")
        != _hash("fresh-predeployment-deleted-inventory", identities)
        or any(value.get(field) != 0 for field in MUTATION_FIELDS)
    ):
        raise PredeploymentVerificationError("predeployment-evidence-not-exact")
    return PredeploymentEvidenceBinding(
        evidence_sha256(value), authorization_hash, _utc_text(observed_at), value
    )


class PredeploymentVerifier:
    def __init__(
        self,
        runner: AzureCliRunner,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.runner = runner
        self.clock = clock or (lambda: datetime.now(UTC))
        self.azure_get_operations = 0

    def _run(self, arguments: tuple[str, ...], code: str) -> str:
        try:
            result = self.runner.run(arguments, timeout=120)
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise PredeploymentVerificationError(code) from exc
        if (
            result.returncode != 0
            or len(result.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES
        ):
            raise PredeploymentVerificationError(code)
        self.azure_get_operations += 1
        return result.stdout

    def _verify_subscription(self, scope: FreshSubscriptionScope) -> None:
        observed = self._run(
            (
                "account",
                "show",
                "--query",
                "id",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            "predeployment-subscription-read-failed",
        ).strip()
        if observed.casefold() != scope.subscription_id:
            raise PredeploymentVerificationError("predeployment-subscription-mismatch")

    def _page(self, url: str) -> dict[str, object]:
        raw = self._run(
            (
                "rest",
                "--method",
                "get",
                "--url",
                url,
                "--output",
                "json",
                "--only-show-errors",
            ),
            "predeployment-deleted-inventory-read-failed",
        )
        try:
            return _require_dict(
                json.loads(raw), "predeployment-deleted-inventory-malformed"
            )
        except json.JSONDecodeError as exc:
            raise PredeploymentVerificationError(
                "predeployment-deleted-inventory-malformed"
            ) from exc

    def verify(
        self, scope: FreshSubscriptionScope, authorization: dict[str, object]
    ) -> dict[str, object]:
        started = self.clock().astimezone(UTC)
        validate_read_authorization(
            authorization, scope=scope, now=started, require_current=True
        )
        self._verify_subscription(scope)
        url = endpoint(scope.subscription_id)
        seen_requests: set[str] = set()
        seen_deleted_ids: set[str] = set()
        seen_names: set[str] = set()
        seen_identities: set[str] = set()
        pages: list[dict[str, object]] = []
        planned_identity = scope_bindings(scope)["plannedAccountIdentitySha256"]
        while True:
            url = _safe_next_link(url, scope)
            request = request_sha256(url)
            if request in seen_requests or len(pages) >= MAX_PAGES:
                raise PredeploymentVerificationError("predeployment-pagination-invalid")
            seen_requests.add(request)
            page = self._page(url)
            raw_records = page.get("value")
            if not isinstance(raw_records, list):
                raise PredeploymentVerificationError(
                    "predeployment-deleted-inventory-malformed"
                )
            identities: list[str] = []
            for raw_record in raw_records:
                identity, deleted_id, name = _record_identity(raw_record, scope)
                if (
                    identity in seen_identities
                    or deleted_id in seen_deleted_ids
                    or name in seen_names
                ):
                    raise PredeploymentVerificationError(
                        "predeployment-deleted-inventory-duplicate"
                    )
                if identity == planned_identity:
                    raise PredeploymentVerificationError(
                        "predeployment-planned-account-present"
                    )
                seen_identities.add(identity)
                seen_deleted_ids.add(deleted_id)
                seen_names.add(name)
                identities.append(identity)
            next_link = page.get("nextLink")
            if next_link not in {None, ""} and not isinstance(next_link, str):
                raise PredeploymentVerificationError("predeployment-next-link-invalid")
            next_url = (
                _safe_next_link(next_link, scope)
                if isinstance(next_link, str) and next_link
                else None
            )
            pages.append(
                {
                    "requestSha256": request,
                    "recordIdentitySha256": sorted(identities),
                    "nextRequestSha256": request_sha256(next_url) if next_url else None,
                }
            )
            if next_url is None:
                break
            url = next_url
        observed_at = self.clock().astimezone(UTC)
        if observed_at < started:
            raise PredeploymentVerificationError(
                "predeployment-observation-clock-regressed"
            )
        document = build_evidence_document(
            scope, authorization=authorization, observed_at=observed_at, pages=pages
        )
        validate_evidence(document, scope=scope, authorization=authorization)
        return document


def _write_private_json(
    path: Path, value: dict[str, object], *, expected_name: str
) -> None:
    if path.name != expected_name or path.exists():
        raise PredeploymentVerificationError("predeployment-private-output-invalid")
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _write_peer_private_json(
    path: Path,
    value: dict[str, object],
    *,
    runtime_path: Path,
    expected_name: str,
) -> None:
    if (
        path.name != expected_name
        or path.exists()
        or path.parent.resolve() != runtime_path.parent.resolve()
    ):
        raise PredeploymentVerificationError("predeployment-private-output-invalid")
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _environment_required(name: str) -> str:
    return _require_string(
        os.environ.get(name), "predeployment-runtime-environment-missing"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or verify one read-only fresh-subscription predeployment scope"
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    initialize = commands.add_parser("initialize")
    initialize.add_argument("--runtime", type=Path, required=True)
    authorize = commands.add_parser("authorize-read")
    authorize.add_argument("--runtime", type=Path, required=True)
    authorize.add_argument("--authorization", type=Path, required=True)
    authorize.add_argument("--expires-at", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--runtime", type=Path, required=True)
    verify.add_argument("--authorization", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.operation == "initialize":
            runtime = build_runtime_document(
                subscription_id=_environment_required("M78_FRESH_SUBSCRIPTION_ID"),
                tenant_id=_environment_required("M78_FRESH_TENANT_ID"),
                campaign_id=_environment_required("M78_FRESH_CAMPAIGN_ID"),
                generation_id=_environment_required("M78_FRESH_GENERATION_ID"),
                region=_environment_required("M78_FRESH_REGION"),
            )
            _write_private_json(
                arguments.runtime,
                cast(dict[str, object], runtime),
                expected_name="fresh-subscription-runtime.json",
            )
            scope = load_runtime(arguments.runtime)
            print(
                json.dumps(
                    {
                        "status": "fresh-subscription-runtime-created",
                        **scope_bindings(scope),
                    },
                    sort_keys=True,
                )
            )
            return 0
        scope = load_runtime(arguments.runtime)
        if arguments.operation == "authorize-read":
            expires_at = _parse_utc(
                arguments.expires_at, "predeployment-authorization-time-invalid"
            )
            authorization = build_read_authorization(
                scope, issued_at=datetime.now(UTC), expires_at=expires_at
            )
            _write_peer_private_json(
                arguments.authorization,
                authorization,
                runtime_path=arguments.runtime,
                expected_name="predeployment-read-authorization.json",
            )
            print(
                json.dumps(
                    {
                        "status": "predeployment-read-authorized",
                        "authorizationSha256": authorization["authorizationSha256"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        authorization = _load_json(
            arguments.authorization, "predeployment-authorization-unreadable"
        )
        document = PredeploymentVerifier(AzureCliLauncher.resolve()).verify(
            scope, authorization
        )
        _write_peer_private_json(
            arguments.output,
            document,
            runtime_path=arguments.runtime,
            expected_name="predeployment-absence-evidence.json",
        )
        binding = validate_evidence(document, scope=scope, authorization=authorization)
        print(
            json.dumps(
                {"status": EVIDENCE_STATUS, "evidenceSha256": binding.evidence_sha256},
                sort_keys=True,
            )
        )
        return 0
    except PredeploymentVerificationError as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
