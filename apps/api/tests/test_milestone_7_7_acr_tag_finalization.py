from __future__ import annotations

import base64
import inspect
import json
from datetime import UTC, datetime

import pytest
from infra.milestone_7_7 import acr_tag_finalization as finalization
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle


def _jwt(claims: dict[str, object]) -> bytearray:
    def encoded(value: object) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(
            b"="
        )

    return bytearray(encoded({"alg": "none"}) + b"." + encoded(claims) + b".signature")


def _exact_access_token(*, actions: list[str], tenant: str) -> bytearray:
    now = int(datetime.now(UTC).timestamp())
    return _jwt(
        {
            "access": [
                {
                    "actions": actions,
                    "name": lifecycle.PUBLISHER_REPOSITORY,
                    "type": "repository",
                }
            ],
            "aud": lifecycle.REGISTRY_HOST,
            "exp": now + 3600,
            "nbf": now - 60,
            "tenant": tenant,
        }
    )


def test_classic_mode_selects_only_exact_registry_pull_and_delete_roles() -> None:
    assert finalization.registry_role_plan(finalization.CLASSIC_MODE) == (
        {
            "roleDefinitionId": finalization.ACR_PULL_ROLE_ID,
            "roleName": "AcrPull",
            "condition": None,
            "conditionVersion": None,
        },
        {
            "roleDefinitionId": finalization.ACR_DELETE_ROLE_ID,
            "roleName": "AcrDelete",
            "condition": None,
            "conditionVersion": None,
        },
    )


def test_abac_mode_requires_exact_repository_condition_without_catalog_role() -> None:
    plan = finalization.registry_role_plan(finalization.ABAC_MODE)
    assert len(plan) == 1
    role = plan[0]
    assert role["roleDefinitionId"] == finalization.REPOSITORY_CONTRIBUTOR_ROLE_ID
    assert role["conditionVersion"] == "2.0"
    assert "opencanvas-api" in str(role["condition"])
    assert "StringEqualsIgnoreCase" in str(role["condition"])
    assert "Catalog Lister" not in json.dumps(plan)


def test_unknown_registry_mode_fails_closed() -> None:
    with pytest.raises(
        finalization.TagFinalizationError,
        match="unsupported-or-ambiguous-acr-role-assignment-mode",
    ):
        finalization.registry_role_plan("unknown")


def test_unconditioned_abac_contributor_assignment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role = finalization.registry_role_plan(finalization.ABAC_MODE)[0]
    registry_scope = (
        "/subscriptions/alias/resourceGroups/target/providers/"
        "Microsoft.ContainerRegistry/registries/registry"
    )
    subscription_scope = registry_scope.rsplit("/resourceGroups/", 1)[0]
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda *_args, **_kwargs: [
            {
                "condition": None,
                "conditionVersion": None,
                "principalId": "object-alias",
                "roleDefinitionId": (
                    f"{subscription_scope}/providers/Microsoft.Authorization/"
                    f"roleDefinitions/{role['roleDefinitionId']}"
                ),
                "scope": registry_scope,
            }
        ],
    )
    with pytest.raises(
        finalization.TagFinalizationError,
        match="finalizer-role-inventory-drift",
    ):
        finalization._validate_role_inventory(
            subscription_id="subscription-alias",
            app_id="application-alias",
            object_id="object-alias",
            registry_scope=registry_scope,
            roles=(role,),
            required=True,
        )


def test_finalizer_repository_token_is_exact_pull_delete_without_push_or_catalog() -> None:
    assert finalization.FINALIZER_SCOPE == "repository:opencanvas-api:pull,delete"
    tenant = "00000000-0000-0000-0000-000000000001"
    token = _exact_access_token(actions=["pull", "delete"], tenant=tenant)
    assert finalization._finalizer_access_is_exact(token, tenant_id=tenant)


@pytest.mark.parametrize(
    "actions",
    [
        ["pull"],
        ["delete"],
        ["pull", "push"],
        ["pull", "delete", "push"],
        ["pull", "delete", "catalog"],
    ],
)
def test_nonexact_finalizer_token_scope_fails_closed(actions: list[str]) -> None:
    tenant = "00000000-0000-0000-0000-000000000001"
    token = _exact_access_token(actions=actions, tenant=tenant)
    with pytest.raises(
        finalization.TagFinalizationError,
        match="finalizer-acr-token-scope-invalid",
    ):
        finalization._finalizer_access_is_exact(token, tenant_id=tenant)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        (
            "DELETE",
            f"/acr/v1/opencanvas-api/_tags/{finalization.SOURCE_TAG}?api-version=2021-07-01",
        ),
        ("GET", "/acr/v1/opencanvas-api/_tags?api-version=2021-07-01"),
        ("GET", f"/v2/opencanvas-api/manifests/{finalization.MANIFEST_DIGEST}"),
        ("GET", f"/v2/opencanvas-api/blobs/{finalization.REGISTRY_CONFIG_DIGEST}"),
    ],
)
def test_only_exact_repository_tag_and_read_paths_are_allowed(method: str, path: str) -> None:
    lifecycle._validate_registry_request(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", f"/v2/opencanvas-api/manifests/{finalization.MANIFEST_DIGEST}"),
        ("DELETE", "/acr/v1/opencanvas-api?api-version=2021-07-01"),
        (
            "DELETE",
            "/acr/v1/opencanvas-api/_tags/another-tag?api-version=2021-07-01",
        ),
        ("GET", "/v2/_catalog"),
        ("GET", "/acr/v1/another-repository/_tags?api-version=2021-07-01"),
    ],
)
def test_manifest_repository_other_tag_and_catalog_paths_are_rejected(
    method: str, path: str
) -> None:
    with pytest.raises(lifecycle.LifecycleError, match="registry-request-scope-invalid"):
        lifecycle._validate_registry_request(method, path)


