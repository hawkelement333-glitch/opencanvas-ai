from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue
from preflight.milestone_7_7 import target_resource_adoption


def _ledger(marker: str = "a") -> dict[str, JsonValue]:
    return {
        "ledgerIntegritySha256": marker * 64,
        "repositoryHead": "b" * 40,
    }


def _state(ledger: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "activeStage": None,
        "cleanupAtUtc": "2026-08-08T12:15:00Z",
        "disposition": "PAUSED_PRESERVED",
        "failedStage": None,
        "lastCompletedStage": "pre-secret",
        "preSecretDeploymentName": "opaque-deployment",
        "privatePathProved": False,
        "publicationEvidenceIntegritySha256": None,
        "publishedManifestDigest": None,
        "publisherRevocationProved": False,
        "repositoryHead": ledger["repositoryHead"],
        "resumableCheckpoint": "secure-manual-entry",
        "secretValueAccessed": False,
        "temporaryKeyVaultAssignmentId": None,
        "temporaryKeyVaultAuthorityLedgerSha256": None,
        "temporaryKeyVaultAuthorityProved": False,
        "temporaryRegistryAssignmentId": None,
    }


def _write_state(
    directory: Path, ledger: dict[str, JsonValue]
) -> tuple[Path, dict[str, JsonValue]]:
    state = _state(ledger)
    path = lifecycle._state_path(directory)
    lifecycle._write_state(path, state)
    return path, state


