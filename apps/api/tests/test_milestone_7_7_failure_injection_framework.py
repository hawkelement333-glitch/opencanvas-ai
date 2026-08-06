from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from evidence.milestone_7_7.framework import (
    EVIDENCE_CLASSES,
    EVIDENCE_STATES,
    validate_package,
)
from performance.milestone_7_7.framework import (
    ContractError,
    canonical_bytes,
    load_json,
    loads_json,
)
from resilience.milestone_7_7.framework import (
    ABORT_CONDITIONS,
    ASSERTION_CODES,
    CATALOG_DOMAIN,
    CATALOG_VERSION,
    CHECKPOINT1_BUNDLE_SHA256,
    CHECKPOINT2_MANIFEST_SHA256,
    CHECKPOINT2_PLAN_SHA256,
    CHECKPOINT2_RESULT_SHA256,
    CHECKPOINT3_PACKAGE_SHA256,
    MAX_CONCURRENT_FAULTS,
    MAX_PLAN_BYTES,
    MAX_SCENARIO_DURATION_SECONDS,
    MAX_SCENARIOS,
    MAX_TOTAL_DURATION_SECONDS,
    MAX_VERIFIER_OUTPUT_BYTES,
    PLAN_DOMAIN,
    REQUIRED_GATES,
    SCENARIO_DEFINITIONS,
    SCENARIO_TYPES,
    SOURCE_COMMIT,
    VERIFIER_VERSION,
    build_local_plan,
    plan_integrity_sha256,
    report_bytes,
    scenario_catalog,
    scenario_catalog_sha256,
    validate_plan,
    verify_plan,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = REPOSITORY_ROOT / "resilience" / "milestone_7_7" / "failure-plan.example.json"
FRAMEWORK_PATH = REPOSITORY_ROOT / "resilience" / "milestone_7_7" / "framework.py"
CHECKPOINT3_PACKAGE_PATH = (
    REPOSITORY_ROOT / "evidence" / "milestone_7_7" / "evidence-package.example.json"
)

EXPECTED_SCENARIOS = {
    "ambiguous-commit",
    "cleanup-interruption",
    "database-failover",
    "dependency-network-delay",
    "duplicate-worker",
    "external-provider-failure",
    "object-storage-failure",
    "partial-network-loss",
    "partial-provider-response",
    "poison-job",
    "postgres-connection-pressure",
    "queue-delay",
    "queue-outage",
    "reserved-control-capacity-exhaustion",
    "retry-storm",
    "scaling-event",
    "scanner-delay",
    "scanner-outage",
    "service-restart",
    "shared-limiter-failure",
    "stale-worker",
    "worker-loss",
}


def _plan() -> dict[str, Any]:
    value = load_json(PLAN_PATH)
    assert isinstance(value, dict)
    return value


def _rehash(plan: dict[str, Any]) -> dict[str, Any]:
    plan["planIntegritySha256"] = plan_integrity_sha256(plan)
    return plan


def _write_plan(path: Path, plan: dict[str, Any]) -> None:
    path.write_bytes(canonical_bytes(plan))


def test_example_matches_deterministic_builder_and_validates() -> None:
    example = _plan()
    built = build_local_plan()
    assert canonical_bytes(example) == canonical_bytes(built)
    assert validate_plan(example) == example


def test_verifier_is_bounded_deterministic_and_explicitly_inert() -> None:
    first = verify_plan(PLAN_PATH)
    second = verify_plan(PLAN_PATH)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert len(report_bytes(first)) <= MAX_VERIFIER_OUTPUT_BYTES
    assert first == {
        "status": "valid",
        "errorCode": None,
        "planId": "m7.7-cp4-local-failure-plan",
        "planIntegritySha256": _plan()["planIntegritySha256"],
        "scenarioCount": 22,
        "executionAuthorized": False,
        "networkAccess": False,
        "destructive": False,
        "classification": "local-plan-only",
        "executionReadiness": "blocked",
        "milestoneEvidenceState": "partial",
        "verifierVersion": VERIFIER_VERSION,
    }


def test_catalog_is_closed_complete_and_deterministic() -> None:
    catalog = scenario_catalog()
    assert catalog["catalogVersion"] == CATALOG_VERSION
    assert catalog["executionBoundary"] == "planning-only"
    assert len(SCENARIO_DEFINITIONS) == 22
    assert len(SCENARIO_TYPES) <= MAX_SCENARIOS
    assert set(SCENARIO_TYPES) == EXPECTED_SCENARIOS
    assert list(SCENARIO_TYPES) == sorted(SCENARIO_TYPES)
    assert scenario_catalog_sha256() == scenario_catalog_sha256()
    assert len(scenario_catalog_sha256()) == 64


def test_every_scenario_has_the_required_bounded_contract() -> None:
    required_fields = {
        "scenarioType",
        "targetClass",
        "objectiveCode",
        "injectionMethod",
        "prerequisiteGates",
        "maximumDurationSeconds",
        "scopeClass",
        "safetyBoundary",
        "expectedOutcomes",
        "assertions",
        "evidenceClasses",
        "rollbackActions",
        "cleanupActions",
        "abortConditions",
    }
    for definition in SCENARIO_DEFINITIONS:
        value = definition.as_json()
        assert set(value) == required_fields
        assert value["scopeClass"] == "exact-isolated-synthetic-target"
        assert value["safetyBoundary"] == "effect-locked-single-fault"
        assert 1 <= value["maximumDurationSeconds"] <= MAX_SCENARIO_DURATION_SECONDS
        assert set(value["assertions"]) <= ASSERTION_CODES
        assert set(value["evidenceClasses"]) <= set(EVIDENCE_CLASSES)
        assert set(value["abortConditions"]) == set(ABORT_CONDITIONS)
        assert value["prerequisiteGates"]
        assert value["expectedOutcomes"]
        assert value["rollbackActions"]
        assert value["cleanupActions"]


def test_plan_binds_all_prior_checkpoint_contracts() -> None:
    bindings = _plan()["bindings"]
    assert bindings == {
        "checkpoint1BundleSha256": CHECKPOINT1_BUNDLE_SHA256,
        "workloadManifestSha256": CHECKPOINT2_MANIFEST_SHA256,
        "requestPlanSha256": CHECKPOINT2_PLAN_SHA256,
        "measurementResultSha256": CHECKPOINT2_RESULT_SHA256,
        "evidencePackageSha256": CHECKPOINT3_PACKAGE_SHA256,
        "scenarioCatalogSha256": scenario_catalog_sha256(),
    }
    package = load_json(CHECKPOINT3_PACKAGE_PATH)
    validated = validate_package(package, artifact_root=REPOSITORY_ROOT)
    assert validated["packageIntegritySha256"] == CHECKPOINT3_PACKAGE_SHA256


def test_plan_has_exact_local_classification_and_source() -> None:
    plan = _plan()
    assert plan["source"] == {
        "repositoryId": "solarplexus-mobius",
        "commitSha": SOURCE_COMMIT,
        "dirty": False,
    }
    assert plan["classification"] == {
        "environment": "unprovisioned-local",
        "execution": "planning-only",
        "claimStrength": "local-contract-validation-only",
    }
    assert set(plan["authorization"].values()) == {False}


def test_plan_preserves_every_unresolved_gate() -> None:
    states = {item["id"]: item["status"] for item in _plan()["gateStates"]}
    assert set(states) == set(REQUIRED_GATES)
    assert set(states.values()) == {"unresolved"}


def test_plan_preserves_partial_and_negative_evidence_states() -> None:
    states = {item["evidenceClass"]: item["state"] for item in _plan()["evidenceStates"]}
    assert set(states) == set(EVIDENCE_CLASSES)
    assert set(states.values()) <= set(EVIDENCE_STATES)
    assert states["local-deterministic-validation"] == "complete"
    assert states["resilience-evidence"] == "pending"
    assert states["cleanup-evidence"] == "pending"
    assert states["azure-execution-evidence"] == "absent"
    assert states["external-provider-evidence"] == "absent"
    assert states["capacity-evidence"] == "unproved"


def test_plan_limits_do_not_exceed_prior_checkpoint_boundaries() -> None:
    limits = _plan()["limits"]
    assert limits["maximumScenarioDurationSeconds"] == MAX_SCENARIO_DURATION_SECONDS
    assert limits["maximumTotalDurationSeconds"] == MAX_TOTAL_DURATION_SECONDS
    assert limits["maximumConcurrentFaults"] == MAX_CONCURRENT_FAULTS
    assert limits["maximumRequests"] == 10_000
    assert limits["maximumConcurrency"] == 128
    assert limits["maximumArrivalRatePerSecond"] == 100
    assert limits["maximumRetriesPerRequest"] == 2
    assert limits["maximumSyntheticUploadBytes"] == 134_217_728
    assert limits["provisioningBlockAboveUsdCents"] == 12_000
    assert limits["absoluteCostCeilingUsdCents"] == 25_000
    assert limits["provisioningBlockAboveUsdCents"] < limits["absoluteCostCeilingUsdCents"]


@pytest.mark.parametrize("field", sorted(_plan()))
def test_missing_top_level_field_is_rejected(field: str) -> None:
    plan = _plan()
    del plan[field]
    with pytest.raises(ContractError):
        validate_plan(plan)


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("source", "branch"),
        ("bindings", "providerReceipt"),
        ("classification", "azure"),
        ("authorization", "force"),
        ("limits", "override"),
        ("safety", "bypass"),
        ("completion", "published"),
    ],
)
def test_unknown_nested_field_is_rejected(location: str, field: str) -> None:
    plan = _plan()
    plan[location][field] = "unexpected"
    with pytest.raises(ContractError):
        validate_plan(plan)


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("classification", "environment", "azure-test"),
        ("classification", "execution", "live"),
        ("classification", "claimStrength", "resilience-validated"),
        ("authorization", "executionAuthorized", True),
        ("authorization", "provisioningAuthorized", True),
        ("authorization", "networkAccessAuthorized", True),
        ("authorization", "destructiveActionsAuthorized", True),
        ("source", "dirty", True),
    ],
)
def test_stronger_classification_or_authority_is_rejected(
    location: str,
    field: str,
    value: Any,
) -> None:
    plan = _rehash(deepcopy(_plan()))
    plan[location][field] = value
    plan = _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


