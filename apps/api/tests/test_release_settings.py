import pytest
from pydantic import ValidationError

from opencanvas_api.core.config import Settings

pytestmark = pytest.mark.security


def test_explicit_openai_provider_requires_server_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY is required"):
        Settings(ai_provider="openai", openai_api_key=None)


def test_explicit_openai_embedding_provider_requires_server_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY is required"):
        Settings(embedding_provider="openai", openai_api_key=None)


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS origins are not allowed"):
        Settings(cors_origins=["*"])


def test_production_requires_postgresql() -> None:
    with pytest.raises(ValidationError, match="production requires"):
        Settings(environment="production", database_url="sqlite+aiosqlite:///unsafe.db")


def test_production_refuses_mock_provider_fallback() -> None:
    with pytest.raises(ValidationError, match="refuses mock AI"):
        Settings(
            environment="production",
            app_url="https://mobius.example",
            cors_origins=["https://mobius.example"],
            database_url="postgresql+asyncpg://user:placeholder@db/opencanvas",
            session_secret="production-placeholder-secret-with-thirty-two-bytes",
            password_reset_provider="smtp",
            smtp_host="smtp.example",
            smtp_from_address="noreply@mobius.example",
            ai_provider="mock",
            embedding_provider="mock",
        )


def test_production_accepts_complete_explicit_configuration() -> None:
    settings = Settings(
        app_mode="production",
        app_url="https://mobius.example",
        cors_origins=["https://mobius.example"],
        database_url="postgresql+asyncpg://user:placeholder@db/opencanvas",
        session_secret="production-placeholder-secret-with-thirty-two-bytes",
        password_reset_provider="smtp",
        smtp_host="smtp.example",
        smtp_from_address="noreply@mobius.example",
        ai_provider="openai",
        embedding_provider="openai",
        openai_api_key="placeholder-not-live",
        storage_provider="s3",
        object_storage_bucket="mobius-production",
        object_storage_access_key_id="placeholder",
        object_storage_secret_access_key="placeholder",
        job_provider="database",
    )

    assert settings.runtime_mode.value == "production"
    assert settings.effective_ai_provider == "openai"
    assert settings.secure_cookies is True
