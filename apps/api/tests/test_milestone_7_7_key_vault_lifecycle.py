from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue


def _ledger(marker: str = "a") -> dict[str, JsonValue]:
    return {
        "ledgerIntegritySha256": marker * 64,
        "repositoryHead": "b" * 40,
    }


def _state(ledger: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "activeStage": None,
        "cleanupAtUtc": "2026-08-02T23:00:00Z",
        "disposition": "PAUSED_PRESERVED",
        "failedStage": None,
        "lastCompletedStage": "pre-secret",
        "preSecretDeploymentName": "opaque-deployment",
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
    _path, _state_value = _write_state(tmp_path, ledger)
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

    with pytest.raises(lifecycle.LifecycleError, match="managed-secret-presence-or-state-unproved"):
        lifecycle._post_secret(
            ledger=ledger,
            subscription_id="opaque-subscription",
            receipt_directory=tmp_path,
        )

    assert calls == ["authority-proved", "authority-revoked-and-denied"]


def test_resume_state_cannot_claim_post_secret_readiness_without_authority() -> None:
    ledger = _ledger()
    state = _state(ledger)
    state["resumableCheckpoint"] = "post-secret-provisioning"

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
