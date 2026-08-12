"""One-use authority for the private observability-owner bootstrap ordering fix."""

from __future__ import annotations

import argparse
import json
import re
import uuid
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

AUTHORIZATION_VERSION: Final = (
    "mobius.milestone-7.7.observability-operator-bootstrap.v1"
)
AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/observability-operator-bootstrap/v1\0"
)
AUTHORIZATION_NAMESPACE: Final = uuid.UUID("84f400a8-37d2-57bc-8a77-cc5b46d3605e")
TARGET_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-staging"
CLEANUP_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-cleanup-control"
CLEANUP_AUTOMATION_ACCOUNT: Final = "aa-mobius77-cleanup-recovery"
CLEANUP_ROLE_DEFINITION_ID: Final = "b24988ac-6180-42a0-ab88-20f7382dd24c"
KEY_VAULT: Final = "kv-mobius77-11564669"
POSTGRES_SERVER: Final = "psql-mobius77-11564669"
POSTGRES_DATABASE: Final = "opencanvas"
MANAGED_ENVIRONMENT: Final = "cae-mobius77-staging"
API_CONTAINER_APP: Final = "ca-mobius77-api"
MIGRATION_JOB: Final = "caj-mobius77-migration"
OWNER_READBACK_JOB: Final = "caj-mobius77-owner-readback"
API_IDENTITY: Final = "id-mobius77-api"
DATABASE_ADMINISTRATOR_IDENTITY: Final = "id-mobius77-db-admin"
WORKER_IDENTITY: Final = "id-mobius77-worker"
SESSION_SECRET: Final = "opencanvas-session-secret"
EXPECTED_DATABASE_REVISION: Final = "20260726_0028"
IMMUTABLE_API_IMAGE: Final = (
    "acrmobius7711564669.azurecr.io/opencanvas-api@"
    "sha256:f4cfbdb663f8cfc20318019ab3ae0fbe63a3b07b047fcf00359e1a89cc054d0e"
)
IMAGE_SOURCE_COMMIT: Final = "56380ce47649a3fc3ce525d921d498dc6bd39a56"
CANONICAL_IMAGE_INPUT_SHA256: Final = (
    "5f1a5b71c45e7b9183ed09205a5bd815b120e3c278026c4238c05834684b4c81"
)
RETAINED_PROOF_MARKER_INTEGRITY_SHA256: Final = (
    "acd390b610e9b71fcf7060167b29980233d27685c5d739d983259c2450e535eb"
)
COST_CEILING_USD_CENTS: Final = 25_000
MAXIMUM_AUTHORIZATION_AGE: Final = timedelta(hours=2)
MINIMUM_CLEANUP_HEADROOM: Final = timedelta(hours=3)
MINIMUM_DATABASE_ADMINISTRATOR_PROPAGATION: Final = timedelta(minutes=10)
ALLOWED_OPERATIONS: Final = (
    "verify-cleanup-executable-and-armed",
    "verify-frozen-immutable-image",
    "verify-session-secret-metadata",
    "provision-or-adopt-authoritative-postgresql",
    "verify-database-administrator-propagation",
    "define-one-exact-migration-job",
    "start-one-exact-migration-execution",
    "deploy-one-private-owner-signup-bootstrap",
    "verify-private-owner-signup-bootstrap",
    "define-one-exact-owner-readback-job",
    "start-one-exact-owner-readback-execution",
    "read-one-genuine-owner-users-id",
    "delete-exact-owner-readback-job",
    "authoritative-read-only-reconciliation",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ObservabilityOperatorBootstrapError(ValueError):
    """Raised when the owner-bootstrap authority expands or becomes stale."""


@dataclass(frozen=True, slots=True)
class ObservabilityOperatorBootstrapAuthorization:
    authorizationVersion: str
    authorizationId: str
    repositoryHead: str
    subscriptionId: str
    targetResourceGroupId: str
    cleanupAutomationAccountId: str
    cleanupDeadlineUtc: str
    cleanupRoleDefinitionId: str
    keyVaultId: str
    postgresServerId: str
    postgresDatabase: str
    managedEnvironmentId: str
    apiContainerAppId: str
    migrationJobId: str
    ownerReadbackJobId: str
    apiIdentityId: str
    databaseAdministratorIdentityId: str
    workerIdentityId: str
    sessionSecretName: str
    expectedDatabaseRevision: str
    apiImageDigest: str
    imageSourceCommit: str
    canonicalImageInputSha256: str
    retainedProofMarkerIntegritySha256: str
    authorizedAtUtc: str
    expiresAtUtc: str
    maximumCostUsdCents: int
    maximumMigrationExecutions: int
    maximumOwnerReadbackExecutions: int
    maximumBootstrapApiResources: int
    minimumDatabaseAdministratorPropagationSeconds: int
    privateIngressRequired: bool
    imageBuildAuthorized: bool
    imagePublicationAuthorized: bool
    scannerProofAuthorized: bool
    publicIngressAuthorized: bool
    fullApplicationDeploymentAuthorized: bool
    workerDeploymentAuthorized: bool
    telemetryDeploymentAuthorized: bool
    redisDeploymentAuthorized: bool
    keyVaultSecretValueAccessAuthorized: bool
    keyVaultSecretMutationAuthorized: bool
    databaseUserInsertAuthorized: bool
    migration0029Authorized: bool
    cleanupExecutionAuthorized: bool
    allowedOperations: tuple[str, ...]
    authorizationIntegritySha256: str


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise ObservabilityOperatorBootstrapError(code) from None


def _resource_ids(subscription_id: str) -> dict[str, str]:
    if _UUID.fullmatch(subscription_id) is None:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-subscription-invalid"
        )
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
        "cleanupRoleDefinitionId": (
            f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{CLEANUP_ROLE_DEFINITION_ID}"
        ),
        "keyVaultId": (f"{target}/providers/Microsoft.KeyVault/vaults/{KEY_VAULT}"),
        "postgresServerId": (
            f"{target}/providers/Microsoft.DBforPostgreSQL/flexibleServers/{POSTGRES_SERVER}"
        ),
        "managedEnvironmentId": (
            f"{target}/providers/Microsoft.App/managedEnvironments/{MANAGED_ENVIRONMENT}"
        ),
        "apiContainerAppId": (
            f"{target}/providers/Microsoft.App/containerApps/{API_CONTAINER_APP}"
        ),
        "migrationJobId": (f"{target}/providers/Microsoft.App/jobs/{MIGRATION_JOB}"),
        "ownerReadbackJobId": (
            f"{target}/providers/Microsoft.App/jobs/{OWNER_READBACK_JOB}"
        ),
        "apiIdentityId": (
            f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{API_IDENTITY}"
        ),
        "databaseAdministratorIdentityId": (
            f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
            f"{DATABASE_ADMINISTRATOR_IDENTITY}"
        ),
        "workerIdentityId": (
            f"{target}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{WORKER_IDENTITY}"
        ),
    }


