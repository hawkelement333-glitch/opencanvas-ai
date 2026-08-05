from __future__ import annotations

import base64
import hashlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

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


def _raw(value: dict[str, object]) -> tuple[bytearray, str]:
    body = bytearray(json.dumps(value, separators=(",", ":")).encode())
    return body, "sha256:" + hashlib.sha256(body).hexdigest()


def _leaf(media_type: str = finalization.OCI_MANIFEST) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": media_type,
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": finalization.REGISTRY_CONFIG_DIGEST,
            "size": 123,
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": "sha256:" + "1" * 64,
                "size": 456,
            }
        ],
    }


def _manifest_headers(digest: str, media_type: str) -> dict[str, str]:
    return {"content-type": media_type, "docker-content-digest": digest}


def test_manifest_head_empty_body_passes_without_json_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json, "loads", lambda _body: pytest.fail("HEAD decoded JSON"))
    result = finalization._parse_manifest_head(
        200,
        {"content-length": "2763", "docker-content-digest": finalization.MANIFEST_DIGEST},
        bytearray(),
        expected_digest=finalization.MANIFEST_DIGEST,
    )
    assert result == {"bodyEmpty": True, "dockerContentDigestPresent": True}


@pytest.mark.parametrize("media_type", [finalization.OCI_MANIFEST, finalization.DOCKER_MANIFEST])
def test_leaf_manifest_media_types_parse(media_type: str) -> None:
    body, digest = _raw(_leaf(media_type))
    parsed = finalization._parse_raw_manifest(
        200, _manifest_headers(digest, media_type), body, expected_digest=digest
    )
    assert parsed["kind"] == "leaf"
    assert parsed["configDigest"] == finalization.REGISTRY_CONFIG_DIGEST


def test_content_type_parameters_are_normalized() -> None:
    body, digest = _raw(_leaf())
    parsed = finalization._parse_raw_manifest(
        200,
        _manifest_headers(digest, finalization.OCI_MANIFEST + "; charset=utf-8"),
        body,
        expected_digest=digest,
    )
    assert parsed["mediaType"] == finalization.OCI_MANIFEST


def test_acr_tag_properties_uses_nested_tag() -> None:
    payload = {
        "registry": "registry-alias",
        "imageName": "opencanvas-api",
        "tag": {
            "name": finalization.SOURCE_TAG,
            "digest": finalization.MANIFEST_DIGEST,
            "changeableAttributes": {
                "deleteEnabled": True,
                "readEnabled": True,
                "writeEnabled": True,
                "listEnabled": True,
            },
        },
    }
    parsed = finalization._parse_tag_properties(200, {}, bytearray(json.dumps(payload).encode()))
    assert parsed["digest"] == finalization.MANIFEST_DIGEST


def test_acr_manifest_properties_uses_nested_manifest() -> None:
    payload = {
        "registry": "registry-alias",
        "imageName": "opencanvas-api",
        "manifest": {
            "digest": finalization.MANIFEST_DIGEST,
            "architecture": "amd64",
            "os": "linux",
            "tags": [finalization.SOURCE_TAG],
            "changeableAttributes": {"readEnabled": True, "deleteEnabled": True},
        },
    }
    parsed = finalization._parse_manifest_properties(
        200,
        {},
        bytearray(json.dumps(payload).encode()),
        expected_digest=finalization.MANIFEST_DIGEST,
        source_tag_expected=True,
    )
    assert parsed["platform"] == "linux/amd64"


def test_manifest_and_config_digests_remain_distinct() -> None:
    body, digest = _raw(_leaf())
    parsed = finalization._parse_raw_manifest(
        200,
        _manifest_headers(digest, finalization.OCI_MANIFEST),
        body,
        expected_digest=digest,
    )
    assert parsed["digest"] != parsed["configDigest"]


def test_raw_manifest_body_digest_mismatch_fails_closed() -> None:
    body, _digest = _raw(_leaf())
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-manifest-body-digest-mismatch",
    ):
        finalization._parse_raw_manifest(
            200,
            {"content-type": finalization.OCI_MANIFEST},
            body,
            expected_digest="sha256:" + "9" * 64,
        )


