from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from performance.milestone_7_7.framework import (
    ContractError,
    canonical_bytes,
    loads_json,
)
from resilience.milestone_7_7.framework import REQUIRED_GATES
from validation.milestone_7_7.framework import (
    CHECKPOINT1_BUNDLE_SHA256,
    CHECKPOINT2_MANIFEST_SHA256,
    CHECKPOINT2_PLAN_SHA256,
    CHECKPOINT2_RESULT_SHA256,
    CHECKPOINT3_PACKAGE_SHA256,
    CHECKPOINT4_CATALOG_SHA256,
    CHECKPOINT4_PLAN_SHA256,
    EXPECTED_BINDINGS,
    MAX_REPORT_BYTES,
    MAX_VERIFIER_OUTPUT_BYTES,
    REQUIRED_LIMITATIONS,
    SOURCE_COMMIT,
    VALIDATION_CHECK_IDS,
    VALIDATION_REQUIREMENTS,
    build_local_report,
    load_json,
    report_bytes,
    report_integrity_sha256,
    validate_report,
    validation_requirement_catalog,
    validation_requirement_catalog_sha256,
    verify_report,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = ROOT / "validation/milestone_7_7"
EXAMPLE_PATH = PACKAGE_ROOT / "validation-report.example.json"
SCHEMA_PATH = PACKAGE_ROOT / "validation-report.schema.json"
FRAMEWORK_PATH = PACKAGE_ROOT / "framework.py"
MIGRATION_ROOT = ROOT / "apps/api/alembic/versions"
PRIVATE_KEY_SENTINEL = "".join(("-----BEGIN PRI", "VATE KEY-----"))
LINUX_HOME_SENTINEL = "/".join(("", "home", "person", "secret.txt"))


def _example() -> dict[str, Any]:
    value = load_json(EXAMPLE_PATH)
    assert isinstance(value, dict)
    return value


def _rehash(value: dict[str, Any]) -> dict[str, Any]:
    value["reportIntegritySha256"] = report_integrity_sha256(value)
    return value


def test_committed_example_matches_builder_exactly() -> None:
    assert _example() == build_local_report()


def test_example_is_valid_and_bound_to_checkpoint_4() -> None:
    report = validate_report(_example())
    assert report["source"] == {
        "repositoryId": "solarplexus-mobius",
        "commitSha": SOURCE_COMMIT,
        "dirty": False,
    }
    assert report["bindings"] == EXPECTED_BINDINGS
    assert report["reportIntegritySha256"] == (
        "f7ee0a76315f4ec1c3f2ce7facc4fe2219637d486b20e61fac95995563e9579c"
    )


def test_all_checkpoint_bindings_are_exact() -> None:
    assert EXPECTED_BINDINGS["checkpoint1BundleSha256"] == CHECKPOINT1_BUNDLE_SHA256
    assert EXPECTED_BINDINGS["checkpoint2ManifestSha256"] == CHECKPOINT2_MANIFEST_SHA256
    assert EXPECTED_BINDINGS["checkpoint2PlanSha256"] == CHECKPOINT2_PLAN_SHA256
    assert EXPECTED_BINDINGS["checkpoint2ResultSha256"] == CHECKPOINT2_RESULT_SHA256
    assert EXPECTED_BINDINGS["checkpoint3PackageSha256"] == CHECKPOINT3_PACKAGE_SHA256
    assert EXPECTED_BINDINGS["checkpoint4PlanSha256"] == CHECKPOINT4_PLAN_SHA256
    assert EXPECTED_BINDINGS["checkpoint4CatalogSha256"] == CHECKPOINT4_CATALOG_SHA256


def test_requirement_catalog_is_closed_and_bound() -> None:
    catalog = validation_requirement_catalog()
    requirements = catalog["requirements"]
    assert isinstance(requirements, list)
    assert [item["id"] for item in requirements] == list(VALIDATION_REQUIREMENTS)
    assert all(item["enforcement"] == "fail-closed" for item in requirements)
    assert all(item["evidenceBoundary"] == "focused-local-tests" for item in requirements)
    assert validation_requirement_catalog_sha256() == (
        "069c9e00e984249b45ef8c5de5b28581b4f8fa1818e62d2af7269d584ae84791"
    )


def test_validation_checks_are_complete() -> None:
    checks = _example()["validationChecks"]
    assert {item["id"] for item in checks} == set(VALIDATION_CHECK_IDS)
    assert {item["status"] for item in checks} == {"passed"}


def test_all_capabilities_are_false() -> None:
    capabilities = _example()["capabilities"]
    assert capabilities
    assert set(capabilities.values()) == {False}


def test_all_external_gates_remain_unresolved() -> None:
    gates = _example()["gateStates"]
    assert {item["id"] for item in gates} == set(REQUIRED_GATES)
    assert len(gates) == 15
    assert {item["status"] for item in gates} == {"unresolved"}


def test_completion_claim_stays_local_and_partial() -> None:
    report = _example()
    assert report["classification"] == {
        "environment": "unprovisioned-local",
        "execution": "contract-validation-only",
        "claimStrength": "local-contract-validation-only",
    }
    assert report["completion"] == {
        "localValidationState": "complete",
        "milestoneEvidenceState": "partial",
        "executionReadiness": "blocked",
        "nextCheckpoint": "azure-topology-preflight",
        "stopReason": "local-validation-complete",
    }
    assert set(report["limitations"]) == REQUIRED_LIMITATIONS


def test_verifier_is_byte_identical() -> None:
    first = report_bytes(verify_report(EXAMPLE_PATH))
    second = report_bytes(verify_report(EXAMPLE_PATH))
    assert first == second
    result = json.loads(first)
    assert result["status"] == "valid"
    assert result["localValidationState"] == "complete"
    assert result["milestoneEvidenceState"] == "partial"
    assert result["executionReadiness"] == "blocked"
    assert result["networkAccess"] is False
    assert result["processExecution"] is False
    assert result["faultExecution"] is False
    assert result["destructive"] is False


def test_hash_is_order_independent_for_closed_registries() -> None:
    report = _example()
    original = report["reportIntegritySha256"]
    for name in (
        "validationChecks",
        "validationRequirements",
        "gateStates",
        "evidenceStates",
        "limitations",
    ):
        report[name] = list(reversed(report[name]))
    assert report_integrity_sha256(report) == original
    assert validate_report(report)["reportIntegritySha256"] == original


@pytest.mark.parametrize(
    "field",
    [
        "schemaVersion",
        "contractVersion",
        "reportId",
        "purpose",
        "source",
        "bindings",
        "classification",
        "capabilities",
        "validationChecks",
        "validationRequirements",
        "gateStates",
        "evidenceStates",
        "completion",
        "limitations",
        "verifierVersion",
        "reportIntegritySha256",
    ],
)
def test_missing_top_level_field_fails_closed(field: str) -> None:
    report = _example()
    del report[field]
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize(
    "field",
    [
        "accessToken",
        "authorization",
        "clientSecret",
        "connectionString",
        "credential",
        "endpoint",
        "localPath",
        "password",
        "privateKey",
        "productionData",
        "requestBody",
        "responseBody",
        "signedUrl",
        "subscriptionId",
        "tenantId",
        "token",
    ],
)
def test_secret_or_private_field_fails_closed(field: str) -> None:
    report = _example()
    report[field] = "opaque"
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer abcdefghijklmnop",
        PRIVATE_KEY_SENTINEL,
        "eyJabcdefghijk.abcdefghijklmnop.signature",
        "https://example.invalid/?sig=opaque",
        "AccountKey=opaque",
        "C:\\Users\\person\\secret.txt",
        LINUX_HOME_SENTINEL,
        "/subscriptions/00000000-0000-4000-8000-000000000000/resourceGroups/private",
    ],
)
def test_sensitive_value_fails_closed(value: str) -> None:
    report = _example()
    report["reportId"] = value
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize(
    "value",
    [
        "../private",
        "..\\private",
        "/absolute/private",
        "C:\\absolute\\private",
    ],
)
def test_traversal_or_absolute_path_fails_closed(value: str) -> None:
    report = _example()
    report["reportId"] = value
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize("capability", list(_example()["capabilities"]))
def test_execution_capability_cannot_be_enabled(capability: str) -> None:
    report = _example()
    report["capabilities"][capability] = True
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize("binding", list(EXPECTED_BINDINGS))
def test_binding_tamper_fails_closed(binding: str) -> None:
    report = _example()
    report["bindings"][binding] = "0" * 64
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize(
    ("section", "replacement"),
    [
        ("classification", "production"),
        ("completion", "complete"),
    ],
)
def test_stronger_claim_fails_closed(section: str, replacement: str) -> None:
    report = _example()
    if section == "classification":
        report[section]["claimStrength"] = replacement
    else:
        report[section]["milestoneEvidenceState"] = replacement
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_resolved_gate_fails_closed() -> None:
    report = _example()
    report["gateStates"][0]["status"] = "resolved"
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_upgraded_evidence_fails_closed() -> None:
    report = _example()
    report["evidenceStates"][0]["state"] = "complete"
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_failed_validation_check_fails_closed() -> None:
    report = _example()
    report["validationChecks"][0]["status"] = "failed"
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize(
    "registry",
    [
        "validationChecks",
        "validationRequirements",
        "gateStates",
        "evidenceStates",
        "limitations",
    ],
)
def test_missing_registry_item_fails_closed(registry: str) -> None:
    report = _example()
    report[registry].pop()
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