def observability_operator_bootstrap_authorization_integrity(
    authorization: ObservabilityOperatorBootstrapAuthorization,
) -> str:
    body = asdict(authorization)
    body.pop("authorizationIntegritySha256", None)
    body["allowedOperations"] = list(authorization.allowedOperations)
    return integrity_sha256(cast(JsonValue, body), AUTHORIZATION_DOMAIN)


def build_observability_operator_bootstrap_authorization(
    *,
    repository_head: str,
    subscription_id: str,
    cleanup_deadline_utc: str,
    now_utc: datetime,
) -> ObservabilityOperatorBootstrapAuthorization:
    """Issue one replay-denying grant for the private owner bootstrap only."""

    if _SHA40.fullmatch(repository_head) is None:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-repository-head-invalid"
        )
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    deadline = _parse_utc(
        cleanup_deadline_utc, "observability-bootstrap-cleanup-deadline-invalid"
    )
    if deadline - current < MINIMUM_CLEANUP_HEADROOM:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-cleanup-window-insufficient"
        )
    expires = min(
        current + MAXIMUM_AUTHORIZATION_AGE,
        deadline - timedelta(hours=2),
    )
    if expires <= current:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-expired"
        )
    expected = _resource_ids(subscription_id)
    authorization_id = str(
        uuid.uuid5(
            AUTHORIZATION_NAMESPACE,
            f"{repository_head}:{subscription_id}:{cleanup_deadline_utc}:{_format_utc(current)}",
        )
    )
    unsigned = ObservabilityOperatorBootstrapAuthorization(
        authorizationVersion=AUTHORIZATION_VERSION,
        authorizationId=authorization_id,
        repositoryHead=repository_head,
        subscriptionId=subscription_id,
        targetResourceGroupId=expected["targetResourceGroupId"],
        cleanupAutomationAccountId=expected["cleanupAutomationAccountId"],
        cleanupDeadlineUtc=cleanup_deadline_utc,
        cleanupRoleDefinitionId=expected["cleanupRoleDefinitionId"],
        keyVaultId=expected["keyVaultId"],
        postgresServerId=expected["postgresServerId"],
        postgresDatabase=POSTGRES_DATABASE,
        managedEnvironmentId=expected["managedEnvironmentId"],
        apiContainerAppId=expected["apiContainerAppId"],
        migrationJobId=expected["migrationJobId"],
        ownerReadbackJobId=expected["ownerReadbackJobId"],
        apiIdentityId=expected["apiIdentityId"],
        databaseAdministratorIdentityId=(expected["databaseAdministratorIdentityId"]),
        workerIdentityId=expected["workerIdentityId"],
        sessionSecretName=SESSION_SECRET,
        expectedDatabaseRevision=EXPECTED_DATABASE_REVISION,
        apiImageDigest=IMMUTABLE_API_IMAGE,
        imageSourceCommit=IMAGE_SOURCE_COMMIT,
        canonicalImageInputSha256=CANONICAL_IMAGE_INPUT_SHA256,
        retainedProofMarkerIntegritySha256=(RETAINED_PROOF_MARKER_INTEGRITY_SHA256),
        authorizedAtUtc=_format_utc(current),
        expiresAtUtc=_format_utc(expires),
        maximumCostUsdCents=COST_CEILING_USD_CENTS,
        maximumMigrationExecutions=1,
        maximumOwnerReadbackExecutions=1,
        maximumBootstrapApiResources=1,
        minimumDatabaseAdministratorPropagationSeconds=int(
            MINIMUM_DATABASE_ADMINISTRATOR_PROPAGATION.total_seconds()
        ),
        privateIngressRequired=True,
        imageBuildAuthorized=False,
        imagePublicationAuthorized=False,
        scannerProofAuthorized=False,
        publicIngressAuthorized=False,
        fullApplicationDeploymentAuthorized=False,
        workerDeploymentAuthorized=False,
        telemetryDeploymentAuthorized=False,
        redisDeploymentAuthorized=False,
        keyVaultSecretValueAccessAuthorized=False,
        keyVaultSecretMutationAuthorized=False,
        databaseUserInsertAuthorized=False,
        migration0029Authorized=False,
        cleanupExecutionAuthorized=False,
        allowedOperations=ALLOWED_OPERATIONS,
        authorizationIntegritySha256="",
    )
    return replace(
        unsigned,
        authorizationIntegritySha256=(
            observability_operator_bootstrap_authorization_integrity(unsigned)
        ),
    )