@pytest.mark.parametrize(
    "binding",
    [
        "checkpoint1BundleSha256",
        "workloadManifestSha256",
        "requestPlanSha256",
        "measurementResultSha256",
        "evidencePackageSha256",
        "scenarioCatalogSha256",
    ],
)
def test_altered_prior_checkpoint_binding_is_rejected(binding: str) -> None:
    plan = deepcopy(_plan())
    plan["bindings"][binding] = "0" * 64
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_missing_scenario_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["selectedScenarioTypes"].pop()
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_duplicate_scenario_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["selectedScenarioTypes"][-1] = plan["selectedScenarioTypes"][0]
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_unknown_scenario_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["selectedScenarioTypes"][-1] = "unbounded-chaos"
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_missing_gate_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["gateStates"].pop()
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_resolved_gate_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["gateStates"][0]["status"] = "resolved"
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_duplicate_gate_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["gateStates"][-1] = deepcopy(plan["gateStates"][0])
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_missing_evidence_state_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["evidenceStates"].pop()
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_stronger_resilience_claim_is_rejected() -> None:
    plan = deepcopy(_plan())
    for item in plan["evidenceStates"]:
        if item["evidenceClass"] == "resilience-evidence":
            item["state"] = "complete"
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_provider_observation_claim_is_rejected() -> None:
    plan = deepcopy(_plan())
    for item in plan["evidenceStates"]:
        if item["evidenceClass"] == "external-provider-evidence":
            item["state"] = "complete"
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_missing_or_replaced_limitation_is_rejected() -> None:
    missing = deepcopy(_plan())
    missing["limitations"].pop()
    _rehash(missing)
    with pytest.raises(ContractError):
        validate_plan(missing)

    replaced = deepcopy(_plan())
    replaced["limitations"][-1] = "resilience-proved"
    _rehash(replaced)
    with pytest.raises(ContractError):
        validate_plan(replaced)


