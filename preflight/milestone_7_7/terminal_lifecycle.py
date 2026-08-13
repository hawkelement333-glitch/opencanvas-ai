"""Integrity-bound contracts for the terminal Milestone 7.7 lifecycle.

The Azure executor owns service calls.  This module owns the durable handoff
artifacts between those calls so every production stage consumes the exact
output written by its predecessor.  It is intentionally side-effect free
apart from explicit artifact writes to the caller-provided receipt directory.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NoReturn, cast

from performance.milestone_7_7.framework import JsonValue, canonical_bytes, load_json

STAGE_EVIDENCE_VERSION: Final = "mobius.milestone-7.7.terminal-stage-evidence.v1"
STAGE_EVIDENCE_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/terminal-stage-evidence/v1\0"
)
SOAK_PROGRESS_VERSION: Final = "mobius.milestone-7.7.soak-progress.v1"
SOAK_PROGRESS_DOMAIN: Final = b"solarplexus-mobius/milestone-7.7/soak-progress/v1\0"
CLEANUP_AUTHORIZATION_VERSION: Final = "mobius.milestone-7.7.cleanup-authorization.v1"
CLEANUP_AUTHORIZATION_DOMAIN: Final = (
    b"solarplexus-mobius/milestone-7.7/cleanup-authorization/v1\0"
)
MILESTONE_COMPLETION_MARKER: Final = "MILESTONE_7_7_COMPLETE"
MIGRATION_REVISION: Final = "20260726_0028"
SOAK_DURATION: Final = timedelta(minutes=90)
SOAK_SAMPLE_INTERVAL_SECONDS: Final = 60
FINAL_CLEANUP_RESERVE: Final = timedelta(minutes=90)
ABSOLUTE_COST_CEILING_USD_CENTS: Final = 25_000
MAXIMUM_CLEANUP_AUTHORIZATION_AGE: Final = timedelta(hours=1)

TERMINAL_STAGE_ORDER: Final = (
    "post-secret-provisioning",
    "migration-execution",
    "readiness-validation",
    "live-validation",
    "soak",
    "successful-closeout",
    "cleanup",
    "zero-residue-verification",
    "milestone-completion",
)
STAGE_STATUS: Final = {
    "post-secret-provisioning": "POST_SECRET_FOUNDATION_READY",
    "migration-execution": "MIGRATION_COMPLETED",
    "readiness-validation": "READINESS_PASSED",
    "live-validation": "VALIDATION_PASSED",
    "soak": "SOAK_COMPLETED",
    "successful-closeout": "READY_FOR_FINAL_CLEANUP",
    "cleanup": "CLEANUP_COMPLETED",
    "zero-residue-verification": "ZERO_RESIDUE_PROVED",
    "milestone-completion": MILESTONE_COMPLETION_MARKER,
}
STAGE_PREDECESSOR: Final = {
    stage: TERMINAL_STAGE_ORDER[index - 1] if index else None
    for index, stage in enumerate(TERMINAL_STAGE_ORDER)
}
STAGE_EVIDENCE_FILES: Final = {
    stage: f"{stage}.evidence.json" for stage in TERMINAL_STAGE_ORDER
}
SOAK_PROGRESS_FILE: Final = "soak.progress.json"
CLEANUP_AUTHORIZATION_FILE: Final = "cleanup-authorization.json"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(
    r"^acrmobius7711564669\.azurecr\.io/opencanvas-api@sha256:[0-9a-f]{64}$"
)


class TerminalLifecycleError(ValueError):
    """Sanitized fail-closed terminal lifecycle contract error."""


def _fail(code: str) -> NoReturn:
    raise TerminalLifecycleError(code)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        _fail("terminal-lifecycle-time-not-utc")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        _fail(code)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(code)


def _integrity(domain: bytes, value: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(domain + canonical_bytes(dict(value))).hexdigest()


def _sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _true(value: object, code: str) -> None:
    if value is not True:
        _fail(code)


def _false(value: object, code: str) -> None:
    if value is not False:
        _fail(code)


def _integer(value: object, code: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        _fail(code)
    return value


@dataclass(frozen=True, slots=True)
class TerminalStageEvidence:
    schema_version: str
    stage: str
    status: str
    repository_head: str
    ledger_integrity_sha256: str
    started_at_utc: str
    completed_at_utc: str
    previous_evidence_integrity_sha256: str | None
    payload: dict[str, JsonValue]
    integrity_sha256: str

    def unsigned(self) -> dict[str, JsonValue]:
        return {
            "completedAtUtc": self.completed_at_utc,
            "ledgerIntegritySha256": self.ledger_integrity_sha256,
            "payload": self.payload,
            "previousEvidenceIntegritySha256": (
                self.previous_evidence_integrity_sha256
            ),
            "repositoryHead": self.repository_head,
            "schemaVersion": self.schema_version,
            "stage": self.stage,
            "startedAtUtc": self.started_at_utc,
            "status": self.status,
        }

    def canonical(self) -> dict[str, JsonValue]:
        return {**self.unsigned(), "integritySha256": self.integrity_sha256}


def stage_evidence_path(receipt_directory: Path, stage: str) -> Path:
    try:
        name = STAGE_EVIDENCE_FILES[stage]
    except KeyError:
        _fail("terminal-stage-unknown")
    return receipt_directory / name


def _validate_post_secret(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "apiDefinitionAuthoritative",
        "immutableImageDigest",
        "managedEnvironmentAuthoritative",
        "managedSecretCount",
        "migrationDefinitionAuthoritative",
        "postgresqlAuthoritative",
        "redisAuthoritative",
        "scannerEvidenceIntegritySha256",
        "secretValueAccessed",
        "telemetryDefinitionAuthoritative",
        "workerDefinitionAuthoritative",
    }
    if set(payload) != expected:
        _fail("post-secret-evidence-fields-invalid")
    for key in expected - {
        "immutableImageDigest",
        "managedSecretCount",
        "scannerEvidenceIntegritySha256",
        "secretValueAccessed",
    }:
        _true(payload[key], "post-secret-foundation-unproved")
    digest = payload["immutableImageDigest"]
    if not isinstance(digest, str) or _IMAGE_DIGEST.fullmatch(digest) is None:
        _fail("post-secret-image-identity-invalid")
    if (
        _integer(payload["managedSecretCount"], "post-secret-secret-count-invalid")
        != 11
    ):
        _fail("post-secret-secret-count-invalid")
    _sha256(
        payload["scannerEvidenceIntegritySha256"],
        "post-secret-scanner-evidence-invalid",
    )
    _false(payload["secretValueAccessed"], "post-secret-secret-value-access-invalid")


def _validate_migration(payload: Mapping[str, JsonValue]) -> None:
    if set(payload) != {
        "executionNameSha256",
        "expectedRevision",
        "singleExecution",
        "terminalStatus",
    }:
        _fail("migration-evidence-fields-invalid")
    _sha256(payload["executionNameSha256"], "migration-execution-identity-invalid")
    if payload["expectedRevision"] != MIGRATION_REVISION:
        _fail("migration-revision-invalid")
    _true(payload["singleExecution"], "migration-execution-count-invalid")
    if payload["terminalStatus"] != "Succeeded":
        _fail("migration-terminal-status-invalid")


def _validate_readiness(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "apiRevisionSha256",
        "immutableImageDigest",
        "privateIngressOnly",
        "telemetryRevisionSha256",
        "workerRevisionSha256",
    }
    if set(payload) != expected:
        _fail("readiness-evidence-fields-invalid")
    for key in ("apiRevisionSha256", "telemetryRevisionSha256", "workerRevisionSha256"):
        _sha256(payload[key], "readiness-revision-identity-invalid")
    digest = payload["immutableImageDigest"]
    if not isinstance(digest, str) or _IMAGE_DIGEST.fullmatch(digest) is None:
        _fail("readiness-image-identity-invalid")
    _true(payload["privateIngressOnly"], "readiness-private-ingress-unproved")


def _validate_live(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "apiLive",
        "apiReady",
        "cleanupArmed",
        "cleanupDeadlineUtc",
        "maximumCostUsdCents",
        "privateAddressSha256",
        "privateDnsProved",
        "runtimeGraphIntegritySha256",
        "runtimeMode",
        "telemetryReady",
        "temporaryAuthorityAbsent",
        "tlsVersion",
        "workerReady",
    }
    if set(payload) != expected:
        _fail("live-validation-evidence-fields-invalid")
    for key in (
        "apiLive",
        "apiReady",
        "cleanupArmed",
        "privateDnsProved",
        "telemetryReady",
        "temporaryAuthorityAbsent",
        "workerReady",
    ):
        _true(payload[key], "live-validation-check-failed")
    _parse_utc(
        payload["cleanupDeadlineUtc"], "live-validation-cleanup-deadline-invalid"
    )
    maximum = _integer(
        payload["maximumCostUsdCents"], "live-validation-cost-invalid", minimum=1
    )
    if maximum > ABSOLUTE_COST_CEILING_USD_CENTS:
        _fail("live-validation-cost-ceiling-exceeded")
    _sha256(payload["privateAddressSha256"], "live-validation-private-address-invalid")
    _sha256(
        payload["runtimeGraphIntegritySha256"], "live-validation-runtime-graph-invalid"
    )
    if payload["runtimeMode"] != "live-staging":
        _fail("live-validation-runtime-mode-invalid")
    if payload["tlsVersion"] not in {"TLS1_2", "TLS1_3"}:
        _fail("live-validation-tls-unproved")


def _validate_soak(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "cleanupDeadlineUtc",
        "cleanupReserveSeconds",
        "durationSeconds",
        "interrupted",
        "maximumCostUsdCents",
        "resetRequired",
        "runtimeGraphIntegritySha256",
        "sampleChainIntegritySha256",
        "sampleCount",
        "sampleIntervalSeconds",
    }
    if set(payload) != expected:
        _fail("soak-evidence-fields-invalid")
    if _integer(payload["durationSeconds"], "soak-duration-invalid") != int(
        SOAK_DURATION.total_seconds()
    ):
        _fail("soak-duration-invalid")
    interval = _integer(
        payload["sampleIntervalSeconds"], "soak-sample-interval-invalid", minimum=1
    )
    if interval > SOAK_SAMPLE_INTERVAL_SECONDS:
        _fail("soak-sample-interval-invalid")
    minimum_samples = int(SOAK_DURATION.total_seconds()) // interval + 1
    if (
        _integer(payload["sampleCount"], "soak-sample-count-invalid", minimum=1)
        < minimum_samples
    ):
        _fail("soak-sample-count-invalid")
    _false(payload["interrupted"], "soak-interrupted")
    _false(payload["resetRequired"], "soak-reset-required")
    if _integer(payload["cleanupReserveSeconds"], "soak-cleanup-reserve-invalid") < int(
        FINAL_CLEANUP_RESERVE.total_seconds()
    ):
        _fail("soak-cleanup-reserve-invalid")
    maximum = _integer(payload["maximumCostUsdCents"], "soak-cost-invalid", minimum=1)
    if maximum > ABSOLUTE_COST_CEILING_USD_CENTS:
        _fail("soak-cost-ceiling-exceeded")
    _parse_utc(payload["cleanupDeadlineUtc"], "soak-cleanup-deadline-invalid")
    _sha256(payload["runtimeGraphIntegritySha256"], "soak-runtime-graph-invalid")
    _sha256(payload["sampleChainIntegritySha256"], "soak-sample-chain-invalid")


def _validate_closeout(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "lifecycleTemporaryTagCount",
        "proofJobResidueCount",
        "publisherFinalizerResidueCount",
        "requiredEvidenceChainIntegritySha256",
        "temporaryAssignmentCount",
        "temporaryAuthorizationCount",
        "temporaryCustomRoleCount",
    }
    if set(payload) != expected:
        _fail("closeout-evidence-fields-invalid")
    _sha256(
        payload["requiredEvidenceChainIntegritySha256"],
        "closeout-evidence-chain-invalid",
    )
    for key in expected - {"requiredEvidenceChainIntegritySha256"}:
        if _integer(payload[key], "closeout-residue-present") != 0:
            _fail("closeout-residue-present")


def _validate_cleanup(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "authorizationMode",
        "resourceGroupDeleteCount",
        "softDeletedVaultAbsent",
        "temporaryAuthorityRevoked",
    }
    if set(payload) != expected:
        _fail("cleanup-evidence-fields-invalid")
    if payload["authorizationMode"] != "successful-closeout":
        _fail("cleanup-success-authorization-missing")
    if (
        _integer(payload["resourceGroupDeleteCount"], "cleanup-group-count-invalid")
        != 3
    ):
        _fail("cleanup-group-count-invalid")
    _true(payload["softDeletedVaultAbsent"], "cleanup-vault-absence-unproved")
    _true(payload["temporaryAuthorityRevoked"], "cleanup-authority-revocation-unproved")


def _validate_zero_residue(payload: Mapping[str, JsonValue]) -> None:
    expected = {
        "finalizerIdentityCount",
        "lifecycleTemporaryTagCount",
        "proofJobCount",
        "publisherIdentityCount",
        "resourceGroupCount",
        "softDeletedVaultCount",
        "targetResourceCount",
        "temporaryAssignmentCount",
        "temporaryAuthorizationCount",
        "temporaryCustomRoleCount",
    }
    if set(payload) != expected:
        _fail("zero-residue-evidence-fields-invalid")
    for key in expected:
        if _integer(payload[key], "zero-residue-count-invalid") != 0:
            _fail("zero-residue-not-zero")


def _validate_completion(payload: Mapping[str, JsonValue]) -> None:
    if set(payload) != {
        "marker",
        "milestone78Started",
        "provisioningAuthorized",
        "zeroResidueEvidenceIntegritySha256",
    }:
        _fail("milestone-completion-evidence-fields-invalid")
    if payload["marker"] != MILESTONE_COMPLETION_MARKER:
        _fail("milestone-completion-marker-invalid")
    _false(payload["milestone78Started"], "milestone-7-8-state-invalid")
    _false(payload["provisioningAuthorized"], "post-run-provisioning-authorized")
    _sha256(
        payload["zeroResidueEvidenceIntegritySha256"],
        "milestone-completion-zero-residue-invalid",
    )


_PAYLOAD_VALIDATORS: Final = {
    "post-secret-provisioning": _validate_post_secret,
    "migration-execution": _validate_migration,
    "readiness-validation": _validate_readiness,
    "live-validation": _validate_live,
    "soak": _validate_soak,
    "successful-closeout": _validate_closeout,
    "cleanup": _validate_cleanup,
    "zero-residue-verification": _validate_zero_residue,
    "milestone-completion": _validate_completion,
}


def build_stage_evidence(
    *,
    stage: str,
    repository_head: str,
    ledger_integrity_sha256: str,
    started_at_utc: datetime,
    completed_at_utc: datetime,
    payload: Mapping[str, JsonValue],
    previous: TerminalStageEvidence | None,
) -> TerminalStageEvidence:
    """Build and validate one exact predecessor-bound stage artifact."""

    if stage not in TERMINAL_STAGE_ORDER:
        _fail("terminal-stage-unknown")
    if _SHA40.fullmatch(repository_head) is None:
        _fail("terminal-stage-repository-head-invalid")
    _sha256(ledger_integrity_sha256, "terminal-stage-ledger-integrity-invalid")
    if started_at_utc.tzinfo is None or completed_at_utc.tzinfo is None:
        _fail("terminal-stage-time-not-utc")
    started = started_at_utc.astimezone(UTC).replace(microsecond=0)
    completed = completed_at_utc.astimezone(UTC).replace(microsecond=0)
    if completed < started:
        _fail("terminal-stage-time-order-invalid")
    predecessor = STAGE_PREDECESSOR[stage]
    if predecessor is None:
        if previous is not None:
            _fail("terminal-stage-predecessor-unexpected")
        previous_integrity = None
    else:
        if (
            previous is None
            or previous.stage != predecessor
            or previous.repository_head != repository_head
            or previous.ledger_integrity_sha256 != ledger_integrity_sha256
            or _parse_utc(
                previous.completed_at_utc, "terminal-stage-predecessor-time-invalid"
            )
            > started
        ):
            _fail("terminal-stage-predecessor-invalid")
        validate_stage_evidence(previous)
        previous_integrity = previous.integrity_sha256
    normalized_payload = cast(dict[str, JsonValue], dict(payload))
    _PAYLOAD_VALIDATORS[stage](normalized_payload)
    unsigned = TerminalStageEvidence(
        schema_version=STAGE_EVIDENCE_VERSION,
        stage=stage,
        status=STAGE_STATUS[stage],
        repository_head=repository_head,
        ledger_integrity_sha256=ledger_integrity_sha256,
        started_at_utc=_format_utc(started),
        completed_at_utc=_format_utc(completed),
        previous_evidence_integrity_sha256=previous_integrity,
        payload=normalized_payload,
        integrity_sha256="",
    )
    return replace(
        unsigned,
        integrity_sha256=_integrity(STAGE_EVIDENCE_DOMAIN, unsigned.unsigned()),
    )


def validate_stage_evidence(evidence: TerminalStageEvidence) -> TerminalStageEvidence:
    if (
        evidence.schema_version != STAGE_EVIDENCE_VERSION
        or evidence.stage not in TERMINAL_STAGE_ORDER
        or evidence.status != STAGE_STATUS.get(evidence.stage)
        or _SHA40.fullmatch(evidence.repository_head) is None
        or _SHA256.fullmatch(evidence.ledger_integrity_sha256) is None
        or _SHA256.fullmatch(evidence.integrity_sha256) is None
        or evidence.integrity_sha256
        != _integrity(STAGE_EVIDENCE_DOMAIN, evidence.unsigned())
    ):
        _fail("terminal-stage-evidence-integrity-invalid")
    started = _parse_utc(evidence.started_at_utc, "terminal-stage-time-invalid")
    completed = _parse_utc(evidence.completed_at_utc, "terminal-stage-time-invalid")
    if completed < started:
        _fail("terminal-stage-time-order-invalid")
    predecessor = STAGE_PREDECESSOR[evidence.stage]
    if predecessor is None:
        if evidence.previous_evidence_integrity_sha256 is not None:
            _fail("terminal-stage-predecessor-unexpected")
    else:
        _sha256(
            evidence.previous_evidence_integrity_sha256,
            "terminal-stage-predecessor-integrity-invalid",
        )
    _PAYLOAD_VALIDATORS[evidence.stage](evidence.payload)
    return evidence


def stage_evidence_from_mapping(value: Mapping[str, object]) -> TerminalStageEvidence:
    expected = {
        "completedAtUtc",
        "integritySha256",
        "ledgerIntegritySha256",
        "payload",
        "previousEvidenceIntegritySha256",
        "repositoryHead",
        "schemaVersion",
        "stage",
        "startedAtUtc",
        "status",
    }
    if set(value) != expected or not isinstance(value.get("payload"), Mapping):
        _fail("terminal-stage-evidence-fields-invalid")
    try:
        evidence = TerminalStageEvidence(
            schema_version=cast(str, value["schemaVersion"]),
            stage=cast(str, value["stage"]),
            status=cast(str, value["status"]),
            repository_head=cast(str, value["repositoryHead"]),
            ledger_integrity_sha256=cast(str, value["ledgerIntegritySha256"]),
            started_at_utc=cast(str, value["startedAtUtc"]),
            completed_at_utc=cast(str, value["completedAtUtc"]),
            previous_evidence_integrity_sha256=cast(
                str | None, value["previousEvidenceIntegritySha256"]
            ),
            payload=cast(
                dict[str, JsonValue], dict(cast(Mapping[str, object], value["payload"]))
            ),
            integrity_sha256=cast(str, value["integritySha256"]),
        )
    except (KeyError, TypeError):
        _fail("terminal-stage-evidence-malformed")
    return validate_stage_evidence(evidence)


def load_stage_evidence(
    path: Path,
    *,
    expected_stage: str,
    repository_head: str,
    ledger_integrity_sha256: str,
) -> TerminalStageEvidence:
    value = load_json(path)
    if not isinstance(value, dict):
        _fail("terminal-stage-evidence-malformed")
    evidence = stage_evidence_from_mapping(cast(Mapping[str, object], value))
    if (
        evidence.stage != expected_stage
        or evidence.repository_head != repository_head
        or evidence.ledger_integrity_sha256 != ledger_integrity_sha256
    ):
        _fail("terminal-stage-evidence-binding-invalid")
    return evidence


def _write_exclusive(path: Path, value: Mapping[str, JsonValue]) -> None:
    if not path.parent.is_dir():
        _fail("terminal-stage-evidence-directory-missing")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("terminal-stage-evidence-already-exists")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(dict(value)))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        _fail("terminal-stage-evidence-write-failed")


def write_stage_evidence(
    receipt_directory: Path, evidence: TerminalStageEvidence
) -> Path:
    validate_stage_evidence(evidence)
    path = stage_evidence_path(receipt_directory, evidence.stage)
    _write_exclusive(path, evidence.canonical())
    return path


@dataclass(frozen=True, slots=True)
class LiveValidationSample:
    observed_at_utc: str
    runtime_graph_integrity_sha256: str
    private_address_sha256: str
    private_dns_proved: bool
    tls_version: str
    api_live: bool
    api_ready: bool
    worker_ready: bool
    telemetry_ready: bool
    cleanup_armed: bool
    cleanup_deadline_utc: str
    maximum_cost_usd_cents: int
    temporary_authority_absent: bool

    def canonical(self) -> dict[str, JsonValue]:
        return asdict(self)


def validate_live_sample(sample: LiveValidationSample) -> LiveValidationSample:
    _parse_utc(sample.observed_at_utc, "soak-sample-time-invalid")
    _parse_utc(sample.cleanup_deadline_utc, "soak-cleanup-deadline-invalid")
    _sha256(sample.runtime_graph_integrity_sha256, "soak-runtime-graph-invalid")
    _sha256(sample.private_address_sha256, "soak-private-address-invalid")
    if sample.tls_version not in {"TLS1_2", "TLS1_3"}:
        _fail("soak-tls-unproved")
    if not all(
        (
            sample.private_dns_proved,
            sample.api_live,
            sample.api_ready,
            sample.worker_ready,
            sample.telemetry_ready,
            sample.cleanup_armed,
            sample.temporary_authority_absent,
        )
    ):
        _fail("soak-live-sample-failed")
    if not 1 <= sample.maximum_cost_usd_cents <= ABSOLUTE_COST_CEILING_USD_CENTS:
        _fail("soak-cost-ceiling-exceeded")
    return sample


@dataclass(frozen=True, slots=True)
class SoakRunResult:
    started_at_utc: datetime
    completed_at_utc: datetime
    payload: dict[str, JsonValue]


def _progress_document(
    *,
    repository_head: str,
    ledger_integrity_sha256: str,
    started_at: datetime,
    observed_at: datetime,
    sample_count: int,
    sample_chain_integrity: str,
    status: str,
    failure_code: str | None,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "failureCode": failure_code,
        "ledgerIntegritySha256": ledger_integrity_sha256,
        "observedAtUtc": _format_utc(observed_at),
        "repositoryHead": repository_head,
        "resetRequired": status == "INVALIDATED",
        "sampleChainIntegritySha256": sample_chain_integrity,
        "sampleCount": sample_count,
        "schemaVersion": SOAK_PROGRESS_VERSION,
        "startedAtUtc": _format_utc(started_at),
        "status": status,
    }
    return {**body, "integritySha256": _integrity(SOAK_PROGRESS_DOMAIN, body)}


def write_soak_progress(path: Path, value: Mapping[str, JsonValue]) -> None:
    unsigned = {key: item for key, item in value.items() if key != "integritySha256"}
    if (
        set(value)
        != {
            "failureCode",
            "integritySha256",
            "ledgerIntegritySha256",
            "observedAtUtc",
            "repositoryHead",
            "resetRequired",
            "sampleChainIntegritySha256",
            "sampleCount",
            "schemaVersion",
            "startedAtUtc",
            "status",
        }
        or value.get("schemaVersion") != SOAK_PROGRESS_VERSION
        or value.get("status") not in {"RUNNING", "COMPLETED", "INVALIDATED"}
        or value.get("integritySha256") != _integrity(SOAK_PROGRESS_DOMAIN, unsigned)
    ):
        _fail("soak-progress-evidence-invalid")
    temporary = path.with_suffix(".tmp")
    if not path.parent.is_dir() or temporary.exists():
        _fail("soak-progress-state-invalid")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(dict(value)))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        _fail("soak-progress-write-failed")


def run_uninterrupted_soak(
    *,
    repository_head: str,
    ledger_integrity_sha256: str,
    cleanup_deadline_utc: datetime,
    sample: Callable[[], LiveValidationSample],
    clock: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    progress: Callable[[Mapping[str, JsonValue]], None],
    sample_interval_seconds: int = SOAK_SAMPLE_INTERVAL_SECONDS,
) -> SoakRunResult:
    """Run the exact read-only 90-minute soak and bind every sample in order."""

    if _SHA40.fullmatch(repository_head) is None:
        _fail("soak-repository-head-invalid")
    _sha256(ledger_integrity_sha256, "soak-ledger-integrity-invalid")
    if not 1 <= sample_interval_seconds <= SOAK_SAMPLE_INTERVAL_SECONDS:
        _fail("soak-sample-interval-invalid")
    initial_clock = clock()
    if initial_clock.tzinfo is None or cleanup_deadline_utc.tzinfo is None:
        _fail("soak-time-not-utc")
    started = initial_clock.astimezone(UTC).replace(microsecond=0)
    deadline = cleanup_deadline_utc.astimezone(UTC).replace(microsecond=0)
    required_window = SOAK_DURATION + FINAL_CLEANUP_RESERVE
    if deadline - started < required_window:
        _fail("soak-cleanup-reserve-insufficient")
    started_monotonic = monotonic()
    sample_count = 0
    chain = "0" * 64
    runtime_graph: str | None = None
    maximum_cost = 0
    last_observed = started
    try:
        while True:
            sample_started = clock().astimezone(UTC).replace(microsecond=0)
            observed = validate_live_sample(sample())
            current = clock().astimezone(UTC).replace(microsecond=0)
            observed_at = _parse_utc(
                observed.observed_at_utc, "soak-sample-time-invalid"
            )
            if observed_at < sample_started - timedelta(
                seconds=5
            ) or observed_at > current + timedelta(seconds=5):
                _fail("soak-sample-time-invalid")
            if observed.cleanup_deadline_utc != _format_utc(deadline):
                _fail("soak-cleanup-deadline-changed")
            if runtime_graph is None:
                runtime_graph = observed.runtime_graph_integrity_sha256
            elif observed.runtime_graph_integrity_sha256 != runtime_graph:
                _fail("soak-runtime-graph-changed")
            maximum_cost = max(maximum_cost, observed.maximum_cost_usd_cents)
            chain = hashlib.sha256(
                b"solarplexus-mobius/milestone-7.7/soak-sample-chain/v1\0"
                + chain.encode("ascii")
                + canonical_bytes(observed.canonical())
            ).hexdigest()
            sample_count += 1
            last_observed = observed_at
            progress(
                _progress_document(
                    repository_head=repository_head,
                    ledger_integrity_sha256=ledger_integrity_sha256,
                    started_at=started,
                    observed_at=observed_at,
                    sample_count=sample_count,
                    sample_chain_integrity=chain,
                    status="RUNNING",
                    failure_code=None,
                )
            )
            elapsed = monotonic() - started_monotonic
            minimum_samples = (
                int(SOAK_DURATION.total_seconds()) // sample_interval_seconds + 1
            )
            if (
                elapsed >= SOAK_DURATION.total_seconds()
                and sample_count >= minimum_samples
            ):
                break
            next_sample_at = float(sample_count * sample_interval_seconds)
            sleep(
                max(
                    0.0,
                    min(
                        next_sample_at - elapsed,
                        max(0.0, SOAK_DURATION.total_seconds() - elapsed),
                    ),
                )
            )
    except BaseException as exc:
        code = str(exc)
        if re.fullmatch(r"[a-z0-9-]{1,128}", code) is None:
            code = "soak-interrupted"
        progress(
            _progress_document(
                repository_head=repository_head,
                ledger_integrity_sha256=ledger_integrity_sha256,
                started_at=started,
                observed_at=clock().astimezone(UTC).replace(microsecond=0),
                sample_count=sample_count,
                sample_chain_integrity=chain,
                status="INVALIDATED",
                failure_code=code,
            )
        )
        raise
    completed = clock().astimezone(UTC).replace(microsecond=0)
    elapsed_seconds = int(monotonic() - started_monotonic)
    if elapsed_seconds < int(SOAK_DURATION.total_seconds()):
        _fail("soak-duration-insufficient")
    reserve = int((deadline - completed).total_seconds())
    if runtime_graph is None:
        _fail("soak-sample-count-invalid")
    payload: dict[str, JsonValue] = {
        "cleanupDeadlineUtc": _format_utc(deadline),
        "cleanupReserveSeconds": reserve,
        "durationSeconds": int(SOAK_DURATION.total_seconds()),
        "interrupted": False,
        "maximumCostUsdCents": maximum_cost,
        "resetRequired": False,
        "runtimeGraphIntegritySha256": runtime_graph,
        "sampleChainIntegritySha256": chain,
        "sampleCount": sample_count,
        "sampleIntervalSeconds": sample_interval_seconds,
    }
    _validate_soak(payload)
    if last_observed < started:
        _fail("soak-sample-time-invalid")
    progress(
        _progress_document(
            repository_head=repository_head,
            ledger_integrity_sha256=ledger_integrity_sha256,
            started_at=started,
            observed_at=completed,
            sample_count=sample_count,
            sample_chain_integrity=chain,
            status="COMPLETED",
            failure_code=None,
        )
    )
    return SoakRunResult(
        started_at_utc=started, completed_at_utc=completed, payload=payload
    )


def build_successful_cleanup_authorization(
    *,
    closeout_evidence: TerminalStageEvidence,
    authorization_id: str,
    resource_groups: tuple[str, str, str],
    issued_at_utc: datetime,
) -> dict[str, JsonValue]:
    validate_stage_evidence(closeout_evidence)
    if closeout_evidence.stage != "successful-closeout":
        _fail("cleanup-authorization-closeout-evidence-invalid")
    if issued_at_utc.tzinfo is None:
        _fail("cleanup-authorization-time-malformed")
    issued = issued_at_utc.astimezone(UTC).replace(microsecond=0)
    expires = issued + MAXIMUM_CLEANUP_AUTHORIZATION_AGE
    required_stages: dict[str, JsonValue] = {
        "deployment": True,
        "evidenceCapture": True,
        "providerValidation": True,
        "secureKeyEntry": True,
        "soak90Minutes": True,
        "temporaryAccessRevocation": True,
    }
    body: dict[str, JsonValue] = {
        "authorizationEvidenceSha256": closeout_evidence.integrity_sha256,
        "authorizationId": authorization_id,
        "authorizationMode": "successful-closeout",
        "expiresAtUtc": _format_utc(expires),
        "issuedAtUtc": _format_utc(issued),
        "lifecycleState": "READY_FOR_FINAL_CLEANUP",
        "repositoryHead": closeout_evidence.repository_head,
        "requiredStages": required_stages,
        "resourceGroups": list(resource_groups),
        "schemaVersion": CLEANUP_AUTHORIZATION_VERSION,
    }
    return {
        **body,
        "authorizationIntegritySha256": _integrity(CLEANUP_AUTHORIZATION_DOMAIN, body),
    }


def write_cleanup_authorization(
    receipt_directory: Path, value: Mapping[str, JsonValue]
) -> Path:
    """Persist one non-replayable cleanup authorization outside the repository."""

    path = receipt_directory / CLEANUP_AUTHORIZATION_FILE
    _write_exclusive(path, value)
    return path


def validate_cleanup_authorization(
    value: Mapping[str, JsonValue],
    *,
    authorization_id: str,
    repository_head: str,
    resource_groups: tuple[str, str, str],
    now_utc: datetime,
    closeout_evidence: TerminalStageEvidence | None,
) -> dict[str, JsonValue]:
    expected = {
        "authorizationEvidenceSha256",
        "authorizationId",
        "authorizationIntegritySha256",
        "authorizationMode",
        "expiresAtUtc",
        "issuedAtUtc",
        "lifecycleState",
        "repositoryHead",
        "requiredStages",
        "resourceGroups",
        "schemaVersion",
    }
    if set(value) != expected:
        _fail("cleanup-authorization-malformed")
    unsigned = {
        key: item
        for key, item in value.items()
        if key != "authorizationIntegritySha256"
    }
    if value.get("authorizationIntegritySha256") != _integrity(
        CLEANUP_AUTHORIZATION_DOMAIN, unsigned
    ):
        _fail("cleanup-authorization-integrity-mismatch")
    issued = _parse_utc(
        value.get("issuedAtUtc"), "cleanup-authorization-time-malformed"
    )
    expires = _parse_utc(
        value.get("expiresAtUtc"), "cleanup-authorization-time-malformed"
    )
    now = now_utc.astimezone(UTC).replace(microsecond=0)
    if (
        now < issued
        or now >= expires
        or expires <= issued
        or expires - issued > MAXIMUM_CLEANUP_AUTHORIZATION_AGE
    ):
        _fail("cleanup-authorization-stale")
    if (
        value.get("schemaVersion") != CLEANUP_AUTHORIZATION_VERSION
        or value.get("authorizationId") != authorization_id
        or value.get("repositoryHead") != repository_head
        or value.get("resourceGroups") != list(resource_groups)
    ):
        _fail("cleanup-authorization-scope-mismatch")
    stages = value.get("requiredStages")
    expected_stages = {
        "deployment",
        "evidenceCapture",
        "providerValidation",
        "secureKeyEntry",
        "soak90Minutes",
        "temporaryAccessRevocation",
    }
    if not isinstance(stages, dict) or set(stages) != expected_stages:
        _fail("cleanup-authorization-stages-malformed")
    mode = value.get("authorizationMode")
    if mode == "successful-closeout":
        if (
            value.get("lifecycleState") != "READY_FOR_FINAL_CLEANUP"
            or any(stages[name] is not True for name in expected_stages)
            or closeout_evidence is None
        ):
            _fail("cleanup-success-evidence-incomplete")
        assert closeout_evidence is not None
        validate_stage_evidence(closeout_evidence)
        if (
            closeout_evidence.stage != "successful-closeout"
            or closeout_evidence.repository_head != repository_head
            or value.get("authorizationEvidenceSha256")
            != closeout_evidence.integrity_sha256
        ):
            _fail("cleanup-success-evidence-incomplete")
    elif mode == "explicit-user":
        if (
            value.get("lifecycleState")
            not in {"PAUSED_PRESERVED", "CONTAINED_PRESERVED"}
            or any(stages[name] is not False for name in expected_stages)
            or closeout_evidence is not None
        ):
            _fail("cleanup-explicit-authorization-malformed")
        _sha256(
            value.get("authorizationEvidenceSha256"),
            "cleanup-authorization-evidence-invalid",
        )
    else:
        _fail("cleanup-authorization-mode-invalid")
    return cast(dict[str, JsonValue], dict(value))


__all__ = [
    "ABSOLUTE_COST_CEILING_USD_CENTS",
    "CLEANUP_AUTHORIZATION_DOMAIN",
    "CLEANUP_AUTHORIZATION_FILE",
    "CLEANUP_AUTHORIZATION_VERSION",
    "FINAL_CLEANUP_RESERVE",
    "MIGRATION_REVISION",
    "MILESTONE_COMPLETION_MARKER",
    "SOAK_DURATION",
    "SOAK_PROGRESS_FILE",
    "SOAK_SAMPLE_INTERVAL_SECONDS",
    "STAGE_EVIDENCE_FILES",
    "STAGE_EVIDENCE_VERSION",
    "STAGE_PREDECESSOR",
    "TERMINAL_STAGE_ORDER",
    "LiveValidationSample",
    "SoakRunResult",
    "TerminalLifecycleError",
    "TerminalStageEvidence",
    "build_stage_evidence",
    "build_successful_cleanup_authorization",
    "load_stage_evidence",
    "run_uninterrupted_soak",
    "stage_evidence_from_mapping",
    "stage_evidence_path",
    "validate_cleanup_authorization",
    "validate_live_sample",
    "validate_stage_evidence",
    "write_cleanup_authorization",
    "write_soak_progress",
    "write_stage_evidence",
]
