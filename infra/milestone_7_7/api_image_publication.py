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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    PublicationMode,
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
ALREADY_PUSHED_RETAINED_RECORD_VERSION = (
    "mobius.milestone-7.7.already-pushed-publication.v1"
)
ALREADY_PUSHED_RECORD_VERSION = "mobius.milestone-7.7.already-pushed-publication.v2"
ALREADY_PUSHED_RECORD_DOMAIN = (
    b"solarplexus-mobius/milestone-7.7/already-pushed-publication/v1\x00"
)
ALREADY_PUSHED_OBSERVATION_VERSION = (
    "mobius.milestone-7.7.already-pushed-registry-observation.v1"
)
ALREADY_PUSHED_OBSERVATION_DOMAIN = (
    b"solarplexus-mobius/milestone-7.7/already-pushed-registry-observation/v1\x00"
)
HISTORICAL_PUSH_EVIDENCE_VERSION = "mobius.milestone-7.7.historical-push-evidence.v1"
HISTORICAL_PUSH_EVIDENCE_DOMAIN = (
    b"solarplexus-mobius/milestone-7.7/historical-push-evidence/v1\x00"
)
LIVE_REGISTRY_OBSERVATION_VERSION = (
    "mobius.milestone-7.7.live-registry-publication-observation.v1"
)
LIVE_REGISTRY_OBSERVATION_DOMAIN = (
    b"solarplexus-mobius/milestone-7.7/live-registry-publication-observation/v1\x00"
)
RECONSTRUCTION_AUTHORIZATION_VERSION = (
    "mobius.milestone-7.7.already-pushed-reconstruction-authorization.v1"
)
RECONSTRUCTION_AUTHORIZATION_DOMAIN = b"solarplexus-mobius/milestone-7.7/already-pushed-reconstruction-authorization/v1\x00"
RECONCILIATION_RECEIPT_VERSION = (
    "mobius.milestone-7.7.already-pushed-reconciliation-receipt.v1"
)
RECONCILIATION_RECEIPT_DOMAIN = (
    b"solarplexus-mobius/milestone-7.7/already-pushed-reconciliation-receipt/v1\x00"
)
RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF = (
    "RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF"
)
RETAINED_ORIGINAL_PUSH_EVIDENCE = "RETAINED_ORIGINAL_PUSH_EVIDENCE"
LIVE_READ_ONLY_REGISTRY_PROOF = "LIVE_READ_ONLY_REGISTRY_PROOF"
RECONSTRUCTION_ALGORITHM_VERSION = "m7.7-already-pushed-reconstruction-v1"
LIVE_REGISTRY_OBSERVATION_MAXIMUM_AGE = timedelta(minutes=15)
RECONCILIATION_OPERATION_ID = "reconcile-already-pushed-publication"
RECONSTRUCTION_PROHIBITED_OPERATIONS = (
    "build",
    "push",
    "retag",
    "upload-publisher-creation",
    "acrpush",
    "manifest-deletion",
    "repository-deletion",
)
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


@dataclass(frozen=True)
class AlreadyPushedPublicationRecord:
    """Integrity-bound evidence that permits reconciliation, never upload."""

    control_plane_head: str
    image_source_commit: str
    build_input_sha256: str
    local_image_id: str
    config_digest: str
    registry_manifest_digest: str
    platform: str
    registry_host: str
    repository: str
    source_tag: str
    push_started_at_utc: str
    push_completed_at_utc: str
    docker_exit_code: int
    docker_timed_out: bool
    stdout_sha256: str
    stderr_sha256: str
    publication_evidence_integrity: str
    cleanup_generation: int
    cleanup_deadline_utc: str
    prior_lifecycle_evidence: str
    operation_id: str
    evidence_provenance: str | None = None
    historical_evidence_integrity: str | None = None
    live_observation_integrity: str | None = None
    reconstruction_authorization_integrity: str | None = None
    reconstructed_at_utc: str | None = None
    reconstruction_algorithm_version: str | None = None

    def unsigned(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "schemaVersion": ALREADY_PUSHED_RETAINED_RECORD_VERSION,
            "controlPlaneHead": self.control_plane_head,
            "imageSourceCommit": self.image_source_commit,
            "imageBuildInputSha256": self.build_input_sha256,
            "localImageId": self.local_image_id,
            "imageConfigDigest": self.config_digest,
            "registryManifestDigest": self.registry_manifest_digest,
            "platform": self.platform,
            "registryHost": self.registry_host,
            "repository": self.repository,
            "sourceTag": self.source_tag,
            "pushStartedAtUtc": self.push_started_at_utc,
            "pushCompletedAtUtc": self.push_completed_at_utc,
            "dockerExitCode": self.docker_exit_code,
            "dockerTimedOut": self.docker_timed_out,
            "stdoutSha256": self.stdout_sha256,
            "stderrSha256": self.stderr_sha256,
            "publicationEvidenceIntegritySha256": self.publication_evidence_integrity,
            "cleanupGeneration": self.cleanup_generation,
            "cleanupDeadlineUtc": self.cleanup_deadline_utc,
            "priorLifecycleEvidenceSha256": self.prior_lifecycle_evidence,
            "authorizedOperationId": self.operation_id,
        }
        reconstruction = (
            self.evidence_provenance,
            self.historical_evidence_integrity,
            self.live_observation_integrity,
            self.reconstruction_authorization_integrity,
            self.reconstructed_at_utc,
            self.reconstruction_algorithm_version,
        )
        if all(item is None for item in reconstruction):
            return value
        if any(item is None for item in reconstruction):
            _fail("already-pushed-record-reconstruction-fields-incomplete")
        return {
            **value,
            "schemaVersion": ALREADY_PUSHED_RECORD_VERSION,
            "evidenceProvenance": cast(str, self.evidence_provenance),
            "historicalEvidenceIntegritySha256": cast(
                str, self.historical_evidence_integrity
            ),
            "liveObservationIntegritySha256": cast(
                str, self.live_observation_integrity
            ),
            "reconstructionAuthorizationIntegritySha256": cast(
                str, self.reconstruction_authorization_integrity
            ),
            "reconstructedAtUtc": cast(str, self.reconstructed_at_utc),
            "reconstructionAlgorithmVersion": cast(
                str, self.reconstruction_algorithm_version
            ),
        }

    def as_json(self) -> dict[str, JsonValue]:
        unsigned = self.unsigned()
        return {
            **unsigned,
            "integritySha256": hashlib.sha256(
                ALREADY_PUSHED_RECORD_DOMAIN + canonical_bytes(unsigned)
            ).hexdigest(),
        }


@dataclass(frozen=True)
class AlreadyPushedRegistryObservation:
    """Sanitized, integrity-bound read-only registry truth for reconciliation."""

    registry_manifest_digest: str
    config_digest: str
    platform: str
    registry_host: str
    repository: str
    source_tag: str
    source_tag_present: bool
    observed_at_utc: str
    read_evidence_integrity: str

    def unsigned(self) -> dict[str, JsonValue]:
        return {
            "schemaVersion": ALREADY_PUSHED_OBSERVATION_VERSION,
            "registryManifestDigest": self.registry_manifest_digest,
            "imageConfigDigest": self.config_digest,
            "platform": self.platform,
            "registryHost": self.registry_host,
            "repository": self.repository,
            "sourceTag": self.source_tag,
            "sourceTagPresent": self.source_tag_present,
            "observedAtUtc": self.observed_at_utc,
            "readEvidenceIntegritySha256": self.read_evidence_integrity,
        }

    def as_json(self) -> dict[str, JsonValue]:
        unsigned = self.unsigned()
        return {
            **unsigned,
            "integritySha256": hashlib.sha256(
                ALREADY_PUSHED_OBSERVATION_DOMAIN + canonical_bytes(unsigned)
            ).hexdigest(),
        }


