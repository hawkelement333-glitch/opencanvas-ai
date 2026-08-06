from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime, timedelta

import pytest
from infra.milestone_7_7 import api_image_publication as publication
from infra.milestone_7_7.scripts import reconstruct_already_pushed_publication as script

NOW = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
HEAD = "d" * 40
SOURCE = "c" * 40
BUILD = "e" * 64
LOCAL = "sha256:" + "f" * 64
CONFIG = "sha256:" + "b" * 64
MANIFEST = "sha256:" + "a" * 64
HOST_HASH = hashlib.sha256(publication.REGISTRY_HOST.encode("ascii")).hexdigest()


def _historical() -> publication.HistoricalPushEvidence:
    return publication.HistoricalPushEvidence(
        image_source_commit=SOURCE,
        build_input_sha256=BUILD,
        local_image_id=LOCAL,
        config_digest=CONFIG,
        platform="linux/amd64",
        repository="opencanvas-api",
        source_tag=f"source-{SOURCE}",
        push_started_at_utc="2026-08-05T15:01:57Z",
        push_completed_at_utc="2026-08-05T15:09:32Z",
        docker_exit_code=0,
        docker_timed_out=False,
        stdout_sha256="1" * 64,
        stderr_sha256="2" * 64,
        docker_push_evidence_integrity="3" * 64,
        prebuilt_image_evidence_integrity="4" * 64,
        prior_lifecycle_evidence_integrity="5" * 64,
        registry_host_sha256=HOST_HASH,
    )


def _retained_artifacts() -> tuple[dict[str, object], dict[str, object]]:
    docker: dict[str, object] = {
        "schemaVersion": publication.DOCKER_PUSH_EVIDENCE_VERSION,
        "status": "SUCCEEDED",
        "actualExitCode": 0,
        "timedOut": False,
        "rawOutputRetained": False,
        "secretValueRetained": False,
        "repository": "opencanvas-api",
        "sourceTag": f"source-{SOURCE}",
        "startedAtUtc": "2026-08-05T15:01:57Z",
        "finishedAtUtc": "2026-08-05T15:09:32Z",
        "stdoutSanitizedSha256": "1" * 64,
        "stderrSanitizedSha256": "2" * 64,
        "registryHostSha256": HOST_HASH,
    }
    docker["integritySha256"] = publication._integrity_value(
        publication.DOCKER_PUSH_EVIDENCE_DOMAIN,
        docker,
    )
    prebuilt: dict[str, object] = {
        "schemaVersion": publication.PREBUILT_IMAGE_RECORD_VERSION,
        "completionStatus": "READY",
        "repositoryHead": SOURCE,
        "buildInputSha256": BUILD,
        # The retained prebuilt-image record binds the loaded Docker image ID
        # to the configuration digest.  The real retained record uses that
        # same identity value; the reconstruction model itself still permits
        # independently recorded local-image and config identities.
        "imageId": CONFIG,
        "configDigest": CONFIG,
        "platform": "linux/amd64",
    }
    prebuilt["integritySha256"] = publication._integrity_value(
        publication.PREBUILT_IMAGE_RECORD_DOMAIN,
        prebuilt,
    )
    return docker, prebuilt


def test_historical_evidence_is_derived_only_from_integrity_bound_artifacts() -> None:
    docker, prebuilt = _retained_artifacts()
    historical = publication.historical_push_evidence_from_retained_artifacts(
        docker_push_evidence=docker,  # type: ignore[arg-type]
        prebuilt_image_evidence=prebuilt,  # type: ignore[arg-type]
        prior_lifecycle_evidence_integrity="5" * 64,
    )
    assert historical.image_source_commit == SOURCE
    assert historical.build_input_sha256 == BUILD
    assert historical.local_image_id == CONFIG
    assert historical.config_digest == CONFIG
    assert historical.docker_push_evidence_integrity == docker["integritySha256"]
    assert historical.prebuilt_image_evidence_integrity == prebuilt["integritySha256"]
    docker["actualExitCode"] = 1
    with pytest.raises(RuntimeError, match="artifact-invalid"):
        publication.historical_push_evidence_from_retained_artifacts(
            docker_push_evidence=docker,  # type: ignore[arg-type]
            prebuilt_image_evidence=prebuilt,  # type: ignore[arg-type]
            prior_lifecycle_evidence_integrity="5" * 64,
        )