@pytest.mark.parametrize(
    "registry",
    [
        "validationChecks",
        "validationRequirements",
        "gateStates",
        "evidenceStates",
        "limitations",
    ],
)
def test_duplicate_registry_item_fails_closed(registry: str) -> None:
    report = _example()
    report[registry][-1] = copy.deepcopy(report[registry][0])
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_unknown_field_fails_closed() -> None:
    report = _example()
    report["unexpected"] = False
    with pytest.raises(ContractError):
        validate_report(report)


def test_incompatible_version_fails_closed() -> None:
    report = _example()
    report["contractVersion"] = "mobius.m7.7.local-validation-report.v2"
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_dirty_source_fails_closed() -> None:
    report = _example()
    report["source"]["dirty"] = True
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_source_commit_tamper_fails_closed() -> None:
    report = _example()
    report["source"]["commitSha"] = "0" * 40
    _rehash(report)
    with pytest.raises(ContractError):
        validate_report(report)


def test_integrity_tamper_fails_closed() -> None:
    report = _example()
    report["reportIntegritySha256"] = "0" * 64
    with pytest.raises(ContractError):
        validate_report(report)


def test_float_and_unsafe_integer_fail_closed() -> None:
    report = _example()
    report["unexpectedFloat"] = 1.5
    with pytest.raises(ContractError):
        validate_report(report)
    report = _example()
    report["unexpectedInteger"] = 2**53
    with pytest.raises(ContractError):
        validate_report(report)