def validate_observability_operator_bootstrap_authorization(
    authorization: ObservabilityOperatorBootstrapAuthorization,
    *,
    expected_repository_head: str,
    now_utc: datetime,
    require_unexpired: bool = True,
) -> ObservabilityOperatorBootstrapAuthorization:
    expected = _resource_ids(authorization.subscriptionId)
    exact: dict[str, object] = {
        "authorizationVersion": AUTHORIZATION_VERSION,
        "repositoryHead": expected_repository_head,
        "targetResourceGroupId": expected["targetResourceGroupId"],
        "cleanupAutomationAccountId": expected["cleanupAutomationAccountId"],
        "cleanupRoleDefinitionId": expected["cleanupRoleDefinitionId"],
        "keyVaultId": expected["keyVaultId"],
        "postgresServerId": expected["postgresServerId"],
        "postgresDatabase": POSTGRES_DATABASE,
        "managedEnvironmentId": expected["managedEnvironmentId"],
        "apiContainerAppId": expected["apiContainerAppId"],
        "migrationJobId": expected["migrationJobId"],
        "ownerReadbackJobId": expected["ownerReadbackJobId"],
        "apiIdentityId": expected["apiIdentityId"],
        "databaseAdministratorIdentityId": (
            expected["databaseAdministratorIdentityId"]
        ),
        "workerIdentityId": expected["workerIdentityId"],
        "sessionSecretName": SESSION_SECRET,
        "expectedDatabaseRevision": EXPECTED_DATABASE_REVISION,
        "apiImageDigest": IMMUTABLE_API_IMAGE,
        "imageSourceCommit": IMAGE_SOURCE_COMMIT,
        "canonicalImageInputSha256": CANONICAL_IMAGE_INPUT_SHA256,
        "retainedProofMarkerIntegritySha256": (RETAINED_PROOF_MARKER_INTEGRITY_SHA256),
        "maximumCostUsdCents": COST_CEILING_USD_CENTS,
        "maximumMigrationExecutions": 1,
        "maximumOwnerReadbackExecutions": 1,
        "maximumBootstrapApiResources": 1,
        "minimumDatabaseAdministratorPropagationSeconds": int(
            MINIMUM_DATABASE_ADMINISTRATOR_PROPAGATION.total_seconds()
        ),
        "privateIngressRequired": True,
        "imageBuildAuthorized": False,
        "imagePublicationAuthorized": False,
        "scannerProofAuthorized": False,
        "publicIngressAuthorized": False,
        "fullApplicationDeploymentAuthorized": False,
        "workerDeploymentAuthorized": False,
        "telemetryDeploymentAuthorized": False,
        "redisDeploymentAuthorized": False,
        "keyVaultSecretValueAccessAuthorized": False,
        "keyVaultSecretMutationAuthorized": False,
        "databaseUserInsertAuthorized": False,
        "migration0029Authorized": False,
        "cleanupExecutionAuthorized": False,
        "allowedOperations": ALLOWED_OPERATIONS,
    }
    for name, value in exact.items():
        if getattr(authorization, name) != value:
            raise ObservabilityOperatorBootstrapError(
                f"observability-bootstrap-{name}-invalid"
            )
    if _UUID.fullmatch(authorization.authorizationId) is None:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-id-invalid"
        )
    authorized = _parse_utc(
        authorization.authorizedAtUtc,
        "observability-bootstrap-authorization-time-invalid",
    )
    expires = _parse_utc(
        authorization.expiresAtUtc,
        "observability-bootstrap-authorization-expiry-invalid",
    )
    deadline = _parse_utc(
        authorization.cleanupDeadlineUtc,
        "observability-bootstrap-cleanup-deadline-invalid",
    )
    current = now_utc.astimezone(UTC).replace(microsecond=0)
    if expires <= authorized or expires - authorized > MAXIMUM_AUTHORIZATION_AGE:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-expiry-invalid"
        )
    if expires > deadline - timedelta(hours=2):
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-cleanup-reserve-invalid"
        )
    if require_unexpired and (current < authorized or current >= expires):
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-expired"
        )
    if deadline - current < timedelta(hours=2):
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-cleanup-window-insufficient"
        )
    expected_integrity = observability_operator_bootstrap_authorization_integrity(
        authorization
    )
    if (
        _SHA256.fullmatch(authorization.authorizationIntegritySha256) is None
        or authorization.authorizationIntegritySha256 != expected_integrity
    ):
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-integrity-invalid"
        )
    return authorization