def _install_authority_fakes(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    def create_assignment(**_kwargs: object) -> str:
        calls.append("assignment-created")
        return "/subscriptions/opaque/providers/Microsoft.Authorization/roleAssignments/opaque"

    monkeypatch.setattr(
        lifecycle,
        "load_managed_binding_contract",
        lambda: {
            "rbac": {"keyVaultSecretsOfficerRoleDefinitionId": "opaque-role"},
            "scopeBinding": {
                "keyVault": "/resourceGroups/opaque/providers/Microsoft.KeyVault/vaults/opaque"
            },
        },
    )
    monkeypatch.setattr(lifecycle, "_signed_in_user_object_id", lambda: "opaque-user")
    monkeypatch.setattr(
        lifecycle,
        "_temporary_role_assignment",
        create_assignment,
    )
    monkeypatch.setattr(
        lifecycle,
        "_wait_for_key_vault_metadata_authority",
        lambda _subscription: calls.append("propagation-proved"),
    )


def _exact_orphan_row() -> dict[str, JsonValue]:
    scope = "/subscriptions/opaque/resourceGroups/target/providers/Microsoft.KeyVault/vaults/vault"
    return {
        "id": (
            f"{scope}/providers/Microsoft.Authorization/roleAssignments/"
            "2fa1d1df-5057-482e-ab5a-dc90f597328e"
        ),
        "principalId": "1ec7f7c3-84ca-4c84-9449-107293f4f51d",
        "roleDefinitionId": (
            "/subscriptions/opaque/providers/Microsoft.Authorization/roleDefinitions/"
            "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
        ),
        "scope": scope,
    }


def test_exact_orphaned_temporary_role_assignment_is_selected() -> None:
    row = _exact_orphan_row()

    assert target_resource_adoption.exact_orphaned_temporary_role_assignment_id(
        [row],
        principal_id=str(row["principalId"]),
        role_definition_id=str(row["roleDefinitionId"]),
        scope=str(row["scope"]),
    ) == str(row["id"])


@pytest.mark.parametrize("drift", ["principalId", "roleDefinitionId", "scope", "id"])
def test_orphaned_temporary_role_assignment_drift_is_rejected(drift: str) -> None:
    row = _exact_orphan_row()
    row[drift] = "wrong"

    with pytest.raises(ValueError, match="orphaned-temporary-role-assignment-drift"):
        target_resource_adoption.exact_orphaned_temporary_role_assignment_id(
            [row],
            principal_id="1ec7f7c3-84ca-4c84-9449-107293f4f51d",
            role_definition_id=(
                "/subscriptions/opaque/providers/Microsoft.Authorization/roleDefinitions/"
                "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
            ),
            scope=(
                "/subscriptions/opaque/resourceGroups/target/providers/"
                "Microsoft.KeyVault/vaults/vault"
            ),
        )


def test_duplicate_orphaned_temporary_role_assignments_are_rejected() -> None:
    row = _exact_orphan_row()

    with pytest.raises(ValueError, match="orphaned-temporary-role-assignment-drift"):
        target_resource_adoption.exact_orphaned_temporary_role_assignment_id(
            [row, row],
            principal_id=str(row["principalId"]),
            role_definition_id=str(row["roleDefinitionId"]),
            scope=str(row["scope"]),
        )


def test_pre_secret_revokes_exact_orphan_before_resource_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    ledger = _ledger()
    assignment_id = str(_exact_orphan_row()["id"])
    monkeypatch.setattr(lifecycle, "_verified_cost", lambda: (1, 2))
    monkeypatch.setattr(
        lifecycle, "_cleanup_deadline", lambda _now: datetime(2026, 8, 13, tzinfo=UTC)
    )
    monkeypatch.setattr(
        lifecycle, "_orphaned_temporary_key_vault_assignment", lambda _subscription: assignment_id
    )

    def revoke(**kwargs: object) -> bool:
        state = kwargs["state"]
        assert isinstance(state, dict)
        assert state["temporaryKeyVaultAssignmentId"] == assignment_id
        assert state["temporaryKeyVaultAuthorityLedgerSha256"] == ledger["ledgerIntegritySha256"]
        calls.append("orphan-revoked")
        return True

    def group_exists(_subscription: str, group: str) -> bool:
        calls.append(f"group:{group}")
        return group == lifecycle.TARGET_GROUP

    monkeypatch.setattr(lifecycle, "_revoke_temporary_key_vault_authority", revoke)
    monkeypatch.setattr(lifecycle, "_group_exists", group_exists)

    with pytest.raises(lifecycle.LifecycleError, match="pre-secret-authorized-scope-incomplete"):
        lifecycle._pre_secret(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
        )

    assert calls[0] == "orphan-revoked"
    assert calls[1].startswith("group:")


def test_key_vault_authority_is_created_and_proved_before_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger()
    path, state = _write_state(tmp_path, ledger)
    calls: list[str] = []
    _install_authority_fakes(monkeypatch, calls)

    lifecycle._ensure_temporary_key_vault_authority(
        subscription_id="opaque-subscription",
        ledger=ledger,
        state_path=path,
        state=state,
    )

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert calls == ["assignment-created", "propagation-proved"]
    assert persisted["temporaryKeyVaultAuthorityProved"] is True
    assert persisted["temporaryKeyVaultAuthorityLedgerSha256"] == "a" * 64
    assert persisted["lastCompletedStage"] == lifecycle.KEY_VAULT_AUTHORITY_PROVED_STAGE


def test_key_vault_authority_waits_through_forbidden_by_rbac_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def probe(subscription_id: str) -> None:
        attempts.append(subscription_id)
        if len(attempts) == 1:
            raise lifecycle.AzureCommandError("forbiddenbyrbac")

    monkeypatch.setattr(lifecycle, "_private_tls_endpoint", lambda _host: None)
    monkeypatch.setattr(lifecycle, "_key_vault_metadata_access_probe", probe)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda _seconds: None)

    lifecycle._wait_for_key_vault_metadata_authority("opaque-subscription")

    assert attempts == ["opaque-subscription", "opaque-subscription"]


def test_stale_authority_is_revoked_before_a_current_ledger_creates_new_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger()
    path, state = _write_state(tmp_path, ledger)
    state["temporaryKeyVaultAssignmentId"] = "/subscriptions/opaque/old-assignment"
    state["temporaryKeyVaultAuthorityLedgerSha256"] = "c" * 64
    state["temporaryKeyVaultAuthorityProved"] = True
    lifecycle._replace_state(path, state)
    calls: list[str] = []
    _install_authority_fakes(monkeypatch, calls)

    def revoke(**kwargs: object) -> bool:
        calls.append("stale-authority-revoked")
        transient = kwargs["state"]
        assert isinstance(transient, dict)
        transient["temporaryKeyVaultAssignmentId"] = None
        transient["temporaryKeyVaultAuthorityLedgerSha256"] = None
        transient["temporaryKeyVaultAuthorityProved"] = False
        return True

    monkeypatch.setattr(lifecycle, "_revoke_temporary_key_vault_authority", revoke)
    lifecycle._ensure_temporary_key_vault_authority(
        subscription_id="opaque-subscription",
        ledger=ledger,
        state_path=path,
        state=state,
    )

    assert calls == [
        "stale-authority-revoked",
        "assignment-created",
        "propagation-proved",
    ]


