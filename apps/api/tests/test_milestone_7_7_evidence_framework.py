from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from evidence.milestone_7_7.framework import (
    EVIDENCE_CLASSES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACTS,
    MAX_LIMITATIONS,
    MAX_METADATA_BYTES,
    MAX_VALIDATION_EVENTS,
    MAX_VERIFIER_OUTPUT_BYTES,
    PACKAGE_DOMAIN,
    REQUIRED_LIMITATIONS,
    UNRESOLVED_GATES,
    ContractError,
    build_local_package,
    package_integrity_sha256,
    report_bytes,
    validate_package,
    verify_package,
)
from performance.milestone_7_7.framework import (
    canonical_bytes,
    load_json,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_PATH = REPOSITORY_ROOT / "evidence" / "milestone_7_7" / "evidence-package.example.json"
MANIFEST_NAME = "performance/milestone_7_7/workload.example.json"
PLAN_NAME = "evidence/milestone_7_7/fixtures/request-plan.fixture.json"
RESULT_NAME = "evidence/milestone_7_7/fixtures/measurement-result.fixture.json"
SOURCE_COMMIT = "032957cc6bf68dd0cf16b4971cdafb6624f0303a"


def _package() -> dict[str, Any]:
    value = load_json(PACKAGE_PATH)
    assert isinstance(value, dict)
    return value


def _rehash(value: dict[str, Any]) -> dict[str, Any]:
    value["packageIntegritySha256"] = package_integrity_sha256(value)
    return value


def _copy_artifacts(root: Path) -> None:
    for logical_name in (MANIFEST_NAME, PLAN_NAME, RESULT_NAME):
        target = root.joinpath(*logical_name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / logical_name, target)


def _rebind_file(package: dict[str, Any], root: Path, logical_name: str) -> None:
    artifact = next(item for item in package["artifacts"] if item["logicalName"] == logical_name)
    content = root.joinpath(*logical_name.split("/")).read_bytes()
    artifact["sizeBytes"] = len(content)
    artifact["contentSha256"] = hashlib.sha256(content).hexdigest()
    _rehash(package)


def test_valid_bounded_local_package_is_accepted() -> None:
    package = validate_package(_package(), artifact_root=REPOSITORY_ROOT)

    assert package["environmentClass"] == "synthetic-local"
    assert package["claimStrength"] == "local-contract-validation-only"
    assert package["completeness"] == {
        "packageState": "complete",
        "milestoneState": "partial",
    }


def test_builder_reproduces_committed_example() -> None:
    package = build_local_package(
        artifact_root=REPOSITORY_ROOT,
        source_commit=SOURCE_COMMIT,
        manifest_name=MANIFEST_NAME,
        plan_name=PLAN_NAME,
        result_name=RESULT_NAME,
    )

    assert canonical_bytes(package) == canonical_bytes(_package())


@pytest.mark.parametrize("field", ["source", "artifacts", "validationState"])
def test_missing_required_fields_are_rejected(field: str) -> None:
    package = _package()
    del package[field]

    with pytest.raises(ContractError):
        validate_package(package)


def test_unknown_fields_are_rejected() -> None:
    package = _package()
    package["unexpected"] = True

    with pytest.raises(ContractError):
        validate_package(package)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("environmentClass",), "azure-test"),
        (("executionClass",), "managed-execution"),
        (("claimStrength",), "production-capacity"),
        (("validationState",), "passed"),
    ],
)
def test_closed_registries_reject_unsupported_values(path: tuple[str, ...], value: str) -> None:
    package = _package()
    package[path[0]] = value
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


