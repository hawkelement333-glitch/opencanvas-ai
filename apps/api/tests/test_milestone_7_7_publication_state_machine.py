"""Regression coverage for the single lifecycle-owned publication path."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from infra.milestone_7_7 import acr_tag_finalization as finalization
from infra.milestone_7_7 import api_image_publication as publication
from infra.milestone_7_7 import publication_state_machine as state_machine
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle


def _finalizer_success_mocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[tuple[str, str]], list[dict[str, object]]]:
    deleted: list[tuple[str, str]] = []
    evidence: list[dict[str, object]] = []
    manifest = "sha256:" + "a" * 64
    config = "sha256:" + "b" * 64
    source = "source-" + "c" * 40
    monkeypatch.setattr(finalization, "_outside_repository", lambda path, _label: path)
    monkeypatch.setattr(
        finalization, "_registry_mode", lambda _subscription: finalization.CLASSIC_MODE
    )
    monkeypatch.setattr(
        finalization, "_finalizer_environment", lambda root: (root, {"AZURE_CONFIG_DIR": str(root)})
    )
    monkeypatch.setattr(lifecycle, "_scope", lambda *_args: "registry-scope")
    monkeypatch.setattr(
        lifecycle,
        "_create_ephemeral_publisher",
        lambda **_kwargs: ("app", "object", "tenant", tmp_path / "cert.pem"),
    )
    monkeypatch.setattr(lifecycle, "_publisher_login", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_reset_ephemeral_directory", lambda _path: None)
    monkeypatch.setattr(lifecycle, "_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(finalization, "_validate_role_inventory", lambda **_kwargs: None)
    monkeypatch.setattr(finalization, "_prove_initial_finalizer_denial", lambda **_kwargs: None)
    monkeypatch.setattr(finalization, "_assign_role", lambda **_kwargs: "assignment")
    monkeypatch.setattr(finalization, "_wait_role_inventory", lambda **_kwargs: None)
    monkeypatch.setattr(
        finalization,
        "_wait_for_finalizer_access",
        lambda **_kwargs: (bytearray(b"refresh"), bytearray(b"access")),
    )
    monkeypatch.setattr(finalization, "_finalizer_access_is_exact", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        finalization, "_tag_properties", lambda *_args, **_kwargs: {"digest": manifest}
    )
    source_results = iter((manifest, None))
    monkeypatch.setattr(
        lifecycle,
        "_acr_manifest_digest",
        lambda *_args, **_kwargs: next(source_results),
    )
    identity = {"manifestDigest": manifest, "configDigest": config, "platform": "linux/amd64"}
    monkeypatch.setattr(finalization, "_manifest_identity", lambda *_args, **_kwargs: identity)
    tag_rows = iter(({source: manifest}, {}))
    monkeypatch.setattr(finalization, "_repository_tags", lambda *_args: next(tag_rows))

    def request(method: str, path: str, **_kwargs):
        deleted.append((method, path))
        return 202, {}, bytearray()

    monkeypatch.setattr(lifecycle, "_private_registry_request", request)
    monkeypatch.setattr(finalization, "_cleanup_finalizer", lambda **_kwargs: [])
    monkeypatch.setattr(
        finalization, "_write_exclusive", lambda _path, value: evidence.append(dict(value))
    )
    return deleted, evidence


def test_publisher_never_deletes_the_mutable_source_tag() -> None:
    source = inspect.getsource(publication._publish_api_image)
    assert "_remove_source_tag" not in source
    assert "finalize_current_publication" in source
    assert source.index("_delete_ephemeral_publisher(") < source.index(
        "finalize_current_publication("
    )


def test_finalizer_is_bound_to_the_active_lifecycle_ledger() -> None:
    source = inspect.getsource(finalization.finalize_current_publication)
    assert "ledgerIntegritySha256" in source
    assert "materialize_continuation_ledger" not in source
    assert "execute_finalization" not in source
    assert "source_tag: str" in source
    assert "manifest_digest: str" in source


def test_finalizer_scope_is_exact_pull_delete_and_not_upload_capable() -> None:
    assert finalization.FINALIZER_SCOPE == "repository:opencanvas-api:pull,delete"
    assert "push" not in finalization.FINALIZER_SCOPE


def test_standalone_finalizer_command_is_retired(capsys) -> None:
    assert finalization.main(("--execute",)) == 2
    assert "TAG_FINALIZATION_RETIRED" in capsys.readouterr().out


def test_standalone_finalizer_callable_is_retired(tmp_path: Path) -> None:
    with pytest.raises(finalization.TagFinalizationError, match="standalone-finalization-retired"):
        finalization.execute_finalization(
            ledger_path=tmp_path / "ledger.json",
            receipt_directory=tmp_path,
            control_plane_head="a" * 40,
        )


def test_downstream_publication_keeps_digest_and_config_identities_distinct() -> None:
    source = inspect.getsource(publication._publish_api_image_stage)
    assert "manifestDigest" in source
    assert "configDigest" in source
    assert "sourceTagRemoved" in source


def test_current_finalizer_deletes_only_the_exact_source_tag_under_the_active_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    deleted, evidence = _finalizer_success_mocks(monkeypatch, tmp_path)
    manifest = "sha256:" + "a" * 64
    config = "sha256:" + "b" * 64
    source = "source-" + "c" * 40
    result = finalization.finalize_current_publication(
        ledger={"ledgerIntegritySha256": "d" * 64},
        subscription_id="subscription-alias",
        receipt_directory=tmp_path,
        source_tag=source,
        manifest_digest=manifest,
        registry_config_digest=config,
        publication=state_machine.PublicationStateMachine(completed=list(state_machine.ORDER[:8])),
    )
    assert deleted == [("DELETE", f"/acr/v1/opencanvas-api/_tags/{source}?api-version=2021-07-01")]
    assert result["sourceTagAbsent"] is True
    assert result["immutableManifestRetained"] is True
    assert result["finalizerIdentityDeleted"] is True
    assert len(evidence) == 1


@pytest.mark.parametrize("oauth_responses,post_delete_tags", [((401, 200), None), ((403, 200), [])])
def test_complete_current_image_simulation_accepts_one_transient_oauth_response(
    oauth_responses: tuple[int, ...], post_delete_tags: object
) -> None:
    transitions = state_machine.simulate_current_image_publication(
        oauth_responses=oauth_responses, post_delete_tags=post_delete_tags
    )
    assert transitions == state_machine.ORDER


def test_propagation_timeout_has_no_delete_transition() -> None:
    with pytest.raises(
        state_machine.PublicationStateError,
        match="finalizer-oauth-propagation-unproved",
    ):
        state_machine.simulate_current_image_publication(
            oauth_responses=(401, 403), post_delete_tags=None
        )


def _already_pushed_inputs(
    *, source_tag_present: bool
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    control_plane_head = "d" * 40
    image_source_commit = "c" * 40
    record = publication.AlreadyPushedPublicationRecord(
        control_plane_head=control_plane_head,
        image_source_commit=image_source_commit,
        build_input_sha256="e" * 64,
        local_image_id="sha256:" + "f" * 64,
        config_digest="sha256:" + "b" * 64,
        registry_manifest_digest="sha256:" + "a" * 64,
        platform="linux/amd64",
        registry_host=publication.REGISTRY_HOST,
        repository="opencanvas-api",
        source_tag=f"source-{image_source_commit}",
        push_started_at_utc="2026-08-05T00:00:00Z",
        push_completed_at_utc="2026-08-05T00:01:00Z",
        docker_exit_code=0,
        docker_timed_out=False,
        stdout_sha256="1" * 64,
        stderr_sha256="2" * 64,
        publication_evidence_integrity="3" * 64,
        cleanup_generation=2,
        cleanup_deadline_utc="2026-08-06T00:00:00Z",
        prior_lifecycle_evidence="4" * 64,
        operation_id="reconcile-already-pushed-publication",
    )
    observation = publication.AlreadyPushedRegistryObservation(
        registry_manifest_digest=record.registry_manifest_digest,
        config_digest=record.config_digest,
        platform=record.platform,
        registry_host=record.registry_host,
        repository=record.repository,
        source_tag=record.source_tag,
        source_tag_present=source_tag_present,
        observed_at_utc="2026-08-05T00:02:00Z",
        read_evidence_integrity="5" * 64,
    )
    ledger = {
        "repositoryHead": control_plane_head,
        "publishedImage": {
            "publicationState": "pending",
            "imageSourceCommit": record.image_source_commit,
            "imageBuildInputSha256": record.build_input_sha256,
            "localImageId": record.local_image_id,
            "imageConfigDigest": record.config_digest,
            "platform": record.platform,
            "repository": record.repository,
            "sourceTag": record.source_tag,
        },
        "ledgerIntegritySha256": "6" * 64,
    }
    return ledger, record.as_json(), observation.as_json()


def _reconciliation_mocks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(publication, "_state_path", lambda _path: Path("state.json"))
    monkeypatch.setattr(
        publication,
        "_read_state",
        lambda _path: {"temporaryRegistryAssignmentId": None},
    )
    monkeypatch.setattr(
        publication,
        "verify_private_registry_publication_path",
        lambda **_kwargs: calls.append("path"),
    )

    def reject_upload(name: str):
        def reject(**_kwargs: object) -> None:
            pytest.fail(f"upload-only call reached: {name}")

        return reject

    for name in (
        "_create_ephemeral_publisher",
        "_temporary_publisher_role_assignment",
        "_docker_push_prebuilt_image",
    ):
        monkeypatch.setattr(
            publication,
            name,
            reject_upload(name),
        )
    return calls


def test_already_pushed_reconciliation_uses_the_canonical_finalizer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger, record, observation = _already_pushed_inputs(source_tag_present=True)
    calls = _reconciliation_mocks(monkeypatch)

    def finalize(**kwargs: object) -> dict[str, object]:
        calls.append("finalizer")
        machine = kwargs["publication"]
        assert isinstance(machine, state_machine.PublicationStateMachine)
        for state in (
            state_machine.PublicationState.FINALIZER_AUTHORITY_READY,
            state_machine.PublicationState.FINALIZER_AUTHENTICATION_PROVED,
            state_machine.PublicationState.SOURCE_TAG_REMOVED,
            state_machine.PublicationState.IMMUTABLE_MANIFEST_REPROVED,
            state_machine.PublicationState.PUBLISHER_FINALIZER_REVOKED,
            state_machine.PublicationState.PUBLICATION_EVIDENCE_PERSISTED,
        ):
            machine.advance(state)
        return {"sourceTagAbsent": True, "immutableManifestRetained": True}

    monkeypatch.setattr(finalization, "finalize_current_publication", finalize)
    result = publication._publish_api_image(
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
        mode=state_machine.PublicationMode.ALREADY_PUSHED_RECONCILIATION,
        already_pushed_record=record,
        registry_observation=observation,
    )
    assert result.endswith("@sha256:" + "a" * 64)
    assert calls == ["path", "finalizer"]


def test_already_pushed_source_absent_skips_finalizer_and_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger, record, observation = _already_pushed_inputs(source_tag_present=False)
    calls = _reconciliation_mocks(monkeypatch)
    monkeypatch.setattr(
        finalization,
        "finalize_current_publication",
        lambda **_kwargs: pytest.fail("finalizer reached for an absent source tag"),
    )
    result = publication._publish_api_image(
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
        mode=state_machine.PublicationMode.ALREADY_PUSHED_RECONCILIATION,
        already_pushed_record=record,
        registry_observation=observation,
    )
    assert result.endswith("@sha256:" + "a" * 64)
    assert calls == ["path"]


def test_already_pushed_mismatch_fails_before_finalizer_or_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger, record, observation = _already_pushed_inputs(source_tag_present=True)
    observation["registryManifestDigest"] = "sha256:" + "9" * 64
    calls = _reconciliation_mocks(monkeypatch)
    with pytest.raises(RuntimeError, match="already-pushed-observation-integrity-invalid"):
        publication._publish_api_image(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
            mode=state_machine.PublicationMode.ALREADY_PUSHED_RECONCILIATION,
            already_pushed_record=record,
            registry_observation=observation,
        )
    assert calls == []


def test_already_pushed_rejects_naked_boolean_admission(tmp_path: Path) -> None:
    ledger, _record, _observation = _already_pushed_inputs(source_tag_present=True)
    with pytest.raises(RuntimeError, match="already-pushed-record-fields-invalid"):
        publication._publish_api_image(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
            mode=state_machine.PublicationMode.ALREADY_PUSHED_RECONCILIATION,
            already_pushed_record={"alreadyPushed": True},
            registry_observation={"alreadyPushed": True},
        )


def test_paused_preserved_has_one_reconciliation_entry_and_no_upload_entry() -> None:
    assert state_machine.CANONICAL_PUBLICATION_ENTRY_POINTS["paused-preserved"] == (
        "reconcile-already-pushed-publication"
    )
    source = inspect.getsource(publication._reconcile_already_pushed_publication)
    assert "_create_ephemeral_publisher" not in source
    assert "_temporary_publisher_role_assignment" not in source
    assert "_docker_push_prebuilt_image" not in source