def test_post_secret_always_revokes_temporary_authority_after_metadata_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger()
    path, state_value = _write_state(tmp_path, ledger)
    state_value["resumableCheckpoint"] = "post-secret-admission"
    lifecycle._replace_state(path, state_value)
    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: datetime(2026, 8, 2, 18, tzinfo=UTC))

    def ensure(**kwargs: object) -> None:
        calls.append("authority-proved")
        transient = kwargs["state"]
        assert isinstance(transient, dict)
        transient["temporaryKeyVaultAssignmentId"] = "/subscriptions/opaque/assignment"
        transient["temporaryKeyVaultAuthorityLedgerSha256"] = "a" * 64
        transient["temporaryKeyVaultAuthorityProved"] = True

    def revoke(**_kwargs: object) -> bool:
        calls.append("authority-revoked-and-denied")
        return True

    monkeypatch.setattr(lifecycle, "_ensure_temporary_key_vault_authority", ensure)
    monkeypatch.setattr(lifecycle, "_managed_secret_states", lambda _subscription: {})
    monkeypatch.setattr(lifecycle, "_revoke_temporary_key_vault_authority", revoke)
    monkeypatch.setattr(
        lifecycle, "load_scanner_bridge_deployment_evidence", lambda *_args, **_kwargs: object()
    )

    with pytest.raises(lifecycle.LifecycleError, match="managed-secret-presence-or-state-unproved"):
        lifecycle._post_secret(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
            scanner_bridge_evidence_path=tmp_path / "scanner-bridge-evidence.json",
        )

    assert calls == ["authority-proved", "authority-revoked-and-denied"]


def test_post_secret_reconciles_ambiguous_deployment_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger()
    path, state = _write_state(tmp_path, ledger)
    state["resumableCheckpoint"] = "post-secret-admission"
    lifecycle._replace_state(path, state)
    calls: list[str] = []

    class Evidence:
        def integrity_sha256(self) -> str:
            return "c" * 64

    secret_names = (
        "openai-api-key",
        "opencanvas-smtp-username",
        "opencanvas-smtp-password",
        "opencanvas-session-secret",
        "opencanvas-invitation-secret",
        "opencanvas-upload-capability-secret",
        "opencanvas-scanner-result-secret",
        "opencanvas-rate-limit-hmac-secret",
        "opencanvas-telemetry-token",
        "opencanvas-telemetry-pseudonymization-secret",
        "opencanvas-observability-operator-user-ids",
    )
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: datetime(2026, 8, 2, 18, tzinfo=UTC))
    monkeypatch.setattr(
        lifecycle,
        "load_scanner_bridge_deployment_evidence",
        lambda *_args, **_kwargs: Evidence(),
    )
    monkeypatch.setattr(lifecycle, "_ensure_temporary_key_vault_authority", lambda **_kwargs: None)
    monkeypatch.setattr(
        lifecycle,
        "_managed_secret_states",
        lambda _subscription: dict.fromkeys(secret_names, True),
    )
    monkeypatch.setattr(lifecycle, "_revoke_temporary_key_vault_authority", lambda **_kwargs: True)
    monkeypatch.setattr(lifecycle, "_verified_cost", lambda: (20_607, 25_000))
    monkeypatch.setattr(
        lifecycle,
        "_reconcile_published_api_image",
        lambda **_kwargs: "acrmobius7711564669.azurecr.io/opencanvas-api@sha256:" + "d" * 64,
    )
    monkeypatch.setattr(lifecycle, "_compile_template", lambda _path: None)

    def deploy(**_kwargs: object) -> None:
        calls.append("deploy-once")
        raise lifecycle.AzureCommandError("gatewaytimeout")

    monkeypatch.setattr(lifecycle, "_deploy_stage", deploy)
    monkeypatch.setattr(
        lifecycle,
        "_verify_post_secret_foundation",
        lambda **_kwargs: calls.append("authoritative-readback"),
    )

    result = lifecycle._post_secret(
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
        scanner_bridge_evidence_path=tmp_path / "scanner-evidence.json",
    )

    assert result["managedSecretCount"] == 11
    assert calls == ["deploy-once", "authoritative-readback"]
    assert json.loads(path.read_text(encoding="utf-8"))["resumableCheckpoint"] == (
        "migration-execution"
    )