def test_docker_content_digest_mismatch_fails_closed() -> None:
    body, digest = _raw(_leaf())
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-manifest-header-digest-mismatch",
    ):
        finalization._parse_raw_manifest(
            200,
            _manifest_headers("sha256:" + "9" * 64, finalization.OCI_MANIFEST),
            body,
            expected_digest=digest,
        )


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (bytearray(), "immutable-manifest-get-empty-or-unavailable"),
        (bytearray(b"{"), "immutable-manifest-response-malformed"),
    ],
)
def test_empty_or_invalid_manifest_get_fails_closed(body: bytearray, error: str) -> None:
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    with pytest.raises(finalization.TagFinalizationError, match=error):
        finalization._parse_raw_manifest(
            200,
            {"content-type": finalization.OCI_MANIFEST},
            body,
            expected_digest=digest,
        )


def test_missing_config_fails_closed() -> None:
    value = _leaf()
    value.pop("config")
    body, digest = _raw(value)
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-manifest-descriptor-malformed",
    ):
        finalization._parse_raw_manifest(
            200,
            _manifest_headers(digest, finalization.OCI_MANIFEST),
            body,
            expected_digest=digest,
        )


def _index(platforms: list[tuple[str, str]]) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": finalization.OCI_INDEX,
        "manifests": [
            {
                "mediaType": finalization.OCI_MANIFEST,
                "digest": "sha256:" + str(index + 1) * 64,
                "size": 100 + index,
                "platform": {"os": os_name, "architecture": architecture},
            }
            for index, (os_name, architecture) in enumerate(platforms)
        ],
    }


def test_index_selects_exactly_one_linux_amd64_child() -> None:
    body, digest = _raw(_index([("linux", "arm64"), ("linux", "amd64")]))
    parsed = finalization._parse_raw_manifest(
        200,
        _manifest_headers(digest, finalization.OCI_INDEX),
        body,
        expected_digest=digest,
    )
    assert parsed["childDigest"] == "sha256:" + "2" * 64


@pytest.mark.parametrize(
    "platforms", [[("linux", "arm64")], [("linux", "amd64"), ("linux", "amd64")]]
)
def test_index_wrong_platform_cardinality_fails_closed(
    platforms: list[tuple[str, str]],
) -> None:
    body, digest = _raw(_index(platforms))
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-index-platform-cardinality-invalid",
    ):
        finalization._parse_raw_manifest(
            200,
            _manifest_headers(digest, finalization.OCI_INDEX),
            body,
            expected_digest=digest,
        )


def test_config_blob_head_empty_body_passes() -> None:
    finalization._parse_blob_head(200, {"content-length": "0"}, bytearray())


def test_legacy_config_get_is_not_part_of_manifest_identity() -> None:
    source = inspect.getsource(finalization._manifest_identity)
    blob_path = 'f"/v2/{lifecycle.PUBLISHER_REPOSITORY}/blobs/{config_digest}"'
    assert f'"HEAD",\n            {blob_path}' in source
    assert f'"GET",\n            {blob_path}' not in source


def test_unsupported_media_type_fails_exactly() -> None:
    body, digest = _raw(_leaf())
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-manifest-media-type-unsupported",
    ):
        finalization._parse_raw_manifest(
            200,
            _manifest_headers(digest, "application/octet-stream"),
            body,
            expected_digest=digest,
        )


def test_cleanup_continues_through_private_tls_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "finalizer"
    azure_config = root / "azure"
    docker_config = root / "docker"
    azure_config.mkdir(parents=True)
    docker_config.mkdir()
    events: list[str] = []
    monkeypatch.setattr(
        lifecycle,
        "_delete_assignment",
        lambda _subscription, assignment: events.append(f"role:{assignment}"),
    )
    monkeypatch.setattr(
        finalization,
        "_wait_role_inventory",
        lambda **_kwargs: events.append("roles-absent"),
    )
    monkeypatch.setattr(
        lifecycle,
        "_reset_ephemeral_directory",
        lambda _path: events.append("cache-cleared"),
    )

    def tls_failure(**_kwargs: object) -> None:
        events.append("tls-failed")
        raise lifecycle.LifecycleError("private-endpoint-tls-unproved")

    monkeypatch.setattr(lifecycle, "_publisher_login", tls_failure)
    monkeypatch.setattr(
        lifecycle,
        "_delete_ephemeral_publisher_by_app_id",
        lambda _app: events.append("identity-deleted"),
    )
    errors = finalization._cleanup_finalizer(
        subscription_id="subscription-alias",
        assignment_ids=("pull", "delete"),
        app_id="application-alias",
        object_id="principal-alias",
        tenant_id="tenant-alias",
        certificate_path=root / "certificate.pem",
        environment={
            "AZURE_CONFIG_DIR": str(azure_config),
            "DOCKER_CONFIG": str(docker_config),
        },
        finalizer_root=root,
        registry_scope="registry-scope-alias",
        roles=(),
    )
    assert events == [
        "role:delete",
        "role:pull",
        "roles-absent",
        "cache-cleared",
        "tls-failed",
        "identity-deleted",
    ]
    assert errors == ["private-endpoint-tls-unproved"]
    assert not root.exists()


