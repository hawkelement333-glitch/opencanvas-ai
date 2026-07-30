from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from performance.milestone_7_7.framework import ContractError, canonical_bytes, load_json
from preflight.milestone_7_7 import framework as topology_framework
from preflight.milestone_7_7.framework import (
    ALLOWED_GATE_STATES,
    CLEANUP_RESOURCE_GROUP,
    DEFINED_OPERATION_IDS,
    EXPECTED_RESOURCE_GROUP_COMMAND,
    INFRASTRUCTURE_GATES,
    INVENTORY_PATH,
    MAXIMUM_EVIDENCE_AGE_SECONDS,
    OPERATION_IDS,
    RESOURCE_GROUP_OPERATION_IDS,
    RUNTIME_GATES,
    SCOPE_PATH,
    SUBSCRIPTION_FINGERPRINT,
    SUBSCRIPTION_FINGERPRINT_DOMAIN,
    TARGET_RESOURCE_GROUP,
    TENANT_FINGERPRINT,
    build_scope_contract,
    evidence_integrity_sha256,
    inventory_integrity_sha256,
    load_operation_inventory,
    load_scope_contract,
    materialize_resource_group_exists_command,
    parse_resource_group_exists_result,
    resource_group_exists_command_template,
    scope_integrity_sha256,
    scope_verification_result,
    validate_evidence,
    validate_operation_inventory,
    validate_scope_contract,
)

ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_PATH = ROOT / "preflight" / "milestone_7_7" / "framework.py"
VERIFY_PATH = ROOT / "preflight" / "milestone_7_7" / "verify.py"
MIGRATION_ROOT = ROOT / "apps" / "api" / "alembic" / "versions"
NOW = datetime(2026, 7, 30, 12, 2, tzinfo=UTC)
OBSERVED_AT = "2026-07-30T12:00:00Z"
VERIFIED_AT = "2026-07-30T12:01:00Z"
EXPIRES_AT = "2026-07-31T12:00:00Z"
HISTORICAL_INVENTORY_SHA256 = "6d8047c2a89bdbe96d3962db5dc2f66eda8e753a02be2d85591b4fa6fe061362"
HISTORICAL_SCOPE_SHA256 = "cc47f0d150953f1df026a40432573372ba41d4c84fb9a39a96dc0fda8ac20cb5"


def _inventory() -> dict[str, Any]:
    value = load_json(INVENTORY_PATH)
    assert isinstance(value, dict)
    return value


def _scope() -> dict[str, Any]:
    value = load_json(SCOPE_PATH)
    assert isinstance(value, dict)
    return value


def _rehash_inventory(value: dict[str, Any]) -> dict[str, Any]:
    value["inventoryIntegritySha256"] = inventory_integrity_sha256(value)
    return value


def _rehash_scope(value: dict[str, Any]) -> dict[str, Any]:
    value["scopeIntegritySha256"] = scope_integrity_sha256(value)
    return value


def _operation(value: dict[str, Any], operation_id: str) -> dict[str, Any]:
    return next(item for item in value["operations"] if item["id"] == operation_id)


