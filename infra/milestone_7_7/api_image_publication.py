"""Isolated local-build and ordinary-push transport module for Milestone 7.7."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from performance.milestone_7_7.framework import JsonValue, canonical_bytes, load_json
from preflight.milestone_7_7.managed_binding_contracts import (
    REPOSITORY_ROOT,
    load_managed_binding_contract,
)
from preflight.milestone_7_7.publication_path_admission import (
    verify_private_registry_publication_path,
)

from infra.milestone_7_7.publication_state_machine import (
    PublicationState,
    PublicationStateMachine,
)

from infra.milestone_7_7.scripts.managed_binding_lifecycle import (
    API_IMAGE_BUILDER_PREFIX,
    API_IMAGE_BUILD_INPUTS,
    API_IMAGE_BUILD_INPUT_DOMAIN,
    API_IMAGE_PLATFORM,
    DEPLOYMENT_TIMEOUT_SECONDS,
    HEX_SHA256,
    HEX_SHA40,
    IMAGE_DIGEST,
    KEY_VAULT,
    KEY_VAULT_HOST,
    _LIFECYCLE_MODULE_IDENTITY as _LIFECYCLE_MODULE_IDENTITY,
    PREBUILT_IMAGE_RECORD_DOMAIN,
    PREBUILT_IMAGE_RECORD_VERSION,
    PUBLICATION_RESULT_DOMAIN,
    PUBLISHER_REPOSITORY,
    RAW_IMAGE_DIGEST,
    REGISTRY_HOST,
    REGISTRY,
    _acr_manifest_digest,
    _assert_source_tag_absent,
    _attribution_scope,
    _begin_process_attribution,
    _create_ephemeral_publisher,
    _delete_assignment,
    _delete_ephemeral_publisher,
    _delete_ephemeral_publisher_by_app_id,
    _docker_login_with_refresh_token,
    _fail,
    _finish_process_attribution,
    _outside_repository,
    _private_tls_endpoint,
    _prove_initial_publisher_denial,
    _publisher_environment,
    _publisher_login,
    _publisher_role_rows,
    _read_state,
    _read_current_transient_state,
    _remove_ephemeral_publisher_directory,
    _replace_state,
    _reset_ephemeral_directory,
    _resolved_executable,
    _run,
    _run_text,
    _safe_attribution_error,
    _sanitized_correlation_hash,
    _sanitized_status_code,
    _scope,
    _secure_ephemeral_directory,
    _state_path,
    TARGET_GROUP,
    _temporary_publisher_role_assignment,
    _validate_publisher_role_inventory,
    _verify_cleanup_control,
    _verify_repository_state,
    _wait_for_denial,
    _wait_for_publisher_access,
    _wait_for_publisher_denial,
    _wait_for_publisher_role_inventory,
)

DOCKER_PUSH_EVIDENCE_DOMAIN = (
    b"solarplexus-mobius/milestone-7.7/docker-push-evidence/v1\x00"
)
DOCKER_PUSH_EVIDENCE_VERSION = "mobius.milestone-7.7.docker-push-evidence.v1"
DOCKER_PUSH_EVIDENCE_FILE = "docker-push-evidence.json"
DOCKER_PUSH_MAXIMUM_OUTPUT_BYTES = 4 * 1024 * 1024
SENSITIVE_PUSH_OUTPUT_PATTERNS = (
    re.compile(r"(?i)(Authorization\s*:\s*)(?:Bearer|Basic)\s+\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(
        r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
    re.compile(
        r"(?i)(?:[A-Z]:\\(?:"
        + "Users"
        + r")\\|/(?:"
        + "Users"
        + r")/|/(?:"
        + "home"
        + r")/)[^/\s\\]+(?:[/\\][^\s]*)?"
    ),
    re.compile(r"(?i)/subscriptions/[0-9a-f-]{36}(?:/[^\s]*)?"),
    re.compile(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
    ),
    re.compile(
        r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
    ),
)


class PublicationAttemptFailure(RuntimeError):
    """Preserve the first publication failure when closeout also fails."""

    primary_failed_stage = "immutable-image-publication"

    def __init__(
        self, primary_error: BaseException, secondary_error: BaseException
    ) -> None:
        self.primary_error_code = _safe_attribution_error(primary_error)
        self.secondary_error_code = _safe_attribution_error(secondary_error)
        super().__init__(self.primary_error_code)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_push_output(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").replace(
        REGISTRY_HOST, "[private-registry]"
    )
    for pattern in SENSITIVE_PUSH_OUTPUT_PATTERNS:
        text = pattern.sub(
            r"\1[redacted]"
            if pattern is SENSITIVE_PUSH_OUTPUT_PATTERNS[0]
            else "[redacted]",
            text,
        )
    return text


def _material_error_lines(stdout: str, stderr: str) -> tuple[str | None, str | None]:
    markers = re.compile(
        r"(?i)(?:error|failed|failure|denied|unauthorized|forbidden|timeout|"
        r"reset|refused|eof|unavailable|not found|unknown|only one connection)"
    )
    lines = [
        line.strip()
        for stream in (stderr, stdout)
        for line in stream.splitlines()
        if line.strip() and markers.search(line)
    ]
    return (lines[0], lines[-1]) if lines else (None, None)


def _docker_runtime_metadata(
    docker_executable: str, *, environment: Mapping[str, str]
) -> dict[str, str]:
    commands = {
        "context": (docker_executable, "context", "show"),
        "endpoint": (
            docker_executable,
            "context",
            "inspect",
            "--format",
            "{{json .Endpoints.docker.Host}}",
        ),
        "version": (docker_executable, "version", "--format", "{{json .}}"),
    }
    results: dict[str, str] = {}
    for name, command in commands.items():
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=120,
        )
        if completed.returncode != 0 or completed.stderr:
            _fail("publisher-docker-runtime-metadata-unavailable")
        try:
            results[name] = completed.stdout.decode("utf-8", errors="strict").strip()
        except UnicodeError:
            _fail("publisher-docker-runtime-metadata-malformed")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", results["context"]) is None:
        _fail("publisher-docker-runtime-metadata-malformed")
    try:
        endpoint = json.loads(results["endpoint"])
    except json.JSONDecodeError:
        _fail("publisher-docker-runtime-metadata-malformed")
    if not isinstance(endpoint, str) or not endpoint:
        _fail("publisher-docker-runtime-metadata-malformed")
    endpoint_class = next(
        (
            name
            for prefix, name in (
                ("npipe://", "windows-npipe"),
                ("unix://", "local-unix-socket"),
                ("tcp://", "tcp"),
                ("ssh://", "ssh"),
            )
            if endpoint.casefold().startswith(prefix)
        ),
        "opaque",
    )
    try:
        version = json.loads(results["version"])
    except json.JSONDecodeError:
        _fail("publisher-docker-runtime-metadata-malformed")
    if not isinstance(version, dict):
        _fail("publisher-docker-runtime-metadata-malformed")
    client = version.get("Client")
    server = version.get("Server")
    if not isinstance(client, dict) or not isinstance(server, dict):
        _fail("publisher-docker-runtime-metadata-malformed")
    client_version = client.get("Version")
    server_version = server.get("Version")
    server_os = server.get("Os")
    if not all(
        isinstance(value, str) for value in (client_version, server_version, server_os)
    ):
        _fail("publisher-docker-runtime-metadata-malformed")
    return {
        "context": results["context"],
        "clientVersion": str(client_version),
        "serverVersion": str(server_version),
        "serverOs": str(server_os),
        "endpointClass": endpoint_class,
        "endpointSha256": hashlib.sha256(endpoint.encode()).hexdigest(),
    }


def _write_docker_push_evidence(path: Path, body: dict[str, JsonValue]) -> None:
    resolved = _outside_repository(path, "docker-push-evidence")
    temporary = resolved.with_suffix(".tmp")
    if not resolved.parent.is_dir() or temporary.exists():
        _fail("publisher-docker-push-evidence-state-invalid")
    value = {
        **body,
        "integritySha256": hashlib.sha256(
            DOCKER_PUSH_EVIDENCE_DOMAIN + canonical_bytes(body)
        ).hexdigest(),
    }
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved)
    except OSError:
        temporary.unlink(missing_ok=True)
        _fail("publisher-docker-push-evidence-write-failed")


def _api_image_reference(repository_head: str) -> str:
    if HEX_SHA40.fullmatch(repository_head) is None:
        _fail("repository-head-invalid")
    return f"{REGISTRY_HOST}/{PUBLISHER_REPOSITORY}:source-{repository_head}"


def _api_image_build_input_sha256(repository_head: str) -> str:
    if HEX_SHA40.fullmatch(repository_head) is None:
        _fail("repository-head-invalid")
    for relative in API_IMAGE_BUILD_INPUTS:
        candidate = REPOSITORY_ROOT / relative
        if not candidate.exists():
            _fail("api-image-build-input-missing")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(REPOSITORY_ROOT.resolve(strict=True))
        except (OSError, ValueError):
            _fail("api-image-build-input-invalid")
    raw = _run_text(
        (
            "git",
            "ls-tree",
            "-r",
            "--full-tree",
            repository_head,
            "--",
            *API_IMAGE_BUILD_INPUTS,
        )
    )
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        matched = re.fullmatch(
            r"(100644|100755|120000) blob ([0-9a-f]{40})\t([^\x00\r\n]+)", line
        )
        if matched is None:
            _fail("api-image-build-input-tree-malformed")
        entries.append(
            {
                "mode": matched.group(1),
                "object": matched.group(2),
                "path": matched.group(3).replace("\\", "/"),
            }
        )
    if not entries:
        _fail("api-image-build-input-tree-malformed")
    observed_paths = {entry["path"] for entry in entries}
    for relative in API_IMAGE_BUILD_INPUTS:
        normalized = relative.replace("\\", "/")
        candidate = REPOSITORY_ROOT / relative
        if candidate.is_file() and normalized not in observed_paths:
            _fail("api-image-build-input-tree-malformed")
        if candidate.is_dir() and not any(
            path.startswith(normalized + "/") for path in observed_paths
        ):
            _fail("api-image-build-input-tree-malformed")
    payload: dict[str, JsonValue] = {
        "inputs": list(API_IMAGE_BUILD_INPUTS),
        "treeEntries": cast(JsonValue, entries),
    }
    return hashlib.sha256(
        API_IMAGE_BUILD_INPUT_DOMAIN + canonical_bytes(payload)
    ).hexdigest()


def _buildx_inventory() -> list[dict[str, JsonValue]]:
    raw = _run(("docker", "buildx", "ls", "--format", "{{json .}}"), require_text=True)
    if not isinstance(raw, str):
        _fail("api-image-builder-inventory-malformed")
    rows: list[dict[str, JsonValue]] = []
    for line in raw.splitlines():
        try:
            value = cast(JsonValue, json.loads(line))
        except json.JSONDecodeError:
            _fail("api-image-builder-inventory-malformed")
        if not isinstance(value, dict):
            _fail("api-image-builder-inventory-malformed")
        name = value.get("Name")
        driver = value.get("Driver")
        current = value.get("Current")
        nodes = value.get("Nodes")
        if (
            not isinstance(name, str)
            or not isinstance(driver, str)
            or not isinstance(current, bool)
            or not isinstance(nodes, list)
        ):
            _fail("api-image-builder-inventory-malformed")
        rows.append(value)
    if not rows:
        _fail("api-image-builder-inventory-malformed")
    return rows


def _current_builders(rows: list[dict[str, JsonValue]]) -> frozenset[str]:
    return frozenset(str(row["Name"]) for row in rows if row.get("Current") is True)


def _remove_stale_api_image_builders() -> None:
    names = sorted(
        {
            str(row["Name"])
            for row in _buildx_inventory()
            if isinstance(row.get("Name"), str)
            and str(row["Name"]).startswith(API_IMAGE_BUILDER_PREFIX)
        }
    )
    for name in names:
        if re.fullmatch(r"mobius77-api-build-[0-9a-f]{12}", name) is None:
            _fail("api-image-builder-name-invalid")
        _run(("docker", "buildx", "rm", "--force", name))
    if any(
        str(row.get("Name", "")).startswith(API_IMAGE_BUILDER_PREFIX)
        for row in _buildx_inventory()
    ):
        _fail("api-image-builder-cleanup-unproved")


def _validate_api_image_builder(rows: list[dict[str, JsonValue]], *, name: str) -> None:
    matches = [row for row in rows if row.get("Name") == name]
    if not matches:
        _fail("api-image-builder-missing")
    for row in matches:
        if row.get("Driver") != "docker-container" or row.get("Current") is True:
            _fail("api-image-builder-contract-mismatch")
        nodes = row.get("Nodes")
        if not isinstance(nodes, list) or not nodes:
            _fail("api-image-builder-contract-mismatch")
        for node in nodes:
            platforms = node.get("Platforms") if isinstance(node, dict) else None
            if (
                not isinstance(node, dict)
                or node.get("Status") != "running"
                or not isinstance(platforms, list)
                or API_IMAGE_PLATFORM not in platforms
            ):
                _fail("api-image-builder-contract-mismatch")


def _inspect_local_api_image(image_reference: str) -> tuple[str, str]:
    if not re.fullmatch(
        rf"{re.escape(REGISTRY_HOST)}/{PUBLISHER_REPOSITORY}:source-[0-9a-f]{{40}}",
        image_reference,
    ):
        _fail("prebuilt-api-image-reference-invalid")
    value = _run(
        (
            "docker",
            "image",
            "inspect",
            "--format",
            "{{json .}}",
            image_reference,
        ),
        require_json=True,
    )
    if not isinstance(value, dict):
        _fail("prebuilt-api-image-inspection-malformed")
    image_id = value.get("Id")
    repository_tags = value.get("RepoTags")
    if (
        not isinstance(image_id, str)
        or RAW_IMAGE_DIGEST.fullmatch(image_id) is None
        or value.get("Os") != "linux"
        or value.get("Architecture") != "amd64"
        or not isinstance(repository_tags, list)
        or image_reference not in repository_tags
    ):
        _fail("prebuilt-api-image-inspection-mismatch")
    return image_id, image_id


def _prebuilt_record_unsigned(
    *, repository_head: str, build_input_sha256: str, image_id: str, config_digest: str
) -> dict[str, JsonValue]:
    return {
        "buildInputSha256": build_input_sha256,
        "completionStatus": "READY",
        "configDigest": config_digest,
        "imageId": image_id,
        "platform": API_IMAGE_PLATFORM,
        "repositoryHead": repository_head,
        "schemaVersion": PREBUILT_IMAGE_RECORD_VERSION,
    }


def _write_prebuilt_api_image_record(path: Path, value: dict[str, JsonValue]) -> None:
    resolved = _outside_repository(path, "prebuilt-api-image-record")
    temporary = resolved.with_suffix(".tmp")
    if resolved.exists() or temporary.exists() or not resolved.parent.is_dir():
        _fail("prebuilt-api-image-record-state-invalid")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved)
    except OSError:
        temporary.unlink(missing_ok=True)
        _fail("prebuilt-api-image-record-write-failed")


def _load_prebuilt_api_image_record(
    path: Path,
    *,
    image_source_commit: str | None,
    control_plane_head: str,
) -> dict[str, JsonValue]:
    resolved = _outside_repository(path, "prebuilt-api-image-record")
    value = load_json(resolved)
    if not isinstance(value, dict):
        _fail("prebuilt-api-image-record-malformed")
    exact = {
        "buildInputSha256",
        "completionStatus",
        "configDigest",
        "imageId",
        "integritySha256",
        "platform",
        "repositoryHead",
        "schemaVersion",
    }
    if set(value) != exact:
        _fail("prebuilt-api-image-record-malformed")
    integrity = value.get("integritySha256")
    unsigned = {key: item for key, item in value.items() if key != "integritySha256"}
    if (
        not isinstance(integrity, str)
        or HEX_SHA256.fullmatch(integrity) is None
        or integrity
        != hashlib.sha256(
            PREBUILT_IMAGE_RECORD_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest()
        or value.get("schemaVersion") != PREBUILT_IMAGE_RECORD_VERSION
        or value.get("completionStatus") != "READY"
        or value.get("platform") != API_IMAGE_PLATFORM
        or not isinstance(value.get("repositoryHead"), str)
        or HEX_SHA40.fullmatch(str(value.get("repositoryHead"))) is None
    ):
        _fail("prebuilt-api-image-record-integrity-invalid")
    source_commit = str(value["repositoryHead"])
    if image_source_commit is not None and source_commit != image_source_commit:
        _fail("prebuilt-api-image-source-commit-mismatch")
    if HEX_SHA40.fullmatch(control_plane_head) is None:
        _fail("prebuilt-api-image-control-plane-head-invalid")
    comparison = subprocess.run(
        (
            "git",
            "diff",
            "--quiet",
            source_commit,
            control_plane_head,
            "--",
            *API_IMAGE_BUILD_INPUTS,
        ),
        cwd=REPOSITORY_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        shell=False,
        timeout=30,
    )
    if comparison.returncode == 1:
        _fail("prebuilt-api-image-control-plane-input-drift")
    if comparison.returncode != 0:
        _fail("prebuilt-api-image-input-comparison-failed")
    build_input_sha256 = value.get("buildInputSha256")
    image_id = value.get("imageId")
    config_digest = value.get("configDigest")
    if (
        not isinstance(build_input_sha256, str)
        or HEX_SHA256.fullmatch(build_input_sha256) is None
        or not isinstance(image_id, str)
        or RAW_IMAGE_DIGEST.fullmatch(image_id) is None
        or config_digest != image_id
    ):
        _fail("prebuilt-api-image-record-malformed")
    if _api_image_build_input_sha256(source_commit) != build_input_sha256:
        _fail("prebuilt-api-image-source-drift")
    inspected_id, inspected_config = _inspect_local_api_image(
        _api_image_reference(source_commit)
    )
    if inspected_id != image_id or inspected_config != config_digest:
        _fail("prebuilt-api-image-identity-mismatch")
    return value


def _prebuild_api_image(
    *, repository_head: str, record_path: Path
) -> dict[str, JsonValue]:
    _verify_repository_state(repository_head)
    resolved_record = _outside_repository(record_path, "prebuilt-api-image-record")
    if resolved_record.exists() or not resolved_record.parent.is_dir():
        _fail("prebuilt-api-image-record-state-invalid")
    _remove_stale_api_image_builders()
    initial_current = _current_builders(_buildx_inventory())
    builder_name = (
        API_IMAGE_BUILDER_PREFIX + hashlib.sha256(os.urandom(32)).hexdigest()[:12]
    )
    image_reference = _api_image_reference(repository_head)
    build_input_sha256 = _api_image_build_input_sha256(repository_head)
    temporary_root = _outside_repository(
        Path(tempfile.mkdtemp(prefix="mobius77-api-image-build-")),
        "api-image-build-temporary-directory",
    )
    config_path = temporary_root / "buildkitd.toml"
    builder_created = False
    build_succeeded = False
    image_id = ""
    config_digest = ""
    try:
        config_path.write_text(
            "[worker.oci]\n  max-parallelism = 1\n", encoding="utf-8", newline="\n"
        )
        os.chmod(config_path, 0o600)
        created = _run(
            (
                "docker",
                "buildx",
                "create",
                "--name",
                builder_name,
                "--driver",
                "docker-container",
                "--buildkitd-config",
                str(config_path),
            ),
            require_text=True,
        )
        builder_created = True
        if not isinstance(created, str) or created.strip() != builder_name:
            _fail("api-image-builder-create-output-malformed")
        _run(("docker", "buildx", "inspect", builder_name, "--bootstrap"))
        _validate_api_image_builder(_buildx_inventory(), name=builder_name)
        if _current_builders(_buildx_inventory()) != initial_current:
            _fail("api-image-default-builder-changed")
        _run(
            (
                "docker",
                "buildx",
                "build",
                "--builder",
                builder_name,
                "--file",
                "apps/api/Dockerfile",
                "--target",
                "runner",
                "--platform",
                API_IMAGE_PLATFORM,
                "--tag",
                image_reference,
                "--load",
                "--provenance=false",
                "--sbom=false",
                "--progress",
                "plain",
                ".",
            ),
            timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
        )
        image_id, config_digest = _inspect_local_api_image(image_reference)
        build_succeeded = True
    finally:
        if builder_created:
            _run(("docker", "buildx", "rm", "--force", builder_name))
        shutil.rmtree(temporary_root, ignore_errors=False)
    if any(row.get("Name") == builder_name for row in _buildx_inventory()):
        _fail("api-image-builder-cleanup-unproved")
    if temporary_root.exists() or config_path.exists():
        _fail("api-image-build-temporary-residue")
    if not build_succeeded:
        _fail("api-image-production-build-failed")
    final_image_id, final_config_digest = _inspect_local_api_image(image_reference)
    if final_image_id != image_id or final_config_digest != config_digest:
        _fail("prebuilt-api-image-identity-mismatch")
    unsigned = _prebuilt_record_unsigned(
        repository_head=repository_head,
        build_input_sha256=build_input_sha256,
        image_id=image_id,
        config_digest=config_digest,
    )
    record = {
        **unsigned,
        "integritySha256": hashlib.sha256(
            PREBUILT_IMAGE_RECORD_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest(),
    }
    _write_prebuilt_api_image_record(resolved_record, record)
    return record


def _docker_push_error_code(stdout: bytearray, stderr: bytearray) -> str:
    try:
        text = (
            (bytes(stdout) + b"\n" + bytes(stderr))
            .decode("utf-8", errors="strict")
            .casefold()
        )
    except UnicodeError:
        return "publisher-docker-push-failed"
    transient_markers = (
        "429",
        "too many requests",
        "connection reset",
        "connection refused",
        "i/o timeout",
        "tls handshake timeout",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    )
    return (
        "publisher-docker-push-transient"
        if any(marker in text for marker in transient_markers)
        else "publisher-docker-push-failed"
    )


def _docker_push_once(
    image_reference: str,
    *,
    environment: Mapping[str, str],
    evidence_path: Path,
) -> str:
    if not re.fullmatch(
        rf"{re.escape(REGISTRY_HOST)}/{PUBLISHER_REPOSITORY}:source-[0-9a-f]{{40}}",
        image_reference,
    ):
        _fail("publisher-docker-push-reference-invalid")
    argv = ("docker", "push", image_reference)
    attribution, operation_id, _attribution_spec = _begin_process_attribution(
        argv,
        environment_overrides=environment,
        expected_authorization="allow",
    )
    stdout = bytearray()
    stderr = bytearray()
    attribution_finished = False
    started_at = datetime.now(tz=UTC)
    publisher_environment = _publisher_environment(environment)
    docker_executable = _resolved_executable("docker")
    runtime = _docker_runtime_metadata(
        docker_executable, environment=publisher_environment
    )
    source_tag = image_reference.rsplit(":", maxsplit=1)[1]
    command_projection: list[JsonValue] = [
        Path(docker_executable).name,
        "push",
        f"[private-registry]/{PUBLISHER_REPOSITORY}:{source_tag}",
    ]
    initial: dict[str, JsonValue] = {
        "schemaVersion": DOCKER_PUSH_EVIDENCE_VERSION,
        "status": "STARTED",
        "command": command_projection,
        "credentialsPresentInCommand": False,
        "dockerClientVersion": runtime["clientVersion"],
        "dockerContext": runtime["context"],
        "dockerDaemonEndpointClass": runtime["endpointClass"],
        "dockerDaemonEndpointSha256": runtime["endpointSha256"],
        "dockerDaemonOs": runtime["serverOs"],
        "dockerDaemonVersion": runtime["serverVersion"],
        "registryHostSha256": hashlib.sha256(REGISTRY_HOST.encode("ascii")).hexdigest(),
        "repository": PUBLISHER_REPOSITORY,
        "sourceTag": source_tag,
        "startedAtUtc": _format_utc(started_at),
        "finishedAtUtc": None,
        "actualExitCode": None,
        "timedOut": False,
        "processKilled": False,
        "azureMutationBegan": False,
        "azureMutationState": "NOT_BEGUN",
        "stdoutComplete": False,
        "stderrComplete": False,
        "stdoutSanitized": "",
        "stderrSanitized": "",
        "stdoutSanitizedSha256": hashlib.sha256(b"").hexdigest(),
        "stderrSanitizedSha256": hashlib.sha256(b"").hexdigest(),
        "firstMaterialError": None,
        "finalMaterialError": None,
        "rawOutputRetained": False,
        "secretValueRetained": False,
    }
    _write_docker_push_evidence(evidence_path, initial)

    def finalize_evidence(
        *,
        status: str,
        exit_code: int | None,
        timed_out: bool,
        process_killed: bool,
        mutation_state: str,
    ) -> tuple[str, str]:
        stdout_text = _sanitize_push_output(bytes(stdout))
        stderr_text = _sanitize_push_output(bytes(stderr))
        output_within_bound = (
            len(stdout) + len(stderr) <= DOCKER_PUSH_MAXIMUM_OUTPUT_BYTES
        )
        if not output_within_bound:
            stdout_text = "[sanitized-output-exceeded-bound]"
            stderr_text = "[sanitized-output-exceeded-bound]"
        first_error, final_error = _material_error_lines(stdout_text, stderr_text)
        body = {
            **initial,
            "status": status,
            "finishedAtUtc": _format_utc(datetime.now(tz=UTC)),
            "actualExitCode": exit_code,
            "timedOut": timed_out,
            "processKilled": process_killed,
            "azureMutationBegan": (
                True
                if mutation_state == "CONFIRMED"
                else False
                if mutation_state == "NOT_BEGUN"
                else None
            ),
            "azureMutationState": mutation_state,
            "stdoutComplete": output_within_bound,
            "stderrComplete": output_within_bound,
            "stdoutSanitized": stdout_text,
            "stderrSanitized": stderr_text,
            "stdoutSanitizedSha256": hashlib.sha256(stdout_text.encode()).hexdigest(),
            "stderrSanitizedSha256": hashlib.sha256(stderr_text.encode()).hexdigest(),
            "firstMaterialError": first_error,
            "finalMaterialError": final_error,
        }
        _write_docker_push_evidence(evidence_path, body)
        if not output_within_bound:
            _fail("publisher-docker-push-output-oversized")
        return stdout_text, stderr_text

    try:
        if attribution is not None and operation_id is not None:
            attribution.mark_request_attempt_began(
                operation_id, cleanup_or_revocation=False
            )
        process = subprocess.Popen(
            (docker_executable, "push", image_reference),
            cwd=REPOSITORY_ROOT,
            env=publisher_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        if attribution is not None and operation_id is not None:
            attribution.mark_azure_request_issued(operation_id)
        try:
            raw_stdout, raw_stderr = process.communicate(
                timeout=DEPLOYMENT_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            process.kill()
            raw_stdout, raw_stderr = process.communicate()
            stdout.extend(raw_stdout)
            stderr.extend(raw_stderr)
            finalize_evidence(
                status="TIMED_OUT",
                exit_code=process.returncode,
                timed_out=True,
                process_killed=True,
                mutation_state="UNKNOWN_PENDING_REGISTRY_RECONCILIATION",
            )
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code="process-timeout",
                azure_error_code="publisher-docker-push-process-timed-out",
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="TIMED_OUT",
            )
            attribution_finished = True
            _fail("publisher-docker-push-process-timed-out")
        except KeyboardInterrupt:
            process.kill()
            raw_stdout, raw_stderr = process.communicate()
            stdout.extend(raw_stdout)
            stderr.extend(raw_stderr)
            finalize_evidence(
                status="CANCELLED",
                exit_code=process.returncode,
                timed_out=False,
                process_killed=True,
                mutation_state="UNKNOWN_PENDING_REGISTRY_RECONCILIATION",
            )
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code="process-cancelled",
                azure_error_code="publisher-docker-push-process-cancelled",
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="CANCELLED",
            )
            attribution_finished = True
            raise
        stdout.extend(raw_stdout)
        stderr.extend(raw_stderr)
        stdout_text, stderr_text = finalize_evidence(
            status="SUCCEEDED" if process.returncode == 0 else "FAILED",
            exit_code=process.returncode,
            timed_out=False,
            process_killed=False,
            mutation_state=(
                "CONFIRMED"
                if process.returncode == 0
                else "UNKNOWN_PENDING_REGISTRY_RECONCILIATION"
            ),
        )
        if process.returncode != 0:
            error_code = _docker_push_error_code(stdout, stderr)
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=f"process-exit-{process.returncode}",
                azure_error_code=error_code,
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
            attribution_finished = True
            _fail(error_code)
        source_tag_bytes = source_tag.encode("ascii")
        digest_pattern = (
            rb"(?im)^(?:"
            + re.escape(source_tag_bytes)
            + rb":\s*)?digest:\s*(sha256:[0-9a-f]{64})\s+size:\s*[1-9][0-9]*\s*$"
        )
        digest_matches = {
            match.group(1)
            for buffer in (stdout_text, stderr_text)
            for match in re.finditer(digest_pattern, buffer.encode())
        }
        if len(digest_matches) != 1:
            _fail("publisher-docker-push-digest-malformed")
        raw_digest = next(iter(digest_matches)).decode("ascii")
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="2xx-not-reported",
            azure_error_code=None,
            correlation_hash=_sanitized_correlation_hash(stdout, stderr),
            terminal_disposition="SUCCEEDED",
        )
        attribution_finished = True
        return raw_digest
    except OSError:
        finalize_evidence(
            status="LAUNCH_FAILED",
            exit_code=None,
            timed_out=False,
            process_killed=False,
            mutation_state="NOT_BEGUN",
        )
        _finish_process_attribution(
            attribution,
            operation_id,
            status_code="not-reported",
            azure_error_code="publisher-docker-push-process-launch-failed",
            correlation_hash=None,
            terminal_disposition="UNCERTAIN",
        )
        attribution_finished = True
        _fail("publisher-docker-push-process-launch-failed")
    except BaseException as exc:
        if not attribution_finished:
            _finish_process_attribution(
                attribution,
                operation_id,
                status_code=_sanitized_status_code(
                    stdout, stderr, default="not-reported"
                ),
                azure_error_code=_safe_attribution_error(exc),
                correlation_hash=_sanitized_correlation_hash(stdout, stderr),
                terminal_disposition="FAILED",
            )
        raise
    finally:
        stdout.clear()
        stderr.clear()


def _docker_push_prebuilt_image(
    image_reference: str,
    *,
    source_tag: str,
    environment: Mapping[str, str],
    access_token: bytearray,
    evidence_path: Path,
) -> str:
    del source_tag, access_token
    return _docker_push_once(
        image_reference,
        environment=environment,
        evidence_path=evidence_path,
    )


def _publish_api_image(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    prebuilt_image_record: Path,
) -> str:
    publication = PublicationStateMachine()
    repository_head = str(ledger["repositoryHead"])
    published = ledger.get("publishedImage")
    if HEX_SHA40.fullmatch(repository_head) is None or not isinstance(published, dict):
        _fail("repository-head-invalid")
    publication.advance(PublicationState.IMAGE_ADMITTED)
    image_source_commit = published.get("imageSourceCommit")
    if (
        not isinstance(image_source_commit, str)
        or HEX_SHA40.fullmatch(image_source_commit) is None
        or published.get("publicationState") != "pending"
        or published.get("registryManifestDigest") is not None
    ):
        _fail("pending-image-ledger-binding-invalid")
    state_path = _state_path(receipt_directory)
    state = _read_state(state_path)
    if state.get("temporaryRegistryAssignmentId") is not None:
        _fail("temporary-registry-authority-already-present")
    record = _load_prebuilt_api_image_record(
        prebuilt_image_record,
        image_source_commit=image_source_commit,
        control_plane_head=repository_head,
    )
    publication.advance(PublicationState.LOCAL_IMAGE_VERIFIED)
    if (
        record.get("buildInputSha256") != published.get("imageBuildInputSha256")
        or record.get("imageId") != published.get("localImageId")
        or record.get("configDigest") != published.get("imageConfigDigest")
        or record.get("platform") != published.get("platform")
        or published.get("sourceTag") != f"source-{image_source_commit}"
    ):
        _fail("pending-image-ledger-record-mismatch")
    verify_private_registry_publication_path(repository_head=image_source_commit)
    publication.advance(PublicationState.PUBLICATION_PATH_PROVED)
    image_by_tag = _api_image_reference(image_source_commit)
    contract = load_managed_binding_contract()
    rbac = contract["rbac"]
    scopes = contract["scopeBinding"]
    if not isinstance(rbac, dict) or not isinstance(scopes, dict):
        _fail("managed-binding-contract-malformed")
    registry_scope = _scope(subscription_id, str(scopes["containerRegistry"]))
    assignment_id: str | None = None
    publisher_app_id: str | None = None
    publisher_object_id: str | None = None
    publisher_deleted = False
    denial_proved = False
    immutable_reference: str | None = None
    raw_digest: str | None = None
    refresh_token = bytearray()
    access_token = bytearray()
    source_tag = f"source-{image_source_commit}"
    push_evidence_path = receipt_directory / DOCKER_PUSH_EVIDENCE_FILE
    publisher_root = receipt_directory / "ephemeral-publisher"
    _secure_ephemeral_directory(publisher_root)
    azure_config = _secure_ephemeral_directory(publisher_root / "azure-config")
    docker_config = _secure_ephemeral_directory(publisher_root / "docker-config")
    publisher_environment = {
        "AZURE_CONFIG_DIR": str(azure_config),
        "DOCKER_CONFIG": str(docker_config),
    }
    cleanup_at_raw = state.get("cleanupAtUtc")
    if not isinstance(cleanup_at_raw, str):
        _fail("cleanup-binding-missing")
    try:
        cleanup_at = datetime.strptime(cleanup_at_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        _fail("cleanup-binding-missing")
    try:
        (
            publisher_app_id,
            publisher_object_id,
            tenant_id,
            certificate_path,
        ) = _create_ephemeral_publisher(
            ledger=ledger,
            publisher_directory=publisher_root,
        )
        publication.advance(PublicationState.PUBLISHER_CREATED)
        _validate_publisher_role_inventory(
            _publisher_role_rows(
                subscription_id=subscription_id,
                publisher_app_id=publisher_app_id,
            ),
            publisher_object_id=publisher_object_id,
            registry_scope=registry_scope,
            acr_push_role_id=str(rbac["acrPushRoleDefinitionId"]),
            assignment_required=False,
        )
        _publisher_login(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            certificate_path=certificate_path,
            environment=publisher_environment,
        )
        _prove_initial_publisher_denial(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            environment=publisher_environment,
        )
        _verify_cleanup_control(subscription_id, cleanup_at)
        assignment_id = _temporary_publisher_role_assignment(
            subscription_id=subscription_id,
            publisher_app_id=publisher_app_id,
            publisher_object_id=publisher_object_id,
            role_id=str(rbac["acrPushRoleDefinitionId"]),
            scope=registry_scope,
        )
        publication.advance(PublicationState.UPLOAD_AUTHORITY_READY)
        state["temporaryRegistryAssignmentId"] = assignment_id
        _replace_state(state_path, state)
        _run(
            ("az", "logout", "--only-show-errors", "--output", "none"),
            environment_overrides=publisher_environment,
        )
        _reset_ephemeral_directory(azure_config)
        _publisher_login(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            certificate_path=certificate_path,
            environment=publisher_environment,
        )
        refresh_token, access_token = _wait_for_publisher_access(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            environment=publisher_environment,
        )
        _docker_login_with_refresh_token(
            refresh_token, environment=publisher_environment
        )
        refresh_token.clear()
        try:
            _assert_source_tag_absent(
                source_tag=source_tag,
                access_token=access_token,
            )
            with _attribution_scope(
                lifecycle_substage="immutable-image-publication",
                expected_authorization="allow",
            ):
                verify_private_registry_publication_path(
                    repository_head=image_source_commit
                )
                try:
                    pushed_digest = _docker_push_prebuilt_image(
                        image_by_tag,
                        source_tag=source_tag,
                        environment=publisher_environment,
                        access_token=access_token,
                        evidence_path=push_evidence_path,
                    )
                except BaseException as push_error:
                    try:
                        verify_private_registry_publication_path(
                            repository_head=image_source_commit
                        )
                    except BaseException as probe_error:
                        raise PublicationAttemptFailure(
                            push_error, probe_error
                        ) from probe_error
                    raise
                verify_private_registry_publication_path(
                    repository_head=image_source_commit
                )
            resolved_digest = _acr_manifest_digest(access_token, reference=source_tag)
            if resolved_digest != pushed_digest:
                _fail("registry-pushed-digest-mismatch")
            raw_digest = pushed_digest
            publication.advance(PublicationState.IMAGE_PUSHED)
            if _acr_manifest_digest(access_token, reference=raw_digest) != raw_digest:
                _fail("registry-immutable-digest-mismatch")
            publication.advance(PublicationState.IMMUTABLE_MANIFEST_PROVED)
            immutable_reference = f"{REGISTRY_HOST}/opencanvas-api@{raw_digest}"
            if IMAGE_DIGEST.fullmatch(immutable_reference) is None:
                _fail("registry-immutable-reference-malformed")
            _run(
                ("docker", "pull", immutable_reference),
                timeout_seconds=DEPLOYMENT_TIMEOUT_SECONDS,
                environment_overrides=publisher_environment,
            )
            revocation_probe = (
                f"{REGISTRY_HOST}/opencanvas-api:revocation-probe-"
                f"{str(ledger['ledgerIntegritySha256'])[:12]}"
            )
            _run(
                ("docker", "tag", immutable_reference, revocation_probe),
                environment_overrides=publisher_environment,
            )
        except BaseException:
            raise
        finally:
            _run(
                ("docker", "logout", REGISTRY_HOST),
                environment_overrides=publisher_environment,
            )
            refresh_token.clear()
            access_token.clear()
            _reset_ephemeral_directory(docker_config)

        _delete_assignment(subscription_id, assignment_id)
        assignment_id = None
        publication.advance(PublicationState.UPLOAD_AUTHORITY_REVOKED)
        state["temporaryRegistryAssignmentId"] = None
        _replace_state(state_path, state)
        _wait_for_publisher_role_inventory(
            subscription_id=subscription_id,
            publisher_app_id=publisher_app_id,
            publisher_object_id=publisher_object_id,
            registry_scope=registry_scope,
            acr_push_role_id=str(rbac["acrPushRoleDefinitionId"]),
            assignment_required=False,
        )
        _run(
            ("az", "logout", "--only-show-errors", "--output", "none"),
            environment_overrides=publisher_environment,
        )
        _reset_ephemeral_directory(azure_config)
        _reset_ephemeral_directory(docker_config)
        _publisher_login(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            certificate_path=certificate_path,
            environment=publisher_environment,
        )
        denial_refresh_token = _wait_for_publisher_denial(
            publisher_app_id=publisher_app_id,
            tenant_id=tenant_id,
            environment=publisher_environment,
        )
        try:
            _docker_login_with_refresh_token(
                denial_refresh_token, environment=publisher_environment
            )
        finally:
            denial_refresh_token.clear()
        try:
            for probe in (
                ("docker", "manifest", "inspect", immutable_reference),
                ("docker", "pull", immutable_reference),
                ("docker", "push", revocation_probe),
            ):
                _wait_for_denial(
                    probe,
                    endpoint_host=REGISTRY_HOST,
                    environment_overrides=publisher_environment,
                )
        finally:
            _run(
                ("docker", "logout", REGISTRY_HOST),
                environment_overrides=publisher_environment,
            )
            _reset_ephemeral_directory(docker_config)
        denial_proved = True
        _verify_cleanup_control(subscription_id, cleanup_at)
        _delete_ephemeral_publisher(
            publisher_app_id=publisher_app_id,
            publisher_object_id=publisher_object_id,
        )
        publisher_deleted = True
        if immutable_reference is None or raw_digest is None:
            _fail("publisher-immutable-image-identity-missing")
        # The publisher has now been denied and deleted.  Only a distinct
        # pull/delete finalizer may issue the exact source-tag DELETE.
        from infra.milestone_7_7 import acr_tag_finalization

        with _attribution_scope(
            lifecycle_substage="mutable-tag-finalization",
            expected_authorization="allow",
        ):
            finalization = acr_tag_finalization.finalize_current_publication(
                ledger=ledger,
                subscription_id=subscription_id,
                receipt_directory=receipt_directory,
                source_tag=source_tag,
                manifest_digest=raw_digest,
                registry_config_digest=str(record["configDigest"]),
                publication=publication,
            )
        if (
            finalization.get("sourceTagAbsent") is not True
            or finalization.get("immutableManifestRetained") is not True
        ):
            _fail("publisher-finalizer-evidence-invalid")
        publication.advance(PublicationState.PUBLICATION_COMPLETE)
        publication.assert_complete()
        _run(
            (
                "docker",
                "image",
                "rm",
                "--force",
                revocation_probe,
                immutable_reference,
                image_by_tag,
            ),
            environment_overrides=publisher_environment,
        )
        _remove_ephemeral_publisher_directory(publisher_root)
        return immutable_reference
    finally:
        refresh_token.clear()
        access_token.clear()
        if assignment_id is not None:
            _delete_assignment(subscription_id, assignment_id)
            state["temporaryRegistryAssignmentId"] = None
            _replace_state(state_path, state)
        if not publisher_deleted and publisher_app_id is not None:
            if publisher_object_id is None:
                _delete_ephemeral_publisher_by_app_id(publisher_app_id)
            else:
                _delete_ephemeral_publisher(
                    publisher_app_id=publisher_app_id,
                    publisher_object_id=publisher_object_id,
                )
            publisher_deleted = True
        if publisher_root.exists():
            _remove_ephemeral_publisher_directory(publisher_root)
        if denial_proved and not publisher_deleted:
            _fail("publisher-identity-state-malformed")


def _private_path(subscription_id: str) -> dict[str, JsonValue]:
    queries: tuple[tuple[str, str, str, str, dict[str, JsonValue]], ...] = (
        (
            "Microsoft.KeyVault/vaults",
            KEY_VAULT,
            "2026-02-01",
            "{state:properties.provisioningState,public:properties.publicNetworkAccess}",
            {"public": "Disabled", "state": "Succeeded"},
        ),
        (
            "Microsoft.ContainerRegistry/registries",
            REGISTRY,
            "2025-11-01",
            "{state:properties.provisioningState,public:properties.publicNetworkAccess}",
            {"public": "Disabled", "state": "Succeeded"},
        ),
        (
            "Microsoft.Network/privateEndpoints",
            "pe-mobius77-keyvault",
            "2026-01-01",
            "{state:properties.provisioningState,approval:properties.privateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status}",
            {"approval": "Approved", "state": "Succeeded"},
        ),
        (
            "Microsoft.Network/privateEndpoints",
            "pe-mobius77-acr",
            "2026-01-01",
            "{state:properties.provisioningState,approval:properties.privateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status}",
            {"approval": "Approved", "state": "Succeeded"},
        ),
        (
            "Microsoft.Network/virtualNetworkGateways",
            "vpngw-mobius77-staging",
            "2026-01-01",
            "{state:properties.provisioningState,active:properties.activeActive}",
            {"active": False, "state": "Succeeded"},
        ),
    )
    for resource_type, name, api_version, projection, expected in queries:
        value = _run(
            (
                "az",
                "resource",
                "show",
                "--resource-group",
                TARGET_GROUP,
                "--resource-type",
                resource_type,
                "--name",
                name,
                "--api-version",
                api_version,
                "--subscription",
                subscription_id,
                "--query",
                projection,
                "--output",
                "json",
                "--only-show-errors",
            ),
            require_json=True,
        )
        if value != expected:
            _fail("private-path-resource-state-unproved")
    _private_tls_endpoint(KEY_VAULT_HOST)
    _private_tls_endpoint(REGISTRY_HOST)
    return {
        "status": "private-entry-path-proved",
        "private-key-vault": True,
        "private-registry": True,
        "private-endpoint-count": 2,
        "p2s-gateway": True,
        "client-dns-and-tls-proved": True,
        "secret-value-accessed": False,
    }


def _private_path_stage(
    *, ledger: Mapping[str, JsonValue], subscription_id: str, receipt_directory: Path
) -> dict[str, JsonValue]:
    state_path = _state_path(receipt_directory)
    state = _read_current_transient_state(state_path, ledger=ledger)
    if (
        state.get("resumableCheckpoint") != "secure-manual-entry"
        or state.get("privatePathProved") is not False
    ):
        _fail("private-path-stage-prerequisite-missing")
    result = _private_path(subscription_id)
    state["privatePathProved"] = True
    state["lastCompletedStage"] = "private-path-verification"
    _replace_state(state_path, state)
    return result


def _publication_result_integrity(value: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(
        PUBLICATION_RESULT_DOMAIN + canonical_bytes(dict(value))
    ).hexdigest()


def _publish_api_image_stage(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    prebuilt_image_record: Path,
) -> dict[str, JsonValue]:
    state_path = _state_path(receipt_directory)
    state = _read_current_transient_state(state_path, ledger=ledger)
    if (
        state.get("resumableCheckpoint") != "secure-manual-entry"
        or state.get("privatePathProved") is not True
        or state.get("publishedManifestDigest") is not None
        or state.get("publisherRevocationProved") is not False
    ):
        _fail("publication-stage-prerequisite-missing")
    with _attribution_scope(
        lifecycle_substage="immutable-image-publication",
        expected_authorization="allow",
    ):
        immutable_reference = _publish_api_image(
            ledger=ledger,
            subscription_id=subscription_id,
            receipt_directory=receipt_directory,
            prebuilt_image_record=prebuilt_image_record,
        )
    if IMAGE_DIGEST.fullmatch(immutable_reference) is None:
        _fail("published-image-reference-invalid")
    manifest_digest = immutable_reference.rsplit("@", 1)[1]
    published = ledger.get("publishedImage")
    if not isinstance(published, dict):
        _fail("pending-image-ledger-binding-missing")
    result: dict[str, JsonValue] = {
        "configDigest": published.get("imageConfigDigest"),
        "imageBuildInputSha256": published.get("imageBuildInputSha256"),
        "imageSourceCommit": published.get("imageSourceCommit"),
        "localImageId": published.get("localImageId"),
        "manifestDigest": manifest_digest,
        "platform": published.get("platform"),
        "publisherResidueZero": True,
        "repository": published.get("repository"),
        "sourceTagRemoved": True,
    }
    integrity = _publication_result_integrity(result)
    state["publicationEvidenceIntegritySha256"] = integrity
    state["publishedManifestDigest"] = manifest_digest
    state["publisherRevocationProved"] = True
    state["lastCompletedStage"] = "publish-api-image"
    state["resumableCheckpoint"] = "post-secret-provisioning"
    _replace_state(state_path, state)
    return {
        "evidence-integrity-sha256": integrity,
        "immutable-image-published": True,
        "publisher-revoked": True,
        "secret-value-accessed": False,
        "status": "image-published-and-revoked",
    }


def _reconcile_published_api_image(
    *, ledger: Mapping[str, JsonValue], state: Mapping[str, JsonValue]
) -> str:
    published = ledger.get("publishedImage")
    if not isinstance(published, dict):
        _fail("published-image-ledger-binding-missing")
    if published.get("publicationState") != "pending":
        _fail("published-image-ledger-binding-invalid")
    digest = state.get("publishedManifestDigest")
    repository = published.get("repository")
    if (
        repository != PUBLISHER_REPOSITORY
        or not isinstance(digest, str)
        or RAW_IMAGE_DIGEST.fullmatch(digest) is None
        or state.get("publisherRevocationProved") is not True
        or not isinstance(state.get("publicationEvidenceIntegritySha256"), str)
    ):
        _fail("published-image-ledger-binding-invalid")
    return f"{REGISTRY_HOST}/{PUBLISHER_REPOSITORY}@{digest}"
