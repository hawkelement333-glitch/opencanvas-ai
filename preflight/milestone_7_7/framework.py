"""Fail-closed local contracts for Milestone 7.7 Checkpoint 6 scope."""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, cast

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
    validate_schema,
)

ROOT = Path(__file__).resolve().parent
INVENTORY_PATH = ROOT / "operation-inventory.json"
INVENTORY_SCHEMA_PATH = ROOT / "operation-inventory.schema.json"
SCOPE_PATH = ROOT / "scope-contract.json"
SCOPE_SCHEMA_PATH = ROOT / "scope-contract.schema.json"
EVIDENCE_SCHEMA_PATH = ROOT / "evidence.schema.json"

CONTRACT_VERSION: Final = "mobius.milestone-7.7.azure-topology-preflight.v1"
CANONICALIZATION_VERSION: Final = "mobius.milestone-7.7.canonical-json.v1"
INVENTORY_VERSION: Final = "mobius.milestone-7.7.azure-topology-operation-inventory.v1"
INTEGRITY_DOMAIN_TEXT: Final = (
    "solarplexus-mobius/milestone-7.7/checkpoint-6/azure-topology-preflight/v1"
)
SCOPE_DOMAIN: Final = (INTEGRITY_DOMAIN_TEXT + "\0").encode()
INVENTORY_DOMAIN: Final = (INTEGRITY_DOMAIN_TEXT + "/operation-inventory\0").encode()
EVIDENCE_DOMAIN: Final = (INTEGRITY_DOMAIN_TEXT + "/evidence\0").encode()

SOURCE_COMMIT: Final = "b81a6cada9d3be40aaa8eb3a68eb659a0755e1ac"
SUBSCRIPTION_FINGERPRINT: Final = (
    "f4493115ce6375cf0e5d0616bede57126075fdb27ac78ea0ba7e0085252a7028"
)
TENANT_FINGERPRINT: Final = (
    "702db9b14ed1014743e30242d59d5c6ef2578efd3213e0b62c5fcb13584ea85e"
)
TARGET_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-staging"
CLEANUP_RESOURCE_GROUP: Final = "rg-solarplexus-mobius-77-cleanup-control"
MAXIMUM_EVIDENCE_AGE_SECONDS: Final = 86_400
MAX_CANONICAL_BYTES: Final = 262_144
MAX_VERIFIER_BYTES: Final = 16_384

