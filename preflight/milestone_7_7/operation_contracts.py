"""Inert, fail-closed operation contracts for Milestone 7.7 Checkpoint 7.

The module validates a local definition matrix. It intentionally contains no
process, network, Azure, deployment, workload, migration, or persistence path.
An operation definition is not execution authority and is not evidence that an
operation ran.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Final

from performance.milestone_7_7.framework import (
    ContractError,
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
    validate_schema,
)
from preflight.milestone_7_7.framework import (
    CANONICALIZATION_VERSION,
    INFRASTRUCTURE_GATES,
    INVENTORY_VERSION,
    MAXIMUM_EVIDENCE_AGE_SECONDS,
    RUNTIME_GATES,
    _walk_sensitive,
    load_operation_inventory,
    load_scope_contract,
)

ROOT = Path(__file__).resolve().parent
MATRIX_PATH = ROOT / "operation-contracts.json"
MATRIX_SCHEMA_PATH = ROOT / "operation-contracts.schema.json"

CONTRACT_VERSION: Final = "mobius.milestone-7.7.azure-topology-operation-contracts.v1"
SCOPE_CONTRACT_VERSION: Final = "mobius.milestone-7.7.azure-topology-preflight.v1"
INTEGRITY_DOMAIN_TEXT: Final = (
    "solarplexus-mobius/milestone-7.7/checkpoint-7/"
    "azure-topology-operation-contracts/v1"
)
INTEGRITY_DOMAIN: Final = (INTEGRITY_DOMAIN_TEXT + "\0").encode()
SOURCE_COMMIT: Final = "39f6409a44e1e9219e001eda80adb126559c94f2"
PRIOR_INVENTORY_SHA256: Final = (
    "923cbf934040405fd1702b49bd79d876ee3e85fe88d68bbb3d94f980fa45b843"
)
SCOPE_SHA256: Final = "a98776f4d2ea33f64e28514fc7c13d2e6160a79ea29247f79fc71f4ffe529e3e"
MAX_CANONICAL_BYTES: Final = 262_144
MAX_VERIFIER_BYTES: Final = 16_384

OPERATION_IDS: Final = (
    "regional-service-availability",
    "provider-registration-api-versions",
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

_OPERATION_POLICY: Final[dict[str, dict[str, JsonValue]]] = {
    "regional-service-availability": {
        "supports": ["region-and-subscription-availability"],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-regions",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-subscription-scope",
            "approved-primary-and-recovery-regions",
            "official-minimum-service-availability-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-service-availability-method-and-parser"
        ),
    },
    "provider-registration-api-versions": {
        "supports": ["exact-provider-api-versions"],
        "regions": ["global", "northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-subscription-scope",
            "closed-provider-namespace-list",
            "official-minimum-api-version-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": ("no-repository-verified-provider-version-method-and-parser"),
    },
    "regional-sku-capabilities": {
        "supports": [
            "redis-custom-acl-support",
            "region-and-subscription-availability",
        ],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-subscription-scope",
            "approved-primary-and-recovery-regions",
            "closed-resource-type-and-sku-registry",
            "official-minimum-capability-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-regional-sku-capability-method-and-parser"
        ),
    },
    "subscription-quota-bounded-usage": {
        "supports": ["region-and-subscription-availability"],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "subscription-scoped-control-plane",
        "requiredInputs": [
            "approved-subscription-scope",
            "approved-primary-and-recovery-regions",
            "closed-quota-and-usage-dimension-registry",
            "official-minimum-quota-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": ("no-repository-verified-quota-usage-method-and-parser"),
    },
    "private-endpoint-network-support": {
        "supports": ["region-and-subscription-availability"],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-subscription-scope",
            "approved-primary-and-recovery-regions",
            "closed-private-endpoint-resource-type-registry",
            "official-minimum-network-support-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-private-endpoint-support-method-and-parser"
        ),
    },
    "private-dns-prerequisites": {
        "supports": ["region-and-subscription-availability"],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-subscription-scope",
            "closed-private-dns-requirement-registry",
            "official-minimum-private-dns-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "private-endpoint-network-support-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-private-dns-prerequisite-method-and-parser"
        ),
    },
    "managed-identity-support": {
        "supports": ["managed-identity-environment-mapping"],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-subscription-scope",
            "approved-primary-and-recovery-regions",
            "closed-workload-identity-capability-registry",
            "official-minimum-identity-support-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-managed-identity-support-method-and-parser"
        ),
    },
    "scoped-rbac-prerequisites": {
        "supports": ["managed-identity-environment-mapping"],
        "regions": ["global"],
        "scope": "approved-future-resource-groups",
        "authority": "subscription-scoped-control-plane",
        "requiredInputs": [
            "approved-future-resource-group-scopes",
            "closed-least-privilege-role-matrix",
            "official-minimum-role-definition-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "managed-identity-support-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-scoped-rbac-prerequisite-method-and-parser"
        ),
    },
    "telemetry-diagnostic-prerequisites": {
        "supports": ["alert-destination", "telemetry-gateway"],
        "regions": ["northcentralus", "southcentralus"],
        "scope": "approved-future-resource-groups",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-future-resource-group-scopes",
            "closed-telemetry-resource-type-registry",
            "closed-diagnostic-category-registry",
            "official-minimum-telemetry-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-telemetry-prerequisite-method-and-parser"
        ),
    },
    "evidence-retention-prerequisites": {
        "supports": ["evidence-retention"],
        "regions": ["southcentralus"],
        "scope": "approved-target-resource-group",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-target-resource-group-scope",
            "closed-evidence-classification-and-retention-policy",
            "closed-immutability-and-deletion-policy",
            "official-minimum-retention-capability-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-evidence-retention-method-and-parser"
        ),
    },
    "scanner-result-bridge-prerequisites": {
        "supports": ["scanner-result-bridge"],
        "regions": ["southcentralus"],
        "scope": "approved-target-resource-group",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-target-resource-group-scope",
            "closed-scanner-event-contract",
            "closed-scanner-result-routing-contract",
            "official-minimum-scanner-bridge-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "exact-provider-api-versions-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": ("no-repository-verified-scanner-bridge-method-and-parser"),
    },
    "external-test-provider-prerequisites": {
        "supports": ["openai-smtp-test-providers"],
        "regions": ["southcentralus"],
        "scope": "approved-target-resource-group",
        "authority": "repository-approved-scope",
        "requiredInputs": [
            "approved-synthetic-provider-test-contract",
            "closed-provider-identity-and-limit-registry",
            "closed-secret-reference-policy",
            "minimum-provider-readiness-projection",
        ],
        "prerequisites": [
            "approved-synthetic-data-only",
            "approved-provider-cost-and-retention-boundary",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-approved-external-provider-readiness-method-and-parser"
        ),
    },
    "bounded-cost-budget-prerequisites": {
        "supports": ["region-and-subscription-availability"],
        "regions": ["global", "northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "subscription-scoped-control-plane",
        "requiredInputs": [
            "approved-subscription-scope",
            "closed-fixed-resource-and-lifetime-manifest",
            "current-official-price-evidence",
            "current-bounded-cost-and-credit-evidence",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "regional-sku-capabilities-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-bounded-cost-read-method-and-parser"
        ),
    },
    "provisioning-dependency-blockers": {
        "supports": list(INFRASTRUCTURE_GATES),
        "regions": ["global", "northcentralus", "southcentralus"],
        "scope": "approved-subscription-metadata",
        "authority": "repository-approved-scope",
        "requiredInputs": [
            "all-ten-infrastructure-gate-evidence-records",
            "all-required-operation-observations",
            "closed-provisioning-dependency-order",
            "current-cost-security-cleanup-and-authority-approvals",
        ],
        "prerequisites": [
            "all-dependent-operation-contracts-proved",
            "all-evidence-fresh-integrity-valid-and-same-scope",
            "all-runtime-preconditions-explicitly-preserved",
        ],
        "blockingReason": ("all-ten-infrastructure-gates-remain-blocked"),
    },
    "private-acr-source-prerequisites": {
        "supports": ["private-acr-source-path"],
        "regions": ["southcentralus"],
        "scope": "approved-target-resource-group",
        "authority": "official-azure-management-metadata",
        "requiredInputs": [
            "approved-target-resource-group-scope",
            "closed-private-source-ingress-contract",
            "closed-build-identity-and-image-digest-contract",
            "official-minimum-private-registry-projection",
        ],
        "prerequisites": [
            "fresh-approved-account-context",
            "private-endpoint-network-support-proved",
            "managed-identity-support-proved",
            "repository-verified-read-only-operation-semantics",
        ],
        "blockingReason": (
            "no-repository-verified-private-acr-source-method-and-parser"
        ),
    },
}


def _copy_json(value: JsonValue) -> JsonValue:
    return copy.deepcopy(value)


def _as_dict(value: JsonValue, location: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ContractError(f"{location}: value must be an object")
    return value


def _as_list(value: JsonValue, location: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ContractError(f"{location}: value must be an array")
    return value


def _matrix_without_integrity() -> dict[str, JsonValue]:
    operations: list[JsonValue] = []
    for operation_id in OPERATION_IDS:
        policy = _OPERATION_POLICY[operation_id]
        operations.append(
            {
                "id": operation_id,
                "supports": _copy_json(policy["supports"]),
                "contractDisposition": "complete-explicit-block",
                "definitionStatus": "blocked",
                "proofStatus": "unproved",
                "executionAuthorized": False,
                "mutationAuthorized": False,
                "provisioningAuthorized": False,
                "intendedEffect": "future-read-only-control-plane-discovery",
                "controlPlaneOnly": True,
                "dataPlaneAllowed": False,
                "semanticReadOnlyVerified": False,
                "methodDefinition": None,
                "parserDefinition": None,
                "retainedProjection": [],
                "requiredInputs": _copy_json(policy["requiredInputs"]),
                "prerequisites": _copy_json(policy["prerequisites"]),
                "targetBoundary": {
                    "regions": _copy_json(policy["regions"]),
                    "scope": policy["scope"],
                },
                "authorityLevel": policy["authority"],
                "authorityState": "denied-pending-separate-authorization",
                "evidenceExpectation": (
                    "future-fresh-sanitized-minimum-projection-required"
                ),
                "privacyProfile": "no-raw-provider-or-private-data",
                "costEffect": "none-no-execution-authorized",
                "failureBehavior": "remain-blocked-do-not-execute",
                "blockingReason": policy["blockingReason"],
                "executionPolicyRef": "default-deny-no-execution-v1",
                "transitionPolicyRef": "blocked-only-no-gate-upgrade-v1",
            }
        )
    return {
        "schemaVersion": "2020-12",
        "contractVersion": CONTRACT_VERSION,
        "scopeContractVersion": SCOPE_CONTRACT_VERSION,
        "inventoryContractVersion": INVENTORY_VERSION,
        "canonicalizationVersion": CANONICALIZATION_VERSION,
        "integrityDomain": INTEGRITY_DOMAIN_TEXT,
        "matrixId": "m7.7-cp7-azure-topology-operation-contracts",
        "sourceCommit": SOURCE_COMMIT,
        "checkpointStatus": (
            "complete-local-operation-contracts-with-provisioning-blocked"
        ),
        "defaultDecision": "deny",
        "operationDefaultsApplyToEveryEntry": True,
        "scopeBinding": {
            "scopeFile": "scope-contract.json",
            "scopeSha256": SCOPE_SHA256,
            "priorInventoryFile": "operation-inventory.json",
            "priorInventorySha256": PRIOR_INVENTORY_SHA256,
            "priorInventoryOperationCount": 18,
            "definitionOperationCount": 15,
        },
        "sourceReview": {
            "sourceType": "committed-repository-only",
            "sourceCommit": SOURCE_COMMIT,
            "reviewedAt": "2026-07-31T05:12:43Z",
            "officialAzureSourceReviewed": False,
            "sufficientForExecutableDefinition": False,
        },
        "authorityPolicy": {
            "azureAccessAuthorized": False,
            "executionAuthorized": False,
            "mutationAuthorized": False,
            "provisioningAuthorized": False,
            "separateAuthorizationRequired": True,
            "definitionGrantsAuthority": False,
        },
        "executionPolicy": {
            "id": "default-deny-no-execution-v1",
            "maximumAttempts": 1,
            "maximumTimeoutSeconds": 30,
            "maximumOutputBytes": 0,
            "retryCount": 0,
            "externalCallsAuthorized": False,
            "allowedResultGrammar": [],
            "rawOutputDisposalRule": "no-output-execution-denied",
            "missingInputDecision": "deny",
            "missingPrerequisiteDecision": "deny",
            "missingAuthorityDecision": "deny",
            "missingEvidenceDecision": "deny",
            "staleEvidenceDecision": "deny",
            "scopeMismatchDecision": "deny",
            "unknownOperationDecision": "deny",
            "successDecision": "unavailable-no-execution",
            "negativeDecision": "unavailable-no-execution",
            "blockedDecision": "preserve-explicit-block",
            "malformedDecision": "reject-and-remain-blocked",
            "timeoutDecision": "deny-and-remain-blocked",
            "failureDecision": "deny-and-remain-blocked",
            "laterExecutionEligibility": (
                "requires-complete-new-definition-and-separate-authorization"
            ),
            "stopConditions": [
                "contract-or-schema-mismatch",
                "missing-or-invalid-required-input",
                "missing-or-invalid-prerequisite",
                "missing-or-invalid-authority",
                "missing-stale-or-invalid-evidence",
                "scope-or-freshness-mismatch",
                "unknown-field-operation-state-or-transition",
                "mutation-provisioning-or-data-plane-request",
                "raw-private-or-secret-value-detected",
            ],
        },
        "evidencePolicy": {
            "maximumFutureObservationAgeSeconds": MAXIMUM_EVIDENCE_AGE_SECONDS,
            "definitionIsExecutionEvidence": False,
            "definitionMayProveOperation": False,
            "definitionMayUpgradeGate": False,
            "fabricatedOrIncompleteEvidenceDecision": "reject",
            "freshSanitizedMinimumProjectionRequired": True,
            "deterministicIntegrityRequired": True,
            "checksumIsSignature": False,
        },
        "privacyPolicy": {
            "rawAzureOutputAllowed": False,
            "rawAzureIdentifiersAllowed": False,
            "credentialsOrTokensAllowed": False,
            "privateAddressesOrHostnamesAllowed": False,
            "personalPathsAllowed": False,
            "minimumProjectionOnly": True,
            "privacyTransforms": [],
        },
        "costPolicy": {
            "azureSpendAuthorizedUsdCents": 0,
            "billableResourceLifetimeSeconds": 0,
            "priceOrCostClaimAuthorized": False,
        },
        "gatePolicy": {
            "infrastructureGates": [
                {"id": gate_id, "state": "blocked"} for gate_id in INFRASTRUCTURE_GATES
            ],
            "runtimeGates": [
                {"id": gate_id, "state": "unproved"} for gate_id in RUNTIME_GATES
            ],
            "operationDefinitionMayUpgradeGate": False,
            "topologyContractMayResolveRuntimeGate": False,
        },
        "supersessionPolicy": {
            "historicalInventoryImmutable": True,
            "historicalScopeImmutable": True,
            "historicalEvidenceImmutable": True,
            "stableOperationIdentitiesPreserved": True,
            "definitionsCoverOnlyPriorBlockedSlots": True,
            "historicalEvidenceReclassificationAllowed": False,
        },
        "supersessionMap": [
            {
                "priorOperationId": operation_id,
                "operationContractId": operation_id,
                "priorDefinitionStatus": "blocked",
                "disposition": "preserved-blocked",
            }
            for operation_id in OPERATION_IDS
        ],
        "operations": operations,
        "deferredWork": [
            "separately-authorized-read-only-azure-observation",
            "isolated-infrastructure-provisioning",
            "runtime-gate-validation",
            "managed-workload-and-failure-execution",
            "milestone-7.7-final-consolidation",
            "milestone-7.8",
        ],
    }


def operation_contract_integrity_sha256(value: dict[str, JsonValue]) -> str:
    body = {
        key: _copy_json(item)
        for key, item in value.items()
        if key != "matrixIntegritySha256"
    }
    return integrity_sha256(body, INTEGRITY_DOMAIN)


def validate_operation_contract_matrix(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ContractError("$: operation contract matrix must be an object")
    matrix = copy.deepcopy(value)
    schema_value = load_json(MATRIX_SCHEMA_PATH)
    if not isinstance(schema_value, dict):
        raise ContractError("$schema: operation contract schema must be an object")
    validate_schema(matrix, schema_value)
    if len(canonical_bytes(matrix)) > MAX_CANONICAL_BYTES:
        raise ContractError("operation contract matrix exceeds its byte limit")
    _walk_sensitive(matrix)

    expected = _matrix_without_integrity()
    actual = {
        key: _copy_json(item)
        for key, item in matrix.items()
        if key != "matrixIntegritySha256"
    }
    if actual != expected:
        raise ContractError(
            "operation contract matrix differs from the approved closed contract"
        )
    if matrix["matrixIntegritySha256"] != operation_contract_integrity_sha256(matrix):
        raise ContractError("operation contract matrix integrity mismatch")

    prior_inventory = load_operation_inventory()
    if prior_inventory["inventoryIntegritySha256"] != PRIOR_INVENTORY_SHA256:
        raise ContractError("bound Checkpoint 6 operation inventory differs")
    prior_scope = load_scope_contract()
    if prior_scope["scopeIntegritySha256"] != SCOPE_SHA256:
        raise ContractError("bound Checkpoint 6 scope differs")
    return matrix


def build_operation_contract_matrix() -> dict[str, JsonValue]:
    matrix = _matrix_without_integrity()
    matrix["matrixIntegritySha256"] = operation_contract_integrity_sha256(matrix)
    return validate_operation_contract_matrix(matrix)


def load_operation_contract_matrix() -> dict[str, JsonValue]:
    return validate_operation_contract_matrix(load_json(MATRIX_PATH))


def operation_execution_decision(
    operation_id: str,
    *,
    inputs_complete: bool = False,
    prerequisites_complete: bool = False,
    scope_valid: bool = False,
    authority_present: bool = False,
    evidence_valid: bool = False,
    evidence_fresh: bool = False,
) -> dict[str, JsonValue]:
    """Return the only permitted local decision: deny without side effects."""

    matrix = load_operation_contract_matrix()
    operations = _as_list(matrix["operations"], "$.operations")
    operation_ids = {
        str(item["id"])
        for item in operations
        if isinstance(item, dict) and "id" in item
    }
    if operation_id not in operation_ids:
        raise ContractError("unknown operation is denied")
    conditions = {
        "inputsComplete": inputs_complete,
        "prerequisitesComplete": prerequisites_complete,
        "scopeValid": scope_valid,
        "authorityPresent": authority_present,
        "evidenceValid": evidence_valid,
        "evidenceFresh": evidence_fresh,
    }
    reason = (
        "required-condition-missing"
        if not all(conditions.values())
        else "operation-contract-remains-blocked"
    )
    return {
        "operationId": operation_id,
        "decision": "deny",
        "reason": reason,
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
    }


def operation_contract_verification_result() -> dict[str, JsonValue]:
    matrix = load_operation_contract_matrix()
    operations = _as_list(matrix["operations"], "$.operations")
    gate_policy = _as_dict(matrix["gatePolicy"], "$.gatePolicy")
    infrastructure_gates = _as_list(
        gate_policy["infrastructureGates"], "$.gatePolicy.infrastructureGates"
    )
    runtime_gates = _as_list(gate_policy["runtimeGates"], "$.gatePolicy.runtimeGates")
    result: dict[str, JsonValue] = {
        "status": "valid",
        "classification": matrix["checkpointStatus"],
        "contractVersion": CONTRACT_VERSION,
        "matrixIntegritySha256": matrix["matrixIntegritySha256"],
        "priorInventorySha256": PRIOR_INVENTORY_SHA256,
        "scopeSha256": SCOPE_SHA256,
        "operationCount": len(operations),
        "blockedOperationCount": sum(
            isinstance(item, dict) and item.get("definitionStatus") == "blocked"
            for item in operations
        ),
        "unprovedOperationCount": sum(
            isinstance(item, dict) and item.get("proofStatus") == "unproved"
            for item in operations
        ),
        "blockedInfrastructureGateCount": sum(
            isinstance(item, dict) and item.get("state") == "blocked"
            for item in infrastructure_gates
        ),
        "unprovedRuntimeGateCount": sum(
            isinstance(item, dict) and item.get("state") == "unproved"
            for item in runtime_gates
        ),
        "azureAccessAuthorized": False,
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
        "checksumIsSignature": False,
        "verifierVersion": "mobius.m7.7.operation-contract-verifier.v1",
    }
    if len(canonical_bytes(result)) > MAX_VERIFIER_BYTES:
        raise ContractError("operation contract verifier output exceeds its byte limit")
    return result