def test_duplicate_json_key_fails_closed() -> None:
    with pytest.raises(ContractError):
        loads_json('{"reportId":"a","reportId":"b"}')


def test_nonfinite_json_fails_closed() -> None:
    with pytest.raises(ContractError):
        loads_json('{"value":NaN}')


def test_oversized_report_fails_before_schema_acceptance() -> None:
    report = _example()
    report["oversized"] = "x" * MAX_REPORT_BYTES
    with pytest.raises(ContractError, match="size ceiling"):
        validate_report(report)


def test_oversized_verifier_output_fails_closed() -> None:
    with pytest.raises(ContractError, match="output exceeds"):
        report_bytes({"value": "x" * MAX_VERIFIER_OUTPUT_BYTES})


def test_invalid_verifier_output_is_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"unexpected":true}', encoding="utf-8")
    result = verify_report(invalid)
    assert result["status"] == "invalid"
    assert result["errorCode"] == "invalid-local-validation-report"
    assert result["reportId"] is None
    assert "exception" not in json.dumps(result).lower()
    assert str(tmp_path) not in json.dumps(result)


def test_missing_and_non_utf8_input_fail_closed(tmp_path: Path) -> None:
    missing = verify_report(tmp_path / "missing.json")
    assert missing["status"] == "invalid"
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    assert verify_report(binary)["status"] == "invalid"


def test_canonical_output_is_bounded() -> None:
    encoded = canonical_bytes(_example())
    assert len(encoded) <= MAX_REPORT_BYTES
    assert encoded.endswith(b"\n")
    assert len(report_bytes(verify_report(EXAMPLE_PATH))) <= MAX_VERIFIER_OUTPUT_BYTES


def test_schema_is_closed_and_uses_local_references_only() -> None:
    schema = load_json(SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    serialized = json.dumps(schema, sort_keys=True)
    references = [
        node["$ref"] for node in _walk_objects(schema) if isinstance(node, dict) and "$ref" in node
    ]
    assert references
    assert all(reference.startswith("#/") for reference in references)
    assert "http://json-schema.org" not in serialized


def _walk_objects(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_walk_objects(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk_objects(item))
    return values


def test_framework_has_no_network_or_process_client() -> None:
    tree = ast.parse(FRAMEWORK_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    assert imported.isdisjoint(
        {
            "aiohttp",
            "azure",
            "boto3",
            "httpx",
            "paramiko",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
    )
    assert calls.isdisjoint(
        {
            "Popen",
            "connect",
            "create_connection",
            "exec",
            "run",
            "system",
        }
    )


def test_builder_and_verifier_create_no_package_files() -> None:
    before = sorted(
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file()
    )
    build_local_report()
    verify_report(EXAMPLE_PATH)
    after = sorted(
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file()
    )
    assert after == before


def test_migration_0029_remains_absent() -> None:
    assert not list(MIGRATION_ROOT.glob("*0029*"))