def test_post_secret_resume_checkpoint_requires_no_retained_key_vault_authority() -> None:
    ledger = _ledger()
    state = _state(ledger)
    state["resumableCheckpoint"] = "post-secret-admission"

    lifecycle._validate_transient_state(state, ledger=ledger)


def test_runtime_handoff_cannot_skip_required_key_vault_authority() -> None:
    ledger = _ledger()
    state = _state(ledger)
    state["resumableCheckpoint"] = "runtime-deployment-handoff"

    with pytest.raises(
        lifecycle.LifecycleError, match="resumable-checkpoint-skips-key-vault-authority"
    ):
        lifecycle._validate_transient_state(state, ledger=ledger)


def test_legacy_resume_state_without_temporary_authority_is_upgraded_safely(
    tmp_path: Path,
) -> None:
    ledger = _ledger()
    path, state = _write_state(tmp_path, ledger)
    state.pop("temporaryKeyVaultAuthorityLedgerSha256")
    state.pop("temporaryKeyVaultAuthorityProved")
    lifecycle._replace_state(path, state)

    upgraded = lifecycle._read_current_transient_state(path, ledger=ledger)

    assert upgraded["temporaryKeyVaultAssignmentId"] is None
    assert upgraded["temporaryKeyVaultAuthorityLedgerSha256"] is None
    assert upgraded["temporaryKeyVaultAuthorityProved"] is False


def test_legacy_resume_state_with_temporary_authority_is_rejected(
    tmp_path: Path,
) -> None:
    ledger = _ledger()
    path, state = _write_state(tmp_path, ledger)
    state["temporaryKeyVaultAssignmentId"] = "/subscriptions/opaque/assignment"
    state.pop("temporaryKeyVaultAuthorityLedgerSha256")
    state.pop("temporaryKeyVaultAuthorityProved")
    lifecycle._replace_state(path, state)

    with pytest.raises(
        lifecycle.LifecycleError, match="legacy-temporary-key-vault-authority-unreconciled"
    ):
        lifecycle._read_current_transient_state(path, ledger=ledger)


def test_key_vault_role_attribution_is_not_misclassified_as_acrpush() -> None:
    with lifecycle._attribution_scope(
        lifecycle_substage="key-vault-temporary-authority-creation",
        expected_authorization="allow",
    ):
        spec = lifecycle._process_attribution_spec(
            ("az", "role", "assignment", "create"), environment_overrides=None
        )

    assert spec["operationClass"] == "key-vault-temporary-authority-creation"
    assert spec["lifecycleSubstage"] == "key-vault-temporary-authority-creation"
    assert spec["serviceClass"] == "azure-resource-manager"


def test_failure_handler_preserves_last_durable_checkpoint_and_revokes_key_vault_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger()
    path, state = _write_state(tmp_path, ledger)
    state["temporaryKeyVaultAssignmentId"] = "/subscriptions/opaque/assignment"
    state["temporaryKeyVaultAuthorityLedgerSha256"] = "a" * 64
    state["temporaryKeyVaultAuthorityProved"] = True
    lifecycle._replace_state(path, state)
    revoked: list[str] = []

    def revoke(**kwargs: object) -> bool:
        revoked.append("revoked")
        transient = kwargs["state"]
        assert isinstance(transient, dict)
        transient["temporaryKeyVaultAssignmentId"] = None
        transient["temporaryKeyVaultAuthorityLedgerSha256"] = None
        transient["temporaryKeyVaultAuthorityProved"] = False
        return True

    monkeypatch.setattr(lifecycle, "_revoke_temporary_key_vault_authority", revoke)
    result = lifecycle._handle_failure(
        error=lifecycle.LifecycleError("provider-failed"),
        operation="post-secret-provisioning",
        ledger=ledger,
        subscription_id="opaque-subscription",
        receipt_directory=tmp_path,
    )

    assert revoked == ["revoked"]
    assert result["cleanup-status"] == "temporary-key-vault-authority-revoked-and-denied"
    assert result["disposition"] == "PAUSED_PRESERVED"