def test_continuation_ledger_binds_control_and_image_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalization, "load_managed_binding_contract", lambda: {})
    monkeypatch.setattr(finalization, "managed_binding_integrity_sha256", lambda _value: "f" * 64)
    ledger = finalization.build_continuation_ledger(
        control_plane_head="a" * 40,
        issued_at_utc=datetime(2026, 8, 4, 23, 0, tzinfo=UTC),
        registry_mode=finalization.CLASSIC_MODE,
    )
    assert ledger["controlPlaneHead"] == "a" * 40
    assert ledger["imageSourceCommit"] == finalization.IMAGE_SOURCE_COMMIT
    assert ledger["manifestDigest"] == finalization.MANIFEST_DIGEST
    assert ledger["buildInputSha256"] == finalization.BUILD_INPUT_SHA256
    assert ledger["repositoryTokenScope"] == finalization.FINALIZER_SCOPE
    assert "build" in ledger["prohibitedMutations"]
    assert "push" in ledger["prohibitedMutations"]
    assert "second-finalization-receipt" in ledger["prohibitedMutations"]


def test_altered_continuation_ledger_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(finalization, "load_managed_binding_contract", lambda: {})
    monkeypatch.setattr(finalization, "managed_binding_integrity_sha256", lambda _value: "f" * 64)
    issued = datetime(2026, 8, 4, 23, 0, tzinfo=UTC)
    ledger = finalization.build_continuation_ledger(
        control_plane_head="a" * 40,
        issued_at_utc=issued,
        registry_mode=finalization.CLASSIC_MODE,
    )
    ledger["repositoryTokenScope"] = "repository:opencanvas-api:pull,push"
    with pytest.raises(
        finalization.TagFinalizationError,
        match="finalization-ledger-integrity-mismatch",
    ):
        finalization.validate_continuation_ledger(
            ledger,
            control_plane_head="a" * 40,
            now_utc=issued,
        )


@pytest.mark.parametrize(
    "value",
    [
        {
            "digest": "sha256:" + "0" * 64,
            "deleteEnabled": True,
            "readEnabled": True,
            "writeEnabled": True,
        },
        {
            "digest": finalization.MANIFEST_DIGEST,
            "deleteEnabled": False,
            "readEnabled": True,
            "writeEnabled": True,
        },
    ],
)
def test_tag_digest_mismatch_or_delete_lock_prevents_mutation(
    value: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle, "_run", lambda *_args, **_kwargs: value)
    with pytest.raises(
        finalization.TagFinalizationError,
        match="source-tag-state-mismatch-or-locked",
    ):
        finalization._live_tag_metadata("subscription-alias")


def test_repository_inventory_uses_exact_data_plane_without_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str]] = []

    def request(
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: bytearray | None = None,
    ) -> tuple[int, dict[str, str], bytearray]:
        del headers, body
        observed.append((method, path))
        payload = {
            "registry": "registry-alias",
            "imageName": "opencanvas-api",
            "tags": [{"name": finalization.SOURCE_TAG, "digest": finalization.MANIFEST_DIGEST}],
        }
        return 200, {}, bytearray(json.dumps(payload).encode())

    monkeypatch.setattr(lifecycle, "_private_registry_request", request)
    monkeypatch.setattr(lifecycle, "_registry_authorization", lambda _token: "Bearer redacted")
    assert finalization._repository_tags(bytearray(b"x" * 64)) == {
        finalization.SOURCE_TAG: finalization.MANIFEST_DIGEST
    }
    assert observed == [("GET", "/acr/v1/opencanvas-api/_tags?api-version=2021-07-01")]


def test_finalization_path_cannot_build_push_or_upload_layers() -> None:
    source = inspect.getsource(finalization.execute_finalization)
    prohibited = (
        "docker build",
        "docker push",
        "buildx",
        "_push_prebuilt_api_image",
        "_prebuild_api_image",
        "/blobs/uploads/",
    )
    assert all(term not in source for term in prohibited)
    assert "source-tag-untag" in inspect.getsource(finalization.build_continuation_ledger)


def test_delete_401_is_classified_as_missing_delete_authority() -> None:
    assert (
        finalization._sanitized_error_code(finalization.TagFinalizationError("tag-delete-http-401"))
        == "tag-delete-http-401"
    )
