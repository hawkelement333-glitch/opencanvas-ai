"""Versioned, default-deny managed-binding contracts for Milestone 7.7.

The historical Checkpoint 7 matrix remains immutable.  This module validates a
separate one-run overlay, binds it to the historical integrity value, and
provides replay-resistant authorization receipts.  Loading a contract never
grants execution or mutation authority.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID, uuid5

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
    validate_schema,
)
from preflight.milestone_7_7.operation_contracts import (
    OPERATION_IDS,
    load_operation_contract_matrix,
)

ROOT: Final = Path(__file__).resolve().parent
REPOSITORY_ROOT: Final = ROOT.parents[1]
INFRASTRUCTURE_ROOT: Final = REPOSITORY_ROOT / "infra" / "milestone_7_7"
MANIFEST_PATH: Final = (
    INFRASTRUCTURE_ROOT / "manifests" / "managed-binding.contract.json"
)
MANIFEST_SCHEMA_PATH: Final = (
    INFRASTRUCTURE_ROOT / "manifests" / "managed-binding.schema.json"
)
CLEANUP_RUNBOOK_PATH: Final = (
    INFRASTRUCTURE_ROOT / "scripts" / "Remove-Mobius77Staging.ps1"
)
OVERLAY_PATH: Final = ROOT / "managed-binding-operation-contracts.json"
OVERLAY_SCHEMA_PATH: Final = ROOT / "managed-binding-operation-contracts.schema.json"

AUTHORIZATION_SOURCE_HEAD: Final = "11564669bd5b40a88fdbf434c8137b063305eb4b"
HISTORICAL_MATRIX_SHA256: Final = (
    "100293931dcc71bb069e4f6fe06228360e0953b3b756544a555941d81bf8d6bc"
)
MANAGED_BINDING_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-resource-contract/v1\0"
)
OPERATION_OVERLAY_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-operation-overlay/v1\0"
)
AUTHORIZATION_LEDGER_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-one-run-ledger/v1\0"
)
AUTHORIZATION_RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/managed-binding-operation-receipt/v1\0"
)
CONTRACT_VERSION: Final = "m7.7-managed-binding-v1"
AUTOMATION_BINDING_NAMESPACE: Final = UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")
LEGACY_CLEANUP_BINDING_CONTRACT_VERSION: Final = "m7.7-automation-cleanup-binding-v2"
GENERATION_THREE_CLEANUP_BINDING_CONTRACT_VERSION: Final = (
    "m7.7-automation-cleanup-binding-v3"
)
CLEANUP_BINDING_CONTRACT_VERSION: Final = "m7.7-automation-cleanup-binding-v4"
CLEANUP_BINDING_GENERATION: Final = 4
TOMBSTONED_CLEANUP_BINDING_ID: Final = "158cac88-5679-5804-9f4d-854520bbb635"
TOMBSTONED_GENERATION_TWO_CLEANUP_BINDING_ID: Final = (
    "b74c6cfe-995e-5107-9e42-4f7f76b76742"
)
TOMBSTONED_DEADLINE_RECOVERY_BINDING_ID: Final = "f61544fe-cd79-5247-ac8b-ee9697b6ffd6"
TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID: Final = (
    "ecdbb32f-9134-5697-85f9-d569ba57454b"
)
TOMBSTONED_THIRD_DEADLINE_RECOVERY_BINDING_ID: Final = (
    "d83b4107-54e0-57a4-b650-fe0b556132d2"
)
TOMBSTONED_FOURTH_DEADLINE_RECOVERY_BINDING_ID: Final = (
    "5ffc55c1-7a88-5231-b0d1-e76ee95d057e"
)
TOMBSTONED_FIFTH_DEADLINE_RECOVERY_BINDING_ID: Final = (
    "a5429a32-87e3-5963-8c3a-bef85e777ed5"
)
TOMBSTONED_POST_FIRED_CLEANUP_BINDING_ID: Final = "f29ca20d-cd14-57d9-b99b-fd6b04406166"
GENERATION_TWO_CLEANUP_BINDING_EPOCH_UTC: Final = "2026-08-08T12:15:00Z"
GENERATION_THREE_CLEANUP_BINDING_EPOCH_UTC: Final = "2026-08-09T08:00:00Z"
TOMBSTONED_GENERATION_THREE_CLEANUP_BINDING_ID: Final = (
    "12f27fa6-2cd5-548d-be20-c6e03a5e19d3"
)
TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_EPOCH_UTC: Final = "2026-08-11T03:45:00Z"
TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_ID: Final = (
    "34b1d170-652b-505a-9cc1-b8177b872ff0"
)
ACTIVE_CLEANUP_BINDING_EPOCH_UTC: Final = "2026-08-11T19:30:00Z"
ACTIVE_CLEANUP_BINDING_ID: Final = "57e1b300-a91a-5629-995e-d587fd0e0cdb"
CLEANUP_AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup-recovery"
CORRUPTED_CLEANUP_AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup"
CLEANUP_SCHEDULE: Final = "schedule-mobius77-cleanup-g4"
GENERATION_THREE_CLEANUP_SCHEDULE: Final = "schedule-mobius77-cleanup-g3"
LEGACY_CLEANUP_SCHEDULE: Final = "schedule-mobius77-cleanup"
CLEANUP_BINDING_TOMBSTONE_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/automation-cleanup-binding-tombstone/v1\0"
)
OVERLAY_VERSION: Final = "mobius.milestone-7.7.managed-binding-operation-overlay.v1"
LEDGER_VERSION: Final = "mobius.milestone-7.7.managed-binding-one-run-ledger.v1"
AUTHORIZATION_ID: Final = "m7.7-managed-binding-closeout-20260731"
STAGING_LOCATION: Final = "southcentralus"
CLEANUP_LOCATION: Final = "westus"
MAXIMUM_LEDGER_LIFETIME_SECONDS: Final = 86_400
MAXIMUM_CONTRACT_BYTES: Final = 524_288
HEX_SHA40 = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
IMAGE_PUBLICATION_REPOSITORY: Final = "opencanvas-api"
IMAGE_PUBLICATION_PLATFORM: Final = "linux/amd64"
HISTORICAL_IMAGE_SOURCE_COMMIT: Final = "948e81b5bf34f5c2f5069ee40568beb09cb997d3"
API_IMAGE_BUILD_INPUTS: Final = (
    "apps/api/Dockerfile",
    "apps/api/Dockerfile.dockerignore",
    "apps/api/pyproject.toml",
    "apps/api/build-requirements.lock",
    "apps/api/requirements.lock",
    "apps/api/opencanvas_api",
    "apps/api/alembic.ini",
    "apps/api/alembic",
    "apps/api/scripts",
    "LICENSE",
    "COPYRIGHT",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
)

EXPECTED_RESOURCE_GROUPS: Final = {
    "cleanupControl": "rg-solarplexus-mobius-77-cleanup-control",
    "containerAppsInfrastructure": (
        "rg-solarplexus-mobius-77-containerapps-infrastructure"
    ),
    "target": "rg-solarplexus-mobius-77-staging",
}
EXPECTED_SECRET_BINDINGS: Final = (
    ("openai-api-key", "openai-api-key", "OPENAI_API_KEY"),
    (
        "opencanvas-smtp-username",
        "opencanvas-smtp-username",
        "OPENCANVAS_SMTP_USERNAME",
    ),
    (
        "opencanvas-smtp-password",
        "opencanvas-smtp-password",
        "OPENCANVAS_SMTP_PASSWORD",
    ),
    (
        "opencanvas-session-secret",
        "opencanvas-session-secret",
        "OPENCANVAS_SESSION_SECRET",
    ),
    (
        "opencanvas-invitation-secret",
        "opencanvas-invitation-secret",
        "OPENCANVAS_INVITATION_SECRET",
    ),
    (
        "opencanvas-upload-capability-secret",
        "opencanvas-upload-capability-secret",
        "OPENCANVAS_UPLOAD_CAPABILITY_SECRET",
    ),
    (
        "opencanvas-scanner-result-secret",
        "opencanvas-scanner-result-secret",
        "OPENCANVAS_SCANNER_RESULT_SECRET",
    ),
    (
        "opencanvas-rate-limit-hmac-secret",
        "opencanvas-rate-limit-hmac-secret",
        "OPENCANVAS_SHARED_RATE_LIMIT_HMAC_SECRET",
    ),
    (
        "opencanvas-telemetry-token",
        "opencanvas-telemetry-token",
        "OPENCANVAS_TELEMETRY_AUTH_TOKEN",
    ),
    (
        "opencanvas-telemetry-pseudonymization-secret",
        "opencanvas-telemetry-pseudonymization-secret",
        "OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET",
    ),
    (
        "opencanvas-observability-operator-user-ids",
        "opencanvas-observability-operator-user-ids",
        "OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS",
    ),
)
EXPECTED_PROVIDER_REGISTRATIONS: Final = (
    "Microsoft.App",
    "Microsoft.Authorization",
    "Microsoft.Automation",
    "Microsoft.Cache",
    "Microsoft.ContainerRegistry",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.EventGrid",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.OperationalInsights",
    "Microsoft.Resources",
    "Microsoft.Security",
    "Microsoft.Storage",
)
EXPECTED_LIFECYCLE_OPERATIONS: Final = (
    "pre-secret-provisioning",
    "private-path-verification",
    "publish-api-image",
    "reconcile-already-pushed-publication",
    "post-secret-provisioning",
    "temporary-authority-revocation",
    "cleanup",
    "zero-residue-verification",
)


def _copy_json(value: JsonValue) -> JsonValue:
    return copy.deepcopy(value)


def _as_object(value: JsonValue, location: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ContractError(f"{location}: value must be an object")
    return value


def _as_array(value: JsonValue, location: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ContractError(f"{location}: value must be an array")
    return value


def _parse_utc(value: JsonValue, location: str) -> datetime:
    if not isinstance(value, str) or RFC3339_UTC.fullmatch(value) is None:
        raise ContractError(f"{location}: exact RFC3339 UTC timestamp required")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ContractError(f"{location}: timestamp is invalid") from None


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ContractError("UTC timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_no_private_material(value: JsonValue) -> None:
    serialized = canonical_bytes(value).decode("utf-8")
    lowered = serialized.casefold()
    forbidden = (
        "/subscriptions/",
        "opencanvas_openai_api_key",
        "-----begin ",
        "bearer ",
        "c:\\users\\",
        "/home/",
        "@gmail.",
        "sharedaccesssignature=",
        "accountkey=",
    )
    for marker in forbidden:
        if marker in lowered:
            raise ContractError("managed-binding contract contains prohibited material")


def managed_binding_integrity_sha256(value: JsonValue) -> str:
    digest = integrity_sha256(value, MANAGED_BINDING_DOMAIN)
    if not isinstance(digest, str):
        raise ContractError("managed-binding integrity is malformed")
    return digest


def cleanup_runbook_sha256(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_azure_resource_id(value: str) -> str:
    """Normalize a complete Azure resource identifier for deterministic binding IDs."""
    if not isinstance(value, str):
        raise ContractError("cleanup binding resource identifier must be text")
    normalized = value.strip().replace("\\", "/").rstrip("/").casefold()
    if (
        not normalized.startswith("/subscriptions/")
        or "//" in normalized
        or any(marker in normalized for marker in ("?", "#", "\x00"))
    ):
        raise ContractError("cleanup binding resource identifier is malformed")
    return normalized


def _normalize_cleanup_binding_epoch(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise ContractError("cleanup binding epoch is malformed") from None
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ContractError("cleanup binding epoch is malformed")
    return value.casefold()


def deterministic_cleanup_binding_id(
    *,
    generation: int,
    automation_account_id: str,
    runbook_resource_id: str,
    schedule_resource_id: str,
    target_resource_group_id: str,
    cleanup_authorized: bool,
    binding_epoch_utc: str | None = None,
) -> str:
    """Return the closed, versioned Azure Automation job-schedule ID.

    Generation one intentionally preserves the historical Bicep ``guid`` input.
    Generations two through four normalize every resource identifier and bind the
    complete cleanup contract so tombstoned children are never retried. A
    deadline recovery adds its fixed UTC epoch. Generation three moves the
    post-cleanup reprovisions onto generation-specific schedule namespaces.
    """
    historical_account = automation_account_id.strip().replace("\\", "/").rstrip("/")
    historical_runbook = runbook_resource_id.strip().replace("\\", "/").rstrip("/")
    historical_schedule = schedule_resource_id.strip().replace("\\", "/").rstrip("/")
    account = normalize_azure_resource_id(automation_account_id)
    runbook = normalize_azure_resource_id(runbook_resource_id)
    schedule = normalize_azure_resource_id(schedule_resource_id)
    target = normalize_azure_resource_id(target_resource_group_id)
    if generation == 1:
        if binding_epoch_utc is not None:
            raise ContractError("cleanup binding generation one rejects an epoch")
        return str(
            uuid5(
                AUTOMATION_BINDING_NAMESPACE,
                "-".join(
                    (
                        historical_account,
                        historical_runbook.rsplit("/", 1)[-1],
                        historical_schedule.rsplit("/", 1)[-1],
                    )
                ),
            )
        )
    contract_versions = {
        2: LEGACY_CLEANUP_BINDING_CONTRACT_VERSION,
        3: GENERATION_THREE_CLEANUP_BINDING_CONTRACT_VERSION,
        4: CLEANUP_BINDING_CONTRACT_VERSION,
    }
    contract_version = contract_versions.get(generation)
    if contract_version is None:
        raise ContractError("cleanup binding generation is not authorized")
    components = [
        account,
        runbook,
        schedule,
        target,
        contract_version,
        f"cleanup-binding-generation-{generation}",
        f"cleanupauthorized={str(cleanup_authorized).casefold()}",
    ]
    if binding_epoch_utc is not None:
        components.append(
            f"bindingepoch={_normalize_cleanup_binding_epoch(binding_epoch_utc)}"
        )
    return str(
        uuid5(
            AUTOMATION_BINDING_NAMESPACE,
            "-".join(components),
        )
    )


def cleanup_binding_id_for_subscription(
    subscription_id: str,
    generation: int = CLEANUP_BINDING_GENERATION,
    *,
    binding_epoch_utc: str | None = None,
) -> str:
    """Construct the deterministic cleanup binding ID without persisting the subscription."""
    if not isinstance(subscription_id, str) or not subscription_id.strip():
        raise ContractError("cleanup binding subscription identifier is malformed")
    root = f"/subscriptions/{subscription_id.strip()}/resourceGroups"
    account = (
        f"{root}/rg-solarplexus-mobius-77-cleanup-control/providers/"
        f"Microsoft.Automation/automationAccounts/{CLEANUP_AUTOMATION_ACCOUNT}"
    )
    return deterministic_cleanup_binding_id(
        generation=generation,
        automation_account_id=account,
        runbook_resource_id=f"{account}/runbooks/Remove-Mobius77Staging",
        schedule_resource_id=(
            f"{account}/schedules/"
            f"{CLEANUP_SCHEDULE if generation == 4 else GENERATION_THREE_CLEANUP_SCHEDULE if generation == 3 else LEGACY_CLEANUP_SCHEDULE}"
        ),
        target_resource_group_id=(
            f"{root}/rg-solarplexus-mobius-77-cleanup-control/providers/"
            "Microsoft.Resources/resourceGroups/rg-solarplexus-mobius-77-staging"
        ),
        cleanup_authorized=True,
        binding_epoch_utc=(
            binding_epoch_utc
            if binding_epoch_utc is not None
            else ACTIVE_CLEANUP_BINDING_EPOCH_UTC
            if generation == CLEANUP_BINDING_GENERATION
            else GENERATION_THREE_CLEANUP_BINDING_EPOCH_UTC
            if generation == 3
            else GENERATION_TWO_CLEANUP_BINDING_EPOCH_UTC
            if generation == 2
            else None
        ),
    )


def cleanup_binding_tombstone_integrity(value: dict[str, JsonValue]) -> str:
    digest = integrity_sha256(value, CLEANUP_BINDING_TOMBSTONE_DOMAIN)
    if not isinstance(digest, str):
        raise ContractError("cleanup binding tombstone integrity is malformed")
    return digest


def operation_overlay_integrity_sha256(value: dict[str, JsonValue]) -> str:
    body = {
        key: _copy_json(item)
        for key, item in value.items()
        if key != "contractIntegritySha256"
    }
    digest = integrity_sha256(body, OPERATION_OVERLAY_DOMAIN)
    if not isinstance(digest, str):
        raise ContractError("operation overlay integrity is malformed")
    return digest


def authorization_ledger_integrity_sha256(value: dict[str, JsonValue]) -> str:
    body = {
        key: _copy_json(item)
        for key, item in value.items()
        if key != "ledgerIntegritySha256"
    }
    digest = integrity_sha256(body, AUTHORIZATION_LEDGER_DOMAIN)
    if not isinstance(digest, str):
        raise ContractError("authorization ledger integrity is malformed")
    return digest


def validate_managed_binding_contract(value: JsonValue) -> dict[str, JsonValue]:
    contract = _as_object(_copy_json(value), "$")
    schema = _as_object(load_json(MANIFEST_SCHEMA_PATH), "$schema")
    validate_schema(contract, schema)
    if len(canonical_bytes(contract)) > MAXIMUM_CONTRACT_BYTES:
        raise ContractError("managed-binding contract exceeds its byte limit")
    _assert_no_private_material(contract)

    if contract["contractVersion"] != CONTRACT_VERSION:
        raise ContractError("managed-binding contract version differs")
    if contract["authorizationSourceHead"] != AUTHORIZATION_SOURCE_HEAD:
        raise ContractError("managed-binding authorization source differs")
    if contract["location"] != STAGING_LOCATION:
        raise ContractError("managed-binding region differs")
    if contract["cleanupLocation"] != CLEANUP_LOCATION:
        raise ContractError("managed-binding cleanup region differs")
    if contract["redisLocation"] != "australiacentral":
        raise ContractError("managed-binding Redis region differs")
    if contract["resourceGroups"] != EXPECTED_RESOURCE_GROUPS:
        raise ContractError("managed-binding resource groups differ")
    cleanup_execution = _as_object(contract["cleanupExecution"], "$.cleanupExecution")
    expected_cleanup_execution = {
        "activeBindingId": ACTIVE_CLEANUP_BINDING_ID,
        "absenceVerificationSeconds": 300,
        "authorizationParameter": "CleanupAuthorized",
        "authorizationValue": True,
        "bindingContractVersion": CLEANUP_BINDING_CONTRACT_VERSION,
        "bindingGeneration": CLEANUP_BINDING_GENERATION,
        "corruptedAutomationAccount": CORRUPTED_CLEANUP_AUTOMATION_ACCOUNT,
        "cleanupContributorRoleDefinitionId": ("b24988ac-6180-42a0-ab88-20f7382dd24c"),
        "cleanupPrincipalFingerprintSha256": (
            "7bae422a2ef6a418379af13fc19f53a195ccc80be0504c531391e6e46f048be3"
        ),
        "deadlineUtc": ACTIVE_CLEANUP_BINDING_EPOCH_UTC,
        "deletionWaitSeconds": 2700,
        "launchGraceSeconds": 1800,
        "publishedContentSha256": cleanup_runbook_sha256(
            CLEANUP_RUNBOOK_PATH.read_text(encoding="utf-8")
        ),
        "subscriptionFingerprint": (
            "f4493115ce6375cf0e5d0616bede57126075fdb27ac78ea0ba7e0085252a7028"
        ),
        "targetParameter": "TargetResourceGroupName",
        "targetResourceGroup": "rg-solarplexus-mobius-77-staging",
        "targetResourceGroupId": "resourceGroups/rg-solarplexus-mobius-77-staging",
        "runbookResourceId": (
            f"Microsoft.Automation/automationAccounts/{CLEANUP_AUTOMATION_ACCOUNT}/"
            "runbooks/Remove-Mobius77Staging"
        ),
        "scheduleResourceId": (
            f"Microsoft.Automation/automationAccounts/{CLEANUP_AUTOMATION_ACCOUNT}/"
            f"schedules/{CLEANUP_SCHEDULE}"
        ),
        "tombstonedBindingIds": [
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v1",
                "bindingGeneration": 1,
                "bindingId": TOMBSTONED_CLEANUP_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "conflict",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "1a61c64e7749f4d81864cc3d95463d8ffc0dcc90926289497495750885b4f571"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_GENERATION_TWO_CLEANUP_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "conflict",
                "deletionStatus": "not-attempted",
                "evidenceIntegritySha256": (
                    "935e9e40975eb5bb23c59e41d4d56ff6609e685884b3bfa18b8f604231be202c"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_DEADLINE_RECOVERY_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "conflict",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "212f44df4720ead2b84e7e2b1aa2928a5eae0eb81ad8ebc51779cf1cc85a2ad5"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_SECOND_DEADLINE_RECOVERY_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "cba08cf83343cb652faaee768f82ab7bc9079ae1588b3d74d9d0b1a71162e6e5"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_THIRD_DEADLINE_RECOVERY_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "edea930642c944d73add7d9c33d2810cc504821dbd473175655de32330d70718"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_FOURTH_DEADLINE_RECOVERY_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "6b6289dbfd6e5093cfe96706fcb036b08233c50a7fb81c97f002f1ac5ca02f11"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_FIFTH_DEADLINE_RECOVERY_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "9b0c06bd9b63c892e16c724ad64e5ae1bbdb14f14a3d00c3353f6fd6b1810dbb"
                ),
            },
            {
                "bindingContractVersion": "m7.7-automation-cleanup-binding-v2",
                "bindingGeneration": 2,
                "bindingId": TOMBSTONED_POST_FIRED_CLEANUP_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "5f08ffcc391fb92d4e8a7f8dc917e00c7f5a3a8ad8506ff03cc0e4d3398bc99b"
                ),
            },
            {
                "bindingContractVersion": (
                    GENERATION_THREE_CLEANUP_BINDING_CONTRACT_VERSION
                ),
                "bindingGeneration": 3,
                "bindingId": TOMBSTONED_GENERATION_THREE_CLEANUP_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "ac457b8127c80ff0e1c63bd489950b140431da40d13d7bfe82b680b49db70512"
                ),
            },
            {
                "bindingContractVersion": CLEANUP_BINDING_CONTRACT_VERSION,
                "bindingGeneration": 4,
                "bindingId": TOMBSTONED_GENERATION_FOUR_CLEANUP_BINDING_ID,
                "directGetStatus": "not-found",
                "listVisibility": "absent",
                "recreationStatus": "not-attempted",
                "deletionStatus": "accepted",
                "evidenceIntegritySha256": (
                    "4a178878a6491aabe854d50a423557ed723fd0e4cee8a2a6f522a57f6d024428"
                ),
            },
        ],
    }
    if cleanup_execution != expected_cleanup_execution:
        raise ContractError("managed-binding cleanup execution contract differs")
    for index, item in enumerate(
        _as_array(
            cleanup_execution["tombstonedBindingIds"],
            "$.cleanupExecution.tombstonedBindingIds",
        )
    ):
        tombstone = _as_object(
            item, f"$.cleanupExecution.tombstonedBindingIds[{index}]"
        )
        tombstone_body = {
            key: _copy_json(value)
            for key, value in tombstone.items()
            if key != "evidenceIntegritySha256"
        }
        if tombstone["evidenceIntegritySha256"] != cleanup_binding_tombstone_integrity(
            tombstone_body
        ):
            raise ContractError(
                "managed-binding cleanup tombstone evidence integrity differs"
            )
    authority = _as_object(contract["defaultAuthority"], "$.defaultAuthority")
    if authority != {
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }:
        raise ContractError("managed-binding default authority is not deny-all")

    account = _as_object(contract["accountBinding"], "$.accountBinding")
    if account.get("cloud") != "AzureCloud":
        raise ContractError("managed-binding Azure cloud differs")
    for field in ("subscriptionFingerprint", "tenantFingerprint"):
        fingerprint = account.get(field)
        if not isinstance(fingerprint, str) or HEX_SHA64.fullmatch(fingerprint) is None:
            raise ContractError("managed-binding account fingerprint is invalid")
    if account.get("requiredState") != "Enabled":
        raise ContractError("managed-binding account state differs")
    if account.get("requiredDefault") is not True:
        raise ContractError("managed-binding account must remain the active default")
    if account.get("requiredUserType") != "user":
        raise ContractError("managed-binding account user type differs")

    scope = _as_object(contract["scopeBinding"], "$.scopeBinding")
    if scope.get("materialization") != "matched-subscription-relative-resource-id":
        raise ContractError("managed-binding scope materialization differs")
    for name, relative_id in scope.items():
        if name == "materialization":
            continue
        if not isinstance(relative_id, str) or not relative_id.startswith(
            "/resourceGroups/"
        ):
            raise ContractError("managed-binding relative resource scope is invalid")
        if ".." in relative_id or "//" in relative_id or "\\" in relative_id:
            raise ContractError("managed-binding relative resource scope is ambiguous")
        if not any(
            f"/resourceGroups/{resource_group}" in relative_id
            for resource_group in EXPECTED_RESOURCE_GROUPS.values()
        ):
            raise ContractError(
                "managed-binding resource scope escapes approved groups"
            )

    provider_registrations = tuple(
        str(item)
        for item in _as_array(
            contract["providerRegistrationRequirements"],
            "$.providerRegistrationRequirements",
        )
    )
    if provider_registrations != EXPECTED_PROVIDER_REGISTRATIONS:
        raise ContractError("managed-binding provider registry differs")

    fixed_skus = _as_object(contract["fixedSkus"], "$.fixedSkus")
    if fixed_skus.get("vpnGateway") != "VpnGw1AZ":
        raise ContractError("managed-binding VPN gateway SKU differs")
    if fixed_skus.get("redis") != "Balanced_B0":
        raise ContractError("managed-binding Redis SKU differs")

    network = _as_object(contract["network"], "$.network")
    vnet = ipaddress.ip_network(str(network["vnetCidr"]), strict=True)
    if not isinstance(vnet, ipaddress.IPv4Network):
        raise ContractError("managed-binding VNet must be IPv4")
    if vnet != ipaddress.ip_network("10.77.0.0/20"):
        raise ContractError("managed-binding VNet differs")
    child_names = (
        "containerAppsCidr",
        "privateEndpointsCidr",
        "managementCleanupCidr",
        "gatewayCidr",
        "azureFirewallCidr",
        "azureFirewallManagementCidr",
        "dnsResolverInboundCidr",
    )
    children: list[ipaddress.IPv4Network] = []
    for name in child_names:
        child = ipaddress.ip_network(str(network[name]), strict=True)
        if not isinstance(child, ipaddress.IPv4Network):
            raise ContractError("managed-binding subnets must be IPv4")
        children.append(child)
    if any(not child.subnet_of(vnet) for child in children):
        raise ContractError("managed-binding subnet escapes the exact VNet")
    for index, left in enumerate(children):
        if any(left.overlaps(right) for right in children[index + 1 :]):
            raise ContractError("managed-binding subnets overlap")
    resolver_address = ipaddress.ip_address(str(network["dnsResolverInboundAddress"]))
    resolver_subnet = ipaddress.ip_network(
        str(network["dnsResolverInboundCidr"]), strict=True
    )
    if (
        not isinstance(resolver_address, ipaddress.IPv4Address)
        or not isinstance(resolver_subnet, ipaddress.IPv4Network)
        or resolver_address not in resolver_subnet
    ):
        raise ContractError("managed-binding resolver address escapes its subnet")
    if network.get("publicApplicationIngress") is not False:
        raise ContractError("managed-binding public application ingress is forbidden")
    if network.get("publicKeyVaultAccess") is not False:
        raise ContractError("managed-binding public Key Vault access is forbidden")

    vpn = _as_object(contract["vpn"], "$.vpn")
    if vpn != {
        "authenticationType": "AAD",
        "gatewayGeneration": "Generation2",
        "gatewaySku": "VpnGw1AZ",
        "gatewayType": "Vpn",
        "microsoftRegisteredClientAudience": ("c632b3df-fb67-4d84-bdcf-b95ad541b5c8"),
        "publicIpAllocation": "Static",
        "publicIpAvailabilityZoneMode": "explicit-zone-redundant",
        "publicIpSku": "Standard",
        "publicIpZones": ["1", "2", "3"],
        "tunnelType": "OpenVPN",
        "vpnType": "RouteBased",
    }:
        raise ContractError("managed-binding VPN compatibility contract differs")

    secrets = _as_array(contract["secrets"], "$.secrets")
    actual_secrets = tuple(
        (
            str(_as_object(item, "$.secrets[]")["keyVaultName"]),
            str(_as_object(item, "$.secrets[]")["containerAppReference"]),
            str(_as_object(item, "$.secrets[]")["environmentVariable"]),
        )
        for item in secrets
    )
    if actual_secrets != EXPECTED_SECRET_BINDINGS:
        raise ContractError("managed-binding secret names or runtime mappings differ")

    provider_runtime = _as_object(contract["providerRuntime"], "$.providerRuntime")
    if provider_runtime != {
        "runtimeMode": "isolated-synthetic-private",
        "smtpFromAddress": "mobius77-validation@example.invalid",
        "smtpHost": "sandbox.smtp.mailtrap.io",
        "smtpPort": 2525,
        "smtpStartTls": True,
    }:
        raise ContractError("managed-binding provider runtime differs")

    rbac = _as_object(contract["rbac"], "$.rbac")
    expected_role_ids = {
        "acrDeleteRoleDefinitionId": "c2f4ef07-c644-48eb-af81-4b1b4947fb11",
        "acrPullRoleDefinitionId": "7f951dda-4ed3-4680-a7ca-43fe172d538d",
        "acrPushRoleDefinitionId": "8311e382-0749-4cb8-b61a-304f252e45ec",
        "acrRepositoryContributorRoleDefinitionId": (
            "2efddaa5-3f1f-4df3-97df-af3f13818f4c"
        ),
        "cleanupContributorRoleDefinitionId": ("b24988ac-6180-42a0-ab88-20f7382dd24c"),
        "containerAppsNetworkContributorRoleDefinitionId": (
            "4d97b98b-1d4f-4787-a291-c67834d212e7"
        ),
        "keyVaultSecretsOfficerRoleDefinitionId": (
            "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
        ),
        "keyVaultSecretsUserRoleDefinitionId": ("4633458b-17de-408a-b874-0445c86b69e6"),
    }
    for field, expected in expected_role_ids.items():
        if rbac.get(field) != expected:
            raise ContractError("managed-binding stable role definition differs")
    if rbac.get("workloadRoleScope") != "key-vault-resource":
        raise ContractError("workload secret role is not scoped to the Key Vault")
    if rbac.get("temporaryOperatorRoleScope") != "key-vault-resource":
        raise ContractError("temporary operator role is not scoped to the Key Vault")
    if rbac.get("cleanupRoleScope") != "target-resource-group":
        raise ContractError("cleanup role is not scoped to the target resource group")
    if (
        rbac.get("containerAppsInfrastructureRoleScope")
        != "exact-infrastructure-group-or-delegated-subnet"
        or rbac.get("containerAppsInfrastructureRolePrincipalType")
        != "ServicePrincipal"
    ):
        raise ContractError("Container Apps platform role boundary differs")
    if rbac.get("workloadRegistryRoleScope") != "container-registry-resource":
        raise ContractError("workload registry role is not scoped to the registry")
    if rbac.get("temporaryRegistryOperatorRoleScope") != "container-registry-resource":
        raise ContractError("temporary registry role is not scoped to the registry")
    if rbac.get("temporaryOperatorAssignmentRemovedAfterEntry") is not True:
        raise ContractError("temporary operator revocation is not mandatory")
    if rbac.get("temporaryRegistryOperatorAssignmentRemovedAfterPublish") is not True:
        raise ContractError("temporary registry operator revocation is not mandatory")
    if (
        rbac.get("temporaryRegistryDeleteRoleScope")
        != "container-registry-resource-or-exact-repository-abac-condition"
        or rbac.get("temporaryRegistryDeleteAssignmentRemovedAfterUntag") is not True
    ):
        raise ContractError("temporary registry delete boundary differs")

    source = _as_object(contract["privateAcrSource"], "$.privateAcrSource")
    expected_source: dict[str, JsonValue] = {
        "buildContext": "repository-root",
        "dockerfile": "apps/api/Dockerfile",
        "dockerfileIgnore": "apps/api/Dockerfile.dockerignore",
        "imageRepository": "opencanvas-api",
        "sourceCommitBinding": "published-image-source-commit",
        "buildTool": "docker-buildx",
        "pushPath": "local-docker-over-p2s-vpn-to-private-acr",
        "registryAuthentication": "entra-current-user-temporary-acr-push",
        "uploadRepositoryScope": "repository:opencanvas-api:pull,push",
        "finalizationRepositoryScope": "repository:opencanvas-api:pull,delete",
        "classicFinalizerRoles": "AcrPull+AcrDelete",
        "abacFinalizerRole": "Container Registry Repository Contributor",
        "abacRepositoryCondition": "StringEqualsIgnoreCase:opencanvas-api",
        "catalogPermissionAllowed": False,
        "deleteAuthorityTiming": "after-independent-digest-match-only",
        "finalizationIdentity": "separate-ephemeral-certificate-finalizer",
        "finalizationOperation": "exact-source-tag-untag-only",
        "manifestDeleteAllowed": False,
        "repositoryDeleteAllowed": False,
        "controlPlaneAndImageSourceCommitSeparated": True,
        "workloadPullAuthentication": "user-assigned-managed-identity-acr-pull",
        "publicRegistryAccess": False,
        "mutableTagsAllowed": False,
        "temporarySourceTagPattern": ("source-{published-image-source-commit}"),
        "temporarySourceTagPreexistenceDecision": "deny",
        "temporarySourceTagRemovedAfterDigestResolution": True,
        "deploymentReference": "digest-only",
        "dockerCredentialDirectory": "ephemeral-outside-repository",
        "dockerLogoutRequired": True,
        "gitRemoteAccessAllowed": False,
        "temporaryPushRoleRevocationRequired": True,
    }
    if source != expected_source:
        raise ContractError("managed-binding private ACR source contract differs")
    for relative_path in ("dockerfile", "dockerfileIgnore"):
        candidate = (REPOSITORY_ROOT / str(source[relative_path])).resolve()
        if (
            REPOSITORY_ROOT.resolve() not in candidate.parents
            or not candidate.is_file()
        ):
            raise ContractError(
                "managed-binding private ACR source file is unavailable"
            )

    one_run = _as_object(contract["oneRunPolicy"], "$.oneRunPolicy")
    if one_run != {
        "authorizationId": AUTHORIZATION_ID,
        "maximumLedgerLifetimeSeconds": MAXIMUM_LEDGER_LIFETIME_SECONDS,
        "maximumAttemptsPerOperation": 1,
        "retryCount": 0,
        "receiptRequiredBeforeFirstEffect": True,
        "replayDecision": "deny",
        "safePreSecretPreservationAllowed": True,
        "cleanupAuthorizedOnlyAfterCompletionOrExplicitUserApproval": True,
        "preservedResumeRequiresFreshLedger": True,
        "postRunProvisioningAuthorized": False,
    }:
        raise ContractError("managed-binding one-run policy differs")
    lifecycle = _as_object(contract["lifecycle"], "$.lifecycle")
    if lifecycle.get("failureDispositionModel") != [
        "RUNNING",
        "PAUSED_PRESERVED",
        "CONTAINED_PRESERVED",
        "READY_FOR_FINAL_CLEANUP",
        "COMPLETED",
    ]:
        raise ContractError("managed-binding failure dispositions differ")
    if (
        lifecycle.get("preSecretFailureDecision")
        != "reconcile-resulting-state-and-pause-preserved"
        or lifecycle.get("rollbackDecision")
        != "preserve-unless-final-cleanup-authorized"
    ):
        raise ContractError("managed-binding failure decision differs")
    return contract


def load_managed_binding_contract() -> dict[str, JsonValue]:
    return validate_managed_binding_contract(load_json(MANIFEST_PATH))


def validate_operation_overlay(value: JsonValue) -> dict[str, JsonValue]:
    overlay = _as_object(_copy_json(value), "$")
    schema = _as_object(load_json(OVERLAY_SCHEMA_PATH), "$schema")
    validate_schema(overlay, schema)
    if len(canonical_bytes(overlay)) > MAXIMUM_CONTRACT_BYTES:
        raise ContractError("managed-binding operation overlay exceeds its byte limit")
    _assert_no_private_material(overlay)

    if overlay["contractVersion"] != OVERLAY_VERSION:
        raise ContractError("managed-binding operation overlay version differs")
    if overlay["authorizationSourceHead"] != AUTHORIZATION_SOURCE_HEAD:
        raise ContractError("managed-binding operation authorization source differs")
    if overlay["historicalMatrixIntegritySha256"] != HISTORICAL_MATRIX_SHA256:
        raise ContractError("managed-binding historical matrix binding differs")
    historical = load_operation_contract_matrix()
    if historical["matrixIntegritySha256"] != HISTORICAL_MATRIX_SHA256:
        raise ContractError("historical operation matrix changed")
    managed_binding = load_managed_binding_contract()
    expected_binding_integrity = managed_binding_integrity_sha256(managed_binding)
    if overlay["managedBindingIntegritySha256"] != expected_binding_integrity:
        raise ContractError("managed-binding resource contract binding differs")

    authority = _as_object(overlay["defaultAuthority"], "$.defaultAuthority")
    if any(authority.values()):
        raise ContractError("managed-binding operation defaults must deny authority")
    policy = _as_object(overlay["executionPolicy"], "$.executionPolicy")
    if policy.get("maximumAttempts") != 1 or policy.get("retryCount") != 0:
        raise ContractError("managed-binding execution is not single-attempt")
    if policy.get("maximumTimeoutSeconds") != 30:
        raise ContractError("managed-binding timeout differs")
    if policy.get("rawOutputRetentionAllowed") is not False:
        raise ContractError("managed-binding raw output retention is forbidden")

    methods = _as_object(overlay["methodDefinitions"], "$.methodDefinitions")
    parsers = _as_object(overlay["parserDefinitions"], "$.parserDefinitions")
    order = tuple(
        str(item) for item in _as_array(overlay["operationOrder"], "$.operationOrder")
    )
    if order != OPERATION_IDS:
        raise ContractError("managed-binding operation order differs")
    operations = _as_array(overlay["operations"], "$.operations")
    operation_ids: list[str] = []
    for index, raw_operation in enumerate(operations):
        operation = _as_object(raw_operation, f"$.operations[{index}]")
        operation_id = str(operation["id"])
        operation_ids.append(operation_id)
        if operation.get("definitionStatus") != "defined":
            raise ContractError("managed-binding operation is not fully defined")
        if operation.get("proofStatus") != "unproved":
            raise ContractError("contract definition cannot claim execution proof")
        method_ids = _as_array(
            operation["methodDefinitions"],
            f"$.operations[{index}].methodDefinitions",
        )
        if any(str(method_id) not in methods for method_id in method_ids):
            raise ContractError(
                "managed-binding operation references an unknown method"
            )
        parser_id = str(operation["parserDefinition"])
        if parser_id not in parsers:
            raise ContractError(
                "managed-binding operation references an unknown parser"
            )
        if operation.get("cleanupOperation") != "none-read-only":
            raise ContractError(
                "read-only prerequisite operation has a mutation cleanup"
            )
    if tuple(operation_ids) != OPERATION_IDS or len(set(operation_ids)) != 15:
        raise ContractError("managed-binding operation registry differs")

    lifecycle = _as_array(overlay["lifecycleOperations"], "$.lifecycleOperations")
    lifecycle_ids = tuple(
        str(_as_object(item, "$.lifecycleOperations[]")["id"]) for item in lifecycle
    )
    if lifecycle_ids != EXPECTED_LIFECYCLE_OPERATIONS:
        raise ContractError("managed-binding lifecycle operation registry differs")
    for raw_lifecycle in lifecycle:
        item = _as_object(raw_lifecycle, "$.lifecycleOperations[]")
        if str(item["methodDefinition"]) not in methods:
            raise ContractError("managed-binding lifecycle method is unknown")
        expected_disposition_policy = (
            "reconcile-and-pause-preserved"
            if item["id"] == "pre-secret-provisioning"
            else "pause-preserved"
        )
        if item.get("failureDispositionPolicy") != expected_disposition_policy:
            raise ContractError("managed-binding failure disposition differs")
        terminal_states = item.get("terminalStates")
        if not isinstance(terminal_states, list) or any(
            not isinstance(state, str) for state in terminal_states
        ):
            raise ContractError("managed-binding terminal states are malformed")
        if (
            item["id"] == "pre-secret-provisioning"
            and "paused-preserved" not in terminal_states
        ):
            raise ContractError("managed-binding preserved terminal state is missing")
        if item.get("replayDecision") != "deny":
            raise ContractError("managed-binding lifecycle permits replay")

    expected_integrity = operation_overlay_integrity_sha256(overlay)
    if overlay["contractIntegritySha256"] != expected_integrity:
        raise ContractError("managed-binding operation overlay integrity mismatch")
    return overlay


def load_operation_overlay() -> dict[str, JsonValue]:
    return validate_operation_overlay(load_json(OVERLAY_PATH))


def pending_image_identity(
    *, control_plane_head: str, value: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """Validate the exact local image that one ledger may publish once."""

    if HEX_SHA40.fullmatch(control_plane_head) is None:
        raise ContractError("pending image control plane HEAD is invalid")
    image = _as_object(_copy_json(dict(value)), "$.pendingImage")
    exact_fields = {
        "configDigest",
        "imageBuildInputSha256",
        "imageSourceCommit",
        "localImageId",
        "platform",
        "registryManifestDigest",
        "repository",
        "sourceTag",
    }
    if set(image) != exact_fields:
        raise ContractError("pending image fields differ")
    source_commit = image.get("imageSourceCommit")
    build_input = image.get("imageBuildInputSha256")
    image_id = image.get("localImageId")
    config_digest = image.get("configDigest")
    if (
        not isinstance(source_commit, str)
        or HEX_SHA40.fullmatch(source_commit) is None
        or source_commit == HISTORICAL_IMAGE_SOURCE_COMMIT
        or not isinstance(build_input, str)
        or HEX_SHA64.fullmatch(build_input) is None
        or not isinstance(image_id, str)
        or not image_id.startswith("sha256:")
        or HEX_SHA64.fullmatch(image_id.removeprefix("sha256:")) is None
        or config_digest != image_id
        or image.get("platform") != IMAGE_PUBLICATION_PLATFORM
        or image.get("repository") != IMAGE_PUBLICATION_REPOSITORY
        or image.get("sourceTag") != f"source-{source_commit}"
        or image.get("registryManifestDigest") is not None
    ):
        raise ContractError("pending image identity is invalid")
    completed = subprocess.run(
        (
            "git",
            "diff",
            "--quiet",
            source_commit,
            control_plane_head,
            "--",
            *API_IMAGE_BUILD_INPUTS,
        ),
        cwd=REPOSITORY_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        shell=False,
        timeout=30,
    )
    if completed.returncode == 1:
        raise ContractError("pending image build inputs changed")
    if completed.returncode != 0:
        raise ContractError("pending image input comparison failed")
    return {
        "controlPlaneHead": control_plane_head,
        "imageSourceCommit": source_commit,
        "imageBuildInputSha256": build_input,
        "registryManifestDigest": None,
        "imageConfigDigest": config_digest,
        "localImageId": image_id,
        "platform": IMAGE_PUBLICATION_PLATFORM,
        "repository": IMAGE_PUBLICATION_REPOSITORY,
        "sourceTag": image["sourceTag"],
        "publicationState": "pending",
    }


def build_authorization_ledger(
    *,
    issued_at_utc: datetime,
    repository_head: str,
    pending_image: Mapping[str, JsonValue],
    maximum_lifetime_seconds: int = MAXIMUM_LEDGER_LIFETIME_SECONDS,
) -> dict[str, JsonValue]:
    if HEX_SHA40.fullmatch(repository_head) is None:
        raise ContractError("authorization ledger repository HEAD is invalid")
    if not 1 <= maximum_lifetime_seconds <= MAXIMUM_LEDGER_LIFETIME_SECONDS:
        raise ContractError("authorization ledger lifetime is outside the closed bound")
    issued = issued_at_utc.astimezone(UTC).replace(microsecond=0)
    expires = issued + timedelta(seconds=maximum_lifetime_seconds)
    managed_binding = load_managed_binding_contract()
    overlay = load_operation_overlay()
    account = _as_object(managed_binding["accountBinding"], "$.accountBinding")
    ledger_without_integrity: dict[str, JsonValue] = {
        "ledgerVersion": LEDGER_VERSION,
        "authorizationId": AUTHORIZATION_ID,
        "issuedAtUtc": _format_utc(issued),
        "expiresAtUtc": _format_utc(expires),
        "repositoryHead": repository_head,
        "publishedImage": pending_image_identity(
            control_plane_head=repository_head, value=pending_image
        ),
        "authorizationSourceHead": AUTHORIZATION_SOURCE_HEAD,
        "historicalMatrixIntegritySha256": HISTORICAL_MATRIX_SHA256,
        "managedBindingIntegritySha256": managed_binding_integrity_sha256(
            managed_binding
        ),
        "operationOverlayIntegritySha256": overlay["contractIntegritySha256"],
        "accountBinding": {
            "cloud": account["cloud"],
            "subscriptionFingerprint": account["subscriptionFingerprint"],
            "tenantFingerprint": account["tenantFingerprint"],
        },
        "resourceGroups": _copy_json(managed_binding["resourceGroups"]),
        "operationOrder": list(OPERATION_IDS),
        "authorityTransition": {
            "readOnlyOperationExecutionAuthorized": True,
            "lifecycleMutationConditionallyAuthorized": True,
            "provisioningConditionallyAuthorized": True,
            "secretValueAccessAuthorized": False,
            "maximumAttemptsPerOperation": 1,
            "retryCount": 0,
            "receiptRequired": True,
            "replayDecision": "deny",
        },
        "cleanupPolicy": {
            "safePreSecretPreservationAllowed": True,
            "unsafeTerminalCleanupRequired": True,
            "preservedResumeRequiresFreshLedger": True,
            "postRunProvisioningAuthorized": False,
            "zeroResidueRequired": True,
        },
    }
    ledger = {
        **ledger_without_integrity,
        "ledgerIntegritySha256": integrity_sha256(
            ledger_without_integrity, AUTHORIZATION_LEDGER_DOMAIN
        ),
    }
    return validate_authorization_ledger(
        ledger,
        now_utc=issued,
        expected_repository_head=repository_head,
    )


def validate_authorization_ledger(
    value: JsonValue,
    *,
    now_utc: datetime,
    expected_repository_head: str,
) -> dict[str, JsonValue]:
    ledger = _as_object(_copy_json(value), "$")
    exact_fields = {
        "accountBinding",
        "authorizationId",
        "authorizationSourceHead",
        "authorityTransition",
        "cleanupPolicy",
        "expiresAtUtc",
        "historicalMatrixIntegritySha256",
        "issuedAtUtc",
        "ledgerIntegritySha256",
        "ledgerVersion",
        "managedBindingIntegritySha256",
        "operationOrder",
        "operationOverlayIntegritySha256",
        "publishedImage",
        "repositoryHead",
        "resourceGroups",
    }
    if set(ledger) != exact_fields:
        raise ContractError("authorization ledger fields differ")
    if ledger["ledgerVersion"] != LEDGER_VERSION:
        raise ContractError("authorization ledger version differs")
    if ledger["authorizationId"] != AUTHORIZATION_ID:
        raise ContractError("authorization ledger identity differs")
    if ledger["repositoryHead"] != expected_repository_head:
        raise ContractError("authorization ledger repository binding differs")
    published = _as_object(ledger["publishedImage"], "$.publishedImage")
    pending = {
        "imageSourceCommit": published.get("imageSourceCommit"),
        "imageBuildInputSha256": published.get("imageBuildInputSha256"),
        "localImageId": published.get("localImageId"),
        "configDigest": published.get("imageConfigDigest"),
        "platform": published.get("platform"),
        "repository": published.get("repository"),
        "sourceTag": published.get("sourceTag"),
        "registryManifestDigest": published.get("registryManifestDigest"),
    }
    if published != pending_image_identity(
        control_plane_head=expected_repository_head, value=pending
    ):
        raise ContractError("authorization ledger pending image binding differs")
    if ledger["authorizationSourceHead"] != AUTHORIZATION_SOURCE_HEAD:
        raise ContractError("authorization ledger source binding differs")
    if ledger["historicalMatrixIntegritySha256"] != HISTORICAL_MATRIX_SHA256:
        raise ContractError("authorization ledger historical binding differs")
    if tuple(_as_array(ledger["operationOrder"], "$.operationOrder")) != OPERATION_IDS:
        raise ContractError("authorization ledger operation order differs")

    managed_binding = load_managed_binding_contract()
    overlay = load_operation_overlay()
    if ledger["managedBindingIntegritySha256"] != managed_binding_integrity_sha256(
        managed_binding
    ):
        raise ContractError("authorization ledger resource contract binding differs")
    if ledger["operationOverlayIntegritySha256"] != overlay["contractIntegritySha256"]:
        raise ContractError("authorization ledger operation contract binding differs")
    if ledger["resourceGroups"] != EXPECTED_RESOURCE_GROUPS:
        raise ContractError("authorization ledger resource groups differ")
    expected_account = _as_object(managed_binding["accountBinding"], "$.accountBinding")
    if ledger["accountBinding"] != {
        "cloud": expected_account["cloud"],
        "subscriptionFingerprint": expected_account["subscriptionFingerprint"],
        "tenantFingerprint": expected_account["tenantFingerprint"],
    }:
        raise ContractError("authorization ledger account binding differs")

    authority = _as_object(ledger["authorityTransition"], "$.authorityTransition")
    if authority != {
        "readOnlyOperationExecutionAuthorized": True,
        "lifecycleMutationConditionallyAuthorized": True,
        "provisioningConditionallyAuthorized": True,
        "secretValueAccessAuthorized": False,
        "maximumAttemptsPerOperation": 1,
        "retryCount": 0,
        "receiptRequired": True,
        "replayDecision": "deny",
    }:
        raise ContractError("authorization ledger transition differs")
    cleanup = _as_object(ledger["cleanupPolicy"], "$.cleanupPolicy")
    if cleanup != {
        "safePreSecretPreservationAllowed": True,
        "unsafeTerminalCleanupRequired": True,
        "preservedResumeRequiresFreshLedger": True,
        "postRunProvisioningAuthorized": False,
        "zeroResidueRequired": True,
    }:
        raise ContractError("authorization ledger cleanup policy differs")

    issued = _parse_utc(ledger["issuedAtUtc"], "$.issuedAtUtc")
    expires = _parse_utc(ledger["expiresAtUtc"], "$.expiresAtUtc")
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if expires <= issued or expires - issued > timedelta(
        seconds=MAXIMUM_LEDGER_LIFETIME_SECONDS
    ):
        raise ContractError("authorization ledger lifetime differs")
    if now < issued or now >= expires:
        raise ContractError("authorization ledger is not currently valid")
    if ledger["ledgerIntegritySha256"] != authorization_ledger_integrity_sha256(ledger):
        raise ContractError("authorization ledger integrity mismatch")
    _assert_no_private_material(ledger)
    return ledger


def operation_authorization_decision(
    operation_id: str,
    *,
    ledger: JsonValue | None = None,
    now_utc: datetime | None = None,
    expected_repository_head: str | None = None,
) -> dict[str, JsonValue]:
    if operation_id not in OPERATION_IDS:
        raise ContractError("unknown managed-binding operation")
    if ledger is None or now_utc is None or expected_repository_head is None:
        return {
            "operationId": operation_id,
            "decision": "deny",
            "reason": "one-run-authority-missing",
            "executionAuthorized": False,
            "mutationAuthorized": False,
            "provisioningAuthorized": False,
            "secretAccessAuthorized": False,
        }
    validate_authorization_ledger(
        ledger,
        now_utc=now_utc,
        expected_repository_head=expected_repository_head,
    )
    return {
        "operationId": operation_id,
        "decision": "allow-once",
        "reason": "exact-one-run-authority-valid",
        "executionAuthorized": True,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "secretAccessAuthorized": False,
    }


def claim_operation_receipt(
    *,
    ledger: JsonValue,
    operation_id: str,
    receipt_directory: Path,
    now_utc: datetime,
    expected_repository_head: str,
) -> Path:
    valid_ledger = validate_authorization_ledger(
        ledger,
        now_utc=now_utc,
        expected_repository_head=expected_repository_head,
    )
    if (
        operation_id not in OPERATION_IDS
        and operation_id not in EXPECTED_LIFECYCLE_OPERATIONS
    ):
        raise ContractError("unknown receipt operation")
    resolved_directory = receipt_directory.resolve()
    resolved_repository = REPOSITORY_ROOT.resolve()
    if (
        resolved_directory == resolved_repository
        or resolved_repository in resolved_directory.parents
    ):
        raise ContractError("authorization receipts must remain outside the repository")
    resolved_directory.mkdir(parents=True, exist_ok=True)
    receipt_path = resolved_directory / f"{operation_id}.receipt.json"
    receipt_body: dict[str, JsonValue] = {
        "authorizationId": AUTHORIZATION_ID,
        "ledgerIntegritySha256": valid_ledger["ledgerIntegritySha256"],
        "operationId": operation_id,
        "claimedAtUtc": _format_utc(now_utc),
        "replayDecision": "deny",
    }
    receipt: dict[str, JsonValue] = {
        **receipt_body,
        "receiptIntegritySha256": integrity_sha256(
            receipt_body, AUTHORIZATION_RECEIPT_DOMAIN
        ),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(receipt_path, flags, 0o600)
    except FileExistsError:
        raise ContractError("authorization receipt already consumed") from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        receipt_path.unlink(missing_ok=True)
        raise ContractError("authorization receipt write failed") from None
    return receipt_path