def _evidence() -> dict[str, Any]:
    scope = load_scope_contract()
    inventory = load_operation_inventory()
    scope_hash = scope["scopeIntegritySha256"]
    inventory_hash = inventory["inventoryIntegritySha256"]
    observations = []
    for operation in inventory["operations"]:
        operation_id = operation["id"]
        if operation_id == "current-account-context":
            fields = [
                {"id": "cloud", "value": "AzureCloud"},
                {"id": "is-default", "value": True},
                {"id": "state", "value": "Enabled"},
                {"id": "subscription-fingerprint", "value": SUBSCRIPTION_FINGERPRINT},
                {"id": "tenant-fingerprint", "value": TENANT_FINGERPRINT},
                {"id": "user-type", "value": "user"},
            ]
            status = "proved"
            explanation = "approved-context-matched"
        elif operation_id in RESOURCE_GROUP_OPERATION_IDS:
            fields = []
            status = "blocked"
            explanation = "operation-execution-not-authorized"
        else:
            fields = []
            status = "blocked"
            explanation = "operation-template-blocked"
        observations.append(
            {
                "operationId": operation_id,
                "status": status,
                "observedAtUtc": OBSERVED_AT,
                "authorityLevel": operation["authorityLevel"],
                "scopeIntegritySha256": scope_hash,
                "fields": fields,
                "minimumProjection": True,
                "rawIdentifiersRetained": False,
                "dataPlane": False,
                "mutation": False,
                "explanationCode": explanation,
            }
        )

    infrastructure_gates = []
    for gate_id in INFRASTRUCTURE_GATES:
        operation_ids = [
            operation["id"]
            for operation in inventory["operations"]
            if gate_id in operation["supports"]
        ]
        infrastructure_gates.append(
            {
                "gateId": gate_id,
                "status": "blocked",
                "operationIds": operation_ids,
                "explanationCode": "required-operation-template-blocked",
            }
        )

    evidence: dict[str, Any] = {
        "schemaVersion": "2020-12",
        "contractVersion": "mobius.milestone-7.7.azure-topology-preflight.v1",
        "canonicalizationVersion": "mobius.milestone-7.7.canonical-json.v1",
        "evidenceId": "m7.7-cp6-synthetic-contract-fixture",
        "scopeIntegritySha256": scope_hash,
        "operationInventorySha256": inventory_hash,
        "observedAtUtc": OBSERVED_AT,
        "verifiedAtUtc": VERIFIED_AT,
        "expiresAtUtc": EXPIRES_AT,
        "observations": observations,
        "infrastructureGates": infrastructure_gates,
        "runtimeGates": [
            {
                "gateId": gate_id,
                "status": "unproved",
                "operationIds": [],
                "explanationCode": "runtime-evidence-required",
            }
            for gate_id in RUNTIME_GATES
        ],
        "privacy": {
            "minimumFieldProjection": True,
            "rawAzureOutputRetained": False,
            "rawAzureIdentifiersRetained": False,
            "dataPlaneEvidenceRetained": False,
            "privateOperationalDataRetained": False,
        },
        "completion": {
            "scopeDefinitionStatus": "complete-local",
            "preflightStatus": "complete-with-provisioning-blocked",
            "runtimeGatesResolved": False,
            "provisioningAuthorized": False,
        },
    }
    evidence["evidenceIntegritySha256"] = evidence_integrity_sha256(evidence)
    return evidence


def _rehash_evidence(value: dict[str, Any]) -> dict[str, Any]:
    value["evidenceIntegritySha256"] = evidence_integrity_sha256(value)
    return value


def test_committed_scope_matches_builder_and_validates() -> None:
    assert canonical_bytes(_scope()) == canonical_bytes(build_scope_contract())
    assert load_scope_contract() == _scope()


def test_scope_binds_the_exact_approved_future_boundary() -> None:
    scope = load_scope_contract()
    azure_scope = scope["azureScope"]
    assert azure_scope == {
        "cloud": "AzureCloud",
        "fingerprintAlgorithm": "domain-separated-sha256-of-lowercase-identifier-v1",
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
    }
    assert scope["evidencePolicy"]["maximumAgeSeconds"] == MAXIMUM_EVIDENCE_AGE_SECONDS
    assert tuple(scope["evidencePolicy"]["allowedGateStates"]) == ALLOWED_GATE_STATES
    assert scope["evidencePolicy"]["checksumIsSignature"] is False
    assert scope["checkpointStatus"] == (
        "blocked-pending-separately-authorized-azure-topology-preflight-execution"
    )
    assert scope["azureExecutionAuthorized"] is False
    assert scope["provisioningAuthorized"] is False


def test_scope_verifier_is_deterministic_and_bounded() -> None:
    first = scope_verification_result()
    second = scope_verification_result()
    assert canonical_bytes(first) == canonical_bytes(second)
    assert len(canonical_bytes(first)) <= 16_384
    assert first["status"] == "valid"
    assert first["operationCount"] == 18
    assert first["definedOperationCount"] == 3
    assert first["blockedOperationCount"] == 15


def test_inventory_is_exact_closed_default_deny_and_control_plane_only() -> None:
    inventory = load_operation_inventory()
    operations = inventory["operations"]
    assert tuple(item["id"] for item in operations) == OPERATION_IDS
    assert inventory["defaultDecision"] == "deny"
    assert inventory["defaults"]["unknownOperationDecision"] == "deny"
    assert inventory["defaults"]["rawOutputRetentionAllowed"] is False
    assert all(item["controlPlane"] is True for item in operations)
    assert all(item["dataPlane"] is False for item in operations)
    assert all(item["mutating"] is False for item in operations)
    assert [item["id"] for item in operations if item["definitionStatus"] == "defined"] == list(
        DEFINED_OPERATION_IDS
    )
    assert all(
        item["commandTemplate"] is None
        for item in operations
        if item["definitionStatus"] == "blocked"
    )