def test_semantic_hash_is_deterministic_and_order_insensitive() -> None:
    package = _package()
    reordered = deepcopy(package)
    reordered["artifacts"].reverse()
    reordered["evidenceClasses"].reverse()
    reordered["validationEvents"].reverse()
    reordered["knownLimitations"].reverse()
    reordered["unresolvedGates"].reverse()

    assert package_integrity_sha256(package) == package_integrity_sha256(reordered)
    assert (
        validate_package(reordered)["packageIntegritySha256"] == package["packageIntegritySha256"]
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["source"].update({"commitSha": "1" * 40}),
        lambda value: value["checkpoint2Bindings"]["workloadManifest"].update(
            {"integritySha256": "1" * 64}
        ),
        lambda value: value["checkpoint2Bindings"]["requestPlan"].update(
            {"integritySha256": "2" * 64}
        ),
        lambda value: value["checkpoint2Bindings"]["measurementResult"].update(
            {"integritySha256": "3" * 64}
        ),
        lambda value: value["checkpoint2Bindings"]["assertions"][0].update({"passed": False}),
        lambda value: value["executionWindow"].update({"endedAtLogicalUs": 5_755_330}),
        lambda value: value["artifacts"][0].update({"contentSha256": "4" * 64}),
        lambda value: value.update({"validationState": "blocked"}),
        lambda value: value["knownLimitations"].reverse(),
    ],
)
def test_material_changes_affect_hash(mutator: Any) -> None:
    package = _package()
    original = package_integrity_sha256(package)
    mutator(package)

    if package["knownLimitations"] == list(reversed(_package()["knownLimitations"])):
        assert package_integrity_sha256(package) == original
    else:
        assert package_integrity_sha256(package) != original


def test_package_hash_is_domain_separated() -> None:
    package = _package()
    body = deepcopy(package)
    body.pop("packageIntegritySha256")
    plain = hashlib.sha256(canonical_bytes(body)).hexdigest()
    domain_hash = hashlib.sha256(PACKAGE_DOMAIN + canonical_bytes(body)).hexdigest()

    assert package_integrity_sha256(package) != plain
    assert package_integrity_sha256(package) != domain_hash


def test_modified_artifact_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    plan = tmp_path.joinpath(*PLAN_NAME.split("/"))
    plan.write_bytes(plan.read_bytes() + b" ")

    with pytest.raises(ContractError, match="size"):
        validate_package(_package(), artifact_root=tmp_path)


def test_missing_artifact_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    tmp_path.joinpath(*RESULT_NAME.split("/")).unlink()

    with pytest.raises((ContractError, FileNotFoundError)):
        validate_package(_package(), artifact_root=tmp_path)


def test_duplicate_and_conflicting_artifacts_are_rejected() -> None:
    package = _package()
    package["artifacts"][1]["logicalName"] = package["artifacts"][0]["logicalName"]
    _rehash(package)

    with pytest.raises(ContractError, match="duplicate"):
        validate_package(package)


def test_substituted_artifact_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    plan = tmp_path.joinpath(*PLAN_NAME.split("/"))
    plan.write_bytes(tmp_path.joinpath(*RESULT_NAME.split("/")).read_bytes())
    package = _package()
    _rebind_file(package, tmp_path, PLAN_NAME)

    with pytest.raises(ContractError, match="request-plan"):
        validate_package(package, artifact_root=tmp_path)


def test_truncated_artifact_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    result = tmp_path.joinpath(*RESULT_NAME.split("/"))
    result.write_bytes(result.read_bytes()[:100])
    package = _package()
    _rebind_file(package, tmp_path, RESULT_NAME)

    with pytest.raises(ContractError):
        validate_package(package, artifact_root=tmp_path)


def test_stale_cross_package_artifact_binding_is_rejected() -> None:
    package = _package()
    package["artifacts"][0]["packageId"] = "another-package"
    _rehash(package)

    with pytest.raises(ContractError, match="another evidence package"):
        validate_package(package)


def test_unexpected_artifact_role_is_rejected() -> None:
    package = _package()
    package["artifacts"][0]["role"] = "provider-receipt"
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


def test_artifact_semantic_hash_must_match_checkpoint2_binding() -> None:
    package = _package()
    package["artifacts"][0]["semanticIntegritySha256"] = "5" * 64
    _rehash(package)

    with pytest.raises(ContractError, match="semantic hash"):
        validate_package(package)


@pytest.mark.parametrize(
    "logical_name",
    [
        "../outside.json",
        "/absolute.json",
        "C:/private.json",
        "evidence//result.json",
        "evidence/./result.json",
        "https://example.invalid/result.json",
        "file:///private/result.json",
    ],
)
def test_unsafe_artifact_paths_are_rejected(logical_name: str) -> None:
    package = _package()
    package["artifacts"][0]["logicalName"] = logical_name
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


