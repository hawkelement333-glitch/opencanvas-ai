"""One-use finalizer for an already verified Milestone 7.7 ACR manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NoReturn, cast

from performance.milestone_7_7.framework import JsonValue, canonical_bytes, load_json
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    load_managed_binding_contract,
    managed_binding_integrity_sha256,
)

from . import api_image_publication as image_publication
from .scripts import managed_binding_lifecycle as lifecycle

LEDGER_VERSION: Final = "mobius.milestone-7.7.acr-tag-finalization-ledger.v1"
EVIDENCE_VERSION: Final = "mobius.milestone-7.7.acr-tag-finalization-evidence.v1"
LEDGER_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/acr-tag-finalization-ledger/v1\0"
)
EVIDENCE_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/acr-tag-finalization-evidence/v1\0"
)
RECEIPT_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/acr-tag-finalization-receipt/v1\0"
)
IMAGE_SOURCE_COMMIT: Final = "948e81b5bf34f5c2f5069ee40568beb09cb997d3"
SOURCE_TAG: Final = f"source-{IMAGE_SOURCE_COMMIT}"
MANIFEST_DIGEST: Final = (
    "sha256:6aceb88fbf4564c621d8553e461b2e496ec543b48d1a59080958d937eddec99c"
)
REGISTRY_CONFIG_DIGEST: Final = (
    "sha256:c43be0285f3399d893d796397f9895a552f8504e61ce61dfac3ba95dd64d2b41"
)
BUILD_INPUT_SHA256: Final = (
    "16758013417d703a9ebe661511ff1fc305653372286909cdbbc6e9c29a6e613c"
)
LOCAL_IMAGE_ID: Final = MANIFEST_DIGEST
CLASSIC_MODE: Final = "LegacyRegistryPermissions"
ABAC_MODE: Final = "RBACRegistryAndABACRepositoryPermissions"
ACR_PULL_ROLE_ID: Final = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
ACR_DELETE_ROLE_ID: Final = "c2f4ef07-c644-48eb-af81-4b1b4947fb11"
REPOSITORY_CONTRIBUTOR_ROLE_ID: Final = "2efddaa5-3f1f-4df3-97df-af3f13818f4c"
FINALIZER_SCOPE: Final = f"repository:{lifecycle.PUBLISHER_REPOSITORY}:pull,delete"
HEX_SHA40: Final = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
RAW_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
OCI_MANIFEST: Final = "application/vnd.oci.image.manifest.v1+json"
DOCKER_MANIFEST: Final = "application/vnd.docker.distribution.manifest.v2+json"
OCI_INDEX: Final = "application/vnd.oci.image.index.v1+json"
DOCKER_INDEX: Final = "application/vnd.docker.distribution.manifest.list.v2+json"
LEAF_MEDIA_TYPES: Final = frozenset({OCI_MANIFEST, DOCKER_MANIFEST})
INDEX_MEDIA_TYPES: Final = frozenset({OCI_INDEX, DOCKER_INDEX})
ABAC_CONDITION_VERSION: Final = "2.0"
ABAC_CONDITION: Final = """(
 (
  !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/read'})
  AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/read'})
  AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/write'})
  AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/write'})
  AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/delete'})
  AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/delete'})
 )
 OR
 (@Request[Microsoft.ContainerRegistry/registries/repositories:name] StringEqualsIgnoreCase 'opencanvas-api')
)"""


class TagFinalizationError(RuntimeError):
    """Sanitized fail-closed tag-finalization error."""


def _fail(code: str) -> NoReturn:
    if re.fullmatch(r"[a-z0-9-]{1,96}", code) is None:
        code = "tag-finalization-failed-closed"
    raise TagFinalizationError(code)


def _sanitized_error_code(exc: BaseException) -> str:
    code = str(exc)
    if re.fullmatch(r"[a-z0-9-]{1,96}", code) is None:
        return type(exc).__name__
    return code


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _integrity(value: Mapping[str, JsonValue], domain: bytes) -> str:
    return hashlib.sha256(domain + canonical_bytes(dict(value))).hexdigest()


def _outside_repository(path: Path, label: str) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        _fail(f"{label}-inside-repository")
    return resolved


def _write_exclusive(path: Path, value: Mapping[str, JsonValue]) -> None:
    resolved = _outside_repository(path, "finalization-evidence")
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("finalization-replay-denied")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(dict(value)))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        resolved.unlink(missing_ok=True)
        _fail("finalization-evidence-write-failed")


def _repository_state(control_plane_head: str) -> None:
    if HEX_SHA40.fullmatch(control_plane_head) is None:
        _fail("finalization-control-plane-head-invalid")
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    ).stdout.strip()
    dirty = subprocess.run(
        ("git", "status", "--porcelain=v1"),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    ).stdout
    if head != control_plane_head or dirty:
        _fail("finalization-repository-state-mismatch")


def registry_role_plan(mode: str) -> tuple[dict[str, JsonValue], ...]:
    if mode == CLASSIC_MODE:
        return (
            {
                "roleDefinitionId": ACR_PULL_ROLE_ID,
                "roleName": "AcrPull",
                "condition": None,
                "conditionVersion": None,
            },
            {
                "roleDefinitionId": ACR_DELETE_ROLE_ID,
                "roleName": "AcrDelete",
                "condition": None,
                "conditionVersion": None,
            },
        )
    if mode == ABAC_MODE:
        return (
            {
                "roleDefinitionId": REPOSITORY_CONTRIBUTOR_ROLE_ID,
                "roleName": "Container Registry Repository Contributor",
                "condition": ABAC_CONDITION,
                "conditionVersion": ABAC_CONDITION_VERSION,
            },
        )
    _fail("unsupported-or-ambiguous-acr-role-assignment-mode")


def _registry_mode(subscription_id: str) -> str:
    mode = lifecycle._run(
        (
            "az",
            "acr",
            "show",
            "--name",
            lifecycle.REGISTRY,
            "--resource-group",
            lifecycle.TARGET_GROUP,
            "--subscription",
            subscription_id,
            "--query",
            "roleAssignmentMode",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        require_text=True,
    )
    if not isinstance(mode, str):
        _fail("unsupported-or-ambiguous-acr-role-assignment-mode")
    normalized = mode.strip()
    registry_role_plan(normalized)
    return normalized


def build_continuation_ledger(
    *, control_plane_head: str, issued_at_utc: datetime, registry_mode: str
) -> dict[str, JsonValue]:
    if HEX_SHA40.fullmatch(control_plane_head) is None:
        _fail("finalization-control-plane-head-invalid")
    roles = registry_role_plan(registry_mode)
    contract = load_managed_binding_contract()
    issued = issued_at_utc.astimezone(UTC).replace(microsecond=0)
    unsigned: dict[str, JsonValue] = {
        "schemaVersion": LEDGER_VERSION,
        "authorizationId": "m7.7-acr-tag-finalization-20260804",
        "issuedAtUtc": _format_utc(issued),
        "expiresAtUtc": _format_utc(issued + timedelta(hours=1)),
        "repositoryHead": control_plane_head,
        "controlPlaneHead": control_plane_head,
        "imageSourceCommit": IMAGE_SOURCE_COMMIT,
        "manifestDigest": MANIFEST_DIGEST,
        "registryConfigDigest": REGISTRY_CONFIG_DIGEST,
        "sourceTag": SOURCE_TAG,
        "repository": lifecycle.PUBLISHER_REPOSITORY,
        "buildInputSha256": BUILD_INPUT_SHA256,
        "localImageId": LOCAL_IMAGE_ID,
        "cleanupDeadlineUtc": _format_utc(lifecycle.AUTHORIZED_CLEANUP_AT_UTC),
        "absoluteCostCeilingUsdCents": lifecycle.ABSOLUTE_COST_CEILING_USD_CENTS,
        "resourceGroups": [
            lifecycle.TARGET_GROUP,
            lifecycle.CLEANUP_GROUP,
            lifecycle.INFRASTRUCTURE_GROUP,
        ],
        "registryRoleAssignmentMode": registry_mode,
        "finalizerRoles": cast(JsonValue, list(roles)),
        "repositoryTokenScope": FINALIZER_SCOPE,
        "permittedTagOperation": "exact-source-tag-untag-only",
        "allowedMutations": [
            "finalizer-application-create",
            "finalizer-service-principal-create",
            "finalizer-certificate-create",
            "exact-temporary-read-delete-role-assign",
            "exact-repository-token-acquire",
            "exact-source-tag-untag",
            "finalizer-role-revoke",
            "finalizer-credential-principal-application-delete",
            "downstream-after-image-published-only",
        ],
        "prohibitedMutations": [
            "build",
            "push",
            "layer-upload",
            "source-tag-replacement",
            "manifest-delete",
            "repository-delete",
            "other-tag-delete",
            "second-finalization-receipt",
        ],
        "managedBindingIntegritySha256": managed_binding_integrity_sha256(contract),
    }
    return {**unsigned, "ledgerIntegritySha256": _integrity(unsigned, LEDGER_DOMAIN)}


def validate_continuation_ledger(
    value: JsonValue, *, control_plane_head: str, now_utc: datetime
) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        _fail("finalization-ledger-malformed")
    try:
        issued = datetime.strptime(
            str(value.get("issuedAtUtc")), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        expires = datetime.strptime(
            str(value.get("expiresAtUtc")), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except ValueError:
        _fail("finalization-ledger-malformed")
    expected = build_continuation_ledger(
        control_plane_head=control_plane_head,
        issued_at_utc=issued,
        registry_mode=str(value.get("registryRoleAssignmentMode")),
    )
    if value != expected:
        _fail("finalization-ledger-integrity-mismatch")
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if now < issued or now >= expires or expires - issued != timedelta(hours=1):
        _fail("finalization-ledger-expired")
    return value


def materialize_continuation_ledger(
    *, ledger_path: Path, control_plane_head: str
) -> dict[str, JsonValue]:
    _repository_state(control_plane_head)
    now = _utc_now()
    subscription_id = lifecycle._account_binding(now)
    lifecycle._verify_cleanup_control(subscription_id, lifecycle._cleanup_deadline(now))
    mode = _registry_mode(subscription_id)
    ledger = build_continuation_ledger(
        control_plane_head=control_plane_head,
        issued_at_utc=now,
        registry_mode=mode,
    )
    _write_exclusive(ledger_path, ledger)
    return ledger


def _live_tag_metadata(subscription_id: str) -> dict[str, JsonValue]:
    value = lifecycle._run(
        (
            "az",
            "acr",
            "repository",
            "show",
            "--name",
            lifecycle.REGISTRY,
            "--image",
            f"{lifecycle.PUBLISHER_REPOSITORY}:{SOURCE_TAG}",
            "--subscription",
            subscription_id,
            "--query",
            "{digest:digest,deleteEnabled:changeableAttributes.deleteEnabled,readEnabled:changeableAttributes.readEnabled,writeEnabled:changeableAttributes.writeEnabled}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    expected: dict[str, JsonValue] = {
        "digest": MANIFEST_DIGEST,
        "deleteEnabled": True,
        "readEnabled": True,
        "writeEnabled": True,
    }
    if value != expected:
        _fail("source-tag-state-mismatch-or-locked")
    return expected


def _repository_tags(token: bytearray) -> dict[str, str]:
    body = bytearray()
    try:
        status, headers, body = lifecycle._private_registry_request(
            "GET",
            f"/acr/v1/{lifecycle.PUBLISHER_REPOSITORY}/_tags?api-version=2021-07-01",
            headers={"Authorization": lifecycle._registry_authorization(token)},
        )
        if status != 200 or "link" in headers:
            _fail("repository-tag-inventory-incomplete")
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        _fail("repository-tag-inventory-malformed")
    finally:
        body.clear()
    if not isinstance(value, dict) or set(value) - {"registry", "imageName", "tags"}:
        _fail("repository-tag-inventory-malformed")
    rows = value.get("tags")
    if not isinstance(rows, list):
        _fail("repository-tag-inventory-malformed")
    result: dict[str, str] = {}
    for item in rows:
        if (
            not isinstance(item, dict)
            or not {"digest", "name"}.issubset(item)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("digest"), str)
            or item["name"] in result
        ):
            _fail("repository-tag-inventory-malformed")
        result[str(item["name"])] = str(item["digest"])
    return result


def _normalized_content_type(headers: Mapping[str, str]) -> str:
    value = headers.get("content-type")
    if not isinstance(value, str):
        _fail("immutable-manifest-content-type-missing")
    return value.split(";", 1)[0].strip().casefold()


def _descriptor(
    value: JsonValue, *, platform_required: bool = False
) -> dict[str, JsonValue]:
    size = value.get("size") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("mediaType"), str)
        or not isinstance(value.get("digest"), str)
        or RAW_DIGEST.fullmatch(str(value["digest"])) is None
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
    ):
        _fail("immutable-manifest-descriptor-malformed")
    if platform_required:
        platform = value.get("platform")
        if (
            not isinstance(platform, dict)
            or not isinstance(platform.get("os"), str)
            or not isinstance(platform.get("architecture"), str)
        ):
            _fail("immutable-manifest-platform-malformed")
    return value


def _parse_tag_properties(
    status: int, headers: Mapping[str, str], body: bytearray
) -> dict[str, JsonValue]:
    del headers
    if status != 200 or not body:
        _fail("source-tag-properties-unavailable")
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        _fail("source-tag-properties-malformed")
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("registry"), str)
        or value.get("imageName") != lifecycle.PUBLISHER_REPOSITORY
        or not isinstance(value.get("tag"), dict)
    ):
        _fail("source-tag-properties-malformed")
    tag = cast(dict[str, JsonValue], value["tag"])
    attributes = tag.get("changeableAttributes")
    if (
        tag.get("name") != SOURCE_TAG
        or not isinstance(tag.get("digest"), str)
        or RAW_DIGEST.fullmatch(str(tag["digest"])) is None
        or not isinstance(attributes, dict)
        or attributes.get("deleteEnabled") is not True
        or attributes.get("readEnabled") is not True
        or not isinstance(attributes.get("writeEnabled"), bool)
        or (
            "listEnabled" in attributes
            and not isinstance(attributes.get("listEnabled"), bool)
        )
    ):
        _fail("source-tag-properties-mismatch-or-locked")
    return {
        "digest": str(tag["digest"]),
        "deleteEnabled": True,
        "readEnabled": True,
        "writeEnabled": cast(bool, attributes["writeEnabled"]),
    }


def _parse_manifest_head(
    status: int,
    headers: Mapping[str, str],
    body: bytearray,
    *,
    expected_digest: str,
) -> dict[str, JsonValue]:
    if status != 200 or body:
        _fail("immutable-manifest-head-invalid")
    observed = headers.get("docker-content-digest")
    if observed is not None and observed != expected_digest:
        _fail("immutable-manifest-head-digest-mismatch")
    return {
        "bodyEmpty": True,
        "dockerContentDigestPresent": observed is not None,
    }


def _parse_raw_manifest(
    status: int,
    headers: Mapping[str, str],
    body: bytearray,
    *,
    expected_digest: str,
) -> dict[str, JsonValue]:
    if status != 200 or not body:
        _fail("immutable-manifest-get-empty-or-unavailable")
    media_type = _normalized_content_type(headers)
    if media_type not in LEAF_MEDIA_TYPES | INDEX_MEDIA_TYPES:
        _fail("immutable-manifest-media-type-unsupported")
    computed = "sha256:" + hashlib.sha256(body).hexdigest()
    if computed != expected_digest:
        _fail("immutable-manifest-body-digest-mismatch")
    header_digest = headers.get("docker-content-digest")
    if header_digest is not None and header_digest != expected_digest:
        _fail("immutable-manifest-header-digest-mismatch")
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        _fail("immutable-manifest-response-malformed")
    if not isinstance(value, dict) or value.get("schemaVersion") != 2:
        _fail("immutable-manifest-response-malformed")
    declared_type = value.get("mediaType")
    if declared_type is not None and declared_type != media_type:
        _fail("immutable-manifest-media-type-mismatch")
    if media_type in LEAF_MEDIA_TYPES:
        config = _descriptor(value.get("config"))
        layers = value.get("layers")
        if not isinstance(layers, list):
            _fail("immutable-manifest-layers-malformed")
        for layer in layers:
            _descriptor(layer)
        return {
            "kind": "leaf",
            "mediaType": media_type,
            "digest": expected_digest,
            "configDigest": str(config["digest"]),
            "layerCount": len(layers),
        }
    manifests = value.get("manifests")
    if not isinstance(manifests, list):
        _fail("immutable-index-manifests-malformed")
    matches: list[dict[str, JsonValue]] = []
    for item in manifests:
        descriptor = _descriptor(item, platform_required=True)
        platform = cast(dict[str, JsonValue], descriptor["platform"])
        if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
            matches.append(descriptor)
    if len(matches) != 1:
        _fail("immutable-index-platform-cardinality-invalid")
    return {
        "kind": "index",
        "mediaType": media_type,
        "digest": expected_digest,
        "childDigest": str(matches[0]["digest"]),
    }


def _parse_manifest_properties(
    status: int,
    headers: Mapping[str, str],
    body: bytearray,
    *,
    expected_digest: str,
    source_tag_expected: bool,
) -> dict[str, JsonValue]:
    del headers
    if status != 200 or not body:
        _fail("acr-manifest-properties-unavailable")
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        _fail("acr-manifest-properties-malformed")
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("registry"), str)
        or value.get("imageName") != lifecycle.PUBLISHER_REPOSITORY
        or not isinstance(value.get("manifest"), dict)
    ):
        _fail("acr-manifest-properties-malformed")
    manifest = cast(dict[str, JsonValue], value["manifest"])
    attributes = manifest.get("changeableAttributes")
    tags = manifest.get("tags")
    if (
        manifest.get("digest") != expected_digest
        or manifest.get("architecture") != "amd64"
        or manifest.get("os") != "linux"
        or not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
        or (SOURCE_TAG in tags) is not source_tag_expected
        or not isinstance(attributes, dict)
        or attributes.get("readEnabled") is not True
        or not isinstance(attributes.get("deleteEnabled"), bool)
    ):
        _fail("acr-manifest-properties-mismatch")
    return {
        "digest": expected_digest,
        "platform": "linux/amd64",
        "sourceTagPresent": source_tag_expected,
    }


def _parse_blob_head(status: int, headers: Mapping[str, str], body: bytearray) -> None:
    del headers
    if status != 200 or body:
        _fail("immutable-config-blob-head-invalid")


def _registry_read(
    token: bytearray,
    method: str,
    path: str,
    *,
    accept_manifest: bool = False,
) -> tuple[int, dict[str, str], bytearray]:
    headers = {"Authorization": lifecycle._registry_authorization(token)}
    if accept_manifest:
        headers.update(
            {"Accept": lifecycle.MANIFEST_ACCEPT, "Accept-Encoding": "identity"}
        )
    return lifecycle._private_registry_request(method, path, headers=headers)


def _tag_properties(token: bytearray) -> dict[str, JsonValue]:
    body = bytearray()
    try:
        status, headers, body = _registry_read(
            token,
            "GET",
            f"/acr/v1/{lifecycle.PUBLISHER_REPOSITORY}/_tags/{SOURCE_TAG}"
            "?api-version=2021-07-01",
        )
        return _parse_tag_properties(status, headers, body)
    finally:
        body.clear()


def _manifest_identity(
    token: bytearray, *, top_level_digest: str, source_tag_expected: bool
) -> dict[str, JsonValue]:
    if RAW_DIGEST.fullmatch(top_level_digest) is None:
        _fail("immutable-manifest-reference-invalid")
    bodies: list[bytearray] = []
    try:
        status, headers, body = _registry_read(
            token,
            "HEAD",
            f"/v2/{lifecycle.PUBLISHER_REPOSITORY}/manifests/{top_level_digest}"
            "?api-version=2021-07-01",
            accept_manifest=True,
        )
        bodies.append(body)
        _parse_manifest_head(status, headers, body, expected_digest=top_level_digest)
        status, headers, body = _registry_read(
            token,
            "GET",
            f"/v2/{lifecycle.PUBLISHER_REPOSITORY}/manifests/{top_level_digest}"
            "?api-version=2021-07-01",
            accept_manifest=True,
        )
        bodies.append(body)
        top = _parse_raw_manifest(
            status, headers, body, expected_digest=top_level_digest
        )
        child_digest: str | None = None
        leaf = top
        if top["kind"] == "index":
            child_digest = str(top["childDigest"])
            status, headers, body = _registry_read(
                token,
                "GET",
                f"/v2/{lifecycle.PUBLISHER_REPOSITORY}/manifests/{child_digest}"
                "?api-version=2021-07-01",
                accept_manifest=True,
            )
            bodies.append(body)
            leaf = _parse_raw_manifest(
                status, headers, body, expected_digest=child_digest
            )
            if leaf["kind"] != "leaf":
                _fail("immutable-index-child-not-leaf")
        config_digest = str(leaf["configDigest"])
        if config_digest != REGISTRY_CONFIG_DIGEST:
            _fail("immutable-config-digest-mismatch")
        status, headers, body = _registry_read(
            token,
            "HEAD",
            f"/v2/{lifecycle.PUBLISHER_REPOSITORY}/blobs/{config_digest}",
        )
        bodies.append(body)
        _parse_blob_head(status, headers, body)
        status, headers, body = _registry_read(
            token,
            "GET",
            f"/acr/v1/{lifecycle.PUBLISHER_REPOSITORY}/_manifests/"
            f"{top_level_digest}?api-version=2021-07-01",
        )
        bodies.append(body)
        _parse_manifest_properties(
            status,
            headers,
            body,
            expected_digest=top_level_digest,
            source_tag_expected=source_tag_expected,
        )
        return {
            "manifestDigest": top_level_digest,
            "childManifestDigest": child_digest,
            "configDigest": config_digest,
            "platform": "linux/amd64",
            "layerCount": leaf["layerCount"],
        }
    finally:
        for body in bodies:
            body.clear()


def _finalizer_access_is_exact(token: bytearray, *, tenant_id: str) -> bool:
    claims = lifecycle._jwt_claims(token)
    try:
        lifecycle._validate_token_time(claims)
        if claims.get("aud") != lifecycle.REGISTRY_HOST:
            _fail("finalizer-acr-token-audience-invalid")
        token_tenant = claims.get("tid", claims.get("tenant"))
        if token_tenant is not None and token_tenant != tenant_id:
            _fail("finalizer-acr-token-tenant-invalid")
        access = claims.get("access")
        if access in (None, []):
            return False
        if not isinstance(access, list) or len(access) != 1:
            _fail("finalizer-acr-token-scope-invalid")
        item = access[0]
        if not isinstance(item, dict) or set(item) != {"actions", "name", "type"}:
            _fail("finalizer-acr-token-scope-invalid")
        actions = item.get("actions")
        if (
            item.get("type") != "repository"
            or item.get("name") != lifecycle.PUBLISHER_REPOSITORY
            or not isinstance(actions, list)
            or len(actions) != 2
            or set(actions) != {"delete", "pull"}
            or any(not isinstance(action, str) for action in actions)
        ):
            _fail("finalizer-acr-token-scope-invalid")
        return True
    finally:
        claims.clear()


def _finalizer_repository_token(
    *, refresh_token: bytearray, tenant_id: str, service: str
) -> bytearray | None:
    if service != lifecycle.REGISTRY_HOST:
        _fail("finalizer-oauth-service-invalid")
    form = lifecycle._form_body(
        (
            (b"grant_type", b"refresh_token"),
            (b"service", service.encode("ascii")),
            (b"scope", FINALIZER_SCOPE.encode("ascii")),
            (b"refresh_token", refresh_token),
        )
    )
    response = bytearray()
    try:
        expected = lifecycle._expected_authorization_result()
        propagation = (
            lifecycle._ATTRIBUTION_SUBSTAGE.get()
            == "finalizer-role-propagation-verification"
        )
        with lifecycle._attribution_scope(
            lifecycle_substage="finalizer-repository-token-request",
            expected_authorization=expected,
        ):
            status, _headers, response = lifecycle._private_registry_request(
                "POST",
                "/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=form,
            )
        if status in {401, 403} and expected == "deny":
            return None
        if status in {401, 403} and propagation:
            raise lifecycle.PublisherAccessPending(
                f"finalizer-oauth-token-propagation-http-{status}"
            )
        if status == 429 or 500 <= status < 600:
            raise lifecycle.PublisherOAuthTransient(
                f"finalizer-oauth-token-http-{status}"
            )
        if status != 200:
            _fail(f"finalizer-oauth-token-http-{status}")
        token = lifecycle._oauth_secret(
            response,
            key="access_token",
            allowed_keys=frozenset({"access_token", "expires_in", "issued_at"}),
        )
        if not _finalizer_access_is_exact(token, tenant_id=tenant_id):
            token.clear()
            if expected == "deny":
                return None
            _fail("finalizer-acr-token-scope-missing")
        return token
    finally:
        form.clear()
        response.clear()


def _finalizer_repository_session_once(
    *, publisher_app_id: str, tenant_id: str, environment: Mapping[str, str]
) -> tuple[bytearray, bytearray | None]:
    service = lifecycle._registry_bearer_challenge()
    entra_token = lifecycle._publisher_entra_token(
        publisher_app_id=publisher_app_id,
        tenant_id=tenant_id,
        environment_overrides=environment,
    )
    refresh_token = bytearray()
    try:
        exchanged = lifecycle._publisher_refresh_token(
            entra_token=entra_token,
            tenant_id=tenant_id,
            service=service,
        )
        if exchanged is None:
            return refresh_token, None
        refresh_token = exchanged
    finally:
        entra_token.clear()
    try:
        return refresh_token, _finalizer_repository_token(
            refresh_token=refresh_token,
            tenant_id=tenant_id,
            service=service,
        )
    except Exception:
        refresh_token.clear()
        raise


def _finalizer_repository_session(
    *, publisher_app_id: str, tenant_id: str, environment: Mapping[str, str]
) -> tuple[bytearray, bytearray | None]:
    for attempt in range(2):
        try:
            return _finalizer_repository_session_once(
                publisher_app_id=publisher_app_id,
                tenant_id=tenant_id,
                environment=environment,
            )
        except lifecycle.PublisherOAuthTransient:
            if attempt == 1:
                raise
    _fail("finalizer-oauth-retry-state-invalid")


def _prove_initial_finalizer_denial(
    *, publisher_app_id: str, tenant_id: str, environment: Mapping[str, str]
) -> None:
    with lifecycle._attribution_scope(
        lifecycle_substage="initial-finalizer-denial",
        expected_authorization="deny",
    ):
        refresh_token, access_token = _finalizer_repository_session(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            environment=environment,
        )
    try:
        if access_token is not None:
            _fail("finalizer-initial-denial-unproved")
    finally:
        refresh_token.clear()
        if access_token is not None:
            access_token.clear()


def _wait_for_finalizer_access(
    *, publisher_app_id: str, tenant_id: str, environment: Mapping[str, str]
) -> tuple[bytearray, bytearray]:
    deadline = time.monotonic() + 600.0
    while True:
        try:
            with lifecycle._attribution_scope(
                lifecycle_substage="finalizer-role-propagation-verification",
                expected_authorization="allow",
            ):
                refresh_token, access_token = _finalizer_repository_session(
                    publisher_app_id=publisher_app_id,
                    tenant_id=tenant_id,
                    environment=environment,
                )
        except lifecycle.PublisherAccessPending:
            refresh_token = bytearray()
            access_token = None
        if access_token is not None:
            return refresh_token, access_token
        refresh_token.clear()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail("finalizer-role-propagation-unproved")
        time.sleep(min(10.0, remaining))


def _wait_for_finalizer_denial(
    *, publisher_app_id: str, tenant_id: str, environment: Mapping[str, str]
) -> bytearray:
    deadline = time.monotonic() + 600.0
    while True:
        try:
            with lifecycle._attribution_scope(
                lifecycle_substage="post-revocation-finalizer-denial",
                expected_authorization="deny",
            ):
                refresh_token, access_token = _finalizer_repository_session(
                    publisher_app_id=publisher_app_id,
                    tenant_id=tenant_id,
                    environment=environment,
                )
        except lifecycle.PublisherAccessPending:
            refresh_token = bytearray()
            access_token = None
        if access_token is None and refresh_token:
            return refresh_token
        refresh_token.clear()
        if access_token is not None:
            access_token.clear()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail("finalizer-authority-revocation-unproved")
        time.sleep(min(10.0, remaining))


def _validate_role_inventory(
    *,
    subscription_id: str,
    app_id: str,
    object_id: str,
    registry_scope: str,
    roles: Sequence[Mapping[str, JsonValue]],
    required: bool,
) -> None:
    value = lifecycle._run(
        (
            "az",
            "role",
            "assignment",
            "list",
            "--assignee",
            app_id,
            "--all",
            "--include-groups",
            "--fill-principal-name",
            "false",
            "--subscription",
            subscription_id,
            "--query",
            "[].{principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope,"
            "condition:condition,conditionVersion:conditionVersion}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        require_json=True,
    )
    if not isinstance(value, list):
        _fail("finalizer-role-inventory-malformed")
    rows: list[dict[str, JsonValue]] = []
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "condition",
                "conditionVersion",
                "principalId",
                "roleDefinitionId",
                "scope",
            }
            or not all(
                isinstance(row.get(key), str)
                for key in ("principalId", "roleDefinitionId", "scope")
            )
            or row.get("condition") not in {None, ABAC_CONDITION}
            or row.get("conditionVersion") not in {None, ABAC_CONDITION_VERSION}
        ):
            _fail("finalizer-role-inventory-malformed")
        rows.append(
            {
                "principalId": str(row["principalId"]).casefold(),
                "roleDefinitionId": str(row["roleDefinitionId"]).casefold(),
                "scope": str(row["scope"]).casefold(),
                "condition": row["condition"],
                "conditionVersion": row["conditionVersion"],
            }
        )
    if not required:
        if rows:
            _fail("finalizer-inherited-authority")
        return
    subscription_scope = registry_scope.rsplit("/resourceGroups/", 1)[0]
    expected = sorted(
        (
            {
                "principalId": object_id.casefold(),
                "roleDefinitionId": (
                    f"{subscription_scope}/providers/Microsoft.Authorization/"
                    f"roleDefinitions/{role['roleDefinitionId']}"
                ).casefold(),
                "scope": registry_scope.casefold(),
                "condition": role.get("condition"),
                "conditionVersion": role.get("conditionVersion"),
            }
            for role in roles
        ),
        key=lambda row: str(row["roleDefinitionId"]),
    )
    if sorted(rows, key=lambda row: str(row["roleDefinitionId"])) != expected:
        _fail("finalizer-role-inventory-drift")


def _assign_role(
    *,
    subscription_id: str,
    object_id: str,
    registry_scope: str,
    role: Mapping[str, JsonValue],
) -> str:
    argv = [
        "az",
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        object_id,
        "--assignee-principal-type",
        "ServicePrincipal",
        "--role",
        str(role["roleDefinitionId"]),
        "--scope",
        registry_scope,
        "--subscription",
        subscription_id,
    ]
    condition = role.get("condition")
    version = role.get("conditionVersion")
    if condition is not None:
        if condition != ABAC_CONDITION or version != ABAC_CONDITION_VERSION:
            _fail("finalizer-abac-condition-invalid")
        argv.extend(
            ("--condition", str(condition), "--condition-version", str(version))
        )
    elif version is not None:
        _fail("finalizer-abac-condition-invalid")
    argv.extend(("--query", "{id:id}", "--output", "json", "--only-show-errors"))
    created = lifecycle._run(tuple(argv), require_json=True)
    if (
        not isinstance(created, dict)
        or set(created) != {"id"}
        or not isinstance(created.get("id"), str)
        or not str(created["id"]).startswith("/subscriptions/")
    ):
        _fail("finalizer-role-assignment-output-malformed")
    return str(created["id"])


def _wait_role_inventory(
    *,
    subscription_id: str,
    app_id: str,
    object_id: str,
    registry_scope: str,
    roles: Sequence[Mapping[str, JsonValue]],
    required: bool,
) -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        try:
            _validate_role_inventory(
                subscription_id=subscription_id,
                app_id=app_id,
                object_id=object_id,
                registry_scope=registry_scope,
                roles=roles,
                required=required,
            )
            return
        except TagFinalizationError as exc:
            if str(exc) != "finalizer-role-inventory-drift":
                raise
            time.sleep(10.0)
    _fail("finalizer-role-propagation-unproved")


def _finalizer_environment(root: Path) -> tuple[Path, dict[str, str]]:
    finalizer = lifecycle._secure_ephemeral_directory(root / "ephemeral-finalizer")
    azure_config = lifecycle._secure_ephemeral_directory(finalizer / "azure-config")
    docker_config = lifecycle._secure_ephemeral_directory(finalizer / "docker-config")
    return finalizer, {
        "AZURE_CONFIG_DIR": str(azure_config),
        "DOCKER_CONFIG": str(docker_config),
    }


def _cleanup_finalizer(
    *,
    subscription_id: str,
    assignment_ids: Sequence[str],
    app_id: str | None,
    object_id: str | None,
    tenant_id: str | None,
    certificate_path: Path | None,
    environment: Mapping[str, str],
    finalizer_root: Path,
    registry_scope: str,
    roles: Sequence[Mapping[str, JsonValue]],
) -> list[str]:
    errors: list[str] = []
    for assignment_id in reversed(assignment_ids):
        try:
            lifecycle._delete_assignment(subscription_id, assignment_id)
        except BaseException as exc:
            errors.append(_sanitized_error_code(exc))
    if app_id is not None and object_id is not None:
        try:
            _wait_role_inventory(
                subscription_id=subscription_id,
                app_id=app_id,
                object_id=object_id,
                registry_scope=registry_scope,
                roles=roles,
                required=False,
            )
        except BaseException as exc:
            errors.append(_sanitized_error_code(exc))
        try:
            lifecycle._reset_ephemeral_directory(Path(environment["AZURE_CONFIG_DIR"]))
            if certificate_path is not None and tenant_id is not None:
                lifecycle._publisher_login(
                    publisher_app_id=app_id,
                    tenant_id=tenant_id,
                    certificate_path=certificate_path,
                    environment=environment,
                )
                denial_refresh = _wait_for_finalizer_denial(
                    publisher_app_id=app_id,
                    tenant_id=tenant_id,
                    environment=environment,
                )
                denial_refresh.clear()
        except BaseException as exc:
            errors.append(_sanitized_error_code(exc))
        try:
            lifecycle._delete_ephemeral_publisher_by_app_id(app_id)
        except BaseException as exc:
            errors.append(_sanitized_error_code(exc))
    if finalizer_root.exists():
        try:
            shutil.rmtree(finalizer_root)
        except OSError as exc:
            errors.append(_sanitized_error_code(exc))
    return errors


def _raise_preserving_primary(
    primary_error: BaseException | None, cleanup_errors: Sequence[str]
) -> None:
    if primary_error is not None:
        raise primary_error
    if cleanup_errors:
        _fail("finalizer-cleanup-failed")


def execute_finalization(
    *, ledger_path: Path, receipt_directory: Path, control_plane_head: str
) -> dict[str, JsonValue]:
    _repository_state(control_plane_head)
    now = _utc_now()
    ledger = validate_continuation_ledger(
        load_json(_outside_repository(ledger_path, "finalization-ledger")),
        control_plane_head=control_plane_head,
        now_utc=now,
    )
    receipt_root = _outside_repository(receipt_directory, "finalization-receipt")
    receipt_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_body: dict[str, JsonValue] = {
        "authorizationId": ledger["authorizationId"],
        "ledgerIntegritySha256": ledger["ledgerIntegritySha256"],
        "claimedAtUtc": _format_utc(now),
        "operation": "exact-source-tag-finalization",
        "replayDecision": "deny",
    }
    _write_exclusive(
        receipt_root / "acr-tag-finalization.receipt.json",
        {
            **receipt_body,
            "receiptIntegritySha256": _integrity(receipt_body, RECEIPT_DOMAIN),
        },
    )
    subscription_id = lifecycle._account_binding(now)
    cleanup_at = lifecycle._cleanup_deadline(now)
    lifecycle._verify_cleanup_control(subscription_id, cleanup_at)
    expected_cost, maximum_cost = lifecycle._verified_cost()
    if maximum_cost > lifecycle.ABSOLUTE_COST_CEILING_USD_CENTS:
        _fail("finalization-cost-ceiling-exceeded")
    mode = _registry_mode(subscription_id)
    if mode != ledger["registryRoleAssignmentMode"]:
        _fail("finalization-role-mode-drift")
    roles = registry_role_plan(mode)
    if (
        image_publication._api_image_build_input_sha256(IMAGE_SOURCE_COMMIT)
        != BUILD_INPUT_SHA256
    ):
        _fail("finalization-image-source-drift")
    image_id, config_id = image_publication._inspect_local_api_image(
        image_publication._api_image_reference(IMAGE_SOURCE_COMMIT)
    )
    if image_id != LOCAL_IMAGE_ID or config_id != LOCAL_IMAGE_ID:
        _fail("finalization-local-image-drift")
    registry_scope = lifecycle._scope(
        subscription_id,
        f"/resourceGroups/{lifecycle.TARGET_GROUP}/providers/"
        f"Microsoft.ContainerRegistry/registries/{lifecycle.REGISTRY}",
    )
    finalizer_root, environment = _finalizer_environment(receipt_root)
    app_id: str | None = None
    object_id: str | None = None
    tenant_id: str | None = None
    certificate_path: Path | None = None
    assignment_ids: list[str] = []
    refresh_token = bytearray()
    access_token = bytearray()
    delete_status: int | None = None
    manifest_before: dict[str, JsonValue] | None = None
    manifest_after: dict[str, JsonValue] | None = None
    deletion_ambiguous = False
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []
    try:
        app_id, object_id, tenant_id, certificate_path = (
            lifecycle._create_ephemeral_publisher(
                ledger=ledger,
                publisher_directory=finalizer_root,
                identity_prefix="mobius77-acr-finalizer",
            )
        )
        _validate_role_inventory(
            subscription_id=subscription_id,
            app_id=app_id,
            object_id=object_id,
            registry_scope=registry_scope,
            roles=roles,
            required=False,
        )
        lifecycle._publisher_login(
            publisher_app_id=app_id,
            tenant_id=tenant_id,
            certificate_path=certificate_path,
            environment=environment,
        )
        _prove_initial_finalizer_denial(
            publisher_app_id=app_id,
            tenant_id=tenant_id,
            environment=environment,
        )
        for role in roles:
            assignment_ids.append(
                _assign_role(
                    subscription_id=subscription_id,
                    object_id=object_id,
                    registry_scope=registry_scope,
                    role=role,
                )
            )
        _wait_role_inventory(
            subscription_id=subscription_id,
            app_id=app_id,
            object_id=object_id,
            registry_scope=registry_scope,
            roles=roles,
            required=True,
        )
        lifecycle._run(
            ("az", "logout", "--only-show-errors", "--output", "none"),
            environment_overrides=environment,
        )
        lifecycle._reset_ephemeral_directory(Path(environment["AZURE_CONFIG_DIR"]))
        lifecycle._publisher_login(
            publisher_app_id=app_id,
            tenant_id=tenant_id,
            certificate_path=certificate_path,
            environment=environment,
        )
        refresh_token, access_token = _wait_for_finalizer_access(
            publisher_app_id=app_id,
            tenant_id=tenant_id,
            environment=environment,
        )
        if not _finalizer_access_is_exact(access_token, tenant_id=tenant_id):
            _fail("finalizer-token-scope-missing")
        tag_properties = _tag_properties(access_token)
        top_level_digest = str(tag_properties["digest"])
        if top_level_digest != MANIFEST_DIGEST:
            _fail("source-tag-digest-mismatch-before-delete")
        if (
            lifecycle._acr_manifest_digest(access_token, reference=SOURCE_TAG)
            != top_level_digest
        ):
            _fail("source-tag-head-digest-mismatch-before-delete")
        manifest_before = _manifest_identity(
            access_token,
            top_level_digest=top_level_digest,
            source_tag_expected=True,
        )
        tags_before = _repository_tags(access_token)
        if tags_before.get(SOURCE_TAG) != top_level_digest:
            _fail("source-tag-state-mismatch-or-locked")
        body = bytearray()
        try:
            delete_status, _headers, body = lifecycle._private_registry_request(
                "DELETE",
                f"/acr/v1/{lifecycle.PUBLISHER_REPOSITORY}/_tags/{SOURCE_TAG}"
                "?api-version=2021-07-01",
                headers={
                    "Authorization": lifecycle._registry_authorization(access_token)
                },
            )
            if delete_status != 202:
                _fail(f"tag-delete-http-{delete_status}")
        except lifecycle.LifecycleError as exc:
            if str(exc) != "publisher-private-registry-request-failed":
                raise
            deletion_ambiguous = True
        finally:
            body.clear()
        if (
            lifecycle._acr_manifest_digest(access_token, reference=SOURCE_TAG)
            is not None
        ):
            _fail("source-tag-remains-after-delete")
        manifest_after = _manifest_identity(
            access_token,
            top_level_digest=top_level_digest,
            source_tag_expected=False,
        )
        tags_after = _repository_tags(access_token)
        expected_after = dict(tags_before)
        expected_after.pop(SOURCE_TAG)
        if tags_after != expected_after:
            _fail("repository-tag-inventory-changed-outside-target")
    except BaseException as exc:
        primary_error = exc
    finally:
        access_token.clear()
        refresh_token.clear()
        cleanup_errors.extend(
            _cleanup_finalizer(
                subscription_id=subscription_id,
                assignment_ids=assignment_ids,
                app_id=app_id,
                object_id=object_id,
                tenant_id=tenant_id,
                certificate_path=certificate_path,
                environment=environment,
                finalizer_root=finalizer_root,
                registry_scope=registry_scope,
                roles=roles,
            )
        )
    if primary_error is not None or cleanup_errors:
        failure_unsigned: dict[str, JsonValue] = {
            "schemaVersion": EVIDENCE_VERSION,
            "ledgerIntegritySha256": ledger["ledgerIntegritySha256"],
            "controlPlaneHead": control_plane_head,
            "primaryError": (
                _sanitized_error_code(primary_error)
                if primary_error is not None
                else None
            ),
            "secondaryCleanupErrors": cast(JsonValue, cleanup_errors),
            "tagDeleteRequestResult": delete_status,
            "ambiguousTransportObserved": deletion_ambiguous,
            "completedAtUtc": _format_utc(_utc_now()),
        }
        failure = {
            **failure_unsigned,
            "evidenceIntegritySha256": _integrity(failure_unsigned, EVIDENCE_DOMAIN),
        }
        _write_exclusive(receipt_root / "acr-tag-finalization.failure.json", failure)
        _raise_preserving_primary(primary_error, cleanup_errors)
    if manifest_before != manifest_after or manifest_after is None:
        _fail("immutable-manifest-changed-during-untag")
    evidence_unsigned: dict[str, JsonValue] = {
        "schemaVersion": EVIDENCE_VERSION,
        "ledgerIntegritySha256": ledger["ledgerIntegritySha256"],
        "controlPlaneHead": control_plane_head,
        "imageSourceCommit": IMAGE_SOURCE_COMMIT,
        "manifestDigest": MANIFEST_DIGEST,
        "registryConfigDigest": REGISTRY_CONFIG_DIGEST,
        "sourceTagSha256": hashlib.sha256(SOURCE_TAG.encode("ascii")).hexdigest(),
        "sourceTagAbsent": True,
        "immutableManifestRetained": True,
        "platform": "linux/amd64",
        "layerCount": 13,
        "registryRoleAssignmentMode": mode,
        "roleDefinitionIds": [str(role["roleDefinitionId"]) for role in roles],
        "roleScope": "exact-container-registry-resource",
        "repositoryTokenScope": FINALIZER_SCOPE,
        "deleteStatus": delete_status,
        "ambiguousTransportReconciled": deletion_ambiguous,
        "buildPerformed": False,
        "pushPerformed": False,
        "layerUploaded": False,
        "assignmentCountRevoked": len(assignment_ids),
        "finalizerIdentityDeleted": True,
        "secretValueAccessed": False,
        "expectedUsdCents": expected_cost,
        "maximumUsdCents": maximum_cost,
        "cleanupDeadlineUtc": _format_utc(cleanup_at),
        "completedAtUtc": _format_utc(_utc_now()),
    }
    evidence = {
        **evidence_unsigned,
        "evidenceIntegritySha256": _integrity(evidence_unsigned, EVIDENCE_DOMAIN),
    }
    _write_exclusive(receipt_root / "acr-tag-finalization.evidence.json", evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--materialize-ledger", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--receipt-directory", type=Path)
    parser.add_argument("--control-plane-head", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.materialize_ledger:
            if args.receipt_directory is not None:
                _fail("finalization-command-contract-invalid")
            result = materialize_continuation_ledger(
                ledger_path=args.ledger,
                control_plane_head=args.control_plane_head,
            )
            safe = {
                "status": "materialized",
                "ledgerIntegritySha256": result["ledgerIntegritySha256"],
                "expiresAtUtc": result["expiresAtUtc"],
                "registryRoleAssignmentMode": result["registryRoleAssignmentMode"],
            }
        else:
            if args.receipt_directory is None:
                _fail("finalization-command-contract-invalid")
            result = execute_finalization(
                ledger_path=args.ledger,
                receipt_directory=args.receipt_directory,
                control_plane_head=args.control_plane_head,
            )
            safe = {
                "status": "IMAGE_PUBLISHED",
                "evidenceIntegritySha256": result["evidenceIntegritySha256"],
                "manifestDigest": result["manifestDigest"],
                "sourceTagAbsent": result["sourceTagAbsent"],
                "immutableManifestRetained": result["immutableManifestRetained"],
                "finalizerIdentityDeleted": result["finalizerIdentityDeleted"],
            }
        print(json.dumps(safe, separators=(",", ":"), sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc)
        if re.fullmatch(r"[a-z0-9-]{1,96}", code) is None:
            code = type(exc).__name__
        print(
            json.dumps(
                {"status": "TAG_FINALIZATION_BLOCKED", "error": code},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 130 if isinstance(exc, KeyboardInterrupt) else 2


if __name__ == "__main__":
    raise SystemExit(main())
