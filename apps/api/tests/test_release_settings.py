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


def test_production_accepts_async_postgresql_without_live_ai() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://user:placeholder@db/opencanvas",
        ai_provider="mock",
        embedding_provider="mock",
    )

    assert settings.environment == "production"
    assert settings.effective_ai_provider == "mock"
