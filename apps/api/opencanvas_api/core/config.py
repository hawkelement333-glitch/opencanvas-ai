from __future__ import annotations

import os
import re
import uuid
from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_ROOT = (PROJECT_ROOT / ".runtime").resolve()
DEMO_RUNTIME_ROOT = (RUNTIME_ROOT / "demo").resolve()
TEST_RUNTIME_ROOT = (RUNTIME_ROOT / "test").resolve()
DEMO_DATABASE_PATH = DEMO_RUNTIME_ROOT / "opencanvas-demo.db"
DEMO_DOCUMENT_STORAGE_ROOT = DEMO_RUNTIME_ROOT / "documents"
DEMO_DATABASE_URL = f"sqlite+aiosqlite:///{DEMO_DATABASE_PATH.as_posix()}"
DEVELOPMENT_SESSION_SECRET = "development-only-session-secret-change-before-deploying"
DEVELOPMENT_INVITATION_SECRET = "development-only-invitation-secret-change-before-deploying"
DEVELOPMENT_UPLOAD_CAPABILITY_SECRET = (
    "development-only-upload-capability-secret-change-before-deploying"
)
DEVELOPMENT_SCANNER_RESULT_SECRET = "development-only-scanner-result-secret-change-before-deploying"
DEVELOPMENT_RATE_LIMIT_SECRET = "development-only-rate-limit-secret-change-before-deploying"
DEVELOPMENT_TELEMETRY_SECRET = "development-only-telemetry-secret-change-before-deploying"
EXPECTED_DATABASE_REVISION = "20260726_0029"


class AppMode(StrEnum):
    DEMO = "demo"
    DEVELOPMENT = "development"
    TEST = "test"
    RECOVERY = "recovery"
    STAGING = "staging"
    PRODUCTION = "production"


