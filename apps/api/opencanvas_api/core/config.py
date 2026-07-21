from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_ROOT = (PROJECT_ROOT / ".runtime").resolve()
DEMO_RUNTIME_ROOT = (RUNTIME_ROOT / "demo").resolve()
TEST_RUNTIME_ROOT = (RUNTIME_ROOT / "test").resolve()
DEMO_DATABASE_PATH = DEMO_RUNTIME_ROOT / "opencanvas-demo.db"
DEMO_DOCUMENT_STORAGE_ROOT = DEMO_RUNTIME_ROOT / "documents"
DEMO_DATABASE_URL = f"sqlite+aiosqlite:///{DEMO_DATABASE_PATH.as_posix()}"
DEVELOPMENT_SESSION_SECRET = "development-only-session-secret-change-before-deploying"


class AppMode(StrEnum):
    DEMO = "demo"
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Single server-only configuration boundary for every runtime mode and provider."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_prefix="OPENCANVAS_",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_mode: AppMode | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_MODE", "OPENCANVAS_APP_MODE"),
    )
    # Backward-compatible inputs retained for the immutable competition runner.
    environment: Literal["development", "test", "staging", "production"] = "development"
    demo_mode: bool = False
    app_url: str = "http://localhost:3000"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite+aiosqlite:///./opencanvas.db"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    auth_enabled: bool = True
    auth_test_bypass: bool = False
    session_secret: str = Field(default=DEVELOPMENT_SESSION_SECRET, min_length=32)
    session_cookie_name: str = "mobius_session"
    session_ttl_minutes: int = Field(default=60 * 24 * 7, ge=5, le=60 * 24 * 90)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=24 * 60)
    password_reset_provider: Literal["development_token", "smtp"] = "development_token"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65_535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    smtp_starttls: bool = True
    session_same_site: Literal["lax", "strict"] = "lax"
    csrf_header_name: str = "X-CSRF-Token"

    ai_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPENCANVAS_OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-5.6-terra"
    openai_timeout_seconds: float = Field(default=45.0, ge=1.0, le=120.0)
    ai_context_character_limit: int = Field(default=60_000, ge=1_000, le=200_000)
    ai_max_output_tokens: int = Field(default=1_600, ge=64, le=16_000)
    ai_provider_configuration_version: str = "openai-responses-v1"

    embedding_provider: Literal["mock", "openai"] = "mock"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: Literal[1536] = 1536
    embedding_batch_size: int = Field(default=64, ge=1, le=256)
    embedding_provider_configuration_version: str = "openai-embeddings-v1"

    storage_provider: Literal["demo", "memory", "local", "s3"] = "local"
    document_storage_root: Path = Path("./data/documents")
    object_storage_bucket: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_endpoint: str | None = None
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    object_storage_prefix: str = "mobius"
    object_storage_force_path_style: bool = False

    job_provider: Literal["inline", "database"] = "inline"
    worker_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    worker_heartbeat_seconds: int = Field(default=15, ge=5, le=300)
    worker_stale_after_seconds: int = Field(default=120, ge=30, le=3_600)
    processing_retry_limit: int = Field(default=3, ge=0, le=10)
    processing_retry_base_seconds: int = Field(default=5, ge=1, le=3_600)
    processing_max_concurrent_per_workspace: int = Field(default=3, ge=1, le=20)

    document_max_file_size_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1_024, le=100 * 1024 * 1024
    )
    document_max_files_per_request: int = Field(default=10, ge=1, le=50)
    document_chunk_size_chars: int = Field(default=2_000, ge=256, le=12_000)
    document_chunk_overlap_chars: int = Field(default=300, ge=0, le=4_000)
    document_max_pdf_pages: int = Field(default=500, ge=1, le=2_000)
    document_max_extracted_characters: int = Field(default=5_000_000, ge=10_000, le=20_000_000)
    document_docx_max_members: int = Field(default=2_000, ge=10, le=10_000)
    document_docx_max_uncompressed_bytes: int = Field(
        default=100 * 1024 * 1024, ge=1_024 * 1024, le=500 * 1024 * 1024
    )
    document_retrieval_top_k: int = Field(default=8, ge=1, le=50)
    document_relevance_threshold: float = Field(default=0.2, ge=0.0, le=1.0)

    request_max_body_bytes: int = Field(default=30 * 1024 * 1024, ge=1_024)
    question_max_characters: int = Field(default=8_000, ge=100, le=50_000)
    requests_per_user_per_minute: int = Field(default=120, ge=1, le=10_000)
    requests_per_workspace_per_minute: int = Field(default=300, ge=1, le=10_000)
    ai_requests_per_user_per_minute: int = Field(default=20, ge=1, le=1_000)
    auth_requests_per_ip_per_minute: int = Field(default=10, ge=1, le=1_000)
    monthly_token_budget_per_workspace: int = Field(default=2_000_000, ge=1_000)
    estimated_input_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)
    estimated_output_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)

    log_level: str = "INFO"
    log_json: bool = True
    error_tracking_dsn: str | None = None
    telemetry_enabled: bool = False
    telemetry_endpoint: str | None = None
    correlation_header_name: str = "X-Request-ID"

    @field_validator(
        "openai_api_key",
        "object_storage_bucket",
        "object_storage_endpoint",
        "object_storage_access_key_id",
        "object_storage_secret_access_key",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from_address",
        "error_tracking_dsn",
        "telemetry_endpoint",
        mode="before",
    )
    @classmethod
    def empty_string_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API prefix must start with one slash and have no trailing slash")
        return value

    @field_validator("app_url")
    @classmethod
    def validate_app_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("application URL must be an absolute http(s) URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_runtime(self) -> Settings:
        mode = self.app_mode
        if mode is None:
            mode = AppMode.DEMO if self.demo_mode else AppMode(self.environment)
            self.app_mode = mode
        if self.demo_mode and mode is not AppMode.DEMO:
            raise ValueError("legacy demo mode conflicts with APP_MODE")
        if mode is AppMode.DEMO and self.environment != "development":
            raise ValueError("demo mode cannot run with the production environment")
        self.demo_mode = mode is AppMode.DEMO
        self.environment = "development" if mode is AppMode.DEMO else mode.value  # type: ignore[assignment]

        if mode is AppMode.DEMO and "storage_provider" not in self.model_fields_set:
            self.storage_provider = "demo"

        if self.document_chunk_overlap_chars >= self.document_chunk_size_chars:
            raise ValueError("document chunk overlap must be smaller than chunk size")
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS origins are not allowed")
        if self.request_max_body_bytes < self.document_max_file_size_bytes:
            raise ValueError("request body limit must be at least the document file-size limit")
        if mode is AppMode.DEMO:
            self._validate_demo_isolation()
        else:
            if self.ai_provider == "openai" and self.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY is required when the AI provider is openai")
            if self.embedding_provider == "openai" and self.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY is required when the embedding provider is openai")
        if mode is AppMode.TEST:
            if self.ai_provider != "mock" or self.embedding_provider != "mock":
                raise ValueError("test mode requires deterministic AI and embedding providers")
            if self.storage_provider not in {"memory", "local"}:
                raise ValueError("test mode requires isolated memory or local storage")
        elif mode in {AppMode.STAGING, AppMode.PRODUCTION}:
            self._validate_deployed_mode(mode)
        return self

    def _validate_demo_isolation(self) -> None:
        if self.database_url != DEMO_DATABASE_URL:
            raise ValueError("demo mode must use the isolated project-local demo database")
        if self.openai_api_key is not None:
            raise ValueError("demo mode refuses OpenAI credentials")
        if self.ai_provider != "mock" or self.embedding_provider != "mock":
            raise ValueError("demo mode requires mock AI and embedding providers")
        if self.storage_provider != "demo":
            raise ValueError("demo mode requires the isolated demo storage provider")
        if self.document_storage_root.resolve() != DEMO_DOCUMENT_STORAGE_ROOT:
            raise ValueError("demo mode must use the isolated project-local document store")
        if self.job_provider != "inline":
            raise ValueError("demo mode does not use the production worker")

    def _validate_deployed_mode(self, mode: AppMode) -> None:
        label = mode.value
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError(f"{label} requires a postgresql+asyncpg database URL")
        if not self.app_url.startswith("https://"):
            raise ValueError(f"{label} requires an HTTPS application URL")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            raise ValueError(f"{label} requires an explicit HTTPS CORS allowlist")
        if not self.auth_enabled or self.auth_test_bypass:
            raise ValueError(f"{label} requires authentication without a bypass")
        if self.password_reset_provider != "smtp":
            raise ValueError(f"{label} requires SMTP password-reset delivery")
        if self.smtp_host is None or self.smtp_from_address is None:
            raise ValueError(f"{label} requires SMTP_HOST and SMTP_FROM_ADDRESS")
        if (
            self.session_secret == DEVELOPMENT_SESSION_SECRET
            or len(self.session_secret.encode("utf-8")) < 32
        ):
            raise ValueError(f"{label} requires a unique session secret of at least 32 bytes")
        if self.ai_provider != "openai" or self.embedding_provider != "openai":
            raise ValueError(f"{label} refuses mock AI and embedding providers")
        if self.storage_provider != "s3":
            raise ValueError(f"{label} requires durable S3-compatible object storage")
        required_storage = {
            "OPENCANVAS_OBJECT_STORAGE_BUCKET": self.object_storage_bucket,
            "OPENCANVAS_OBJECT_STORAGE_ACCESS_KEY_ID": self.object_storage_access_key_id,
            "OPENCANVAS_OBJECT_STORAGE_SECRET_ACCESS_KEY": self.object_storage_secret_access_key,
        }
        missing = [name for name, value in required_storage.items() if not value]
        if missing:
            raise ValueError(f"{label} object storage is missing: {', '.join(missing)}")
        if self.job_provider != "database":
            raise ValueError(f"{label} requires the database-backed worker provider")

    @property
    def runtime_mode(self) -> AppMode:
        if self.app_mode is None:  # pragma: no cover - model validation always resolves it
            raise RuntimeError("APP_MODE was not resolved")
        return self.app_mode

    @property
    def secure_cookies(self) -> bool:
        return self.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}

    @property
    def openai_configured(self) -> bool:
        return self.ai_provider == "openai" and self.openai_api_key is not None

    @property
    def effective_ai_provider(self) -> Literal["mock", "openai"]:
        return self.ai_provider

    @property
    def effective_embedding_provider(self) -> Literal["mock", "openai"]:
        return self.embedding_provider


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "DEMO_DATABASE_PATH",
    "DEMO_DATABASE_URL",
    "DEMO_DOCUMENT_STORAGE_ROOT",
    "DEMO_RUNTIME_ROOT",
    "DEVELOPMENT_SESSION_SECRET",
    "PROJECT_ROOT",
    "RUNTIME_ROOT",
    "TEST_RUNTIME_ROOT",
    "AppMode",
    "Settings",
    "get_settings",
]