def test_symlink_artifact_escape_is_rejected(tmp_path: Path) -> None:
    if not hasattr(Path, "symlink_to"):
        pytest.skip("symlinks are unavailable")
    _copy_artifacts(tmp_path)
    source = tmp_path.joinpath(*PLAN_NAME.split("/"))
    link = source.with_name("linked-plan.json")
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("the current Windows account cannot create symlinks")
    package = _package()
    package["artifacts"][1]["logicalName"] = link.relative_to(tmp_path).as_posix()
    _rehash(package)

    with pytest.raises(ContractError, match="symlink"):
        validate_package(package, artifact_root=tmp_path)


def test_inventory_count_and_size_bounds_are_enforced() -> None:
    package = _package()
    package["artifacts"] = package["artifacts"] * (MAX_ARTIFACTS + 1)
    _rehash(package)
    with pytest.raises(ContractError):
        validate_package(package)

    package = _package()
    package["artifacts"][0]["sizeBytes"] = MAX_ARTIFACT_BYTES + 1
    _rehash(package)
    with pytest.raises(ContractError):
        validate_package(package)


def test_metadata_and_collection_bounds_are_enforced() -> None:
    package = _package()
    package["purpose"] = "x" * (MAX_METADATA_BYTES + 1)
    _rehash(package)
    with pytest.raises(ContractError, match="metadata"):
        validate_package(package)

    package = _package()
    package["validationEvents"] = package["validationEvents"] * (MAX_VALIDATION_EVENTS + 1)
    _rehash(package)
    with pytest.raises(ContractError):
        validate_package(package)

    package = _package()
    package["knownLimitations"] = ["unsigned"] * (MAX_LIMITATIONS + 1)
    _rehash(package)
    with pytest.raises(ContractError):
        validate_package(package)


def test_label_cardinality_is_closed() -> None:
    package = _package()
    package["labels"]["requestId"] = "high-cardinality"
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


@pytest.mark.parametrize(
    "state", ["failed", "skipped", "unavailable", "blocked", "partial", "unproved"]
)
def test_negative_validation_state_cannot_be_hidden_by_complete_package(
    state: str,
) -> None:
    package = _package()
    package["validationEvents"][0]["state"] = state
    _rehash(package)

    with pytest.raises(ContractError, match="complete"):
        validate_package(package)


def test_failed_assertion_cannot_be_hidden_by_complete_package() -> None:
    package = _package()
    package["checkpoint2Bindings"]["assertions"][0]["passed"] = False
    _rehash(package)

    with pytest.raises(ContractError, match="assertion"):
        validate_package(package)


def test_negative_and_unproved_evidence_states_are_preserved() -> None:
    package = validate_package(_package())
    states = {item["evidenceClass"]: item["state"] for item in package["evidenceClasses"]}

    assert set(states) == set(EVIDENCE_CLASSES)
    assert {
        "absent",
        "partial",
        "complete",
        "unavailable",
        "unproved",
    } <= set(states.values())
    assert set(package["knownLimitations"]) == REQUIRED_LIMITATIONS
    assert set(package["unresolvedGates"]) == set(UNRESOLVED_GATES)


def test_local_evidence_cannot_claim_azure_completion() -> None:
    package = _package()
    azure = next(
        item
        for item in package["evidenceClasses"]
        if item["evidenceClass"] == "azure-execution-evidence"
    )
    azure["state"] = "complete"
    _rehash(package)

    with pytest.raises(ContractError, match="stronger evidence"):
        validate_package(package)


def test_generated_fixture_cannot_claim_provider_observation() -> None:
    package = _package()
    provider = next(
        item
        for item in package["evidenceClasses"]
        if item["evidenceClass"] == "external-provider-evidence"
    )
    provider["state"] = "complete"
    provider["sourceKind"] = "generated-fixture"
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


def test_unsigned_package_cannot_be_misclassified_as_signed() -> None:
    package = _package()
    package["signature"]["status"] = "signed"
    package["signature"]["verified"] = True
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


def test_local_retention_cannot_be_misclassified_as_independent() -> None:
    package = _package()
    package["retention"]["independentlyProtected"] = True
    _rehash(package)

    with pytest.raises(ContractError):
        validate_package(package)