class DatabaseRole(StrEnum):
    API = "api"
    WORKER = "worker"
    PROVISIONING = "provisioning"
    MIGRATION = "migration"
    BACKUP = "backup"
    OBSERVABILITY = "observability"
    EMERGENCY = "emergency"


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
    environment: Literal["development", "test", "recovery", "staging", "production"] = "development"
    demo_mode: bool = False
    app_url: str = "http://localhost:3000"
    api_prefix: str = "/api/v1"

    database_url: SecretStr = SecretStr("sqlite+aiosqlite:///./opencanvas.db")
    database_role: DatabaseRole = DatabaseRole.API
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=0, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    database_pool_recycle_seconds: int = Field(default=1_800, ge=60, le=7_200)
    database_connect_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    database_statement_timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    database_lock_timeout_ms: int = Field(default=5_000, ge=100, le=30_000)
    database_idle_transaction_timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    database_tls_mode: Literal["disable", "require", "verify-ca", "verify-full"] = "disable"
    database_auth_mode: Literal["password", "entra"] = "password"
    database_managed_identity_endpoint: str | None = None
    database_managed_identity_header: str | None = None
    database_managed_identity_client_id: str | None = None
    database_application_name: str = Field(
        default="solarplexus-mobius", min_length=3, max_length=63, pattern=r"^[a-z0-9-]+$"
    )
    database_expected_revision: str = Field(
        default=EXPECTED_DATABASE_REVISION, pattern=r"^\d{8}_\d{4}$"
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    auth_enabled: bool = True
    auth_test_bypass: bool = False
    session_secret: str = Field(default=DEVELOPMENT_SESSION_SECRET, min_length=32)
    invitation_secret: str = Field(default=DEVELOPMENT_INVITATION_SECRET, min_length=32)
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
    embedding_dimensions: int = Field(default=1536, ge=1536, le=1536)
    embedding_batch_size: int = Field(default=64, ge=1, le=256)
    embedding_provider_configuration_version: str = "openai-embeddings-v1"

    storage_provider: Literal["demo", "memory", "local", "s3", "azure"] = "local"
    document_storage_root: Path = Path("./data/documents")
    object_storage_bucket: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_endpoint: str | None = None
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    object_storage_prefix: str = "mobius"
    object_storage_force_path_style: bool = False
    azure_storage_account_url: str | None = None
    azure_quarantine_container: str = "quarantine"
    azure_clean_container: str = "clean"
    azure_rejected_container: str = "rejected"
    azure_retained_container: str = "retained"
    azure_managed_identity_endpoint: str | None = None
    azure_managed_identity_header: str | None = None
    azure_managed_identity_client_id: str | None = None

    object_ingestion_mode: Literal["disabled", "deterministic", "trusted"] = "disabled"
    upload_capability_secret: str = Field(
        default=DEVELOPMENT_UPLOAD_CAPABILITY_SECRET,
        min_length=32,
    )
    scanner_result_secret: str = Field(
        default=DEVELOPMENT_SCANNER_RESULT_SECRET,
        min_length=32,
    )
    upload_capability_ttl_seconds: int = Field(default=300, ge=60, le=900)
    upload_max_active_sessions_per_workspace: int = Field(default=10, ge=1, le=100)
    scanner_result_requests_per_minute: int = Field(default=120, ge=1, le=10_000)
    malware_scan_timeout_seconds: int = Field(default=300, ge=30, le=3_600)
    malware_scan_result_max_age_seconds: int = Field(default=86_400, ge=60, le=604_800)
    malware_scanner_identity: str = Field(
        default="deterministic-test-scanner",
        min_length=3,
        max_length=120,
    )
    malware_scanner_version: str = Field(default="v1", min_length=1, max_length=120)
    malware_policy_version: str = Field(
        default="mobius-malware-policy-v1",
        min_length=3,
        max_length=120,
    )
    scanner_result_bridge_mode: Literal["disabled", "private_pull"] = "disabled"
    azure_log_analytics_workspace_id: uuid.UUID | None = None
    azure_log_analytics_endpoint: str = "https://api.loganalytics.azure.com"
    scanner_result_bridge_batch_size: int = Field(default=10, ge=1, le=100)
    scanner_result_bridge_max_log_rows: int = Field(default=4, ge=1, le=8)
    scanner_result_bridge_query_timeout_seconds: float = Field(default=20.0, ge=1.0, le=30.0)
    scanner_result_bridge_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    scanner_result_bridge_retry_max_seconds: int = Field(default=300, ge=1, le=3_600)
    object_promotion_service_identity: str = Field(
        default="mobius-object-promotion",
        min_length=3,
        max_length=120,
    )

    job_provider: Literal["inline", "database"] = "inline"
    worker_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    worker_heartbeat_seconds: int = Field(default=15, ge=5, le=300)
    worker_stale_after_seconds: int = Field(default=120, ge=30, le=3_600)
    processing_retry_limit: int = Field(default=3, ge=0, le=10)
    processing_retry_base_seconds: int = Field(default=5, ge=1, le=3_600)
    processing_max_concurrent_per_workspace: int = Field(default=3, ge=1, le=20)
    processing_max_concurrent_global: int = Field(default=32, ge=1, le=1_000)
    processing_lease_seconds: int = Field(default=60, ge=5, le=900)
    processing_job_deadline_seconds: int = Field(default=3_600, ge=30, le=604_800)
    processing_retry_max_seconds: int = Field(default=900, ge=1, le=86_400)

    shared_rate_limit_provider: Literal["memory", "redis"] = "memory"
    shared_rate_limit_auth_mode: Literal["entra", "acl"] = "entra"
    shared_rate_limit_redis_url: str | None = None
    shared_rate_limit_redis_username: str | None = None
    shared_rate_limit_identity_endpoint: str | None = None
    shared_rate_limit_identity_header: str | None = None
    shared_rate_limit_identity_client_id: str | None = None
    shared_rate_limit_acl_username_file: Path | None = None
    shared_rate_limit_acl_password_file: Path | None = None
    shared_rate_limit_tls_ca_file: Path | None = None
    shared_rate_limit_recovery_epoch: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{0,63}$",
    )
    shared_rate_limit_hmac_secret: str = Field(
        default=DEVELOPMENT_RATE_LIMIT_SECRET,
        min_length=32,
    )
    shared_rate_limit_namespace: str = Field(default="mobius", pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    shared_rate_limit_deployment: str = Field(default="local", pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    shared_rate_limit_connect_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10.0)
    shared_rate_limit_operation_timeout_seconds: float = Field(default=1.0, ge=0.05, le=5.0)
    shared_rate_limit_emergency_requests_per_minute: int = Field(
        default=10_000,
        ge=1,
        le=10_000_000,
    )

    indexer_publication_mode: Literal["disabled", "private_legacy", "private_clean"] = "disabled"
    indexer_parser_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    indexer_parser_memory_limit_bytes: int = Field(
        default=512 * 1024 * 1024, ge=64 * 1024 * 1024, le=2 * 1024 * 1024 * 1024
    )
    indexer_parser_cpu_seconds: int = Field(default=30, ge=1, le=300)
    indexer_max_active_requests_per_workspace: int = Field(default=10, ge=1, le=100)
    indexer_manifest_schema_version: str = "pipeline-manifest-v1"
    indexer_parser_version: str = "mobius-parser-v1"
    indexer_parser_build_digest: str = (
        "8c3f2d3ec499d52e6156636b25165d20615eebf6c1d61a18675623c33757f61b"
    )
    indexer_normalizer_version: str = "mobius-normalizer-v1"
    indexer_metadata_version: str = "mobius-allowlisted-metadata-v1"
    indexer_chunker_version: str = "mobius-chunker-v1"
    indexer_version: str = "mobius-indexer-v1"
    indexer_schema_version: str = "immutable-index-v1"

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
    document_docx_max_compression_ratio: int = Field(default=100, ge=2, le=1_000)
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

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    error_tracking_dsn: str | None = None
    telemetry_enabled: bool = False
    telemetry_exporter: Literal["disabled", "memory", "http"] = "disabled"
    telemetry_endpoint: str | None = None
    telemetry_service_name: str = Field(
        default="opencanvas-api",
        pattern=r"^[a-z][a-z0-9-]{1,62}$",
    )
    telemetry_release: str = Field(default="local-development", min_length=3, max_length=80)
    telemetry_deployment: str = Field(
        default="local",
        pattern=r"^[a-z][a-z0-9_.-]{0,63}$",
    )
    telemetry_auth_secret_reference: str | None = None
    telemetry_tls_verify: bool = True
    telemetry_export_timeout_seconds: float = Field(default=2.0, ge=0.05, le=10.0)
    telemetry_shutdown_timeout_seconds: float = Field(default=3.0, ge=0.1, le=10.0)
    telemetry_batch_size: int = Field(default=64, ge=1, le=512)
    telemetry_buffer_size: int = Field(default=1_024, ge=16, le=10_000)
    telemetry_retry_limit: int = Field(default=2, ge=0, le=5)
    telemetry_sample_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    telemetry_max_span_depth: int = Field(default=16, ge=1, le=64)
    telemetry_max_span_events: int = Field(default=16, ge=0, le=64)
    telemetry_max_span_attributes: int = Field(default=16, ge=1, le=64)
    telemetry_pseudonymization_secret: str = Field(
        default=DEVELOPMENT_TELEMETRY_SECRET,
        min_length=32,
    )
    telemetry_baggage_allowlist: list[str] = Field(
        default_factory=lambda: ["operation", "component"]
    )
    telemetry_cardinality_budget: int = Field(default=128, ge=8, le=2_000)
    telemetry_health_failure_threshold: int = Field(default=3, ge=1, le=20)
    telemetry_application_log_retention_days: int = Field(default=30, ge=1, le=90)
    telemetry_security_log_retention_days: int = Field(default=90, ge=7, le=365)
    telemetry_metric_retention_days: int = Field(default=30, ge=7, le=90)
    telemetry_trace_retention_days: int = Field(default=14, ge=1, le=30)
    telemetry_incident_retention_days: int = Field(default=365, ge=30, le=2_555)
    telemetry_objective_version: str = Field(
        default="mobius-internal-slos-v1",
        pattern=r"^[a-z][a-z0-9_.-]{2,63}$",
    )
    telemetry_queue_age_alert_seconds: int = Field(default=300, ge=30, le=86_400)
    telemetry_error_rate_alert_ratio: float = Field(default=0.05, gt=0.0, le=1.0)
    telemetry_dropped_signal_alert_count: int = Field(default=1, ge=1, le=1_000_000)
    observability_operator_user_ids: list[uuid.UUID] = Field(default_factory=list)
    correlation_header_name: str = "X-Request-ID"

    @field_validator(
        "openai_api_key",
        "object_storage_bucket",
        "object_storage_endpoint",
        "object_storage_access_key_id",
        "object_storage_secret_access_key",
        "azure_storage_account_url",
        "azure_managed_identity_endpoint",
        "azure_managed_identity_header",
        "azure_managed_identity_client_id",
        "shared_rate_limit_redis_url",
        "shared_rate_limit_redis_username",
        "shared_rate_limit_identity_endpoint",
        "shared_rate_limit_identity_header",
        "shared_rate_limit_identity_client_id",
        "shared_rate_limit_acl_username_file",
        "shared_rate_limit_acl_password_file",
        "shared_rate_limit_tls_ca_file",
        "shared_rate_limit_recovery_epoch",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from_address",
        "error_tracking_dsn",
        "telemetry_endpoint",
        "telemetry_auth_secret_reference",
        mode="before",
    )
    @classmethod
    def empty_string_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

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

    @field_validator("azure_storage_account_url")
    @classmethod
    def validate_azure_storage_account_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("Azure storage account URL must be an HTTPS origin")
        return value.rstrip("/")

    @field_validator("azure_log_analytics_endpoint")
    @classmethod
    def validate_azure_log_analytics_endpoint(cls, value: str) -> str:
        parsed = urlparse(value.rstrip("/"))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.loganalytics.azure.com"
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Log Analytics requires the exact private-query endpoint")
        return value.rstrip("/")

    @field_validator("shared_rate_limit_redis_url")
    @classmethod
    def validate_shared_rate_limit_redis_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if (
            parsed.scheme != "rediss"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/", "/0"}
        ):
            raise ValueError(
                "shared Redis must be a credential-free rediss URL using database zero"
            )
        return value

    @field_validator(
        "azure_quarantine_container",
        "azure_clean_container",
        "azure_rejected_container",
        "azure_retained_container",
    )
    @classmethod
    def validate_azure_container(cls, value: str) -> str:
        if (
            not 3 <= len(value) <= 63
            or value != value.lower()
            or not value[0].isalnum()
            or not value[-1].isalnum()
            or any(not (character.isalnum() or character == "-") for character in value)
            or "--" in value
        ):
            raise ValueError("Azure container names must satisfy the Blob naming contract")
        return value

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

        # Azure Container Apps injects these two values for every managed-identity
        # enabled replica.  Map that provider-owned contract into each explicit
        # application boundary without copying tokens or identity headers into
        # deployment parameters.
        identity_endpoint = os.getenv("IDENTITY_ENDPOINT")
        identity_header = os.getenv("IDENTITY_HEADER")
        if identity_endpoint:
            if self.database_managed_identity_endpoint is None:
                self.database_managed_identity_endpoint = identity_endpoint
            if self.database_managed_identity_header is None:
                self.database_managed_identity_header = identity_header
            if self.azure_managed_identity_endpoint is None:
                self.azure_managed_identity_endpoint = identity_endpoint
            if self.azure_managed_identity_header is None:
                self.azure_managed_identity_header = identity_header
            if self.shared_rate_limit_identity_endpoint is None:
                self.shared_rate_limit_identity_endpoint = identity_endpoint
            if self.shared_rate_limit_identity_header is None:
                self.shared_rate_limit_identity_header = identity_header

        if mode is AppMode.DEMO and "storage_provider" not in self.model_fields_set:
            self.storage_provider = "demo"
        if (
            mode in {AppMode.DEVELOPMENT, AppMode.TEST, AppMode.DEMO}
            and "indexer_publication_mode" not in self.model_fields_set
        ):
            self.indexer_publication_mode = "private_legacy"

        if self.document_chunk_overlap_chars >= self.document_chunk_size_chars:
            raise ValueError("document chunk overlap must be smaller than chunk size")
        if self.processing_retry_base_seconds > self.processing_retry_max_seconds:
            raise ValueError("processing retry base cannot exceed the retry maximum")
        if (
            self.scanner_result_bridge_retry_base_seconds
            > self.scanner_result_bridge_retry_max_seconds
        ):
            raise ValueError("scanner bridge retry base cannot exceed the retry maximum")
        if self.telemetry_batch_size > self.telemetry_buffer_size:
            raise ValueError("telemetry batch size cannot exceed the bounded buffer")
        if len(set(self.telemetry_baggage_allowlist)) != len(
            self.telemetry_baggage_allowlist
        ) or any(
            not re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", value)
            for value in self.telemetry_baggage_allowlist
        ):
            raise ValueError("telemetry baggage allowlist is invalid")
        if self.telemetry_exporter == "http" and not self.telemetry_endpoint:
            raise ValueError("HTTP telemetry export requires an endpoint")
        if self.telemetry_enabled and self.telemetry_exporter == "disabled":
            raise ValueError("enabled telemetry requires an explicit bounded exporter")
        if not self.telemetry_enabled and self.telemetry_exporter != "disabled":
            raise ValueError("a telemetry exporter requires telemetry enablement")
        if self.telemetry_endpoint is not None and urlparse(self.telemetry_endpoint).scheme not in {
            "http",
            "https",
        }:
            raise ValueError("telemetry endpoint must be an absolute HTTP(S) URL")
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS origins are not allowed")
        if self.request_max_body_bytes < self.document_max_file_size_bytes:
            raise ValueError("request body limit must be at least the document file-size limit")
        if self.shared_rate_limit_auth_mode == "acl" and mode is not AppMode.RECOVERY:
            raise ValueError("ACL shared Redis authentication is limited to recovery mode")
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
            if self.object_ingestion_mode == "trusted":
                raise ValueError("test mode refuses trusted external scanner results")
        elif mode is AppMode.RECOVERY:
            self._validate_recovery_mode()
        elif mode in {AppMode.STAGING, AppMode.PRODUCTION}:
            self._validate_deployed_mode(mode)
        return self

    def _validate_recovery_mode(self) -> None:
        if self.shared_rate_limit_provider != "redis":
            raise ValueError("recovery mode requires the shared Redis rate-limit provider")
        if self.shared_rate_limit_auth_mode != "acl":
            raise ValueError("recovery mode requires recovery-only ACL authentication")
        if self.shared_rate_limit_identity_endpoint is not None:
            raise ValueError("recovery ACL authentication refuses a managed identity endpoint")
        if self.shared_rate_limit_identity_header is not None:
            raise ValueError("recovery ACL authentication refuses a managed identity header")
        if self.shared_rate_limit_redis_username is not None:
            raise ValueError(
                "recovery ACL authentication requires a username secret-file reference"
            )
        if self.shared_rate_limit_redis_url is None:
            raise ValueError("recovery ACL authentication requires a Redis URL")
        parsed = urlparse(self.shared_rate_limit_redis_url)
        try:
            loopback = ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("recovery ACL authentication requires a loopback Redis endpoint")
        for label, path in {
            "ACL username": self.shared_rate_limit_acl_username_file,
            "ACL password": self.shared_rate_limit_acl_password_file,
            "TLS trust": self.shared_rate_limit_tls_ca_file,
        }.items():
            self._read_required_secret_file(path, label)
        if self.shared_rate_limit_recovery_epoch is None:
            raise ValueError("recovery ACL authentication requires an explicit limiter epoch")

    @staticmethod
    def _read_required_secret_file(path: Path | None, label: str) -> str:
        if path is None:
            raise ValueError(
                f"recovery ACL authentication requires a {label} secret-file reference"
            )
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(
                f"recovery ACL authentication could not read the {label} secret file"
            ) from exc
        if not value:
            raise ValueError(
                f"recovery ACL authentication requires a non-empty {label} secret file"
            )
        return value

    def _validate_demo_isolation(self) -> None:
        if self.database_url_value != DEMO_DATABASE_URL:
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
        try:
            database_url = make_url(self.database_url_value)
        except ArgumentError as exc:
            raise ValueError(f"{label} requires a valid managed PostgreSQL database URL") from exc
        if database_url.drivername != "postgresql+asyncpg":
            raise ValueError(f"{label} requires a postgresql+asyncpg database URL")
        if not database_url.host or not database_url.database or not database_url.username:
            raise ValueError(f"{label} requires a complete managed PostgreSQL database URL")
        if database_url.password is not None and database_url.password.lower() in {
            "changeme",
            "password",
            "placeholder",
            "secret",
        }:
            raise ValueError(f"{label} refuses a placeholder database credential")
        if self.database_tls_mode != "verify-full":
            raise ValueError(f"{label} requires verified PostgreSQL TLS")
        if self.database_auth_mode == "entra":
            required_database_identity = {
                "OPENCANVAS_DATABASE_MANAGED_IDENTITY_ENDPOINT": (
                    self.database_managed_identity_endpoint
                ),
                "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID": (
                    self.database_managed_identity_client_id
                ),
            }
            missing_database_identity = [
                name for name, value in required_database_identity.items() if not value
            ]
            if missing_database_identity:
                raise ValueError(
                    f"{label} database identity is missing: {', '.join(missing_database_identity)}"
                )
        if self.database_expected_revision != EXPECTED_DATABASE_REVISION:
            raise ValueError(f"{label} requires the release's exact database revision")
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
        if (
            self.invitation_secret == DEVELOPMENT_INVITATION_SECRET
            or len(self.invitation_secret.encode("utf-8")) < 32
            or self.invitation_secret == self.session_secret
        ):
            raise ValueError(f"{label} requires a distinct invitation secret of at least 32 bytes")
        if self.ai_provider != "openai" or self.embedding_provider != "openai":
            raise ValueError(f"{label} refuses mock AI and embedding providers")
        if self.storage_provider != "azure":
            raise ValueError(f"{label} requires the approved private Azure Blob storage provider")
        required_storage = {
            "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL": self.azure_storage_account_url,
            "OPENCANVAS_AZURE_MANAGED_IDENTITY_ENDPOINT": (self.azure_managed_identity_endpoint),
            "OPENCANVAS_AZURE_MANAGED_IDENTITY_HEADER": self.azure_managed_identity_header,
        }
        missing = [name for name, value in required_storage.items() if not value]
        if missing:
            raise ValueError(f"{label} object storage is missing: {', '.join(missing)}")
        containers = {
            self.azure_quarantine_container,
            self.azure_clean_container,
            self.azure_rejected_container,
            self.azure_retained_container,
        }
        if len(containers) != 4:
            raise ValueError(f"{label} requires distinct storage security-class containers")
        if self.object_ingestion_mode != "trusted":
            raise ValueError(f"{label} requires the trusted clean-object ingestion gate")
        if (
            self.scanner_result_bridge_mode != "private_pull"
            or self.azure_log_analytics_workspace_id is None
            or self.malware_scanner_identity != "azure-defender-for-storage"
            or self.malware_scanner_version != "defender-storage-dual-source-v1"
        ):
            raise ValueError(f"{label} requires the private dual-source scanner bridge")
        if (
            self.upload_capability_secret == DEVELOPMENT_UPLOAD_CAPABILITY_SECRET
            or self.scanner_result_secret == DEVELOPMENT_SCANNER_RESULT_SECRET
            or self.upload_capability_secret
            in {self.session_secret, self.invitation_secret, self.scanner_result_secret}
            or self.scanner_result_secret in {self.session_secret, self.invitation_secret}
        ):
            raise ValueError(
                f"{label} requires distinct upload-capability and scanner-result secrets"
            )
        if self.job_provider != "database":
            raise ValueError(f"{label} requires the database-backed worker provider")
        if self.shared_rate_limit_provider != "redis":
            raise ValueError(f"{label} requires the managed shared rate-limit provider")
        if self.shared_rate_limit_auth_mode != "entra":
            raise ValueError(f"{label} requires Microsoft Entra shared Redis authentication")
        if any(
            value is not None
            for value in (
                self.shared_rate_limit_acl_username_file,
                self.shared_rate_limit_acl_password_file,
                self.shared_rate_limit_tls_ca_file,
                self.shared_rate_limit_recovery_epoch,
            )
        ):
            raise ValueError(f"{label} refuses recovery-only shared Redis configuration")
        required_rate_limit = {
            "OPENCANVAS_SHARED_RATE_LIMIT_REDIS_URL": self.shared_rate_limit_redis_url,
            "OPENCANVAS_SHARED_RATE_LIMIT_REDIS_USERNAME": (self.shared_rate_limit_redis_username),
            "OPENCANVAS_SHARED_RATE_LIMIT_IDENTITY_ENDPOINT": (
                self.shared_rate_limit_identity_endpoint
            ),
        }
        missing_rate_limit = [name for name, value in required_rate_limit.items() if not value]
        if missing_rate_limit:
            raise ValueError(
                f"{label} shared rate limiter is missing: {', '.join(missing_rate_limit)}"
            )
        if (
            self.shared_rate_limit_hmac_secret == DEVELOPMENT_RATE_LIMIT_SECRET
            or self.shared_rate_limit_hmac_secret
            in {
                self.session_secret,
                self.invitation_secret,
                self.upload_capability_secret,
                self.scanner_result_secret,
            }
        ):
            raise ValueError(f"{label} requires a distinct shared rate-limit HMAC secret")
        if self.indexer_publication_mode not in {"disabled", "private_clean"}:
            raise ValueError(f"{label} permits only disabled or clean-gated Indexer publication")
        if not self.telemetry_enabled or self.telemetry_exporter != "http":
            raise ValueError(f"{label} requires explicit bounded HTTP telemetry export")
        if (
            self.telemetry_endpoint is None
            or urlparse(self.telemetry_endpoint).scheme != "https"
            or not self.telemetry_tls_verify
        ):
            raise ValueError(f"{label} requires verified HTTPS telemetry export")
        if self.telemetry_auth_secret_reference is None or not re.fullmatch(
            r"env://[A-Z][A-Z0-9_]{2,63}",
            self.telemetry_auth_secret_reference,
        ):
            raise ValueError(f"{label} requires an environment-backed telemetry secret reference")
        if (
            self.telemetry_pseudonymization_secret == DEVELOPMENT_TELEMETRY_SECRET
            or self.telemetry_pseudonymization_secret
            in {
                self.session_secret,
                self.invitation_secret,
                self.upload_capability_secret,
                self.scanner_result_secret,
                self.shared_rate_limit_hmac_secret,
            }
        ):
            raise ValueError(f"{label} requires a distinct telemetry pseudonymization secret")
        if self.telemetry_release == "local-development" or self.telemetry_deployment == "local":
            raise ValueError(f"{label} requires explicit release and deployment identities")
        if not self.observability_operator_user_ids:
            raise ValueError(f"{label} requires an operator health allowlist")

    @property
    def runtime_mode(self) -> AppMode:
        if self.app_mode is None:  # pragma: no cover - model validation always resolves it
            raise RuntimeError("APP_MODE was not resolved")
        return self.app_mode

    @property
    def database_url_value(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def recovery_rate_limit_acl_username(self) -> str:
        return self._read_required_secret_file(
            self.shared_rate_limit_acl_username_file,
            "ACL username",
        )

    @property
    def recovery_rate_limit_acl_password(self) -> str:
        return self._read_required_secret_file(
            self.shared_rate_limit_acl_password_file,
            "ACL password",
        )

    @property
    def secure_cookies(self) -> bool:
        return self.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}

    @property
    def openai_configured(self) -> bool:
        return self.ai_provider == "openai" and self.openai_api_key is not None

    @property
    def telemetry_authentication(self) -> SecretStr | None:
        reference = self.telemetry_auth_secret_reference
        if reference is None or not reference.startswith("env://"):
            return None
        value = os.getenv(reference.removeprefix("env://"))
        return SecretStr(value) if value else None

    @property
    def effective_ai_provider(self) -> Literal["mock", "openai"]:
        return self.ai_provider

    @property
    def effective_embedding_provider(self) -> Literal["mock", "openai"]:
        return self.embedding_provider

    def require_database_role(self, expected: DatabaseRole) -> None:
        if (
            self.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}
            and self.database_role is not expected
        ):
            raise RuntimeError(
                f"{expected.value} process requires its dedicated database credential role"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "DEMO_DATABASE_PATH",
    "DEMO_DATABASE_URL",
    "DEMO_DOCUMENT_STORAGE_ROOT",
    "DEMO_RUNTIME_ROOT",
    "DEVELOPMENT_INVITATION_SECRET",
    "DEVELOPMENT_RATE_LIMIT_SECRET",
    "DEVELOPMENT_SESSION_SECRET",
    "DEVELOPMENT_TELEMETRY_SECRET",
    "EXPECTED_DATABASE_REVISION",
    "PROJECT_ROOT",
    "RUNTIME_ROOT",
    "TEST_RUNTIME_ROOT",
    "AppMode",
    "DatabaseRole",
    "Settings",
    "get_settings",
]