InventoryMutation = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: _operation(value, "regional-service-availability").update(
            {"supports": ["telemetry-gateway"]}
        ),
        lambda value: _operation(value, "regional-service-availability").update(
            {"permittedRegions": ["eastus"]}
        ),
        lambda value: _operation(value, "regional-service-availability").update(
            {"permittedScope": "approved-future-resource-groups"}
        ),
        lambda value: _operation(value, "regional-service-availability").update(
            {"authorityLevel": "repository-approved-scope"}
        ),
        lambda value: _operation(value, "regional-service-availability").update(
            {"semanticReadOnlyVerified": True}
        ),
        lambda value: _operation(value, "regional-service-availability").update(
            {"commandTemplate": ["az", "group", "list"]}
        ),
        lambda value: _operation(value, "current-account-context").update(
            {"commandTemplate": ["az", "account", "set", "--subscription", "redacted"]}
        ),
        lambda value: _operation(value, "current-account-context").update({"dataPlane": True}),
        lambda value: _operation(value, "current-account-context").update({"mutating": True}),
        lambda value: _operation(value, "current-account-context")["transforms"][0].update(
            {"domain": "mobius.azure.tenant-context.v1"}
        ),
        lambda value: _operation(value, "target-group-existence").update(
            {"commandTemplate": ["az", "group", "list"]}
        ),
        lambda value: _operation(value, "target-group-existence").update(
            {"commandTemplate": ["az", "group", "create"]}
        ),
        lambda value: _operation(value, "target-group-existence").update(
            {"commandTemplate": ["az", "storage", "blob", "list"]}
        ),
    ],
)
def test_inventory_semantic_tampering_fails_closed(mutate: InventoryMutation) -> None:
    inventory = _inventory()
    mutate(inventory)
    _rehash_inventory(inventory)
    with pytest.raises(ContractError):
        validate_operation_inventory(inventory)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subscriptionFingerprint", "A" * 64),
        ("tenantFingerprint", "0" * 63),
        ("targetResourceGroup", "rg-unapproved"),
        ("cleanupControlResourceGroup", "rg-unapproved"),
    ],
)
def test_scope_rejects_unapproved_or_malformed_values(field: str, value: str) -> None:
    scope = _scope()
    scope["azureScope"][field] = value
    _rehash_scope(scope)
    with pytest.raises(ContractError):
        validate_scope_contract(scope)


def test_synthetic_contract_evidence_is_valid_and_deterministic() -> None:
    evidence = _evidence()
    reordered = deepcopy(evidence)
    reordered["observations"].reverse()
    reordered["infrastructureGates"].reverse()
    reordered["runtimeGates"].reverse()
    for observation in reordered["observations"]:
        observation["fields"].reverse()
    assert evidence_integrity_sha256(evidence) == evidence_integrity_sha256(reordered)
    assert validate_evidence(evidence, now=NOW) == evidence


