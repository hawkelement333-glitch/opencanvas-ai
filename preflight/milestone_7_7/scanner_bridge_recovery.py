"""One-use authority for the Milestone 7.7 private scanner bridge stages."""

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

AUTHORIZATION_VERSION: Final = "mobius.milestone-7.7.scanner-bridge-recovery.v1"
AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/scanner-bridge-recovery/v1\0"
)
FOUNDATION_STAGE: Final = "scanner-foundation"
PROOF_STAGE: Final = "scanner-proof"
TARGET_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-staging"
CLEANUP_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-cleanup-control"
CLEANUP_AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup-recovery"
STORAGE_ACCOUNT: Final = "stmobius7711564669"
LOG_ANALYTICS_WORKSPACE: Final = "law-mobius77-staging"
WORKER_IDENTITY: Final = "id-mobius77-worker"
PRIVATE_LINK_SCOPE: Final = "ampls-mobius77-staging"
MONITOR_PRIVATE_ENDPOINT: Final = "pe-mobius77-azure-monitor"
PROOF_JOB: Final = "caj-mobius77-scanner-bridge-proof"
PROOF_ROLE_DEFINITION_NAME: Final = "7d78ed8f-4b48-4e74-bb95-f0fcfe811897"
REGISTRY_HOST: Final = "acrmobius7711564669.azurecr.io"
IMAGE_REPOSITORY: Final = "opencanvas-api"
COST_CEILING_USD_CENTS: Final = 25_000
MINIMUM_CLEANUP_WINDOW: Final = timedelta(hours=6)
MAXIMUM_AUTHORIZATION_AGE: Final = timedelta(hours=1)
FOUNDATION_ALLOWED_OPERATIONS: Final = (
    "deploy-private-scanner-foundation",
    "authoritative-readback-reconcile-private-scanner-foundation",
)
PROOF_ALLOWED_OPERATIONS: Final = (
    "deploy-one-private-scanner-proof-job",
    "start-one-private-scanner-proof-execution",
    "authoritative-readback-reconcile-private-scanner-proof",
    "delete-exact-private-scanner-proof-role-assignment",
    "delete-exact-private-scanner-proof-job",
    "delete-exact-private-scanner-proof-role-definition",
    "verify-private-scanner-proof-residue-absent",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUBSCRIPTION = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_IMAGE = re.compile(
    rf"^{re.escape(REGISTRY_HOST)}/{IMAGE_REPOSITORY}@sha256:[0-9a-f]{{64}}$"
)


class ScannerBridgeRecoveryError(ValueError):
    """Raised when scanner-bridge authority expands beyond the two exact stages."""


@dataclass(frozen=True, slots=True)
class ScannerBridgeRecoveryAuthorization:
    authorizationVersion: str
    stage: str
    repositoryHead: str
    subscriptionId: str
    targetResourceGroupId: str
    cleanupAutomationAccountId: str
    cleanupDeadlineUtc: str
    storageAccountId: str
    logAnalyticsWorkspaceId: str
    workerIdentityId: str
    privateLinkScopeId: str
    monitorPrivateEndpointId: str
    proofJobId: str | None
    proofRoleDefinitionId: str | None
    apiImageDigest: str | None
    buildInputSha256: str | None
    authorizedAtUtc: str
    expiresAtUtc: str
    maximumCostUsdCents: int
    maximumProofExecutions: int
    publicAccessAuthorized: bool
    tagWriteAuthorized: bool
    applicationDeploymentAuthorized: bool
    migrationAuthorized: bool
    cleanupExecutionAuthorized: bool
    allowedOperations: tuple[str, ...]
    authorizationIntegritySha256: str


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise ScannerBridgeRecoveryError(code) from None


def _resource_ids(subscription_id: str) -> dict[str, str]:
    if _SUBSCRIPTION.fullmatch(subscription_id) is None:
        raise ScannerBridgeRecoveryError("scanner-bridge-subscription-invalid")
    target = f"/subscriptions/{subscription_id}/resourceGroups/{TARGET_RESOURCE_GROUP}"
    cleanup = (
        f"/subscriptions/{subscription_id}/resourceGroups/{CLEANUP_RESOURCE_GROUP}"
    )
    return {
        "targetResourceGroupId": target,
        "cleanupAutomationAccountId": (
            f"{cleanup}/providers/Microsoft.Automation/automationAccounts/"
            f"{CLEANUP_AUTOMATION_ACCOUNT}"
        ),
        "storageAccountId": (
            f"{target}/providers/Microsoft.Storage/storageAccounts/{STORAGE_ACCOUNT}"
        ),
        "logAnalyticsWorkspaceId": (
            f"{target}/providers/Microsoft.OperationalInsights/workspaces/{LOG_ANALYTICS_WORKSPACE}"
        ),
        "workerIdentityId": (
            f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{WORKER_IDENTITY}"
        ),
        "privateLinkScopeId": (
            f"{target}/providers/Microsoft.Insights/privateLinkScopes/{PRIVATE_LINK_SCOPE}"
        ),
        "monitorPrivateEndpointId": (
            f"{target}/providers/Microsoft.Network/privateEndpoints/{MONITOR_PRIVATE_ENDPOINT}"
        ),
        "proofJobId": (f"{target}/providers/Microsoft.App/jobs/{PROOF_JOB}"),
        "proofRoleDefinitionId": (
            f"{target}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{PROOF_ROLE_DEFINITION_NAME}"
        ),
    }


def scanner_bridge_recovery_authorization_integrity(
    authorization: ScannerBridgeRecoveryAuthorization,
) -> str:
    body = asdict(authorization)
    body.pop("authorizationIntegritySha256", None)
    body["allowedOperations"] = list(authorization.allowedOperations)
    return cast(str, integrity_sha256(cast(JsonValue, body), AUTHORIZATION_DOMAIN))


def build_scanner_bridge_recovery_authorization(
    *,
    stage: str,
    repository_head: str,
    subscription_id: str,
    target_resource_group_id: str,
    cleanup_automation_account_id: str,
    cleanup_deadline_utc: str,
    now_utc: datetime,
    api_image_digest: str | None = None,
    build_input_sha256: str | None = None,
) -> ScannerBridgeRecoveryAuthorization:
    """Issue one short-lived, stage-specific, replay-denying production grant."""

    if _SHA40.fullmatch(repository_head) is None:
        raise ScannerBridgeRecoveryError("scanner-bridge-repository-head-invalid")
    expected = _resource_ids(subscription_id)
    if target_resource_group_id != expected["targetResourceGroupId"]:
        raise ScannerBridgeRecoveryError("scanner-bridge-target-scope-invalid")
    if cleanup_automation_account_id != expected["cleanupAutomationAccountId"]:
        raise ScannerBridgeRecoveryError("scanner-bridge-cleanup-account-invalid")
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    deadline = _parse_utc(
        cleanup_deadline_utc, "scanner-bridge-cleanup-deadline-invalid"
    )
    if deadline - current < MINIMUM_CLEANUP_WINDOW:
        raise ScannerBridgeRecoveryError("scanner-bridge-cleanup-window-insufficient")
    expires = min(current + MAXIMUM_AUTHORIZATION_AGE, deadline - timedelta(minutes=90))
    if expires <= current:
        raise ScannerBridgeRecoveryError("scanner-bridge-authorization-expired")
    if stage == FOUNDATION_STAGE:
        if api_image_digest is not None or build_input_sha256 is not None:
            raise ScannerBridgeRecoveryError(
                "scanner-foundation-image-authority-prohibited"
            )
        proof_job_id = None
        proof_role_id = None
        maximum_executions = 0
        operations: tuple[str, ...] = FOUNDATION_ALLOWED_OPERATIONS
    elif stage == PROOF_STAGE:
        if (
            not isinstance(api_image_digest, str)
            or _IMAGE.fullmatch(api_image_digest) is None
            or not isinstance(build_input_sha256, str)
            or _SHA256.fullmatch(build_input_sha256) is None
        ):
            raise ScannerBridgeRecoveryError("scanner-proof-image-binding-invalid")
        proof_job_id = expected["proofJobId"]
        proof_role_id = expected["proofRoleDefinitionId"]
        maximum_executions = 1
        operations = PROOF_ALLOWED_OPERATIONS
    else:
        raise ScannerBridgeRecoveryError("scanner-bridge-stage-invalid")
    unsigned = ScannerBridgeRecoveryAuthorization(
        authorizationVersion=AUTHORIZATION_VERSION,
        stage=stage,
        repositoryHead=repository_head,
        subscriptionId=subscription_id,
        targetResourceGroupId=expected["targetResourceGroupId"],
        cleanupAutomationAccountId=expected["cleanupAutomationAccountId"],
        cleanupDeadlineUtc=cleanup_deadline_utc,
        storageAccountId=expected["storageAccountId"],
        logAnalyticsWorkspaceId=expected["logAnalyticsWorkspaceId"],
        workerIdentityId=expected["workerIdentityId"],
        privateLinkScopeId=expected["privateLinkScopeId"],
        monitorPrivateEndpointId=expected["monitorPrivateEndpointId"],
        proofJobId=proof_job_id,
        proofRoleDefinitionId=proof_role_id,
        apiImageDigest=api_image_digest,
        buildInputSha256=build_input_sha256,
        authorizedAtUtc=_format_utc(current),
        expiresAtUtc=_format_utc(expires),
        maximumCostUsdCents=COST_CEILING_USD_CENTS,
        maximumProofExecutions=maximum_executions,
        publicAccessAuthorized=False,
        tagWriteAuthorized=False,
        applicationDeploymentAuthorized=False,
        migrationAuthorized=False,
        cleanupExecutionAuthorized=False,
        allowedOperations=operations,
        authorizationIntegritySha256="",
    )
    return replace(
        unsigned,
        authorizationIntegritySha256=(
            scanner_bridge_recovery_authorization_integrity(unsigned)
        ),
    )


def validate_scanner_bridge_recovery_authorization(
    authorization: ScannerBridgeRecoveryAuthorization,
    *,
    expected_repository_head: str,
    now_utc: datetime,
) -> ScannerBridgeRecoveryAuthorization:
    expected = _resource_ids(authorization.subscriptionId)
    if authorization.stage == FOUNDATION_STAGE:
        stage_values: dict[str, object] = {
            "proofJobId": None,
            "proofRoleDefinitionId": None,
            "apiImageDigest": None,
            "buildInputSha256": None,
            "maximumProofExecutions": 0,
            "allowedOperations": FOUNDATION_ALLOWED_OPERATIONS,
        }
    elif authorization.stage == PROOF_STAGE:
        stage_values = {
            "proofJobId": expected["proofJobId"],
            "proofRoleDefinitionId": expected["proofRoleDefinitionId"],
            "maximumProofExecutions": 1,
            "allowedOperations": PROOF_ALLOWED_OPERATIONS,
        }
        if (
            not isinstance(authorization.apiImageDigest, str)
            or _IMAGE.fullmatch(authorization.apiImageDigest) is None
            or not isinstance(authorization.buildInputSha256, str)
            or _SHA256.fullmatch(authorization.buildInputSha256) is None
        ):
            raise ScannerBridgeRecoveryError("scanner-proof-image-binding-invalid")
    else:
        raise ScannerBridgeRecoveryError("scanner-bridge-stage-invalid")
    exact: dict[str, object] = {
        "authorizationVersion": AUTHORIZATION_VERSION,
        "repositoryHead": expected_repository_head,
        "targetResourceGroupId": expected["targetResourceGroupId"],
        "cleanupAutomationAccountId": expected["cleanupAutomationAccountId"],
        "storageAccountId": expected["storageAccountId"],
        "logAnalyticsWorkspaceId": expected["logAnalyticsWorkspaceId"],
        "workerIdentityId": expected["workerIdentityId"],
        "privateLinkScopeId": expected["privateLinkScopeId"],
        "monitorPrivateEndpointId": expected["monitorPrivateEndpointId"],
        "maximumCostUsdCents": COST_CEILING_USD_CENTS,
        "publicAccessAuthorized": False,
        "tagWriteAuthorized": False,
        "applicationDeploymentAuthorized": False,
        "migrationAuthorized": False,
        "cleanupExecutionAuthorized": False,
        **stage_values,
    }
    observed = asdict(authorization)
    if any(observed.get(key) != value for key, value in exact.items()):
        raise ScannerBridgeRecoveryError("scanner-bridge-authorization-scope-invalid")
    if _SHA40.fullmatch(authorization.repositoryHead) is None:
        raise ScannerBridgeRecoveryError("scanner-bridge-repository-head-invalid")
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    authorized = _parse_utc(
        authorization.authorizedAtUtc, "scanner-bridge-authorized-at-invalid"
    )
    expires = _parse_utc(
        authorization.expiresAtUtc, "scanner-bridge-expires-at-invalid"
    )
    cleanup = _parse_utc(
        authorization.cleanupDeadlineUtc, "scanner-bridge-cleanup-deadline-invalid"
    )
    if (
        authorized > current
        or current > expires
        or expires - authorized > MAXIMUM_AUTHORIZATION_AGE
        or cleanup - current < MINIMUM_CLEANUP_WINDOW
        or expires > cleanup - timedelta(minutes=90)
    ):
        raise ScannerBridgeRecoveryError("scanner-bridge-authorization-expired")
    if authorization.authorizationIntegritySha256 != (
        scanner_bridge_recovery_authorization_integrity(authorization)
    ):
        raise ScannerBridgeRecoveryError(
            "scanner-bridge-authorization-integrity-invalid"
        )
    return authorization


def scanner_bridge_recovery_authorization_from_mapping(
    value: Mapping[str, object],
) -> ScannerBridgeRecoveryAuthorization:
    expected_fields = {
        field.name for field in fields(ScannerBridgeRecoveryAuthorization)
    }
    if set(value) != expected_fields:
        raise ScannerBridgeRecoveryError("scanner-bridge-authorization-fields-invalid")
    operations = value.get("allowedOperations")
    if not isinstance(operations, (list, tuple)) or not all(
        isinstance(operation, str) for operation in operations
    ):
        raise ScannerBridgeRecoveryError("scanner-bridge-authorization-malformed")
    try:
        return ScannerBridgeRecoveryAuthorization(
            **cast(
                Any,
                {**dict(value), "allowedOperations": tuple(operations)},
            )
        )
    except TypeError as exc:
        raise ScannerBridgeRecoveryError(
            "scanner-bridge-authorization-malformed"
        ) from exc


def load_scanner_bridge_recovery_authorization(
    path: Path,
) -> ScannerBridgeRecoveryAuthorization:
    value = load_json(path)
    if not isinstance(value, Mapping):
        raise ScannerBridgeRecoveryError("scanner-bridge-authorization-malformed")
    return scanner_bridge_recovery_authorization_from_mapping(value)


def write_scanner_bridge_recovery_authorization(
    path: Path, authorization: ScannerBridgeRecoveryAuthorization
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = asdict(authorization)
    body["allowedOperations"] = list(authorization.allowedOperations)
    path.write_bytes(canonical_bytes(cast(JsonValue, body)))


def execute_scanner_bridge_recovery(
    *,
    authorization: ScannerBridgeRecoveryAuthorization,
    receipt_directory: Path,
    expected_repository_head: str,
    evidence_output: Path | None = None,
) -> dict[str, JsonValue]:
    """Invoke the sole production consumer for the typed scanner-bridge grant."""

    from infra.milestone_7_7.scanner_bridge_recovery_adapter import (
        ProductionScannerBridgeRecoveryAdapter,
    )

    return cast(
        dict[str, JsonValue],
        ProductionScannerBridgeRecoveryAdapter().execute(
            authorization=authorization,
            receipt_directory=receipt_directory,
            expected_repository_head=expected_repository_head,
            evidence_output=evidence_output,
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--receipt-directory", type=Path, required=True)
    parser.add_argument("--repository-head", required=True)
    parser.add_argument("--evidence-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        authorization = load_scanner_bridge_recovery_authorization(args.authorization)
        if (authorization.stage == PROOF_STAGE) != (args.evidence_output is not None):
            raise ScannerBridgeRecoveryError(
                "scanner-bridge-evidence-output-contract-invalid"
            )
        result = execute_scanner_bridge_recovery(
            authorization=authorization,
            receipt_directory=args.receipt_directory,
            expected_repository_head=args.repository_head,
            evidence_output=args.evidence_output,
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except (ScannerBridgeRecoveryError, RuntimeError, OSError, ValueError) as exc:
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
    "FOUNDATION_STAGE",
    "PROOF_STAGE",
    "ScannerBridgeRecoveryAuthorization",
    "ScannerBridgeRecoveryError",
    "build_scanner_bridge_recovery_authorization",
    "execute_scanner_bridge_recovery",
    "load_scanner_bridge_recovery_authorization",
    "scanner_bridge_recovery_authorization_integrity",
    "validate_scanner_bridge_recovery_authorization",
    "write_scanner_bridge_recovery_authorization",
]
