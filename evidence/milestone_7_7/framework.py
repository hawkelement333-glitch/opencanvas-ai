"""Bounded local evidence packages for Milestone 7.7.

The framework is deliberately network-incapable. It binds committed Checkpoint
2 artifacts, validates local files, and emits bounded deterministic reports.
It does not collect provider evidence, sign artifacts, or publish evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Final, Literal, cast

from performance.milestone_7_7.framework import (
    ContractError as ContractError,
    JsonValue,
    canonical_bytes,
    generate_plan,
    integrity_sha256,
    load_json,
    validate_manifest,
    validate_result,
    validate_schema,
)

ROOT: Final = Path(__file__).resolve().parent
SCHEMA_PATH: Final = ROOT / "evidence-package.schema.json"

PACKAGE_DOMAIN: Final = b"mobius.m7.7.evidence-package.v1\0"
VERIFIER_VERSION: Final = "mobius.m7.7.evidence-verifier.v1"
PACKAGE_VERSION: Final = "mobius.m7.7.evidence-package.v1"
SCHEMA_VERSION: Final = "2020-12"

MAX_PACKAGE_BYTES: Final = 524_288
MAX_METADATA_BYTES: Final = 262_144
MAX_ARTIFACTS: Final = 32
MAX_ARTIFACT_BYTES: Final = 4_194_304
MAX_TOTAL_ARTIFACT_BYTES: Final = 16_777_216
MAX_IDENTIFIER_LENGTH: Final = 128
MAX_LOGICAL_NAME_LENGTH: Final = 240
MAX_PATH_DEPTH: Final = 12
MAX_LABELS: Final = 8
MAX_VALIDATION_EVENTS: Final = 64
MAX_ASSERTIONS: Final = 64
MAX_LIMITATIONS: Final = 32
MAX_VERIFIER_OUTPUT_BYTES: Final = 65_536

SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
IDENTIFIER_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
LOGICAL_NAME_RE: Final = re.compile(r"[a-zA-Z0-9._/-]+")
SENSITIVE_TEXT_PATTERNS: Final = (
    re.compile(r"(?i)\b(?:password|passwd|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]"),
    re.compile(r"(?i)\b(?:authorization|cookie|set-cookie)\s*:"),
    re.compile(r"(?i)\b(?:accountkey|sharedaccesssignature)\s*="),
    re.compile(r"(?i)[?&](?:sig|se|sp|sv|spr|srt|ss)="),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)/subscriptions/[0-9a-f-]+/"),
    re.compile(r"(?i)\b(?:tenant|subscription|object)[_-]?id\s*[:=]"),
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\"),
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
)
PROHIBITED_FIELD_NAMES: Final = {
    "password",
    "credential",
    "credentials",
    "apiKey",
    "accessToken",
    "refreshToken",
    "authorization",
    "cookie",
    "connectionString",
    "privateKey",
    "signedUrl",
    "requestBody",
    "responseBody",
    "productionUserContent",
    "azureResourceId",
    "tenantId",
    "subscriptionId",
    "privateIdentifier",
    "localPath",
}

EVIDENCE_CLASSES: Final = (
    "local-deterministic-validation",
    "synthetic-workload-evidence",
    "infrastructure-definition-evidence",
    "external-provider-evidence",
    "azure-execution-evidence",
    "observability-evidence",
    "alert-delivery-evidence",
    "capacity-evidence",
    "resilience-evidence",
    "security-evidence",
    "cleanup-evidence",
)
EVIDENCE_STATES: Final = (
    "absent",
    "pending",
    "partial",
    "complete",
    "invalid",
    "blocked",
    "unavailable",
    "skipped",
    "failed",
    "unproved",
)
VALIDATION_STATES: Final = (
    "pending",
    "valid",
    "invalid",
    "blocked",
    "unavailable",
    "skipped",
    "failed",
    "unproved",
)
PACKAGE_STATES: Final = (
    "absent",
    "pending",
    "partial",
    "complete",
    "invalid",
    "blocked",
    "unavailable",
    "skipped",
    "failed",
    "unproved",
)
SOURCE_KINDS: Final = (
    "generated-fixture",
    "local-observation",
    "repository-definition",
    "provider-observation",
    "external-delivery",
)
ARTIFACT_ROLES: Final = (
    "workload-manifest",
    "request-plan",
    "measurement-result",
)
REQUIRED_ARTIFACT_ROLES: Final = frozenset(ARTIFACT_ROLES)
REQUIRED_VALIDATIONS: Final = frozenset(
    {
        "schema-validation",
        "checkpoint2-binding",
        "artifact-integrity",
        "classification-validation",
        "privacy-structure-scan",
        "package-integrity",
    }
)
STRONG_EVIDENCE_CLASSES: Final = frozenset(
    {
        "external-provider-evidence",
        "azure-execution-evidence",
        "observability-evidence",
        "alert-delivery-evidence",
        "capacity-evidence",
        "resilience-evidence",
        "cleanup-evidence",
    }
)
REQUIRED_LIMITATIONS: Final = frozenset(
    {
        "local-synthetic-only",
        "no-azure-execution",
        "no-provider-observation",
        "no-external-retention",
        "unsigned",
        "unresolved-infrastructure-gates",
        "no-production-capacity-claim",
        "no-live-failure-injection",
        "schema-subset-validator-only",
    }
)
UNRESOLVED_GATES: Final = (
    "region-and-subscription-availability",
    "exact-provider-api-versions",
    "managed-identity-environment-mapping",
    "redis-custom-acl-support",
    "private-acr-source-path",
    "telemetry-gateway",
    "scanner-result-bridge",
    "alert-destination",
    "openai-smtp-test-providers",
    "evidence-retention",
)

VerifierStatus = Literal["valid", "invalid"]


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


def _as_int(value: JsonValue, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError(f"{location}: expected an integer")
    return value


def _sha256_file(path: Path) -> tuple[int, str]:
    size = path.stat().st_size
    if size > MAX_ARTIFACT_BYTES:
        raise ContractError("artifact exceeds the individual size ceiling")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(65_536):
            digest.update(block)
    return size, digest.hexdigest()


def _walk_sensitive(value: JsonValue, location: str = "$") -> None:
    if isinstance(value, str):
        for pattern in SENSITIVE_TEXT_PATTERNS:
            if pattern.search(value):
                raise ContractError(f"{location}: prohibited sensitive text")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_sensitive(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PROHIBITED_FIELD_NAMES:
                raise ContractError(f"{location}: prohibited sensitive field {key}")
            _walk_sensitive(item, f"{location}.{key}")


def _validate_identifier(value: str, location: str) -> None:
    if len(value) > MAX_IDENTIFIER_LENGTH or IDENTIFIER_RE.fullmatch(value) is None:
        raise ContractError(f"{location}: identifier is outside the safe closed form")


def _normalize_logical_name(value: str) -> str:
    if (
        not value
        or len(value) > MAX_LOGICAL_NAME_LENGTH
        or "\\" in value
        or ":" in value
        or "?" in value
        or "#" in value
        or "\0" in value
        or LOGICAL_NAME_RE.fullmatch(value) is None
    ):
        raise ContractError("artifact logical name is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError("artifact logical name is absolute or traverses")
    if len(path.parts) > MAX_PATH_DEPTH:
        raise ContractError("artifact logical name exceeds the path-depth ceiling")
    normalized = path.as_posix()
    if normalized != value:
        raise ContractError("artifact logical name is ambiguously normalized")
    return normalized


def _safe_artifact_path(root: Path, logical_name: str) -> Path:
    normalized = _normalize_logical_name(logical_name)
    resolved_root = root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    current = resolved_root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise ContractError("artifact path contains a symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ContractError("artifact resolves outside the approved root") from exc
    if not resolved.is_file():
        raise ContractError("artifact is not a regular file")
    return resolved


def _normalized_semantic_package(
    value: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    body = {
        key: deepcopy(item)
        for key, item in value.items()
        if key != "packageIntegritySha256"
    }
    sortable_fields = {
        "artifacts": "logicalName",
        "evidenceClasses": "evidenceClass",
        "validationEvents": "validationId",
        "knownLimitations": None,
        "unresolvedGates": None,
    }
    for field, key in sortable_fields.items():
        raw = body.get(field)
        if not isinstance(raw, list):
            continue
        if key is None:
            body[field] = cast(JsonValue, sorted(raw, key=lambda item: str(item)))
        else:
            body[field] = cast(
                JsonValue,
                sorted(
                    raw,
                    key=lambda item: (
                        str(item.get(key, "")) if isinstance(item, dict) else ""
                    ),
                ),
            )
    bindings = body.get("checkpoint2Bindings")
    if isinstance(bindings, dict) and isinstance(bindings.get("assertions"), list):
        normalized_bindings = deepcopy(bindings)
        assertions = cast(list[JsonValue], normalized_bindings["assertions"])
        normalized_bindings["assertions"] = sorted(
            assertions,
            key=lambda item: (
                str(item.get("assertionId", "")) if isinstance(item, dict) else ""
            ),
        )
        body["checkpoint2Bindings"] = normalized_bindings
    return body


def package_integrity_sha256(value: Mapping[str, JsonValue]) -> str:
    """Hash normalized semantic content; unordered registries are sorted first."""

    return integrity_sha256(_normalized_semantic_package(value), PACKAGE_DOMAIN)


def _validate_artifacts(
    package: Mapping[str, JsonValue],
    *,
    artifact_root: Path | None,
) -> dict[str, Path]:
    package_id = _as_str(package["packageId"], "packageId")
    artifacts = _as_list(package["artifacts"], "artifacts")
    if not 1 <= len(artifacts) <= MAX_ARTIFACTS:
        raise ContractError("artifact inventory count is outside the bounded contract")
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    total_size = 0
    resolved_by_role: dict[str, Path] = {}
    for index, raw in enumerate(artifacts):
        item = _as_dict(raw, f"artifacts[{index}]")
        if item["packageId"] != package_id:
            raise ContractError("artifact is bound to another evidence package")
        artifact_id = _as_str(item["artifactId"], f"artifacts[{index}].artifactId")
        _validate_identifier(artifact_id, f"artifacts[{index}].artifactId")
        if artifact_id in seen_ids:
            raise ContractError(
                "artifact inventory contains a duplicate artifact identity"
            )
        seen_ids.add(artifact_id)
        logical_name = _normalize_logical_name(
            _as_str(item["logicalName"], f"artifacts[{index}].logicalName")
        )
        normalized_key = logical_name.casefold()
        if normalized_key in seen_names:
            raise ContractError(
                "artifact inventory contains a duplicate normalized name"
            )
        seen_names.add(normalized_key)
        role = _as_str(item["role"], f"artifacts[{index}].role")
        if role not in ARTIFACT_ROLES or role in seen_roles:
            raise ContractError(
                "artifact inventory contains a duplicate or unexpected role"
            )
        seen_roles.add(role)
        size = _as_int(item["sizeBytes"], f"artifacts[{index}].sizeBytes")
        if size < 1 or size > MAX_ARTIFACT_BYTES:
            raise ContractError("artifact size is outside the individual ceiling")
        total_size += size
        if total_size > MAX_TOTAL_ARTIFACT_BYTES:
            raise ContractError("artifact inventory exceeds the total-size ceiling")
        if (
            SHA256_RE.fullmatch(
                _as_str(item["contentSha256"], f"artifacts[{index}].contentSha256")
            )
            is None
        ):
            raise ContractError("artifact content hash is malformed")
        if artifact_root is not None:
            path = _safe_artifact_path(artifact_root, logical_name)
            actual_size, actual_hash = _sha256_file(path)
            if actual_size != size:
                raise ContractError("artifact size does not match the inventory")
            if actual_hash != item["contentSha256"]:
                raise ContractError(
                    "artifact content hash does not match the inventory"
                )
            resolved_by_role[role] = path
    if seen_roles != REQUIRED_ARTIFACT_ROLES:
        raise ContractError("artifact inventory is incomplete")
    return resolved_by_role


def _validate_checkpoint2_bindings(
    package: Mapping[str, JsonValue],
    paths: Mapping[str, Path],
) -> None:
    bindings = _as_dict(package["checkpoint2Bindings"], "checkpoint2Bindings")
    assertion_rows = _as_list(bindings["assertions"], "checkpoint2Bindings.assertions")
    if len(assertion_rows) > MAX_ASSERTIONS:
        raise ContractError("assertion count exceeds the ceiling")
    assertion_ids = [
        _as_str(_as_dict(item, "assertion")["assertionId"], "assertion.assertionId")
        for item in assertion_rows
    ]
    if assertion_ids != sorted(set(assertion_ids)):
        raise ContractError("assertion definitions must be unique and sorted")
    workload = _as_dict(bindings["workloadManifest"], "workloadManifest")
    plan_binding = _as_dict(bindings["requestPlan"], "requestPlan")
    result_binding = _as_dict(bindings["measurementResult"], "measurementResult")
    artifacts = {
        _as_str(_as_dict(item, "artifact")["role"], "artifact.role"): _as_dict(
            item, "artifact"
        )
        for item in _as_list(package["artifacts"], "artifacts")
    }
    for role, binding in (
        ("workload-manifest", workload),
        ("request-plan", plan_binding),
        ("measurement-result", result_binding),
    ):
        if artifacts[role]["semanticIntegritySha256"] != binding["integritySha256"]:
            raise ContractError(
                "artifact semantic hash differs from its source binding"
            )
    if not paths:
        return
    manifest = validate_manifest(load_json(paths["workload-manifest"]))
    expected_plan = generate_plan(manifest)
    plan = load_json(paths["request-plan"])
    if canonical_bytes(plan) != canonical_bytes(expected_plan):
        raise ContractError(
            "request-plan artifact differs from Checkpoint 2 generation"
        )
    result = validate_result(load_json(paths["measurement-result"]))
    if (
        workload["contractVersion"] != manifest["contractVersion"]
        or workload["workloadId"] != manifest["workloadId"]
        or workload["integritySha256"] != expected_plan["manifestSha256"]
    ):
        raise ContractError("workload-manifest binding does not match Checkpoint 2")
    if (
        plan_binding["contractVersion"] != expected_plan["contractVersion"]
        or plan_binding["workloadId"] != expected_plan["workloadId"]
        or plan_binding["integritySha256"] != expected_plan["planSha256"]
    ):
        raise ContractError("request-plan binding does not match Checkpoint 2")
    if (
        result_binding["contractVersion"] != result["contractVersion"]
        or result_binding["workloadId"] != result["workloadId"]
        or result_binding["integritySha256"] != result["integritySha256"]
    ):
        raise ContractError("measurement-result binding does not match Checkpoint 2")
    if bindings["generatorVersion"] != result["generatorVersion"]:
        raise ContractError("generator binding differs from Checkpoint 2")
    if canonical_bytes(bindings["measurementConfiguration"]) != canonical_bytes(
        result["measurementConfiguration"]
    ):
        raise ContractError("measurement configuration differs from Checkpoint 2")
    if canonical_bytes(assertion_rows) != canonical_bytes(result["assertions"]):
        raise ContractError("assertion outcomes differ from Checkpoint 2")
    execution = _as_dict(package["executionWindow"], "executionWindow")
    run_metadata = _as_dict(result["runMetadata"], "runMetadata")
    if (
        execution["startedAtLogicalUs"] != run_metadata["startedAtLogicalUs"]
        or execution["endedAtLogicalUs"] != run_metadata["endedAtLogicalUs"]
        or package["stopReason"] != result["stopReason"]
    ):
        raise ContractError("execution or stop metadata differs from Checkpoint 2")


def _validate_claims(package: Mapping[str, JsonValue]) -> None:
    environment = _as_str(package["environmentClass"], "environmentClass")
    execution = _as_str(package["executionClass"], "executionClass")
    claim = _as_str(package["claimStrength"], "claimStrength")
    if environment != "synthetic-local":
        raise ContractError("Checkpoint 3 accepts only synthetic-local packages")
    if execution != "local-deterministic-validation":
        raise ContractError(
            "local evidence cannot claim managed or production execution"
        )
    if claim != "local-contract-validation-only":
        raise ContractError("local evidence cannot claim stronger evidence")

    rows = _as_list(package["evidenceClasses"], "evidenceClasses")
    classes: set[str] = set()
    required_classes: set[str] = set()
    for index, raw in enumerate(rows):
        item = _as_dict(raw, f"evidenceClasses[{index}]")
        evidence_class = _as_str(item["evidenceClass"], "evidenceClass")
        state = _as_str(item["state"], "state")
        source_kind = _as_str(item["sourceKind"], "sourceKind")
        if evidence_class not in EVIDENCE_CLASSES or evidence_class in classes:
            raise ContractError("evidence classes must be complete and unique")
        if state not in EVIDENCE_STATES or source_kind not in SOURCE_KINDS:
            raise ContractError("evidence class uses an unsupported closed value")
        classes.add(evidence_class)
        if item["requiredForPackage"] is True:
            required_classes.add(evidence_class)
            if state != "complete":
                raise ContractError("required package evidence is not complete")
        if evidence_class in STRONG_EVIDENCE_CLASSES and state == "complete":
            raise ContractError(
                "local synthetic output cannot complete stronger evidence"
            )
        if source_kind in {"provider-observation", "external-delivery"}:
            raise ContractError(
                "provider or external-delivery evidence is unavailable locally"
            )
        if source_kind == "generated-fixture" and evidence_class not in {
            "synthetic-workload-evidence"
        }:
            raise ContractError("generated fixtures cannot represent observed evidence")
    if classes != set(EVIDENCE_CLASSES):
        raise ContractError("the closed evidence-class registry is incomplete")
    if required_classes != {
        "local-deterministic-validation",
        "synthetic-workload-evidence",
    }:
        raise ContractError(
            "local package requirements differ from the closed contract"
        )

    validation_rows = _as_list(package["validationEvents"], "validationEvents")
    if len(validation_rows) > MAX_VALIDATION_EVENTS:
        raise ContractError("validation-event count exceeds the ceiling")
    validation_ids: set[str] = set()
    for raw in validation_rows:
        item = _as_dict(raw, "validationEvent")
        validation_id = _as_str(item["validationId"], "validationId")
        state = _as_str(item["state"], "validation state")
        _validate_identifier(validation_id, "validationId")
        if validation_id in validation_ids:
            raise ContractError("validation events must be unique")
        validation_ids.add(validation_id)
        if state not in EVIDENCE_STATES:
            raise ContractError("validation event uses an unsupported state")
    if validation_ids != REQUIRED_VALIDATIONS:
        raise ContractError(
            "validation-event registry is missing or contains an unknown check"
        )

    package_state = _as_str(
        _as_dict(package["completeness"], "completeness")["packageState"],
        "completeness.packageState",
    )
    milestone_state = _as_str(
        _as_dict(package["completeness"], "completeness")["milestoneState"],
        "completeness.milestoneState",
    )
    validation_state = _as_str(package["validationState"], "validationState")
    states = {
        _as_str(
            _as_dict(item, "validation event")["validationId"], "validationId"
        ): _as_str(_as_dict(item, "validation event")["state"], "state")
        for item in validation_rows
    }
    required_complete = all(
        states.get(item) == "complete" for item in REQUIRED_VALIDATIONS
    )
    if package_state == "complete" and not required_complete:
        raise ContractError(
            "package is complete while required validation is incomplete"
        )
    if package_state == "complete" and validation_state != "valid":
        raise ContractError("complete package must have valid validation state")
    assertions = _as_list(
        _as_dict(package["checkpoint2Bindings"], "checkpoint2Bindings")["assertions"],
        "checkpoint2Bindings.assertions",
    )
    if package_state == "complete" and (
        package["stopReason"] != "completed"
        or any(_as_dict(item, "assertion")["passed"] is not True for item in assertions)
    ):
        raise ContractError(
            "complete package contains a failed or unverified assertion"
        )
    if milestone_state == "complete":
        raise ContractError(
            "local synthetic package cannot complete Milestone 7.7 evidence"
        )
    if package_state not in PACKAGE_STATES or milestone_state not in PACKAGE_STATES:
        raise ContractError("completeness uses an unsupported state")
    if validation_state not in VALIDATION_STATES:
        raise ContractError("validation uses an unsupported state")


def _validate_boundaries(package: Mapping[str, JsonValue]) -> None:
    labels = _as_dict(package["labels"], "labels")
    if len(labels) > MAX_LABELS:
        raise ContractError("label count exceeds the ceiling")
    if labels != {
        "checkpoint": "milestone-7.7-checkpoint-3",
        "claim": "local-contract-validation-only",
        "dataClass": "isolated-synthetic",
        "environment": "synthetic-local",
        "execution": "local-deterministic-validation",
    }:
        raise ContractError("labels differ from the bounded closed registry")
    limitations = _as_list(package["knownLimitations"], "knownLimitations")
    if len(limitations) > MAX_LIMITATIONS:
        raise ContractError("limitation count exceeds the ceiling")
    limitation_values = {_as_str(item, "known limitation") for item in limitations}
    if limitation_values != REQUIRED_LIMITATIONS:
        raise ContractError("known limitations are missing, duplicated, or unsupported")
    gates = tuple(
        _as_str(item, "unresolved gate")
        for item in _as_list(package["unresolvedGates"], "unresolvedGates")
    )
    if set(gates) != set(UNRESOLVED_GATES) or len(gates) != len(UNRESOLVED_GATES):
        raise ContractError("unresolved infrastructure gates differ")
    signature = _as_dict(package["signature"], "signature")
    if signature != {
        "status": "unsigned",
        "scheme": "none",
        "signerClass": "none",
        "keyReference": None,
        "signatureValue": None,
        "verified": False,
    }:
        raise ContractError("Checkpoint 3 package must remain explicitly unsigned")
    retention = _as_dict(package["retention"], "retention")
    if (
        retention["status"] != "local-only"
        or retention["independentlyProtected"] is not False
        or retention["immutableProviderStorage"] is not False
        or retention["legalHold"] is not False
        or retention["externalReference"] is not None
    ):
        raise ContractError(
            "local retention cannot claim independent provider guarantees"
        )
    replacement = _as_dict(package["replacement"], "replacement")
    if replacement["kind"] == "original":
        if (
            replacement["supersedesPackageSha256"] is not None
            or replacement["reasonCode"] is not None
            or replacement["priorStatePreserved"] is not False
        ):
            raise ContractError("original package contains replacement claims")
    else:
        if (
            not isinstance(replacement["supersedesPackageSha256"], str)
            or SHA256_RE.fullmatch(replacement["supersedesPackageSha256"]) is None
            or replacement["reasonCode"] is None
            or replacement["priorStatePreserved"] is not True
        ):
            raise ContractError("replacement does not preserve and bind prior evidence")


def validate_package(
    value: JsonValue,
    *,
    artifact_root: Path | None = None,
) -> dict[str, JsonValue]:
    """Validate schema, claims, package bounds, bindings, and optional files."""

    if len(canonical_bytes(value)) > MAX_PACKAGE_BYTES:
        raise ContractError("evidence package exceeds the canonical package ceiling")
    if len(canonical_bytes(value)) > MAX_METADATA_BYTES:
        raise ContractError("evidence package metadata exceeds the metadata ceiling")
    package = _as_dict(value, "$")
    schema = _as_dict(load_json(SCHEMA_PATH), "evidence-package schema")
    validate_schema(package, schema)
    _walk_sensitive(package)
    if package["packageVersion"] != PACKAGE_VERSION:
        raise ContractError("unsupported evidence package version")
    if package["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("unsupported evidence schema version")
    _validate_identifier(_as_str(package["packageId"], "packageId"), "packageId")
    source = _as_dict(package["source"], "source")
    if source["repositoryId"] != "solarplexus-mobius":
        raise ContractError("source repository identity is unsupported")
    if COMMIT_RE.fullmatch(_as_str(source["commitSha"], "source.commitSha")) is None:
        raise ContractError("source commit SHA is malformed")
    if source["dirty"] is not False:
        raise ContractError("evidence source must identify a clean committed state")
    execution = _as_dict(package["executionWindow"], "executionWindow")
    if _as_int(
        execution["endedAtLogicalUs"], "executionWindow.endedAtLogicalUs"
    ) < _as_int(execution["startedAtLogicalUs"], "executionWindow.startedAtLogicalUs"):
        raise ContractError("execution window ends before it starts")
    paths = _validate_artifacts(package, artifact_root=artifact_root)
    _validate_checkpoint2_bindings(package, paths)
    _validate_claims(package)
    _validate_boundaries(package)
    expected_hash = package_integrity_sha256(package)
    if package["packageIntegritySha256"] != expected_hash:
        raise ContractError("evidence package integrity hash does not match")
    return deepcopy(package)


def _artifact_record(
    *,
    package_id: str,
    artifact_root: Path,
    logical_name: str,
    role: str,
    semantic_hash: str,
) -> dict[str, JsonValue]:
    path = _safe_artifact_path(artifact_root, logical_name)
    size, content_hash = _sha256_file(path)
    return {
        "packageId": package_id,
        "artifactId": f"artifact-{role}",
        "logicalName": logical_name,
        "role": role,
        "mediaType": "application/json",
        "sizeBytes": size,
        "contentSha256": content_hash,
        "semanticIntegritySha256": semantic_hash,
    }


def build_local_package(
    *,
    artifact_root: Path,
    source_commit: str,
    manifest_name: str,
    plan_name: str,
    result_name: str,
    package_id: str = "m7.7-cp3-local-fixture",
) -> dict[str, JsonValue]:
    """Build one deterministic unsigned local package from Checkpoint 2 artifacts."""

    if COMMIT_RE.fullmatch(source_commit) is None:
        raise ContractError("source commit SHA is malformed")
    _validate_identifier(package_id, "packageId")
    manifest_path = _safe_artifact_path(artifact_root, manifest_name)
    plan_path = _safe_artifact_path(artifact_root, plan_name)
    result_path = _safe_artifact_path(artifact_root, result_name)
    manifest = validate_manifest(load_json(manifest_path))
    expected_plan = generate_plan(manifest)
    plan = load_json(plan_path)
    if canonical_bytes(plan) != canonical_bytes(expected_plan):
        raise ContractError(
            "request-plan artifact differs from Checkpoint 2 generation"
        )
    result = validate_result(load_json(result_path))
    if (
        result["manifestSha256"] != expected_plan["manifestSha256"]
        or result["planSha256"] != expected_plan["planSha256"]
    ):
        raise ContractError(
            "measurement result is not bound to the supplied manifest and plan"
        )
    evidence_states = {
        "local-deterministic-validation": ("complete", "local-observation", True),
        "synthetic-workload-evidence": ("complete", "generated-fixture", True),
        "infrastructure-definition-evidence": (
            "unproved",
            "repository-definition",
            False,
        ),
        "external-provider-evidence": ("unavailable", "local-observation", False),
        "azure-execution-evidence": ("absent", "local-observation", False),
        "observability-evidence": ("unproved", "local-observation", False),
        "alert-delivery-evidence": ("unavailable", "local-observation", False),
        "capacity-evidence": ("unproved", "local-observation", False),
        "resilience-evidence": ("unproved", "local-observation", False),
        "security-evidence": ("partial", "local-observation", False),
        "cleanup-evidence": ("unproved", "local-observation", False),
    }
    package: dict[str, JsonValue] = {
        "schemaVersion": SCHEMA_VERSION,
        "packageVersion": PACKAGE_VERSION,
        "packageId": package_id,
        "purpose": "milestone-7.7-local-evidence-contract-validation",
        "checkpoint": "milestone-7.7-checkpoint-3",
        "source": {
            "repositoryId": "solarplexus-mobius",
            "commitSha": source_commit,
            "dirty": False,
        },
        "checkpoint2Bindings": {
            "workloadManifest": {
                "contractVersion": manifest["contractVersion"],
                "workloadId": manifest["workloadId"],
                "integritySha256": expected_plan["manifestSha256"],
            },
            "requestPlan": {
                "contractVersion": expected_plan["contractVersion"],
                "workloadId": expected_plan["workloadId"],
                "integritySha256": expected_plan["planSha256"],
            },
            "measurementResult": {
                "contractVersion": result["contractVersion"],
                "workloadId": result["workloadId"],
                "integritySha256": result["integritySha256"],
            },
            "generatorVersion": result["generatorVersion"],
            "measurementConfiguration": deepcopy(result["measurementConfiguration"]),
            "assertions": deepcopy(result["assertions"]),
        },
        "environmentClass": "synthetic-local",
        "executionClass": "local-deterministic-validation",
        "claimStrength": "local-contract-validation-only",
        "executionWindow": {
            "clock": "logical-monotonic-microseconds",
            "startedAtLogicalUs": _as_dict(result["runMetadata"], "runMetadata")[
                "startedAtLogicalUs"
            ],
            "endedAtLogicalUs": _as_dict(result["runMetadata"], "runMetadata")[
                "endedAtLogicalUs"
            ],
        },
        "artifacts": [
            _artifact_record(
                package_id=package_id,
                artifact_root=artifact_root,
                logical_name=manifest_name,
                role="workload-manifest",
                semantic_hash=_as_str(
                    expected_plan["manifestSha256"], "manifestSha256"
                ),
            ),
            _artifact_record(
                package_id=package_id,
                artifact_root=artifact_root,
                logical_name=plan_name,
                role="request-plan",
                semantic_hash=_as_str(expected_plan["planSha256"], "planSha256"),
            ),
            _artifact_record(
                package_id=package_id,
                artifact_root=artifact_root,
                logical_name=result_name,
                role="measurement-result",
                semantic_hash=_as_str(result["integritySha256"], "integritySha256"),
            ),
        ],
        "labels": {
            "checkpoint": "milestone-7.7-checkpoint-3",
            "claim": "local-contract-validation-only",
            "dataClass": "isolated-synthetic",
            "environment": "synthetic-local",
            "execution": "local-deterministic-validation",
        },
        "evidenceClasses": [
            {
                "evidenceClass": evidence_class,
                "state": state,
                "sourceKind": source_kind,
                "requiredForPackage": required,
            }
            for evidence_class, (state, source_kind, required) in sorted(
                evidence_states.items()
            )
        ],
        "validationEvents": [
            {"validationId": validation_id, "state": "complete"}
            for validation_id in sorted(REQUIRED_VALIDATIONS)
        ],
        "validationState": "valid",
        "completeness": {
            "packageState": "complete",
            "milestoneState": "partial",
        },
        "stopReason": result["stopReason"],
        "knownLimitations": cast(JsonValue, sorted(REQUIRED_LIMITATIONS)),
        "unresolvedGates": cast(JsonValue, sorted(UNRESOLVED_GATES)),
        "retention": {
            "policyVersion": "mobius.m7.7.retention-metadata.v1",
            "retentionClass": "local-repository-fixture",
            "status": "local-only",
            "independentlyProtected": False,
            "immutableProviderStorage": False,
            "legalHold": False,
            "externalReference": None,
            "deletionPolicy": "repository-lifecycle-only",
            "revalidationTrigger": "source-or-contract-change",
        },
        "signature": {
            "status": "unsigned",
            "scheme": "none",
            "signerClass": "none",
            "keyReference": None,
            "signatureValue": None,
            "verified": False,
        },
        "replacement": {
            "kind": "original",
            "supersedesPackageSha256": None,
            "reasonCode": None,
            "priorStatePreserved": False,
        },
        "verifierVersion": VERIFIER_VERSION,
        "packageIntegritySha256": "0" * 64,
    }
    package["packageIntegritySha256"] = package_integrity_sha256(package)
    return validate_package(package, artifact_root=artifact_root)


def _report(
    *,
    status: VerifierStatus,
    package: Mapping[str, JsonValue] | None,
    error_code: str | None,
) -> dict[str, JsonValue]:
    report: dict[str, JsonValue] = {
        "verifierVersion": VERIFIER_VERSION,
        "status": status,
        "syntheticLocalOnly": True,
        "networkAccess": False,
        "destructive": False,
        "packageId": package["packageId"] if package is not None else None,
        "packageIntegritySha256": (
            package["packageIntegritySha256"] if package is not None else None
        ),
        "packageState": (
            _as_dict(package["completeness"], "completeness")["packageState"]
            if package is not None
            else "invalid"
        ),
        "milestoneState": (
            _as_dict(package["completeness"], "completeness")["milestoneState"]
            if package is not None
            else "unproved"
        ),
        "errorCode": error_code,
    }
    if len(canonical_bytes(report)) > MAX_VERIFIER_OUTPUT_BYTES:
        raise ContractError("verifier output exceeds the bounded output ceiling")
    return report


def verify_package(package_path: Path, *, artifact_root: Path) -> dict[str, JsonValue]:
    """Return a bounded deterministic report without exposing unsafe details."""

    try:
        value = load_json(package_path)
        package = validate_package(value, artifact_root=artifact_root)
    except (ContractError, OSError):
        return _report(
            status="invalid", package=None, error_code="package-verification-failed"
        )
    return _report(status="valid", package=package, error_code=None)


def report_bytes(report: Mapping[str, JsonValue]) -> bytes:
    """Serialize a verified bounded report."""

    encoded = canonical_bytes(cast(JsonValue, dict(report)))
    if len(encoded) > MAX_VERIFIER_OUTPUT_BYTES:
        raise ContractError("verifier output exceeds the bounded output ceiling")
    return encoded
