"""Aggregate, network-incapable local validation for Milestone 7.7.

This module revalidates the public Checkpoint 1-4 contracts and emits one
bounded deterministic report. It cannot execute a workload or fault, spawn a
process, contact a service, provision infrastructure, or strengthen evidence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final, Literal, cast

from evidence.milestone_7_7.framework import (
    EVIDENCE_CLASSES,
    validate_package,
)
from infra.milestone_7_7.scripts.contract_validation import validate_bundle
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
from resilience.milestone_7_7.framework import (
    EXPECTED_EVIDENCE_STATES,
    REQUIRED_GATES,
    scenario_catalog_sha256,
    validate_plan,
)

ROOT: Final = Path(__file__).resolve().parent
REPOSITORY_ROOT: Final = ROOT.parents[1]
SCHEMA_PATH: Final = ROOT / "validation-report.schema.json"

REPORT_VERSION: Final = "mobius.m7.7.local-validation-report.v1"
REQUIREMENT_CATALOG_VERSION: Final = "mobius.m7.7.validation-requirements.v1"
VERIFIER_VERSION: Final = "mobius.m7.7.local-validation-verifier.v1"
SCHEMA_VERSION: Final = "2020-12"
REPORT_DOMAIN: Final = b"mobius.m7.7.local-validation-report.v1\0"
REQUIREMENT_CATALOG_DOMAIN: Final = b"mobius.m7.7.validation-requirements.v1\0"

SOURCE_COMMIT: Final = "c4fdab9ed46ae8d1b8ef380dae9a3812155097c5"
CHECKPOINT1_BUNDLE_SHA256: Final = (
    "e98c786a62659de316084963eadfc0ceca6688cb7749fe6951aa1d67b8e8b132"
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
CHECKPOINT4_PLAN_SHA256: Final = (
    "bc0132f8babe576656b9422d17a05cc21e674bf9f7b7418cd68d4915b2a049f3"
)
CHECKPOINT4_CATALOG_SHA256: Final = (
    "bf38c10982a5ed3e15fe27174f0b472b44fa0e44c23d9c62f1a2e68148fac8be"
)

MAX_REPORT_BYTES: Final = 262_144
MAX_VERIFIER_OUTPUT_BYTES: Final = 16_384
MAX_VALIDATION_CHECKS: Final = 16
MAX_REQUIREMENTS: Final = 16
MAX_LIMITATIONS: Final = 24

IDENTIFIER_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
SENSITIVE_VALUE_PATTERNS: Final = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}[.][A-Za-z0-9_-]{8,}[.]"),
    re.compile(r"(?:^|[?&])(?:sig|se|sp|sv|spr|srt|ss)=", re.IGNORECASE),
    re.compile(r"\b(?:AccountKey|SharedAccessSignature)=", re.IGNORECASE),
    re.compile(
        r"(?i)(?:[A-Z]:\\U"
        r"sers\\|/U"
        r"sers/|/ho"
        r"me/)[^/\s\\]+"
    ),
    re.compile(r"(?i)/subscriptions/[0-9a-f-]{36}(?:/resourceGroups/[^/\s]+)?"),
)
PROHIBITED_FIELD_NAMES: Final = frozenset(
    {
        "accessToken",
        "authorization",
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
        "productionContent",
        "productionData",
        "requestBody",
        "responseBody",
        "signedUrl",
        "subscriptionId",
        "targetResourceId",
        "tenantId",
        "token",
    }
)

VALIDATION_CHECK_IDS: Final = (
    "checkpoint-1-bundle-validation",
    "checkpoint-2-fixture-reproduction",
    "checkpoint-3-evidence-package-validation",
    "checkpoint-4-failure-plan-validation",
    "cross-checkpoint-binding-validation",
)

VALIDATION_REQUIREMENTS: Final = (
    "absolute-path-rejection",
    "bounded-output-rejection",
    "claim-strength-rejection",
    "compatibility-version-rejection",
    "completeness-rejection",
    "execution-authority-rejection",
    "invalid-input-rejection",
    "private-identifier-rejection",
    "schema-closure-rejection",
    "secret-material-rejection",
    "tamper-rejection",
    "traversal-rejection",
    "unknown-input-rejection",
)

REQUIRED_LIMITATIONS: Final = frozenset(
    {
        "all-external-gates-unresolved",
        "local-validation-only",
        "no-azure-execution",
        "no-external-retention",
        "no-live-failure-injection",
        "no-live-workload",
        "no-production-capacity-claim",
        "no-provider-observation",
        "no-real-cleanup-proof",
        "no-real-rollback-proof",
        "no-runtime-gate-resolution",
        "unsigned",
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


def _deepcopy_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _deepcopy_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deepcopy_json(item) for item in value]
    return value


def _walk_sensitive(value: JsonValue, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PROHIBITED_FIELD_NAMES:
                raise ContractError(f"{location}: prohibited field {key}")
            _walk_sensitive(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_sensitive(item, f"{location}[{index}]")
        return
    if isinstance(value, str):
        for pattern in SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise ContractError(f"{location}: sensitive value is prohibited")


def validation_requirement_catalog() -> dict[str, JsonValue]:
    """Return the closed rejection-path requirements for local validation."""

    return {
        "catalogVersion": REQUIREMENT_CATALOG_VERSION,
        "classification": "local-contract-requirements",
        "requirements": [
            {
                "id": requirement,
                "enforcement": "fail-closed",
                "evidenceBoundary": "focused-local-tests",
            }
            for requirement in VALIDATION_REQUIREMENTS
        ],
    }


def validation_requirement_catalog_sha256() -> str:
    return integrity_sha256(
        validation_requirement_catalog(),
        REQUIREMENT_CATALOG_DOMAIN,
    )


def _current_bindings() -> dict[str, str]:
    infrastructure_root = REPOSITORY_ROOT / "infra/milestone_7_7"
    infrastructure = validate_bundle(infrastructure_root)
    infrastructure_sha = infrastructure.get("bundleSha256")
    if not isinstance(infrastructure_sha, str):
        raise ContractError("Checkpoint 1 bundle validation omitted its hash")

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
    failure_path = (
        REPOSITORY_ROOT / "resilience/milestone_7_7/failure-plan.example.json"
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
    result_hash = _as_str(validated_result["integritySha256"], "result hash")

    evidence = validate_package(load_json(evidence_path), artifact_root=REPOSITORY_ROOT)
    evidence_hash = _as_str(
        evidence["packageIntegritySha256"],
        "evidence package hash",
    )
    failure = validate_plan(load_json(failure_path))
    failure_hash = _as_str(failure["planIntegritySha256"], "failure plan hash")

    return {
        "checkpoint1BundleSha256": infrastructure_sha,
        "checkpoint2ManifestSha256": manifest_sha256(manifest),
        "checkpoint2PlanSha256": _as_str(expected_plan["planSha256"], "plan hash"),
        "checkpoint2ResultSha256": result_hash,
        "checkpoint3PackageSha256": evidence_hash,
        "checkpoint4PlanSha256": failure_hash,
        "checkpoint4CatalogSha256": scenario_catalog_sha256(),
        "validationRequirementCatalogSha256": (validation_requirement_catalog_sha256()),
    }


EXPECTED_BINDINGS: Final = {
    "checkpoint1BundleSha256": CHECKPOINT1_BUNDLE_SHA256,
    "checkpoint2ManifestSha256": CHECKPOINT2_MANIFEST_SHA256,
    "checkpoint2PlanSha256": CHECKPOINT2_PLAN_SHA256,
    "checkpoint2ResultSha256": CHECKPOINT2_RESULT_SHA256,
    "checkpoint3PackageSha256": CHECKPOINT3_PACKAGE_SHA256,
    "checkpoint4PlanSha256": CHECKPOINT4_PLAN_SHA256,
    "checkpoint4CatalogSha256": CHECKPOINT4_CATALOG_SHA256,
    "validationRequirementCatalogSha256": validation_requirement_catalog_sha256(),
}


def _normalized_report(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    normalized = cast(dict[str, JsonValue], _deepcopy_json(value))
    normalized.pop("reportIntegritySha256", None)
    normalized["validationChecks"] = cast(
        JsonValue,
        sorted(
            (
                _as_dict(item, "validation check")
                for item in _as_list(
                    normalized["validationChecks"],
                    "validationChecks",
                )
            ),
            key=lambda item: _as_str(item["id"], "validation check id"),
        ),
    )
    normalized["validationRequirements"] = cast(
        JsonValue,
        sorted(
            _as_str(item, "validation requirement")
            for item in _as_list(
                normalized["validationRequirements"],
                "validationRequirements",
            )
        ),
    )
    normalized["gateStates"] = cast(
        JsonValue,
        sorted(
            (
                _as_dict(item, "gate state")
                for item in _as_list(normalized["gateStates"], "gateStates")
            ),
            key=lambda item: _as_str(item["id"], "gate id"),
        ),
    )
    normalized["evidenceStates"] = cast(
        JsonValue,
        sorted(
            (
                _as_dict(item, "evidence state")
                for item in _as_list(
                    normalized["evidenceStates"],
                    "evidenceStates",
                )
            ),
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


def report_integrity_sha256(value: dict[str, JsonValue]) -> str:
    """Hash normalized report content using the Checkpoint 5 domain."""

    return integrity_sha256(_normalized_report(value), REPORT_DOMAIN)


def build_local_report(
    report_id: str = "m7.7-cp5-local-validation",
) -> dict[str, JsonValue]:
    """Build the deterministic aggregate local-validation report."""

    if IDENTIFIER_RE.fullmatch(report_id) is None:
        raise ContractError("report identifier is malformed")
    current_bindings = _current_bindings()
    if current_bindings != EXPECTED_BINDINGS:
        raise ContractError("Checkpoint 1-4 bindings differ from protected values")
    report: dict[str, JsonValue] = {
        "schemaVersion": SCHEMA_VERSION,
        "contractVersion": REPORT_VERSION,
        "reportId": report_id,
        "purpose": "aggregate-local-validation",
        "source": {
            "repositoryId": "solarplexus-mobius",
            "commitSha": SOURCE_COMMIT,
            "dirty": False,
        },
        "bindings": cast(JsonValue, current_bindings),
        "classification": {
            "environment": "unprovisioned-local",
            "execution": "contract-validation-only",
            "claimStrength": "local-contract-validation-only",
        },
        "capabilities": {
            "network": False,
            "process": False,
            "faultExecution": False,
            "workloadExecution": False,
            "provisioning": False,
            "destructiveActions": False,
            "externalServices": False,
            "credentialUse": False,
        },
        "validationChecks": cast(
            JsonValue,
            [{"id": check_id, "status": "passed"} for check_id in VALIDATION_CHECK_IDS],
        ),
        "validationRequirements": cast(JsonValue, list(VALIDATION_REQUIREMENTS)),
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
            "localValidationState": "complete",
            "milestoneEvidenceState": "partial",
            "executionReadiness": "blocked",
            "nextCheckpoint": "azure-topology-preflight",
            "stopReason": "local-validation-complete",
        },
        "limitations": cast(JsonValue, sorted(REQUIRED_LIMITATIONS)),
        "verifierVersion": VERIFIER_VERSION,
        "reportIntegritySha256": "",
    }
    report["reportIntegritySha256"] = report_integrity_sha256(report)
    return validate_report(report)


def _validate_closed_items(
    values: JsonValue,
    *,
    expected: tuple[str, ...] | frozenset[str],
    location: str,
) -> None:
    items = [_as_str(item, location) for item in _as_list(values, location)]
    if len(items) != len(set(items)):
        raise ContractError(f"{location}: items must be unique")
    if set(items) != set(expected):
        raise ContractError(f"{location}: inventory differs from the closed contract")


def _validate_checks(report: dict[str, JsonValue]) -> None:
    checks: dict[str, str] = {}
    for item_value in _as_list(report["validationChecks"], "validationChecks"):
        item = _as_dict(item_value, "validation check")
        check_id = _as_str(item["id"], "validation check id")
        status = _as_str(item["status"], "validation check status")
        if check_id in checks:
            raise ContractError("validation check identifiers must be unique")
        checks[check_id] = status
    if set(checks) != set(VALIDATION_CHECK_IDS):
        raise ContractError("validation checks differ from the closed contract")
    if set(checks.values()) != {"passed"}:
        raise ContractError("aggregate local validation contains a failed check")


def _validate_gates(report: dict[str, JsonValue]) -> None:
    gates: dict[str, str] = {}
    for item_value in _as_list(report["gateStates"], "gateStates"):
        item = _as_dict(item_value, "gate state")
        gate_id = _as_str(item["id"], "gate id")
        state = _as_str(item["status"], "gate status")
        if gate_id in gates:
            raise ContractError("gate identifiers must be unique")
        gates[gate_id] = state
    if set(gates) != set(REQUIRED_GATES):
        raise ContractError("gate inventory differs from the required closed set")
    if set(gates.values()) != {"unresolved"}:
        raise ContractError("local validation cannot resolve an external gate")


def _validate_evidence(report: dict[str, JsonValue]) -> None:
    states: dict[str, str] = {}
    for item_value in _as_list(report["evidenceStates"], "evidenceStates"):
        item = _as_dict(item_value, "evidence state")
        evidence_class = _as_str(item["evidenceClass"], "evidence class")
        state = _as_str(item["state"], "evidence state")
        if evidence_class in states:
            raise ContractError("evidence classes must be unique")
        if evidence_class not in EVIDENCE_CLASSES:
            raise ContractError("evidence class is outside the Checkpoint 3 registry")
        states[evidence_class] = state
    if states != EXPECTED_EVIDENCE_STATES:
        raise ContractError("local validation evidence states are misclassified")


def validate_report(value: JsonValue) -> dict[str, JsonValue]:
    """Validate schema, bindings, claims, negative state, and integrity."""

    if len(canonical_bytes(value)) > MAX_REPORT_BYTES:
        raise ContractError("validation report exceeds the canonical size ceiling")
    report = _as_dict(value, "$")
    schema = _as_dict(load_json(SCHEMA_PATH), "validation-report schema")
    validate_schema(report, schema)
    _walk_sensitive(report)

    source = _as_dict(report["source"], "source")
    if COMMIT_RE.fullmatch(_as_str(source["commitSha"], "commit")) is None:
        raise ContractError("source commit is malformed")
    if source != {
        "repositoryId": "solarplexus-mobius",
        "commitSha": SOURCE_COMMIT,
        "dirty": False,
    }:
        raise ContractError("source identity differs from the protected boundary")

    bindings = _as_dict(report["bindings"], "bindings")
    current_bindings = _current_bindings()
    if bindings != current_bindings or bindings != EXPECTED_BINDINGS:
        raise ContractError("Checkpoint 1-4 bindings differ from current contracts")
    for binding in bindings.values():
        if not isinstance(binding, str) or SHA256_RE.fullmatch(binding) is None:
            raise ContractError("binding contains a malformed SHA-256 value")

    capabilities = _as_dict(report["capabilities"], "capabilities")
    if not capabilities or set(capabilities.values()) != {False}:
        raise ContractError("local validation cannot gain an execution capability")

    _validate_checks(report)
    _validate_closed_items(
        report["validationRequirements"],
        expected=VALIDATION_REQUIREMENTS,
        location="validationRequirements",
    )
    _validate_gates(report)
    _validate_evidence(report)
    _validate_closed_items(
        report["limitations"],
        expected=REQUIRED_LIMITATIONS,
        location="limitations",
    )

    expected_hash = report_integrity_sha256(report)
    if report["reportIntegritySha256"] != expected_hash:
        raise ContractError("validation report integrity hash does not match")
    return cast(dict[str, JsonValue], _deepcopy_json(report))


VerifierStatus = Literal["valid", "invalid"]


def _verification_result(
    *,
    status: VerifierStatus,
    report: dict[str, JsonValue] | None,
    error_code: str | None,
) -> dict[str, JsonValue]:
    return {
        "status": status,
        "errorCode": error_code,
        "reportId": None if report is None else report.get("reportId"),
        "reportIntegritySha256": (
            None if report is None else report.get("reportIntegritySha256")
        ),
        "validationCheckCount": 0 if report is None else len(VALIDATION_CHECK_IDS),
        "validationRequirementCount": (
            0 if report is None else len(VALIDATION_REQUIREMENTS)
        ),
        "classification": "local-validation-only",
        "localValidationState": ("invalid" if report is None else "complete"),
        "milestoneEvidenceState": "partial",
        "executionReadiness": "blocked",
        "networkAccess": False,
        "processExecution": False,
        "faultExecution": False,
        "destructive": False,
        "verifierVersion": VERIFIER_VERSION,
    }


def report_bytes(report: dict[str, JsonValue]) -> bytes:
    encoded = canonical_bytes(report)
    if len(encoded) > MAX_VERIFIER_OUTPUT_BYTES:
        raise ContractError("verifier output exceeds the hard ceiling")
    return encoded


def verify_report(path: Path) -> dict[str, JsonValue]:
    """Verify one report and return a bounded result without exception details."""

    try:
        report = validate_report(load_json(path))
    except (ContractError, OSError, UnicodeError):
        result = _verification_result(
            status="invalid",
            report=None,
            error_code="invalid-local-validation-report",
        )
    else:
        result = _verification_result(status="valid", report=report, error_code=None)
    report_bytes(result)
    return result
