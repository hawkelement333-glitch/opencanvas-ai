from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

from infra.milestone_7_8.azure_cli import AzureCliLauncher

API_VERSION = "2024-10-23"
MANAGEMENT_HOST = "management.azure.com"
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 2_000_000
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CORRELATION_PATTERN = re.compile(r"^[a-f0-9]{16}$")
ACCOUNT_NAME_PATTERN = re.compile(r"^[a-z0-9-]{6,50}$")
SUBSCRIPTION_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ABSENCE_EVIDENCE_VERSION = "m7.8-retained-automation-absence-verification-v2"
CURRENT_ABSENCE_EVIDENCE_VERSION = "m7.8-retained-automation-absence-verification-v3"
MANAGED_EVIDENCE_CLASS = "managed-provider-get-only"
SYNTHETIC_EVIDENCE_CLASS = "synthetic-test-fixture"
AUTHORITATIVE_DELETION_TIME_UTC = "2026-08-15T01:09:46.307Z"
EXPECTED_REMOVAL_BOUNDARY_UTC = "2026-09-14T01:09:46.307Z"
RETENTION_CAMPAIGN_CORRELATION = "07e350df451c6bec"
RETENTION_GENERATION_CORRELATION = "599df8555c0781d9"
RETENTION_REGION = "southeastasia"
RETENTION_TARGET_IDENTITY_SHA256 = (
    "70802f6e1464afc66bde5466f7b9f3b36892af96eb5de74e6a6560b717e123fc"
)
RETENTION_UNRELATED_IDENTITY_SHA256 = (
    "695cbab9b5f3c9c685d3060788b4e3c203322ccc34042f7502e60e9c37925359",
    "7784599e8675788d8affdbb71f6dbc6f6ae0780ef5898351eeb424298c4ee9e0",
    "8296a885b417e20d4e0b1ce649a7c7abf94576102b25d159bcd71adfe7add046",
    "e0d171a6cdad7ca8d6de4c8f6c2df640ff5cce098071838576b5af934aa85e1f",
)
ABSENCE_EVIDENCE_FIELDS = {
    "version",
    "evidenceClass",
    "status",
    "subscriptionCorrelation",
    "campaignCorrelation",
    "generationCorrelation",
    "region",
    "observedAtUtc",
    "authoritativeDeletionTimeUtc",
    "expectedRemovalBoundaryUtc",
    "providerReportedDeletionTime",
    "deletionTimeInterpretation",
    "paginationComplete",
    "deletedInventoryPages",
    "deletedAccountCount",
    "targetCandidates",
    "unrelatedDeletedAccountCount",
    "campaignDeletedIdentitySha256",
    "legacyCampaignIdentityHashMatch",
    "unrelatedDeletedIdentitySha256",
    "legacyUnrelatedIdentityHashMatch",
    "azureGetOperations",
    "azureMutationCount",
    "repositoryMutationCount",
    "supportTicketOperationCount",
}


class RetentionVerificationError(RuntimeError):
    """A safe, non-sensitive retention verification failure."""


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
class RetentionContract:
    evidence_version: str
    subscription_id: str
    account_name: str
    region: str
    campaign_correlation: str
    generation_correlation: str
    campaign_identity_sha256: str
    unrelated_identity_sha256: tuple[str, ...]
    authoritative_deletion_time: datetime
    expected_removal_boundary: datetime


@dataclass(frozen=True, slots=True)
class DeletedAccountRecord:
    name: str
    location: str
    deleted_record_id: str
    original_resource_id: str
    deletion_time: str | None


@dataclass(frozen=True, slots=True)
class RetentionAbsenceBinding:
    evidence_sha256: str
    evidence_class: str
    observed_at_utc: str
    subscription_correlation: str
    document: dict[str, object]


