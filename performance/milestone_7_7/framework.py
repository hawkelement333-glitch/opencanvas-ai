"""Bounded, deterministic workload and measurement contracts for Milestone 7.7.

This module is intentionally incapable of making network or application calls. It creates a
synthetic request plan and aggregates caller-supplied observations using logical time.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

ROOT = Path(__file__).resolve().parent
WORKLOAD_SCHEMA_PATH = ROOT / "workload.schema.json"
RESULT_SCHEMA_PATH = ROOT / "result.schema.json"
OPERATIONS_PATH = ROOT / "operations.json"

MANIFEST_DOMAIN = b"mobius.m7.7.workload-manifest.v1\0"
PLAN_DOMAIN = b"mobius.m7.7.workload-plan.v1\0"
RESULT_DOMAIN = b"mobius.m7.7.measurement-result.v1\0"
TOKEN_DOMAIN = b"mobius.m7.7.synthetic-token.v1\0"
GENERATOR_VERSION = "mobius.m7.7.generator.v1"

SUPPORTED_WORKLOAD_TYPES = (
    "baseline",
    "sustained",
    "spike",
    "bounded-stress",
    "bounded-soak",
    "mixed",
    "noisy-neighbor",
    "hostile-authorized-concurrency",
    "horizontal-scaling-preparation",
)
EXPECTED_PHASE_ORDER = ("warmup", "measurement", "cooldown")
EXPECTED_PERCENTILES = (5000, 9500, 9900)
OUTCOME_CLASSES = (
    "success",
    "rate-limited",
    "dependency-unavailable",
    "timeout",
    "client-error",
    "server-error",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\b"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Za-z]:\\Users\\[^\\\s]+\\"),
    re.compile("/" + r"Users/[^/\s]+/"),
    re.compile("/" + r"home/[^/\s]+/"),
)
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_OBSERVATIONS = 10_000

JsonScalar = str | int | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
Outcome = Literal[
    "success",
    "rate-limited",
    "dependency-unavailable",
    "timeout",
    "client-error",
    "server-error",
]


class ContractError(ValueError):
    """Raised when a workload or result fails closed-contract validation."""


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON value is prohibited: {value}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key is prohibited: {key}")
        result[key] = value
    return result


def loads_json(source: str) -> JsonValue:
    """Load strict JSON, rejecting duplicate keys, non-finite values, and floats."""

    try:
        value: Any = json.loads(
            source,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {exc.msg}") from exc
    _validate_json_value(value, "$")
    return cast(JsonValue, value)


def load_json(path: Path) -> JsonValue:
    return loads_json(path.read_text(encoding="utf-8"))


def _validate_json_value(value: Any, location: str) -> None:
    if isinstance(value, float):
        raise ContractError(f"{location}: floating-point values are prohibited")
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ContractError(f"{location}: integer exceeds the safe deterministic range")
        return
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if value != normalized:
            raise ContractError(f"{location}: strings must already be Unicode NFC")
        for pattern in (*SECRET_PATTERNS, *LOCAL_PATH_PATTERNS):
            if pattern.search(value):
                raise ContractError(
                    f"{location}: secret-bearing or private path text is prohibited"
                )
        return
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        normalized_keys: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{location}: object keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            if normalized in normalized_keys:
                raise ContractError(f"{location}: keys collide after Unicode normalization")
            if key != normalized:
                raise ContractError(f"{location}: object keys must already be Unicode NFC")
            normalized_keys.add(normalized)
            _validate_json_value(item, f"{location}.{key}")
        return
    raise ContractError(f"{location}: unsupported JSON value type {type(value).__name__}")


def canonical_bytes(value: JsonValue) -> bytes:
    """Return compact, key-sorted, NFC, newline-terminated UTF-8 JSON."""

    _validate_json_value(value, "$")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (encoded + "\n").encode("utf-8")


def integrity_sha256(value: JsonValue, domain: bytes) -> str:
    return hashlib.sha256(domain + canonical_bytes(value)).hexdigest()


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ContractError(f"schema uses unsupported type: {expected}")


def _resolve_ref(root_schema: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ContractError(f"external schema reference is prohibited: {reference}")
    current: Any = root_schema
    for part in reference[2:].split("/"):
        if not isinstance(current, dict) or part not in current:
            raise ContractError(f"unresolvable local schema reference: {reference}")
        current = current[part]
    if not isinstance(current, dict):
        raise ContractError(f"schema reference does not resolve to an object: {reference}")
    return current


def validate_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    root: Mapping[str, Any] | None = None,
    location: str = "$",
) -> None:
    """Validate the closed Draft 2020-12 subset used by this checkpoint."""

    root_schema = schema if root is None else root
    if "$ref" in schema:
        validate_schema(
            value,
            _resolve_ref(root_schema, str(schema["$ref"])),
            root=root_schema,
            location=location,
        )
        return
    expected_type = schema.get("type")
    if expected_type is not None:
        candidates = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_is_type(value, str(candidate)) for candidate in candidates):
            raise ContractError(f"{location}: value has the wrong type")
    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{location}: value differs from the closed contract")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{location}: value is outside the closed registry")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                raise ContractError(f"{location}: missing required field {name}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ContractError(f"{location}: unknown field {unknown[0]}")
        for name, item in value.items():
            child_schema = properties.get(name)
            if isinstance(child_schema, dict):
                validate_schema(
                    item,
                    child_schema,
                    root=root_schema,
                    location=f"{location}.{name}",
                )
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise ContractError(f"{location}: array is shorter than allowed")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ContractError(f"{location}: array is longer than allowed")
        if schema.get("uniqueItems"):
            canonical_items = [canonical_bytes(item).decode("utf-8") for item in value]
            if len(set(canonical_items)) != len(canonical_items):
                raise ContractError(f"{location}: array items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_schema(
                    item,
                    item_schema,
                    root=root_schema,
                    location=f"{location}[{index}]",
                )
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise ContractError(f"{location}: string is shorter than allowed")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ContractError(f"{location}: string is longer than allowed")
        if "pattern" in schema and re.fullmatch(str(schema["pattern"]), value) is None:
            raise ContractError(f"{location}: string does not match the closed pattern")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < int(schema["minimum"]):
            raise ContractError(f"{location}: value is below the minimum")
        if "maximum" in schema and value > int(schema["maximum"]):
            raise ContractError(f"{location}: value exceeds the maximum")


def operation_registry() -> dict[str, dict[str, JsonValue]]:
    raw = load_json(OPERATIONS_PATH)
    if not isinstance(raw, dict):
        raise ContractError("operation registry must be an object")
    if set(raw) != {"contractVersion", "operations"}:
        raise ContractError("operation registry fields differ from the closed contract")
    if raw["contractVersion"] != "mobius.m7.7.operation-registry.v1":
        raise ContractError("unsupported operation registry version")
    operations = raw["operations"]
    if not isinstance(operations, list):
        raise ContractError("operation registry entries must be an array")
    result: dict[str, dict[str, JsonValue]] = {}
    for index, item in enumerate(operations):
        if not isinstance(item, dict):
            raise ContractError(f"operation registry item {index} must be an object")
        if set(item) != {"method", "operationId", "route", "source", "sourceLine"}:
            raise ContractError(f"operation registry item {index} has unknown or missing fields")
        operation_id = item["operationId"]
        route = item["route"]
        method = item["method"]
        source = item["source"]
        source_line = item["sourceLine"]
        if not isinstance(operation_id, str) or operation_id in result:
            raise ContractError("operation identifiers must be unique strings")
        if method not in {"GET", "POST"}:
            raise ContractError(f"{operation_id}: unsupported method")
        if (
            not isinstance(route, str)
            or not route.startswith("/")
            or "://" in route
            or "\\" in route
            or ".." in route
        ):
            raise ContractError(f"{operation_id}: route is not a repository-relative path")
        if (
            not isinstance(source, str)
            or not source.startswith("apps/api/opencanvas_api/api/routes/")
            or not source.endswith(".py")
            or "\\" in source
            or ".." in source
        ):
            raise ContractError(f"{operation_id}: source path is outside the route registry")
        if not isinstance(source_line, int) or isinstance(source_line, bool) or source_line < 1:
            raise ContractError(f"{operation_id}: source line is invalid")
        result[operation_id] = item
    if not result:
        raise ContractError("operation registry must not be empty")
    return result


def _as_dict(value: JsonValue, location: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ContractError(f"{location}: expected an object")
    return value


def _as_list(value: JsonValue, location: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ContractError(f"{location}: expected an array")
    return value


def _as_int(value: JsonValue, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError(f"{location}: expected an integer")
    return value


def _as_str(value: JsonValue, location: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{location}: expected a string")
    return value


def _generated_entity_count(identities: Mapping[str, JsonValue]) -> int:
    tenant_count = _as_int(identities["tenantCount"], "identities.tenantCount")
    users = tenant_count * _as_int(identities["usersPerTenant"], "identities.usersPerTenant")
    workspaces = tenant_count * _as_int(
        identities["workspacesPerTenant"], "identities.workspacesPerTenant"
    )
    canvases = workspaces * _as_int(
        identities["canvasesPerWorkspace"], "identities.canvasesPerWorkspace"
    )
    documents = workspaces * _as_int(
        identities["documentsPerWorkspace"], "identities.documentsPerWorkspace"
    )
    objects = documents * _as_int(identities["objectsPerDocument"], "identities.objectsPerDocument")
    workflows = workspaces * _as_int(
        identities["workflowsPerWorkspace"], "identities.workflowsPerWorkspace"
    )
    agents = workspaces * _as_int(identities["agentsPerWorkspace"], "identities.agentsPerWorkspace")
    return tenant_count + users + workspaces + canvases + documents + objects + workflows + agents


def validate_manifest(value: JsonValue) -> dict[str, JsonValue]:
    _validate_json_value(value, "$")
    manifest = _as_dict(value, "$")
    schema = _as_dict(load_json(WORKLOAD_SCHEMA_PATH), "workload schema")
    validate_schema(manifest, schema)

    if manifest["workloadType"] not in SUPPORTED_WORKLOAD_TYPES:
        raise ContractError("unsupported workload type")
    registry = operation_registry()
    operations = _as_list(manifest["operations"], "operations")
    operation_ids: list[str] = []
    expected_classes = set(_as_list(manifest["expectedOutcomeClasses"], "expectedOutcomeClasses"))
    for index, raw in enumerate(operations):
        item = _as_dict(raw, f"operations[{index}]")
        operation_id = _as_str(item["operationId"], f"operations[{index}].operationId")
        if operation_id not in registry:
            raise ContractError(f"operations[{index}]: unsupported repository operation")
        if operation_id in operation_ids:
            raise ContractError("operation identifiers must not repeat")
        operation_ids.append(operation_id)
        outcomes = set(_as_list(item["expectedOutcomes"], f"operations[{index}].expectedOutcomes"))
        if not outcomes <= expected_classes:
            raise ContractError(f"operations[{index}]: expected outcome is not globally declared")

    phases = _as_list(manifest["phases"], "phases")
    phase_kinds = tuple(
        _as_str(_as_dict(item, f"phases[{index}]")["kind"], f"phases[{index}].kind")
        for index, item in enumerate(phases)
    )
    expected_order = tuple(kind for kind in EXPECTED_PHASE_ORDER if kind in phase_kinds)
    if phase_kinds != expected_order or phase_kinds.count("measurement") != 1:
        raise ContractError("phases must be unique and ordered warmup, measurement, cooldown")

    limits = _as_dict(manifest["limits"], "limits")
    duration_ms = sum(
        _as_int(_as_dict(item, "phase")["durationMs"], "phase.durationMs") for item in phases
    )
    request_count = sum(
        _as_int(_as_dict(item, "phase")["requestCount"], "phase.requestCount") for item in phases
    )
    if duration_ms > _as_int(limits["maximumDurationMs"], "limits.maximumDurationMs"):
        raise ContractError("phase duration exceeds maximumDurationMs")
    if request_count > _as_int(limits["maximumRequests"], "limits.maximumRequests"):
        raise ContractError("phase requests exceed maximumRequests")

    load_model = _as_dict(manifest["loadModel"], "loadModel")
    concurrency = _as_int(load_model["concurrency"], "loadModel.concurrency")
    if concurrency > _as_int(limits["maximumConcurrency"], "limits.maximumConcurrency"):
        raise ContractError("load-model concurrency exceeds the manifest ceiling")
    model_type = _as_str(load_model["type"], "loadModel.type")
    arrival_rate = load_model["arrivalRatePerSecond"]
    if model_type == "arrival-rate":
        rate = _as_int(arrival_rate, "loadModel.arrivalRatePerSecond")
        if rate > _as_int(limits["maxArrivalRatePerSecond"], "limits.maxArrivalRatePerSecond"):
            raise ContractError("arrival rate exceeds the manifest ceiling")
        for raw in phases:
            phase = _as_dict(raw, "phase")
            feasible = (rate * _as_int(phase["durationMs"], "phase.durationMs") + 999) // 1000
            if _as_int(phase["requestCount"], "phase.requestCount") > feasible:
                raise ContractError("phase request count exceeds its bounded arrival-rate capacity")
    elif arrival_rate is not None:
        raise ContractError("closed-concurrency workloads must set arrivalRatePerSecond to null")

    identities = _as_dict(manifest["identities"], "identities")
    tenant_count = _as_int(identities["tenantCount"], "identities.tenantCount")
    if tenant_count > _as_int(limits["maxTenantCount"], "limits.maxTenantCount"):
        raise ContractError("synthetic tenant count exceeds the manifest ceiling")
    if _generated_entity_count(identities) > _as_int(
        limits["maxGeneratedEntities"], "limits.maxGeneratedEntities"
    ):
        raise ContractError("synthetic entity count exceeds the manifest ceiling")
    object_bytes = _as_int(limits["maxObjectBytes"], "limits.maxObjectBytes")
    total_object_bytes = _as_int(limits["maxTotalObjectBytes"], "limits.maxTotalObjectBytes")
    if object_bytes > total_object_bytes:
        raise ContractError("maxObjectBytes exceeds maxTotalObjectBytes")

    output = _as_dict(manifest["output"], "output")
    max_output = _as_int(output["maxBytes"], "output.maxBytes")
    if max_output != _as_int(limits["maxOutputBytes"], "limits.maxOutputBytes"):
        raise ContractError("output maxBytes must equal limits.maxOutputBytes")
    estimated_plan_bytes = request_count * 512 + 32_768
    if estimated_plan_bytes > max_output:
        raise ContractError("request plan cannot fit inside the declared output ceiling")

    stop = _as_dict(manifest["stopConditions"], "stopConditions")
    if _as_int(stop["maxFailures"], "stopConditions.maxFailures") > request_count:
        raise ContractError("maxFailures exceeds the bounded request count")
    if _as_int(stop["maxTimeouts"], "stopConditions.maxTimeouts") > request_count:
        raise ContractError("maxTimeouts exceeds the bounded request count")
    if (
        manifest["workloadType"] == "noisy-neighbor"
        and manifest["tenantDistribution"] != "weighted-noisy-neighbor"
    ):
        raise ContractError("noisy-neighbor workloads require weighted-noisy-neighbor distribution")
    if (
        manifest["workloadType"] != "noisy-neighbor"
        and manifest["tenantDistribution"] == "weighted-noisy-neighbor"
    ):
        raise ContractError(
            "weighted-noisy-neighbor distribution is reserved for that workload type"
        )
    return deepcopy(manifest)


def manifest_sha256(manifest: JsonValue) -> str:
    validated = validate_manifest(manifest)
    return integrity_sha256(validated, MANIFEST_DOMAIN)


def _deterministic_number(seed: int, namespace: str, index: int) -> int:
    payload = f"{GENERATOR_VERSION}\0{seed}\0{namespace}\0{index}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _synthetic_token(seed: int, kind: str, index: int) -> str:
    payload = TOKEN_DOMAIN + f"{seed}\0{kind}\0{index}".encode()
    return f"syn-{kind}-{hashlib.sha256(payload).hexdigest()[:16]}"


def _weighted_operation(
    operations: Sequence[dict[str, JsonValue]], seed: int, sequence: int
) -> dict[str, JsonValue]:
    total = sum(_as_int(item["weight"], "operation.weight") for item in operations)
    selected = _deterministic_number(seed, "operation", sequence) % total
    cumulative = 0
    for operation in operations:
        cumulative += _as_int(operation["weight"], "operation.weight")
        if selected < cumulative:
            return operation
    raise AssertionError("closed weighted selection must return")


def _tenant_index(distribution: str, tenant_count: int, sequence: int) -> int:
    if distribution == "round-robin":
        return sequence % tenant_count
    if sequence % 2 == 0:
        return 0
    if tenant_count == 1:
        return 0
    return 1 + ((sequence // 2) % (tenant_count - 1))


def generate_plan(value: JsonValue) -> dict[str, JsonValue]:
    """Expand a valid manifest into a bounded deterministic synthetic request plan."""

    manifest = validate_manifest(value)
    seed = _as_int(manifest["seed"], "seed")
    manifest_hash = integrity_sha256(manifest, MANIFEST_DOMAIN)
    operations = [
        _as_dict(item, "operation") for item in _as_list(manifest["operations"], "operations")
    ]
    registry = operation_registry()
    identities = _as_dict(manifest["identities"], "identities")
    tenant_count = _as_int(identities["tenantCount"], "identities.tenantCount")
    max_request_bytes = _as_int(
        _as_dict(manifest["limits"], "limits")["maxRequestBytes"],
        "limits.maxRequestBytes",
    )
    distribution = _as_str(manifest["tenantDistribution"], "tenantDistribution")
    events: list[JsonValue] = []
    sequence = 0
    phase_start_us = 0
    for raw_phase in _as_list(manifest["phases"], "phases"):
        phase = _as_dict(raw_phase, "phase")
        kind = _as_str(phase["kind"], "phase.kind")
        duration_us = _as_int(phase["durationMs"], "phase.durationMs") * 1000
        count = _as_int(phase["requestCount"], "phase.requestCount")
        for phase_index in range(count):
            selected = _weighted_operation(operations, seed, sequence)
            operation_id = _as_str(selected["operationId"], "operation.operationId")
            registry_entry = registry[operation_id]
            tenant_index = _tenant_index(distribution, tenant_count, sequence)
            workspace_count = _as_int(
                identities["workspacesPerTenant"], "identities.workspacesPerTenant"
            )
            workspace_index = tenant_index * workspace_count + (sequence % workspace_count)
            users_per_tenant = _as_int(identities["usersPerTenant"], "identities.usersPerTenant")
            user_index = tenant_index * users_per_tenant + (sequence % users_per_tenant)
            canvases_per_workspace = _as_int(
                identities["canvasesPerWorkspace"], "identities.canvasesPerWorkspace"
            )
            canvas_index = workspace_index * canvases_per_workspace + (
                sequence % canvases_per_workspace
            )
            document_count = _as_int(
                identities["documentsPerWorkspace"], "identities.documentsPerWorkspace"
            )
            document_index = workspace_index * max(document_count, 1) + (
                sequence % max(document_count, 1)
            )
            event: dict[str, JsonValue] = {
                "sequence": sequence,
                "phase": kind,
                "scheduledAtLogicalUs": phase_start_us + (phase_index * duration_us // count),
                "operationId": operation_id,
                "method": registry_entry["method"],
                "route": registry_entry["route"],
                "tenantToken": _synthetic_token(seed, "tenant", tenant_index),
                "userToken": _synthetic_token(seed, "user", user_index),
                "workspaceToken": _synthetic_token(seed, "workspace", workspace_index),
                "canvasToken": _synthetic_token(seed, "canvas", canvas_index),
                "documentToken": _synthetic_token(seed, "document", document_index),
                "objectToken": _synthetic_token(seed, "object", document_index),
                "workflowToken": _synthetic_token(seed, "workflow", workspace_index),
                "agentToken": _synthetic_token(seed, "agent", workspace_index),
                "syntheticRequestBytes": (
                    _deterministic_number(seed, "request-bytes", sequence) % (max_request_bytes + 1)
                ),
            }
            events.append(event)
            sequence += 1
        phase_start_us += duration_us
    plan_without_hash: dict[str, JsonValue] = {
        "contractVersion": "mobius.m7.7.workload-plan.v1",
        "executionBoundary": "synthetic-local-plan-only",
        "generatorVersion": GENERATOR_VERSION,
        "manifestSha256": manifest_hash,
        "seed": seed,
        "workloadId": manifest["workloadId"],
        "workloadType": manifest["workloadType"],
        "events": events,
    }
    plan_hash = integrity_sha256(plan_without_hash, PLAN_DOMAIN)
    plan = {**plan_without_hash, "planSha256": plan_hash}
    max_output = _as_int(_as_dict(manifest["output"], "output")["maxBytes"], "output.maxBytes")
    if len(canonical_bytes(plan)) > max_output:
        raise ContractError("generated plan exceeds the declared output ceiling")
    return plan


@dataclass(frozen=True, slots=True)
class Observation:
    """One bounded logical-time measurement sample."""

    sequence: int
    phase: Literal["warmup", "measurement", "cooldown"]
    operation_id: str
    tenant_token: str
    completed_at_logical_us: int
    latency_us: int
    outcome: Outcome
    retry_count: int = 0
    queue_depth: int | None = None
    queue_wait_us: int | None = None
    saturation_basis_points: int | None = None


def _validate_observation(item: Observation, operation_ids: set[str]) -> None:
    if item.sequence < 0 or item.sequence >= MAX_OBSERVATIONS:
        raise ContractError("observation sequence is outside the bounded range")
    if item.phase not in EXPECTED_PHASE_ORDER:
        raise ContractError("observation phase is outside the closed registry")
    if item.operation_id not in operation_ids:
        raise ContractError("observation operation is outside the manifest registry")
    if re.fullmatch(r"syn-tenant-[0-9a-f]{16}", item.tenant_token) is None:
        raise ContractError("observation tenant token is not a bounded synthetic token")
    if item.completed_at_logical_us < 0 or item.latency_us < 0:
        raise ContractError("observation time values must be non-negative")
    if item.outcome not in OUTCOME_CLASSES:
        raise ContractError("observation outcome is outside the closed registry")
    if item.retry_count < 0 or item.retry_count > 2:
        raise ContractError("observation retry count is outside the hard ceiling")
    if item.queue_depth is not None and not 0 <= item.queue_depth <= 1_000_000:
        raise ContractError("observation queue depth is outside the bounded range")
    if item.queue_wait_us is not None and item.queue_wait_us < 0:
        raise ContractError("observation queue wait must be non-negative")
    if item.saturation_basis_points is not None and not (
        0 <= item.saturation_basis_points <= 10_000
    ):
        raise ContractError("observation saturation is outside the basis-point range")


def _validate_measurement_counts(value: Mapping[str, JsonValue], location: str) -> None:
    requests = _as_int(value["requestCount"], f"{location}.requestCount")
    successes = _as_int(value["successCount"], f"{location}.successCount")
    failures = _as_int(value["failureCount"], f"{location}.failureCount")
    timeouts = _as_int(value["timeoutCount"], f"{location}.timeoutCount")
    error_rate = _as_int(value["errorRateBasisPoints"], f"{location}.errorRateBasisPoints")
    if successes + failures != requests or timeouts > failures:
        raise ContractError(f"{location}: result counts are internally inconsistent")
    if error_rate != _round_ratio_half_up(failures * 10_000, requests):
        raise ContractError(f"{location}: error rate does not match result counts")


def _round_ratio_half_up(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return (numerator + denominator // 2) // denominator


def nearest_rank(samples: Sequence[int], percentile_basis_points: int) -> int | None:
    """Return a nearest-rank percentile over non-negative integer samples."""

    if not 1 <= percentile_basis_points <= 10_000:
        raise ContractError("percentile must be between 1 and 10,000 basis points")
    if not samples:
        return None
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in samples):
        raise ContractError("percentile samples must be non-negative integers")
    ordered = sorted(samples)
    rank = (percentile_basis_points * len(ordered) + 9_999) // 10_000
    return ordered[max(rank, 1) - 1]


def _latency_summary(samples: Sequence[int]) -> dict[str, JsonValue]:
    if not samples:
        return {
            "sampleCount": 0,
            "minimumUs": None,
            "maximumUs": None,
            "meanUs": None,
            "p50Us": None,
            "p95Us": None,
            "p99Us": None,
        }
    return {
        "sampleCount": len(samples),
        "minimumUs": min(samples),
        "maximumUs": max(samples),
        "meanUs": _round_ratio_half_up(sum(samples), len(samples)),
        "p50Us": nearest_rank(samples, 5000),
        "p95Us": nearest_rank(samples, 9500),
        "p99Us": nearest_rank(samples, 9900),
    }


def _measurement(
    observations: Sequence[Observation],
    *,
    elapsed_us: int,
    include_timeout_latencies: bool,
    include_failure_latencies: bool,
) -> dict[str, JsonValue]:
    request_count = len(observations)
    success_count = sum(item.outcome == "success" for item in observations)
    timeout_count = sum(item.outcome == "timeout" for item in observations)
    failure_count = request_count - success_count
    latency_samples = [
        item.latency_us
        for item in observations
        if item.outcome == "success"
        or (item.outcome == "timeout" and include_timeout_latencies)
        or (item.outcome not in {"success", "timeout"} and include_failure_latencies)
    ]
    queue_wait_samples = [
        item.queue_wait_us for item in observations if item.queue_wait_us is not None
    ]
    queue_depths = [item.queue_depth for item in observations if item.queue_depth is not None]
    saturations = [
        item.saturation_basis_points
        for item in observations
        if item.saturation_basis_points is not None
    ]
    return {
        "requestCount": request_count,
        "successCount": success_count,
        "failureCount": failure_count,
        "timeoutCount": timeout_count,
        "retryCount": sum(item.retry_count for item in observations),
        "throughputMilliRequestsPerSecond": _round_ratio_half_up(
            request_count * 1_000_000_000, elapsed_us
        ),
        "errorRateBasisPoints": _round_ratio_half_up(failure_count * 10_000, request_count),
        "latency": _latency_summary(latency_samples),
        "queueWait": _latency_summary(queue_wait_samples),
        "maximumQueueDepth": max(queue_depths) if queue_depths else None,
        "maximumSaturationBasisPoints": max(saturations) if saturations else None,
    }


def evaluate_stop_reason(
    observations: Sequence[Observation], stop_conditions: Mapping[str, JsonValue]
) -> str | None:
    failures = sum(item.outcome != "success" for item in observations)
    timeouts = sum(item.outcome == "timeout" for item in observations)
    if failures > _as_int(stop_conditions["maxFailures"], "stopConditions.maxFailures"):
        return "max-failures"
    if timeouts > _as_int(stop_conditions["maxTimeouts"], "stopConditions.maxTimeouts"):
        return "max-timeouts"
    rate = _round_ratio_half_up(failures * 10_000, len(observations))
    if rate > _as_int(
        stop_conditions["maxErrorRateBasisPoints"],
        "stopConditions.maxErrorRateBasisPoints",
    ):
        return "max-error-rate"
    return None


def build_result(
    manifest_value: JsonValue,
    plan_value: JsonValue,
    observations: Iterable[Observation],
    *,
    assertions: Mapping[str, bool] | None = None,
) -> dict[str, JsonValue]:
    """Build a bounded deterministic local result from logical observations."""

    manifest = validate_manifest(manifest_value)
    plan = _as_dict(plan_value, "plan")
    expected_plan = generate_plan(manifest)
    if canonical_bytes(plan) != canonical_bytes(expected_plan):
        raise ContractError("plan does not match deterministic generation")
    collected = list(observations)
    if len(collected) > _as_int(
        _as_dict(manifest["limits"], "limits")["maximumRequests"],
        "limits.maximumRequests",
    ):
        raise ContractError("observations exceed the workload request ceiling")
    operation_ids = {
        _as_str(_as_dict(item, "operation")["operationId"], "operation.operationId")
        for item in _as_list(manifest["operations"], "operations")
    }
    for item in collected:
        _validate_observation(item, operation_ids)
    if len({item.sequence for item in collected}) != len(collected):
        raise ContractError("observation sequences must be unique")
    plan_events = {
        _as_int(_as_dict(item, "plan event")["sequence"], "plan event.sequence"): _as_dict(
            item, "plan event"
        )
        for item in _as_list(plan["events"], "plan.events")
    }
    limits = _as_dict(manifest["limits"], "limits")
    latest_completion_us = (
        _as_int(limits["maximumDurationMs"], "limits.maximumDurationMs")
        + _as_int(limits["requestTimeoutMs"], "limits.requestTimeoutMs")
    ) * 1000
    for item in collected:
        expected = plan_events.get(item.sequence)
        if expected is None:
            raise ContractError("observation sequence is absent from the deterministic plan")
        if (
            item.phase != expected["phase"]
            or item.operation_id != expected["operationId"]
            or item.tenant_token != expected["tenantToken"]
        ):
            raise ContractError("observation attribution differs from the deterministic plan")
        scheduled_us = _as_int(expected["scheduledAtLogicalUs"], "plan event.scheduledAtLogicalUs")
        if item.completed_at_logical_us < scheduled_us:
            raise ContractError("observation completes before its logical schedule")
        if item.completed_at_logical_us > latest_completion_us:
            raise ContractError("observation completes outside the runtime and timeout ceiling")
        if item.latency_us > _as_int(limits["requestTimeoutMs"], "limits.requestTimeoutMs") * 1000:
            raise ContractError("observation latency exceeds the request-timeout ceiling")
        if item.retry_count > _as_int(limits["maxRetries"], "limits.maxRetries"):
            raise ContractError("observation retry count exceeds the manifest ceiling")
    ordered = sorted(collected, key=lambda item: item.sequence)
    measured = [item for item in ordered if item.phase == "measurement"]
    measurement = _as_dict(manifest["measurement"], "measurement")
    include_timeout = bool(measurement["includeTimeoutLatencies"])
    include_failure = bool(measurement["includeFailureLatencies"])
    elapsed_us = max((item.completed_at_logical_us for item in measured), default=0)
    elapsed_us = max(elapsed_us, 1)
    series_limit = _as_int(
        _as_dict(manifest["limits"], "limits")["maxMeasurementSeries"],
        "limits.maxMeasurementSeries",
    )
    operation_values = sorted({item.operation_id for item in measured})
    tenant_values = sorted({item.tenant_token for item in measured})
    if len(operation_values) + len(tenant_values) + 1 > series_limit:
        raise ContractError("measurement cardinality exceeds the manifest ceiling")

    declared_assertions = [
        _as_str(item, "assertion") for item in _as_list(manifest["assertions"], "assertions")
    ]
    assertion_map = dict(assertions or {item: True for item in declared_assertions})
    if set(assertion_map) != set(declared_assertions):
        raise ContractError("assertion outcomes must exactly match the manifest")
    stop = evaluate_stop_reason(measured, _as_dict(manifest["stopConditions"], "stopConditions"))
    if not all(assertion_map.values()):
        stop = "assertion-failed"
    result_without_hash: dict[str, JsonValue] = {
        "contractVersion": "mobius.m7.7.measurement-result.v1",
        "outputSchemaVersion": "2020-12",
        "workloadId": manifest["workloadId"],
        "workloadType": manifest["workloadType"],
        "manifestSha256": integrity_sha256(manifest, MANIFEST_DOMAIN),
        "planSha256": plan["planSha256"],
        "seed": manifest["seed"],
        "generatorVersion": GENERATOR_VERSION,
        "measurementConfiguration": deepcopy(measurement),
        "runMetadata": {
            "executionBoundary": "synthetic-local-simulator",
            "startedAtLogicalUs": 0,
            "endedAtLogicalUs": max((item.completed_at_logical_us for item in ordered), default=0),
        },
        "aggregate": _measurement(
            measured,
            elapsed_us=elapsed_us,
            include_timeout_latencies=include_timeout,
            include_failure_latencies=include_failure,
        ),
        "operationMeasurements": [
            {
                "operationId": operation_id,
                "measurement": _measurement(
                    [item for item in measured if item.operation_id == operation_id],
                    elapsed_us=elapsed_us,
                    include_timeout_latencies=include_timeout,
                    include_failure_latencies=include_failure,
                ),
            }
            for operation_id in operation_values
        ],
        "tenantMeasurements": [
            {
                "tenantToken": tenant_token,
                "measurement": _measurement(
                    [item for item in measured if item.tenant_token == tenant_token],
                    elapsed_us=elapsed_us,
                    include_timeout_latencies=include_timeout,
                    include_failure_latencies=include_failure,
                ),
            }
            for tenant_token in tenant_values
        ],
        "stopReason": stop or "completed",
        "assertions": [
            {"assertionId": assertion_id, "passed": assertion_map[assertion_id]}
            for assertion_id in sorted(assertion_map)
        ],
        "validationStatus": (
            "valid-synthetic-local" if stop is None and all(assertion_map.values()) else "invalid"
        ),
    }
    result_hash = integrity_sha256(result_without_hash, RESULT_DOMAIN)
    result = {**result_without_hash, "integritySha256": result_hash}
    validate_result(result)
    max_output = _as_int(_as_dict(manifest["output"], "output")["maxBytes"], "output.maxBytes")
    if len(canonical_bytes(result)) > max_output:
        raise ContractError("measurement result exceeds the declared output ceiling")
    return result


def validate_result(value: JsonValue) -> dict[str, JsonValue]:
    _validate_json_value(value, "$")
    result = _as_dict(value, "$")
    schema = _as_dict(load_json(RESULT_SCHEMA_PATH), "result schema")
    validate_schema(result, schema)
    supplied = _as_str(result["integritySha256"], "integritySha256")
    body = {key: deepcopy(item) for key, item in result.items() if key != "integritySha256"}
    expected = integrity_sha256(body, RESULT_DOMAIN)
    if supplied != expected:
        raise ContractError("measurement result integrity hash does not match")
    aggregate = _as_dict(result["aggregate"], "aggregate")
    _validate_measurement_counts(aggregate, "aggregate")
    requests = _as_int(aggregate["requestCount"], "aggregate.requestCount")
    operation_rows = [
        _as_dict(item, "operationMeasurements[]")
        for item in _as_list(result["operationMeasurements"], "operationMeasurements")
    ]
    tenant_rows = [
        _as_dict(item, "tenantMeasurements[]")
        for item in _as_list(result["tenantMeasurements"], "tenantMeasurements")
    ]
    operation_ids = [_as_str(item["operationId"], "operationId") for item in operation_rows]
    tenant_tokens = [_as_str(item["tenantToken"], "tenantToken") for item in tenant_rows]
    if operation_ids != sorted(set(operation_ids)):
        raise ContractError("operation measurement rows must be unique and sorted")
    if tenant_tokens != sorted(set(tenant_tokens)):
        raise ContractError("tenant measurement rows must be unique and sorted")
    for index, row in enumerate(operation_rows):
        _validate_measurement_counts(
            _as_dict(row["measurement"], "operation measurement"),
            f"operationMeasurements[{index}].measurement",
        )
    for index, row in enumerate(tenant_rows):
        _validate_measurement_counts(
            _as_dict(row["measurement"], "tenant measurement"),
            f"tenantMeasurements[{index}].measurement",
        )
    if (
        sum(
            _as_int(_as_dict(row["measurement"], "measurement")["requestCount"], "requestCount")
            for row in operation_rows
        )
        != requests
    ):
        raise ContractError("operation measurements do not reconcile to the aggregate")
    if (
        sum(
            _as_int(_as_dict(row["measurement"], "measurement")["requestCount"], "requestCount")
            for row in tenant_rows
        )
        != requests
    ):
        raise ContractError("tenant measurements do not reconcile to the aggregate")
    assertion_rows = [
        _as_dict(item, "assertions[]") for item in _as_list(result["assertions"], "assertions")
    ]
    assertion_ids = [_as_str(item["assertionId"], "assertionId") for item in assertion_rows]
    if assertion_ids != sorted(set(assertion_ids)):
        raise ContractError("assertion rows must be unique and sorted")
    valid = result["stopReason"] == "completed" and all(
        bool(item["passed"]) for item in assertion_rows
    )
    expected_status = "valid-synthetic-local" if valid else "invalid"
    if result["validationStatus"] != expected_status:
        raise ContractError("validation status does not match stop and assertion outcomes")
    return deepcopy(result)


def simulate_local(value: JsonValue) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """Run the inert logical simulator; it makes no calls and produces only successes."""

    manifest = validate_manifest(value)
    plan = generate_plan(manifest)
    events = _as_list(plan["events"], "plan.events")
    observations: list[Observation] = []
    for raw in events:
        event = _as_dict(raw, "plan event")
        sequence = _as_int(event["sequence"], "event.sequence")
        latency = 1_000 + (
            _deterministic_number(_as_int(manifest["seed"], "seed"), "latency", sequence) % 49_001
        )
        observations.append(
            Observation(
                sequence=sequence,
                phase=_as_str(event["phase"], "event.phase"),  # type: ignore[arg-type]
                operation_id=_as_str(event["operationId"], "event.operationId"),
                tenant_token=_as_str(event["tenantToken"], "event.tenantToken"),
                completed_at_logical_us=_as_int(
                    event["scheduledAtLogicalUs"], "event.scheduledAtLogicalUs"
                )
                + latency,
                latency_us=latency,
                outcome="success",
            )
        )
    return plan, build_result(manifest, plan, observations)
