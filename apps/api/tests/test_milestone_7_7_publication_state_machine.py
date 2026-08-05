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
