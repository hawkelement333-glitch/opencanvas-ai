"""Bounded local failure-injection planning contracts for Milestone 7.7.

This module validates plans; it cannot execute a fault, contact a service,
spawn a process, or mutate infrastructure. Live execution remains a later
separately authorized checkpoint after every referenced gate is proved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from evidence.milestone_7_7.framework import (
    EVIDENCE_CLASSES,
    EVIDENCE_STATES,
    UNRESOLVED_GATES,
    validate_package,
)
from performance.milestone_7_7.framework import (
    ContractError as ContractError,
    JsonValue,
    canonical_bytes,
    integrity_sha256,
    load_json,
    manifest_sha256,
    simulate_local,
    validate_result,
    validate_schema,
)

ROOT: Final = Path(__file__).resolve().parent
REPOSITORY_ROOT: Final = ROOT.parents[1]
SCHEMA_PATH: Final = ROOT / "failure-plan.schema.json"

PLAN_VERSION: Final = "mobius.m7.7.failure-plan.v1"
CATALOG_VERSION: Final = "mobius.m7.7.failure-catalog.v1"
VERIFIER_VERSION: Final = "mobius.m7.7.failure-plan-verifier.v1"
SCHEMA_VERSION: Final = "2020-12"
PLAN_DOMAIN: Final = b"mobius.m7.7.failure-plan.v1\0"
CATALOG_DOMAIN: Final = b"mobius.m7.7.failure-catalog.v1\0"

SOURCE_COMMIT: Final = "996e969a1e80f70e8ded5668ca80207ecfe414f8"
CHECKPOINT1_BUNDLE_SHA256: Final = (
    "b4f5ebbe9158d0264460158a31454e1ebf63ac038e51296c33cdfcb77b088297"
)
CHECKPOINT2_MANIFEST_SHA256: Final = (
    "7d8832aae03e00ec93a6203a2360555ba19b030912a406b775fc7b20630c1c26"
)
CHECKPOINT2_PLAN_SHA256: Final = (
    "4c13cc8b536cef325a27a0a00b4d008d164ff5d955512e599df309f69c7f32b3"
)
CHECKPOINT2_RESULT_SHA256: Final = (
    "a98e8122f5c16a448de69f17cc6b537ea03989843805bbb584dfc620ae5d5c79"
)
CHECKPOINT3_PACKAGE_SHA256: Final = (
    "e88ab17245804f26d535ee225de1042ebf20d1fb6acf66e4cc755262c8e94ad1"
)

MAX_PLAN_BYTES: Final = 262_144
MAX_VERIFIER_OUTPUT_BYTES: Final = 16_384
MAX_SCENARIOS: Final = 32
MAX_SCENARIO_DURATION_SECONDS: Final = 900
MAX_TOTAL_DURATION_SECONDS: Final = 7_200
MAX_CONCURRENT_FAULTS: Final = 1

IDENTIFIER_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")

PROHIBITED_FIELD_NAMES: Final = frozenset(
    {
        "accessToken",
        "azureResourceId",
        "clientSecret",
        "connectionString",
        "cookie",
        "credential",
        "credentials",
        "endpoint",
        "externalTarget",
        "localPath",
        "password",
        "privateIdentifier",
        "privateKey",
        "productionData",
        "requestBody",
        "responseBody",
        "signedUrl",
        "subscriptionId",
        "targetResourceId",
        "tenantId",
    }
)

LOCAL_RUNTIME_GATES: Final = (
    "cleanup-supervisor-runtime-proof",
    "effect-lock-runtime-proof",
    "fault-controller-shape",
    "isolated-environment",
    "live-failure-authorization",
)
REQUIRED_GATES: Final = tuple(sorted((*UNRESOLVED_GATES, *LOCAL_RUNTIME_GATES)))

REQUIRED_LIMITATIONS: Final = frozenset(
    {
        "fault-controller-shape-unresolved",
        "local-plan-only",
        "no-azure-execution",
        "no-cleanup-proof",
        "no-external-retention",
        "no-live-failure-injection",
        "no-production-capacity-claim",
        "no-provider-observation",
        "no-real-rollback-proof",
        "unsigned",
        "unresolved-infrastructure-gates",
    }
)

ASSERTION_CODES: Final = frozenset(
    {
        "ambiguous-outcome-reconciled",
        "authority-revalidated",
        "bounded-retry",
        "cleanup-zero-residue",
        "control-capacity-preserved",
        "dead-letter-isolated",
        "effect-lock-held",
        "evidence-continuity",
        "no-duplicate-effect",
        "no-process-local-fallback",
        "recovery-bounded",
        "safe-429",
        "safe-503",
        "scope-preserved",
        "stale-result-suppressed",
    }
)
ABORT_CONDITIONS: Final = (
    "cleanup-timer-unproved",
    "cost-boundary-at-risk",
    "effect-lock-failure",
    "evidence-integrity-failure",
    "scope-mismatch",
    "synthetic-isolation-failure",
    "unauthorized-side-effect",
    "unexpected-public-access",
)


@dataclass(frozen=True)
class ScenarioDefinition:
    """One closed, non-executable future failure-exercise definition."""

    scenario_type: str
    target_class: str
    objective_code: str
    injection_method: str
    prerequisite_gates: tuple[str, ...]
    maximum_duration_seconds: int
    expected_outcomes: tuple[str, ...]
    assertions: tuple[str, ...]
    evidence_classes: tuple[str, ...]
    rollback_actions: tuple[str, ...]
    cleanup_actions: tuple[str, ...]

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "scenarioType": self.scenario_type,
            "targetClass": self.target_class,
            "objectiveCode": self.objective_code,
            "injectionMethod": self.injection_method,
            "prerequisiteGates": list(self.prerequisite_gates),
            "maximumDurationSeconds": self.maximum_duration_seconds,
            "scopeClass": "exact-isolated-synthetic-target",
            "safetyBoundary": "effect-locked-single-fault",
            "expectedOutcomes": list(self.expected_outcomes),
            "assertions": list(self.assertions),
            "evidenceClasses": list(self.evidence_classes),
            "rollbackActions": list(self.rollback_actions),
            "cleanupActions": list(self.cleanup_actions),
            "abortConditions": list(ABORT_CONDITIONS),
        }


def _scenario(
    scenario_type: str,
    target_class: str,
    objective_code: str,
    injection_method: str,
    *,
    gates: tuple[str, ...] = (),
    duration: int = 300,
    outcomes: tuple[str, ...] = ("dependency-unavailable", "success"),
    assertions: tuple[str, ...] = (
        "scope-preserved",
        "recovery-bounded",
        "evidence-continuity",
    ),
    evidence: tuple[str, ...] = (
        "resilience-evidence",
        "security-evidence",
        "cleanup-evidence",
    ),
    rollback: tuple[str, ...] = ("remove-fault-control", "restore-target-state"),
    cleanup: tuple[str, ...] = (
        "remove-synthetic-test-state",
        "verify-zero-residue",
    ),
) -> ScenarioDefinition:
    required = (
        "isolated-environment",
        "live-failure-authorization",
        "effect-lock-runtime-proof",
        "cleanup-supervisor-runtime-proof",
        *gates,
    )
    return ScenarioDefinition(
        scenario_type=scenario_type,
        target_class=target_class,
        objective_code=objective_code,
        injection_method=injection_method,
        prerequisite_gates=tuple(sorted(set(required))),
        maximum_duration_seconds=duration,
        expected_outcomes=outcomes,
        assertions=assertions,
        evidence_classes=evidence,
        rollback_actions=rollback,
        cleanup_actions=cleanup,
    )


SCENARIO_DEFINITIONS: Final = tuple(
    sorted(
        (
            _scenario(
                "ambiguous-commit",
                "database",
                "prove-idempotent-ambiguous-outcome-reconciliation",
                "bounded-response-loss-after-commit",
                assertions=(
                    "ambiguous-outcome-reconciled",
                    "no-duplicate-effect",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "cleanup-interruption",
                "cleanup",
                "prove-restartable-zero-residue-cleanup",
                "bounded-cleanup-controller-stop",
                duration=600,
                assertions=(
                    "cleanup-zero-residue",
                    "effect-lock-held",
                    "evidence-continuity",
                ),
                rollback=("resume-cleanup-controller",),
                cleanup=("complete-cleanup-runbook", "verify-zero-residue"),
            ),
            _scenario(
                "database-failover",
                "database",
                "prove-bounded-database-failover-recovery",
                "provider-managed-failover",
                gates=("exact-provider-api-versions",),
                duration=900,
                assertions=(
                    "bounded-retry",
                    "no-duplicate-effect",
                    "recovery-bounded",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "dependency-network-delay",
                "network",
                "prove-timeout-backpressure-and-recovery",
                "scoped-network-delay",
                assertions=(
                    "bounded-retry",
                    "safe-503",
                    "recovery-bounded",
                    "scope-preserved",
                ),
            ),
            _scenario(
                "duplicate-worker",
                "worker",
                "prove-single-commit-under-duplicate-workers",
                "bounded-duplicate-worker",
                assertions=(
                    "no-duplicate-effect",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "external-provider-failure",
                "provider",
                "prove-provider-failure-is-bounded-and-fail-closed",
                "scoped-dependency-denial",
                gates=("openai-smtp-test-providers",),
                assertions=(
                    "bounded-retry",
                    "safe-503",
                    "no-duplicate-effect",
                    "evidence-continuity",
                ),
                evidence=(
                    "external-provider-evidence",
                    "resilience-evidence",
                    "security-evidence",
                    "cleanup-evidence",
                ),
            ),
            _scenario(
                "object-storage-failure",
                "object-storage",
                "prove-object-failure-cannot-bypass-quarantine",
                "scoped-dependency-denial",
                gates=("scanner-result-bridge",),
                assertions=(
                    "safe-503",
                    "scope-preserved",
                    "effect-lock-held",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "partial-network-loss",
                "network",
                "prove-bounded-recovery-from-partial-network-loss",
                "scoped-packet-loss",
                assertions=(
                    "bounded-retry",
                    "safe-503",
                    "recovery-bounded",
                    "scope-preserved",
                ),
            ),
            _scenario(
                "partial-provider-response",
                "provider",
                "prove-partial-provider-output-is-never-accepted-as-complete",
                "bounded-partial-response",
                gates=("openai-smtp-test-providers",),
                assertions=(
                    "safe-503",
                    "no-duplicate-effect",
                    "evidence-continuity",
                ),
                evidence=(
                    "external-provider-evidence",
                    "resilience-evidence",
                    "security-evidence",
                ),
            ),
            _scenario(
                "poison-job",
                "queue",
                "prove-poison-work-isolated-after-bounded-attempts",
                "synthetic-poison-delivery",
                assertions=(
                    "bounded-retry",
                    "dead-letter-isolated",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "postgres-connection-pressure",
                "database",
                "prove-database-pool-backpressure-and-control-capacity",
                "bounded-connection-pressure",
                assertions=(
                    "safe-503",
                    "control-capacity-preserved",
                    "recovery-bounded",
                    "scope-preserved",
                ),
            ),
            _scenario(
                "queue-delay",
                "queue",
                "prove-bounded-queue-age-and-recovery",
                "bounded-delivery-delay",
                assertions=(
                    "bounded-retry",
                    "recovery-bounded",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "queue-outage",
                "queue",
                "prove-queue-outage-fails-closed",
                "scoped-dependency-denial",
                assertions=(
                    "safe-503",
                    "no-duplicate-effect",
                    "recovery-bounded",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "reserved-control-capacity-exhaustion",
                "control-capacity",
                "prove-control-capacity-remains-reserved",
                "bounded-control-capacity-pressure",
                duration=600,
                assertions=(
                    "safe-429",
                    "control-capacity-preserved",
                    "scope-preserved",
                ),
            ),
            _scenario(
                "retry-storm",
                "queue",
                "prove-retry-amplification-remains-bounded",
                "synthetic-retry-amplification",
                duration=600,
                assertions=(
                    "bounded-retry",
                    "safe-429",
                    "control-capacity-preserved",
                    "no-duplicate-effect",
                ),
            ),
            _scenario(
                "scaling-event",
                "scaling",
                "prove-scaling-preserves-leases-and-scope",
                "bounded-replica-transition",
                gates=("fault-controller-shape",),
                duration=600,
                assertions=(
                    "stale-result-suppressed",
                    "no-duplicate-effect",
                    "scope-preserved",
                    "recovery-bounded",
                ),
            ),
            _scenario(
                "scanner-delay",
                "scanner",
                "prove-delayed-scan-keeps-content-quarantined",
                "bounded-provider-delay",
                gates=("scanner-result-bridge",),
                assertions=(
                    "safe-503",
                    "effect-lock-held",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "scanner-outage",
                "scanner",
                "prove-scanner-outage-keeps-content-quarantined",
                "scoped-dependency-denial",
                gates=("scanner-result-bridge",),
                assertions=(
                    "safe-503",
                    "effect-lock-held",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "service-restart",
                "service",
                "prove-service-restart-preserves-bounded-work",
                "bounded-service-restart",
                assertions=(
                    "bounded-retry",
                    "no-duplicate-effect",
                    "recovery-bounded",
                    "scope-preserved",
                ),
            ),
            _scenario(
                "shared-limiter-failure",
                "shared-limiter",
                "prove-shared-limiter-failure-has-no-local-fallback",
                "scoped-dependency-denial",
                gates=("redis-custom-acl-support",),
                assertions=(
                    "safe-503",
                    "no-process-local-fallback",
                    "scope-preserved",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "stale-worker",
                "worker",
                "prove-expired-lease-cannot-commit",
                "bounded-lease-expiry",
                assertions=(
                    "stale-result-suppressed",
                    "no-duplicate-effect",
                    "authority-revalidated",
                    "evidence-continuity",
                ),
            ),
            _scenario(
                "worker-loss",
                "worker",
                "prove-lost-work-is-recovered-once",
                "bounded-worker-termination",
                assertions=(
                    "bounded-retry",
                    "no-duplicate-effect",
                    "recovery-bounded",
                    "evidence-continuity",
                ),
            ),
        ),
        key=lambda item: item.scenario_type,
    )
)

SCENARIO_TYPES: Final = tuple(item.scenario_type for item in SCENARIO_DEFINITIONS)
EXPECTED_EVIDENCE_STATES: Final = {
    "alert-delivery-evidence": "unproved",
    "azure-execution-evidence": "absent",
    "capacity-evidence": "unproved",
    "cleanup-evidence": "pending",
    "external-provider-evidence": "absent",
    "infrastructure-definition-evidence": "partial",
    "local-deterministic-validation": "complete",
    "observability-evidence": "unproved",
    "resilience-evidence": "pending",
    "security-evidence": "pending",
    "synthetic-workload-evidence": "partial",
}


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


def _walk_prohibited_fields(value: JsonValue, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PROHIBITED_FIELD_NAMES:
                raise ContractError(f"{location}: prohibited field {key}")
            _walk_prohibited_fields(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_prohibited_fields(item, f"{location}[{index}]")


def scenario_catalog() -> dict[str, JsonValue]:
    """Return the deterministic closed scenario catalog."""

    return {
        "catalogVersion": CATALOG_VERSION,
        "executionBoundary": "planning-only",
        "scenarios": [item.as_json() for item in SCENARIO_DEFINITIONS],
    }


def scenario_catalog_sha256() -> str:
    return integrity_sha256(scenario_catalog(), CATALOG_DOMAIN)


def _normalized_plan(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    normalized = cast(dict[str, JsonValue], _deepcopy_json(value))
    normalized.pop("planIntegritySha256", None)
    normalized["selectedScenarioTypes"] = cast(
        JsonValue,
        sorted(
            _as_str(item, "selected scenario")
            for item in _as_list(
                normalized["selectedScenarioTypes"],
                "selectedScenarioTypes",
            )
        ),
    )
    gate_states = [
        _as_dict(item, "gate state")
        for item in _as_list(normalized["gateStates"], "gateStates")
    ]
    normalized["gateStates"] = cast(
        JsonValue,
        sorted(gate_states, key=lambda item: _as_str(item["id"], "gate id")),
    )
    evidence_states = [
        _as_dict(item, "evidence state")
        for item in _as_list(normalized["evidenceStates"], "evidenceStates")
    ]
    normalized["evidenceStates"] = cast(
        JsonValue,
        sorted(
            evidence_states,
            key=lambda item: _as_str(item["evidenceClass"], "evidence class"),
        ),
    )
    normalized["limitations"] = cast(
        JsonValue,
        sorted(
            _as_str(item, "limitation")
            for item in _as_list(normalized["limitations"], "limitations")
        ),
    )
    return normalized


def _deepcopy_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _deepcopy_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deepcopy_json(item) for item in value]
    return value


def plan_integrity_sha256(value: dict[str, JsonValue]) -> str:
    """Hash normalized semantic plan content using the Checkpoint 4 domain."""

    return integrity_sha256(_normalized_plan(value), PLAN_DOMAIN)


def _current_bindings() -> dict[str, str]:
    manifest_path = REPOSITORY_ROOT / "performance/milestone_7_7/workload.example.json"
    request_plan_path = (
        REPOSITORY_ROOT / "evidence/milestone_7_7/fixtures/request-plan.fixture.json"
    )
    result_path = (
        REPOSITORY_ROOT
        / "evidence/milestone_7_7/fixtures/measurement-result.fixture.json"
    )
    evidence_path = (
        REPOSITORY_ROOT / "evidence/milestone_7_7/evidence-package.example.json"
    )
    manifest = load_json(manifest_path)
    expected_plan, expected_result = simulate_local(manifest)
    committed_plan = load_json(request_plan_path)
    committed_result = load_json(result_path)
    if canonical_bytes(expected_plan) != canonical_bytes(committed_plan):
        raise ContractError(
            "Checkpoint 2 request-plan fixture differs from reproduction"
        )
    if canonical_bytes(expected_result) != canonical_bytes(committed_result):
        raise ContractError("Checkpoint 2 result fixture differs from reproduction")
    validated_result = validate_result(committed_result)
    evidence_package = validate_package(
        load_json(evidence_path),
        artifact_root=REPOSITORY_ROOT,
    )
    result_hash = _as_str(validated_result["integritySha256"], "result hash")
    package_hash = _as_str(
        evidence_package["packageIntegritySha256"],
        "evidence package hash",
    )
    return {
        "checkpoint1BundleSha256": CHECKPOINT1_BUNDLE_SHA256,
        "workloadManifestSha256": manifest_sha256(manifest),
        "requestPlanSha256": _as_str(expected_plan["planSha256"], "plan hash"),
        "measurementResultSha256": result_hash,
        "evidencePackageSha256": package_hash,
        "scenarioCatalogSha256": scenario_catalog_sha256(),
    }


def build_local_plan(
    plan_id: str = "m7.7-cp4-local-failure-plan",
) -> dict[str, JsonValue]:
    """Build the inert deterministic plan used by the Checkpoint 4 fixture."""

    if IDENTIFIER_RE.fullmatch(plan_id) is None:
        raise ContractError("plan identifier is malformed")
    plan: dict[str, JsonValue] = {
        "schemaVersion": SCHEMA_VERSION,
        "contractVersion": PLAN_VERSION,
        "planId": plan_id,
        "purpose": "local-failure-injection-framework",
        "source": {
            "repositoryId": "solarplexus-mobius",
            "commitSha": SOURCE_COMMIT,
            "dirty": False,
        },
        "bindings": cast(JsonValue, _current_bindings()),
        "classification": {
            "environment": "unprovisioned-local",
            "execution": "planning-only",
            "claimStrength": "local-contract-validation-only",
        },
        "authorization": {
            "executionAuthorized": False,
            "provisioningAuthorized": False,
            "networkAccessAuthorized": False,
            "destructiveActionsAuthorized": False,
        },
        "limits": {
            "maximumScenarioDurationSeconds": MAX_SCENARIO_DURATION_SECONDS,
            "maximumTotalDurationSeconds": MAX_TOTAL_DURATION_SECONDS,
            "maximumConcurrentFaults": MAX_CONCURRENT_FAULTS,
            "maximumAttemptsPerScenario": 1,
            "maximumRequests": 10_000,
            "maximumConcurrency": 128,
            "maximumArrivalRatePerSecond": 100,
            "maximumRetriesPerRequest": 2,
            "maximumSyntheticUploadBytes": 134_217_728,
            "maximumScannerObjects": 25,
            "maximumScannerBytes": 26_214_400,
            "maximumEvidenceBytes": 104_857_600,
            "provisioningBlockAboveUsdCents": 12_000,
            "absoluteCostCeilingUsdCents": 17_500,
            "minimumCleanupReserveSeconds": 5_400,
            "maximumEnvironmentLifetimeSeconds": 86_400,
        },
        "safety": {
            "syntheticOnly": True,
            "exactScopeRequired": True,
            "effectLockRequired": True,
            "independentCleanupTimerRequired": True,
            "manualCleanupFallbackRequired": True,
            "rollbackRequired": True,
            "zeroResidueRequired": True,
            "postRevocationDenialRequired": True,
            "executionFailsClosed": True,
            "externalTargetsAllowed": False,
            "productionDataAllowed": False,
            "credentialsAllowed": False,
            "liveExecutionAllowed": False,
            "networkAccessAllowed": False,
            "destructiveActionsAllowed": False,
        },
        "selectedScenarioTypes": cast(JsonValue, list(SCENARIO_TYPES)),
        "gateStates": cast(
            JsonValue,
            [{"id": gate, "status": "unresolved"} for gate in REQUIRED_GATES],
        ),
        "evidenceStates": cast(
            JsonValue,
            [
                {"evidenceClass": evidence_class, "state": state}
                for evidence_class, state in sorted(EXPECTED_EVIDENCE_STATES.items())
            ],
        ),
        "completion": {
            "localPlanState": "complete",
            "milestoneEvidenceState": "partial",
            "executionReadiness": "blocked",
            "stopReason": "not-executed",
        },
        "limitations": cast(JsonValue, sorted(REQUIRED_LIMITATIONS)),
        "verifierVersion": VERIFIER_VERSION,
        "planIntegritySha256": "",
    }
    plan["planIntegritySha256"] = plan_integrity_sha256(plan)
    return validate_plan(plan)


def _validate_scenarios(plan: dict[str, JsonValue]) -> None:
    selected = [
        _as_str(item, "selected scenario")
        for item in _as_list(plan["selectedScenarioTypes"], "selectedScenarioTypes")
    ]
    if len(selected) > MAX_SCENARIOS:
        raise ContractError("selected scenario count exceeds the hard ceiling")
    if len(selected) != len(set(selected)):
        raise ContractError("selected scenarios must be unique")
    if set(selected) != set(SCENARIO_TYPES):
        raise ContractError(
            "selected scenarios differ from the required closed catalog"
        )
    catalog = scenario_catalog()
    definitions = _as_list(catalog["scenarios"], "scenario catalog")
    for definition_value in definitions:
        definition = _as_dict(definition_value, "scenario definition")
        duration = definition["maximumDurationSeconds"]
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 1
            or duration > MAX_SCENARIO_DURATION_SECONDS
        ):
            raise ContractError("scenario duration exceeds the hard ceiling")
        assertions = {
            _as_str(item, "scenario assertion")
            for item in _as_list(definition["assertions"], "scenario assertions")
        }
        if not assertions or not assertions.issubset(ASSERTION_CODES):
            raise ContractError("scenario assertion is outside the closed registry")
        evidence_classes = {
            _as_str(item, "scenario evidence class")
            for item in _as_list(
                definition["evidenceClasses"],
                "scenario evidence classes",
            )
        }
        if not evidence_classes or not evidence_classes.issubset(EVIDENCE_CLASSES):
            raise ContractError(
                "scenario evidence class is outside the closed registry"
            )
        for required_list in (
            "abortConditions",
            "cleanupActions",
            "expectedOutcomes",
            "prerequisiteGates",
            "rollbackActions",
        ):
            values = _as_list(definition[required_list], required_list)
            if not values:
                raise ContractError(f"scenario {required_list} must not be empty")


def _validate_gates(plan: dict[str, JsonValue]) -> None:
    gate_items = _as_list(plan["gateStates"], "gateStates")
    gates: dict[str, str] = {}
    for item_value in gate_items:
        item = _as_dict(item_value, "gate state")
        gate_id = _as_str(item["id"], "gate id")
        state = _as_str(item["status"], "gate status")
        if gate_id in gates:
            raise ContractError("gate identifiers must be unique")
        gates[gate_id] = state
    if set(gates) != set(REQUIRED_GATES):
        raise ContractError("gate inventory differs from the required closed set")
    if set(gates.values()) != {"unresolved"}:
        raise ContractError("local planning cannot resolve an execution gate")


def _validate_evidence_states(plan: dict[str, JsonValue]) -> None:
    states: dict[str, str] = {}
    for item_value in _as_list(plan["evidenceStates"], "evidenceStates"):
        item = _as_dict(item_value, "evidence state")
        evidence_class = _as_str(item["evidenceClass"], "evidence class")
        state = _as_str(item["state"], "evidence state")
        if evidence_class in states:
            raise ContractError("evidence classes must be unique")
        if evidence_class not in EVIDENCE_CLASSES or state not in EVIDENCE_STATES:
            raise ContractError("evidence state is outside the Checkpoint 3 registry")
        states[evidence_class] = state
    if states != EXPECTED_EVIDENCE_STATES:
        raise ContractError("local planning evidence states are misclassified")


def validate_plan(value: JsonValue) -> dict[str, JsonValue]:
    """Validate schema, bindings, bounds, claims, gates, and plan integrity."""

    if len(canonical_bytes(value)) > MAX_PLAN_BYTES:
        raise ContractError("failure plan exceeds the canonical size ceiling")
    plan = _as_dict(value, "$")
    schema = _as_dict(load_json(SCHEMA_PATH), "failure-plan schema")
    validate_schema(plan, schema)
    _walk_prohibited_fields(plan)
    if (
        COMMIT_RE.fullmatch(
            _as_str(_as_dict(plan["source"], "source")["commitSha"], "commit")
        )
        is None
    ):
        raise ContractError("source commit is malformed")
    bindings = _as_dict(plan["bindings"], "bindings")
    current_bindings = _current_bindings()
    if bindings != current_bindings:
        raise ContractError("Checkpoint 1-3 bindings differ from current contracts")
    for value_sha in bindings.values():
        if not isinstance(value_sha, str) or SHA256_RE.fullmatch(value_sha) is None:
            raise ContractError("binding contains a malformed SHA-256 value")
    _validate_scenarios(plan)
    _validate_gates(plan)
    _validate_evidence_states(plan)
    limitations = {
        _as_str(item, "limitation")
        for item in _as_list(plan["limitations"], "limitations")
    }
    if limitations != REQUIRED_LIMITATIONS:
        raise ContractError("limitations differ from the required closed set")
    expected_hash = plan_integrity_sha256(plan)
    if plan["planIntegritySha256"] != expected_hash:
        raise ContractError("failure plan integrity hash does not match")
    return cast(dict[str, JsonValue], _deepcopy_json(plan))


VerifierStatus = Literal["valid", "invalid"]


def _verification_report(
    *,
    status: VerifierStatus,
    plan: dict[str, JsonValue] | None,
    error_code: str | None,
) -> dict[str, JsonValue]:
    return {
        "status": status,
        "errorCode": error_code,
        "planId": None if plan is None else plan.get("planId"),
        "planIntegritySha256": (
            None if plan is None else plan.get("planIntegritySha256")
        ),
        "scenarioCount": 0 if plan is None else len(SCENARIO_TYPES),
        "executionAuthorized": False,
        "networkAccess": False,
        "destructive": False,
        "classification": "local-plan-only",
        "executionReadiness": "blocked",
        "milestoneEvidenceState": "partial",
        "verifierVersion": VERIFIER_VERSION,
    }


def report_bytes(report: dict[str, JsonValue]) -> bytes:
    encoded = canonical_bytes(report)
    if len(encoded) > MAX_VERIFIER_OUTPUT_BYTES:
        raise ContractError("verifier output exceeds the hard ceiling")
    return encoded


def verify_plan(path: Path) -> dict[str, JsonValue]:
    """Verify a local plan and return a bounded report without error details."""

    try:
        plan = validate_plan(load_json(path))
    except (ContractError, OSError):
        report = _verification_report(
            status="invalid",
            plan=None,
            error_code="invalid-failure-plan",
        )
    else:
        report = _verification_report(status="valid", plan=plan, error_code=None)
    report_bytes(report)
    return report