@pytest.mark.parametrize(
    "field",
    [
        "maximumScenarioDurationSeconds",
        "maximumTotalDurationSeconds",
        "maximumConcurrentFaults",
        "maximumAttemptsPerScenario",
        "maximumRequests",
        "maximumConcurrency",
        "maximumArrivalRatePerSecond",
        "maximumRetriesPerRequest",
        "maximumSyntheticUploadBytes",
        "maximumScannerObjects",
        "maximumScannerBytes",
        "maximumEvidenceBytes",
        "provisioningBlockAboveUsdCents",
        "absoluteCostCeilingUsdCents",
        "minimumCleanupReserveSeconds",
        "maximumEnvironmentLifetimeSeconds",
    ],
)
def test_limit_change_is_rejected(field: str) -> None:
    plan = deepcopy(_plan())
    plan["limits"][field] += 1
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


@pytest.mark.parametrize("field", sorted(_plan()["safety"]))
def test_safety_weakening_is_rejected(field: str) -> None:
    plan = deepcopy(_plan())
    plan["safety"][field] = not plan["safety"][field]
    _rehash(plan)
    with pytest.raises(ContractError):
        validate_plan(plan)


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        (None, "targetResourceId", "/subscriptions/00000000-0000-0000-0000-000000000000"),
        (None, "endpoint", "https://provider.invalid"),
        (None, "password", "do-not-store"),
        (None, "authorization", "Bearer opaque"),
        (None, "localPath", "C:\\Users\\private\\fixture"),
        ("source", "privateIdentifier", "private-user"),
    ],
)
def test_sensitive_or_operational_fields_are_rejected(
    location: str | None,
    field: str,
    value: str,
) -> None:
    plan = deepcopy(_plan())
    target = plan if location is None else plan[location]
    target[field] = value
    with pytest.raises(ContractError):
        _rehash(plan)
        validate_plan(plan)