def _require_dict(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RetentionVerificationError(code)
    return cast(dict[str, object], value)


def _require_string(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise RetentionVerificationError(code)
    return value


def _load_json(path: Path, code: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RetentionVerificationError(code)
        return _require_dict(json.loads(raw), code)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RetentionVerificationError(code) from exc


def _parse_instant(value: str, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetentionVerificationError(code) from exc
    if parsed.tzinfo is None:
        raise RetentionVerificationError(code)
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _correlation(value: str, *, domain: str) -> str:
    return hashlib.sha256(f"m7.8/{domain}\0{value}".encode()).hexdigest()[:16]


def retention_absence_evidence_v2_sha256(value: dict[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(b"m7.8/retention-absence-evidence/v2\0" + encoded).hexdigest()


def validate_retention_absence_evidence_v2(
    path: Path,
    *,
    subscription_correlation: str,
    allow_synthetic: bool,
) -> RetentionAbsenceBinding:
    value = _load_json(path, "retention-absence-evidence-invalid")
    unrelated = value.get("unrelatedDeletedIdentitySha256")
    observed_at = value.get("observedAtUtc")
    evidence_class = value.get("evidenceClass")
    if (
        set(value) != ABSENCE_EVIDENCE_FIELDS
        or CORRELATION_PATTERN.fullmatch(subscription_correlation) is None
        or value.get("version") != ABSENCE_EVIDENCE_VERSION
        or evidence_class not in {MANAGED_EVIDENCE_CLASS, SYNTHETIC_EVIDENCE_CLASS}
        or (not allow_synthetic and evidence_class != MANAGED_EVIDENCE_CLASS)
        or value.get("status") != "retained-account-absent"
        or value.get("subscriptionCorrelation") != subscription_correlation
        or value.get("campaignCorrelation") != RETENTION_CAMPAIGN_CORRELATION
        or value.get("generationCorrelation") != RETENTION_GENERATION_CORRELATION
        or value.get("region") != RETENTION_REGION
        or not isinstance(observed_at, str)
        or value.get("authoritativeDeletionTimeUtc") != AUTHORITATIVE_DELETION_TIME_UTC
        or value.get("expectedRemovalBoundaryUtc") != EXPECTED_REMOVAL_BOUNDARY_UTC
        or value.get("providerReportedDeletionTime") is not None
        or value.get("deletionTimeInterpretation") is not None
        or value.get("paginationComplete") is not True
        or type(value.get("deletedInventoryPages")) is not int
        or cast(int, value["deletedInventoryPages"]) < 1
        or value.get("deletedAccountCount") != 4
        or value.get("targetCandidates") != 0
        or value.get("unrelatedDeletedAccountCount") != 4
        or value.get("campaignDeletedIdentitySha256")
        != RETENTION_TARGET_IDENTITY_SHA256
        or value.get("legacyCampaignIdentityHashMatch") is not True
        or not isinstance(unrelated, list)
        or tuple(unrelated) != RETENTION_UNRELATED_IDENTITY_SHA256
        or value.get("legacyUnrelatedIdentityHashMatch") is not True
        or type(value.get("azureGetOperations")) is not int
        or cast(int, value["azureGetOperations"]) < 2
        or value.get("azureMutationCount") != 0
        or value.get("repositoryMutationCount") != 0
        or value.get("supportTicketOperationCount") != 0
    ):
        raise RetentionVerificationError("retention-absence-evidence-not-exact")
    if _parse_instant(
        observed_at, "retention-absence-observed-time-invalid"
    ) < _parse_instant(
        EXPECTED_REMOVAL_BOUNDARY_UTC,
        "retention-absence-boundary-invalid",
    ):
        raise RetentionVerificationError("retention-absence-observed-before-boundary")
    return RetentionAbsenceBinding(
        evidence_sha256=retention_absence_evidence_v2_sha256(value),
        evidence_class=evidence_class,
        observed_at_utc=observed_at,
        subscription_correlation=subscription_correlation,
        document=value,
    )


def retention_absence_evidence_sha256(value: dict[str, object]) -> str:
    from infra.milestone_7_8.retention_v3 import evidence_sha256

    return evidence_sha256(value)


def validate_retention_absence_evidence(
    path: Path,
    *,
    subscription_correlation: str,
    subscription_id: str,
    allow_synthetic: bool,
) -> RetentionAbsenceBinding:
    from infra.milestone_7_8.retention_v3 import validate_evidence

    return validate_evidence(
        path,
        subscription_id=subscription_id,
        subscription_correlation=subscription_correlation,
        allow_synthetic=allow_synthetic,
    )


def _target_deletion_instant(value: str) -> tuple[datetime, str]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetentionVerificationError(
            "retention-target-deletion-time-invalid"
        ) from exc
    if parsed.tzinfo is None:
        return (
            parsed.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(UTC),
            "provider-naive-central-daylight-time-utc-minus-05",
        )
    return parsed.astimezone(UTC), "provider-rfc3339-instant"


def load_contract(
    runtime_path: Path,
    evidence_path: Path,
    *,
    authoritative_deletion_time: str,
) -> RetentionContract:
    runtime = _load_json(runtime_path, "retention-runtime-invalid")
    evidence = _load_json(evidence_path, "retention-evidence-invalid")
    subscription_id = _require_string(
        runtime.get("subscriptionId"), "retention-runtime-subscription-invalid"
    ).casefold()
    account_name = _require_string(
        runtime.get("automationAccountName"), "retention-runtime-account-invalid"
    ).casefold()
    region = _require_string(
        runtime.get("cleanupRegion"), "retention-runtime-region-invalid"
    )
    if (
        SUBSCRIPTION_PATTERN.fullmatch(subscription_id) is None
        or ACCOUNT_NAME_PATTERN.fullmatch(account_name) is None
        or re.fullmatch(r"[a-z0-9]+", region) is None
    ):
        raise RetentionVerificationError("retention-runtime-binding-invalid")
    campaign_correlation = _require_string(
        evidence.get("campaignCorrelation"), "retention-campaign-correlation-invalid"
    )
    generation_correlation = _require_string(
        evidence.get("generationCorrelation"),
        "retention-generation-correlation-invalid",
    )
    identity_hash = _require_string(
        evidence.get("campaignDeletedIdentitySha256"), "retention-target-hash-invalid"
    )
    unrelated_value = evidence.get("unrelatedDeletedIdentitySha256")
    evidence_version = _require_string(
        evidence.get("version"), "retention-evidence-version-invalid"
    )
    if (
        evidence_version
        not in {
            "m7.8-automation-retention-remediation-v1",
            "m7.8-automation-retention-live-reconciliation-v1",
        }
        or evidence.get("region") != region
        or CORRELATION_PATTERN.fullmatch(campaign_correlation) is None
        or CORRELATION_PATTERN.fullmatch(generation_correlation) is None
        or HASH_PATTERN.fullmatch(identity_hash) is None
        or not isinstance(unrelated_value, list)
        or len(unrelated_value) != 4
        or any(
            not isinstance(item, str) or HASH_PATTERN.fullmatch(item) is None
            for item in unrelated_value
        )
        or len(set(unrelated_value)) != 4
    ):
        raise RetentionVerificationError("retention-evidence-binding-invalid")
    inventories = _require_dict(
        evidence.get("inventories"), "retention-evidence-inventory-invalid"
    )
    deleted = _require_dict(
        inventories.get("deleted"), "retention-evidence-inventory-invalid"
    )
    if (
        deleted.get("afterTotalCount") != 5
        or deleted.get("afterCampaignCount") != 1
        or deleted.get("unrelatedCount") != 4
    ):
        raise RetentionVerificationError("retention-evidence-inventory-invalid")
    deletion_time = _parse_instant(
        authoritative_deletion_time, "retention-authoritative-time-invalid"
    )
    expected_boundary = deletion_time + timedelta(days=30)
    if evidence_version == "m7.8-automation-retention-live-reconciliation-v1" and (
        evidence.get("authoritativeDeletionTimeUtc") != _utc_text(deletion_time)
        or evidence.get("expectedRemovalBoundaryUtc") != _utc_text(expected_boundary)
        or evidence.get("status") != "provider-retained"
        or evidence.get("azureMutationCount") != 0
    ):
        raise RetentionVerificationError("retention-reconciliation-evidence-invalid")
    return RetentionContract(
        evidence_version=evidence_version,
        subscription_id=subscription_id,
        account_name=account_name,
        region=region,
        campaign_correlation=campaign_correlation,
        generation_correlation=generation_correlation,
        campaign_identity_sha256=identity_hash,
        unrelated_identity_sha256=tuple(sorted(cast(list[str], unrelated_value))),
        authoritative_deletion_time=deletion_time,
        expected_removal_boundary=expected_boundary,
    )


def _ci_get(value: dict[str, object], name: str) -> object:
    expected = name.casefold()
    if len({key.casefold() for key in value}) != len(value):
        raise RetentionVerificationError("retention-record-ambiguous-fields")
    for key, item in value.items():
        if key.casefold() == expected:
            return item
    return None


def _normalized_region(value: object) -> str:
    if not isinstance(value, str):
        raise RetentionVerificationError("retention-record-location-invalid")
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if not normalized:
        raise RetentionVerificationError("retention-record-location-invalid")
    return normalized


def _validate_arm_id(
    value: object,
    *,
    subscription_id: str,
    suffix: str,
    code: str,
) -> str:
    identifier = _require_string(value, code)
    parsed = urlparse(identifier)
    normalized = identifier.casefold().rstrip("/")
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not normalized.startswith(f"/subscriptions/{subscription_id}/")
        or not normalized.endswith(suffix.casefold())
    ):
        raise RetentionVerificationError(code)
    return normalized


def _record(value: object, contract: RetentionContract) -> DeletedAccountRecord:
    item = _require_dict(value, "retention-record-invalid")
    properties = _require_dict(
        _ci_get(item, "properties"), "retention-record-properties-invalid"
    )
    name = _require_string(
        _ci_get(item, "name"), "retention-record-name-invalid"
    ).casefold()
    if ACCOUNT_NAME_PATTERN.fullmatch(name) is None:
        raise RetentionVerificationError("retention-record-name-invalid")
    deleted_id = _validate_arm_id(
        _ci_get(item, "id"),
        subscription_id=contract.subscription_id,
        suffix=f"/deletedAutomationAccounts/{name}",
        code="retention-deleted-record-id-invalid",
    )
    original_id = _validate_arm_id(
        _ci_get(properties, "automationAccountResourceId"),
        subscription_id=contract.subscription_id,
        suffix=f"/automationAccounts/{name}",
        code="retention-original-resource-id-invalid",
    )
    expected_deleted = (
        f"/subscriptions/{contract.subscription_id}/providers/"
        f"microsoft.automation/deletedautomationaccounts/{name}"
    )
    if deleted_id != expected_deleted:
        raise RetentionVerificationError("retention-deleted-record-id-invalid")
    if re.fullmatch(
        rf"/subscriptions/{re.escape(contract.subscription_id)}/resourcegroups/"
        rf"[^/]+/providers/microsoft\.automation/automationaccounts/{re.escape(name)}",
        original_id,
    ) is None:
        raise RetentionVerificationError("retention-original-resource-id-invalid")
    location_value = _ci_get(properties, "location")
    if location_value is None:
        location_value = _ci_get(item, "location")
    deletion_time_value = _ci_get(properties, "deletionTime")
    deleted_time_value = _ci_get(properties, "deletedTime")
    if (
        deletion_time_value is not None
        and deleted_time_value is not None
        and deletion_time_value != deleted_time_value
    ):
        raise RetentionVerificationError("retention-deletion-time-conflict")
    if deletion_time_value is None:
        deletion_time_value = deleted_time_value
    deletion_time = (
        deletion_time_value if isinstance(deletion_time_value, str) else None
    )
    return DeletedAccountRecord(
        name=name,
        location=_normalized_region(location_value),
        deleted_record_id=deleted_id,
        original_resource_id=original_id,
        deletion_time=deletion_time,
    )


def _target_hash(resource_id: str) -> str:
    return hashlib.sha256(
        b"m7.8/deleted-automation-account/v1\0" + resource_id.encode()
    ).hexdigest()


def _unrelated_hash(resource_id: str) -> str:
    return hashlib.sha256(
        b"m7.8/unrelated-deleted-automation-account/v1\0" + resource_id.encode()
    ).hexdigest()


def _safe_next_link(value: str, contract: RetentionContract) -> str:
    parsed = urlparse(value)
    expected_path = (
        f"/subscriptions/{contract.subscription_id}/providers/"
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
        raise RetentionVerificationError("retention-next-link-invalid")
    return value


class RetentionVerifier:
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
            raise RetentionVerificationError(code) from exc
        if (
            result.returncode != 0
            or len(result.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES
        ):
            raise RetentionVerificationError(code)
        self.azure_get_operations += 1
        return result.stdout

    def _verify_subscription(self, contract: RetentionContract) -> None:
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
            "retention-subscription-read-failed",
        ).strip()
        if observed.casefold() != contract.subscription_id:
            raise RetentionVerificationError("retention-subscription-mismatch")

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
            "retention-deleted-inventory-read-failed",
        )
        try:
            return _require_dict(
                json.loads(raw), "retention-deleted-inventory-malformed"
            )
        except json.JSONDecodeError as exc:
            raise RetentionVerificationError(
                "retention-deleted-inventory-malformed"
            ) from exc

    def _inventory(
        self, contract: RetentionContract
    ) -> tuple[list[DeletedAccountRecord], int]:
        url = (
            f"https://{MANAGEMENT_HOST}/subscriptions/{contract.subscription_id}/providers/"
            f"Microsoft.Automation/deletedAutomationAccounts?api-version={API_VERSION}"
        )
        seen: set[str] = set()
        values: list[object] = []
        pages = 0
        while True:
            url = _safe_next_link(url, contract)
            if url in seen or pages >= MAX_PAGES:
                raise RetentionVerificationError("retention-pagination-invalid")
            seen.add(url)
            page = self._page(url)
            page_values = page.get("value")
            if not isinstance(page_values, list):
                raise RetentionVerificationError(
                    "retention-deleted-inventory-malformed"
                )
            values.extend(page_values)
            pages += 1
            next_link = page.get("nextLink")
            if next_link in {None, ""}:
                break
            if not isinstance(next_link, str):
                raise RetentionVerificationError("retention-next-link-invalid")
            url = next_link
        records = [_record(value, contract) for value in values]
        if len({record.deleted_record_id for record in records}) != len(records):
            raise RetentionVerificationError("retention-deleted-inventory-duplicate")
        return records, pages

    def verify(
        self,
        contract: RetentionContract,
        *,
        expect: str,
        reconcile_legacy_binding: bool = False,
    ) -> dict[str, object]:
        if expect == "absent":
            from infra.milestone_7_8.retention_v3 import verify_absence

            if reconcile_legacy_binding:
                raise RetentionVerificationError("retention-reconciliation-mode-invalid")
            return verify_absence(self, contract)
        observed_at = self.clock().astimezone(UTC)
        if reconcile_legacy_binding and (
            expect != "present"
            or contract.evidence_version != "m7.8-automation-retention-remediation-v1"
        ):
            raise RetentionVerificationError("retention-reconciliation-mode-invalid")
        if expect == "absent" and observed_at < contract.expected_removal_boundary:
            raise RetentionVerificationError("retention-boundary-not-reached")
        self._verify_subscription(contract)
        records, pages = self._inventory(contract)
        target_by_hash = [
            record
            for record in records
            if _target_hash(record.original_resource_id)
            == contract.campaign_identity_sha256
        ]
        target_by_name = [
            record for record in records if record.name == contract.account_name
        ]
        if len(target_by_hash) > 1 or len(target_by_name) > 1:
            raise RetentionVerificationError("retention-target-not-unique")
        binding_matches = {record.deleted_record_id for record in target_by_hash} == {
            record.deleted_record_id for record in target_by_name
        }
        if not binding_matches and not (
            reconcile_legacy_binding
            and len(target_by_hash) == 0
            and len(target_by_name) == 1
        ):
            raise RetentionVerificationError("retention-target-attribution-conflict")
        targets = target_by_name if reconcile_legacy_binding else target_by_hash
        target_ids = {record.deleted_record_id for record in targets}
        unrelated = tuple(
            sorted(
                _unrelated_hash(record.original_resource_id)
                for record in records
                if record.deleted_record_id not in target_ids
            )
        )
        unrelated_matches = unrelated == contract.unrelated_identity_sha256
        if not unrelated_matches and not reconcile_legacy_binding:
            raise RetentionVerificationError("retention-unrelated-inventory-drift")
        expected_total = 5 if expect == "present" else 4
        expected_target_count = 1 if expect == "present" else 0
        if len(records) != expected_total or len(targets) != expected_target_count:
            raise RetentionVerificationError("retention-inventory-count-mismatch")
        corrected_identity_hash = contract.campaign_identity_sha256
        provider_reported_deletion_time: str | None = None
        deletion_time_interpretation: str | None = None
        if targets:
            target = targets[0]
            if target.location != contract.region:
                raise RetentionVerificationError("retention-target-location-mismatch")
            if target.deletion_time is None:
                raise RetentionVerificationError(
                    "retention-target-deletion-time-invalid"
                )
            observed_deletion_time, deletion_time_interpretation = (
                _target_deletion_instant(target.deletion_time)
            )
            if observed_deletion_time != contract.authoritative_deletion_time:
                raise RetentionVerificationError(
                    "retention-target-deletion-time-mismatch"
                )
            provider_reported_deletion_time = target.deletion_time
            corrected_identity_hash = _target_hash(target.original_resource_id)
        return {
            "version": ABSENCE_EVIDENCE_VERSION,
            "evidenceClass": MANAGED_EVIDENCE_CLASS,
            "status": "provider-retained" if targets else "retained-account-absent",
            "subscriptionCorrelation": _correlation(
                contract.subscription_id, domain="subscription"
            ),
            "campaignCorrelation": contract.campaign_correlation,
            "generationCorrelation": contract.generation_correlation,
            "region": contract.region,
            "observedAtUtc": _utc_text(observed_at),
            "authoritativeDeletionTimeUtc": _utc_text(
                contract.authoritative_deletion_time
            ),
            "expectedRemovalBoundaryUtc": _utc_text(contract.expected_removal_boundary),
            "providerReportedDeletionTime": provider_reported_deletion_time,
            "deletionTimeInterpretation": deletion_time_interpretation,
            "paginationComplete": True,
            "deletedInventoryPages": pages,
            "deletedAccountCount": len(records),
            "targetCandidates": len(targets),
            "unrelatedDeletedAccountCount": len(unrelated),
            "campaignDeletedIdentitySha256": corrected_identity_hash,
            "legacyCampaignIdentityHashMatch": binding_matches,
            "unrelatedDeletedIdentitySha256": list(unrelated),
            "legacyUnrelatedIdentityHashMatch": unrelated_matches,
            "azureGetOperations": self.azure_get_operations,
            "azureMutationCount": 0,
            "repositoryMutationCount": 0,
            "supportTicketOperationCount": 0,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the exact M7.8 retained Automation account with Azure GETs only"
    )
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--authoritative-deletion-time", required=True)
    parser.add_argument("--expect", choices=("present", "absent"), required=True)
    parser.add_argument("--reconcile-legacy-binding", action="store_true")
    arguments = parser.parse_args()
    try:
        contract = load_contract(
            arguments.runtime,
            arguments.evidence,
            authoritative_deletion_time=arguments.authoritative_deletion_time,
        )
        result = RetentionVerifier(AzureCliLauncher.resolve()).verify(
            contract,
            expect=arguments.expect,
            reconcile_legacy_binding=arguments.reconcile_legacy_binding,
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except RetentionVerificationError as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
