"""Exact target absence with observational, non-authorizing historical context.

V2 remains an audit format. Only this format can enter current live admission.
All identifiers below are domain-separated digests; raw provider data stays in memory.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlencode, urlparse

from infra.milestone_7_8 import retention as r

VERSION = r.CURRENT_ABSENCE_EVIDENCE_VERSION
RESOURCE_TYPE = "Microsoft.Automation/deletedAutomationAccounts"
ENDPOINT_TEMPLATE = (
    "https://management.azure.com/subscriptions/{subscriptionId}/providers/"
    "Microsoft.Automation/deletedAutomationAccounts?api-version=2024-10-23"
)
MUTATION_FIELDS = (
    "azureMutationCount", "repositoryMutationCount", "supportTicketOperationCount",
    "controllerMutationCount", "campaignMutationCount", "remoteGitMutationCount",
    "milestone8MutationCount",
)
FIELDS = {
    "version", "evidenceClass", "status", "subscriptionCorrelation",
    "subscriptionIdentitySha256", "campaignCorrelation", "generationCorrelation",
    "region", "observedAtUtc", "authoritativeDeletionTimeUtc",
    "expectedRemovalBoundaryUtc", "campaignDeletedIdentitySha256",
    "providerResourceType", "providerEndpointTemplate", "providerApiVersion",
    "providerEndpointSha256", "httpMethods", "paginationComplete",
    "deletedInventoryPages", "continuationCount", "inventoryPages",
    "currentInventorySha256", "deletedAccountCount", "targetCandidates",
    "currentOnlyRecordCount", "unrelatedBaselineIdentitySha256",
    "unrelatedBaselineSha256", "unrelatedObservations", "azureGetOperations",
    *MUTATION_FIELDS,
}


def digest(domain: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(f"m7.8/{domain}/v3\0".encode() + encoded).hexdigest()


def evidence_sha256(value: dict[str, object]) -> str:
    if value.get("version") != VERSION:
        raise r.RetentionVerificationError("retention-absence-version-not-v3")
    return digest("retention-absence-evidence", value)


def endpoint(subscription_id: str) -> str:
    return ENDPOINT_TEMPLATE.replace("{subscriptionId}", subscription_id.casefold())


def request_sha256(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    normalized = (
        "https://management.azure.com" + parsed.path.casefold() + "?"
        + urlencode(sorted((key, item) for key, values in query.items() for item in values))
    )
    return digest("retention-provider-request", normalized)


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and r.HASH_PATTERN.fullmatch(value) is not None


def _fail() -> None:
    raise r.RetentionVerificationError("retention-absence-evidence-not-exact")


def validate_contract(contract: r.RetentionContract) -> None:
    if (
        r.SUBSCRIPTION_PATTERN.fullmatch(contract.subscription_id) is None
        or r.CORRELATION_PATTERN.fullmatch(contract.campaign_correlation) is None
        or r.CORRELATION_PATTERN.fullmatch(contract.generation_correlation) is None
        or not contract.region
        or not _is_hash(contract.campaign_identity_sha256)
        or len(contract.unrelated_identity_sha256) != 4
        or any(not _is_hash(item) for item in contract.unrelated_identity_sha256)
        or len(set(contract.unrelated_identity_sha256)) != 4
        or contract.campaign_identity_sha256 in contract.unrelated_identity_sha256
        or contract.expected_removal_boundary != contract.authoritative_deletion_time.replace(
            microsecond=contract.authoritative_deletion_time.microsecond
        ) + timedelta(days=30)
    ):
        raise r.RetentionVerificationError("retention-v3-contract-binding-invalid")


def build_document(
    *, subscription_id: str, observed_at: datetime,
    pages: list[dict[str, object]], evidence_class: str,
    baseline: list[str] | None = None,
    campaign_correlation: str = r.RETENTION_CAMPAIGN_CORRELATION,
    generation_correlation: str = r.RETENTION_GENERATION_CORRELATION,
    region: str = r.RETENTION_REGION,
    target_identity_sha256: str = r.RETENTION_TARGET_IDENTITY_SHA256,
    authoritative_deletion_time: str = r.AUTHORITATIVE_DELETION_TIME_UTC,
    expected_removal_boundary: str = r.EXPECTED_REMOVAL_BOUNDARY_UTC,
) -> dict[str, object]:
    """Serialize an already observed inventory; this function grants no authority."""
    hashes = sorted(
        item for page in pages for item in cast(list[str], page["recordIdentitySha256"])
    )
    baseline = list(r.RETENTION_UNRELATED_IDENTITY_SHA256 if baseline is None else baseline)
    value: dict[str, object] = {
        "version": VERSION, "evidenceClass": evidence_class,
        "status": "retained-account-absent",
        "subscriptionCorrelation": r._correlation(subscription_id, domain="subscription"),
        "subscriptionIdentitySha256": digest("retention-subscription", subscription_id.casefold()),
        "campaignCorrelation": campaign_correlation,
        "generationCorrelation": generation_correlation,
        "region": region,
        "observedAtUtc": r._utc_text(observed_at),
        "authoritativeDeletionTimeUtc": authoritative_deletion_time,
        "expectedRemovalBoundaryUtc": expected_removal_boundary,
        "campaignDeletedIdentitySha256": target_identity_sha256,
        "providerResourceType": RESOURCE_TYPE,
        "providerEndpointTemplate": ENDPOINT_TEMPLATE,
        "providerApiVersion": r.API_VERSION,
        "providerEndpointSha256": request_sha256(endpoint(subscription_id)),
        "httpMethods": ["GET"], "paginationComplete": True,
        "deletedInventoryPages": len(pages), "continuationCount": len(pages) - 1,
        "inventoryPages": pages,
        "currentInventorySha256": digest("retention-current-inventory", hashes),
        "deletedAccountCount": len(hashes), "targetCandidates": 0,
        "currentOnlyRecordCount": len(set(hashes) - set(baseline)),
        "unrelatedBaselineIdentitySha256": baseline,
        "unrelatedBaselineSha256": digest("retention-unrelated-baseline", baseline),
        "unrelatedObservations": [
            {
                "baselineIdentitySha256": item,
                "status": "present-unchanged" if item in hashes else "absent-unattributed",
            }
            for item in baseline
        ],
        "azureGetOperations": len(pages) + 1,
        **dict.fromkeys(MUTATION_FIELDS, 0),
    }
    return value


def validate_document(
    value: dict[str, object], *, subscription_id: str,
    subscription_correlation: str, allow_synthetic: bool,
) -> r.RetentionAbsenceBinding:
    subscription_id = subscription_id.casefold()
    baseline = list(r.RETENTION_UNRELATED_IDENTITY_SHA256)
    observed_at = value.get("observedAtUtc")
    evidence_class = value.get("evidenceClass")
    if (
        set(value) != FIELDS
        or r.SUBSCRIPTION_PATTERN.fullmatch(subscription_id) is None
        or r._correlation(subscription_id, domain="subscription") != subscription_correlation
        or value.get("version") != VERSION
        or evidence_class not in (r.MANAGED_EVIDENCE_CLASS, r.SYNTHETIC_EVIDENCE_CLASS)
        or (not allow_synthetic and evidence_class != r.MANAGED_EVIDENCE_CLASS)
        or value.get("status") != "retained-account-absent"
        or value.get("subscriptionCorrelation") != subscription_correlation
        or value.get("subscriptionIdentitySha256")
        != digest("retention-subscription", subscription_id)
        or value.get("campaignCorrelation") != r.RETENTION_CAMPAIGN_CORRELATION
        or value.get("generationCorrelation") != r.RETENTION_GENERATION_CORRELATION
        or value.get("region") != r.RETENTION_REGION
        or value.get("authoritativeDeletionTimeUtc") != r.AUTHORITATIVE_DELETION_TIME_UTC
        or value.get("expectedRemovalBoundaryUtc") != r.EXPECTED_REMOVAL_BOUNDARY_UTC
        or value.get("campaignDeletedIdentitySha256") != r.RETENTION_TARGET_IDENTITY_SHA256
        or value.get("providerResourceType") != RESOURCE_TYPE
        or value.get("providerEndpointTemplate") != ENDPOINT_TEMPLATE
        or value.get("providerApiVersion") != r.API_VERSION
        or value.get("providerEndpointSha256") != request_sha256(endpoint(subscription_id))
        or value.get("httpMethods") != ["GET"]
        or value.get("paginationComplete") is not True
        or value.get("unrelatedBaselineIdentitySha256") != baseline
        or value.get("unrelatedBaselineSha256") != digest("retention-unrelated-baseline", baseline)
        or not isinstance(observed_at, str)
    ):
        _fail()
    observed_at = cast(str, observed_at)
    if r._parse_instant(observed_at, "retention-absence-observed-time-invalid") <= r._parse_instant(
        r.EXPECTED_REMOVAL_BOUNDARY_UTC, "retention-absence-boundary-invalid"
    ):
        raise r.RetentionVerificationError("retention-absence-observed-before-boundary")
    pages = value.get("inventoryPages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= r.MAX_PAGES:
        _fail()
    pages = cast(list[object], pages)
    expected_request: object = value["providerEndpointSha256"]
    seen_requests: set[str] = set()
    seen_page_contents: set[str] = set()
    hashes: list[str] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != {
            "requestSha256", "recordIdentitySha256", "nextRequestSha256"
        }:
            _fail()
        page = cast(dict[str, object], page)
        request = page["requestSha256"]
        records = page["recordIdentitySha256"]
        next_request = page["nextRequestSha256"]
        if (
            not _is_hash(request) or request != expected_request
            or request in seen_requests
            or not isinstance(records, list)
            or any(not _is_hash(item) for item in records)
            or records != sorted(records)
            or (index == len(pages) - 1 and next_request is not None)
            or (index < len(pages) - 1 and not _is_hash(next_request))
        ):
            _fail()
        records = cast(list[str], records)
        page_digest = digest("retention-page-inventory", records)
        if page_digest in seen_page_contents:
            _fail()
        seen_page_contents.add(page_digest)
        seen_requests.add(cast(str, request))
        hashes.extend(records)
        expected_request = next_request
    hashes.sort()
    if len(set(hashes)) != len(hashes) or not set(hashes) <= set(baseline):
        _fail()
    expected_counts = {
        "deletedInventoryPages": len(pages), "continuationCount": len(pages) - 1,
        "azureGetOperations": len(pages) + 1, "deletedAccountCount": len(hashes),
        "targetCandidates": 0, "currentOnlyRecordCount": 0,
        **dict.fromkeys(MUTATION_FIELDS, 0),
    }
    if any(type(value.get(key)) is not int or value[key] != count
           for key, count in expected_counts.items()):
        _fail()
    expected_observations = [
        {"baselineIdentitySha256": item,
         "status": "present-unchanged" if item in hashes else "absent-unattributed"}
        for item in baseline
    ]
    if (
        value.get("unrelatedObservations") != expected_observations
        or value.get("currentInventorySha256") != digest("retention-current-inventory", hashes)
    ):
        _fail()
    return r.RetentionAbsenceBinding(
        evidence_sha256(value), cast(str, evidence_class), observed_at,
        subscription_correlation, value,
    )


def validate_evidence(
    path: Path, *, subscription_id: str, subscription_correlation: str,
    allow_synthetic: bool,
) -> r.RetentionAbsenceBinding:
    return validate_document(
        r._load_json(path, "retention-absence-evidence-invalid"),
        subscription_id=subscription_id, subscription_correlation=subscription_correlation,
        allow_synthetic=allow_synthetic,
    )


def verify_absence(verifier: r.RetentionVerifier, contract: r.RetentionContract) -> dict[str, object]:
    validate_contract(contract)
    started = verifier.clock()
    if started <= contract.expected_removal_boundary:
        raise r.RetentionVerificationError("retention-boundary-not-reached")
    if verifier.azure_get_operations != 0:
        raise r.RetentionVerificationError("retention-verifier-already-used")
    verifier._verify_subscription(contract)
    url = endpoint(contract.subscription_id)
    seen_requests: set[str] = set()
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_identities: set[str] = set()
    pages: list[dict[str, object]] = []
    while True:
        url = r._safe_next_link(url, contract)
        request = request_sha256(url)
        if request in seen_requests or len(pages) >= r.MAX_PAGES:
            raise r.RetentionVerificationError("retention-pagination-invalid")
        seen_requests.add(request)
        page = verifier._page(url)
        raw_records = page.get("value")
        if not isinstance(raw_records, list):
            raise r.RetentionVerificationError("retention-deleted-inventory-malformed")
        records = [r._record(item, contract) for item in raw_records]
        identities: list[str] = []
        for record in records:
            if record.deleted_record_id in seen_ids or record.name in seen_names:
                raise r.RetentionVerificationError("retention-deleted-inventory-duplicate")
            seen_ids.add(record.deleted_record_id)
            seen_names.add(record.name)
            target_hash_match = r._target_hash(record.original_resource_id) == contract.campaign_identity_sha256
            target_name_match = record.name == contract.account_name
            if target_hash_match or target_name_match:
                raise r.RetentionVerificationError(
                    "retention-target-present" if target_hash_match and target_name_match
                    else "retention-target-attribution-conflict"
                )
            identity = r._unrelated_hash(record.original_resource_id)
            if identity not in contract.unrelated_identity_sha256:
                raise r.RetentionVerificationError("retention-unexpected-current-record")
            if identity in seen_identities:
                raise r.RetentionVerificationError("retention-deleted-inventory-duplicate")
            seen_identities.add(identity)
            identities.append(identity)
        next_link = page.get("nextLink")
        if next_link is not None and next_link != "" and not isinstance(next_link, str):
            raise r.RetentionVerificationError("retention-next-link-invalid")
        next_url = r._safe_next_link(next_link, contract) if isinstance(next_link, str) and next_link else None
        pages.append({
            "requestSha256": request, "recordIdentitySha256": sorted(identities),
            "nextRequestSha256": request_sha256(next_url) if next_url else None,
        })
        if next_url is None:
            break
        url = next_url
    observed_at = verifier.clock()
    if observed_at < started:
        raise r.RetentionVerificationError("retention-observation-clock-regressed")
    document = build_document(
        subscription_id=contract.subscription_id, observed_at=observed_at,
        pages=pages, evidence_class=r.MANAGED_EVIDENCE_CLASS,
        baseline=list(contract.unrelated_identity_sha256),
        campaign_correlation=contract.campaign_correlation,
        generation_correlation=contract.generation_correlation,
        region=contract.region,
        target_identity_sha256=contract.campaign_identity_sha256,
        authoritative_deletion_time=r._utc_text(contract.authoritative_deletion_time),
        expected_removal_boundary=r._utc_text(contract.expected_removal_boundary),
    )
    if (
        contract.campaign_correlation == r.RETENTION_CAMPAIGN_CORRELATION
        and contract.generation_correlation == r.RETENTION_GENERATION_CORRELATION
        and contract.region == r.RETENTION_REGION
        and contract.campaign_identity_sha256 == r.RETENTION_TARGET_IDENTITY_SHA256
        and contract.unrelated_identity_sha256 == r.RETENTION_UNRELATED_IDENTITY_SHA256
        and r._utc_text(contract.authoritative_deletion_time)
        == r.AUTHORITATIVE_DELETION_TIME_UTC
        and r._utc_text(contract.expected_removal_boundary)
        == r.EXPECTED_REMOVAL_BOUNDARY_UTC
    ):
        validate_document(
            document,
            subscription_id=contract.subscription_id,
            subscription_correlation=r._correlation(
                contract.subscription_id, domain="subscription"
            ),
            allow_synthetic=False,
        )
    return document