@pytest.mark.parametrize(
    "source",
    [
        '{"a":1,"a":1}',
        '{"value":NaN}',
        '{"value":1.5}',
        '{"path":"C:\\\\Users\\\\private\\\\fixture"}',
        '{"note":"Authorization: Bearer opaque"}',
    ],
)
def test_strict_json_rejects_ambiguous_or_sensitive_input(source: str) -> None:
    with pytest.raises(ContractError):
        loads_json(source)


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("source", "commitSha", "0" * 40),
        ("classification", "environment", "other-local"),
        ("completion", "executionReadiness", "ready"),
        ("completion", "milestoneEvidenceState", "complete"),
        ("completion", "stopReason", "completed"),
        ("authorization", "executionAuthorized", True),
    ],
)
def test_material_change_alters_semantic_hash(
    location: str,
    field: str,
    value: Any,
) -> None:
    original = _plan()
    changed = deepcopy(original)
    changed[location][field] = value
    assert plan_integrity_sha256(changed) != plan_integrity_sha256(original)


def test_order_independent_registries_have_stable_semantic_hash() -> None:
    original = _plan()
    reordered = deepcopy(original)
    reordered["selectedScenarioTypes"].reverse()
    reordered["gateStates"].reverse()
    reordered["evidenceStates"].reverse()
    reordered["limitations"].reverse()
    assert plan_integrity_sha256(reordered) == plan_integrity_sha256(original)
    reordered["planIntegritySha256"] = original["planIntegritySha256"]
    assert validate_plan(reordered) == reordered


def test_tampered_integrity_is_rejected() -> None:
    plan = deepcopy(_plan())
    plan["planIntegritySha256"] = "0" * 64
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_plan_size_ceiling_fails_before_unknown_content_is_accepted() -> None:
    plan = deepcopy(_plan())
    plan["oversized"] = "x" * MAX_PLAN_BYTES
    with pytest.raises(ContractError):
        validate_plan(plan)


def test_invalid_verifier_report_is_closed_and_does_not_leak_path(
    tmp_path: Path,
) -> None:
    plan = deepcopy(_plan())
    plan["planIntegritySha256"] = "0" * 64
    path = tmp_path / "tampered.json"
    _write_plan(path, plan)
    report = verify_plan(path)
    assert report["status"] == "invalid"
    assert report["errorCode"] == "invalid-failure-plan"
    assert str(path) not in report_bytes(report).decode("utf-8")


def test_missing_plan_has_the_same_closed_failure_shape(tmp_path: Path) -> None:
    report = verify_plan(tmp_path / "missing.json")
    assert report["status"] == "invalid"
    assert report["planId"] is None
    assert report["scenarioCount"] == 0
    assert report["networkAccess"] is False
    assert report["destructive"] is False


def test_framework_has_no_network_process_or_execution_client() -> None:
    source = FRAMEWORK_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    prohibited_imports = {
        "azure",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & prohibited_imports
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert not {"execute_fault", "inject_fault", "run_failure"} & function_names


def test_build_and_verify_create_no_repository_files() -> None:
    before = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_file()
        and (
            "resilience/milestone_7_7" in path.as_posix()
            or "performance/milestone_7_7" in path.as_posix()
            or "evidence/milestone_7_7" in path.as_posix()
        )
    }
    build_local_plan()
    verify_plan(PLAN_PATH)
    after = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_file()
        and (
            "resilience/milestone_7_7" in path.as_posix()
            or "performance/milestone_7_7" in path.as_posix()
            or "evidence/milestone_7_7" in path.as_posix()
        )
    }
    assert after == before


def test_no_migration_or_dependency_file_is_part_of_checkpoint_4() -> None:
    assert not (REPOSITORY_ROOT / "apps/api/alembic/versions/20260726_0029.py").exists()
    assert PLAN_DOMAIN != CATALOG_DOMAIN
    assert len(canonical_bytes(_plan())) <= MAX_PLAN_BYTES
