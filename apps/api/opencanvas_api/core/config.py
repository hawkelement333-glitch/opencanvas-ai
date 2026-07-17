from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEMO_RUNTIME_ROOT = (PROJECT_ROOT / ".runtime" / "demo").resolve()
DEMO_DATABASE_PATH = DEMO_RUNTIME_ROOT / "opencanvas-demo.db"
DEMO_DOCUMENT_STORAGE_ROOT = DEMO_RUNTIME_ROOT / "documents"
DEMO_DATABASE_URL = f"sqlite+aiosqlite:///{DEMO_DATABASE_PATH.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_prefix="OPENCANVAS_",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    demo_mode: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./opencanvas.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    ai_provider: Literal["auto", "mock", "openai"] = "auto"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPENCANVAS_OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-5.6-terra"
    openai_timeout_seconds: float = Field(default=45.0, ge=1.0, le=120.0)
    ai_context_character_limit: int = Field(default=60_000, ge=1_000, le=200_000)

    document_storage_root: Path = Path("./data/documents")
    document_max_file_size_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1_024, le=100 * 1024 * 1024
    )
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
    embedding_provider: Literal["auto", "mock", "openai"] = "auto"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: Literal[1536] = 1536
    embedding_batch_size: int = Field(default=64, ge=1, le=256)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_key_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_document_chunking(self) -> Settings:
        if self.document_chunk_overlap_chars >= self.document_chunk_size_chars:
            raise ValueError("document chunk overlap must be smaller than chunk size")
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS origins are not allowed")
        if self.demo_mode:
            self._validate_demo_isolation()
        if self.ai_provider == "openai" and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when the AI provider is openai")
        if self.embedding_provider == "openai" and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when the embedding provider is openai")
        if self.environment == "production" and not self.database_url.startswith(
            "postgresql+asyncpg://"
        ):
            raise ValueError("production requires a postgresql+asyncpg database URL")
        return self

    def _validate_demo_isolation(self) -> None:
        if self.environment == "production":
            raise ValueError("demo mode cannot run with the production environment")
        if self.database_url != DEMO_DATABASE_URL:
            raise ValueError("demo mode must use the isolated project-local demo database")
        if self.openai_api_key is not None:
            raise ValueError("demo mode refuses OpenAI credentials")
        if self.ai_provider != "mock" or self.embedding_provider != "mock":
            raise ValueError("demo mode requires mock AI and embedding providers")
        if self.document_storage_root.resolve() != DEMO_DOCUMENT_STORAGE_ROOT:
            raise ValueError("demo mode must use the isolated project-local document store")

    @property
    def openai_configured(self) -> bool:
        return self.effective_ai_provider == "openai"

    @property
    def effective_ai_provider(self) -> Literal["mock", "openai"]:
        if self.ai_provider == "mock" or not self.openai_api_key:
            return "mock"
        return "openai"

    @property
    def effective_embedding_provider(self) -> Literal["mock", "openai"]:
        if self.embedding_provider == "mock" or not self.openai_api_key:
            return "mock"
        return "openai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