@pytest.mark.parametrize(
    "value",
    [
        "password=do-not-store",
        "Authorization: Bearer opaque",
        "AccountKey=opaque",
        "https://host.invalid/x?sig=opaque",
        "eyJaaaaaaaaaaa.bbbbbbbbbbb.ccccccccccc",
        "/subscriptions/00000000-0000-0000-0000-000000000000/x",
        "C:\\Users\\private\\fixture",
    ],
)
def test_secret_and_private_identifier_text_is_rejected(value: str) -> None:
    package = _package()
    package["packageId"] = value
    for artifact in package["artifacts"]:
        artifact["packageId"] = value

    with pytest.raises(ContractError):
        _rehash(package)
        validate_package(package)


def test_checkpoint2_manifest_tampering_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    manifest_path = tmp_path.joinpath(*MANIFEST_NAME.split("/"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["seed"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = _package()
    _rebind_file(package, tmp_path, MANIFEST_NAME)

    with pytest.raises(ContractError):
        validate_package(package, artifact_root=tmp_path)


def test_checkpoint2_plan_tampering_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    plan_path = tmp_path.joinpath(*PLAN_NAME.split("/"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["events"][0]["syntheticRequestBytes"] += 1
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    package = _package()
    _rebind_file(package, tmp_path, PLAN_NAME)

    with pytest.raises(ContractError):
        validate_package(package, artifact_root=tmp_path)


def test_checkpoint2_result_tampering_is_rejected(tmp_path: Path) -> None:
    _copy_artifacts(tmp_path)
    result_path = tmp_path.joinpath(*RESULT_NAME.split("/"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["aggregate"]["requestCount"] += 1
    result_path.write_text(json.dumps(result), encoding="utf-8")
    package = _package()
    _rebind_file(package, tmp_path, RESULT_NAME)

    with pytest.raises(ContractError):
        validate_package(package, artifact_root=tmp_path)


def test_tampered_package_integrity_is_rejected() -> None:
    package = _package()
    package["packageIntegritySha256"] = "0" * 64

    with pytest.raises(ContractError, match="integrity"):
        validate_package(package)


def test_verifier_output_is_deterministic_bounded_and_safe() -> None:
    first = verify_package(PACKAGE_PATH, artifact_root=REPOSITORY_ROOT)
    second = verify_package(PACKAGE_PATH, artifact_root=REPOSITORY_ROOT)
    encoded = report_bytes(first)

    assert first == second
    assert first["status"] == "valid"
    assert first["syntheticLocalOnly"] is True
    assert first["networkAccess"] is False
    assert first["destructive"] is False
    assert len(encoded) <= MAX_VERIFIER_OUTPUT_BYTES
    assert str(REPOSITORY_ROOT) not in encoded.decode()


def test_invalid_verifier_output_does_not_expose_error_details(tmp_path: Path) -> None:
    missing = tmp_path / "missing-package.json"
    report = verify_package(missing, artifact_root=REPOSITORY_ROOT)

    assert report["status"] == "invalid"
    assert report["errorCode"] == "package-verification-failed"
    assert str(missing) not in canonical_bytes(report).decode()


def test_replacement_requires_prior_hash_reason_and_preservation() -> None:
    package = _package()
    package["replacement"] = {
        "kind": "replacement",
        "supersedesPackageSha256": "1" * 64,
        "reasonCode": "corrected-failed-validation",
        "priorStatePreserved": True,
    }
    _rehash(package)

    assert validate_package(package)["replacement"]["kind"] == "replacement"

    package["replacement"]["priorStatePreserved"] = False
    _rehash(package)
    with pytest.raises(ContractError):
        validate_package(package)


def test_framework_has_no_network_process_or_provider_client_imports() -> None:
    source = (REPOSITORY_ROOT / "evidence" / "milestone_7_7" / "framework.py").read_text(
        encoding="utf-8"
    )
    verify_source = (REPOSITORY_ROOT / "evidence" / "milestone_7_7" / "verify.py").read_text(
        encoding="utf-8"
    )

    for prohibited in (
        "import socket",
        "import subprocess",
        "import requests",
        "import httpx",
        "import urllib",
        "azure.identity",
        "azure.mgmt",
    ):
        assert prohibited not in source
        assert prohibited not in verify_source
