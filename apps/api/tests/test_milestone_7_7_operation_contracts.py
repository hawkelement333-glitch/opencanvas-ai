from __future__ import annotations

import ast
import copy
import json
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from performance.milestone_7_7.framework import (
    ContractError,
    canonical_bytes,
    load_json,
    loads_json,
)
from preflight.milestone_7_7.framework import (
    INFRASTRUCTURE_GATES,
    RUNTIME_GATES,
)
from preflight.milestone_7_7.operation_contracts import (
    CONTRACT_VERSION,
    MATRIX_PATH,
    OPERATION_IDS,
    build_operation_contract_matrix,
    load_operation_contract_matrix,
    operation_contract_integrity_sha256,
    operation_contract_verification_result,
    operation_execution_decision,
    validate_operation_contract_matrix,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_MODULE = ROOT / "preflight" / "milestone_7_7" / "operation_contracts.py"
VERIFIER_MODULE = ROOT / "preflight" / "milestone_7_7" / "verify_operation_contracts.py"

MatrixMutation = Callable[[dict[str, object]], None]


def _matrix() -> dict[str, object]:
    value = copy.deepcopy(load_json(MATRIX_PATH))
    assert isinstance(value, dict)
    return value


def _rehash(value: dict[str, object]) -> None:
    value["matrixIntegritySha256"] = operation_contract_integrity_sha256(value)


def _remove_first_operation(value: dict[str, object]) -> None:
    operations = value["operations"]
    assert isinstance(operations, list)
    operations.pop(0)


def _duplicate_first_operation(value: dict[str, object]) -> None:
    operations = value["operations"]
    assert isinstance(operations, list)
    operations[-1] = copy.deepcopy(operations[0])


def _add_unknown_operation(value: dict[str, object]) -> None:
    operations = value["operations"]
    assert isinstance(operations, list)
    extra = copy.deepcopy(operations[0])
    assert isinstance(extra, dict)
    extra["id"] = "unknown-operation"
    operations.append(extra)


def _change_version(value: dict[str, object]) -> None:
    value["contractVersion"] = f"{CONTRACT_VERSION}.unknown"


def _add_unknown_field(value: dict[str, object]) -> None:
    value["unexpected"] = "not-allowed"


def _remove_required_inputs(value: dict[str, object]) -> None:
    operation = _first_operation(value)
    operation.pop("requiredInputs")


def _empty_prerequisites(value: dict[str, object]) -> None:
    _first_operation(value)["prerequisites"] = []


def _prove_operation(value: dict[str, object]) -> None:
    _first_operation(value)["proofStatus"] = "proved"


def _define_operation(value: dict[str, object]) -> None:
    _first_operation(value)["definitionStatus"] = "defined"


def _authorize_execution(value: dict[str, object]) -> None:
    _first_operation(value)["executionAuthorized"] = True


def _authorize_mutation(value: dict[str, object]) -> None:
    _first_operation(value)["mutationAuthorized"] = True


def _authorize_provisioning(value: dict[str, object]) -> None:
    authority = value["authorityPolicy"]
    assert isinstance(authority, dict)
    authority["provisioningAuthorized"] = True


def _fabricate_method(value: dict[str, object]) -> None:
    _first_operation(value)["methodDefinition"] = ["az", "resource", "list"]


def _fabricate_parser(value: dict[str, object]) -> None:
    _first_operation(value)["parserDefinition"] = "accept-any-json"


def _fabricate_evidence(value: dict[str, object]) -> None:
    _first_operation(value)["evidence"] = {"outcome": "proved"}


def _upgrade_infrastructure_gate(value: dict[str, object]) -> None:
    gate_policy = value["gatePolicy"]
    assert isinstance(gate_policy, dict)
    gates = gate_policy["infrastructureGates"]
    assert isinstance(gates, list)
    assert isinstance(gates[0], dict)
    gates[0]["state"] = "proved"


def _upgrade_runtime_gate(value: dict[str, object]) -> None:
    gate_policy = value["gatePolicy"]
    assert isinstance(gate_policy, dict)
    gates = gate_policy["runtimeGates"]
    assert isinstance(gates, list)
    assert isinstance(gates[0], dict)
    gates[0]["state"] = "proved"


def _enable_retry(value: dict[str, object]) -> None:
    policy = value["executionPolicy"]
    assert isinstance(policy, dict)
    policy["retryCount"] = 1


def _change_source_review(value: dict[str, object]) -> None:
    source_review = value["sourceReview"]
    assert isinstance(source_review, dict)
    source_review["officialAzureSourceReviewed"] = True


def _permit_output(value: dict[str, object]) -> None:
    policy = value["executionPolicy"]
    assert isinstance(policy, dict)
    policy["maximumOutputBytes"] = 1


def _add_result_grammar(value: dict[str, object]) -> None:
    policy = value["executionPolicy"]
    assert isinstance(policy, dict)
    policy["allowedResultGrammar"] = ["fabricated"]


def _change_outcome_policy(value: dict[str, object]) -> None:
    policy = value["executionPolicy"]
    assert isinstance(policy, dict)
    policy["successDecision"] = "accept"


def _add_privacy_transform(value: dict[str, object]) -> None:
    policy = value["privacyPolicy"]
    assert isinstance(policy, dict)
    policy["privacyTransforms"] = ["retain-raw"]


def _first_operation(value: dict[str, object]) -> dict[str, object]:
    operations = value["operations"]
    assert isinstance(operations, list)
    operation = operations[0]
    assert isinstance(operation, dict)
    return operation


def test_committed_matrix_matches_builder_and_validates() -> None:
    committed = load_operation_contract_matrix()
    built = build_operation_contract_matrix()

    assert canonical_bytes(committed) == canonical_bytes(built)
    assert committed["contractVersion"] == CONTRACT_VERSION
    assert committed["matrixIntegritySha256"] == (
        "100293931dcc71bb069e4f6fe06228360e0953b3b756544a555941d81bf8d6bc"
    )


def test_exact_stable_operation_registry_remains_blocked_and_unproved() -> None:
    matrix = load_operation_contract_matrix()
    operations = matrix["operations"]
    assert isinstance(operations, list)

    assert tuple(item["id"] for item in operations) == OPERATION_IDS
    assert len(set(OPERATION_IDS)) == 15
    assert all(item["definitionStatus"] == "blocked" for item in operations)
    assert all(item["proofStatus"] == "unproved" for item in operations)
    assert all(item["contractDisposition"] == "complete-explicit-block" for item in operations)
    assert all(item["methodDefinition"] is None for item in operations)
    assert all(item["parserDefinition"] is None for item in operations)
    assert all(item["retainedProjection"] == [] for item in operations)
    assert matrix["operationDefaultsApplyToEveryEntry"] is True
    source_review = matrix["sourceReview"]
    assert isinstance(source_review, dict)
    assert source_review["sourceType"] == "committed-repository-only"
    assert source_review["officialAzureSourceReviewed"] is False
    assert source_review["sufficientForExecutableDefinition"] is False
    execution_policy = matrix["executionPolicy"]
    assert isinstance(execution_policy, dict)
    assert execution_policy["maximumOutputBytes"] == 0
    assert execution_policy["allowedResultGrammar"] == []
    assert execution_policy["retryCount"] == 0
    supersession_map = matrix["supersessionMap"]
    assert isinstance(supersession_map, list)
    assert tuple(item["priorOperationId"] for item in supersession_map) == OPERATION_IDS
    assert tuple(item["operationContractId"] for item in supersession_map) == (OPERATION_IDS)
    assert all(
        item["priorDefinitionStatus"] == "blocked" and item["disposition"] == "preserved-blocked"
        for item in supersession_map
    )


@pytest.mark.parametrize(
    "mutate",
    [
        _remove_first_operation,
        _duplicate_first_operation,
        _add_unknown_operation,
        _change_version,
        _add_unknown_field,
        _remove_required_inputs,
        _empty_prerequisites,
        _prove_operation,
        _define_operation,
        _authorize_execution,
        _authorize_mutation,
        _authorize_provisioning,
        _fabricate_method,
        _fabricate_parser,
        _fabricate_evidence,
        _upgrade_infrastructure_gate,
        _upgrade_runtime_gate,
        _enable_retry,
        _change_source_review,
        _permit_output,
        _add_result_grammar,
        _change_outcome_policy,
        _add_privacy_transform,
    ],
)
def test_unknown_missing_malformed_or_authority_strengthening_changes_fail_closed(
    mutate: MatrixMutation,
) -> None:
    value = _matrix()
    mutate(value)
    _rehash(value)

    with pytest.raises(ContractError):
        validate_operation_contract_matrix(value)


def test_tampering_without_matching_integrity_fails_closed() -> None:
    value = _matrix()
    _first_operation(value)["blockingReason"] = "tampered"

    with pytest.raises(ContractError, match=r"closed contract|integrity"):
        validate_operation_contract_matrix(value)


def test_duplicate_json_key_and_non_finite_json_fail_before_validation() -> None:
    with pytest.raises(ContractError, match="duplicate JSON key"):
        loads_json('{"schemaVersion":"2020-12","schemaVersion":"tampered"}')
    with pytest.raises(ContractError, match="non-finite"):
        loads_json('{"value":NaN}')


@pytest.mark.parametrize(
    "conditions",
    [
        {},
        {"inputs_complete": True},
        {"inputs_complete": True, "prerequisites_complete": True},
        {
            "inputs_complete": True,
            "prerequisites_complete": True,
            "scope_valid": True,
            "authority_present": True,
            "evidence_valid": True,
            "evidence_fresh": True,
        },
    ],
)
def test_execution_is_denied_even_when_requested_conditions_are_claimed(
    conditions: dict[str, bool],
) -> None:
    result = operation_execution_decision(OPERATION_IDS[0], **conditions)

    assert result == {
        "operationId": OPERATION_IDS[0],
        "decision": "deny",
        "reason": (
            "operation-contract-remains-blocked"
            if len(conditions) == 6
            else "required-condition-missing"
        ),
        "executionAuthorized": False,
        "mutationAuthorized": False,
        "provisioningAuthorized": False,
    }


def test_unknown_operation_is_denied() -> None:
    with pytest.raises(ContractError, match="unknown operation"):
        operation_execution_decision("not-in-the-closed-registry")


def test_verifier_preserves_every_negative_state() -> None:
    result = operation_contract_verification_result()

    assert result["status"] == "valid"
    assert result["classification"] == (
        "complete-local-operation-contracts-with-provisioning-blocked"
    )
    assert result["operationCount"] == 15
    assert result["blockedOperationCount"] == 15
    assert result["unprovedOperationCount"] == 15
    assert result["blockedInfrastructureGateCount"] == len(INFRASTRUCTURE_GATES) == 10
    assert result["unprovedRuntimeGateCount"] == len(RUNTIME_GATES) == 5
    assert result["azureAccessAuthorized"] is False
    assert result["executionAuthorized"] is False
    assert result["mutationAuthorized"] is False
    assert result["provisioningAuthorized"] is False


def test_reproduction_and_verifier_are_deterministic_and_bounded() -> None:
    first_matrix = build_operation_contract_matrix()
    second_matrix = build_operation_contract_matrix()
    first_result = operation_contract_verification_result()
    second_result = operation_contract_verification_result()

    assert canonical_bytes(first_matrix) == canonical_bytes(second_matrix)
    assert canonical_bytes(first_result) == canonical_bytes(second_result)
    assert len(canonical_bytes(first_result)) < 16_384


def test_validation_has_no_process_network_or_azure_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external operation attempted")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    assert load_operation_contract_matrix()["defaultDecision"] == "deny"
    assert operation_contract_verification_result()["status"] == "valid"
    assert operation_execution_decision(OPERATION_IDS[-1])["decision"] == "deny"

    forbidden_imports = {
        "azure",
        "http",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    for path in (CONTRACT_MODULE, VERIFIER_MODULE):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_roots = {
            alias.name.split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (
                node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")]
            )
        }
        assert imported_roots.isdisjoint(forbidden_imports)


def test_no_milestone_7_7_migration_exists() -> None:
    assert not list((ROOT / "apps" / "api" / "alembic" / "versions").glob("*0029*"))


def test_contract_artifact_contains_no_raw_identifier_or_private_value() -> None:
    serialized = json.dumps(load_operation_contract_matrix(), sort_keys=True)

    assert "/subscriptions/" not in serialized.casefold()
    assert "@" not in serialized
    assert "c:\\users\\" not in serialized.casefold()
    assert "/home/" not in serialized.casefold()
    assert "privatelink." not in serialized.casefold()