ALLOWED_GATE_STATES: Final = ("blocked", "failed", "proved", "unproved")
AUTHORITY_LEVELS: Final = (
    "official-azure-management-metadata",
    "repository-approved-scope",
    "subscription-scoped-control-plane",
)
INFRASTRUCTURE_GATES: Final = (
    "alert-destination",
    "evidence-retention",
    "exact-provider-api-versions",
    "managed-identity-environment-mapping",
    "openai-smtp-test-providers",
    "private-acr-source-path",
    "redis-custom-acl-support",
    "region-and-subscription-availability",
    "scanner-result-bridge",
    "telemetry-gateway",
)
RUNTIME_GATES: Final = (
    "cleanup-supervisor-runtime-proof",
    "effect-lock-runtime-proof",
    "fault-controller-shape",
    "isolated-environment",
    "live-failure-authorization",
)
EXIT_GATES: Final = (
    "active-context-matches-approved-scope",
    "all-operations-come-from-closed-inventory",
    "all-operations-read-only-verified",
    "all-observations-share-approved-scope",
    "all-observations-fresh-utc",
    "derived-evidence-minimum-field-only",
    "evidence-schema-canonicalization-integrity-pass",
    "all-infrastructure-gates-have-evidence-status",
    "no-required-observation-silently-missing",
    "negative-evidence-remains-visible",
    "runtime-gates-remain-unresolved",
    "no-mutation-data-plane-or-execution",
)
DEFERRED_WORK: Final = (
    "azure-topology-preflight-execution",
    "checkpoint-7",
    "deployment",
    "failure-injection",
    "milestone-7.8",
    "provisioning",
    "runtime-validation",
    "workload-execution",
)
OPERATION_IDS: Final = (
    "current-account-context",
    "regional-service-availability",
    "provider-registration-api-versions",
    "target-group-existence",
    "cleanup-group-existence",
    "regional-sku-capabilities",
    "subscription-quota-bounded-usage",
    "private-endpoint-network-support",
    "private-dns-prerequisites",
    "managed-identity-support",
    "scoped-rbac-prerequisites",
    "telemetry-diagnostic-prerequisites",
    "evidence-retention-prerequisites",
    "scanner-result-bridge-prerequisites",
    "external-test-provider-prerequisites",
    "bounded-cost-budget-prerequisites",
    "provisioning-dependency-blockers",
    "private-acr-source-prerequisites",
)
DEFINED_OPERATION_IDS: Final = ("current-account-context",)
EXPECTED_ACCOUNT_COMMAND: Final = (
    "az",
    "account",
    "show",
    "--only-show-errors",
    "--query",
    (
        "{environmentName:environmentName,state:state,isDefault:isDefault,"
        "userType:user.type,id:id,tenantId:tenantId}"
    ),
    "-o",
    "json",
)
EXPECTED_ACCOUNT_PROJECTION: Final = (
    "cloud",
    "is-default",
    "state",
    "subscription-fingerprint",
    "tenant-fingerprint",
    "user-type",
)
EXPECTED_ACCOUNT_TRANSFORMS: Final = (
    {
        "sourceField": "id",
        "retainedField": "subscription-fingerprint",
        "action": "domain-separated-sha256-lowercase",
        "domain": "mobius.azure.subscription-context.v1",
    },
    {
        "sourceField": "tenantId",
        "retainedField": "tenant-fingerprint",
        "action": "domain-separated-sha256-lowercase",
        "domain": "mobius.azure.tenant-context.v1",
    },
)
EXPECTED_OPERATION_POLICY: Final = {
    "current-account-context": (
        ("region-and-subscription-availability",),
        ("global",),
        "approved-account-context",
        "subscription-scoped-control-plane",
    ),
    "regional-service-availability": (
        ("region-and-subscription-availability",),
        ("northcentralus", "southcentralus"),
        "approved-regions",
        "official-azure-management-metadata",
    ),
    "provider-registration-api-versions": (
        ("exact-provider-api-versions",),
        ("global", "northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "official-azure-management-metadata",
    ),
    "target-group-existence": (
        ("region-and-subscription-availability",),
        ("southcentralus",),
        "approved-target-resource-group",
        "subscription-scoped-control-plane",
    ),
    "cleanup-group-existence": (
        ("region-and-subscription-availability",),
        ("southcentralus",),
        "approved-cleanup-control-resource-group",
        "subscription-scoped-control-plane",
    ),
    "regional-sku-capabilities": (
        ("redis-custom-acl-support", "region-and-subscription-availability"),
        ("northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "official-azure-management-metadata",
    ),
    "subscription-quota-bounded-usage": (
        ("region-and-subscription-availability",),
        ("northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "subscription-scoped-control-plane",
    ),
    "private-endpoint-network-support": (
        ("region-and-subscription-availability",),
        ("northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "official-azure-management-metadata",
    ),
    "private-dns-prerequisites": (
        ("region-and-subscription-availability",),
        ("northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "official-azure-management-metadata",
    ),
    "managed-identity-support": (
        ("managed-identity-environment-mapping",),
        ("northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "official-azure-management-metadata",
    ),
    "scoped-rbac-prerequisites": (
        ("managed-identity-environment-mapping",),
        ("global",),
        "approved-future-resource-groups",
        "subscription-scoped-control-plane",
    ),
    "telemetry-diagnostic-prerequisites": (
        ("alert-destination", "telemetry-gateway"),
        ("northcentralus", "southcentralus"),
        "approved-future-resource-groups",
        "official-azure-management-metadata",
    ),
    "evidence-retention-prerequisites": (
        ("evidence-retention",),
        ("southcentralus",),
        "approved-target-resource-group",
        "official-azure-management-metadata",
    ),
    "scanner-result-bridge-prerequisites": (
        ("scanner-result-bridge",),
        ("southcentralus",),
        "approved-target-resource-group",
        "official-azure-management-metadata",
    ),
    "external-test-provider-prerequisites": (
        ("openai-smtp-test-providers",),
        ("southcentralus",),
        "approved-target-resource-group",
        "repository-approved-scope",
    ),
    "bounded-cost-budget-prerequisites": (
        ("region-and-subscription-availability",),
        ("global", "northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "subscription-scoped-control-plane",
    ),
    "provisioning-dependency-blockers": (
        INFRASTRUCTURE_GATES,
        ("global", "northcentralus", "southcentralus"),
        "approved-subscription-metadata",
        "repository-approved-scope",
    ),
    "private-acr-source-prerequisites": (
        ("private-acr-source-path",),
        ("southcentralus",),
        "approved-target-resource-group",
        "official-azure-management-metadata",
    ),
}

RAW_UUID = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"
)
RESOURCE_ID = re.compile(r"(?i)/subscriptions/[^/\s]+(?:/resourcegroups/[^/\s]+)?")
EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
SIGNED_URL = re.compile(r"(?i)[?&](?:sig|se|sp|sv|token)=")
PRIVATE_HOST = re.compile(r"(?i)\b(?:privatelink|internal|corp)\.[a-z0-9.-]+\b")
LOCAL_PATH = re.compile(
    r"(?i)(?:\b[A-Za-z]:\\Users\\[^\\\s]+\\|"
    + "/"
    + r"Users/[^/\s]+/|"
    + "/"
    + r"home/[^/\s]+/)"
)
RFC1918 = re.compile(
    r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)"
)
FORBIDDEN_COMMAND_TOKENS: Final = frozenset(
    {
        "add",
        "apply",
        "assign",
        "create",
        "delete",
        "deploy",
        "disable",
        "download",
        "enable",
        "export",
        "failover",
        "get-access-token",
        "grant",
        "import",
        "invoke",
        "login",
        "logout",
        "migrate",
        "move",
        "purge",
        "recover",
        "regenerate",
        "register",
        "remove",
        "restart",
        "restore",
        "revoke",
        "rotate",
        "run",
        "set",
        "start",
        "stop",
        "sync",
        "unregister",
        "update",
        "upload",
        "validate",
        "what-if",
    }
)
FORBIDDEN_DATA_PLANE_TOKENS: Final = frozenset(
    {
        "blob",
        "certificate",
        "key",
        "message",
        "queue",
        "secret",
    }
)


def _as_dict(value: JsonValue, location: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ContractError(f"{location}: expected an object")
    return value


def _as_list(value: JsonValue, location: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ContractError(f"{location}: expected an array")
    return value


def _as_str(value: JsonValue, location: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{location}: expected a string")
    return value


def _copy_json(value: JsonValue) -> JsonValue:
    return copy.deepcopy(value)


def _walk_sensitive(value: JsonValue, location: str = "$") -> None:
    if isinstance(value, str):
        for pattern in (
            RAW_UUID,
            RESOURCE_ID,
            EMAIL,
            JWT,
            SIGNED_URL,
            PRIVATE_HOST,
            LOCAL_PATH,
            RFC1918,
        ):
            if pattern.search(value):
                raise ContractError(
                    f"{location}: raw Azure, private, secret, or local-path text "
                    "is prohibited"
                )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_sensitive(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_sensitive(item, f"{location}.{key}")


def _without_integrity(
    value: dict[str, JsonValue], integrity_field: str
) -> dict[str, JsonValue]:
    normalized = cast(dict[str, JsonValue], _copy_json(value))
    normalized.pop(integrity_field, None)
    return normalized


def inventory_integrity_sha256(value: dict[str, JsonValue]) -> str:
    return integrity_sha256(
        _without_integrity(value, "inventoryIntegritySha256"),
        INVENTORY_DOMAIN,
    )


def scope_integrity_sha256(value: dict[str, JsonValue]) -> str:
    return integrity_sha256(
        _without_integrity(value, "scopeIntegritySha256"),
        SCOPE_DOMAIN,
    )


def _normalized_evidence(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    normalized = _without_integrity(value, "evidenceIntegritySha256")
    observations = _as_list(normalized["observations"], "$.observations")
    for observation_value in observations:
        observation = _as_dict(observation_value, "$.observations[]")
        fields = _as_list(observation["fields"], "$.observations[].fields")
        fields.sort(
            key=lambda item: _as_str(_as_dict(item, "$.fields[]")["id"], "$.id")
        )
    observations.sort(
        key=lambda item: _as_str(
            _as_dict(item, "$.observations[]")["operationId"], "$.id"
        )
    )
    for registry_name in ("infrastructureGates", "runtimeGates"):
        registry = _as_list(normalized[registry_name], f"$.{registry_name}")
        registry.sort(
            key=lambda item: _as_str(
                _as_dict(item, f"$.{registry_name}[]")["gateId"], "$.id"
            )
        )
        for row_value in registry:
            row = _as_dict(row_value, f"$.{registry_name}[]")
            operation_ids = _as_list(
                row["operationIds"], f"$.{registry_name}[].operationIds"
            )
            operation_ids.sort(key=lambda item: _as_str(item, "$.operationIds[]"))
    return normalized


def evidence_integrity_sha256(value: dict[str, JsonValue]) -> str:
    return integrity_sha256(_normalized_evidence(value), EVIDENCE_DOMAIN)


def _operation_rows(
    inventory: dict[str, JsonValue],
) -> list[dict[str, JsonValue]]:
    return [
        _as_dict(item, "$.operations[]")
        for item in _as_list(inventory["operations"], "$.operations")
    ]


def validate_operation_inventory(value: JsonValue) -> dict[str, JsonValue]:
    inventory = _as_dict(_copy_json(value), "$")
    schema = _as_dict(load_json(INVENTORY_SCHEMA_PATH), "$schema")
    validate_schema(inventory, schema)
    if len(canonical_bytes(inventory)) > MAX_CANONICAL_BYTES:
        raise ContractError("operation inventory exceeds the canonical byte limit")
    _walk_sensitive(inventory)

    rows = _operation_rows(inventory)
    ids = tuple(_as_str(row["id"], "$.operations[].id") for row in rows)
    if ids != OPERATION_IDS:
        raise ContractError("operation inventory IDs or order differ")
    if len(set(ids)) != len(ids):
        raise ContractError("operation inventory IDs must be unique")

    covered_gates: set[str] = set()
    for row in rows:
        operation_id = _as_str(row["id"], "$.operations[].id")
        supports = tuple(
            _as_str(item, "$.operations[].supports[]")
            for item in _as_list(row["supports"], "$.operations[].supports")
        )
        expected_supports, expected_regions, expected_scope, expected_authority = (
            EXPECTED_OPERATION_POLICY[operation_id]
        )
        if supports != expected_supports:
            raise ContractError(f"{operation_id}: operation gate binding differs")
        covered_gates.update(supports)
        regions = tuple(
            _as_str(item, "$.operations[].permittedRegions[]")
            for item in _as_list(
                row["permittedRegions"], "$.operations[].permittedRegions"
            )
        )
        if regions != expected_regions:
            raise ContractError(f"{operation_id}: permitted regions differ")
        if row["permittedScope"] != expected_scope:
            raise ContractError(f"{operation_id}: permitted scope differs")
        if row["authorityLevel"] != expected_authority:
            raise ContractError(f"{operation_id}: authority level differs")
        if row["controlPlane"] is not True or row["dataPlane"] is not False:
            raise ContractError(f"{operation_id}: operation is not control-plane-only")
        if row["mutating"] is not False:
            raise ContractError(f"{operation_id}: mutating operations are prohibited")
        if row["maximumEvidenceAgeSeconds"] != MAXIMUM_EVIDENCE_AGE_SECONDS:
            raise ContractError(f"{operation_id}: evidence age differs")

        status = _as_str(row["definitionStatus"], "$.definitionStatus")
        command_value = row["commandTemplate"]
        if status == "defined":
            if operation_id not in DEFINED_OPERATION_IDS:
                raise ContractError(f"{operation_id}: unexpected executable operation")
            command = tuple(
                _as_str(item, "$.commandTemplate[]")
                for item in _as_list(command_value, "$.commandTemplate")
            )
            if command != EXPECTED_ACCOUNT_COMMAND:
                raise ContractError(
                    "current-account command differs from the closed template"
                )
            lowered_tokens = {token.lower() for token in command}
            if lowered_tokens & FORBIDDEN_COMMAND_TOKENS:
                raise ContractError(
                    "defined command contains a prohibited mutating token"
                )
            if lowered_tokens & FORBIDDEN_DATA_PLANE_TOKENS:
                raise ContractError(
                    "defined command contains a prohibited data-plane token"
                )
            if row["managementMethod"] != "local-context":
                raise ContractError("current-account management method differs")
            if row["semanticReadOnlyVerified"] is not True:
                raise ContractError("defined operation is not read-only verified")
            projection = tuple(
                _as_str(item, "$.retainedProjection[]")
                for item in _as_list(row["retainedProjection"], "$.retainedProjection")
            )
            if projection != EXPECTED_ACCOUNT_PROJECTION:
                raise ContractError("current-account retained projection differs")
            transforms = _as_list(row["transforms"], "$.transforms")
            if (
                transforms != list(EXPECTED_ACCOUNT_TRANSFORMS)
                or row["failureBehavior"]
                != "record-failure-and-stop-context-verification"
                or row["readOnlyProof"]
                != "current-account-show-has-no-control-plane-or-data-plane-mutation"
                or row["blockingReason"] is not None
            ):
                raise ContractError(
                    "current-account transform or blocking state differs"
                )
        elif status == "blocked":
            if command_value is not None:
                raise ContractError(f"{operation_id}: blocked operation has a command")
            if row["managementMethod"] != "unresolved":
                raise ContractError(
                    f"{operation_id}: blocked method must remain unresolved"
                )
            if row["semanticReadOnlyVerified"] is not False:
                raise ContractError(
                    f"{operation_id}: blocked operation claims verification"
                )
            if _as_list(row["retainedProjection"], "$.retainedProjection"):
                raise ContractError(
                    f"{operation_id}: blocked projection must remain empty"
                )
            if _as_list(row["transforms"], "$.transforms"):
                raise ContractError(
                    f"{operation_id}: blocked transforms must remain empty"
                )
            if (
                row["failureBehavior"] != "record-blocked-and-do-not-execute"
                or row["readOnlyProof"]
                != "unavailable-no-repository-verified-command-template"
                or row["blockingReason"]
                != "repository-does-not-bind-an-exact-safe-command-template"
            ):
                raise ContractError(f"{operation_id}: blocked evidence is incomplete")
        else:
            raise ContractError(f"{operation_id}: unsupported definition status")

    if covered_gates != set(INFRASTRUCTURE_GATES):
        raise ContractError(
            "operation inventory does not cover every infrastructure gate"
        )
    if inventory["inventoryIntegritySha256"] != inventory_integrity_sha256(inventory):
        raise ContractError("operation inventory integrity mismatch")
    return inventory


def load_operation_inventory() -> dict[str, JsonValue]:
    return validate_operation_inventory(load_json(INVENTORY_PATH))


def _scope_without_integrity(inventory_sha256: str) -> dict[str, JsonValue]:
    return {
        "schemaVersion": "2020-12",
        "contractVersion": CONTRACT_VERSION,
        "canonicalizationVersion": CANONICALIZATION_VERSION,
        "integrityDomain": INTEGRITY_DOMAIN_TEXT,
        "scopeId": "m7.7-cp6-azure-topology-scope",
        "sourceCommit": SOURCE_COMMIT,
        "checkpointStatus": (
            "blocked-pending-separately-authorized-azure-topology-preflight-execution"
        ),
        "azureExecutionAuthorized": False,
        "provisioningAuthorized": False,
        "azureScope": {
            "cloud": "AzureCloud",
            "fingerprintAlgorithm": (
                "domain-separated-sha256-of-lowercase-identifier-v1"
            ),
            "subscriptionFingerprint": SUBSCRIPTION_FINGERPRINT,
            "tenantFingerprint": TENANT_FINGERPRINT,
            "primaryRegion": {
                "name": "southcentralus",
                "displayName": "South Central US",
            },
            "recoveryComparisonRegion": {
                "name": "northcentralus",
                "displayName": "North Central US",
            },
            "targetResourceGroup": TARGET_RESOURCE_GROUP,
            "cleanupControlResourceGroup": CLEANUP_RESOURCE_GROUP,
            "resourceGroupsAreIntendedFutureScopesOnly": True,
        },
        "evidencePolicy": {
            "contractVersion": CONTRACT_VERSION,
            "schemaFile": "evidence.schema.json",
            "maximumAgeSeconds": MAXIMUM_EVIDENCE_AGE_SECONDS,
            "timestampFormat": "rfc3339-utc-z-seconds",
            "allowedGateStates": list(ALLOWED_GATE_STATES),
            "authorityLevels": list(AUTHORITY_LEVELS),
            "checksumIsSignature": False,
            "minimumFieldProjectionRequired": True,
            "rawAzureOutputRetentionAllowed": False,
            "mixedScopeEvidenceAllowed": False,
            "runtimeGateResolutionFromMetadataAllowed": False,
        },
        "operationInventory": {
            "version": INVENTORY_VERSION,
            "file": "operation-inventory.json",
            "sha256": inventory_sha256,
            "defaultDecision": "deny",
        },
        "gatePolicy": {
            "infrastructureGates": [
                {"id": gate, "scopeDefinitionState": "defined-unresolved"}
                for gate in INFRASTRUCTURE_GATES
            ],
            "runtimeGates": [
                {"id": gate, "scopeDefinitionState": "runtime-unresolved"}
                for gate in RUNTIME_GATES
            ],
            "runtimeGatesRemainUnresolved": True,
            "topologyMetadataMayResolveRuntimeGates": False,
        },
        "exitGates": list(EXIT_GATES),
        "privacyRules": {
            "rawAzureIdentifiersAllowed": False,
            "principalEnumerationAllowed": False,
            "dataPlaneEvidenceAllowed": False,
            "privateEndpointOrHostnameRetentionAllowed": False,
            "emailRetentionAllowed": False,
            "credentialOrTokenRetentionAllowed": False,
            "minimumFieldProjectionRequired": True,
            "fingerprintBeforeRetentionRequired": True,
        },
        "failureRules": {
            "unknownOperation": "deny",
            "missingEvidence": "record-and-block",
            "staleEvidence": "reject",
            "malformedEvidence": "reject",
            "conflictingEvidence": "reject",
            "tamperedEvidence": "reject",
            "outOfScopeEvidence": "reject",
            "mutatingOperation": "deny-and-record",
            "dataPlaneOperation": "deny-and-record",
        },
        "deferredWork": list(DEFERRED_WORK),
    }


def build_scope_contract() -> dict[str, JsonValue]:
    inventory = load_operation_inventory()
    inventory_sha256 = _as_str(
        inventory["inventoryIntegritySha256"], "$.inventoryIntegritySha256"
    )
    scope = _scope_without_integrity(inventory_sha256)
    scope["scopeIntegritySha256"] = scope_integrity_sha256(scope)
    return validate_scope_contract(scope, inventory=inventory)


def validate_scope_contract(
    value: JsonValue,
    *,
    inventory: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    scope = _as_dict(_copy_json(value), "$")
    schema = _as_dict(load_json(SCOPE_SCHEMA_PATH), "$schema")
    validate_schema(scope, schema)
    if len(canonical_bytes(scope)) > MAX_CANONICAL_BYTES:
        raise ContractError("scope contract exceeds the canonical byte limit")
    _walk_sensitive(scope)

    current_inventory = load_operation_inventory() if inventory is None else inventory
    inventory_sha256 = _as_str(
        current_inventory["inventoryIntegritySha256"],
        "$.inventoryIntegritySha256",
    )
    expected = _scope_without_integrity(inventory_sha256)
    actual_without_integrity = _without_integrity(scope, "scopeIntegritySha256")
    if actual_without_integrity != expected:
        raise ContractError("scope contract differs from the approved closed contract")
    if scope["scopeIntegritySha256"] != scope_integrity_sha256(scope):
        raise ContractError("scope contract integrity mismatch")
    return scope


def load_scope_contract() -> dict[str, JsonValue]:
    return validate_scope_contract(load_json(SCOPE_PATH))


def _parse_utc(value: JsonValue, location: str) -> datetime:
    text = _as_str(value, location)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ContractError(
            f"{location}: timestamp must be RFC3339 UTC seconds"
        ) from exc
    return parsed


def _unique_rows(
    values: JsonValue,
    *,
    id_field: str,
    expected_ids: tuple[str, ...],
    location: str,
) -> list[dict[str, JsonValue]]:
    rows = [_as_dict(item, f"{location}[]") for item in _as_list(values, location)]
    ids = [_as_str(row[id_field], f"{location}[].{id_field}") for row in rows]
    if len(ids) != len(set(ids)):
        raise ContractError(f"{location}: duplicate records are prohibited")
    if set(ids) != set(expected_ids):
        raise ContractError(f"{location}: records are missing or unknown")
    return rows


def validate_evidence(
    value: JsonValue,
    *,
    now: datetime,
) -> dict[str, JsonValue]:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ContractError("evidence verification time must be timezone-aware UTC")
    evidence = _as_dict(_copy_json(value), "$")
    schema = _as_dict(load_json(EVIDENCE_SCHEMA_PATH), "$schema")
    validate_schema(evidence, schema)
    if len(canonical_bytes(evidence)) > MAX_CANONICAL_BYTES:
        raise ContractError("evidence package exceeds the canonical byte limit")
    _walk_sensitive(evidence)

    scope = load_scope_contract()
    inventory = load_operation_inventory()
    scope_sha256 = _as_str(scope["scopeIntegritySha256"], "$.scopeIntegritySha256")
    inventory_sha256 = _as_str(
        inventory["inventoryIntegritySha256"], "$.inventoryIntegritySha256"
    )
    if evidence["scopeIntegritySha256"] != scope_sha256:
        raise ContractError("evidence uses a mixed or unknown scope")
    if evidence["operationInventorySha256"] != inventory_sha256:
        raise ContractError("evidence uses an unknown operation inventory")

    observed_at = _parse_utc(evidence["observedAtUtc"], "$.observedAtUtc")
    verified_at = _parse_utc(evidence["verifiedAtUtc"], "$.verifiedAtUtc")
    expires_at = _parse_utc(evidence["expiresAtUtc"], "$.expiresAtUtc")
    if verified_at < observed_at:
        raise ContractError("evidence verification precedes observation")
    if expires_at != observed_at + timedelta(seconds=MAXIMUM_EVIDENCE_AGE_SECONDS):
        raise ContractError("evidence expiration differs from the 24-hour contract")
    if now < observed_at or now > expires_at:
        raise ContractError("evidence is future-dated or stale")

    operation_rows = {
        _as_str(row["id"], "$.operations[].id"): row
        for row in _operation_rows(inventory)
    }
    observations = _unique_rows(
        evidence["observations"],
        id_field="operationId",
        expected_ids=OPERATION_IDS,
        location="$.observations",
    )
    observation_statuses: dict[str, str] = {}
    observation_times: list[datetime] = []
    for observation in observations:
        operation_id = _as_str(
            observation["operationId"], "$.observations[].operationId"
        )
        operation = operation_rows[operation_id]
        status = _as_str(observation["status"], "$.observations[].status")
        observation_statuses[operation_id] = status
        observation_time = _parse_utc(
            observation["observedAtUtc"], "$.observations[].observedAtUtc"
        )
        observation_times.append(observation_time)
        if observation_time < observed_at or observation_time > verified_at:
            raise ContractError("observation timestamp is outside the package window")
        if observation["scopeIntegritySha256"] != scope_sha256:
            raise ContractError("observation scope differs")
        if observation["authorityLevel"] != operation["authorityLevel"]:
            raise ContractError(f"{operation_id}: authority level differs")

        fields = [
            _as_dict(item, "$.observations[].fields[]")
            for item in _as_list(observation["fields"], "$.observations[].fields")
        ]
        field_ids = [_as_str(item["id"], "$.fields[].id") for item in fields]
        if len(field_ids) != len(set(field_ids)):
            raise ContractError(f"{operation_id}: duplicate retained fields")
        permitted_fields = {
            _as_str(item, "$.retainedProjection[]")
            for item in _as_list(
                operation["retainedProjection"], "$.retainedProjection"
            )
        }
        if not set(field_ids).issubset(permitted_fields):
            raise ContractError(f"{operation_id}: output exceeds minimum projection")

        if operation["definitionStatus"] == "blocked":
            if (
                status != "blocked"
                or fields
                or observation["explanationCode"] != "operation-template-blocked"
            ):
                raise ContractError(
                    f"{operation_id}: blocked operation cannot claim observation"
                )
        elif status == "proved":
            if set(field_ids) != permitted_fields:
                raise ContractError(
                    f"{operation_id}: proved result lacks the exact projection"
                )
            field_map = {str(item["id"]): item["value"] for item in fields}
            if field_map.get("cloud") != "AzureCloud":
                raise ContractError("current-account cloud differs")
            if field_map.get("is-default") is not True:
                raise ContractError("current-account selection is not active")
            if field_map.get("state") != "Enabled":
                raise ContractError("current-account state is not enabled")
            if field_map.get("subscription-fingerprint") != SUBSCRIPTION_FINGERPRINT:
                raise ContractError("current-account subscription fingerprint differs")
            if field_map.get("tenant-fingerprint") != TENANT_FINGERPRINT:
                raise ContractError("current-account tenant fingerprint differs")
        elif fields:
            raise ContractError(
                f"{operation_id}: negative observation must not retain projected fields"
            )

    if min(observation_times) != observed_at:
        raise ContractError("package observation time is not the earliest observation")

    infrastructure_rows = _unique_rows(
        evidence["infrastructureGates"],
        id_field="gateId",
        expected_ids=INFRASTRUCTURE_GATES,
        location="$.infrastructureGates",
    )
    for gate_row in infrastructure_rows:
        gate_id = _as_str(gate_row["gateId"], "$.infrastructureGates[].gateId")
        operation_ids = [
            _as_str(item, "$.operationIds[]")
            for item in _as_list(gate_row["operationIds"], "$.operationIds")
        ]
        if len(operation_ids) != len(set(operation_ids)):
            raise ContractError(f"{gate_id}: duplicate operation references")
        required_operations = {
            operation_id
            for operation_id, operation in operation_rows.items()
            if gate_id
            in {
                _as_str(item, "$.supports[]")
                for item in _as_list(operation["supports"], "$.supports")
            }
        }
        if set(operation_ids) != required_operations:
            raise ContractError(f"{gate_id}: operation evidence is incomplete")
        statuses = {
            observation_statuses[operation_id] for operation_id in operation_ids
        }
        expected_status = (
            "failed"
            if "failed" in statuses
            else "blocked"
            if "blocked" in statuses
            else "unproved"
            if "unproved" in statuses
            else "proved"
        )
        if gate_row["status"] != expected_status:
            raise ContractError(f"{gate_id}: gate status conflicts with observations")

    runtime_rows = _unique_rows(
        evidence["runtimeGates"],
        id_field="gateId",
        expected_ids=RUNTIME_GATES,
        location="$.runtimeGates",
    )
    for runtime_row in runtime_rows:
        if runtime_row["status"] != "unproved" or _as_list(
            runtime_row["operationIds"], "$.runtimeGates[].operationIds"
        ):
            raise ContractError("topology metadata cannot resolve a runtime gate")

    completion = _as_dict(evidence["completion"], "$.completion")
    all_infrastructure_proved = all(
        row["status"] == "proved" for row in infrastructure_rows
    )
    blocked_inventory_exists = any(
        row["definitionStatus"] == "blocked" for row in operation_rows.values()
    )
    expected_preflight_status = (
        "complete-preflight"
        if all_infrastructure_proved and not blocked_inventory_exists
        else "complete-with-provisioning-blocked"
    )
    if completion["preflightStatus"] != expected_preflight_status:
        raise ContractError("preflight completion status conflicts with gate evidence")
    if evidence["evidenceIntegritySha256"] != evidence_integrity_sha256(evidence):
        raise ContractError("evidence package integrity mismatch")
    return evidence


def scope_verification_result() -> dict[str, JsonValue]:
    scope = load_scope_contract()
    inventory = load_operation_inventory()
    rows = _operation_rows(inventory)
    return {
        "status": "valid",
        "contractVersion": CONTRACT_VERSION,
        "scopeIntegritySha256": scope["scopeIntegritySha256"],
        "operationInventorySha256": inventory["inventoryIntegritySha256"],
        "operationCount": len(rows),
        "definedOperationCount": sum(
            row["definitionStatus"] == "defined" for row in rows
        ),
        "blockedOperationCount": sum(
            row["definitionStatus"] == "blocked" for row in rows
        ),
        "infrastructureGateCount": len(INFRASTRUCTURE_GATES),
        "runtimeGateCount": len(RUNTIME_GATES),
        "azureExecutionAuthorized": False,
        "provisioningAuthorized": False,
        "checkpoint6Status": scope["checkpointStatus"],
        "checksumIsSignature": False,
        "verifierVersion": "mobius.m7.7.azure-topology-scope-verifier.v1",
    }