def _from_mapping(
    value: Mapping[str, Any],
) -> ObservabilityOperatorBootstrapAuthorization:
    expected_fields = {
        field.name for field in fields(ObservabilityOperatorBootstrapAuthorization)
    }
    if set(value) != expected_fields:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-fields-invalid"
        )
    body = dict(value)
    operations = body.get("allowedOperations")
    if not isinstance(operations, list) or any(
        not isinstance(item, str) for item in operations
    ):
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-allowed-operations-invalid"
        )
    body["allowedOperations"] = tuple(operations)
    try:
        return ObservabilityOperatorBootstrapAuthorization(**body)
    except TypeError as exc:
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-malformed"
        ) from exc


def load_observability_operator_bootstrap_authorization(
    path: Path,
) -> ObservabilityOperatorBootstrapAuthorization:
    value = load_json(path)
    if not isinstance(value, Mapping):
        raise ObservabilityOperatorBootstrapError(
            "observability-bootstrap-authorization-malformed"
        )
    return _from_mapping(cast(Mapping[str, Any], value))


def write_observability_operator_bootstrap_authorization(
    path: Path, authorization: ObservabilityOperatorBootstrapAuthorization
) -> None:
    body = asdict(authorization)
    body["allowedOperations"] = list(authorization.allowedOperations)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(cast(JsonValue, body)))


def _parse_now(value: str) -> datetime:
    return _parse_utc(value, "observability-bootstrap-authorization-time-invalid")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-head", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--cleanup-deadline-utc", required=True)
    parser.add_argument("--authorized-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    authorization = build_observability_operator_bootstrap_authorization(
        repository_head=args.repository_head,
        subscription_id=args.subscription_id,
        cleanup_deadline_utc=args.cleanup_deadline_utc,
        now_utc=_parse_now(args.authorized_at_utc),
    )
    write_observability_operator_bootstrap_authorization(args.output, authorization)
    print(
        json.dumps(
            {
                "authorizationIntegritySha256": (
                    authorization.authorizationIntegritySha256
                ),
                "authorizationVersion": authorization.authorizationVersion,
                "output": str(args.output),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