def validate_already_pushed_publication_record(
    value: Mapping[str, JsonValue], *, control_plane_head: str
) -> AlreadyPushedPublicationRecord:
    retained_required = {
        "schemaVersion",
        "controlPlaneHead",
        "imageSourceCommit",
        "imageBuildInputSha256",
        "localImageId",
        "imageConfigDigest",
        "registryManifestDigest",
        "platform",
        "registryHost",
        "repository",
        "sourceTag",
        "pushStartedAtUtc",
        "pushCompletedAtUtc",
        "dockerExitCode",
        "dockerTimedOut",
        "stdoutSha256",
        "stderrSha256",
        "publicationEvidenceIntegritySha256",
        "cleanupGeneration",
        "cleanupDeadlineUtc",
        "priorLifecycleEvidenceSha256",
        "authorizedOperationId",
        "integritySha256",
    }
    reconstruction_required = {
        "evidenceProvenance",
        "historicalEvidenceIntegritySha256",
        "liveObservationIntegritySha256",
        "reconstructionAuthorizationIntegritySha256",
        "reconstructedAtUtc",
        "reconstructionAlgorithmVersion",
    }
    version = value.get("schemaVersion")
    if version == ALREADY_PUSHED_RETAINED_RECORD_VERSION:
        required = retained_required
    elif version == ALREADY_PUSHED_RECORD_VERSION:
        required = retained_required | reconstruction_required
    else:
        _fail("already-pushed-record-fields-invalid")
    if set(value) != required:
        _fail("already-pushed-record-fields-invalid")
    unsigned = {key: value[key] for key in required - {"integritySha256"}}
    integrity = value.get("integritySha256")
    if (
        not isinstance(integrity, str)
        or HEX_SHA256.fullmatch(integrity) is None
        or integrity
        != hashlib.sha256(
            ALREADY_PUSHED_RECORD_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest()
    ):
        _fail("already-pushed-record-integrity-invalid")
    strings = (
        "controlPlaneHead",
        "imageSourceCommit",
        "imageBuildInputSha256",
        "localImageId",
        "imageConfigDigest",
        "registryManifestDigest",
        "platform",
        "registryHost",
        "repository",
        "sourceTag",
        "pushStartedAtUtc",
        "pushCompletedAtUtc",
        "stdoutSha256",
        "stderrSha256",
        "publicationEvidenceIntegritySha256",
        "cleanupDeadlineUtc",
        "priorLifecycleEvidenceSha256",
        "authorizedOperationId",
    )
    if (
        value.get("controlPlaneHead") != control_plane_head
        or any(not isinstance(value[key], str) for key in strings)
        or any(
            HEX_SHA256.fullmatch(str(value[key])) is None
            for key in (
                "imageBuildInputSha256",
                "stdoutSha256",
                "stderrSha256",
                "publicationEvidenceIntegritySha256",
                "priorLifecycleEvidenceSha256",
            )
        )
        or HEX_SHA40.fullmatch(str(value["imageSourceCommit"])) is None
        or RAW_IMAGE_DIGEST.fullmatch(str(value["localImageId"])) is None
        or RAW_IMAGE_DIGEST.fullmatch(str(value["imageConfigDigest"])) is None
        or RAW_IMAGE_DIGEST.fullmatch(str(value["registryManifestDigest"])) is None
        or value.get("platform") != API_IMAGE_PLATFORM
        or value.get("registryHost") != REGISTRY_HOST
        or value.get("repository") != PUBLISHER_REPOSITORY
        or str(value.get("sourceTag")) != f"source-{value['imageSourceCommit']}"
        or type(value.get("dockerExitCode")) is not int
        or value.get("dockerExitCode") != 0
        or value.get("dockerTimedOut") is not False
        or type(value.get("cleanupGeneration")) is not int
        or value.get("cleanupGeneration") != 2
        or value.get("authorizedOperationId") != "reconcile-already-pushed-publication"
    ):
        _fail("already-pushed-record-binding-invalid")
    try:
        push_started = datetime.strptime(
            str(value["pushStartedAtUtc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        push_completed = datetime.strptime(
            str(value["pushCompletedAtUtc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        cleanup_deadline = datetime.strptime(
            str(value["cleanupDeadlineUtc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except ValueError:
        _fail("already-pushed-record-time-invalid")
    if push_started.year < 2026 or not (
        push_started < push_completed < cleanup_deadline
    ):
        _fail("already-pushed-record-time-invalid")
    provenance = RETAINED_ORIGINAL_PUSH_EVIDENCE
    historical_integrity: str | None = None
    observation_integrity: str | None = None
    authorization_integrity: str | None = None
    reconstructed_at: str | None = None
    algorithm_version: str | None = None
    if version == ALREADY_PUSHED_RECORD_VERSION:
        provenance = value.get("evidenceProvenance")  # type: ignore[assignment]
        reconstruction_values = (
            value.get("historicalEvidenceIntegritySha256"),
            value.get("liveObservationIntegritySha256"),
            value.get("reconstructionAuthorizationIntegritySha256"),
        )
        if (
            provenance != RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF
            or any(
                not isinstance(item, str) or HEX_SHA256.fullmatch(item) is None
                for item in reconstruction_values
            )
            or value.get("reconstructionAlgorithmVersion")
            != RECONSTRUCTION_ALGORITHM_VERSION
            or not isinstance(value.get("reconstructedAtUtc"), str)
        ):
            _fail("already-pushed-record-reconstruction-binding-invalid")
        try:
            reconstructed = datetime.strptime(
                str(value["reconstructedAtUtc"]), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except ValueError:
            _fail("already-pushed-record-reconstruction-time-invalid")
        if reconstructed.year < 2026:
            _fail("already-pushed-record-reconstruction-time-invalid")
        historical_integrity = str(value["historicalEvidenceIntegritySha256"])
        observation_integrity = str(value["liveObservationIntegritySha256"])
        authorization_integrity = str(
            value["reconstructionAuthorizationIntegritySha256"]
        )
        reconstructed_at = str(value["reconstructedAtUtc"])
        algorithm_version = str(value["reconstructionAlgorithmVersion"])
    return AlreadyPushedPublicationRecord(
        control_plane_head=str(value["controlPlaneHead"]),
        image_source_commit=str(value["imageSourceCommit"]),
        build_input_sha256=str(value["imageBuildInputSha256"]),
        local_image_id=str(value["localImageId"]),
        config_digest=str(value["imageConfigDigest"]),
        registry_manifest_digest=str(value["registryManifestDigest"]),
        platform=str(value["platform"]),
        registry_host=str(value["registryHost"]),
        repository=str(value["repository"]),
        source_tag=str(value["sourceTag"]),
        push_started_at_utc=str(value["pushStartedAtUtc"]),
        push_completed_at_utc=str(value["pushCompletedAtUtc"]),
        docker_exit_code=cast(int, value["dockerExitCode"]),
        docker_timed_out=cast(bool, value["dockerTimedOut"]),
        stdout_sha256=str(value["stdoutSha256"]),
        stderr_sha256=str(value["stderrSha256"]),
        publication_evidence_integrity=str(value["publicationEvidenceIntegritySha256"]),
        cleanup_generation=cast(int, value["cleanupGeneration"]),
        cleanup_deadline_utc=str(value["cleanupDeadlineUtc"]),
        prior_lifecycle_evidence=str(value["priorLifecycleEvidenceSha256"]),
        operation_id=str(value["authorizedOperationId"]),
        evidence_provenance=provenance,
        historical_evidence_integrity=historical_integrity,
        live_observation_integrity=observation_integrity,
        reconstruction_authorization_integrity=authorization_integrity,
        reconstructed_at_utc=reconstructed_at,
        reconstruction_algorithm_version=algorithm_version,
    )


def _integrity_value(domain: bytes, unsigned: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(domain + canonical_bytes(dict(unsigned))).hexdigest()


def _parse_evidence_utc(value: object, *, error: str) -> datetime:
    if not isinstance(value, str):
        _fail(error)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(error)
    if parsed.year < 2026:
        _fail(error)
    return parsed


@dataclass(frozen=True)
class HistoricalPushEvidence:
    """Immutable facts actually retained by the successful ordinary Docker push."""

    image_source_commit: str
    build_input_sha256: str
    local_image_id: str
    config_digest: str
    platform: str
    repository: str
    source_tag: str
    push_started_at_utc: str
    push_completed_at_utc: str
    docker_exit_code: int
    docker_timed_out: bool
    stdout_sha256: str
    stderr_sha256: str
    docker_push_evidence_integrity: str
    prebuilt_image_evidence_integrity: str
    prior_lifecycle_evidence_integrity: str
    registry_host_sha256: str

    def unsigned(self) -> dict[str, JsonValue]:
        return {
            "schemaVersion": HISTORICAL_PUSH_EVIDENCE_VERSION,
            "imageSourceCommit": self.image_source_commit,
            "imageBuildInputSha256": self.build_input_sha256,
            "localImageId": self.local_image_id,
            "imageConfigDigest": self.config_digest,
            "platform": self.platform,
            "repository": self.repository,
            "sourceTag": self.source_tag,
            "pushStartedAtUtc": self.push_started_at_utc,
            "pushCompletedAtUtc": self.push_completed_at_utc,
            "dockerExitCode": self.docker_exit_code,
            "dockerTimedOut": self.docker_timed_out,
            "stdoutSha256": self.stdout_sha256,
            "stderrSha256": self.stderr_sha256,
            "dockerPushEvidenceIntegritySha256": self.docker_push_evidence_integrity,
            "prebuiltImageEvidenceIntegritySha256": self.prebuilt_image_evidence_integrity,
            "priorLifecycleEvidenceIntegritySha256": self.prior_lifecycle_evidence_integrity,
            "registryHostSha256": self.registry_host_sha256,
        }

    def as_json(self) -> dict[str, JsonValue]:
        unsigned = self.unsigned()
        return {
            **unsigned,
            "integritySha256": _integrity_value(
                HISTORICAL_PUSH_EVIDENCE_DOMAIN, unsigned
            ),
        }


def validate_historical_push_evidence(
    value: Mapping[str, JsonValue],
) -> HistoricalPushEvidence:
    required = {
        "schemaVersion",
        "imageSourceCommit",
        "imageBuildInputSha256",
        "localImageId",
        "imageConfigDigest",
        "platform",
        "repository",
        "sourceTag",
        "pushStartedAtUtc",
        "pushCompletedAtUtc",
        "dockerExitCode",
        "dockerTimedOut",
        "stdoutSha256",
        "stderrSha256",
        "dockerPushEvidenceIntegritySha256",
        "prebuiltImageEvidenceIntegritySha256",
        "priorLifecycleEvidenceIntegritySha256",
        "registryHostSha256",
        "integritySha256",
    }
    if set(value) != required:
        _fail("historical-push-evidence-fields-invalid")
    unsigned = {key: value[key] for key in required - {"integritySha256"}}
    if (
        value.get("schemaVersion") != HISTORICAL_PUSH_EVIDENCE_VERSION
        or value.get("integritySha256")
        != _integrity_value(HISTORICAL_PUSH_EVIDENCE_DOMAIN, unsigned)
        or HEX_SHA40.fullmatch(str(value.get("imageSourceCommit"))) is None
        or any(
            HEX_SHA256.fullmatch(str(value.get(key))) is None
            for key in (
                "imageBuildInputSha256",
                "stdoutSha256",
                "stderrSha256",
                "dockerPushEvidenceIntegritySha256",
                "prebuiltImageEvidenceIntegritySha256",
                "priorLifecycleEvidenceIntegritySha256",
                "registryHostSha256",
            )
        )
        or RAW_IMAGE_DIGEST.fullmatch(str(value.get("localImageId"))) is None
        or RAW_IMAGE_DIGEST.fullmatch(str(value.get("imageConfigDigest"))) is None
        or value.get("platform") != API_IMAGE_PLATFORM
        or value.get("repository") != PUBLISHER_REPOSITORY
        or value.get("sourceTag") != f"source-{value['imageSourceCommit']}"
        or type(value.get("dockerExitCode")) is not int
        or value.get("dockerExitCode") != 0
        or value.get("dockerTimedOut") is not False
    ):
        _fail("historical-push-evidence-binding-invalid")
    started = _parse_evidence_utc(
        value.get("pushStartedAtUtc"), error="historical-push-evidence-time-invalid"
    )
    completed = _parse_evidence_utc(
        value.get("pushCompletedAtUtc"), error="historical-push-evidence-time-invalid"
    )
    if started >= completed:
        _fail("historical-push-evidence-time-invalid")
    return HistoricalPushEvidence(
        image_source_commit=str(value["imageSourceCommit"]),
        build_input_sha256=str(value["imageBuildInputSha256"]),
        local_image_id=str(value["localImageId"]),
        config_digest=str(value["imageConfigDigest"]),
        platform=str(value["platform"]),
        repository=str(value["repository"]),
        source_tag=str(value["sourceTag"]),
        push_started_at_utc=str(value["pushStartedAtUtc"]),
        push_completed_at_utc=str(value["pushCompletedAtUtc"]),
        docker_exit_code=cast(int, value["dockerExitCode"]),
        docker_timed_out=cast(bool, value["dockerTimedOut"]),
        stdout_sha256=str(value["stdoutSha256"]),
        stderr_sha256=str(value["stderrSha256"]),
        docker_push_evidence_integrity=str(value["dockerPushEvidenceIntegritySha256"]),
        prebuilt_image_evidence_integrity=str(
            value["prebuiltImageEvidenceIntegritySha256"]
        ),
        prior_lifecycle_evidence_integrity=str(
            value["priorLifecycleEvidenceIntegritySha256"]
        ),
        registry_host_sha256=str(value["registryHostSha256"]),
    )


def historical_push_evidence_from_retained_artifacts(
    *,
    docker_push_evidence: Mapping[str, JsonValue],
    prebuilt_image_evidence: Mapping[str, JsonValue],
    prior_lifecycle_evidence_integrity: str,
) -> HistoricalPushEvidence:
    """Validate immutable retained artifacts without inspecting Docker or Azure."""
    docker_integrity = docker_push_evidence.get("integritySha256")
    docker_unsigned = {
        key: item
        for key, item in docker_push_evidence.items()
        if key != "integritySha256"
    }
    if (
        docker_push_evidence.get("schemaVersion") != DOCKER_PUSH_EVIDENCE_VERSION
        or not isinstance(docker_integrity, str)
        or HEX_SHA256.fullmatch(docker_integrity) is None
        or docker_integrity
        != _integrity_value(DOCKER_PUSH_EVIDENCE_DOMAIN, docker_unsigned)
        or docker_push_evidence.get("status") != "SUCCEEDED"
        or docker_push_evidence.get("actualExitCode") != 0
        or docker_push_evidence.get("timedOut") is not False
        or docker_push_evidence.get("rawOutputRetained") is not False
        or docker_push_evidence.get("secretValueRetained") is not False
        or docker_push_evidence.get("repository") != PUBLISHER_REPOSITORY
        or not isinstance(docker_push_evidence.get("sourceTag"), str)
        or not isinstance(docker_push_evidence.get("startedAtUtc"), str)
        or not isinstance(docker_push_evidence.get("finishedAtUtc"), str)
        or any(
            not isinstance(docker_push_evidence.get(key), str)
            or HEX_SHA256.fullmatch(str(docker_push_evidence[key])) is None
            for key in (
                "stdoutSanitizedSha256",
                "stderrSanitizedSha256",
                "registryHostSha256",
            )
        )
    ):
        _fail("historical-push-evidence-artifact-invalid")
    prebuilt_integrity = prebuilt_image_evidence.get("integritySha256")
    prebuilt_unsigned = {
        key: item
        for key, item in prebuilt_image_evidence.items()
        if key != "integritySha256"
    }
    if (
        prebuilt_image_evidence.get("schemaVersion") != PREBUILT_IMAGE_RECORD_VERSION
        or not isinstance(prebuilt_integrity, str)
        or HEX_SHA256.fullmatch(prebuilt_integrity) is None
        or prebuilt_integrity
        != _integrity_value(PREBUILT_IMAGE_RECORD_DOMAIN, prebuilt_unsigned)
        or prebuilt_image_evidence.get("completionStatus") != "READY"
        or not isinstance(prebuilt_image_evidence.get("repositoryHead"), str)
        or HEX_SHA40.fullmatch(str(prebuilt_image_evidence["repositoryHead"])) is None
        or HEX_SHA256.fullmatch(str(prebuilt_image_evidence.get("buildInputSha256")))
        is None
        or RAW_IMAGE_DIGEST.fullmatch(str(prebuilt_image_evidence.get("imageId")))
        is None
        or prebuilt_image_evidence.get("configDigest")
        != prebuilt_image_evidence.get("imageId")
        or prebuilt_image_evidence.get("platform") != API_IMAGE_PLATFORM
        or not isinstance(prior_lifecycle_evidence_integrity, str)
        or HEX_SHA256.fullmatch(prior_lifecycle_evidence_integrity) is None
    ):
        _fail("historical-push-evidence-artifact-invalid")
    source_commit = str(prebuilt_image_evidence["repositoryHead"])
    if docker_push_evidence["sourceTag"] != f"source-{source_commit}":
        _fail("historical-push-evidence-artifact-identity-mismatch")
    historical = HistoricalPushEvidence(
        image_source_commit=source_commit,
        build_input_sha256=str(prebuilt_image_evidence["buildInputSha256"]),
        local_image_id=str(prebuilt_image_evidence["imageId"]),
        config_digest=str(prebuilt_image_evidence["configDigest"]),
        platform=API_IMAGE_PLATFORM,
        repository=PUBLISHER_REPOSITORY,
        source_tag=str(docker_push_evidence["sourceTag"]),
        push_started_at_utc=str(docker_push_evidence["startedAtUtc"]),
        push_completed_at_utc=str(docker_push_evidence["finishedAtUtc"]),
        docker_exit_code=0,
        docker_timed_out=False,
        stdout_sha256=str(docker_push_evidence["stdoutSanitizedSha256"]),
        stderr_sha256=str(docker_push_evidence["stderrSanitizedSha256"]),
        docker_push_evidence_integrity=docker_integrity,
        prebuilt_image_evidence_integrity=prebuilt_integrity,
        prior_lifecycle_evidence_integrity=prior_lifecycle_evidence_integrity,
        registry_host_sha256=str(docker_push_evidence["registryHostSha256"]),
    )
    return validate_historical_push_evidence(historical.as_json())


@dataclass(frozen=True)
class LiveRegistryPublicationObservation:
    """Sanitized future read-only registry proof; never a historical claim."""

    observed_at_utc: str
    registry_host: str
    repository: str
    source_tag: str
    source_tag_present: bool
    source_tag_digest: str | None
    registry_manifest_digest: str
    raw_manifest_body_sha256: str
    config_digest: str
    platform: str
    media_type: str
    request_sequence: tuple[str, ...]
    response_statuses: tuple[str, ...]
    correlation_hashes: tuple[str, ...]
    mutation_performed: bool

    def unsigned(self) -> dict[str, JsonValue]:
        return {
            "schemaVersion": LIVE_REGISTRY_OBSERVATION_VERSION,
            "observationClassification": LIVE_READ_ONLY_REGISTRY_PROOF,
            "observedAtUtc": self.observed_at_utc,
            "registryHost": self.registry_host,
            "repository": self.repository,
            "sourceTag": self.source_tag,
            "sourceTagPresent": self.source_tag_present,
            "sourceTagDigest": self.source_tag_digest,
            "registryManifestDigest": self.registry_manifest_digest,
            "rawManifestBodySha256": self.raw_manifest_body_sha256,
            "imageConfigDigest": self.config_digest,
            "platform": self.platform,
            "mediaType": self.media_type,
            "readOnlyRequestSequence": list(self.request_sequence),
            "sanitizedResponseStatuses": list(self.response_statuses),
            "correlationIdHashes": list(self.correlation_hashes),
            "mutationPerformed": self.mutation_performed,
        }

    def as_json(self) -> dict[str, JsonValue]:
        unsigned = self.unsigned()
        return {
            **unsigned,
            "integritySha256": _integrity_value(
                LIVE_REGISTRY_OBSERVATION_DOMAIN, unsigned
            ),
        }


def validate_live_registry_publication_observation(
    value: Mapping[str, JsonValue], *, now_utc: datetime
) -> LiveRegistryPublicationObservation:
    required = {
        "schemaVersion",
        "observationClassification",
        "observedAtUtc",
        "registryHost",
        "repository",
        "sourceTag",
        "sourceTagPresent",
        "sourceTagDigest",
        "registryManifestDigest",
        "rawManifestBodySha256",
        "imageConfigDigest",
        "platform",
        "mediaType",
        "readOnlyRequestSequence",
        "sanitizedResponseStatuses",
        "correlationIdHashes",
        "mutationPerformed",
        "integritySha256",
    }
    if set(value) != required:
        _fail("live-registry-observation-fields-invalid")
    unsigned = {key: value[key] for key in required - {"integritySha256"}}
    if (
        value.get("schemaVersion") != LIVE_REGISTRY_OBSERVATION_VERSION
        or value.get("observationClassification") != LIVE_READ_ONLY_REGISTRY_PROOF
        or value.get("integritySha256")
        != _integrity_value(LIVE_REGISTRY_OBSERVATION_DOMAIN, unsigned)
        or value.get("registryHost") != REGISTRY_HOST
        or value.get("repository") != PUBLISHER_REPOSITORY
        or not isinstance(value.get("sourceTag"), str)
        or type(value.get("sourceTagPresent")) is not bool
        or value.get("platform") != API_IMAGE_PLATFORM
        or not isinstance(value.get("mediaType"), str)
        or not str(value["mediaType"]).startswith("application/")
        or RAW_IMAGE_DIGEST.fullmatch(str(value.get("registryManifestDigest"))) is None
        or RAW_IMAGE_DIGEST.fullmatch(str(value.get("imageConfigDigest"))) is None
        or HEX_SHA256.fullmatch(str(value.get("rawManifestBodySha256"))) is None
        or f"sha256:{value['rawManifestBodySha256']}"
        != value.get("registryManifestDigest")
        or value.get("mutationPerformed") is not False
    ):
        _fail("live-registry-observation-binding-invalid")
    tag_digest = value.get("sourceTagDigest")
    if (
        value["sourceTagPresent"] is True
        and RAW_IMAGE_DIGEST.fullmatch(str(tag_digest)) is None
    ) or (value["sourceTagPresent"] is False and tag_digest is not None):
        _fail("live-registry-observation-source-tag-invalid")
    request_sequence = value.get("readOnlyRequestSequence")
    statuses = value.get("sanitizedResponseStatuses")
    correlations = value.get("correlationIdHashes")
    if (
        not isinstance(request_sequence, list)
        or not request_sequence
        or not isinstance(statuses, list)
        or not statuses
        or not isinstance(correlations, list)
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"[a-z0-9-]{1,96}", item) is None
            or any(blocked in item for blocked in ("delete", "put", "post", "patch"))
            for item in request_sequence
        )
        or any(
            not isinstance(item, str) or re.fullmatch(r"[1-5][0-9]{2}", item) is None
            for item in statuses
        )
        or any(
            not isinstance(item, str) or HEX_SHA256.fullmatch(item) is None
            for item in correlations
        )
    ):
        _fail("live-registry-observation-sanitization-invalid")
    observed = _parse_evidence_utc(
        value.get("observedAtUtc"), error="live-registry-observation-time-invalid"
    )
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if observed > now or now - observed > LIVE_REGISTRY_OBSERVATION_MAXIMUM_AGE:
        _fail("live-registry-observation-stale")
    return LiveRegistryPublicationObservation(
        observed_at_utc=str(value["observedAtUtc"]),
        registry_host=str(value["registryHost"]),
        repository=str(value["repository"]),
        source_tag=str(value["sourceTag"]),
        source_tag_present=cast(bool, value["sourceTagPresent"]),
        source_tag_digest=cast(str | None, value["sourceTagDigest"]),
        registry_manifest_digest=str(value["registryManifestDigest"]),
        raw_manifest_body_sha256=str(value["rawManifestBodySha256"]),
        config_digest=str(value["imageConfigDigest"]),
        platform=str(value["platform"]),
        media_type=str(value["mediaType"]),
        request_sequence=tuple(cast(list[str], request_sequence)),
        response_statuses=tuple(cast(list[str], statuses)),
        correlation_hashes=tuple(cast(list[str], correlations)),
        mutation_performed=False,
    )


@dataclass(frozen=True)
class AlreadyPushedReconstructionAuthorization:
    """Current-HEAD local authorization data, not a live reconciliation receipt."""

    control_plane_head: str
    image_source_commit: str
    build_input_sha256: str
    expected_local_image_id: str
    expected_config_digest: str
    registry_host: str
    repository: str
    source_tag: str
    platform: str
    historical_evidence_integrity: str
    live_observation_integrity: str
    prior_lifecycle_evidence_integrity: str
    cleanup_generation: int
    cleanup_deadline_utc: str
    cost_ceiling_usd_cents: int
    issued_at_utc: str
    expires_at_utc: str

    def unsigned(self) -> dict[str, JsonValue]:
        return {
            "schemaVersion": RECONSTRUCTION_AUTHORIZATION_VERSION,
            "controlPlaneHead": self.control_plane_head,
            "imageSourceCommit": self.image_source_commit,
            "imageBuildInputSha256": self.build_input_sha256,
            "expectedLocalImageId": self.expected_local_image_id,
            "expectedConfigDigest": self.expected_config_digest,
            "registryHost": self.registry_host,
            "repository": self.repository,
            "sourceTag": self.source_tag,
            "platform": self.platform,
            "historicalEvidenceIntegritySha256": self.historical_evidence_integrity,
            "liveObservationIntegritySha256": self.live_observation_integrity,
            "priorLifecycleEvidenceIntegritySha256": self.prior_lifecycle_evidence_integrity,
            "cleanupGeneration": self.cleanup_generation,
            "cleanupDeadlineUtc": self.cleanup_deadline_utc,
            "costCeilingUsdCents": self.cost_ceiling_usd_cents,
            "allowedOperation": RECONCILIATION_OPERATION_ID,
            "prohibitedOperations": list(RECONSTRUCTION_PROHIBITED_OPERATIONS),
            "issuedAtUtc": self.issued_at_utc,
            "expiresAtUtc": self.expires_at_utc,
        }

    def as_json(self) -> dict[str, JsonValue]:
        unsigned = self.unsigned()
        return {
            **unsigned,
            "integritySha256": _integrity_value(
                RECONSTRUCTION_AUTHORIZATION_DOMAIN, unsigned
            ),
        }


def validate_already_pushed_reconstruction_authorization(
    value: Mapping[str, JsonValue], *, now_utc: datetime, repository_head: str
) -> AlreadyPushedReconstructionAuthorization:
    required = {
        "schemaVersion",
        "controlPlaneHead",
        "imageSourceCommit",
        "imageBuildInputSha256",
        "expectedLocalImageId",
        "expectedConfigDigest",
        "registryHost",
        "repository",
        "sourceTag",
        "platform",
        "historicalEvidenceIntegritySha256",
        "liveObservationIntegritySha256",
        "priorLifecycleEvidenceIntegritySha256",
        "cleanupGeneration",
        "cleanupDeadlineUtc",
        "costCeilingUsdCents",
        "allowedOperation",
        "prohibitedOperations",
        "issuedAtUtc",
        "expiresAtUtc",
        "integritySha256",
    }
    if set(value) != required:
        _fail("already-pushed-reconstruction-authorization-fields-invalid")
    unsigned = {key: value[key] for key in required - {"integritySha256"}}
    if (
        value.get("schemaVersion") != RECONSTRUCTION_AUTHORIZATION_VERSION
        or value.get("integritySha256")
        != _integrity_value(RECONSTRUCTION_AUTHORIZATION_DOMAIN, unsigned)
        or value.get("controlPlaneHead") != repository_head
        or HEX_SHA40.fullmatch(str(value.get("controlPlaneHead"))) is None
        or HEX_SHA40.fullmatch(str(value.get("imageSourceCommit"))) is None
        or any(
            HEX_SHA256.fullmatch(str(value.get(key))) is None
            for key in (
                "imageBuildInputSha256",
                "historicalEvidenceIntegritySha256",
                "liveObservationIntegritySha256",
                "priorLifecycleEvidenceIntegritySha256",
            )
        )
        or RAW_IMAGE_DIGEST.fullmatch(str(value.get("expectedLocalImageId"))) is None
        or RAW_IMAGE_DIGEST.fullmatch(str(value.get("expectedConfigDigest"))) is None
        or value.get("registryHost") != REGISTRY_HOST
        or value.get("repository") != PUBLISHER_REPOSITORY
        or value.get("sourceTag") != f"source-{value['imageSourceCommit']}"
        or value.get("platform") != API_IMAGE_PLATFORM
        or value.get("cleanupGeneration") != 2
        or value.get("costCeilingUsdCents") != 25000
        or value.get("allowedOperation") != RECONCILIATION_OPERATION_ID
        or value.get("prohibitedOperations")
        != list(RECONSTRUCTION_PROHIBITED_OPERATIONS)
    ):
        _fail("already-pushed-reconstruction-authorization-binding-invalid")
    issued = _parse_evidence_utc(
        value.get("issuedAtUtc"),
        error="already-pushed-reconstruction-authorization-time-invalid",
    )
    expires = _parse_evidence_utc(
        value.get("expiresAtUtc"),
        error="already-pushed-reconstruction-authorization-time-invalid",
    )
    deadline = _parse_evidence_utc(
        value.get("cleanupDeadlineUtc"),
        error="already-pushed-reconstruction-authorization-time-invalid",
    )
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if not (issued <= now < expires <= deadline) or expires - issued > timedelta(
        minutes=30
    ):
        _fail("already-pushed-reconstruction-authorization-time-invalid")
    return AlreadyPushedReconstructionAuthorization(
        control_plane_head=str(value["controlPlaneHead"]),
        image_source_commit=str(value["imageSourceCommit"]),
        build_input_sha256=str(value["imageBuildInputSha256"]),
        expected_local_image_id=str(value["expectedLocalImageId"]),
        expected_config_digest=str(value["expectedConfigDigest"]),
        registry_host=str(value["registryHost"]),
        repository=str(value["repository"]),
        source_tag=str(value["sourceTag"]),
        platform=str(value["platform"]),
        historical_evidence_integrity=str(value["historicalEvidenceIntegritySha256"]),
        live_observation_integrity=str(value["liveObservationIntegritySha256"]),
        prior_lifecycle_evidence_integrity=str(
            value["priorLifecycleEvidenceIntegritySha256"]
        ),
        cleanup_generation=2,
        cleanup_deadline_utc=str(value["cleanupDeadlineUtc"]),
        cost_ceiling_usd_cents=25000,
        issued_at_utc=str(value["issuedAtUtc"]),
        expires_at_utc=str(value["expiresAtUtc"]),
    )


@dataclass(frozen=True)
class AlreadyPushedReconciliationReceipt:
    """Future one-use receipt model; this module never issues it live."""

    control_plane_head: str
    image_source_commit: str
    build_input_sha256: str
    local_image_id: str
    config_digest: str
    registry_manifest_digest: str
    repository: str
    source_tag: str
    reconstructed_record_integrity: str
    historical_evidence_integrity: str
    live_observation_integrity: str
    cleanup_generation: int
    cleanup_deadline_utc: str
    cost_ceiling_usd_cents: int

    def unsigned(self) -> dict[str, JsonValue]:
        return {
            "schemaVersion": RECONCILIATION_RECEIPT_VERSION,
            "controlPlaneHead": self.control_plane_head,
            "imageSourceCommit": self.image_source_commit,
            "imageBuildInputSha256": self.build_input_sha256,
            "localImageId": self.local_image_id,
            "imageConfigDigest": self.config_digest,
            "registryManifestDigest": self.registry_manifest_digest,
            "repository": self.repository,
            "sourceTag": self.source_tag,
            "reconstructedRecordIntegritySha256": self.reconstructed_record_integrity,
            "historicalEvidenceIntegritySha256": self.historical_evidence_integrity,
            "liveObservationIntegritySha256": self.live_observation_integrity,
            "cleanupGeneration": self.cleanup_generation,
            "cleanupDeadlineUtc": self.cleanup_deadline_utc,
            "costCeilingUsdCents": self.cost_ceiling_usd_cents,
            "permittedOperation": RECONCILIATION_OPERATION_ID,
            "allowedFinalizerRoles": ["AcrPull", "AcrDelete"],
            "sourceTagDeleteMaximum": 1,
            "prohibitedOperations": list(RECONSTRUCTION_PROHIBITED_OPERATIONS),
        }

    def as_json(self) -> dict[str, JsonValue]:
        unsigned = self.unsigned()
        return {
            **unsigned,
            "integritySha256": _integrity_value(
                RECONCILIATION_RECEIPT_DOMAIN, unsigned
            ),
        }


def validate_already_pushed_reconciliation_receipt(
    value: Mapping[str, JsonValue], *, record: AlreadyPushedPublicationRecord
) -> AlreadyPushedReconciliationReceipt:
    required = {
        "schemaVersion",
        "controlPlaneHead",
        "imageSourceCommit",
        "imageBuildInputSha256",
        "localImageId",
        "imageConfigDigest",
        "registryManifestDigest",
        "repository",
        "sourceTag",
        "reconstructedRecordIntegritySha256",
        "historicalEvidenceIntegritySha256",
        "liveObservationIntegritySha256",
        "cleanupGeneration",
        "cleanupDeadlineUtc",
        "costCeilingUsdCents",
        "permittedOperation",
        "allowedFinalizerRoles",
        "sourceTagDeleteMaximum",
        "prohibitedOperations",
        "integritySha256",
    }
    if set(value) != required:
        _fail("already-pushed-reconciliation-receipt-fields-invalid")
    unsigned = {key: value[key] for key in required - {"integritySha256"}}
    if (
        value.get("schemaVersion") != RECONCILIATION_RECEIPT_VERSION
        or value.get("integritySha256")
        != _integrity_value(RECONCILIATION_RECEIPT_DOMAIN, unsigned)
        or record.evidence_provenance
        != RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF
        or value.get("controlPlaneHead") != record.control_plane_head
        or value.get("imageSourceCommit") != record.image_source_commit
        or value.get("imageBuildInputSha256") != record.build_input_sha256
        or value.get("localImageId") != record.local_image_id
        or value.get("imageConfigDigest") != record.config_digest
        or value.get("registryManifestDigest") != record.registry_manifest_digest
        or value.get("repository") != record.repository
        or value.get("sourceTag") != record.source_tag
        or value.get("reconstructedRecordIntegritySha256")
        != record.as_json()["integritySha256"]
        or value.get("historicalEvidenceIntegritySha256")
        != record.historical_evidence_integrity
        or value.get("liveObservationIntegritySha256")
        != record.live_observation_integrity
        or value.get("cleanupGeneration") != record.cleanup_generation
        or value.get("cleanupDeadlineUtc") != record.cleanup_deadline_utc
        or value.get("costCeilingUsdCents") != 25000
        or value.get("permittedOperation") != RECONCILIATION_OPERATION_ID
        or value.get("allowedFinalizerRoles") != ["AcrPull", "AcrDelete"]
        or value.get("sourceTagDeleteMaximum") != 1
        or value.get("prohibitedOperations")
        != list(RECONSTRUCTION_PROHIBITED_OPERATIONS)
    ):
        _fail("already-pushed-reconciliation-receipt-binding-invalid")
    return AlreadyPushedReconciliationReceipt(
        control_plane_head=record.control_plane_head,
        image_source_commit=record.image_source_commit,
        build_input_sha256=record.build_input_sha256,
        local_image_id=record.local_image_id,
        config_digest=record.config_digest,
        registry_manifest_digest=record.registry_manifest_digest,
        repository=record.repository,
        source_tag=record.source_tag,
        reconstructed_record_integrity=cast(
            str, value["reconstructedRecordIntegritySha256"]
        ),
        historical_evidence_integrity=cast(
            str, value["historicalEvidenceIntegritySha256"]
        ),
        live_observation_integrity=cast(str, value["liveObservationIntegritySha256"]),
        cleanup_generation=record.cleanup_generation,
        cleanup_deadline_utc=record.cleanup_deadline_utc,
        cost_ceiling_usd_cents=25000,
    )


def reconciliation_receipt_from_reconstructed_record(
    record: AlreadyPushedPublicationRecord,
) -> AlreadyPushedReconciliationReceipt:
    """Produce a pure receipt shape; live issuance remains separately authorized."""
    if (
        record.evidence_provenance != RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF
        or record.historical_evidence_integrity is None
        or record.live_observation_integrity is None
    ):
        _fail("already-pushed-reconciliation-receipt-provenance-invalid")
    return AlreadyPushedReconciliationReceipt(
        control_plane_head=record.control_plane_head,
        image_source_commit=record.image_source_commit,
        build_input_sha256=record.build_input_sha256,
        local_image_id=record.local_image_id,
        config_digest=record.config_digest,
        registry_manifest_digest=record.registry_manifest_digest,
        repository=record.repository,
        source_tag=record.source_tag,
        reconstructed_record_integrity=cast(str, record.as_json()["integritySha256"]),
        historical_evidence_integrity=record.historical_evidence_integrity,
        live_observation_integrity=record.live_observation_integrity,
        cleanup_generation=record.cleanup_generation,
        cleanup_deadline_utc=record.cleanup_deadline_utc,
        cost_ceiling_usd_cents=25000,
    )


def reconstruct_already_pushed_publication_record(
    *,
    historical: HistoricalPushEvidence,
    observation: LiveRegistryPublicationObservation,
    authorization: AlreadyPushedReconstructionAuthorization,
    repository_head: str,
    now_utc: datetime,
) -> AlreadyPushedPublicationRecord:
    """Join immutable history with future read-only proof without backfilling history."""
    if repository_head != authorization.control_plane_head:
        _fail("already-pushed-reconstruction-current-head-mismatch")
    descriptor_backed_local_identity = (
        historical.local_image_id == historical.config_digest
        and historical.local_image_id == observation.registry_manifest_digest
        and historical.config_digest != observation.config_digest
        and authorization.expected_local_image_id == historical.local_image_id
        and authorization.expected_config_digest == observation.config_digest
    )
    if (
        historical.image_source_commit != authorization.image_source_commit
        or historical.build_input_sha256 != authorization.build_input_sha256
        or historical.local_image_id != authorization.expected_local_image_id
        or (
            historical.config_digest != authorization.expected_config_digest
            and not descriptor_backed_local_identity
        )
        or historical.platform != authorization.platform
        or historical.repository != authorization.repository
        or historical.source_tag != authorization.source_tag
        or historical.prior_lifecycle_evidence_integrity
        != authorization.prior_lifecycle_evidence_integrity
        or historical.registry_host_sha256
        != hashlib.sha256(authorization.registry_host.encode("ascii")).hexdigest()
        or historical.as_json()["integritySha256"]
        != authorization.historical_evidence_integrity
        or observation.as_json()["integritySha256"]
        != authorization.live_observation_integrity
    ):
        _fail("already-pushed-reconstruction-historical-identity-mismatch")
    if _api_image_build_input_sha256(repository_head) != historical.build_input_sha256:
        _fail("already-pushed-reconstruction-build-input-mismatch")
    if (
        observation.registry_host != authorization.registry_host
        or observation.repository != historical.repository
        or observation.source_tag != historical.source_tag
        or (
            observation.config_digest != historical.config_digest
            and not descriptor_backed_local_identity
        )
        or observation.platform != historical.platform
        or (
            observation.source_tag_present
            and observation.source_tag_digest != observation.registry_manifest_digest
        )
    ):
        _fail("already-pushed-reconstruction-live-identity-mismatch")
    observed = _parse_evidence_utc(
        observation.observed_at_utc,
        error="already-pushed-reconstruction-observation-time-invalid",
    )
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if observed > now or now - observed > LIVE_REGISTRY_OBSERVATION_MAXIMUM_AGE:
        _fail("already-pushed-reconstruction-observation-stale")
    reconstructed_at = _format_utc(now)
    record = AlreadyPushedPublicationRecord(
        control_plane_head=authorization.control_plane_head,
        image_source_commit=historical.image_source_commit,
        build_input_sha256=historical.build_input_sha256,
        local_image_id=historical.local_image_id,
        config_digest=observation.config_digest,
        registry_manifest_digest=observation.registry_manifest_digest,
        platform=historical.platform,
        registry_host=authorization.registry_host,
        repository=historical.repository,
        source_tag=historical.source_tag,
        push_started_at_utc=historical.push_started_at_utc,
        push_completed_at_utc=historical.push_completed_at_utc,
        docker_exit_code=historical.docker_exit_code,
        docker_timed_out=historical.docker_timed_out,
        stdout_sha256=historical.stdout_sha256,
        stderr_sha256=historical.stderr_sha256,
        publication_evidence_integrity=historical.docker_push_evidence_integrity,
        cleanup_generation=authorization.cleanup_generation,
        cleanup_deadline_utc=authorization.cleanup_deadline_utc,
        prior_lifecycle_evidence=historical.prior_lifecycle_evidence_integrity,
        operation_id=RECONCILIATION_OPERATION_ID,
        evidence_provenance=RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF,
        historical_evidence_integrity=authorization.historical_evidence_integrity,
        live_observation_integrity=authorization.live_observation_integrity,
        reconstruction_authorization_integrity=cast(
            str, authorization.as_json()["integritySha256"]
        ),
        reconstructed_at_utc=reconstructed_at,
        reconstruction_algorithm_version=RECONSTRUCTION_ALGORITHM_VERSION,
    )
    validate_already_pushed_publication_record(
        record.as_json(), control_plane_head=repository_head
    )
    return record


def validate_already_pushed_registry_observation(
    value: Mapping[str, JsonValue], *, record: AlreadyPushedPublicationRecord
) -> AlreadyPushedRegistryObservation:
    if value.get("schemaVersion") == LIVE_REGISTRY_OBSERVATION_VERSION:
        live = validate_live_registry_publication_observation(
            value, now_utc=datetime.now(UTC).replace(microsecond=0)
        )
        if (
            live.registry_manifest_digest != record.registry_manifest_digest
            or live.config_digest != record.config_digest
            or live.platform != record.platform
            or live.registry_host != record.registry_host
            or live.repository != record.repository
            or live.source_tag != record.source_tag
        ):
            _fail("already-pushed-reconstructed-observation-mismatch")
        return AlreadyPushedRegistryObservation(
            registry_manifest_digest=live.registry_manifest_digest,
            config_digest=live.config_digest,
            platform=live.platform,
            registry_host=live.registry_host,
            repository=live.repository,
            source_tag=live.source_tag,
            source_tag_present=live.source_tag_present,
            observed_at_utc=live.observed_at_utc,
            read_evidence_integrity=cast(str, live.as_json()["integritySha256"]),
        )
    required = {
        "schemaVersion",
        "registryManifestDigest",
        "imageConfigDigest",
        "platform",
        "registryHost",
        "repository",
        "sourceTag",
        "sourceTagPresent",
        "observedAtUtc",
        "readEvidenceIntegritySha256",
        "integritySha256",
    }
    if set(value) != required:
        _fail("already-pushed-observation-fields-invalid")
    unsigned = {key: value[key] for key in required - {"integritySha256"}}
    integrity = value.get("integritySha256")
    if (
        not isinstance(integrity, str)
        or HEX_SHA256.fullmatch(integrity) is None
        or integrity
        != hashlib.sha256(
            ALREADY_PUSHED_OBSERVATION_DOMAIN + canonical_bytes(unsigned)
        ).hexdigest()
    ):
        _fail("already-pushed-observation-integrity-invalid")
    if (
        value.get("schemaVersion") != ALREADY_PUSHED_OBSERVATION_VERSION
        or value.get("registryManifestDigest") != record.registry_manifest_digest
        or value.get("imageConfigDigest") != record.config_digest
        or value.get("platform") != record.platform
        or value.get("registryHost") != record.registry_host
        or value.get("repository") != record.repository
        or value.get("sourceTag") != record.source_tag
        or type(value.get("sourceTagPresent")) is not bool
        or not isinstance(value.get("observedAtUtc"), str)
        or not isinstance(value.get("readEvidenceIntegritySha256"), str)
        or HEX_SHA256.fullmatch(str(value["readEvidenceIntegritySha256"])) is None
    ):
        _fail("already-pushed-observation-binding-invalid")
    try:
        observed = datetime.strptime(
            str(value["observedAtUtc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except ValueError:
        _fail("already-pushed-observation-time-invalid")
    if observed.year < 2026:
        _fail("already-pushed-observation-time-invalid")
    return AlreadyPushedRegistryObservation(
        registry_manifest_digest=record.registry_manifest_digest,
        config_digest=record.config_digest,
        platform=record.platform,
        registry_host=record.registry_host,
        repository=record.repository,
        source_tag=record.source_tag,
        source_tag_present=cast(bool, value["sourceTagPresent"]),
        observed_at_utc=str(value["observedAtUtc"]),
        read_evidence_integrity=str(value["readEvidenceIntegritySha256"]),
    )


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


def _reconcile_already_pushed_publication(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    already_pushed_record: Mapping[str, JsonValue],
    registry_observation: Mapping[str, JsonValue],
) -> str:
    """Enter the single canonical finalizer path without an upload capability."""
    repository_head = ledger.get("repositoryHead")
    published = ledger.get("publishedImage")
    if (
        not isinstance(repository_head, str)
        or HEX_SHA40.fullmatch(repository_head) is None
        or not isinstance(published, dict)
        or published.get("publicationState") != "pending"
    ):
        _fail("already-pushed-ledger-binding-invalid")
    record = validate_already_pushed_publication_record(
        already_pushed_record, control_plane_head=repository_head
    )
    observation = validate_already_pushed_registry_observation(
        registry_observation, record=record
    )
    descriptor_backed_ledger_identity = (
        record.evidence_provenance == RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF
        and record.local_image_id == record.registry_manifest_digest
        and record.local_image_id != record.config_digest
        and published.get("localImageId") == record.local_image_id
        and published.get("imageConfigDigest") == record.local_image_id
    )
    if (
        published.get("imageSourceCommit") != record.image_source_commit
        or published.get("imageBuildInputSha256") != record.build_input_sha256
        or published.get("localImageId") != record.local_image_id
        or (
            published.get("imageConfigDigest") != record.config_digest
            and not descriptor_backed_ledger_identity
        )
        or published.get("platform") != record.platform
        or published.get("repository") != record.repository
        or published.get("sourceTag") != record.source_tag
    ):
        _fail("already-pushed-ledger-record-mismatch")
    state_path = _state_path(receipt_directory)
    state = _read_state(state_path)
    if state.get("temporaryRegistryAssignmentId") is not None:
        _fail("temporary-registry-authority-already-present")
    publication = PublicationStateMachine(
        mode=PublicationMode.ALREADY_PUSHED_RECONCILIATION,
        source_tag_present=observation.source_tag_present,
    )
    publication.advance(PublicationState.IMAGE_ADMITTED)
    verify_private_registry_publication_path(repository_head=record.image_source_commit)
    publication.advance(PublicationState.PUBLICATION_PATH_PROVED)
    publication.advance(PublicationState.ALREADY_PUSHED_RECONCILED)
    publication.advance(PublicationState.IMMUTABLE_MANIFEST_PROVED)
    # A reconciliation entry never owns upload authority.  This state is an
    # explicit zero-authority invariant, not a role revocation action.
    publication.advance(PublicationState.UPLOAD_AUTHORITY_REVOKED)
    immutable_reference = (
        f"{record.registry_host}/{record.repository}@{record.registry_manifest_digest}"
    )
    if IMAGE_DIGEST.fullmatch(immutable_reference) is None:
        _fail("already-pushed-immutable-reference-malformed")
    if observation.source_tag_present:
        from infra.milestone_7_7 import acr_tag_finalization

        finalization = acr_tag_finalization.finalize_current_publication(
            ledger=ledger,
            subscription_id=subscription_id,
            receipt_directory=receipt_directory,
            source_tag=record.source_tag,
            manifest_digest=record.registry_manifest_digest,
            registry_config_digest=record.config_digest,
            publication=publication,
        )
        if (
            finalization.get("sourceTagAbsent") is not True
            or finalization.get("immutableManifestRetained") is not True
        ):
            _fail("already-pushed-finalizer-evidence-invalid")
    else:
        # No finalizer is created when read-only reconciliation proves the
        # mutable tag is already absent and the immutable manifest survives.
        publication.advance(PublicationState.SOURCE_TAG_REMOVED)
        publication.advance(PublicationState.IMMUTABLE_MANIFEST_REPROVED)
        publication.advance(PublicationState.PUBLISHER_FINALIZER_REVOKED)
        publication.advance(PublicationState.PUBLICATION_EVIDENCE_PERSISTED)
    publication.advance(PublicationState.PUBLICATION_COMPLETE)
    publication.assert_complete()
    return immutable_reference


def _publish_api_image(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    prebuilt_image_record: Path | None = None,
    mode: PublicationMode = PublicationMode.FRESH_UPLOAD,
    already_pushed_record: Mapping[str, JsonValue] | None = None,
    registry_observation: Mapping[str, JsonValue] | None = None,
) -> str:
    if mode is PublicationMode.ALREADY_PUSHED_RECONCILIATION:
        if (
            prebuilt_image_record is not None
            or already_pushed_record is None
            or registry_observation is None
        ):
            _fail("already-pushed-reconciliation-admission-invalid")
        return _reconcile_already_pushed_publication(
            ledger=ledger,
            subscription_id=subscription_id,
            receipt_directory=receipt_directory,
            already_pushed_record=already_pushed_record,
            registry_observation=registry_observation,
        )
    if (
        mode is not PublicationMode.FRESH_UPLOAD
        or prebuilt_image_record is None
        or already_pushed_record is not None
        or registry_observation is not None
    ):
        _fail("fresh-upload-admission-invalid")
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


def _reconcile_already_pushed_publication_stage(
    *,
    ledger: dict[str, JsonValue],
    subscription_id: str,
    receipt_directory: Path,
    already_pushed_record_path: Path,
    registry_observation_path: Path,
) -> dict[str, JsonValue]:
    """Persist the canonical result from a paused, already-pushed image."""
    state_path = _state_path(receipt_directory)
    state = _read_current_transient_state(state_path, ledger=ledger)
    if (
        state.get("privatePathProved") is not True
        or state.get("publishedManifestDigest") is not None
        or state.get("publisherRevocationProved") is not False
    ):
        _fail("already-pushed-reconciliation-stage-prerequisite-missing")
    record_value = load_json(
        _outside_repository(already_pushed_record_path, "already-pushed-record")
    )
    observation_value = load_json(
        _outside_repository(registry_observation_path, "registry-observation")
    )
    if not isinstance(record_value, dict) or not isinstance(observation_value, dict):
        _fail("already-pushed-reconciliation-input-malformed")
    immutable_reference = _publish_api_image(
        ledger=ledger,
        subscription_id=subscription_id,
        receipt_directory=receipt_directory,
        mode=PublicationMode.ALREADY_PUSHED_RECONCILIATION,
        already_pushed_record=cast(Mapping[str, JsonValue], record_value),
        registry_observation=cast(Mapping[str, JsonValue], observation_value),
    )
    record = validate_already_pushed_publication_record(
        cast(Mapping[str, JsonValue], record_value),
        control_plane_head=str(ledger["repositoryHead"]),
    )
    result: dict[str, JsonValue] = {
        "configDigest": record.config_digest,
        "imageBuildInputSha256": record.build_input_sha256,
        "imageSourceCommit": record.image_source_commit,
        "localImageId": record.local_image_id,
        "manifestDigest": record.registry_manifest_digest,
        "platform": record.platform,
        "publisherResidueZero": True,
        "reconciliationMode": PublicationMode.ALREADY_PUSHED_RECONCILIATION.value,
        "repository": record.repository,
        "sourceTagRemoved": True,
    }
    state["publicationEvidenceIntegritySha256"] = _publication_result_integrity(result)
    state["publishedManifestDigest"] = immutable_reference.rsplit("@", 1)[1]
    state["publisherRevocationProved"] = True
    state["lastCompletedStage"] = "reconcile-already-pushed-publication"
    state["resumableCheckpoint"] = "post-secret-provisioning"
    _replace_state(state_path, state)
    return {
        "evidence-integrity-sha256": state["publicationEvidenceIntegritySha256"],
        "immutable-image-published": True,
        "publisher-revoked": True,
        "reconciliation-mode": PublicationMode.ALREADY_PUSHED_RECONCILIATION.value,
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