def _observation(*, tag_present: bool = True) -> publication.LiveRegistryPublicationObservation:
    return publication.LiveRegistryPublicationObservation(
        observed_at_utc="2026-08-05T15:59:00Z",
        registry_host=publication.REGISTRY_HOST,
        repository="opencanvas-api",
        source_tag=f"source-{SOURCE}",
        source_tag_present=tag_present,
        source_tag_digest=MANIFEST if tag_present else None,
        registry_manifest_digest=MANIFEST,
        raw_manifest_body_sha256="a" * 64,
        config_digest=CONFIG,
        platform="linux/amd64",
        media_type="application/vnd.oci.image.manifest.v1+json",
        request_sequence=("registry-challenge", "manifest-get", "tag-get"),
        response_statuses=("200", "200", "200" if tag_present else "404"),
        correlation_hashes=("6" * 64,),
        mutation_performed=False,
    )


def _authorization(
    historical: publication.HistoricalPushEvidence,
    observation: publication.LiveRegistryPublicationObservation,
) -> publication.AlreadyPushedReconstructionAuthorization:
    return publication.AlreadyPushedReconstructionAuthorization(
        control_plane_head=HEAD,
        image_source_commit=SOURCE,
        build_input_sha256=BUILD,
        expected_local_image_id=LOCAL,
        expected_config_digest=CONFIG,
        registry_host=publication.REGISTRY_HOST,
        repository="opencanvas-api",
        source_tag=f"source-{SOURCE}",
        platform="linux/amd64",
        historical_evidence_integrity=historical.as_json()["integritySha256"],  # type: ignore[arg-type]
        live_observation_integrity=observation.as_json()["integritySha256"],  # type: ignore[arg-type]
        prior_lifecycle_evidence_integrity="5" * 64,
        cleanup_generation=2,
        cleanup_deadline_utc="2026-08-06T12:00:00Z",
        cost_ceiling_usd_cents=25000,
        issued_at_utc="2026-08-05T15:59:00Z",
        expires_at_utc="2026-08-05T16:14:00Z",
    )


def _validated_inputs(
    *, tag_present: bool = True
) -> tuple[
    publication.HistoricalPushEvidence,
    publication.LiveRegistryPublicationObservation,
    publication.AlreadyPushedReconstructionAuthorization,
]:
    historical = publication.validate_historical_push_evidence(_historical().as_json())
    observation = publication.validate_live_registry_publication_observation(
        _observation(tag_present=tag_present).as_json(), now_utc=NOW
    )
    authorization = publication.validate_already_pushed_reconstruction_authorization(
        _authorization(historical, observation).as_json(),
        now_utc=NOW,
        repository_head=HEAD,
    )
    return historical, observation, authorization


def _reconstruct(
    monkeypatch: pytest.MonkeyPatch, *, tag_present: bool = True
) -> publication.AlreadyPushedPublicationRecord:
    monkeypatch.setattr(publication, "_api_image_build_input_sha256", lambda _head: BUILD)
    historical, observation, authorization = _validated_inputs(tag_present=tag_present)
    return publication.reconstruct_already_pushed_publication_record(
        historical=historical,
        observation=observation,
        authorization=authorization,
        repository_head=HEAD,
        now_utc=NOW,
    )


@pytest.mark.parametrize("tag_present", [True, False])
def test_reconstruction_is_truthful_for_present_or_absent_source_tag(
    monkeypatch: pytest.MonkeyPatch, tag_present: bool
) -> None:
    record = _reconstruct(monkeypatch, tag_present=tag_present)
    assert record.evidence_provenance == (
        publication.RECONSTRUCTED_FROM_LIVE_READ_ONLY_REGISTRY_PROOF
    )
    assert record.registry_manifest_digest == MANIFEST
    assert (
        publication.validate_already_pushed_publication_record(
            record.as_json(), control_plane_head=HEAD
        ).evidence_provenance
        == record.evidence_provenance
    )


def test_reconstruction_keeps_historical_evidence_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical, observation, authorization = _validated_inputs()
    original = historical.as_json()
    monkeypatch.setattr(publication, "_api_image_build_input_sha256", lambda _head: BUILD)
    publication.reconstruct_already_pushed_publication_record(
        historical=historical,
        observation=observation,
        authorization=authorization,
        repository_head=HEAD,
        now_utc=NOW,
    )
    assert historical.as_json() == original
    assert "registryManifestDigest" not in original