def _synthetic_subscription_fingerprint(raw_subscription_id: str) -> str:
    payload = (
        SUBSCRIPTION_FINGERPRINT_DOMAIN.encode("utf-8")
        + b"\0"
        + raw_subscription_id.lower().encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    ("operation_id", "resource_group_name"),
    [
        ("target-group-existence", TARGET_RESOURCE_GROUP),
        ("cleanup-group-existence", CLEANUP_RESOURCE_GROUP),
    ],
)
def test_resource_group_command_is_exact_independent_and_explicitly_scoped(
    operation_id: str,
    resource_group_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_subscription_id = "-".join(("synthetic", "subscription", "context"))
    with monkeypatch.context() as context:
        context.setattr(
            topology_framework,
            "SUBSCRIPTION_FINGERPRINT",
            _synthetic_subscription_fingerprint(raw_subscription_id),
        )
        command = materialize_resource_group_exists_command(
            operation_id,
            raw_subscription_id,
        )
    assert command == (
        "az",
        "group",
        "exists",
        "--name",
        resource_group_name,
        "--subscription",
        raw_subscription_id,
        "--only-show-errors",
        "--output",
        "tsv",
    )
    assert command.count("--subscription") == 1
    assert "list" not in command
    assert "show" not in command
    assert "resource" not in command

    inventory = load_operation_inventory()
    operation = _operation(inventory, operation_id)
    assert tuple(operation["commandTemplate"]) == EXPECTED_RESOURCE_GROUP_COMMAND
    assert operation["retainedProjection"] == ["exists"]
    assert operation["controlPlane"] is True
    assert operation["dataPlane"] is False
    assert operation["mutating"] is False
    assert resource_group_exists_command_template(operation_id) == (
        "az",
        "group",
        "exists",
        "--name",
        resource_group_name,
        "--subscription",
        "{verified_subscription_id}",
        "--only-show-errors",
        "--output",
        "tsv",
    )

    retained_contracts = canonical_bytes(
        {
            "inventory": inventory,
            "scope": load_scope_contract(),
            "evidence": _evidence(),
        }
    )
    assert raw_subscription_id.encode("utf-8") not in retained_contracts


def test_subscription_fingerprint_mismatch_prevents_command_materialization() -> None:
    with pytest.raises(ContractError, match="fingerprint mismatch"):
        materialize_resource_group_exists_command(
            "target-group-existence",
            "-".join(("synthetic", "wrong", "subscription")),
        )


def test_unknown_resource_group_operation_cannot_materialize() -> None:
    with pytest.raises(ContractError, match="closed inventory"):
        resource_group_exists_command_template("regional-service-availability")


@pytest.mark.parametrize("stdout", ["false", "false\n", "false\r\n"])
def test_exact_false_output_projects_only_proved_absence(stdout: str) -> None:
    assert parse_resource_group_exists_result(
        stdout=stdout,
        exit_code=0,
        timed_out=False,
    ) == {
        "status": "proved",
        "fields": [{"id": "exists", "value": False}],
        "explanationCode": "exact-resource-group-absent",
    }


@pytest.mark.parametrize("stdout", ["true", "true\n", "true\r\n"])
def test_exact_true_output_fails_closed_as_existing_group(stdout: str) -> None:
    assert parse_resource_group_exists_result(
        stdout=stdout,
        exit_code=0,
        timed_out=False,
    ) == {
        "status": "failed",
        "fields": [],
        "explanationCode": "exact-resource-group-present",
    }


def test_nonzero_exit_and_timeout_fail_closed_without_retained_output() -> None:
    assert parse_resource_group_exists_result(
        stdout="false\n",
        exit_code=1,
        timed_out=False,
    ) == {
        "status": "failed",
        "fields": [],
        "explanationCode": "resource-group-query-error",
    }
    assert parse_resource_group_exists_result(
        stdout="false\n",
        exit_code=0,
        timed_out=True,
    ) == {
        "status": "failed",
        "fields": [],
        "explanationCode": "resource-group-query-timeout",
    }


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "\n",
        "False\n",
        " false\n",
        "false \n",
        "false\nfalse\n",
        "warning\nfalse\n",
        "false true\n",
        "null\n",
        "{}\n",
    ],
)
def test_blank_malformed_mixed_duplicate_or_unexpected_output_fails_closed(
    stdout: str,
) -> None:
    result = parse_resource_group_exists_result(
        stdout=stdout,
        exit_code=0,
        timed_out=False,
    )
    assert result == {
        "status": "failed",
        "fields": [],
        "explanationCode": "resource-group-output-malformed",
    }


def test_group_absence_observations_validate_without_resolving_the_gate() -> None:
    evidence = _evidence()
    for operation_id in RESOURCE_GROUP_OPERATION_IDS:
        observation = next(
            item for item in evidence["observations"] if item["operationId"] == operation_id
        )
        observation.update(
            parse_resource_group_exists_result(
                stdout="false\n",
                exit_code=0,
                timed_out=False,
            )
        )
    _rehash_evidence(evidence)
    validated = validate_evidence(evidence, now=NOW)
    assert all(row["status"] == "blocked" for row in validated["infrastructureGates"])
    assert all(row["status"] == "unproved" for row in validated["runtimeGates"])


@pytest.mark.parametrize(
    ("status", "fields", "explanation_code"),
    [
        ("proved", [{"id": "exists", "value": True}], "exact-resource-group-absent"),
        ("proved", [{"id": "exists", "value": False}], "claimed-result"),
        ("failed", [{"id": "exists", "value": False}], "resource-group-query-error"),
        ("failed", [], "claimed-result"),
        ("blocked", [], "operation-template-blocked"),
        ("unproved", [], "operation-not-observed"),
    ],
)
def test_group_existence_evidence_semantics_fail_closed(
    status: str,
    fields: list[dict[str, object]],
    explanation_code: str,
) -> None:
    evidence = _evidence()
    observation = next(
        item for item in evidence["observations"] if item["operationId"] == "target-group-existence"
    )
    observation.update(
        {
            "status": status,
            "fields": fields,
            "explanationCode": explanation_code,
        }
    )
    _rehash_evidence(evidence)
    with pytest.raises(ContractError):
        validate_evidence(evidence, now=NOW)


