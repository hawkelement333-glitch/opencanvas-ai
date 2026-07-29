from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from opencanvas_api.core.config import AppMode, Settings
from opencanvas_api.services import rate_limits
from opencanvas_api.services.rate_limits import (
    EntraRedisAuthentication,
    RecoveryAclRedisAuthentication,
    RedisAtomicRateLimitStore,
    SharedRateLimitUnavailable,
    build_shared_rate_limit_service,
)

pytestmark = pytest.mark.security


def _write_secret_file(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def _recovery_settings(tmp_path: Path, **overrides: object) -> Settings:
    username_file = _write_secret_file(tmp_path / "limiter-username", "recovery-limiter")
    password_file = _write_secret_file(tmp_path / "limiter-password", "test-only-acl-password")
    ca_file = _write_secret_file(tmp_path / "limiter-ca.pem", "test-ca")
    values: dict[str, object] = {
        "app_mode": "recovery",
        "shared_rate_limit_provider": "redis",
        "shared_rate_limit_auth_mode": "acl",
        "shared_rate_limit_redis_url": "rediss://127.0.0.1:6380/0",
        "shared_rate_limit_acl_username_file": username_file,
        "shared_rate_limit_acl_password_file": password_file,
        "shared_rate_limit_tls_ca_file": ca_file,
        "shared_rate_limit_recovery_epoch": "exercise-001",
        "shared_rate_limit_hmac_secret": "test-rate-limit-secret-that-is-long-enough",
        "shared_rate_limit_deployment": "recovery",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_rate_limit_authentication_is_unchanged() -> None:
    settings = Settings()

    assert settings.runtime_mode is AppMode.DEVELOPMENT
    assert settings.shared_rate_limit_auth_mode == "entra"
    assert settings.shared_rate_limit_provider == "memory"


def test_recovery_acl_configuration_is_accepted_and_builds_shared_store(tmp_path: Path) -> None:
    settings = _recovery_settings(tmp_path)
    limiter = build_shared_rate_limit_service(settings)

    assert isinstance(limiter.store, RedisAtomicRateLimitStore)
    assert limiter.deployment == "recovery.exercise-001"


@pytest.mark.parametrize("environment", ["development", "test", "staging", "production"])
def test_acl_authentication_is_rejected_outside_recovery(
    tmp_path: Path,
    environment: str,
) -> None:
    values = _recovery_settings(tmp_path).model_dump()
    values["app_mode"] = None
    values["environment"] = environment

    with pytest.raises(ValidationError, match="limited to recovery mode"):
        Settings(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("shared_rate_limit_redis_url", "redis://127.0.0.1:6380/0", "credential-free rediss"),
        (
            "shared_rate_limit_redis_url",
            "rediss://redis.private.example:6380/0",
            "loopback Redis endpoint",
        ),
        (
            "shared_rate_limit_redis_url",
            "rediss://user:password@127.0.0.1:6380/0",
            "credential-free rediss",
        ),
    ],
)
def test_recovery_acl_rejects_unsafe_redis_urls(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _recovery_settings(tmp_path, **{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "shared_rate_limit_acl_username_file",
        "shared_rate_limit_acl_password_file",
        "shared_rate_limit_tls_ca_file",
    ],
)
def test_recovery_acl_requires_readable_nonempty_secret_files(tmp_path: Path, field: str) -> None:
    missing_path = tmp_path / "missing-secret"
    with pytest.raises(ValidationError, match="secret file"):
        _recovery_settings(tmp_path, **{field: missing_path})

    empty_path = _write_secret_file(tmp_path / f"empty-{field}", "")
    with pytest.raises(ValidationError, match="non-empty"):
        _recovery_settings(tmp_path, **{field: empty_path})


def test_recovery_acl_requires_an_explicit_epoch(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="explicit limiter epoch"):
        _recovery_settings(tmp_path, shared_rate_limit_recovery_epoch=None)


def test_entra_configuration_still_rejects_credentials_in_url() -> None:
    with pytest.raises(ValidationError, match="credential-free rediss"):
        Settings(shared_rate_limit_redis_url="rediss://user:password@redis.example:10000/0")


class _CapturingRedis:
    kwargs: dict[str, object]

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        type(self).kwargs = kwargs

    async def aclose(self) -> None:
        return None


class _DeniedRedis(_CapturingRedis):
    async def eval(self, *_args: object) -> object:
        raise RuntimeError("authentication denied")


@pytest.mark.asyncio
async def test_recovery_acl_does_not_request_entra_token_and_enforces_tls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_identity_client(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("ACL mode must not request an Entra token")

    monkeypatch.setattr(rate_limits.httpx, "AsyncClient", unexpected_identity_client)
    monkeypatch.setattr(rate_limits, "Redis", _CapturingRedis)
    limiter = build_shared_rate_limit_service(_recovery_settings(tmp_path))
    store = limiter.store
    assert isinstance(store, RedisAtomicRateLimitStore)

    await store._get_client()

    assert _CapturingRedis.kwargs["username"] == "recovery-limiter"
    assert _CapturingRedis.kwargs["password"] == "test-only-acl-password"
    assert _CapturingRedis.kwargs["ssl"] is True
    assert _CapturingRedis.kwargs["ssl_cert_reqs"] == "required"
    assert _CapturingRedis.kwargs["ssl_ca_certs"] == str(tmp_path / "limiter-ca.pem")


@pytest.mark.asyncio
async def test_acl_authentication_denial_is_generic_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limits, "Redis", _DeniedRedis)
    limiter = build_shared_rate_limit_service(_recovery_settings(tmp_path))

    with pytest.raises(SharedRateLimitUnavailable) as exc_info:
        await limiter.consume(
            operation="upload",
            dimensions=[rate_limits.RateLimitDimension("workspace", "workspace-a", 1)],
        )

    assert "test-only-acl-password" not in str(exc_info.value)
    assert "recovery-limiter" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_entra_authentication_preserves_existing_audience_and_token_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"access_token": "test-entra-token", "expires_on": "2147483647"}

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> _Response:
            captured["url"] = url
            captured.update(kwargs)
            return _Response()

    monkeypatch.setattr(rate_limits.httpx, "AsyncClient", lambda **_kwargs: _Client())
    authentication = EntraRedisAuthentication(
        username="managed-identity",
        managed_identity_endpoint="https://identity.invalid/token",
        managed_identity_header="test-header",
        operation_timeout_seconds=1.0,
    )

    credentials = await authentication.credentials()

    assert credentials.username == "managed-identity"
    assert credentials.password == "test-entra-token"
    assert credentials.expires_at == 2_147_483_647
    assert captured["url"] == "https://identity.invalid/token"
    assert captured["params"] == {
        "api-version": "2019-08-01",
        "resource": "https://redis.azure.com",
    }
    assert captured["headers"] == {"Metadata": "true", "X-IDENTITY-HEADER": "test-header"}


@pytest.mark.asyncio
async def test_entra_redis_client_keeps_platform_tls_trust_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fixed_credentials(_self: EntraRedisAuthentication) -> rate_limits.RedisCredentials:
        token = "test-entra-token"
        return rate_limits.RedisCredentials(
            username="managed-identity",
            password=token,
            expires_at=2_147_483_647,
        )

    monkeypatch.setattr(EntraRedisAuthentication, "credentials", fixed_credentials)
    monkeypatch.setattr(rate_limits, "Redis", _CapturingRedis)
    store = RedisAtomicRateLimitStore(
        redis_url="rediss://redis.example:10000/0",
        authentication=EntraRedisAuthentication(
            username="managed-identity",
            managed_identity_endpoint="https://identity.invalid/token",
            managed_identity_header=None,
            operation_timeout_seconds=1.0,
        ),
        connect_timeout_seconds=1.0,
        operation_timeout_seconds=1.0,
    )

    await store._get_client()

    assert _CapturingRedis.kwargs["ssl_cert_reqs"] == "required"
    assert "ssl_ca_certs" not in _CapturingRedis.kwargs


@pytest.mark.asyncio
async def test_recovery_epoch_changes_only_the_recovery_deployment_scope(tmp_path: Path) -> None:
    first = build_shared_rate_limit_service(_recovery_settings(tmp_path))
    second = build_shared_rate_limit_service(
        _recovery_settings(tmp_path, shared_rate_limit_recovery_epoch="exercise-002")
    )
    dimension = rate_limits.RateLimitDimension("workspace", "workspace-a", 1)

    assert first._key("upload", dimension) != second._key("upload", dimension)


@pytest.mark.asyncio
async def test_recovery_acl_store_never_falls_back_to_memory(tmp_path: Path) -> None:
    limiter = build_shared_rate_limit_service(_recovery_settings(tmp_path))

    assert isinstance(limiter.store, RedisAtomicRateLimitStore)
    assert not isinstance(limiter.store, rate_limits.InMemoryAtomicRateLimitStore)


def test_acl_authentication_type_is_recovery_only() -> None:
    authentication = RecoveryAclRedisAuthentication(username="user", password="password")

    assert authentication.username == "user"
