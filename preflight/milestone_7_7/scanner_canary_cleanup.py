"""One-use authority for deleting the exact retained Image Eight canary version."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, cast

from performance.milestone_7_7.framework import (
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
)

AUTHORIZATION_VERSION: Final = "mobius.milestone-7.7.scanner-canary-cleanup.v1"
AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-canary-cleanup/v1\0"
)
TARGET_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-staging"
CLEANUP_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-cleanup-control"
CLEANUP_AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup-recovery"
CLEANUP_DEADLINE_UTC: Final = "2026-08-08T12:15:00Z"
STORAGE_ACCOUNT: Final = "stmobius7711564669"
QUARANTINE_CONTAINER: Final = "quarantine"
WORKER_IDENTITY: Final = "id-mobius77-worker"
WORKER_PRINCIPAL_ID: Final = "7c6c093e-e38b-4733-8a35-0b59ed6ef230"
MANAGED_ENVIRONMENT: Final = "cae-mobius77-staging"
CLEANUP_JOB: Final = "caj-mobius77-i8-canary-cleanup"
CLEANUP_ROLE_DEFINITION_NAME: Final = "0bbe9d3f-c0cc-58b2-93f1-3e678bf98df6"
CLEANUP_ROLE_ASSIGNMENT_NAME: Final = "e5f9be4c-cf82-565b-a3dd-7959d31049c0"
IMAGE_EIGHT_DIGEST: Final = (
    "acrmobius7711564669.azurecr.io/opencanvas-api@"
    "sha256:b6f46bb2ee2d249d742b47d00b1bbd2c76e39190d6015ad4d9d3b83171ac834e"
)
DETERMINISTIC_OBJECT_ID: Final = "9b78828a-4e5f-5f60-9b5e-6f21823d4658"
DETERMINISTIC_OBJECT_VERSION_ID: Final = "d763ec77-7292-5e06-88b8-e388f2e7b6e6"
DETERMINISTIC_BLOB_NAME: Final = (
    "9b78828a4e5f5f609b5e6f21823d4658/d763ec7772925e0688b8e388f2e7b6e6"
)
EXPECTED_PROVIDER_VERSION_SHA256: Final = (
    "b0bc0413744bbf1dbd4921eac990b21d72f255556faa5e8c83a87eae080b52b5"
)
COST_CEILING_USD_CENTS: Final = 25_000
MAXIMUM_AUTHORIZATION_AGE: Final = timedelta(minutes=30)
MINIMUM_CLEANUP_HEADROOM: Final = timedelta(hours=2)
ALLOWED_OPERATIONS: Final = (
    "verify-exact-image-eight-canary-version",
    "create-exact-temporary-canary-cleanup-role-definition",
    "create-exact-temporary-canary-cleanup-role-assignment",
    "deploy-one-exact-canary-cleanup-job",
    "start-one-exact-canary-cleanup-execution",
    "delete-one-exact-image-eight-canary-version",
    "verify-exact-canary-version-residue-absent",
    "delete-exact-temporary-canary-cleanup-role-assignment",
    "delete-exact-temporary-canary-cleanup-job",
    "delete-exact-temporary-canary-cleanup-role-definition",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ScannerCanaryCleanupError(ValueError):
    """Raised when exact-version cleanup authority expands or becomes stale."""


@dataclass(frozen=True, slots=True)
class ScannerCanaryCleanupAuthorization:
    authorizationVersion: str
    repositoryHead: str
    subscriptionId: str
    targetResourceGroupId: str
    cleanupAutomationAccountId: str
    cleanupDeadlineUtc: str
    storageAccountId: str
    quarantineContainer: str
    quarantineContainerId: str
    deterministicBlobName: str
    deterministicObjectId: str
    deterministicObjectVersionId: str
    expectedProviderVersionSha256: str
    workerIdentityId: str
    cleanupPrincipalId: str
    cleanupScope: str
    managedEnvironmentId: str
    cleanupRoleDefinitionId: str
    cleanupRoleAssignmentId: str
    cleanupJobId: str
    apiImageDigest: str
    authorizedAtUtc: str
    expiresAtUtc: str
    maximumCostUsdCents: int
    maximumExecutions: int
    wildcardDeleteAuthorized: bool
    containerDeleteAuthorized: bool
    multipleVersionDeleteAuthorized: bool
    blobWriteAuthorized: bool
    scannerProofAuthorized: bool
    applicationDeploymentAuthorized: bool
    migrationAuthorized: bool
    resourceGroupCleanupAuthorized: bool
    allowedOperations: tuple[str, ...]
    authorizationIntegritySha256: str


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise ScannerCanaryCleanupError(code) from None


def _resource_ids(subscription_id: str) -> dict[str, str]:
    if _UUID.fullmatch(subscription_id) is None:
        raise ScannerCanaryCleanupError("scanner-canary-cleanup-subscription-invalid")
    target = f"/subscriptions/{subscription_id}/resourceGroups/{TARGET_RESOURCE_GROUP}"
    cleanup = (
        f"/subscriptions/{subscription_id}/resourceGroups/{CLEANUP_RESOURCE_GROUP}"
    )
    storage = f"{target}/providers/Microsoft.Storage/storageAccounts/{STORAGE_ACCOUNT}"
    container = f"{storage}/blobServices/default/containers/{QUARANTINE_CONTAINER}"
    return {
        "targetResourceGroupId": target,
        "cleanupAutomationAccountId": (
            f"{cleanup}/providers/Microsoft.Automation/automationAccounts/"
            f"{CLEANUP_AUTOMATION_ACCOUNT}"
        ),
        "storageAccountId": storage,
        "quarantineContainerId": container,
        "workerIdentityId": (
            f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
            f"{WORKER_IDENTITY}"
        ),
        "managedEnvironmentId": (
            f"{target}/providers/Microsoft.App/managedEnvironments/{MANAGED_ENVIRONMENT}"
        ),
        "cleanupRoleDefinitionId": (
            f"{target}/providers/Microsoft.Authorization/roleDefinitions/"
            f"{CLEANUP_ROLE_DEFINITION_NAME}"
        ),
        "cleanupRoleAssignmentId": (
            f"{container}/providers/Microsoft.Authorization/roleAssignments/"
            f"{CLEANUP_ROLE_ASSIGNMENT_NAME}"
        ),
        "cleanupJobId": f"{target}/providers/Microsoft.App/jobs/{CLEANUP_JOB}",
    }


def scanner_canary_cleanup_authorization_integrity(
    authorization: ScannerCanaryCleanupAuthorization,
) -> str:
    body = asdict(authorization)
    body.pop("authorizationIntegritySha256", None)
    body["allowedOperations"] = list(authorization.allowedOperations)
    return integrity_sha256(cast(JsonValue, body), AUTHORIZATION_DOMAIN)


def build_scanner_canary_cleanup_authorization(
    *,
    repository_head: str,
    subscription_id: str,
    cleanup_deadline_utc: str,
    cleanup_principal_id: str,
    now_utc: datetime,
) -> ScannerCanaryCleanupAuthorization:
    """Issue one replay-denying grant for the retained Image Eight canary only."""

    if _SHA40.fullmatch(repository_head) is None:
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-repository-head-invalid"
        )
    if cleanup_deadline_utc != CLEANUP_DEADLINE_UTC:
        raise ScannerCanaryCleanupError("scanner-canary-cleanup-deadline-invalid")
    if cleanup_principal_id != WORKER_PRINCIPAL_ID:
        raise ScannerCanaryCleanupError("scanner-canary-cleanup-principal-invalid")
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    deadline = _parse_utc(
        cleanup_deadline_utc, "scanner-canary-cleanup-deadline-invalid"
    )
    if deadline - current < MINIMUM_CLEANUP_HEADROOM:
        raise ScannerCanaryCleanupError("scanner-canary-cleanup-window-insufficient")
    expires = min(
        current + MAXIMUM_AUTHORIZATION_AGE,
        deadline - timedelta(hours=1),
    )
    if expires <= current:
        raise ScannerCanaryCleanupError("scanner-canary-cleanup-authorization-expired")
    expected = _resource_ids(subscription_id)
    unsigned = ScannerCanaryCleanupAuthorization(
        authorizationVersion=AUTHORIZATION_VERSION,
        repositoryHead=repository_head,
        subscriptionId=subscription_id,
        targetResourceGroupId=expected["targetResourceGroupId"],
        cleanupAutomationAccountId=expected["cleanupAutomationAccountId"],
        cleanupDeadlineUtc=cleanup_deadline_utc,
        storageAccountId=expected["storageAccountId"],
        quarantineContainer=QUARANTINE_CONTAINER,
        quarantineContainerId=expected["quarantineContainerId"],
        deterministicBlobName=DETERMINISTIC_BLOB_NAME,
        deterministicObjectId=DETERMINISTIC_OBJECT_ID,
        deterministicObjectVersionId=DETERMINISTIC_OBJECT_VERSION_ID,
        expectedProviderVersionSha256=EXPECTED_PROVIDER_VERSION_SHA256,
        workerIdentityId=expected["workerIdentityId"],
        cleanupPrincipalId=cleanup_principal_id,
        cleanupScope=expected["quarantineContainerId"],
        managedEnvironmentId=expected["managedEnvironmentId"],
        cleanupRoleDefinitionId=expected["cleanupRoleDefinitionId"],
        cleanupRoleAssignmentId=expected["cleanupRoleAssignmentId"],
        cleanupJobId=expected["cleanupJobId"],
        apiImageDigest=IMAGE_EIGHT_DIGEST,
        authorizedAtUtc=_format_utc(current),
        expiresAtUtc=_format_utc(expires),
        maximumCostUsdCents=COST_CEILING_USD_CENTS,
        maximumExecutions=1,
        wildcardDeleteAuthorized=False,
        containerDeleteAuthorized=False,
        multipleVersionDeleteAuthorized=False,
        blobWriteAuthorized=False,
        scannerProofAuthorized=False,
        applicationDeploymentAuthorized=False,
        migrationAuthorized=False,
        resourceGroupCleanupAuthorized=False,
        allowedOperations=ALLOWED_OPERATIONS,
        authorizationIntegritySha256="",
    )
    return replace(
        unsigned,
        authorizationIntegritySha256=(
            scanner_canary_cleanup_authorization_integrity(unsigned)
        ),
    )


def validate_scanner_canary_cleanup_authorization(
    authorization: ScannerCanaryCleanupAuthorization,
    *,
    expected_repository_head: str,
    now_utc: datetime,
) -> ScannerCanaryCleanupAuthorization:
    expected = _resource_ids(authorization.subscriptionId)
    exact: dict[str, object] = {
        "authorizationVersion": AUTHORIZATION_VERSION,
        "repositoryHead": expected_repository_head,
        "targetResourceGroupId": expected["targetResourceGroupId"],
        "cleanupAutomationAccountId": expected["cleanupAutomationAccountId"],
        "cleanupDeadlineUtc": CLEANUP_DEADLINE_UTC,
        "storageAccountId": expected["storageAccountId"],
        "quarantineContainer": QUARANTINE_CONTAINER,
        "quarantineContainerId": expected["quarantineContainerId"],
        "deterministicBlobName": DETERMINISTIC_BLOB_NAME,
        "deterministicObjectId": DETERMINISTIC_OBJECT_ID,
        "deterministicObjectVersionId": DETERMINISTIC_OBJECT_VERSION_ID,
        "expectedProviderVersionSha256": EXPECTED_PROVIDER_VERSION_SHA256,
        "workerIdentityId": expected["workerIdentityId"],
        "cleanupPrincipalId": WORKER_PRINCIPAL_ID,
        "cleanupScope": expected["quarantineContainerId"],
        "managedEnvironmentId": expected["managedEnvironmentId"],
        "cleanupRoleDefinitionId": expected["cleanupRoleDefinitionId"],
        "cleanupRoleAssignmentId": expected["cleanupRoleAssignmentId"],
        "cleanupJobId": expected["cleanupJobId"],
        "apiImageDigest": IMAGE_EIGHT_DIGEST,
        "maximumCostUsdCents": COST_CEILING_USD_CENTS,
        "maximumExecutions": 1,
        "wildcardDeleteAuthorized": False,
        "containerDeleteAuthorized": False,
        "multipleVersionDeleteAuthorized": False,
        "blobWriteAuthorized": False,
        "scannerProofAuthorized": False,
        "applicationDeploymentAuthorized": False,
        "migrationAuthorized": False,
        "resourceGroupCleanupAuthorized": False,
        "allowedOperations": ALLOWED_OPERATIONS,
    }
    observed = asdict(authorization)
    if any(observed.get(key) != value for key, value in exact.items()):
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-authorization-scope-invalid"
        )
    if _SHA40.fullmatch(authorization.repositoryHead) is None:
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-repository-head-invalid"
        )
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    authorized = _parse_utc(
        authorization.authorizedAtUtc,
        "scanner-canary-cleanup-authorized-at-invalid",
    )
    expires = _parse_utc(
        authorization.expiresAtUtc,
        "scanner-canary-cleanup-expires-at-invalid",
    )
    deadline = _parse_utc(
        authorization.cleanupDeadlineUtc,
        "scanner-canary-cleanup-deadline-invalid",
    )
    if (
        authorized > current
        or current > expires
        or expires - authorized > MAXIMUM_AUTHORIZATION_AGE
        or deadline - current < MINIMUM_CLEANUP_HEADROOM
        or expires > deadline - timedelta(hours=1)
    ):
        raise ScannerCanaryCleanupError("scanner-canary-cleanup-authorization-expired")
    if authorization.authorizationIntegritySha256 != (
        scanner_canary_cleanup_authorization_integrity(authorization)
    ):
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-authorization-integrity-invalid"
        )
    return authorization


def scanner_canary_cleanup_authorization_from_mapping(
    value: Mapping[str, object],
) -> ScannerCanaryCleanupAuthorization:
    expected_fields = {
        field.name for field in fields(ScannerCanaryCleanupAuthorization)
    }
    if set(value) != expected_fields:
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-authorization-fields-invalid"
        )
    operations = value.get("allowedOperations")
    if not isinstance(operations, (list, tuple)) or not all(
        isinstance(operation, str) for operation in operations
    ):
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-authorization-malformed"
        )
    try:
        return ScannerCanaryCleanupAuthorization(
            **cast(Any, {**dict(value), "allowedOperations": tuple(operations)})
        )
    except TypeError as exc:
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-authorization-malformed"
        ) from exc


def load_scanner_canary_cleanup_authorization(
    path: Path,
) -> ScannerCanaryCleanupAuthorization:
    value = load_json(path)
    if not isinstance(value, Mapping):
        raise ScannerCanaryCleanupError(
            "scanner-canary-cleanup-authorization-malformed"
        )
    return scanner_canary_cleanup_authorization_from_mapping(value)


def write_scanner_canary_cleanup_authorization(
    path: Path, authorization: ScannerCanaryCleanupAuthorization
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = asdict(authorization)
    body["allowedOperations"] = list(authorization.allowedOperations)
    path.write_bytes(canonical_bytes(cast(JsonValue, body)))


def execute_scanner_canary_cleanup(
    *,
    authorization: ScannerCanaryCleanupAuthorization,
    receipt_directory: Path,
    expected_repository_head: str,
    evidence_output: Path,
) -> dict[str, JsonValue]:
    """Invoke the sole production consumer for exact Image Eight cleanup."""

    from infra.milestone_7_7.scanner_canary_cleanup_adapter import (
        ProductionScannerCanaryCleanupAdapter,
    )

    return ProductionScannerCanaryCleanupAdapter().execute(
        authorization=authorization,
        receipt_directory=receipt_directory,
        expected_repository_head=expected_repository_head,
        evidence_output=evidence_output,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--receipt-directory", type=Path, required=True)
    parser.add_argument("--repository-head", required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        authorization = load_scanner_canary_cleanup_authorization(args.authorization)
        result = execute_scanner_canary_cleanup(
            authorization=authorization,
            receipt_directory=args.receipt_directory,
            expected_repository_head=args.repository_head,
            evidence_output=args.evidence_output,
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except (ScannerCanaryCleanupError, RuntimeError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "blocked"},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ScannerCanaryCleanupAuthorization",
    "ScannerCanaryCleanupError",
    "build_scanner_canary_cleanup_authorization",
    "execute_scanner_canary_cleanup",
    "load_scanner_canary_cleanup_authorization",
    "scanner_canary_cleanup_authorization_integrity",
    "validate_scanner_canary_cleanup_authorization",
    "write_scanner_canary_cleanup_authorization",
]