def test_historical_inventory_and_scope_hashes_are_not_current_proof() -> None:
    evidence = _evidence()
    evidence["operationInventorySha256"] = HISTORICAL_INVENTORY_SHA256
    evidence["scopeIntegritySha256"] = HISTORICAL_SCOPE_SHA256
    for observation in evidence["observations"]:
        observation["scopeIntegritySha256"] = HISTORICAL_SCOPE_SHA256
    _rehash_evidence(evidence)
    with pytest.raises(ContractError, match="mixed or unknown scope"):
        validate_evidence(evidence, now=NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observedAtUtc", "2026-07-30T12:00:00"),
        ("observedAtUtc", "malformed"),
        ("expiresAtUtc", "2026-07-31T11:59:59Z"),
    ],
)
def test_evidence_rejects_naive_malformed_or_wrong_expiry(field: str, value: str) -> None:
    evidence = _evidence()
    evidence[field] = value
    _rehash_evidence(evidence)
    with pytest.raises(ContractError):
        validate_evidence(evidence, now=NOW)


def test_evidence_rejects_stale_future_and_non_utc_verification() -> None:
    evidence = _evidence()
    with pytest.raises(ContractError, match="stale"):
        validate_evidence(evidence, now=datetime(2026, 7, 31, 12, 0, 1, tzinfo=UTC))
    with pytest.raises(ContractError, match="future"):
        validate_evidence(evidence, now=datetime(2026, 7, 30, 11, 59, 59, tzinfo=UTC))
    with pytest.raises(ContractError, match="timezone-aware UTC"):
        validate_evidence(evidence, now=datetime(2026, 7, 30, 12, 2))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"scopeIntegritySha256": "1" * 64}),
        lambda value: value.update({"operationInventorySha256": "2" * 64}),
        lambda value: value["observations"].pop(),
        lambda value: value["observations"].append(deepcopy(value["observations"][0])),
        lambda value: value["observations"][0].update({"operationId": "unknown-operation"}),
        lambda value: value["infrastructureGates"].pop(),
        lambda value: value["runtimeGates"][0].update({"status": "proved"}),
        lambda value: value["runtimeGates"][0].update(
            {"operationIds": ["current-account-context"]}
        ),
        lambda value: value["observations"][1].update(
            {
                "status": "proved",
                "fields": [{"id": "unexpected", "value": True}],
                "explanationCode": "claimed-result",
            }
        ),
        lambda value: value["observations"][0]["fields"].append(
            {"id": "unexpected", "value": True}
        ),
        lambda value: value["infrastructureGates"][0].update({"status": "proved"}),
    ],
)
def test_incomplete_duplicate_unknown_mixed_or_conflicting_evidence_fails_closed(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    evidence = _evidence()
    mutate(evidence)
    _rehash_evidence(evidence)
    with pytest.raises(ContractError):
        validate_evidence(evidence, now=NOW)


@pytest.mark.parametrize(
    ("field_id", "value"),
    [
        ("subscription-fingerprint", "0" * 64),
        ("tenant-fingerprint", "1" * 64),
        ("cloud", "AzureUSGovernment"),
        ("is-default", False),
        ("state", "Disabled"),
    ],
)
def test_account_context_mismatch_fails_closed(field_id: str, value: object) -> None:
    evidence = _evidence()
    account = evidence["observations"][0]
    next(item for item in account["fields"] if item["id"] == field_id)["value"] = value
    _rehash_evidence(evidence)
    with pytest.raises(ContractError):
        validate_evidence(evidence, now=NOW)


@pytest.mark.parametrize(
    "sensitive",
    [
        "-".join(("11111111", "1111", "4111", "8111", "111111111111")),
        "/".join(("", "subscriptions", "redacted", "resourceGroups", "rg-example")),
        "@".join(("person", "example.com")),
        ".".join(("10", "12", "13", "14")),
        ".".join(("private", "internal", "example")),
        "\\".join(("C:", "Users", "person", "secret.txt")),
    ],
)
def test_raw_identifiers_private_values_and_local_paths_are_rejected(
    sensitive: str,
) -> None:
    evidence = _evidence()
    account = evidence["observations"][0]
    next(item for item in account["fields"] if item["id"] == "user-type")["value"] = sensitive
    with pytest.raises(ContractError, match="prohibited"):
        _rehash_evidence(evidence)
        validate_evidence(evidence, now=NOW)


def test_tampered_evidence_hash_is_rejected() -> None:
    evidence = _evidence()
    evidence["evidenceIntegritySha256"] = "0" * 64
    with pytest.raises(ContractError, match="integrity mismatch"):
        validate_evidence(evidence, now=NOW)


def test_framework_and_verifier_have_no_execution_or_network_clients() -> None:
    prohibited_imports = {
        "asyncio",
        "azure",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    for path in (FRAMEWORK_PATH, VERIFY_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert imports.isdisjoint(prohibited_imports)


def test_no_milestone_7_7_migration_exists() -> None:
    assert not list(MIGRATION_ROOT.glob("20260726_0029*"))
