"""Local-only validation for the Milestone 7.7 infrastructure contracts."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

CONTRACT_DOMAIN = "mobius:milestone-7.7"
AUTHORITATIVE_SOURCE_COMMIT = "1aca65c4a1d131dd420154efbe36e2c2204c3903"
EXPECTED_GATES = (
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
EXPECTED_IMAGE_ROLES = (
    "api",
    "web",
    "indexer-worker",
    "scan-worker",
    "workflow-worker",
    "agent-worker",
    "telemetry-gateway",
    "load-generator",
)
EXPECTED_TAG_KEYS = (
    "mobius-cleanup-binding-sha256",
    "mobius-contract-version",
    "mobius-cost-ceiling-usd-cents",
    "mobius-data-class",
    "mobius-environment",
    "mobius-expires-at-utc",
    "mobius-manifest-sha256",
    "mobius-public-access",
    "mobius-run-id",
    "mobius-source-commit",
    "mobius-teardown-state",
)
EXPECTED_ADDRESS_PLAN = {
    "vnet": "10.77.0.0/20",
    "containerApps": "10.77.0.0/23",
    "privateEndpoints": "10.77.2.0/24",
    "managementCleanup": "10.77.3.0/28",
    "gateway": "10.77.3.32/27",
    "azureFirewall": "10.77.4.0/26",
    "azureFirewallManagement": "10.77.4.64/26",
}
EXPECTED_DEPLOYMENT_ORDER = (
    "validate-contracts",
    "validate-exact-scope",
    "bind-immutable-inputs",
    "arm-cost-controls",
    "create-cleanup-identity",
    "arm-cleanup-controls",
    "prove-cleanup-timer",
    "apply-deny-policies",
    "create-private-network",
    "apply-deny-public-controls",
    "create-private-telemetry",
    "create-workload-identities",
    "create-private-key-vault",
    "create-private-data-services",
    "publish-digest-pinned-images",
    "create-internal-compute",
    "close-bootstrap-egress",
    "prove-security-controls",
)
EXPECTED_TEARDOWN_ORDER = (
    "stop-load-and-scheduled-work",
    "stop-workloads",
    "lock-external-effects",
    "finalize-sanitized-evidence",
    "revoke-temporary-authority",
    "prove-post-revocation-denial",
    "preserve-approved-evidence",
    "delete-compute",
    "delete-container-apps-environment",
    "delete-container-apps-infrastructure-group",
    "delete-data-services",
    "delete-private-telemetry",
    "delete-workload-identities",
    "delete-private-network",
    "prove-target-zero-residue",
    "delete-cleanup-controls",
    "prove-final-zero-residue",
)
EXPECTED_SCHEMAS = {
    "cost-envelope.template.json": "cost-envelope.schema.json",
    "environment.template.json": "environment.schema.json",
    "image-digests.template.json": "image-digests.schema.json",
    "scanner-result-bridge.contract.json": "scanner-result-bridge.schema.json",
}
MANIFEST_DOMAINS = {
    "m7.7-cost-envelope-v1": ("cost-envelope", "v1"),
    "m7.7-environment-v1": ("environment", "v1"),
    "m7.7-image-digests-v1": ("image-digests", "v1"),
}
MANIFEST_SCHEMAS = {
    "m7.7-cost-envelope-v1": "cost-envelope.schema.json",
    "m7.7-environment-v1": "environment.schema.json",
    "m7.7-image-digests-v1": "image-digests.schema.json",
}
FORBIDDEN_BUNDLE_PARTS = {
    ".azure",
    ".pytest_cache",
    "__pycache__",
    "generated",
    "out",
}
EXPECTED_POLICY_DIGESTS = {
    "dependency-order.json": (
        "036a369242182e52018f98e0b27d2944492c977e82475edd8a9209fecd1afce2"
    ),
    "lifecycle-policy.json": (
        "6bc56ebdc0a8221e2f6cb50ba72ecaf129ab8af64bac0193756edfaa9b637a2f"
    ),
    "network-policy.json": (
        "67fe0f29d7a69c78a08a213764da7498a6a83293c3e8838c7d3f971da15a851b"
    ),
    "resource-policy.json": (
        "83e0bc9952184edf9d41e37d3b0d5b94d330e49488a7fab7e211ca27cacd3516"
    ),
    "unresolved-gates.json": (
        "c6b039152023b53b339b42dd88f6622ca369d7d912476a8f656355b847c6256c"
    ),
}
EXPECTED_SCHEMA_DIGESTS = {
    "cost-envelope.schema.json": (
        "1bf046d404541d4fec76673264255e941406ad6a7edbaec9dbe9f4573654452a"
    ),
    "environment.schema.json": (
        "27e038b925ccd66b1172942dd7bf1963bd681fd1e92769f6d46a34d720187076"
    ),
    "image-digests.schema.json": (
        "96cd11b19f621e726075943b3bcf03790255930d6d15ba19b67ac21865eb5d80"
    ),
    "scanner-result-bridge.schema.json": (
        "281bf3a0c5f4ad9a6afe3e624569d521888793c1e445fd57313d71fa12d927e5"
    ),
}
FORBIDDEN_KEY = re.compile(
    r"(?:password|secretvalue|clientsecret|accesstoken|refreshtoken|credential|"
    r"privatekey|accountkey|connectionstring|sastoken|tenantid|subscriptionid|"
    r"principalid|objectid|clientid|resourceid|privateip|apikey|token|"
    r"authorization|accesskey|signedurl|sasuri)",
    re.IGNORECASE,
)
SAFE_CONTROL_KEYS = frozenset(
    {
        "accesskeysenabled",
        "extensionrequiresseparateauthorization",
    }
)
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
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
GUID_PATTERN = re.compile(
    r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
)
HEX_SHA40 = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RESOURCE_GROUP_NAME = re.compile(
    r"^[A-Za-z0-9_()\-](?:[A-Za-z0-9._()\-]{0,88}[A-Za-z0-9_()\-])?$"
)


class ContractError(ValueError):
    """A closed, non-sensitive contract validation error."""


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key at {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON number is forbidden: {value}")


def loads_json(text: str) -> Any:
    """Parse strict JSON while rejecting duplicate keys and non-finite values."""

    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_nonfinite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc


def load_json(path: Path) -> Any:
    try:
        return loads_json(path.read_text(encoding="utf-8"))
    except ContractError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ContractError(
            f"JSON input is unavailable ({type(exc).__name__})"
        ) from None


def _normalise_json(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"non-finite number at {path}")
        raise ContractError(f"floating-point value forbidden at {path}")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [
            _normalise_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        normalised: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"non-string object key at {path}")
            normalised_key = unicodedata.normalize("NFC", key)
            if normalised_key in normalised:
                raise ContractError(f"normalization creates duplicate key at {path}")
            normalised[normalised_key] = _normalise_json(
                item, f"{path}.{normalised_key}"
            )
        return {key: normalised[key] for key in sorted(normalised)}
    raise ContractError(f"unsupported JSON value at {path}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON with sorted keys and a terminal LF."""

    normalised = _normalise_json(value)
    encoded = json.dumps(
        normalised,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{encoded}\n".encode()


def manifest_sha256(kind: str, version: str, value: Any) -> str:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", kind):
        raise ContractError("manifest kind is invalid")
    if not re.fullmatch(r"v[1-9][0-9]{0,7}", version):
        raise ContractError("manifest version is invalid")
    payload = f"{CONTRACT_DOMAIN}:{kind}:{version}\n".encode() + canonical_json_bytes(
        value
    )
    return hashlib.sha256(payload).hexdigest()


def manifest_identity(value: Any) -> tuple[str, str]:
    """Return the immutable hashing domain for one approved manifest."""

    if not isinstance(value, Mapping):
        raise ContractError("manifest must be a JSON object")
    contract_version = value.get("contractVersion")
    if not isinstance(contract_version, str):
        raise ContractError("manifest contract version is not approved")
    identity = MANIFEST_DOMAINS.get(contract_version)
    if identity is None:
        raise ContractError("manifest contract version is not approved")
    return identity


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise ContractError(f"schema uses unsupported type {expected!r}")


def _resolve_local_ref(reference: str, root_schema: Mapping[str, Any]) -> Any:
    if not reference.startswith("#/"):
        raise ContractError("schema uses a non-local reference")
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise ContractError("schema local reference is unresolved")
        current = current[part]
    return current


def validate_schema_subset(
    instance: Any,
    schema: Mapping[str, Any] | bool,
    path: str = "$",
    root_schema: Mapping[str, Any] | None = None,
) -> None:
    """Validate the closed Draft 2020-12 subset used by this checkpoint."""

    if schema is False:
        raise ContractError(f"schema forbids the value at {path}")
    if schema is True:
        return
    if root_schema is None:
        root_schema = schema
    reference = schema.get("$ref")
    if reference is not None:
        resolved = _resolve_local_ref(reference, root_schema)
        validate_schema_subset(instance, resolved, path, root_schema)
        return

    for sub_schema in schema.get("allOf", []):
        condition = sub_schema.get("if")
        if condition is None:
            validate_schema_subset(instance, sub_schema, path, root_schema)
            continue
        try:
            validate_schema_subset(instance, condition, path, root_schema)
            matched = True
        except ContractError:
            matched = False
        selected = sub_schema.get("then" if matched else "else")
        if selected is not None:
            validate_schema_subset(instance, selected, path, root_schema)

    if "const" in schema and instance != schema["const"]:
        raise ContractError(f"constant mismatch at {path}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ContractError(f"value is outside the enum at {path}")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            [expected_type] if isinstance(expected_type, str) else expected_type
        )
        if not any(_json_type_matches(instance, item) for item in expected_types):
            raise ContractError(f"type mismatch at {path}")

    if instance is None:
        return

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [key for key in required if key not in instance]
        if missing:
            raise ContractError(f"missing required field at {path}.{missing[0]}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(instance) - set(properties))
            if unknown:
                raise ContractError(f"unknown field at {path}.{unknown[0]}")
        for key, value in instance.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                validate_schema_subset(
                    value, child_schema, f"{path}.{key}", root_schema
                )
        return

    if isinstance(instance, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(instance) < minimum:
            raise ContractError(f"array is too short at {path}")
        if maximum is not None and len(instance) > maximum:
            raise ContractError(f"array is too long at {path}")
        if schema.get("uniqueItems"):
            canonical_items = [canonical_json_bytes(item) for item in instance]
            if len(canonical_items) != len(set(canonical_items)):
                raise ContractError(f"array items are not unique at {path}")
        prefix_items = schema.get("prefixItems", [])
        for index, prefix_schema in enumerate(prefix_items):
            if index < len(instance):
                validate_schema_subset(
                    instance[index],
                    prefix_schema,
                    f"{path}[{index}]",
                    root_schema,
                )
        item_schema = schema.get("items")
        if item_schema is not None:
            start = len(prefix_items) if prefix_items else 0
            for index, value in enumerate(instance[start:], start=start):
                validate_schema_subset(
                    value, item_schema, f"{path}[{index}]", root_schema
                )
        return

    if isinstance(instance, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(instance) < minimum:
            raise ContractError(f"string is too short at {path}")
        if maximum is not None and len(instance) > maximum:
            raise ContractError(f"string is too long at {path}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, instance) is None:
            raise ContractError(f"string pattern mismatch at {path}")

    if isinstance(instance, int) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if minimum is not None and instance < minimum:
            raise ContractError(f"number is below minimum at {path}")
        if maximum is not None and instance > maximum:
            raise ContractError(f"number is above maximum at {path}")
        if exclusive_maximum is not None and instance >= exclusive_maximum:
            raise ContractError(f"number reaches exclusive maximum at {path}")


def scan_private_material(value: Any, path: str = "$") -> None:
    """Reject secret-bearing names and concrete private identifiers."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            normalised_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if (
                FORBIDDEN_KEY.search(normalised_key)
                and normalised_key not in SAFE_CONTROL_KEYS
            ):
                raise ContractError(f"forbidden private field name at {path}.{key}")
            scan_private_material(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            scan_private_material(child, f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if GUID_PATTERN.search(value):
        raise ContractError(f"concrete private identifier at {path}")
    if any(pattern.search(value) for pattern in FORBIDDEN_VALUE_PATTERNS):
        raise ContractError(f"secret or private value at {path}")


def _validate_environment(value: Mapping[str, Any]) -> None:
    if value["resolutionStatus"] == "unresolved" and value["location"] is not None:
        raise ContractError("unresolved environment must not select a location")
    if value["resolutionStatus"] == "verified" and not isinstance(
        value["location"], str
    ):
        raise ContractError("verified environment requires one explicit location")
    if value["provisioningAuthorized"] is not False:
        raise ContractError("Checkpoint 1 cannot authorize provisioning")
    if tuple(value["requiredTagKeys"]) != EXPECTED_TAG_KEYS:
        raise ContractError("required lifecycle tag inventory differs")

    network = value["network"]
    manifest_address_plan = {
        "vnet": network["vnetCidr"],
        "containerApps": network["containerAppsCidr"],
        "privateEndpoints": network["privateEndpointsCidr"],
        "managementCleanup": network["managementCleanupCidr"],
        "gateway": network["gatewayCidr"],
        "azureFirewall": network["azureFirewallCidr"],
        "azureFirewallManagement": network["azureFirewallManagementCidr"],
    }
    if manifest_address_plan != EXPECTED_ADDRESS_PLAN:
        raise ContractError("environment address plan differs from the fixed contract")
    vnet = ipaddress.ip_network(network["vnetCidr"], strict=True)
    if not isinstance(vnet, ipaddress.IPv4Network):
        raise ContractError("network contract requires an IPv4 VNet")
    private_roots = (
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    )
    if not any(vnet.subnet_of(root) for root in private_roots):
        raise ContractError("network contract must remain inside RFC1918 space")
    child_names = (
        "containerAppsCidr",
        "privateEndpointsCidr",
        "managementCleanupCidr",
        "gatewayCidr",
        "azureFirewallCidr",
        "azureFirewallManagementCidr",
    )
    children: list[ipaddress.IPv4Network] = []
    for name in child_names:
        parsed_child = ipaddress.ip_network(network[name], strict=True)
        if not isinstance(parsed_child, ipaddress.IPv4Network):
            raise ContractError("network contract requires IPv4 subnets")
        child = parsed_child
        children.append(child)
    if any(not child.subnet_of(vnet) for child in children):
        raise ContractError("network subnet is outside the exact VNet")
    for index, left in enumerate(children):
        for right in children[index + 1 :]:
            if left.overlaps(right):
                raise ContractError("network subnets overlap")

    lifecycle = value["lifecycle"]
    bound_fields = (
        "provisioningStartedAtUtc",
        "leaseExpiresAtUtc",
        "cleanupReserveStartsAtUtc",
        "cleanupBindingSha256",
        "cleanupTimerVerifiedAtUtc",
    )
    if value["resolutionStatus"] == "unresolved":
        if any(lifecycle[field] is not None for field in bound_fields):
            raise ContractError("unresolved environment contains a lease binding")
        return

    binding = lifecycle["cleanupBindingSha256"]
    if not isinstance(binding, str) or not HEX_SHA64.fullmatch(binding):
        raise ContractError("verified environment requires a cleanup binding")
    start = _parse_utc(lifecycle["provisioningStartedAtUtc"], "provisioning start")
    expiry = _parse_utc(lifecycle["leaseExpiresAtUtc"], "lease expiry")
    reserve = _parse_utc(
        lifecycle["cleanupReserveStartsAtUtc"], "cleanup reserve start"
    )
    timer_verified = _parse_utc(
        lifecycle["cleanupTimerVerifiedAtUtc"], "cleanup timer verification"
    )
    if expiry <= start or expiry - start > timedelta(hours=30):
        raise ContractError("verified lease exceeds the 30-hour hard maximum")
    if reserve < start or expiry - reserve < timedelta(minutes=90):
        raise ContractError("verified lease lacks the 90-minute cleanup reserve")
    if timer_verified >= start:
        raise ContractError("cleanup timer was not verified before provisioning")


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        raise ContractError(f"{label} is not an exact RFC3339 UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ContractError(f"{label} is not a valid UTC timestamp") from None
    return parsed


def _validate_images(value: Mapping[str, Any]) -> None:
    if value["sourceCommit"] != AUTHORITATIVE_SOURCE_COMMIT:
        raise ContractError("image contract source commit differs")
    roles = tuple(item["role"] for item in value["images"])
    if roles != EXPECTED_IMAGE_ROLES:
        raise ContractError("image role inventory or order differs")
    if value["resolutionStatus"] == "unresolved":
        if (
            value["buildManifestSha256"] is not None
            or value["registryBindingSha256"] is not None
        ):
            raise ContractError("unresolved images must not bind build or registry")
        if any(item["digest"] is not None for item in value["images"]):
            raise ContractError("unresolved images must not contain image digests")
    else:
        build_digest = value["buildManifestSha256"]
        registry_binding = value["registryBindingSha256"]
        if not isinstance(build_digest, str) or not HEX_SHA64.fullmatch(build_digest):
            raise ContractError("verified images require a build manifest digest")
        if not isinstance(registry_binding, str) or not HEX_SHA64.fullmatch(
            registry_binding
        ):
            raise ContractError("verified images require an exact registry binding")
        for item in value["images"]:
            digest = item["digest"]
            if not isinstance(digest, str) or not IMAGE_DIGEST.fullmatch(digest):
                raise ContractError("verified image requires an immutable digest")


def _validate_cost(value: Mapping[str, Any]) -> None:
    expected = value["expectedUsdCents"]
    base_maximum = value["baseMaximumUsdCents"]
    contingency = value["contingencyUsdCents"]
    maximum = value["maximumPlausibleUsdCents"]
    lines = value["lineItems"]
    if value["resolutionStatus"] == "unresolved":
        if (
            any(
                item is not None
                for item in (expected, base_maximum, contingency, maximum)
            )
            or lines
        ):
            raise ContractError("unresolved cost envelope contains a price")
        return
    if not all(
        isinstance(item, int) and not isinstance(item, bool)
        for item in (expected, base_maximum, contingency, maximum)
    ):
        raise ContractError("verified cost envelope requires integer totals")
    if not lines:
        raise ContractError("verified cost envelope requires priced line items")
    names = [item["name"] for item in lines]
    if len(names) != len(set(names)):
        raise ContractError("cost line-item names are not unique")
    if expected > 12000:
        raise ContractError("expected cost exceeds the provisioning block")
    if maximum > 25000:
        raise ContractError("maximum cost exceeds the absolute ceiling")
    if expected > base_maximum:
        raise ContractError("expected cost exceeds the base maximum")
    if sum(item["expectedUsdCents"] for item in lines) != expected:
        raise ContractError("expected cost line items do not reconcile")
    if sum(item["baseMaximumUsdCents"] for item in lines) != base_maximum:
        raise ContractError("base maximum cost line items do not reconcile")
    if any(item["expectedUsdCents"] > item["baseMaximumUsdCents"] for item in lines):
        raise ContractError("cost line-item expected value exceeds its base maximum")
    basis_points = value["uncertaintyContingencyBasisPoints"]
    required_contingency = (base_maximum * basis_points + 9999) // 10000
    if contingency != required_contingency:
        raise ContractError("cost contingency is not the bounded cent calculation")
    if maximum != base_maximum + contingency:
        raise ContractError("maximum cost does not include the contingency")
    if any(item["priceEvidenceStatus"] == "unresolved" for item in lines):
        raise ContractError("verified cost envelope contains unresolved evidence")


def _load_closed_schema(root: Path, schema_name: str) -> Mapping[str, Any]:
    schema = load_json(root.resolve() / "manifests" / schema_name)
    if not isinstance(schema, Mapping):
        raise ContractError("manifest schema must be a JSON object")
    digest = manifest_sha256("schema-contract", "v1", schema)
    if digest != EXPECTED_SCHEMA_DIGESTS[schema_name]:
        raise ContractError(f"{schema_name} differs from the reviewed closed contract")
    return schema


def _validate_manifest(root: Path, value: Any) -> tuple[str, str]:
    """Validate one approved manifest before returning its hashing domain."""

    if not isinstance(value, Mapping):
        raise ContractError("manifest must be a JSON object")
    kind, version = manifest_identity(value)
    schema_name = MANIFEST_SCHEMAS[value["contractVersion"]]
    schema = _load_closed_schema(root, schema_name)
    if value.get("$schema") != schema_name:
        raise ContractError("manifest does not bind its approved local schema")
    validate_schema_subset(value, schema)
    scan_private_material(value)
    if kind == "environment":
        _validate_environment(value)
    elif kind == "image-digests":
        _validate_images(value)
    elif kind == "cost-envelope":
        _validate_cost(value)
    else:
        raise ContractError("manifest hashing domain is unsupported")
    return kind, version


def validate_manifest(root: Path, value: Any) -> tuple[str, str]:
    """Validate one manifest behind a redacted, fail-closed error boundary."""

    try:
        return _validate_manifest(root, value)
    except ContractError:
        raise
    except (
        AttributeError,
        IndexError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ContractError(
            f"manifest validation failed closed ({type(exc).__name__})"
        ) from None


def _validate_policies(root: Path, environment: Mapping[str, Any]) -> None:
    resource = load_json(root / "policies" / "resource-policy.json")
    network = load_json(root / "policies" / "network-policy.json")
    lifecycle = load_json(root / "policies" / "lifecycle-policy.json")
    gates = load_json(root / "policies" / "unresolved-gates.json")
    order = load_json(root / "policies" / "dependency-order.json")
    policies = {
        "resource-policy.json": resource,
        "network-policy.json": network,
        "lifecycle-policy.json": lifecycle,
        "unresolved-gates.json": gates,
        "dependency-order.json": order,
    }
    for name, policy in policies.items():
        if not isinstance(policy, Mapping):
            raise ContractError(f"{name} must be a JSON object")
        scan_private_material(policy)
        if policy.get("provisioningAuthorized") is not False:
            raise ContractError("policy contract authorizes provisioning")
        digest = manifest_sha256("policy-contract", "v1", policy)
        if digest != EXPECTED_POLICY_DIGESTS[name]:
            raise ContractError(f"{name} differs from the reviewed closed contract")

    if resource["defaultEffect"] != "deny":
        raise ContractError("resource policy must deny by default")
    if resource["mutableSkuSelectionAllowed"] is not False:
        raise ContractError("mutable SKU selection is forbidden")
    if resource["mutableReplicaSelectionAllowed"] is not False:
        raise ContractError("mutable replica selection is forbidden")
    if network["defaultInboundAction"] != "deny":
        raise ContractError("network ingress must deny by default")
    if network["defaultOutboundAction"] != "deny":
        raise ContractError("network egress must deny by default")
    if network["publicNetworkAccessAllowed"] is not False:
        raise ContractError("public network access is forbidden")
    network_address_plan = {
        key: value
        for key, value in network["addressPlan"].items()
        if key != "selectionStatus"
    }
    if network_address_plan != EXPECTED_ADDRESS_PLAN:
        raise ContractError("network policy address plan differs")
    environment_address_plan = {
        "vnet": environment["network"]["vnetCidr"],
        "containerApps": environment["network"]["containerAppsCidr"],
        "privateEndpoints": environment["network"]["privateEndpointsCidr"],
        "managementCleanup": environment["network"]["managementCleanupCidr"],
        "gateway": environment["network"]["gatewayCidr"],
        "azureFirewall": environment["network"]["azureFirewallCidr"],
        "azureFirewallManagement": environment["network"][
            "azureFirewallManagementCidr"
        ],
    }
    if network_address_plan != environment_address_plan:
        raise ContractError("environment and network policy address plans differ")
    if lifecycle["costControls"] != {
        "absoluteCeilingUsdCents": 25000,
        "budgetAlertsAreEnforcement": False,
        "minimumContingencyBasisPoints": 2500,
        "provisioningBlockAboveUsdCents": 12000,
        "targetUsdCents": 10000,
    }:
        raise ContractError("fixed cost controls differ")
    if lifecycle["lease"].get("authorizedCleanupAtUtc") != "2026-08-12T22:15:00Z":
        raise ContractError("authorized cleanup deadline differs")
    if tuple(lifecycle["requiredTags"]) != EXPECTED_TAG_KEYS:
        raise ContractError("lifecycle policy tags differ")
    if tuple(environment["requiredTagKeys"]) != tuple(lifecycle["requiredTags"]):
        raise ContractError("environment and lifecycle tag contracts differ")
    gate_ids = tuple(item["id"] for item in gates["gates"])
    if gate_ids != EXPECTED_GATES:
        raise ContractError("unresolved gate inventory or order differs")
    if gates["allResolved"] is not False:
        raise ContractError("Checkpoint 1 gates must remain unresolved")
    if any(item["status"] != "unresolved" for item in gates["gates"]):
        raise ContractError("Checkpoint 1 contains a resolved gate")

    if tuple(order["deployment"]) != EXPECTED_DEPLOYMENT_ORDER:
        raise ContractError("deployment dependency order differs")
    if tuple(order["teardown"]) != EXPECTED_TEARDOWN_ORDER:
        raise ContractError("teardown dependency order differs")


def _validate_bundle(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ContractError("bundle root does not exist")
    manifests_root = root / "manifests"
    environment: Mapping[str, Any] | None = None
    for template_name, schema_name in EXPECTED_SCHEMAS.items():
        schema = _load_closed_schema(root, schema_name)
        instance = load_json(manifests_root / template_name)
        if not isinstance(instance, Mapping):
            raise ContractError("schema and manifest inputs must be JSON objects")
        if instance.get("$schema") != schema_name:
            raise ContractError(f"{template_name} does not bind its local schema")
        validate_schema_subset(instance, schema)
        scan_private_material(instance)
        if template_name == "environment.template.json":
            _validate_environment(instance)
            environment = instance
        elif template_name == "image-digests.template.json":
            _validate_images(instance)
        elif template_name == "cost-envelope.template.json":
            _validate_cost(instance)
    if environment is None:
        raise ContractError("environment contract is unavailable")
    _validate_policies(root, environment)
    return bundle_checksum_manifest(root)


def validate_bundle(root: Path) -> dict[str, Any]:
    """Validate the complete local bundle behind a redacted error boundary."""

    try:
        return _validate_bundle(root)
    except ContractError:
        raise
    except (
        AttributeError,
        IndexError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ContractError(
            f"bundle validation failed closed ({type(exc).__name__})"
        ) from None


def _bundle_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in FORBIDDEN_BUNDLE_PARTS for part in relative.parts):
            raise ContractError("bundle contains forbidden generated material")
        if path.is_symlink():
            raise ContractError("bundle must not contain symbolic links")
        if path.is_file():
            if path.suffix.lower() in {".pyc", ".pyo"}:
                raise ContractError("bundle contains compiled Python output")
            paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def bundle_checksum_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files: list[dict[str, str]] = []
    for path in _bundle_paths(root):
        relative = path.relative_to(root).as_posix()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
            raise ContractError("bundle path escapes the approved root")
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    envelope = {
        "contractVersion": "m7.7-bundle-checksum-v1",
        "files": files,
    }
    return {
        **envelope,
        "bundleSha256": manifest_sha256("bundle-checksum", "v1", envelope),
    }


def _normalise_arm_root(value: str) -> str:
    if not value or value != value.strip():
        raise ContractError("scope is blank or contains surrounding whitespace")
    if any(character in value for character in ("?", "#", "%", "\\")):
        raise ContractError("scope contains an ambiguous character")
    if (
        "//" in value
        or "/./" in value
        or "/../" in value
        or value.endswith("/.")
        or value.endswith("/..")
    ):
        raise ContractError("scope contains an ambiguous segment")
    trimmed = value[:-1] if value.endswith("/") else value
    parts = trimmed.split("/")
    if (
        len(parts) != 5
        or parts[0] != ""
        or parts[1].lower() != "subscriptions"
        or parts[3].lower() != "resourcegroups"
    ):
        raise ContractError("scope is not an exact resource-group root")
    if not GUID_PATTERN.fullmatch(parts[2]):
        raise ContractError("scope subscription segment is invalid")
    try:
        canonical_subscription = str(UUID(parts[2]))
    except ValueError:
        raise ContractError("scope subscription segment is invalid") from None
    if parts[2].lower() != canonical_subscription:
        raise ContractError("scope subscription segment is noncanonical")
    if not RESOURCE_GROUP_NAME.fullmatch(parts[4]):
        raise ContractError("scope resource-group name is invalid")
    return trimmed.lower()


def assert_exact_resource_group_roots(
    target: str, cleanup_control: str
) -> tuple[str, str]:
    normal_target = _normalise_arm_root(target)
    normal_cleanup = _normalise_arm_root(cleanup_control)
    if normal_target == normal_cleanup:
        raise ContractError("target and cleanup-control roots must be separate")
    target_subscription = normal_target.split("/")[2]
    cleanup_subscription = normal_cleanup.split("/")[2]
    if target_subscription != cleanup_subscription:
        raise ContractError("target and cleanup-control roots cross subscriptions")
    return normal_target, normal_cleanup


def assert_within_exact_root(candidate: str, approved_root: str) -> str:
    normal_root = _normalise_arm_root(approved_root)
    if not candidate or candidate != candidate.strip():
        raise ContractError("candidate scope is blank or ambiguous")
    if any(character in candidate for character in ("?", "#", "%", "\\")):
        raise ContractError("candidate scope contains an ambiguous character")
    if (
        "//" in candidate
        or "/./" in candidate
        or "/../" in candidate
        or candidate.endswith("/.")
        or candidate.endswith("/..")
    ):
        raise ContractError("candidate scope contains an ambiguous segment")
    normal_candidate = candidate[:-1] if candidate.endswith("/") else candidate
    normal_candidate = normal_candidate.lower()
    if normal_candidate == normal_root:
        return normal_candidate
    if candidate.endswith("/"):
        raise ContractError("candidate child scope is malformed")
    required_prefix = f"{normal_root}/providers/"
    if not normal_candidate.startswith(required_prefix):
        raise ContractError("candidate scope escapes the exact approved root")
    suffix = normal_candidate[len(required_prefix) :]
    if not suffix or suffix.startswith("/") or suffix.endswith("/"):
        raise ContractError("candidate child scope is malformed")
    parts = suffix.split("/")
    index = 0
    while index < len(parts):
        namespace = parts[index]
        if re.fullmatch(r"[a-z0-9]+(?:\.[a-z0-9]+)+", namespace) is None:
            raise ContractError("candidate provider namespace is malformed")
        index += 1
        pair_count = 0
        while index < len(parts) and parts[index] != "providers":
            if index + 1 >= len(parts):
                raise ContractError("candidate provider child is malformed")
            resource_type, resource_name = parts[index : index + 2]
            if (
                re.fullmatch(r"[a-z0-9._-]+", resource_type) is None
                or re.fullmatch(r"[a-z0-9._()-]+", resource_name) is None
            ):
                raise ContractError("candidate provider child is malformed")
            pair_count += 1
            index += 2
        if pair_count == 0:
            raise ContractError("candidate provider child is malformed")
        if index < len(parts):
            index += 1
            if index >= len(parts):
                raise ContractError("candidate provider child is malformed")
    return normal_candidate


def scope_binding_sha256(target: str, cleanup_control: str) -> str:
    normal_target, normal_cleanup = assert_exact_resource_group_roots(
        target, cleanup_control
    )
    return manifest_sha256(
        "scope-binding",
        "v1",
        {
            "cleanupControlRoot": normal_cleanup,
            "targetRoot": normal_target,
        },
    )
