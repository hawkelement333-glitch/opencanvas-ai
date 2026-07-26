from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.db.runtime import (
    DatabaseRuntimeError,
    validate_postgresql_capabilities,
)
from opencanvas_api.db.session import Database


def _deployed_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_mode": "production",
        "app_url": "https://mobius.example",
        "cors_origins": ["https://mobius.example"],
        "database_url": "postgresql+asyncpg://api:test-db-credential@db/mobius",
        "database_tls_mode": "verify-full",
        "session_secret": "production-placeholder-secret-with-thirty-two-bytes",
        "invitation_secret": "production-invitation-secret-distinct-from-session",
        "password_reset_provider": "smtp",
        "smtp_host": "smtp.example",
        "smtp_from_address": "noreply@mobius.example",
        "ai_provider": "openai",
        "embedding_provider": "openai",
        "openai_api_key": "placeholder-not-live",
        "storage_provider": "s3",
        "object_storage_bucket": "mobius-production",
        "object_storage_access_key_id": "placeholder",
        "object_storage_secret_access_key": "placeholder",
        "job_provider": "database",
    }
    values.update(overrides)
    return Settings(**values)


def test_deployed_database_requires_certificate_verification() -> None:
    with pytest.raises(ValidationError, match="verified PostgreSQL TLS"):
        _deployed_settings(database_tls_mode="require")


def test_deployed_database_rejects_placeholder_credentials() -> None:
    with pytest.raises(ValidationError, match="placeholder database credential"):
        _deployed_settings(database_url="postgresql+asyncpg://api:placeholder@db/mobius")


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_complete_deployed_database_configuration_is_valid(mode: str) -> None:
    settings = _deployed_settings(app_mode=mode)

    assert settings.runtime_mode.value == mode
    assert settings.database_tls_mode == "verify-full"


def test_deployed_api_refuses_a_migration_credential_role() -> None:
    settings = _deployed_settings(database_role="migration")

    with pytest.raises(RuntimeError, match="dedicated database credential role"):
        settings.require_database_role(DatabaseRole.API)


def test_postgresql_engine_has_bounded_pool_transaction_and_timeout_policy() -> None:
    engine = Mock()
    engine.sync_engine = Mock()
    with patch("opencanvas_api.db.session.create_async_engine", return_value=engine) as create:
        database = Database(
            "postgresql+asyncpg://api:secret@db/mobius",
            pool_size=8,
            max_overflow=2,
            pool_timeout_seconds=12,
            pool_recycle_seconds=900,
            connect_timeout_seconds=7,
            statement_timeout_ms=20_000,
            lock_timeout_ms=3_000,
            idle_transaction_timeout_ms=15_000,
            tls_mode="verify-full",
            application_name="solarplexus-mobius-api",
        )

    assert database.engine is engine
    _, options = create.call_args
    assert options["pool_pre_ping"] is True
    assert options["pool_size"] == 8
    assert options["max_overflow"] == 2
    assert options["pool_timeout"] == 12
    assert options["pool_recycle"] == 900
    assert options["isolation_level"] == "READ COMMITTED"
    assert options["connect_args"] == {
        "timeout": 7,
        "ssl": "verify-full",
        "server_settings": {
            "application_name": "solarplexus-mobius-api",
            "statement_timeout": "20000",
            "lock_timeout": "3000",
            "idle_in_transaction_session_timeout": "15000",
        },
    }


def test_runtime_error_never_includes_connection_details() -> None:
    error = DatabaseRuntimeError("database_unavailable")
    assert str(error) == "database_unavailable"
    assert "postgresql" not in str(error)


def test_database_url_is_redacted_from_configuration_serialization() -> None:
    settings = Settings(database_url="postgresql+asyncpg://api:top-secret@db/mobius")

    serialized = settings.model_dump_json()

    assert "top-secret" not in serialized
    assert "postgresql+asyncpg" not in serialized
    assert '"database_url":"**********"' in serialized


@pytest.mark.parametrize(
    "database_url",
    [
        "not-a-database-url",
        "postgresql+psycopg://api:secret@db/mobius",
        "postgresql+asyncpg://api:secret@/mobius",
    ],
)
def test_deployed_database_rejects_malformed_or_unsupported_urls(database_url: str) -> None:
    with pytest.raises(ValidationError, match=r"managed PostgreSQL|postgresql\+asyncpg"):
        _deployed_settings(database_url=database_url)


def test_postgresql_17_pgvector_and_exact_schema_are_accepted() -> None:
    validate_postgresql_capabilities(
        server_version=170_005,
        vector_version="0.8.1",
        schema_revision="20260725_0025",
        expected_revision="20260725_0025",
    )


@pytest.mark.parametrize(
    ("server_version", "vector_version", "revision", "code"),
    [
        (160_010, "0.8.1", "20260725_0025", "postgresql_version_incompatible"),
        (180_001, "0.8.1", "20260725_0025", "postgresql_version_incompatible"),
        (170_005, None, "20260725_0025", "pgvector_capability_incompatible"),
        (170_005, "0.6.2", "20260725_0025", "pgvector_capability_incompatible"),
        (170_005, "0.8.1", "20260725_0024", "database_schema_incompatible"),
        (170_005, "0.8.1", "20260726_0026", "database_schema_incompatible"),
    ],
)
def test_postgresql_capability_mismatch_fails_closed(
    server_version: int,
    vector_version: str | None,
    revision: str,
    code: str,
) -> None:
    with pytest.raises(DatabaseRuntimeError, match=code):
        validate_postgresql_capabilities(
            server_version=server_version,
            vector_version=vector_version,
            schema_revision=revision,
            expected_revision="20260725_0025",
        )