def test_primary_parser_failure_is_not_replaced_by_secondary_cleanup_failure() -> None:
    primary = finalization.TagFinalizationError("immutable-manifest-response-malformed")
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-manifest-response-malformed",
    ):
        finalization._raise_preserving_primary(primary, ["private-endpoint-tls-unproved"])


def test_request_scope_allows_only_exact_typed_finalizer_reads() -> None:
    allowed = (
        ("GET", f"/acr/v1/opencanvas-api/_tags/{finalization.SOURCE_TAG}?api-version=2021-07-01"),
        (
            "HEAD",
            f"/v2/opencanvas-api/manifests/{finalization.MANIFEST_DIGEST}?api-version=2021-07-01",
        ),
        (
            "GET",
            f"/v2/opencanvas-api/manifests/{finalization.MANIFEST_DIGEST}?api-version=2021-07-01",
        ),
        (
            "GET",
            f"/acr/v1/opencanvas-api/_manifests/{finalization.MANIFEST_DIGEST}?api-version=2021-07-01",
        ),
        ("HEAD", f"/v2/opencanvas-api/blobs/{finalization.REGISTRY_CONFIG_DIGEST}"),
    )
    for method, path in allowed:
        lifecycle._validate_registry_request(method, path)
    with pytest.raises(lifecycle.LifecycleError, match="registry-request-scope-invalid"):
        lifecycle._validate_registry_request(
            "DELETE", f"/v2/opencanvas-api/manifests/{finalization.MANIFEST_DIGEST}"
        )


def test_retained_leaf_response_shape_proves_manifest_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_body, manifest_digest = _raw(_leaf())
    properties = {
        "registry": "registry-alias",
        "imageName": "opencanvas-api",
        "manifest": {
            "digest": manifest_digest,
            "architecture": "amd64",
            "os": "linux",
            "tags": [finalization.SOURCE_TAG],
            "changeableAttributes": {"readEnabled": True, "deleteEnabled": True},
        },
    }
    responses = iter(
        (
            (
                200,
                {"docker-content-digest": manifest_digest},
                bytearray(),
            ),
            (
                200,
                _manifest_headers(manifest_digest, finalization.OCI_MANIFEST),
                manifest_body,
            ),
            (200, {}, bytearray()),
            (200, {}, bytearray(json.dumps(properties).encode())),
        )
    )
    monkeypatch.setattr(finalization, "_registry_read", lambda *_args, **_kwargs: next(responses))
    identity = finalization._manifest_identity(
        bytearray(b"token"),
        top_level_digest=manifest_digest,
        source_tag_expected=True,
    )
    assert identity["manifestDigest"] == manifest_digest
    assert identity["configDigest"] == finalization.REGISTRY_CONFIG_DIGEST


def test_manifest_identity_rejects_config_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaf = _leaf()
    leaf["config"] = {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": "sha256:" + "8" * 64,
        "size": 123,
    }
    body, digest = _raw(leaf)
    responses = iter(
        (
            (200, {"docker-content-digest": digest}, bytearray()),
            (200, _manifest_headers(digest, finalization.OCI_MANIFEST), body),
        )
    )
    monkeypatch.setattr(finalization, "_registry_read", lambda *_args, **_kwargs: next(responses))
    with pytest.raises(
        finalization.TagFinalizationError,
        match="immutable-config-digest-mismatch",
    ):
        finalization._manifest_identity(
            bytearray(b"token"),
            top_level_digest=digest,
            source_tag_expected=True,
        )


def test_second_finalization_receipt_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "acr-tag-finalization.receipt.json"
    finalization._write_exclusive(path, {"status": "claimed"})
    with pytest.raises(finalization.TagFinalizationError, match="finalization-replay-denied"):
        finalization._write_exclusive(path, {"status": "claimed-again"})