@pytest.mark.parametrize(
    "field,value,error",
    [
        (
            "imageConfigDigest",
            "sha256:" + "9" * 64,
            "live-registry-observation-binding-invalid",
        ),
        ("repository", "different-repository", "live-registry-observation-binding-invalid"),
        ("platform", "linux/arm64", "live-registry-observation-binding-invalid"),
        ("mutationPerformed", True, "live-registry-observation-binding-invalid"),
    ],
)
def test_invalid_live_identity_or_mutation_fails_closed(
    field: str, value: object, error: str
) -> None:
    raw = _observation().as_json()
    raw[field] = value
    with pytest.raises(RuntimeError, match=error):
        publication.validate_live_registry_publication_observation(raw, now_utc=NOW)


def test_source_tag_mismatch_fails_during_strict_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical, _observation_value, _authorization_value = _validated_inputs()
    raw = _observation().as_json()
    raw["sourceTag"] = "source-" + "9" * 40
    raw["integritySha256"] = publication._integrity_value(
        publication.LIVE_REGISTRY_OBSERVATION_DOMAIN,
        {key: raw[key] for key in raw if key != "integritySha256"},
    )
    observation = publication.validate_live_registry_publication_observation(raw, now_utc=NOW)
    authorization = _authorization(historical, observation)
    monkeypatch.setattr(publication, "_api_image_build_input_sha256", lambda _head: BUILD)
    with pytest.raises(RuntimeError, match="live-identity-mismatch"):
        publication.reconstruct_already_pushed_publication_record(
            historical=historical,
            observation=observation,
            authorization=authorization,
            repository_head=HEAD,
            now_utc=NOW,
        )


def test_manifest_body_digest_and_freshness_cannot_be_guessed() -> None:
    raw = _observation().as_json()
    raw["rawManifestBodySha256"] = "9" * 64
    raw["integritySha256"] = publication._integrity_value(
        publication.LIVE_REGISTRY_OBSERVATION_DOMAIN,
        {key: raw[key] for key in raw if key != "integritySha256"},
    )
    with pytest.raises(RuntimeError, match="live-registry-observation-binding-invalid"):
        publication.validate_live_registry_publication_observation(raw, now_utc=NOW)
    stale = _observation().as_json()
    stale["observedAtUtc"] = "2026-08-05T15:40:00Z"
    stale["integritySha256"] = publication._integrity_value(
        publication.LIVE_REGISTRY_OBSERVATION_DOMAIN,
        {key: stale[key] for key in stale if key != "integritySha256"},
    )
    with pytest.raises(RuntimeError, match="live-registry-observation-stale"):
        publication.validate_live_registry_publication_observation(stale, now_utc=NOW)


def test_current_head_and_build_input_mismatch_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical, observation, authorization = _validated_inputs()
    monkeypatch.setattr(publication, "_api_image_build_input_sha256", lambda _head: "9" * 64)
    with pytest.raises(RuntimeError, match="build-input-mismatch"):
        publication.reconstruct_already_pushed_publication_record(
            historical=historical,
            observation=observation,
            authorization=authorization,
            repository_head=HEAD,
            now_utc=NOW,
        )
    with pytest.raises(RuntimeError, match="current-head-mismatch"):
        publication.reconstruct_already_pushed_publication_record(
            historical=historical,
            observation=observation,
            authorization=authorization,
            repository_head="9" * 40,
            now_utc=NOW,
        )


def test_reconstruction_authorization_rejects_missing_integrity_or_forbidden_scope() -> None:
    _historical, _observation_value, authorization = _validated_inputs()
    raw = authorization.as_json()
    raw["prohibitedOperations"] = ["build"]
    raw["integritySha256"] = publication._integrity_value(
        publication.RECONSTRUCTION_AUTHORIZATION_DOMAIN,
        {key: raw[key] for key in raw if key != "integritySha256"},
    )
    with pytest.raises(RuntimeError, match="authorization-binding-invalid"):
        publication.validate_already_pushed_reconstruction_authorization(
            raw, now_utc=NOW, repository_head=HEAD
        )
    raw = authorization.as_json()
    raw["integritySha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="authorization-binding-invalid"):
        publication.validate_already_pushed_reconstruction_authorization(
            raw, now_utc=NOW, repository_head=HEAD
        )


def test_reconstructed_record_only_enters_reconciliation_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _reconstruct(monkeypatch)
    receipt = publication.reconciliation_receipt_from_reconstructed_record(record)
    assert (
        publication.validate_already_pushed_reconciliation_receipt(
            receipt.as_json(), record=record
        ).source_tag
        == record.source_tag
    )
    assert receipt.unsigned()["permittedOperation"] == "reconcile-already-pushed-publication"
    assert receipt.unsigned()["allowedFinalizerRoles"] == ["AcrPull", "AcrDelete"]
    assert "acrpush" in receipt.unsigned()["prohibitedOperations"]
    source = inspect.getsource(publication.reconstruct_already_pushed_publication_record)
    assert "_docker_push_prebuilt_image" not in source
    assert "_create_ephemeral_publisher" not in source


def test_reconciliation_receipt_rejects_manifest_deletion_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _reconstruct(monkeypatch)
    raw = publication.reconciliation_receipt_from_reconstructed_record(record).as_json()
    raw["prohibitedOperations"] = ["build"]
    raw["integritySha256"] = publication._integrity_value(
        publication.RECONCILIATION_RECEIPT_DOMAIN,
        {key: raw[key] for key in raw if key != "integritySha256"},
    )
    with pytest.raises(RuntimeError, match="receipt-binding-invalid"):
        publication.validate_already_pushed_reconciliation_receipt(raw, record=record)


def test_legacy_original_record_remains_valid_and_reconstructed_record_requires_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = publication.AlreadyPushedPublicationRecord(
        control_plane_head=HEAD,
        image_source_commit=SOURCE,
        build_input_sha256=BUILD,
        local_image_id=LOCAL,
        config_digest=CONFIG,
        registry_manifest_digest=MANIFEST,
        platform="linux/amd64",
        registry_host=publication.REGISTRY_HOST,
        repository="opencanvas-api",
        source_tag=f"source-{SOURCE}",
        push_started_at_utc="2026-08-05T15:01:57Z",
        push_completed_at_utc="2026-08-05T15:09:32Z",
        docker_exit_code=0,
        docker_timed_out=False,
        stdout_sha256="1" * 64,
        stderr_sha256="2" * 64,
        publication_evidence_integrity="3" * 64,
        cleanup_generation=2,
        cleanup_deadline_utc="2026-08-06T12:00:00Z",
        prior_lifecycle_evidence="5" * 64,
        operation_id="reconcile-already-pushed-publication",
    )
    assert (
        publication.validate_already_pushed_publication_record(
            legacy.as_json(), control_plane_head=HEAD
        ).evidence_provenance
        == publication.RETAINED_ORIGINAL_PUSH_EVIDENCE
    )
    reconstructed = _reconstruct(monkeypatch).as_json()
    reconstructed["evidenceProvenance"] = "reconstructed=true"
    reconstructed["integritySha256"] = publication._integrity_value(
        publication.ALREADY_PUSHED_RECORD_DOMAIN,
        {key: reconstructed[key] for key in reconstructed if key != "integritySha256"},
    )
    with pytest.raises(RuntimeError, match="reconstruction-binding-invalid"):
        publication.validate_already_pushed_publication_record(
            reconstructed, control_plane_head=HEAD
        )


def test_reconstruction_script_is_local_only() -> None:
    source = inspect.getsource(script)
    assert "subprocess" not in source
    assert "az " not in source
    assert "docker build" not in source.casefold()
    assert "docker push" not in source.casefold()
    assert "requests." not in source
    assert "urllib" not in source


def test_reconstruction_rejects_expired_authorization() -> None:
    historical = _historical()
    observation = _observation()
    authorization = _authorization(historical, observation).as_json()
    authorization["expiresAtUtc"] = "2026-08-05T15:59:30Z"
    authorization["integritySha256"] = publication._integrity_value(
        publication.RECONSTRUCTION_AUTHORIZATION_DOMAIN,
        {key: authorization[key] for key in authorization if key != "integritySha256"},
    )
    with pytest.raises(RuntimeError, match="authorization-time-invalid"):
        publication.validate_already_pushed_reconstruction_authorization(
            authorization, now_utc=NOW + timedelta(minutes=1), repository_head=HEAD
        )
