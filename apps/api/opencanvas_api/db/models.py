from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


SYSTEM_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SYSTEM_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(email) <= 320", name="ck_users_email_length"),
        Index("ix_users_email_normalized", "email_normalized", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_expires", "user_id", "expires_at"),
        Index("ix_user_sessions_token_hash", "token_hash", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))


class PasswordResetToken(TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_token_hash", "token_hash", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TraceEvent(Base):
    """Immutable, subsystem-neutral execution and provenance event."""

    __tablename__ = "trace_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'system', 'service')",
            name="ck_trace_events_actor_type",
        ),
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name="ck_trace_events_status",
        ),
        CheckConstraint(
            "parent_trace_id IS NULL OR parent_trace_id <> trace_id",
            name="ck_trace_events_not_own_parent",
        ),
        Index("ix_trace_events_trace_time", "trace_id", "occurred_at", "event_id"),
        Index("ix_trace_events_workspace_time", "workspace_id", "occurred_at"),
        Index("ix_trace_events_object_time", "object_id", "occurred_at"),
        Index("ix_trace_events_type_time", "event_type", "occurred_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    parent_trace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(255))
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Trace identifiers are immutable audit references, not cascading ownership
    # links. They may be written before the referenced workspace transaction commits.
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    object_type: Mapped[str | None] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_payload: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    error_payload: Mapped[dict[str, object] | None] = mapped_column("error", JSON)


class Canvas(TimestampMixin, Base):
    __tablename__ = "canvases"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_canvases_id_workspace"),
        CheckConstraint("revision >= 0", name="ck_canvases_revision_nonnegative"),
        CheckConstraint("viewport_zoom > 0", name="ck_canvases_viewport_zoom_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        default=lambda: SYSTEM_WORKSPACE_ID,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    viewport_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    viewport_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    viewport_zoom: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CanvasNode(TimestampMixin, Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("id", "canvas_id", name="uq_nodes_id_canvas"),
        CheckConstraint("type IN ('note', 'ai_response', 'document')", name="ck_nodes_type"),
        CheckConstraint("width >= 220 AND width <= 1600", name="ck_nodes_width"),
        CheckConstraint("height >= 140 AND height <= 1200", name="ck_nodes_height"),
        CheckConstraint("revision >= 0", name="ck_nodes_revision_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position_x: Mapped[float] = mapped_column(Float, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False, default=300.0)
    height: Mapped[float] = mapped_column(Float, nullable=False, default=220.0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Edge(TimestampMixin, Base):
    __tablename__ = "edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_node_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_edges_source_same_canvas",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_node_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_edges_target_same_canvas",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "canvas_id", "source_node_id", "target_node_id", "kind", name="uq_edges_direction_kind"
        ),
        CheckConstraint("source_node_id <> target_node_id", name="ck_edges_not_self"),
        CheckConstraint("kind IN ('default', 'generated_from', 'cites')", name="ck_edges_kind"),
        CheckConstraint("revision >= 0", name="ck_edges_revision_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="default")
    label: Mapped[str | None] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AIRequest(TimestampMixin, Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')", name="ck_ai_requests_status"
        ),
        CheckConstraint("provider IN ('mock', 'openai')", name="ck_ai_requests_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, default=uuid.uuid4, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        default=lambda: SYSTEM_USER_ID,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        default=lambda: SYSTEM_WORKSPACE_ID,
    )
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    selected_node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    context_snapshot: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    model_configuration: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    retrieval_configuration: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="canvas-v1")
    provider_configuration_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unknown"
    )
    execution_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="current_context"
    )
    parent_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="SET NULL"), index=True
    )
    rerun_type: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    safe_error_category: Mapped[str | None] = mapped_column(String(64))
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)


class AIResponse(TimestampMixin, Base):
    __tablename__ = "ai_responses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("id", "canvas_id", name="uq_documents_id_canvas"),
        CheckConstraint(
            "status IN ('uploaded', 'queued', 'processing', 'ready', 'failed', "
            "'retryable_failure', 'permanent_failure', 'deleting', 'deleted')",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "processing_stage IN "
            "('uploading', 'queued', 'processing', 'extracting', 'chunking', 'embedding', "
            "'indexing', 'ready', 'retrying', 'failed', 'deleting', 'deleted')",
            name="ck_documents_processing_stage",
        ),
        CheckConstraint("file_size_bytes >= 0", name="ck_documents_file_size_nonnegative"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_documents_page_count"),
        CheckConstraint("chunk_count >= 0", name="ck_documents_chunk_count_nonnegative"),
        CheckConstraint("version_count > 0", name="ck_documents_version_count_positive"),
        Index("ix_documents_canvas_hash", "canvas_id", "content_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing")
    processing_stage: Mapped[str] = mapped_column(String(24), nullable=False, default="uploading")
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    safe_error_category: Mapped[str | None] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_number"),
        CheckConstraint("version > 0", name="ck_document_versions_number_positive"),
        CheckConstraint("file_size_bytes >= 0", name="ck_document_versions_size_nonnegative"),
        Index("ix_document_versions_hash", "document_id", "content_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentFile(TimestampMixin, Base):
    __tablename__ = "document_files"
    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="ck_document_files_byte_size_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)


class CanvasDocumentNode(TimestampMixin, Base):
    __tablename__ = "canvas_document_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["node_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_canvas_document_nodes_node_same_canvas",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "canvas_id"],
            ["documents.id", "documents.canvas_id"],
            name="fk_canvas_document_nodes_document_same_canvas",
            ondelete="CASCADE",
        ),
    )

    node_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("id", "document_id", name="uq_document_chunks_id_document"),
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_index"),
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonnegative"),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0", name="ck_document_chunks_page_number"
        ),
        CheckConstraint("char_start >= 0", name="ck_document_chunks_char_start_nonnegative"),
        CheckConstraint("char_end > char_start", name="ck_document_chunks_char_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(500))
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)


class DocumentEmbedding(TimestampMixin, Base):
    __tablename__ = "document_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "document_id"],
            ["document_chunks.id", "document_chunks.document_id"],
            name="fk_document_embeddings_chunk_document",
            ondelete="CASCADE",
        ),
        CheckConstraint("dimensions = 1536", name="ck_document_embeddings_dimensions"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(1536).with_variant(JSON(), "sqlite"), nullable=False
    )


class DocumentProcessingJob(TimestampMixin, Base):
    __tablename__ = "document_processing_jobs"
    __table_args__ = (
        UniqueConstraint("document_id", "attempt", name="uq_document_processing_jobs_attempt"),
        CheckConstraint("attempt > 0", name="ck_document_processing_jobs_attempt_positive"),
        CheckConstraint(
            "status IN ('queued', 'uploading', 'processing', 'extracting', 'chunking', "
            "'embedding', 'indexing', 'ready', 'retrying', 'retryable_failure', "
            "'permanent_failure', 'cancelled', 'failed')",
            name="ck_document_processing_jobs_status",
        ),
        Index("ix_document_jobs_claim", "status", "available_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        default=lambda: SYSTEM_USER_ID,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        default=lambda: SYSTEM_WORKSPACE_ID,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True, default=lambda: uuid.uuid4().hex
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    safe_error_category: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(120))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineManifest(Base):
    __tablename__ = "pipeline_manifests"
    __table_args__ = (
        UniqueConstraint("manifest_id", "workspace_id", name="uq_pipeline_manifest_scope"),
        UniqueConstraint("workspace_id", "manifest_digest", name="uq_pipeline_manifest_digest"),
        CheckConstraint("length(manifest_digest) = 64", name="ck_pipeline_manifest_digest"),
        CheckConstraint("dimensions > 0", name="ck_pipeline_manifest_dimensions"),
    )

    manifest_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_build_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_version: Mapped[str] = mapped_column(String(64), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_configuration_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    indexer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    index_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionRequest(Base):
    __tablename__ = "ingestion_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_ingestion_request_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["pipeline_manifest_id", "workspace_id"],
            ["pipeline_manifests.manifest_id", "pipeline_manifests.workspace_id"],
            name="fk_ingestion_request_manifest",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("request_id", "workspace_id", name="uq_ingestion_request_scope"),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "idempotency_key",
            name="uq_ingestion_request_idempotency",
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_ingestion_request_digest"),
        CheckConstraint("length(source_sha256) = 64", name="ck_ingestion_request_source_digest"),
        CheckConstraint(
            "operation IN ('index', 'reindex')",
            name="ck_ingestion_request_operation",
        ),
        CheckConstraint("authority_generation >= 0", name="ck_ingestion_authority_generation"),
        CheckConstraint("cancel_generation >= 0", name="ck_ingestion_cancel_generation"),
        Index(
            "ix_ingestion_request_document",
            "workspace_id",
            "canvas_id",
            "document_id",
            "document_version",
            "created_at",
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    pipeline_manifest_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionRequestTransition(Base):
    __tablename__ = "ingestion_request_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_ingestion_transition_request",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("request_id", "sequence", name="uq_ingestion_request_transition_sequence"),
        CheckConstraint("sequence >= 0", name="ck_ingestion_transition_sequence"),
        CheckConstraint(
            "current_state IN "
            "('requested', 'queued', 'parsing', 'normalizing', 'chunking', 'indexing', "
            "'completed', 'published', 'failed', 'canceled', 'superseded')",
            name="ck_ingestion_transition_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('requested', 'queued', 'parsing', 'normalizing', 'chunking', 'indexing', "
            "'completed', 'published', 'failed', 'canceled', 'superseded')",
            name="ck_ingestion_transition_previous_state",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(24))
    current_state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormalizedArtifact(Base):
    __tablename__ = "normalized_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_normalized_artifact_request",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("request_id", name="uq_normalized_artifact_request"),
        Index(
            "ix_normalized_artifact_scoped_digest",
            "workspace_id",
            "normalized_digest",
            "pipeline_manifest_id",
        ),
        CheckConstraint("length(normalized_digest) = 64", name="ck_normalized_artifact_digest"),
        CheckConstraint("length(metadata_digest) = 64", name="ck_normalized_metadata_digest"),
        CheckConstraint(
            "length(near_duplicate_fingerprint) = 64",
            name="ck_normalized_near_duplicate_digest",
        ),
    )

    artifact_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pipeline_manifest_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_manifests.manifest_id", ondelete="RESTRICT"), nullable=False
    )
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    metadata_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    near_duplicate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndexCompatibilityProjection(Base):
    __tablename__ = "index_compatibility_projections"
    __table_args__ = (
        UniqueConstraint(
            "projection_id", "workspace_id", name="uq_index_compatibility_projection_scope"
        ),
        UniqueConstraint(
            "document_id",
            "document_version",
            name="uq_index_compatibility_document_version",
        ),
        CheckConstraint(
            "provenance_state = 'unverified_legacy'",
            name="ck_index_compatibility_provenance_state",
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_index_compatibility_source_digest"),
        CheckConstraint("chunk_count >= 0", name="ck_index_compatibility_chunk_count"),
    )

    projection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified_legacy"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndexRevision(Base):
    __tablename__ = "index_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_index_revision_request",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("revision_id", "workspace_id", name="uq_index_revision_scope"),
        UniqueConstraint("request_id", name="uq_index_revision_request"),
        CheckConstraint("revision_kind = 'native'", name="ck_index_revision_kind"),
        CheckConstraint("status = 'completed'", name="ck_index_revision_status"),
        CheckConstraint(
            "deduplication_kind IN ('none', 'exact_bytes', 'normalized_content')",
            name="ck_index_revision_deduplication_kind",
        ),
        CheckConstraint(
            "(deduplication_kind = 'none' AND deduplicated_from_revision_id IS NULL) "
            "OR (deduplication_kind IN ('exact_bytes', 'normalized_content') "
            "AND deduplicated_from_revision_id IS NOT NULL)",
            name="ck_index_revision_deduplication_source",
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_index_revision_source_digest"),
        CheckConstraint(
            "length(normalized_digest) = 64", name="ck_index_revision_normalized_digest"
        ),
        CheckConstraint(
            "length(chunk_manifest_digest) = 64", name="ck_index_revision_chunk_digest"
        ),
        CheckConstraint(
            "length(vector_manifest_digest) = 64", name="ck_index_revision_vector_digest"
        ),
        CheckConstraint("length(output_digest) = 64", name="ck_index_revision_output_digest"),
        Index(
            "ix_index_revision_document",
            "workspace_id",
            "document_id",
            "document_version",
            "created_at",
        ),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_manifest_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_manifests.manifest_id", ondelete="RESTRICT"), nullable=False
    )
    revision_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="native")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    deduplication_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    deduplicated_from_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("index_revisions.revision_id", ondelete="RESTRICT")
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    output_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndexRevisionChunk(Base):
    __tablename__ = "index_revision_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_index_chunk_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("chunk_id", "revision_id", name="uq_index_chunk_revision"),
        UniqueConstraint("revision_id", "chunk_index", name="uq_index_chunk_order"),
        UniqueConstraint("revision_id", "stable_chunk_id", name="uq_index_chunk_stable_identity"),
        CheckConstraint("chunk_index >= 0", name="ck_index_chunk_index"),
        CheckConstraint("char_start >= 0", name="ck_index_chunk_start"),
        CheckConstraint("char_end > char_start", name="ck_index_chunk_range"),
        CheckConstraint("length(content_digest) = 64", name="ck_index_chunk_content_digest"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    stable_chunk_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(500))
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VectorMaterialization(Base):
    __tablename__ = "vector_materializations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_vector_materialization_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "revision_id"],
            ["index_revision_chunks.chunk_id", "index_revision_chunks.revision_id"],
            name="fk_vector_materialization_chunk",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("revision_id", "chunk_id", name="uq_vector_materialization_chunk"),
        CheckConstraint("dimensions = 1536", name="ck_vector_materialization_dimensions"),
        CheckConstraint("length(artifact_digest) = 64", name="ck_vector_materialization_digest"),
    )

    materialization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reused_from_materialization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vector_materializations.materialization_id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(1536).with_variant(JSON(), "sqlite"), nullable=False
    )
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndexPublication(Base):
    __tablename__ = "index_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_index_publication_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["membership_id", "actor_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_index_publication_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("publication_id", "workspace_id", name="uq_index_publication_scope"),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "generation",
            name="uq_index_publication_generation",
        ),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "revision_id",
            name="uq_index_publication_revision",
        ),
        CheckConstraint("generation > 0", name="ck_index_publication_generation"),
        CheckConstraint("authority_generation >= 0", name="ck_index_publication_authority"),
        CheckConstraint("cancel_generation >= 0", name="ck_index_publication_cancel"),
    )

    publication_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    cancel_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RetrievalHead(TimestampMixin, Base):
    __tablename__ = "retrieval_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_retrieval_head_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["index_publications.publication_id", "index_publications.workspace_id"],
            name="fk_retrieval_head_publication",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["compatibility_projection_id", "workspace_id"],
            [
                "index_compatibility_projections.projection_id",
                "index_compatibility_projections.workspace_id",
            ],
            name="fk_retrieval_head_compatibility",
            ondelete="RESTRICT",
        ),
        CheckConstraint("generation > 0", name="ck_retrieval_head_generation"),
        CheckConstraint(
            "(activation_kind = 'native' AND revision_id IS NOT NULL "
            "AND publication_id IS NOT NULL AND compatibility_projection_id IS NULL) "
            "OR (activation_kind = 'compatibility' AND revision_id IS NULL "
            "AND publication_id IS NULL AND compatibility_projection_id IS NOT NULL)",
            name="ck_retrieval_head_activation",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    activation_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    revision_id: Mapped[uuid.UUID | None] = mapped_column()
    publication_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    compatibility_projection_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)


class IndexerAuditEvent(Base):
    __tablename__ = "indexer_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_indexer_audit_request",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "outcome IN ('allowed', 'denied', 'succeeded', 'failed')",
            name="ck_indexer_audit_outcome",
        ),
    )

    audit_event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    metadata_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IndexerFailure(Base):
    __tablename__ = "indexer_failures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_indexer_failure_request",
            ondelete="RESTRICT",
        ),
    )

    failure_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    safe_failure_code: Mapped[str] = mapped_column(String(64), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Citation(TimestampMixin, Base):
    __tablename__ = "citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "document_id"],
            ["document_chunks.id", "document_chunks.document_id"],
            name="fk_citations_chunk_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint("ai_response_id", "identifier", name="uq_citations_response_identifier"),
        CheckConstraint("ordinal > 0", name="ck_citations_ordinal_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ai_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    identifier: Mapped[str] = mapped_column(String(48), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class AIResponseSource(TimestampMixin, Base):
    __tablename__ = "ai_response_sources"
    __table_args__ = (
        UniqueConstraint(
            "ai_response_id", "document_id", name="uq_ai_response_sources_response_document"
        ),
        CheckConstraint(
            "max_relevance_score >= -1 AND max_relevance_score <= 1",
            name="ck_ai_response_sources_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ai_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), index=True
    )
    max_relevance_score: Mapped[float] = mapped_column(Float, nullable=False)


class AIExecutionNode(TimestampMixin, Base):
    __tablename__ = "ai_execution_nodes"
    __table_args__ = (
        UniqueConstraint("request_id", "selected_order", name="uq_ai_execution_nodes_order"),
        CheckConstraint("selected_order >= 0", name="ck_ai_execution_nodes_order_nonnegative"),
        CheckConstraint("node_revision >= 0", name="ck_ai_execution_nodes_revision_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), index=True
    )
    node_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(index=True)
    selected_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    node_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(index=True)


class AIExecutionChunk(TimestampMixin, Base):
    __tablename__ = "ai_execution_chunks"
    __table_args__ = (
        UniqueConstraint("request_id", "rank", name="uq_ai_execution_chunks_rank"),
        CheckConstraint("rank > 0", name="ck_ai_execution_chunks_rank_positive"),
        CheckConstraint("score >= -1 AND score <= 1", name="ck_ai_execution_chunks_score"),
        CheckConstraint(
            "page_number_snapshot IS NULL OR page_number_snapshot > 0",
            name="ck_ai_execution_chunks_page_number",
        ),
        CheckConstraint(
            "char_start_snapshot >= 0", name="ck_ai_execution_chunks_char_start_nonnegative"
        ),
        CheckConstraint(
            "char_end_snapshot > char_start_snapshot",
            name="ck_ai_execution_chunks_char_range",
        ),
        CheckConstraint(
            "chunk_index_snapshot >= 0",
            name="ck_ai_execution_chunks_index_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True
    )
    chunk_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(index=True)
    document_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_index_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    included_in_context: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(120))
    source_id_snapshot: Mapped[str] = mapped_column(String(48), nullable=False)
    document_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    page_number_snapshot: Mapped[int | None] = mapped_column(Integer)
    heading_snapshot: Mapped[str | None] = mapped_column(String(500))
    char_start_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)


class AIExecutionCitation(TimestampMixin, Base):
    __tablename__ = "ai_execution_citations"
    __table_args__ = (
        UniqueConstraint("request_id", "ordinal", name="uq_ai_execution_citations_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_ai_execution_citations_ordinal_positive"),
        CheckConstraint(
            "page_number_snapshot IS NULL OR page_number_snapshot > 0",
            name="ck_ai_execution_citations_page_number",
        ),
        CheckConstraint(
            "char_start_snapshot >= 0",
            name="ck_ai_execution_citations_char_start_nonnegative",
        ),
        CheckConstraint(
            "char_end_snapshot > char_start_snapshot",
            name="ck_ai_execution_citations_char_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_response_id_snapshot: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id_snapshot: Mapped[str] = mapped_column(String(48), nullable=False)
    claim_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    document_id_snapshot: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_id_snapshot: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number_snapshot: Mapped[int | None] = mapped_column(Integer)
    heading_snapshot: Mapped[str | None] = mapped_column(String(500))
    char_start_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)


class AIExecutionSource(TimestampMixin, Base):
    __tablename__ = "ai_execution_sources"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "document_id_snapshot",
            "document_node_id_snapshot",
            name="uq_ai_execution_sources_relation",
        ),
        CheckConstraint(
            "max_relevance_score >= -1 AND max_relevance_score <= 1",
            name="ck_ai_execution_sources_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    response_node_id_snapshot: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id_snapshot: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_node_id_snapshot: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    max_relevance_score: Mapped[float] = mapped_column(Float, nullable=False)


class AIClaim(TimestampMixin, Base):
    __tablename__ = "ai_claims"
    __table_args__ = (
        CheckConstraint(
            "evidence_status IN ('supported', 'inference', 'conflict', 'unsupported', "
            "'insufficient_evidence', 'excluded_from_context')",
            name="ck_ai_claims_evidence_status",
        ),
        Index("ix_ai_claims_request_ordinal", "request_id", "ordinal", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_response_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )


class UsageRecord(TimestampMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_user_time", "user_id", "created_at"),
        Index("ix_usage_records_workspace_time", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metadata_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class ApplicationError(TimestampMixin, Base):
    __tablename__ = "application_errors"
    __table_args__ = (Index("ix_application_errors_correlation", "correlation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(500), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class WorkerHeartbeat(TimestampMixin, Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class DataExportRequest(TimestampMixin, Base):
    __tablename__ = "data_export_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested")
    storage_key: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_workspaces_version_positive"),
        CheckConstraint(
            "lifecycle_state IN ('created', 'active', 'archived', 'deleted')",
            name="ck_workspaces_lifecycle_state",
        ),
        Index("ix_workspaces_owner_id", "owner_id"),
        Index("ix_workspaces_lifecycle_state", "lifecycle_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: SYSTEM_USER_ID,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    metadata_payload: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    settings_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legacy_canvas_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("canvases.id", ondelete="SET NULL"), unique=True
    )


class WorkspaceMembership(Base):
    """Immutable admission identity; current state and role come from transitions."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "user_id",
            "workspace_id",
            name="uq_workspace_memberships_scope",
        ),
        UniqueConstraint(
            "accepted_invitation_id",
            name="uq_workspace_memberships_accepted_invitation",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_workspace_memberships_policy",
        ),
        Index(
            "ix_workspace_memberships_user_workspace",
            "user_id",
            "workspace_id",
            "created_at",
        ),
        Index(
            "ix_workspace_memberships_workspace_time",
            "workspace_id",
            "created_at",
            "membership_id",
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    accepted_invitation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceMembershipTransition(Base):
    """Append-only membership lifecycle and one-role evidence."""

    __tablename__ = "workspace_membership_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_workspace_membership_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "membership_id",
            "sequence",
            name="uq_workspace_membership_transition_sequence",
        ),
        CheckConstraint(
            "current_state IN ('active', 'suspended', 'removed')",
            name="ck_workspace_membership_transition_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('active', 'suspended', 'removed')",
            name="ck_workspace_membership_transition_previous_state",
        ),
        CheckConstraint(
            '"current_role" IN '
            "('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_workspace_membership_transition_role",
        ),
        CheckConstraint(
            "previous_role IS NULL OR previous_role IN "
            "('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_workspace_membership_transition_previous_role",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_workspace_membership_transition_policy",
        ),
        CheckConstraint("sequence >= 0", name="ck_workspace_membership_transition_sequence"),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_workspace_membership_transition_generation",
        ),
        Index(
            "ix_workspace_membership_transition_current",
            "membership_id",
            "sequence",
        ),
        Index(
            "ix_workspace_membership_transition_workspace",
            "workspace_id",
            "recorded_at",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(16))
    current_state: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_role: Mapped[str | None] = mapped_column(String(24))
    current_role: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceInvitation(Base):
    """Immutable invitation identity with no recoverable bearer credential."""

    __tablename__ = "workspace_invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["inviter_membership_id", "inviter_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_workspace_invitation_inviter_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "invitation_id",
            "workspace_id",
            name="uq_workspace_invitations_scope",
        ),
        CheckConstraint(
            "intended_role IN ('administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_workspace_invitations_role",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_workspace_invitations_policy",
        ),
        CheckConstraint(
            "length(recipient_digest) = 64 AND length(request_digest) = 64",
            name="ck_workspace_invitations_digests",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_workspace_invitations_expiry_order",
        ),
        Index(
            "ix_workspace_invitations_workspace_recipient",
            "workspace_id",
            "recipient_digest",
            "created_at",
        ),
        Index(
            "ix_workspace_invitations_workspace_expiry",
            "workspace_id",
            "expires_at",
        ),
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recipient_email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    intended_role: Mapped[str] = mapped_column(String(24), nullable=False)
    inviter_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    inviter_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceInvitationTransition(Base):
    """Append-only invitation lifecycle evidence."""

    __tablename__ = "workspace_invitation_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "workspace_id"],
            ["workspace_invitations.invitation_id", "workspace_invitations.workspace_id"],
            name="fk_workspace_invitation_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "invitation_id",
            "sequence",
            name="uq_workspace_invitation_transition_sequence",
        ),
        UniqueConstraint(
            "invitation_id",
            "current_state",
            name="uq_workspace_invitation_terminal_once",
        ),
        CheckConstraint(
            "current_state IN ('pending', 'accepted', 'declined', 'expired', 'revoked')",
            name="ck_workspace_invitation_transition_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('pending', 'accepted', 'declined', 'expired', 'revoked')",
            name="ck_workspace_invitation_transition_previous_state",
        ),
        CheckConstraint("sequence >= 0", name="ck_workspace_invitation_transition_sequence"),
        Index(
            "ix_workspace_invitation_transition_current",
            "invitation_id",
            "sequence",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(16))
    current_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    result_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace_memberships.membership_id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceInvitationSecretVersion(Base):
    """Append-only nonrecoverable invitation credential version."""

    __tablename__ = "workspace_invitation_secret_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "workspace_id"],
            ["workspace_invitations.invitation_id", "workspace_invitations.workspace_id"],
            name="fk_workspace_invitation_secret_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "invitation_id",
            "sequence",
            name="uq_workspace_invitation_secret_sequence",
        ),
        UniqueConstraint("token_hash", name="uq_workspace_invitation_secret_hash"),
        CheckConstraint("sequence >= 0", name="ck_workspace_invitation_secret_sequence"),
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_workspace_invitation_secret_hash_length",
        ),
        Index(
            "ix_workspace_invitation_secret_current",
            "invitation_id",
            "sequence",
        ),
    )

    secret_version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceInvitationDeliveryAttempt(Base):
    """Append-only safe delivery outcome without recipient or secret material."""

    __tablename__ = "workspace_invitation_delivery_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "workspace_id"],
            ["workspace_invitations.invitation_id", "workspace_invitations.workspace_id"],
            name="fk_workspace_invitation_delivery_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "invitation_id",
            "sequence",
            name="uq_workspace_invitation_delivery_sequence",
        ),
        CheckConstraint(
            "channel IN ('development_token', 'smtp')",
            name="ck_workspace_invitation_delivery_channel",
        ),
        CheckConstraint(
            "outcome IN ('delivered', 'failed')",
            name="ck_workspace_invitation_delivery_outcome",
        ),
        CheckConstraint("sequence >= 0", name="ck_workspace_invitation_delivery_sequence"),
        Index(
            "ix_workspace_invitation_delivery_recent",
            "invitation_id",
            "recorded_at",
        ),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    secret_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationRequestIdentity(Base):
    """Append-only scoped idempotency result."""

    __tablename__ = "collaboration_request_identities"
    __table_args__ = (
        UniqueConstraint(
            "actor_user_id",
            "workspace_id",
            "operation",
            "idempotency_key",
            name="uq_collaboration_request_scope",
        ),
        CheckConstraint(
            "operation IN ('invitation.create', 'invitation.resend', "
            "'invitation.accept', 'invitation.decline', 'invitation.revoke', "
            "'membership.role.change', 'membership.suspend', 'membership.restore', "
            "'membership.remove', 'approval_authority.assign', "
            "'approval_authority.replace', 'approval_authority.revoke', "
            "'share.create', 'share.revoke', 'share.bulk_revoke', "
            "'resource.visibility.change', 'ownership_transfer.request', "
            "'ownership_transfer.accept', 'ownership_transfer.reject', "
            "'ownership_transfer.cancel', 'comment.create', 'comment.reply', "
            "'comment.revise', 'comment.tombstone', 'comment.thread.resolve', "
            "'comment.thread.reopen')",
            name="ck_collaboration_request_operation",
        ),
        CheckConstraint(
            "result_kind IN ('workspace_invitation', 'workspace_membership', "
            "'approval_authority_assignment', 'resource_share_request', "
            "'collaboration_resource', 'ownership_transfer', 'authority_fence', "
            "'comment_thread', 'comment', 'comment_revision', "
            "'comment_transition', 'comment_thread_transition')",
            name="ck_collaboration_request_result_kind",
        ),
        CheckConstraint(
            "length(request_digest) = 64",
            name="ck_collaboration_request_digest",
        ),
        Index(
            "ix_collaboration_request_created",
            "workspace_id",
            "created_at",
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    result_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceAuthorityVersion(Base):
    """Mutable server-owned current generation for collaboration authority."""

    __tablename__ = "workspace_authority_versions"
    __table_args__ = (
        CheckConstraint(
            "authority_generation > 0",
            name="ck_workspace_authority_generation",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationApprovalAuthorityAssignment(Base):
    """Immutable exact reviewer-eligibility assignment."""

    __tablename__ = "collaboration_approval_authority_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "reviewer_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_approval_assignment_reviewer_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["issuer_membership_id", "issuer_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_approval_assignment_issuer_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "assignment_id",
            "membership_id",
            "reviewer_user_id",
            "workspace_id",
            name="uq_collaboration_approval_assignment_scope",
        ),
        CheckConstraint(
            "capability IN ('workspace.metadata.read', 'canvas.snapshot.read', "
            "'context.selected.read', 'document.version.read', 'trace.scoped.read', "
            "'retrieval.selected.search', 'draft.note.create', 'draft.answer.create', "
            "'canvas.note.create', 'canvas.note.update', 'canvas.note.create.rollback', "
            "'canvas.note.update.rollback', 'knowledge_graph.relationship.write', "
            "'workflow.step.execute', 'evidence.bundle.create', 'execution.cancel')",
            name="ck_collaboration_approval_assignment_capability",
        ),
        CheckConstraint(
            "resource_kind IN ('workspace', 'canvas', 'node', 'document_version', "
            "'chunk', 'trace', 'canonical_relationship', 'canonical_object')",
            name="ck_collaboration_approval_assignment_resource_kind",
        ),
        CheckConstraint(
            "maximum_risk_class IN ('r0_observation', 'r1_draft', "
            "'r2_transient_action', 'r3_durable_write')",
            name="ck_collaboration_approval_assignment_risk",
        ),
        CheckConstraint(
            "conflict_policy = 'deny_self_review'",
            name="ck_collaboration_approval_assignment_conflict",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_approval_assignment_policy",
        ),
        CheckConstraint(
            "expires_at > valid_from",
            name="ck_collaboration_approval_assignment_time_order",
        ),
        CheckConstraint(
            "length(scope_digest) = 64",
            name="ck_collaboration_approval_assignment_digest",
        ),
        Index(
            "ix_collaboration_approval_assignment_reviewer",
            "workspace_id",
            "membership_id",
            "valid_from",
        ),
        Index(
            "ix_collaboration_approval_assignment_scope",
            "workspace_id",
            "capability",
            "resource_kind",
            "resource_id",
        ),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    issuer_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    issuer_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    maximum_risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conflict_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "collaboration_approval_authority_assignments.assignment_id",
            ondelete="RESTRICT",
        )
    )
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationApprovalAuthorityTransition(Base):
    """Append-only approval-authority lifecycle evidence."""

    __tablename__ = "collaboration_approval_authority_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_id", "membership_id", "reviewer_user_id", "workspace_id"],
            [
                "collaboration_approval_authority_assignments.assignment_id",
                "collaboration_approval_authority_assignments.membership_id",
                "collaboration_approval_authority_assignments.reviewer_user_id",
                "collaboration_approval_authority_assignments.workspace_id",
            ],
            name="fk_collaboration_approval_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "assignment_id",
            "sequence",
            name="uq_collaboration_approval_transition_sequence",
        ),
        CheckConstraint(
            "current_state IN ('active', 'revoked', 'superseded')",
            name="ck_collaboration_approval_transition_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('active', 'revoked', 'superseded')",
            name="ck_collaboration_approval_transition_previous_state",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_approval_transition_generation",
        ),
        Index(
            "ix_collaboration_approval_transition_current",
            "assignment_id",
            "sequence",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(16))
    current_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationReviewerEligibilityEvidence(Base):
    """Append-only proof of eligibility for one existing Milestone 4 approval."""

    __tablename__ = "collaboration_reviewer_eligibility_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["approval_id", "execution_id", "requester_user_id", "workspace_id"],
            [
                "controlled_agent_approvals.approval_id",
                "controlled_agent_approvals.execution_id",
                "controlled_agent_approvals.user_id",
                "controlled_agent_approvals.workspace_id",
            ],
            name="fk_collaboration_reviewer_evidence_approval_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assignment_id", "deciding_membership_id", "deciding_user_id", "workspace_id"],
            [
                "collaboration_approval_authority_assignments.assignment_id",
                "collaboration_approval_authority_assignments.membership_id",
                "collaboration_approval_authority_assignments.reviewer_user_id",
                "collaboration_approval_authority_assignments.workspace_id",
            ],
            name="fk_collaboration_reviewer_evidence_assignment_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("approval_id", name="uq_collaboration_reviewer_evidence_approval"),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_reviewer_evidence_policy",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_reviewer_evidence_generation",
        ),
        CheckConstraint(
            "length(scope_digest) = 64",
            name="ck_collaboration_reviewer_evidence_digest",
        ),
        Index(
            "ix_collaboration_reviewer_evidence_reviewer",
            "workspace_id",
            "deciding_membership_id",
            "recorded_at",
        ),
    )

    eligibility_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    requester_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    deciding_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    deciding_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    assignment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision_session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationAuditEvent(Base):
    """Immutable bounded collaboration audit fact."""

    __tablename__ = "collaboration_audit_events"
    __table_args__ = (
        CheckConstraint(
            "subject_kind IN ('workspace_membership', 'workspace_invitation', "
            "'approval_authority_assignment', 'collaboration_resource', "
            "'resource_share', 'ownership_transfer', 'authority_fence', "
            "'comment_thread', 'comment', 'comment_revision', "
            "'comment_transition')",
            name="ck_collaboration_audit_subject_kind",
        ),
        CheckConstraint(
            "outcome IN ('succeeded', 'failed')",
            name="ck_collaboration_audit_outcome",
        ),
        CheckConstraint(
            "length(metadata_digest) = 64",
            name="ck_collaboration_audit_metadata_digest",
        ),
        Index(
            "ix_collaboration_audit_workspace_time",
            "workspace_id",
            "recorded_at",
            "audit_event_id",
        ),
        Index("ix_collaboration_audit_trace", "trace_id"),
    )

    audit_event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationResource(Base):
    """Typed shareable resource identity with real target foreign keys."""

    __tablename__ = "collaboration_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_collaboration_resource_canvas_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["canonical_object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_collaboration_resource_object_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_definition_id", "target_user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_definitions.definition_id",
                "controlled_workflow_definitions.user_id",
                "controlled_workflow_definitions.workspace_id",
                "controlled_workflow_definitions.canvas_id",
            ],
            name="fk_collaboration_resource_workflow_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_id", "target_user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_identities.agent_id",
                "bounded_agent_identities.user_id",
                "bounded_agent_identities.workspace_id",
                "bounded_agent_identities.canvas_id",
            ],
            name="fk_collaboration_resource_agent_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "resource_kind IN ('canvas', 'canonical_object', 'workflow', 'agent')",
            name="ck_collaboration_resource_kind",
        ),
        CheckConstraint(
            "(resource_kind = 'canvas' AND resource_id = canvas_id "
            "AND canonical_object_id IS NULL AND workflow_definition_id IS NULL "
            "AND agent_id IS NULL AND target_user_id IS NULL) OR "
            "(resource_kind = 'canonical_object' AND resource_id = canonical_object_id "
            "AND workflow_definition_id IS NULL AND agent_id IS NULL "
            "AND target_user_id IS NULL) OR "
            "(resource_kind = 'workflow' AND resource_id = workflow_definition_id "
            "AND canonical_object_id IS NULL AND agent_id IS NULL "
            "AND target_user_id IS NOT NULL AND canvas_id IS NOT NULL) OR "
            "(resource_kind = 'agent' AND resource_id = agent_id "
            "AND canonical_object_id IS NULL AND workflow_definition_id IS NULL "
            "AND target_user_id IS NOT NULL AND canvas_id IS NOT NULL)",
            name="ck_collaboration_resource_target_shape",
        ),
        Index(
            "ix_collaboration_resource_workspace_kind",
            "workspace_id",
            "resource_kind",
            "created_at",
        ),
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), primary_key=True
    )
    resource_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    canvas_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    canonical_object_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    workflow_definition_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    creator_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationResourceOwnershipTransition(Base):
    """Append-only current ownership and visibility-policy evidence."""

    __tablename__ = "collaboration_resource_ownership_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_ownership_resource_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["current_owner_membership_id", "current_owner_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_ownership_current_member_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_owner_membership_id", "previous_owner_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_ownership_previous_member_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "resource_id",
            "workspace_id",
            "resource_kind",
            "sequence",
            name="uq_collaboration_ownership_sequence",
        ),
        CheckConstraint("sequence >= 0", name="ck_collaboration_ownership_sequence"),
        CheckConstraint(
            "current_owner_kind IN ('workspace', 'membership')",
            name="ck_collaboration_ownership_current_kind",
        ),
        CheckConstraint(
            "previous_owner_kind IS NULL OR previous_owner_kind IN ('workspace', 'membership')",
            name="ck_collaboration_ownership_previous_kind",
        ),
        CheckConstraint(
            "(current_owner_kind = 'workspace' AND current_owner_membership_id IS NULL "
            "AND current_owner_user_id IS NULL) OR "
            "(current_owner_kind = 'membership' AND current_owner_membership_id IS NOT NULL "
            "AND current_owner_user_id IS NOT NULL)",
            name="ck_collaboration_ownership_current_shape",
        ),
        CheckConstraint(
            "(previous_owner_kind IS NULL AND previous_owner_membership_id IS NULL "
            "AND previous_owner_user_id IS NULL) OR "
            "(previous_owner_kind = 'workspace' AND previous_owner_membership_id IS NULL "
            "AND previous_owner_user_id IS NULL) OR "
            "(previous_owner_kind = 'membership' AND previous_owner_membership_id IS NOT NULL "
            "AND previous_owner_user_id IS NOT NULL)",
            name="ck_collaboration_ownership_previous_shape",
        ),
        CheckConstraint(
            "visibility_policy IN ('private', 'inherit', 'workspace_visible')",
            name="ck_collaboration_ownership_visibility",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_ownership_generation",
        ),
        Index(
            "ix_collaboration_ownership_current",
            "workspace_id",
            "resource_kind",
            "resource_id",
            "sequence",
        ),
        Index(
            "ix_collaboration_ownership_member",
            "workspace_id",
            "current_owner_membership_id",
            "recorded_at",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_owner_kind: Mapped[str | None] = mapped_column(String(16))
    previous_owner_membership_id: Mapped[uuid.UUID | None] = mapped_column()
    previous_owner_user_id: Mapped[uuid.UUID | None] = mapped_column()
    current_owner_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    current_owner_membership_id: Mapped[uuid.UUID | None] = mapped_column()
    current_owner_user_id: Mapped[uuid.UUID | None] = mapped_column()
    visibility_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace_memberships.membership_id", ondelete="RESTRICT")
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT")
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationResourceShare(Base):
    """Immutable typed share identity; lifecycle and access are transitions."""

    __tablename__ = "collaboration_resource_shares"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_share_resource_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["audience_membership_id", "audience_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_share_audience_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "created_by_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_share_creator_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "share_id",
            "workspace_id",
            name="uq_collaboration_share_scope",
        ),
        UniqueConstraint(
            "workspace_id",
            "resource_kind",
            "resource_id",
            "audience_key",
            name="uq_collaboration_share_audience",
        ),
        CheckConstraint(
            "audience_kind IN ('workspace', 'membership')",
            name="ck_collaboration_share_audience_kind",
        ),
        CheckConstraint(
            "(audience_kind = 'workspace' AND audience_membership_id IS NULL "
            "AND audience_user_id IS NULL) OR "
            "(audience_kind = 'membership' AND audience_membership_id IS NOT NULL "
            "AND audience_user_id IS NOT NULL)",
            name="ck_collaboration_share_audience_shape",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_share_policy",
        ),
        CheckConstraint(
            "length(request_digest) = 64",
            name="ck_collaboration_share_request_digest",
        ),
        Index(
            "ix_collaboration_share_resource",
            "workspace_id",
            "resource_kind",
            "resource_id",
            "created_at",
        ),
        Index(
            "ix_collaboration_share_audience",
            "workspace_id",
            "audience_membership_id",
            "created_at",
        ),
        Index("ix_collaboration_share_request", "workspace_id", "creation_request_id"),
    )

    share_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    audience_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    audience_key: Mapped[str] = mapped_column(String(64), nullable=False)
    audience_membership_id: Mapped[uuid.UUID | None] = mapped_column()
    audience_user_id: Mapped[uuid.UUID | None] = mapped_column()
    created_by_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    creation_request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationResourceShareTransition(Base):
    """Append-only share access, expiration, and revocation evidence."""

    __tablename__ = "collaboration_resource_share_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["share_id", "workspace_id"],
            [
                "collaboration_resource_shares.share_id",
                "collaboration_resource_shares.workspace_id",
            ],
            name="fk_collaboration_share_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "share_id",
            "sequence",
            name="uq_collaboration_share_transition_sequence",
        ),
        CheckConstraint("sequence >= 0", name="ck_collaboration_share_transition_sequence"),
        CheckConstraint(
            "current_state IN ('active', 'revoked')",
            name="ck_collaboration_share_transition_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('active', 'revoked')",
            name="ck_collaboration_share_transition_previous_state",
        ),
        CheckConstraint(
            "access_level IN ('view', 'contribute', 'manage')",
            name="ck_collaboration_share_transition_access",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > recorded_at",
            name="ck_collaboration_share_transition_expiry",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_share_transition_generation",
        ),
        Index(
            "ix_collaboration_share_transition_current",
            "share_id",
            "sequence",
        ),
        Index(
            "ix_collaboration_share_transition_expiry",
            "workspace_id",
            "current_state",
            "expires_at",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    share_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(16))
    current_state: Mapped[str] = mapped_column(String(16), nullable=False)
    access_level: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_memberships.membership_id", ondelete="RESTRICT"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationOwnershipTransfer(Base):
    """Immutable workspace or resource ownership-transfer request."""

    __tablename__ = "collaboration_ownership_transfers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_transfer_resource_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requester_membership_id", "requester_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_transfer_requester_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_membership_id", "recipient_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_transfer_recipient_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "transfer_id",
            "workspace_id",
            name="uq_collaboration_transfer_scope",
        ),
        CheckConstraint(
            "transfer_kind IN ('workspace', 'resource')",
            name="ck_collaboration_transfer_kind",
        ),
        CheckConstraint(
            "(transfer_kind = 'workspace' AND resource_id IS NULL "
            "AND resource_kind IS NULL) OR "
            "(transfer_kind = 'resource' AND resource_id IS NOT NULL "
            "AND resource_kind IS NOT NULL)",
            name="ck_collaboration_transfer_target_shape",
        ),
        CheckConstraint(
            "requester_membership_id <> recipient_membership_id",
            name="ck_collaboration_transfer_distinct_memberships",
        ),
        CheckConstraint(
            "former_owner_role IN ('administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_collaboration_transfer_former_owner_role",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_collaboration_transfer_expiry",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_transfer_policy",
        ),
        CheckConstraint(
            "length(request_digest) = 64",
            name="ck_collaboration_transfer_request_digest",
        ),
        Index(
            "ix_collaboration_transfer_workspace_time",
            "workspace_id",
            "transfer_kind",
            "created_at",
        ),
        Index(
            "ix_collaboration_transfer_recipient",
            "workspace_id",
            "recipient_membership_id",
            "created_at",
        ),
    )

    transfer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    transfer_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    resource_kind: Mapped[str | None] = mapped_column(String(32))
    requester_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    requester_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recipient_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    former_owner_role: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationOwnershipTransferTransition(Base):
    """Append-only transfer lifecycle evidence."""

    __tablename__ = "collaboration_ownership_transfer_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transfer_id", "workspace_id"],
            [
                "collaboration_ownership_transfers.transfer_id",
                "collaboration_ownership_transfers.workspace_id",
            ],
            name="fk_collaboration_transfer_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "transfer_id",
            "sequence",
            name="uq_collaboration_transfer_transition_sequence",
        ),
        CheckConstraint("sequence >= 0", name="ck_collaboration_transfer_transition_sequence"),
        CheckConstraint(
            "current_state IN ('pending', 'accepted', 'rejected', 'canceled', "
            "'expired', 'superseded')",
            name="ck_collaboration_transfer_transition_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('pending', 'accepted', 'rejected', 'canceled', 'expired', 'superseded')",
            name="ck_collaboration_transfer_transition_previous_state",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_transfer_transition_generation",
        ),
        Index(
            "ix_collaboration_transfer_transition_current",
            "transfer_id",
            "sequence",
        ),
        Index(
            "ix_collaboration_transfer_transition_workspace",
            "workspace_id",
            "recorded_at",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    transfer_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(16))
    current_state: Mapped[str] = mapped_column(String(16), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_memberships.membership_id", ondelete="RESTRICT"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationAuthoritySnapshot(Base):
    """Immutable point-in-time collaboration authority evidence."""

    __tablename__ = "collaboration_authority_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_snapshot_member_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "snapshot_id",
            "user_id",
            "membership_id",
            "workspace_id",
            name="uq_collaboration_snapshot_invoker_scope",
        ),
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_snapshot_resource_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["share_id", "workspace_id"],
            [
                "collaboration_resource_shares.share_id",
                "collaboration_resource_shares.workspace_id",
            ],
            name="fk_collaboration_snapshot_share_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role IN ('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_collaboration_snapshot_role",
        ),
        CheckConstraint(
            "boundary IN ('claim', 'service_call', 'tool_call', 'retry', 'effect', "
            "'compensation', 'export', 'publication', 'share_decision', "
            "'ownership_decision')",
            name="ck_collaboration_snapshot_boundary",
        ),
        CheckConstraint(
            "(resource_id IS NULL AND resource_kind IS NULL) OR "
            "(resource_id IS NOT NULL AND resource_kind IS NOT NULL)",
            name="ck_collaboration_snapshot_resource_shape",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_snapshot_generation",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_snapshot_policy",
        ),
        CheckConstraint(
            "length(scope_digest) = 64",
            name="ck_collaboration_snapshot_digest",
        ),
        Index(
            "ix_collaboration_snapshot_controlled_execution",
            "controlled_execution_id",
            "captured_at",
        ),
        Index(
            "ix_collaboration_snapshot_workflow_execution",
            "workflow_execution_id",
            "captured_at",
        ),
        Index(
            "ix_collaboration_snapshot_scope",
            "workspace_id",
            "membership_id",
            "captured_at",
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    permission: Mapped[str] = mapped_column(String(64), nullable=False)
    boundary: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    resource_kind: Mapped[str | None] = mapped_column(String(32))
    share_id: Mapped[uuid.UUID | None] = mapped_column()
    ownership_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "collaboration_resource_ownership_transitions.transition_id",
            ondelete="RESTRICT",
        )
    )
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    controlled_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("controlled_agent_executions.id", ondelete="RESTRICT")
    )
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("controlled_workflow_executions.execution_id", ondelete="RESTRICT")
    )
    request_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collaboration_request_identities.request_id", ondelete="RESTRICT")
    )
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationRevocationFence(Base):
    """Append-only monotonic authority-generation advance evidence."""

    __tablename__ = "collaboration_revocation_fences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "membership_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_fence_member_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["share_id", "workspace_id"],
            [
                "collaboration_resource_shares.share_id",
                "collaboration_resource_shares.workspace_id",
            ],
            name="fk_collaboration_fence_share_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_fence_resource_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "scope_kind IN ('workspace', 'membership', 'share', 'resource_ownership', "
            "'resource_visibility', 'approval_authority')",
            name="ck_collaboration_fence_scope_kind",
        ),
        CheckConstraint(
            "authority_generation = previous_authority_generation + 1",
            name="ck_collaboration_fence_monotonic",
        ),
        CheckConstraint(
            "(resource_id IS NULL AND resource_kind IS NULL) OR "
            "(resource_id IS NOT NULL AND resource_kind IS NOT NULL)",
            name="ck_collaboration_fence_resource_shape",
        ),
        Index(
            "ix_collaboration_fence_workspace_generation",
            "workspace_id",
            "authority_generation",
        ),
        Index("ix_collaboration_fence_share", "share_id", "recorded_at"),
        Index("ix_collaboration_fence_membership", "membership_id", "recorded_at"),
    )

    fence_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    membership_id: Mapped[uuid.UUID | None] = mapped_column()
    membership_user_id: Mapped[uuid.UUID | None] = mapped_column()
    share_id: Mapped[uuid.UUID | None] = mapped_column()
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    resource_kind: Mapped[str | None] = mapped_column(String(32))
    previous_authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_memberships.membership_id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationCommentThread(Base):
    """Immutable thread identity for one exact collaboration resource."""

    __tablename__ = "collaboration_comment_threads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_comment_thread_resource_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["creator_membership_id", "creator_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_thread_creator_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "thread_id",
            "workspace_id",
            "resource_id",
            "resource_kind",
            name="uq_collaboration_comment_thread_scope",
        ),
        UniqueConstraint(
            "workspace_id",
            "resource_id",
            "resource_kind",
            "resource_sequence",
            name="uq_collaboration_comment_thread_resource_sequence",
        ),
        CheckConstraint(
            "resource_kind IN ('canvas', 'canonical_object', 'workflow', 'agent')",
            name="ck_collaboration_comment_thread_resource_kind",
        ),
        CheckConstraint(
            "resource_sequence > 0",
            name="ck_collaboration_comment_thread_sequence",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_thread_generation",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_comment_thread_policy",
        ),
        Index(
            "ix_collaboration_comment_thread_resource",
            "workspace_id",
            "resource_kind",
            "resource_id",
            "resource_sequence",
        ),
        Index(
            "ix_collaboration_comment_thread_creator",
            "workspace_id",
            "creator_membership_id",
            "created_at",
        ),
    )

    thread_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canvas_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT")
    )
    resource_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creator_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    creation_request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationCommentThreadTransition(Base):
    """Append-only thread resolution and reopening evidence."""

    __tablename__ = "collaboration_comment_thread_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comment_threads.thread_id",
                "collaboration_comment_threads.workspace_id",
                "collaboration_comment_threads.resource_id",
                "collaboration_comment_threads.resource_kind",
            ],
            name="fk_collaboration_comment_thread_transition_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "actor_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_thread_transition_actor_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "thread_id",
            "sequence",
            name="uq_collaboration_comment_thread_transition_sequence",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('open', 'resolved', 'reopened')",
            name="ck_collaboration_comment_thread_transition_previous",
        ),
        CheckConstraint(
            "current_state IN ('open', 'resolved', 'reopened')",
            name="ck_collaboration_comment_thread_transition_state",
        ),
        CheckConstraint(
            "sequence >= 0",
            name="ck_collaboration_comment_thread_transition_sequence",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_thread_transition_generation",
        ),
        Index(
            "ix_collaboration_comment_thread_transition_current",
            "workspace_id",
            "thread_id",
            "sequence",
        ),
        Index(
            "ix_collaboration_comment_thread_transition_state",
            "workspace_id",
            "current_state",
            "recorded_at",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(16))
    current_state: Mapped[str] = mapped_column(String(16), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationComment(Base):
    """Immutable comment identity and bounded reply relationship."""

    __tablename__ = "collaboration_comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comment_threads.thread_id",
                "collaboration_comment_threads.workspace_id",
                "collaboration_comment_threads.resource_id",
                "collaboration_comment_threads.resource_kind",
            ],
            name="fk_collaboration_comment_thread_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "parent_comment_id",
                "thread_id",
                "workspace_id",
                "resource_id",
                "resource_kind",
            ],
            [
                "collaboration_comments.comment_id",
                "collaboration_comments.thread_id",
                "collaboration_comments.workspace_id",
                "collaboration_comments.resource_id",
                "collaboration_comments.resource_kind",
            ],
            name="fk_collaboration_comment_parent_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["author_membership_id", "author_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_author_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "comment_id",
            "thread_id",
            "workspace_id",
            "resource_id",
            "resource_kind",
            name="uq_collaboration_comment_scope",
        ),
        UniqueConstraint(
            "thread_id",
            "thread_sequence",
            name="uq_collaboration_comment_thread_sequence",
        ),
        CheckConstraint(
            "depth BETWEEN 0 AND 4",
            name="ck_collaboration_comment_depth",
        ),
        CheckConstraint(
            "(depth = 0 AND parent_comment_id IS NULL) OR "
            "(depth > 0 AND parent_comment_id IS NOT NULL)",
            name="ck_collaboration_comment_parent_shape",
        ),
        CheckConstraint(
            "parent_comment_id IS NULL OR parent_comment_id <> comment_id",
            name="ck_collaboration_comment_not_self_parent",
        ),
        CheckConstraint(
            "thread_sequence > 0",
            name="ck_collaboration_comment_thread_sequence",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_generation",
        ),
        CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_comment_policy",
        ),
        Index(
            "ix_collaboration_comment_thread_order",
            "workspace_id",
            "thread_id",
            "thread_sequence",
            "comment_id",
        ),
        Index(
            "ix_collaboration_comment_author",
            "workspace_id",
            "author_membership_id",
            "created_at",
        ),
        Index(
            "ix_collaboration_comment_parent",
            "workspace_id",
            "parent_comment_id",
            "thread_sequence",
        ),
    )

    comment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_comment_id: Mapped[uuid.UUID | None] = mapped_column()
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    thread_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    author_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    collaboration_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    creation_request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    creation_audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationCommentRevision(Base):
    """Immutable bounded plain-text content for one comment revision."""

    __tablename__ = "collaboration_comment_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["comment_id", "thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comments.comment_id",
                "collaboration_comments.thread_id",
                "collaboration_comments.workspace_id",
                "collaboration_comments.resource_id",
                "collaboration_comments.resource_kind",
            ],
            name="fk_collaboration_comment_revision_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_revision_id", "comment_id", "workspace_id"],
            [
                "collaboration_comment_revisions.revision_id",
                "collaboration_comment_revisions.comment_id",
                "collaboration_comment_revisions.workspace_id",
            ],
            name="fk_collaboration_comment_revision_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["author_membership_id", "author_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_revision_author_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "revision_id",
            "comment_id",
            "workspace_id",
            name="uq_collaboration_comment_revision_scope",
        ),
        UniqueConstraint(
            "comment_id",
            "sequence",
            name="uq_collaboration_comment_revision_sequence",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_collaboration_comment_revision_sequence",
        ),
        CheckConstraint(
            "revision_kind IN ('created', 'edited')",
            name="ck_collaboration_comment_revision_kind",
        ),
        CheckConstraint(
            "(sequence = 1 AND revision_kind = 'created' AND "
            "previous_revision_id IS NULL) OR "
            "(sequence > 1 AND revision_kind = 'edited' AND "
            "previous_revision_id IS NOT NULL)",
            name="ck_collaboration_comment_revision_previous_shape",
        ),
        CheckConstraint(
            "length(content) BETWEEN 1 AND 5000",
            name="ck_collaboration_comment_revision_content_length",
        ),
        CheckConstraint(
            "length(content_digest) = 64",
            name="ck_collaboration_comment_revision_digest",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_revision_generation",
        ),
        Index(
            "ix_collaboration_comment_revision_history",
            "workspace_id",
            "comment_id",
            "sequence",
        ),
        Index(
            "ix_collaboration_comment_revision_author",
            "workspace_id",
            "author_membership_id",
            "created_at",
        ),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    comment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column()
    revision_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    author_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollaborationCommentTransition(Base):
    """Append-only visible state and tombstone evidence for one comment."""

    __tablename__ = "collaboration_comment_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["comment_id", "thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comments.comment_id",
                "collaboration_comments.thread_id",
                "collaboration_comments.workspace_id",
                "collaboration_comments.resource_id",
                "collaboration_comments.resource_kind",
            ],
            name="fk_collaboration_comment_transition_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["visible_revision_id", "comment_id", "workspace_id"],
            [
                "collaboration_comment_revisions.revision_id",
                "collaboration_comment_revisions.comment_id",
                "collaboration_comment_revisions.workspace_id",
            ],
            name="fk_collaboration_comment_transition_visible_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_id", "actor_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_transition_actor_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "comment_id",
            "sequence",
            name="uq_collaboration_comment_transition_sequence",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('active', 'edited', 'hidden_by_moderation', 'removed_by_author')",
            name="ck_collaboration_comment_transition_previous",
        ),
        CheckConstraint(
            "current_state IN ('active', 'edited', 'hidden_by_moderation', 'removed_by_author')",
            name="ck_collaboration_comment_transition_state",
        ),
        CheckConstraint(
            "(current_state IN ('active', 'edited') AND visible_revision_id IS NOT NULL) "
            "OR (current_state IN ('hidden_by_moderation', 'removed_by_author') "
            "AND visible_revision_id IS NULL)",
            name="ck_collaboration_comment_transition_visibility",
        ),
        CheckConstraint(
            "sequence >= 0",
            name="ck_collaboration_comment_transition_sequence",
        ),
        CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_transition_generation",
        ),
        Index(
            "ix_collaboration_comment_transition_current",
            "workspace_id",
            "comment_id",
            "sequence",
        ),
        Index(
            "ix_collaboration_comment_transition_state",
            "workspace_id",
            "current_state",
            "recorded_at",
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    comment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32))
    current_state: Mapped[str] = mapped_column(String(32), nullable=False)
    visible_revision_id: Mapped[uuid.UUID | None] = mapped_column()
    authority_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collaboration_audit_events.audit_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CanonicalObject(TimestampMixin, Base):
    __tablename__ = "canonical_objects"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_canonical_objects_id_workspace"),
        CheckConstraint(
            "object_type IN ('document', 'chunk', 'note', 'execution', 'relationship')",
            name="ck_canonical_objects_type",
        ),
        CheckConstraint("version >= 1", name="ck_canonical_objects_version_positive"),
        CheckConstraint(
            "lifecycle_state IN ('created', 'active', 'archived', 'deleted')",
            name="ck_canonical_objects_lifecycle_state",
        ),
        Index(
            "ix_canonical_objects_workspace_type_state",
            "workspace_id",
            "object_type",
            "lifecycle_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    metadata_payload: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class CanonicalDocument(Base):
    __tablename__ = "canonical_documents"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('created', 'processing', 'ready', 'failed')",
            name="ck_canonical_documents_processing_status",
        ),
        Index("ix_canonical_documents_processing_status", "processing_status"),
    )

    object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_objects.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    source_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    legacy_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), unique=True
    )


class CanonicalChunk(Base):
    __tablename__ = "canonical_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_object_id",
            "ordered_position",
            name="uq_canonical_chunks_document_position",
        ),
        CheckConstraint("ordered_position >= 0", name="ck_canonical_chunks_position_nonnegative"),
    )

    object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_objects.id", ondelete="CASCADE"), primary_key=True
    )
    document_object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_documents.object_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordered_position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_location: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class CanonicalNote(Base):
    __tablename__ = "canonical_notes"

    object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_objects.id", ondelete="CASCADE"), primary_key=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class CanonicalExecution(Base):
    __tablename__ = "canonical_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_canonical_executions_status",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_canonical_executions_time_order",
        ),
        Index("ix_canonical_executions_status", "status"),
        Index("ix_canonical_executions_trace_id", "trace_id"),
    )

    object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_objects.id", ondelete="CASCADE"), primary_key=True
    )
    execution_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[uuid.UUID | None] = mapped_column()
    inputs_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    outputs_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    failure: Mapped[dict[str, object] | None] = mapped_column(JSON)


class CanonicalRelationship(Base):
    __tablename__ = "canonical_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_canonical_relationships_object_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_canonical_relationships_source_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_canonical_relationships_target_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "source_object_id",
            "target_object_id",
            "relationship_type",
            name="uq_canonical_relationships_direction_type",
        ),
        UniqueConstraint(
            "object_id",
            "workspace_id",
            name="uq_canonical_relationships_object_workspace",
        ),
        CheckConstraint(
            "relationship_type IN "
            "('contains', 'part_of', 'references', 'derived_from', 'related_to', "
            "'cites', 'supports', 'contradicts', 'produced_by', 'affected_by')",
            name="ck_canonical_relationships_type",
        ),
        CheckConstraint(
            "source_object_id <> target_object_id",
            name="ck_canonical_relationships_not_self",
        ),
        Index(
            "ix_canonical_relationships_workspace_type",
            "workspace_id",
            "relationship_type",
        ),
        Index(
            "ix_canonical_relationships_workspace_target",
            "workspace_id",
            "target_object_id",
        ),
        Index("ix_canonical_relationships_trace_id", "trace_id"),
    )

    object_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column()
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class WorkspaceGraphState(Base):
    """Server-owned optimistic revision for one workspace's semantic graph."""

    __tablename__ = "workspace_graph_states"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_workspace_graph_state_revision_nonnegative"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CanonicalGraphEntity(Base):
    """Stable graph identity backed by an existing canonical object."""

    __tablename__ = "canonical_graph_entities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_graph_entities_object_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "object_id",
            "workspace_id",
            "user_id",
            name="uq_graph_entities_object_scope",
        ),
        CheckConstraint(
            "entity_kind IN ('document', 'note', 'execution')",
            name="ck_graph_entities_kind",
        ),
        Index(
            "ix_graph_entities_scope_kind",
            "user_id",
            "workspace_id",
            "entity_kind",
        ),
    )

    object_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    entity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CanonicalCanvasObjectBinding(Base):
    """Immutable presentation binding; semantic identity remains the canonical object."""

    __tablename__ = "canonical_canvas_object_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_id", "workspace_id", "user_id"],
            [
                "canonical_graph_entities.object_id",
                "canonical_graph_entities.workspace_id",
                "canonical_graph_entities.user_id",
            ],
            name="fk_canvas_object_bindings_entity_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_canvas_object_bindings_canvas_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "object_id",
            "workspace_id",
            "user_id",
            "canvas_id",
            name="uq_canvas_object_bindings_entity_canvas",
        ),
        Index(
            "ix_canvas_object_bindings_scope",
            "user_id",
            "workspace_id",
            "canvas_id",
        ),
    )

    binding_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CanonicalGraphRelationship(Base):
    """Scoped integrity extension for one canonical relationship."""

    __tablename__ = "canonical_graph_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["relationship_id", "workspace_id"],
            ["canonical_relationships.object_id", "canonical_relationships.workspace_id"],
            name="fk_graph_relationships_canonical_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_object_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_canvas_object_bindings.object_id",
                "canonical_canvas_object_bindings.workspace_id",
                "canonical_canvas_object_bindings.user_id",
                "canonical_canvas_object_bindings.canvas_id",
            ],
            name="fk_graph_relationships_source_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_object_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_canvas_object_bindings.object_id",
                "canonical_canvas_object_bindings.workspace_id",
                "canonical_canvas_object_bindings.user_id",
                "canonical_canvas_object_bindings.canvas_id",
            ],
            name="fk_graph_relationships_target_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "relationship_id",
            "workspace_id",
            "user_id",
            "canvas_id",
            name="uq_graph_relationships_scope",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_graph_relationships_idempotency",
        ),
        CheckConstraint(
            "schema_version = 'knowledge-graph-v1'",
            name="ck_graph_relationships_schema",
        ),
        CheckConstraint("graph_revision > 0", name="ck_graph_relationships_revision_positive"),
        CheckConstraint(
            "length(canonical_digest) = 64 AND length(request_digest) = 64",
            name="ck_graph_relationships_digest_length",
        ),
        Index(
            "ix_graph_relationships_source",
            "user_id",
            "workspace_id",
            "canvas_id",
            "source_object_id",
        ),
        Index(
            "ix_graph_relationships_target",
            "user_id",
            "workspace_id",
            "canvas_id",
            "target_object_id",
        ),
    )

    relationship_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    graph_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CanonicalRelationshipProvenance(Base):
    """Immutable evidence explaining why a canonical graph relationship exists."""

    __tablename__ = "canonical_relationship_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["relationship_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_graph_relationships.relationship_id",
                "canonical_graph_relationships.workspace_id",
                "canonical_graph_relationships.user_id",
                "canonical_graph_relationships.canvas_id",
            ],
            name="fk_relationship_provenance_graph_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_relationship_provenance_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("relationship_id", name="uq_relationship_provenance_relationship"),
        CheckConstraint(
            "origin_type IN ('user_created', 'imported_canonical', 'citation_derived', "
            "'controlled_agent_approved', 'deterministic_rule')",
            name="ck_relationship_provenance_origin",
        ),
        CheckConstraint(
            "(origin_type = 'controlled_agent_approved' AND execution_id IS NOT NULL) OR "
            "(origin_type <> 'controlled_agent_approved' AND execution_id IS NULL)",
            name="ck_relationship_provenance_execution_shape",
        ),
        CheckConstraint(
            "(origin_type IN ('imported_canonical', 'citation_derived') "
            "AND source_reference_id IS NOT NULL) OR "
            "(origin_type NOT IN ('imported_canonical', 'citation_derived') "
            "AND source_reference_id IS NULL)",
            name="ck_relationship_provenance_source_shape",
        ),
        CheckConstraint(
            "(origin_type = 'deterministic_rule' AND rule_id IS NOT NULL "
            "AND rule_version IS NOT NULL) OR "
            "(origin_type <> 'deterministic_rule' AND rule_id IS NULL "
            "AND rule_version IS NULL)",
            name="ck_relationship_provenance_rule_shape",
        ),
        CheckConstraint(
            "length(provenance_digest) = 64",
            name="ck_relationship_provenance_digest_length",
        ),
        Index("ix_relationship_provenance_trace", "trace_id"),
    )

    provenance_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    relationship_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    origin_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column()
    source_reference_id: Mapped[uuid.UUID | None] = mapped_column()
    rule_id: Mapped[str | None] = mapped_column(String(120))
    rule_version: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    provenance_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CanonicalRelationshipHistory(Base):
    """Append-only relationship lifecycle evidence."""

    __tablename__ = "canonical_relationship_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["relationship_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_graph_relationships.relationship_id",
                "canonical_graph_relationships.workspace_id",
                "canonical_graph_relationships.user_id",
                "canonical_graph_relationships.canvas_id",
            ],
            name="fk_relationship_history_graph_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_history_id", "relationship_id"],
            [
                "canonical_relationship_history.history_id",
                "canonical_relationship_history.relationship_id",
            ],
            name="fk_relationship_history_previous",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "history_id",
            "relationship_id",
            name="uq_relationship_history_identity",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_relationship_history_idempotency",
        ),
        CheckConstraint(
            "state IN ('active', 'inactive', 'superseded', 'rejected')",
            name="ck_relationship_history_state",
        ),
        CheckConstraint("graph_revision > 0", name="ck_relationship_history_revision_positive"),
        CheckConstraint(
            "length(request_digest) = 64",
            name="ck_relationship_history_request_digest_length",
        ),
        Index(
            "ix_relationship_history_timeline",
            "relationship_id",
            "graph_revision",
            "history_id",
        ),
    )

    history_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    relationship_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    graph_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_history_id: Mapped[uuid.UUID | None] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkspaceEventSequence(Base):
    """Server-owned monotonic sequence for one workspace event stream."""

    __tablename__ = "workspace_event_sequences"
    __table_args__ = (
        CheckConstraint("last_sequence >= 0", name="ck_workspace_event_sequence_nonnegative"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DomainEventRecord(Base):
    """Immutable scoped business fact; distinct from audit and Trace evidence."""

    __tablename__ = "domain_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_domain_events_canvas_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_domain_events_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "scope_id",
            "event_type",
            "source_identity",
            name="uq_domain_events_idempotency_scope",
        ),
        UniqueConstraint(
            "event_id",
            "user_id",
            "workspace_id",
            name="uq_domain_events_scope",
        ),
        UniqueConstraint(
            "workspace_id",
            "sequence",
            name="uq_domain_events_workspace_sequence",
        ),
        CheckConstraint(
            "registry_version = 'mobius-domain-events-v1'",
            name="ck_domain_events_registry_version",
        ),
        CheckConstraint(
            "schema_version = 'domain-event-v1'",
            name="ck_domain_events_schema_version",
        ),
        CheckConstraint(
            "event_type IN ("
            "'graph.relationship.created', "
            "'graph.relationship.superseded', "
            "'graph.relationship.deactivated', "
            "'canonical.resource.created', "
            "'canonical.resource.updated', "
            "'canonical.resource.historical', "
            "'controlled.execution.started', "
            "'controlled.execution.completed', "
            "'controlled.execution.failed', "
            "'controlled.execution.canceled', "
            "'controlled.effect.committed', "
            "'controlled.rollback.committed', "
            "'evidence.bundle.requested', "
            "'evidence.bundle.generation_started', "
            "'evidence.bundle.completed', "
            "'evidence.bundle.failed', "
            "'evidence.bundle.accessed', "
            "'evidence.bundle.export_denied', "
            "'citation.rendering.completed', "
            "'citation.rendering.failed', "
            "'workflow.definition.created', "
            "'workflow.version.created', "
            "'workflow.version.validated', "
            "'workflow.version.activated', "
            "'workflow.version.disabled', "
            "'workflow.execution.requested', "
            "'workflow.execution.planned', "
            "'workflow.execution.started', "
            "'workflow.execution.awaiting_approval', "
            "'workflow.execution.completed', "
            "'workflow.execution.failed', "
            "'workflow.execution.canceled', "
            "'workflow.compensation.started', "
            "'workflow.compensation.completed', "
            "'workflow.compensation.failed', "
            "'workflow.step.started', "
            "'workflow.step.completed', "
            "'workflow.step.failed', "
            "'workflow.step.retry_scheduled', "
            "'workflow.step.awaiting_approval', "
            "'workflow.approval.requested', "
            "'workflow.approval.accepted', "
            "'workflow.approval.denied', "
            "'agent.identity.created', "
            "'agent.version.created', "
            "'agent.version.validated', "
            "'agent.version.validation_failed', "
            "'agent.version.activated', "
            "'agent.activation.requested', "
            "'agent.activation.approved', "
            "'agent.activation.denied', "
            "'agent.invocation.started', "
            "'agent.proposal.created', "
            "'agent.proposal.accepted', "
            "'agent.proposal.rejected', "
            "'agent.evaluation.recorded', "
            "'agent.communication.revision_proposed', "
            "'agent.communication.revision_accepted', "
            "'agent.communication.revision_rejected', "
            "'agent.suspended', "
            "'agent.retired', "
            "'invitation.created', "
            "'invitation.accepted', "
            "'invitation.declined', "
            "'invitation.expired', "
            "'invitation.revoked', "
            "'membership.activated', "
            "'membership.role_changed', "
            "'membership.suspended', "
            "'membership.restored', "
            "'membership.removed', "
            "'approval_authority.assigned', "
            "'approval_authority.replaced', "
            "'approval_authority.revoked', "
            "'resource.share.created', "
            "'resource.share.changed', "
            "'resource.share.revoked', "
            "'resource.share.expired', "
            "'resource.visibility.changed', "
            "'resource.ownership_changed', "
            "'ownership_transfer.requested', "
            "'ownership_transfer.accepted', "
            "'ownership_transfer.rejected', "
            "'ownership_transfer.canceled', "
            "'revocation.bulk_completed', "
            "'comment.created', "
            "'comment.reply.created', "
            "'comment.revised', "
            "'comment.tombstoned', "
            "'comment.thread.resolved', "
            "'comment.thread.reopened', "
            "'ingestion.requested', "
            "'ingestion.queued', "
            "'ingestion.failed', "
            "'ingestion.canceled', "
            "'index.reindex.requested', "
            "'index.revision.created', "
            "'index.published', "
            "'index.superseded')",
            name="ck_domain_events_type",
        ),
        CheckConstraint(
            "subject_kind IN ('canonical_resource', 'graph_relationship', "
            "'controlled_execution', 'controlled_effect', 'controlled_rollback', "
            "'evidence_bundle', 'citation', 'workflow_definition', 'workflow_version', "
            "'workflow_execution', 'workflow_step', 'agent_identity', 'agent_version', "
            "'agent_activation', 'agent_invocation', 'agent_proposal', "
            "'agent_evaluation', 'communication_revision', "
            "'workspace_invitation', 'workspace_membership', "
            "'approval_authority_assignment', 'collaboration_resource', "
            "'resource_share', 'ownership_transfer', 'authority_fence', "
            "'comment_thread', 'comment', 'ingestion_request', "
            "'index_revision', 'index_publication')",
            name="ck_domain_events_subject_kind",
        ),
        CheckConstraint("sequence > 0", name="ck_domain_events_sequence_positive"),
        CheckConstraint(
            "length(payload_digest) = 64 AND length(request_digest) = 64",
            name="ck_domain_events_digest_length",
        ),
        CheckConstraint(
            "graph_revision IS NULL OR graph_revision > 0",
            name="ck_domain_events_graph_revision_positive",
        ),
        Index(
            "ix_domain_events_workspace_timeline",
            "user_id",
            "workspace_id",
            "sequence",
            "event_id",
        ),
        Index(
            "ix_domain_events_canvas_timeline",
            "user_id",
            "workspace_id",
            "canvas_id",
            "sequence",
        ),
        Index(
            "ix_domain_events_subject_timeline",
            "user_id",
            "workspace_id",
            "subject_id",
            "sequence",
        ),
        Index("ix_domain_events_trace", "trace_id"),
        Index("ix_domain_events_execution", "execution_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    canvas_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    registry_version: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    related_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    graph_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DomainEventProvenance(Base):
    """Immutable operational provenance for one domain event."""

    __tablename__ = "domain_event_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "user_id", "workspace_id"],
            ["domain_events.event_id", "domain_events.user_id", "domain_events.workspace_id"],
            name="fk_domain_event_provenance_event_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_domain_event_provenance_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("event_id", name="uq_domain_event_provenance_event"),
        CheckConstraint(
            "origin_type IN ('authenticated_user', 'canonical_service', "
            "'controlled_execution', 'reserved_future_contract')",
            name="ck_domain_event_provenance_origin",
        ),
        CheckConstraint(
            "length(provenance_digest) = 64",
            name="ck_domain_event_provenance_digest_length",
        ),
        Index("ix_domain_event_provenance_trace", "trace_id"),
    )

    provenance_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    origin_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    graph_relationship_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    graph_history_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    effect_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    rollback_result_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    provenance_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DomainEventOutbox(Base):
    """Server-owned bounded delivery state for one domain event."""

    __tablename__ = "domain_event_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "user_id", "workspace_id"],
            ["domain_events.event_id", "domain_events.user_id", "domain_events.workspace_id"],
            name="fk_domain_event_outbox_event_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "outbox_id",
            "event_id",
            name="uq_domain_event_outbox_identity",
        ),
        UniqueConstraint("event_id", name="uq_domain_event_outbox_event"),
        CheckConstraint(
            "delivery_state IN ('pending', 'delivering', 'retry_wait', "
            "'delivered', 'terminal_failure')",
            name="ck_domain_event_outbox_state",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts AND max_attempts > 0",
            name="ck_domain_event_outbox_attempts_bounded",
        ),
        CheckConstraint(
            "lease_generation >= 0",
            name="ck_domain_event_outbox_generation_nonnegative",
        ),
        CheckConstraint(
            "(delivery_state = 'delivering' AND lease_owner_id IS NOT NULL "
            "AND lease_acquired_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > lease_acquired_at) OR "
            "(delivery_state <> 'delivering' AND lease_owner_id IS NULL "
            "AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)",
            name="ck_domain_event_outbox_lease_shape",
        ),
        CheckConstraint(
            "(delivery_state = 'delivered' AND completed_at IS NOT NULL "
            "AND terminal_at IS NULL) OR "
            "(delivery_state = 'terminal_failure' AND terminal_at IS NOT NULL) OR "
            "(delivery_state NOT IN ('delivered', 'terminal_failure') "
            "AND completed_at IS NULL AND terminal_at IS NULL)",
            name="ck_domain_event_outbox_terminal_shape",
        ),
        Index(
            "ix_domain_event_outbox_claimable",
            "delivery_state",
            "eligible_at",
            "lease_expires_at",
            "outbox_id",
        ),
        Index(
            "ix_domain_event_outbox_scope",
            "user_id",
            "workspace_id",
            "created_at",
        ),
    )

    outbox_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(24), nullable=False)
    eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    lease_owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DomainEventDeliveryAttempt(Base):
    """Append-only evidence for one dispatcher result."""

    __tablename__ = "domain_event_delivery_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["outbox_id", "event_id"],
            ["domain_event_outbox.outbox_id", "domain_event_outbox.event_id"],
            name="fk_domain_event_attempt_outbox",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "outbox_id",
            "lease_generation",
            name="uq_domain_event_attempt_generation",
        ),
        CheckConstraint(
            "outcome IN ('delivered', 'retry_scheduled', 'terminal_failure')",
            name="ck_domain_event_attempt_outcome",
        ),
        CheckConstraint("attempt_number > 0", name="ck_domain_event_attempt_number_positive"),
        Index("ix_domain_event_attempt_event", "event_id", "recorded_at"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    outbox_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DomainActivityEntry(Base):
    """Idempotent append-only timeline projection derived from one event."""

    __tablename__ = "domain_activity_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "user_id", "workspace_id"],
            ["domain_events.event_id", "domain_events.user_id", "domain_events.workspace_id"],
            name="fk_domain_activity_event_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("event_id", name="uq_domain_activity_event"),
        CheckConstraint(
            "projection_version = 'activity-v1'",
            name="ck_domain_activity_projection_version",
        ),
        Index(
            "ix_domain_activity_workspace_timeline",
            "user_id",
            "workspace_id",
            "sequence",
            "activity_id",
        ),
        Index(
            "ix_domain_activity_canvas_timeline",
            "user_id",
            "workspace_id",
            "canvas_id",
            "sequence",
        ),
        Index(
            "ix_domain_activity_subject_timeline",
            "user_id",
            "workspace_id",
            "subject_id",
            "sequence",
        ),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    projection_version: Mapped[str] = mapped_column(String(24), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphRetrievalRun(Base):
    """Immutable authoritative result of one bounded graph-aware retrieval."""

    __tablename__ = "graph_retrieval_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_graph_retrieval_runs_canvas_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_graph_retrieval_runs_idempotency",
        ),
        UniqueConstraint(
            "retrieval_id",
            "user_id",
            "workspace_id",
            name="uq_graph_retrieval_runs_scope",
        ),
        CheckConstraint(
            "algorithm_version = 'graph-retrieval-v1'",
            name="ck_graph_retrieval_runs_algorithm",
        ),
        CheckConstraint(
            "schema_version = 'graph-retrieval-result-v1'",
            name="ck_graph_retrieval_runs_schema",
        ),
        CheckConstraint(
            "mode IN ('selected_graph')",
            name="ck_graph_retrieval_runs_mode",
        ),
        CheckConstraint(
            "outcome IN ('supported', 'conflicting_evidence', "
            "'insufficient_evidence', 'bounded_result')",
            name="ck_graph_retrieval_runs_outcome",
        ),
        CheckConstraint(
            "graph_revision >= 0 AND citation_count >= 0",
            name="ck_graph_retrieval_runs_counts",
        ),
        CheckConstraint(
            "length(query_digest) = 64 AND length(request_digest) = 64",
            name="ck_graph_retrieval_runs_digests",
        ),
        Index(
            "ix_graph_retrieval_runs_scope_time",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
        Index("ix_graph_retrieval_runs_trace", "trace_id"),
    )

    retrieval_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_object_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    seed_object_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    graph_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    bounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphRetrievalDecision(Base):
    """Append-only inclusion, exclusion, traversal, and ranking evidence."""

    __tablename__ = "graph_retrieval_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["retrieval_id", "user_id", "workspace_id"],
            [
                "graph_retrieval_runs.retrieval_id",
                "graph_retrieval_runs.user_id",
                "graph_retrieval_runs.workspace_id",
            ],
            name="fk_graph_retrieval_decisions_run_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("distance >= 0", name="ck_graph_retrieval_decisions_distance"),
        CheckConstraint(
            "rank IS NULL OR rank > 0",
            name="ck_graph_retrieval_decisions_rank",
        ),
        CheckConstraint(
            "reason_code IN ('selected_seed', 'direct_citation', "
            "'supporting_relationship', 'reference_relationship', "
            "'derivation_relationship', 'graph_related_candidate', "
            "'exact_source_passage_match', 'approved_deterministic_fallback', "
            "'outside_selected_context', 'unauthorized_scope', "
            "'inactive_relationship', 'superseded_relationship', "
            "'invalid_relationship_direction', 'unsupported_relationship_kind', "
            "'historical_resource', 'removed_resource', "
            "'missing_immutable_version', 'missing_source_content', "
            "'malformed_locator', 'duplicate_candidate', "
            "'candidate_limit_reached', 'traversal_limit_reached', "
            "'insufficient_relevance', 'unsupported_schema_version', "
            "'conflicting_provenance', 'unsafe_source', "
            "'export_not_authorized')",
            name="ck_graph_retrieval_decisions_reason",
        ),
        Index(
            "ix_graph_retrieval_decisions_run_order",
            "retrieval_id",
            "included",
            "rank",
            "decision_id",
        ),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    retrieval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    relationship_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    distance: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relationship_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    detail: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphRetrievalCitation(Base):
    """Immutable exact passage and canonical source evidence."""

    __tablename__ = "graph_retrieval_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["retrieval_id", "user_id", "workspace_id"],
            [
                "graph_retrieval_runs.retrieval_id",
                "graph_retrieval_runs.user_id",
                "graph_retrieval_runs.workspace_id",
            ],
            name="fk_graph_retrieval_citations_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "retrieval_id",
            "ordinal",
            name="uq_graph_retrieval_citations_ordinal",
        ),
        UniqueConstraint(
            "retrieval_id",
            "canonical_object_id",
            "passage_identity",
            name="uq_graph_retrieval_citations_passage",
        ),
        CheckConstraint("ordinal > 0", name="ck_graph_retrieval_citations_ordinal"),
        CheckConstraint(
            "canonical_version > 0 AND source_version > 0",
            name="ck_graph_retrieval_citations_versions",
        ),
        CheckConstraint(
            "citation_schema_version = 'graph-citation-v1'",
            name="ck_graph_retrieval_citations_schema",
        ),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(excerpt_sha256) = 64",
            name="ck_graph_retrieval_citations_hashes",
        ),
        Index(
            "ix_graph_retrieval_citations_run_order",
            "retrieval_id",
            "ordinal",
        ),
        Index("ix_graph_retrieval_citations_trace", "trace_id"),
    )

    citation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    retrieval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canonical_object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canonical_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    passage_identity: Mapped[str] = mapped_column(String(96), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    relationship_path: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    graph_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TraceEvidenceBundle(Base):
    """Deterministic owner-scoped bundle stored as verified opaque bytes."""

    __tablename__ = "trace_evidence_bundles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["retrieval_id", "user_id", "workspace_id"],
            [
                "graph_retrieval_runs.retrieval_id",
                "graph_retrieval_runs.user_id",
                "graph_retrieval_runs.workspace_id",
            ],
            name="fk_trace_evidence_bundles_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("retrieval_id", name="uq_trace_evidence_bundles_retrieval"),
        CheckConstraint(
            "schema_version = 'trace-evidence-bundle-v1'",
            name="ck_trace_evidence_bundles_schema",
        ),
        CheckConstraint(
            "state IN ('completed', 'failed')",
            name="ck_trace_evidence_bundles_state",
        ),
        CheckConstraint(
            "(state = 'completed' AND artifact_bytes IS NOT NULL "
            "AND artifact_sha256 IS NOT NULL AND byte_size > 0) OR "
            "(state = 'failed' AND artifact_bytes IS NULL "
            "AND artifact_sha256 IS NULL AND byte_size = 0)",
            name="ck_trace_evidence_bundles_artifact_shape",
        ),
        CheckConstraint(
            "artifact_sha256 IS NULL OR length(artifact_sha256) = 64",
            name="ck_trace_evidence_bundles_hash",
        ),
        Index(
            "ix_trace_evidence_bundles_scope",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
    )

    bundle_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    retrieval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    artifact_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ControlledWorkflowDefinition(Base):
    """Stable scoped identity; executable content lives only in immutable versions."""

    __tablename__ = "controlled_workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "definition_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_definition_scope",
        ),
        CheckConstraint(
            "schema_version = 'controlled-workflow-v1'",
            name="ck_workflow_definition_schema",
        ),
        CheckConstraint(
            "kind IN ('grounded_answer', 'evidence_package', 'approved_reversible_note')",
            name="ck_workflow_definition_kind",
        ),
        Index(
            "ix_workflow_definition_scope_time",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
    )

    definition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowVersion(Base):
    """Immutable normalized workflow definition version."""

    __tablename__ = "controlled_workflow_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["definition_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_definitions.definition_id",
                "controlled_workflow_definitions.user_id",
                "controlled_workflow_definitions.workspace_id",
                "controlled_workflow_definitions.canvas_id",
            ],
            name="fk_workflow_version_definition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "definition_id",
            "version_number",
            name="uq_workflow_version_number",
        ),
        UniqueConstraint(
            "version_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_version_scope",
        ),
        UniqueConstraint(
            "version_id",
            "definition_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_version_parent_owner_scope",
        ),
        UniqueConstraint(
            "definition_id",
            "idempotency_key",
            name="uq_workflow_version_idempotency",
        ),
        CheckConstraint(
            "schema_version = 'controlled-workflow-v1'",
            name="ck_workflow_version_schema",
        ),
        CheckConstraint("version_number > 0", name="ck_workflow_version_number"),
        CheckConstraint("max_steps > 0 AND max_steps <= 32", name="ck_workflow_version_steps"),
        CheckConstraint(
            "max_duration_seconds > 0 AND max_duration_seconds <= 900",
            name="ck_workflow_version_duration",
        ),
        CheckConstraint(
            "max_retries_per_step >= 0 AND max_retries_per_step <= 3",
            name="ck_workflow_version_retries",
        ),
        CheckConstraint(
            "compensation_policy IN ('none', 'predefined_saga')",
            name="ck_workflow_version_compensation",
        ),
        CheckConstraint("length(content_digest) = 64", name="ck_workflow_version_digest"),
        Index("ix_workflow_version_definition_time", "definition_id", "created_at"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_definition: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_retries_per_step: Mapped[int] = mapped_column(Integer, nullable=False)
    compensation_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("controlled_workflow_versions.version_id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowVersionState(Base):
    __tablename__ = "controlled_workflow_version_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_workflow_version_state_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "version_id",
            "sequence",
            name="uq_workflow_version_state_sequence",
        ),
        CheckConstraint(
            "state IN ('draft', 'validated', 'active', 'superseded', 'disabled', 'retired')",
            name="ck_workflow_version_state",
        ),
        CheckConstraint("sequence >= 0", name="ck_workflow_version_state_sequence"),
        Index("ix_workflow_version_state_time", "version_id", "sequence"),
    )

    state_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowStep(Base):
    __tablename__ = "controlled_workflow_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_workflow_step_version_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "version_id",
            "step_id",
            name="uq_workflow_step_version_id",
        ),
        UniqueConstraint("version_id", "step_key", name="uq_workflow_step_key"),
        UniqueConstraint("version_id", "ordinal", name="uq_workflow_step_ordinal"),
        CheckConstraint("ordinal >= 0 AND ordinal < 32", name="ck_workflow_step_ordinal"),
        CheckConstraint(
            "step_type IN ('validate_input', 'capture_context', 'graph_retrieval', "
            "'evaluate_evidence', 'grounded_model', 'render_citations', "
            "'evidence_bundle', 'human_approval', 'controlled_effect', "
            "'compensation', 'record_output')",
            name="ck_workflow_step_type",
        ),
        CheckConstraint(
            "risk_class IN ('r0_observation', 'r1_draft', 'r2_transient_action', "
            "'r3_durable_write')",
            name="ck_workflow_step_risk",
        ),
        CheckConstraint(
            "max_attempts > 0 AND max_attempts <= 4",
            name="ck_workflow_step_attempts",
        ),
        CheckConstraint("length(step_digest) = 64", name="ck_workflow_step_digest"),
        Index("ix_workflow_step_version_order", "version_id", "ordinal"),
    )

    step_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(40), nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    step_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    compensation_step_key: Mapped[str | None] = mapped_column(String(64))


class ControlledWorkflowDependency(Base):
    __tablename__ = "controlled_workflow_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "step_id"],
            ["controlled_workflow_steps.version_id", "controlled_workflow_steps.step_id"],
            name="fk_workflow_dependency_step",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["version_id", "depends_on_step_id"],
            ["controlled_workflow_steps.version_id", "controlled_workflow_steps.step_id"],
            name="fk_workflow_dependency_predecessor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "version_id",
            "step_id",
            "depends_on_step_id",
            name="uq_workflow_dependency_edge",
        ),
        CheckConstraint("step_id <> depends_on_step_id", name="ck_workflow_dependency_self"),
        Index("ix_workflow_dependency_step", "version_id", "step_id"),
    )

    dependency_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    step_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    depends_on_step_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class ControlledWorkflowExecution(Base):
    __tablename__ = "controlled_workflow_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "version_id",
                "definition_id",
                "definition_owner_user_id",
                "workspace_id",
                "canvas_id",
            ],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.definition_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_workflow_execution_version_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["invoking_membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_workflow_execution_invoking_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["authority_snapshot_id", "user_id", "invoking_membership_id", "workspace_id"],
            [
                "collaboration_authority_snapshots.snapshot_id",
                "collaboration_authority_snapshots.user_id",
                "collaboration_authority_snapshots.membership_id",
                "collaboration_authority_snapshots.workspace_id",
            ],
            name="fk_workflow_execution_authority_snapshot",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "execution_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_execution_scope",
        ),
        UniqueConstraint(
            "execution_id",
            "version_id",
            "user_id",
            "invoking_membership_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_execution_invocation_scope",
        ),
        UniqueConstraint(
            "execution_id",
            "user_id",
            "workspace_id",
            name="uq_workflow_execution_owner_scope",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_workflow_execution_idempotency",
        ),
        CheckConstraint(
            "status IN ('requested', 'planned', 'awaiting_approval', 'ready', 'running', "
            "'cancel_requested', 'canceling', 'compensating', 'completed', 'failed', "
            "'canceled', 'compensated', 'compensation_failed')",
            name="ck_workflow_execution_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('supported', 'conflicting_evidence', "
            "'insufficient_evidence', 'bounded_result', 'effect_committed', "
            "'compensated', 'canceled', 'failed')",
            name="ck_workflow_execution_outcome",
        ),
        CheckConstraint("deadline_at > created_at", name="ck_workflow_execution_deadline"),
        CheckConstraint("length(request_digest) = 64", name="ck_workflow_execution_request_digest"),
        CheckConstraint("length(plan_digest) = 64", name="ck_workflow_execution_plan_digest"),
        CheckConstraint("length(input_digest) = 64", name="ck_workflow_execution_input_digest"),
        Index(
            "ix_workflow_execution_scope_time",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
        Index("ix_workflow_execution_status", "status", "deadline_at"),
        Index(
            "ix_workflow_execution_invoker_authority",
            "workspace_id",
            "user_id",
            "invoking_membership_id",
            "authority_snapshot_id",
        ),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    definition_owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    invoking_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    authority_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_input: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    selected_object_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    graph_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32))
    output: Mapped[dict[str, object] | None] = mapped_column(JSON)
    output_digest: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ControlledWorkflowPlanSnapshot(Base):
    __tablename__ = "controlled_workflow_plan_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
            ],
            name="fk_workflow_plan_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_workflow_plan_execution"),
        CheckConstraint(
            "schema_version = 'controlled-workflow-plan-v1'",
            name="ck_workflow_plan_schema",
        ),
        CheckConstraint("length(plan_digest) = 64", name="ck_workflow_plan_digest"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowExecutionTransition(Base):
    __tablename__ = "controlled_workflow_execution_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
            ],
            name="fk_workflow_execution_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_workflow_execution_transition_sequence",
        ),
        CheckConstraint("sequence >= 0", name="ck_workflow_execution_transition_sequence"),
        Index("ix_workflow_execution_transition_time", "execution_id", "sequence"),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowStepExecution(Base):
    __tablename__ = "controlled_workflow_step_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_execution_id", "user_id", "workspace_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
            ],
            name="fk_workflow_step_execution_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["step_definition_id"],
            ["controlled_workflow_steps.step_id"],
            name="fk_workflow_step_execution_definition",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workflow_execution_id",
            "step_definition_id",
            name="uq_workflow_step_execution",
        ),
        CheckConstraint(
            "status IN ('pending', 'blocked', 'awaiting_approval', 'ready', 'claimed', "
            "'running', 'succeeded', 'retry_waiting', 'failed', 'canceled', "
            "'compensating', 'compensated', 'compensation_failed', 'skipped')",
            name="ck_workflow_step_execution_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_workflow_step_execution_attempts",
        ),
        CheckConstraint(
            "(lease_owner_id IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_workflow_step_execution_lease",
        ),
        CheckConstraint(
            "lease_generation >= 0",
            name="ck_workflow_step_execution_generation",
        ),
        Index("ix_workflow_step_execution_ready", "status", "next_retry_at"),
        Index(
            "ix_workflow_step_execution_run",
            "workflow_execution_id",
            "step_definition_id",
        ),
    )

    step_execution_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    step_definition_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    controlled_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("controlled_agent_executions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner_id: Mapped[str | None] = mapped_column(String(128))
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_id: Mapped[uuid.UUID | None] = mapped_column()
    retrieval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_retrieval_runs.retrieval_id", ondelete="RESTRICT")
    )
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trace_evidence_bundles.bundle_id", ondelete="RESTRICT")
    )
    effect_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("controlled_agent_reversible_write_effects.effect_id", ondelete="RESTRICT")
    )
    rollback_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "controlled_agent_reversible_write_rollback_results.rollback_result_id",
            ondelete="RESTRICT",
        )
    )
    output: Mapped[dict[str, object] | None] = mapped_column(JSON)
    output_digest: Mapped[str | None] = mapped_column(String(64))
    safe_failure_class: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ControlledWorkflowStepTransition(Base):
    __tablename__ = "controlled_workflow_step_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["step_execution_id"],
            ["controlled_workflow_step_executions.step_execution_id"],
            name="fk_workflow_step_transition_execution",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "step_execution_id",
            "sequence",
            name="uq_workflow_step_transition_sequence",
        ),
        CheckConstraint("sequence >= 0", name="ck_workflow_step_transition_sequence"),
        Index("ix_workflow_step_transition_time", "step_execution_id", "sequence"),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    step_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowStepAttempt(Base):
    __tablename__ = "controlled_workflow_step_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["step_execution_id"],
            ["controlled_workflow_step_executions.step_execution_id"],
            name="fk_workflow_step_attempt_execution",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "step_execution_id",
            "attempt_number",
            name="uq_workflow_step_attempt_number",
        ),
        CheckConstraint("attempt_number > 0", name="ck_workflow_step_attempt_number"),
        CheckConstraint(
            "outcome IN ('succeeded', 'retry_scheduled', 'failed', 'canceled')",
            name="ck_workflow_step_attempt_outcome",
        ),
        CheckConstraint("length(input_digest) = 64", name="ck_workflow_step_attempt_input_digest"),
        CheckConstraint(
            "output_digest IS NULL OR length(output_digest) = 64",
            name="ck_workflow_step_attempt_output_digest",
        ),
        Index("ix_workflow_step_attempt_time", "step_execution_id", "attempt_number"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    step_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    output_digest: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_class: Mapped[str | None] = mapped_column(String(64))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(160))
    provider_configuration_version: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledWorkflowEvidenceLink(Base):
    __tablename__ = "controlled_workflow_evidence_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_execution_id"],
            ["controlled_workflow_executions.execution_id"],
            name="fk_workflow_evidence_execution",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["step_execution_id"],
            ["controlled_workflow_step_executions.step_execution_id"],
            name="fk_workflow_evidence_step",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workflow_execution_id",
            "step_execution_id",
            "evidence_kind",
            "evidence_id",
            name="uq_workflow_evidence_link",
        ),
        CheckConstraint(
            "evidence_kind IN ('retrieval', 'citation', 'evidence_bundle', "
            "'controlled_effect', 'controlled_rollback', 'approval', 'model_output')",
            name="ck_workflow_evidence_kind",
        ),
        CheckConstraint("length(evidence_digest) = 64", name="ck_workflow_evidence_digest"),
        Index("ix_workflow_evidence_execution", "workflow_execution_id", "step_execution_id"),
    )

    evidence_link_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    step_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentIdentity(Base):
    """Stable scoped identity for a governed Agent Studio definition."""

    __tablename__ = "bounded_agent_identities"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_scope",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_agent_create_idempotency",
        ),
        CheckConstraint(
            "schema_version = 'bounded-agent-studio-v1'",
            name="ck_bounded_agent_schema",
        ),
        CheckConstraint(
            "kind IN ('workflow_assistant', 'grounded_research_assistant', "
            "'document_analysis_assistant', 'controlled_operations_assistant', "
            "'communication_assistant', 'evaluation_assistant', 'agent_design_assistant')",
            name="ck_bounded_agent_kind",
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_bounded_agent_request_digest"),
        Index(
            "ix_bounded_agent_scope_time",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentLifecycleState(Base):
    __tablename__ = "bounded_agent_lifecycle_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_identities.agent_id",
                "bounded_agent_identities.user_id",
                "bounded_agent_identities.workspace_id",
                "bounded_agent_identities.canvas_id",
            ],
            name="fk_bounded_agent_state_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("agent_id", "sequence", name="uq_bounded_agent_state_sequence"),
        CheckConstraint(
            "state IN ('draft', 'proposed', 'validation_failed', 'validated', "
            "'awaiting_activation_approval', 'active', 'suspended', 'superseded', "
            "'retired', 'rejected')",
            name="ck_bounded_agent_state",
        ),
        CheckConstraint("sequence >= 0", name="ck_bounded_agent_state_sequence"),
        Index("ix_bounded_agent_state_time", "agent_id", "sequence"),
    )

    state_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentVersion(Base):
    """Immutable normalized definition. Editing always creates a new row."""

    __tablename__ = "bounded_agent_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_identities.agent_id",
                "bounded_agent_identities.user_id",
                "bounded_agent_identities.workspace_id",
                "bounded_agent_identities.canvas_id",
            ],
            name="fk_bounded_agent_version_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("agent_id", "version_number", name="uq_bounded_agent_version_number"),
        UniqueConstraint(
            "version_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_version_scope",
        ),
        UniqueConstraint(
            "version_id",
            "agent_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_version_parent_owner_scope",
        ),
        UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_bounded_agent_version_idempotency",
        ),
        CheckConstraint(
            "schema_version = 'bounded-agent-definition-v1'",
            name="ck_bounded_agent_version_schema",
        ),
        CheckConstraint("version_number > 0", name="ck_bounded_agent_version_number"),
        CheckConstraint(
            "provider IN ('mock', 'openai')",
            name="ck_bounded_agent_version_provider",
        ),
        CheckConstraint(
            "risk_class IN ('r0_observation', 'r1_draft', 'r2_transient_action', "
            "'r3_durable_write')",
            name="ck_bounded_agent_version_risk",
        ),
        CheckConstraint(
            "selected_context_policy IN ('required_explicit', 'optional_explicit')",
            name="ck_bounded_agent_context_policy",
        ),
        CheckConstraint(
            "evaluation_policy IN ('human_review', 'deterministic_evidence_review')",
            name="ck_bounded_agent_evaluation_policy",
        ),
        CheckConstraint("length(content_digest) = 64", name="ck_bounded_agent_version_digest"),
        Index("ix_bounded_agent_version_time", "agent_id", "version_number"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    purpose: Mapped[str] = mapped_column(String(2000), nullable=False)
    system_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    selected_context_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    limits: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    communication_policy: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    evaluation_policy: Mapped[str] = mapped_column(String(48), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_definition: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bounded_agent_versions.version_id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentVersionState(Base):
    __tablename__ = "bounded_agent_version_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_version_state_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "version_id",
            "sequence",
            name="uq_bounded_agent_version_state_sequence",
        ),
        CheckConstraint(
            "state IN ('draft', 'proposed', 'validation_failed', 'validated', "
            "'awaiting_activation_approval', 'approved', 'active', 'superseded', "
            "'rejected', 'retired')",
            name="ck_bounded_agent_version_state",
        ),
        CheckConstraint("sequence >= 0", name="ck_bounded_agent_version_state_sequence"),
        Index("ix_bounded_agent_version_state_time", "version_id", "sequence"),
    )

    state_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentWorkflowBinding(Base):
    __tablename__ = "bounded_agent_workflow_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_workflow_agent_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_bounded_agent_workflow_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "agent_version_id",
            "workflow_version_id",
            name="uq_bounded_agent_workflow_binding",
        ),
        CheckConstraint("ordinal >= 0 AND ordinal < 16", name="ck_bounded_agent_workflow_ordinal"),
        Index("ix_bounded_agent_workflow_order", "agent_version_id", "ordinal"),
    )

    binding_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentCapabilityRequirement(Base):
    __tablename__ = "bounded_agent_capability_requirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_capability_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "agent_version_id",
            "capability",
            "resource_kind",
            name="uq_bounded_agent_capability_requirement",
        ),
        CheckConstraint(
            "capability IN ('workspace.metadata.read', 'canvas.snapshot.read', "
            "'context.selected.read', 'document.version.read', 'trace.scoped.read', "
            "'retrieval.selected.search', 'draft.note.create', 'draft.answer.create', "
            "'canvas.note.create', 'canvas.note.update', 'canvas.note.create.rollback', "
            "'canvas.note.update.rollback', 'knowledge_graph.relationship.write', "
            "'workflow.step.execute', 'evidence.bundle.create', 'execution.cancel')",
            name="ck_bounded_agent_capability",
        ),
        CheckConstraint(
            "resource_kind IN ('workspace', 'canvas', 'node', 'document_version', "
            "'chunk', 'trace', 'canonical_relationship', 'canonical_object')",
            name="ck_bounded_agent_resource_kind",
        ),
        Index("ix_bounded_agent_capability_version", "agent_version_id"),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentValidationReport(Base):
    __tablename__ = "bounded_agent_validation_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_validation_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "agent_version_id",
            "content_digest",
            name="uq_bounded_agent_validation_digest",
        ),
        UniqueConstraint(
            "validation_id",
            "agent_version_id",
            name="uq_bounded_agent_validation_version",
        ),
        CheckConstraint(
            "outcome IN ('valid', 'invalid_schema', 'invalid_workflow', "
            "'invalid_capability', 'invalid_scope', 'invalid_provider', 'invalid_limits', "
            "'invalid_prompt_contract', 'invalid_communication_policy', "
            "'risk_exceeds_allowed_boundary', 'approval_required', 'unsupported_version')",
            name="ck_bounded_agent_validation_outcome",
        ),
        CheckConstraint("length(content_digest) = 64", name="ck_bounded_agent_validation_digest"),
        Index("ix_bounded_agent_validation_time", "agent_version_id", "created_at"),
    )

    validation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(48), nullable=False)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    registry_versions: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentActivationRequest(Base):
    __tablename__ = "bounded_agent_activation_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_activation_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["validation_id", "agent_version_id"],
            [
                "bounded_agent_validation_reports.validation_id",
                "bounded_agent_validation_reports.agent_version_id",
            ],
            name="fk_bounded_agent_activation_validation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "agent_version_id",
            "idempotency_key",
            name="uq_bounded_agent_activation_idempotency",
        ),
        UniqueConstraint(
            "activation_request_id",
            "agent_version_id",
            name="uq_bounded_agent_activation_version",
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_bounded_agent_activation_digest"),
        CheckConstraint("expires_at > created_at", name="ck_bounded_agent_activation_expiry"),
        Index("ix_bounded_agent_activation_time", "agent_version_id", "created_at"),
    )

    activation_request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    validation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentActivationDecision(Base):
    __tablename__ = "bounded_agent_activation_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activation_request_id", "agent_version_id"],
            [
                "bounded_agent_activation_requests.activation_request_id",
                "bounded_agent_activation_requests.agent_version_id",
            ],
            name="fk_bounded_agent_activation_decision_request",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "activation_request_id",
            name="uq_bounded_agent_activation_decision",
        ),
        CheckConstraint(
            "decision IN ('approved', 'denied')", name="ck_bounded_agent_activation_decision"
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_bounded_agent_decision_digest"),
        Index("ix_bounded_agent_activation_decision_time", "agent_version_id", "decided_at"),
    )

    activation_decision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    activation_request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentInvocation(Base):
    __tablename__ = "bounded_agent_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "agent_version_id",
                "agent_id",
                "definition_owner_user_id",
                "workspace_id",
                "canvas_id",
            ],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.agent_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_invocation_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["invoking_membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_bounded_agent_invocation_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["authority_snapshot_id", "user_id", "invoking_membership_id", "workspace_id"],
            [
                "collaboration_authority_snapshots.snapshot_id",
                "collaboration_authority_snapshots.user_id",
                "collaboration_authority_snapshots.membership_id",
                "collaboration_authority_snapshots.workspace_id",
            ],
            name="fk_bounded_agent_invocation_authority_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workflow_execution_id",
                "workflow_version_id",
                "user_id",
                "invoking_membership_id",
                "workspace_id",
                "canvas_id",
            ],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.version_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.invoking_membership_id",
                "controlled_workflow_executions.workspace_id",
                "controlled_workflow_executions.canvas_id",
            ],
            name="fk_bounded_agent_invocation_workflow",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_agent_invocation_idempotency",
        ),
        UniqueConstraint(
            "invocation_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_invocation_scope",
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_bounded_agent_invocation_digest"),
        Index("ix_bounded_agent_invocation_time", "agent_id", "created_at"),
        Index(
            "ix_bounded_agent_invocation_invoker_authority",
            "workspace_id",
            "user_id",
            "invoking_membership_id",
            "authority_snapshot_id",
        ),
    )

    invocation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    definition_owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    invoking_membership_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    authority_snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_object_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    graph_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentProposal(Base):
    __tablename__ = "bounded_agent_proposals"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_agent_proposal_idempotency",
        ),
        UniqueConstraint(
            "proposal_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_proposal_scope",
        ),
        CheckConstraint(
            "kind IN ('agent_creation', 'agent_version_improvement', 'workflow_binding', "
            "'capability_requirement', 'provider_policy', 'communication_revision', "
            "'evaluation_recommendation')",
            name="ck_bounded_agent_proposal_kind",
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_bounded_agent_proposal_request"),
        CheckConstraint("length(payload_digest) = 64", name="ck_bounded_agent_proposal_payload"),
        Index(
            "ix_bounded_agent_proposal_time", "user_id", "workspace_id", "canvas_id", "created_at"
        ),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bounded_agent_identities.agent_id", ondelete="RESTRICT")
    )
    source_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bounded_agent_invocations.invocation_id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentProposalDecision(Base):
    __tablename__ = "bounded_agent_proposal_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["proposal_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_proposals.proposal_id",
                "bounded_agent_proposals.user_id",
                "bounded_agent_proposals.workspace_id",
                "bounded_agent_proposals.canvas_id",
            ],
            name="fk_bounded_agent_proposal_decision_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("proposal_id", name="uq_bounded_agent_proposal_decision"),
        CheckConstraint(
            "decision IN ('accepted', 'rejected')", name="ck_bounded_agent_proposal_decision"
        ),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resulting_agent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    resulting_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedAgentEvaluation(Base):
    __tablename__ = "bounded_agent_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invocation_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_invocations.invocation_id",
                "bounded_agent_invocations.user_id",
                "bounded_agent_invocations.workspace_id",
                "bounded_agent_invocations.canvas_id",
            ],
            name="fk_bounded_agent_evaluation_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "invocation_id",
            "idempotency_key",
            name="uq_bounded_agent_evaluation_idempotency",
        ),
        CheckConstraint(
            "outcome IN ('meets_requirements', 'partially_meets_requirements', "
            "'fails_requirements', 'unsafe_result', 'insufficient_evidence', "
            "'bounded_result', 'evaluation_unavailable')",
            name="ck_bounded_agent_evaluation_outcome",
        ),
        CheckConstraint("length(evidence_digest) = 64", name="ck_bounded_agent_evaluation_digest"),
        Index("ix_bounded_agent_evaluation_time", "invocation_id", "created_at"),
    )

    evaluation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    outcome: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    recommendations: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedCommunicationProfile(Base):
    __tablename__ = "bounded_communication_profiles"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_communication_profile_scope",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_communication_profile_idempotency",
        ),
        CheckConstraint("length(request_digest) = 64", name="ck_bounded_profile_request_digest"),
        Index(
            "ix_bounded_communication_profile_time",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedCommunicationProfileVersion(Base):
    __tablename__ = "bounded_communication_profile_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_communication_profiles.profile_id",
                "bounded_communication_profiles.user_id",
                "bounded_communication_profiles.workspace_id",
                "bounded_communication_profiles.canvas_id",
            ],
            name="fk_bounded_profile_version_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("profile_id", "version_number", name="uq_bounded_profile_version_number"),
        UniqueConstraint(
            "profile_id",
            "idempotency_key",
            name="uq_bounded_profile_version_idempotency",
        ),
        UniqueConstraint(
            "profile_version_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_profile_version_scope",
        ),
        CheckConstraint(
            "audience IN ('general', 'executive', 'technical', 'academic')",
            name="ck_bounded_profile_audience",
        ),
        CheckConstraint(
            "reading_level IN ('plain', 'standard', 'advanced')",
            name="ck_bounded_profile_reading_level",
        ),
        CheckConstraint(
            "formality IN ('conversational', 'neutral', 'formal')",
            name="ck_bounded_profile_formality",
        ),
        CheckConstraint(
            "verbosity IN ('concise', 'balanced', 'detailed')",
            name="ck_bounded_profile_verbosity",
        ),
        CheckConstraint(
            "technical_depth IN ('low', 'medium', 'high')",
            name="ck_bounded_profile_technical_depth",
        ),
        CheckConstraint("length(content_digest) = 64", name="ck_bounded_profile_digest"),
    )

    profile_version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    reading_level: Mapped[str] = mapped_column(String(24), nullable=False)
    formality: Mapped[str] = mapped_column(String(24), nullable=False)
    verbosity: Mapped[str] = mapped_column(String(24), nullable=False)
    technical_depth: Mapped[str] = mapped_column(String(24), nullable=False)
    orwell_rules: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedCommunicationRevision(Base):
    __tablename__ = "bounded_communication_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_communication_profile_versions.profile_version_id",
                "bounded_communication_profile_versions.user_id",
                "bounded_communication_profile_versions.workspace_id",
                "bounded_communication_profile_versions.canvas_id",
            ],
            name="fk_bounded_revision_profile_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_communication_revision_idempotency",
        ),
        CheckConstraint(
            "preservation_status IN ('preserved', 'rejected')",
            name="ck_bounded_communication_preservation",
        ),
        CheckConstraint("length(original_digest) = 64", name="ck_bounded_revision_original_digest"),
        CheckConstraint("length(revised_digest) = 64", name="ck_bounded_revision_revised_digest"),
        CheckConstraint(
            "length(protected_facts_digest) = 64", name="ck_bounded_revision_facts_digest"
        ),
        Index(
            "ix_bounded_communication_revision_time",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bounded_agent_invocations.invocation_id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    revised_text: Mapped[str] = mapped_column(Text, nullable=False)
    original_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    revised_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    protected_facts: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    protected_facts_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    preservation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_failure_code: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundedCommunicationRevisionDecision(Base):
    __tablename__ = "bounded_communication_revision_decisions"
    __table_args__ = (
        UniqueConstraint("revision_id", name="uq_bounded_communication_revision_decision"),
        CheckConstraint(
            "decision IN ('accepted', 'rejected')", name="ck_bounded_revision_decision"
        ),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bounded_communication_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentExecution(Base):
    """Immutable authority identity plus server-owned bounded reliability state."""

    __tablename__ = "controlled_agent_executions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", "workspace_id", name="uq_agent_execution_scope"),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_execution_schema"),
        CheckConstraint(
            "role IN ('universe_coordinator', 'galaxy_analyst', "
            "'solar_system_researcher', 'planet_specialist', 'evidence_verifier', "
            "'drafting_assistant', 'controlled_action_executor')",
            name="ck_agent_execution_role",
        ),
        CheckConstraint(
            "deadline_at > created_at",
            name="ck_agent_execution_deadline_after_creation",
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="ck_agent_execution_max_attempts_positive",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_agent_execution_attempt_count_bounded",
        ),
        CheckConstraint(
            "next_retry_at IS NULL OR next_retry_at <= deadline_at",
            name="ck_agent_execution_retry_before_deadline",
        ),
        CheckConstraint(
            "(lease_owner_id IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner_id IS NOT NULL AND length(lease_owner_id) > 0 "
            "AND lease_acquired_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > lease_acquired_at "
            "AND lease_expires_at <= deadline_at)",
            name="ck_agent_execution_lease_shape",
        ),
        CheckConstraint(
            "lease_generation >= 0",
            name="ck_agent_execution_lease_generation_nonnegative",
        ),
        CheckConstraint(
            "(completed_at IS NULL AND terminal_outcome IS NULL "
            "AND failure_classification IS NULL) OR "
            "(completed_at IS NOT NULL AND terminal_outcome IS NOT NULL "
            "AND terminal_outcome IN ('succeeded', 'failed', 'cancelled', 'denied') "
            "AND lease_owner_id IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL AND next_retry_at IS NULL)",
            name="ck_agent_execution_terminal_shape",
        ),
        CheckConstraint(
            "terminal_outcome IS NULL OR "
            "(terminal_outcome = 'succeeded' AND failure_classification IS NULL) OR "
            "(terminal_outcome IN ('failed', 'cancelled', 'denied') "
            "AND failure_classification IS NOT NULL "
            "AND length(failure_classification) > 0)",
            name="ck_agent_execution_terminal_classification",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_agent_execution_completion_after_creation",
        ),
        Index("ix_agent_execution_owner_created", "user_id", "workspace_id", "created_at"),
        Index(
            "ix_agent_execution_claimable",
            "deadline_at",
            "next_retry_at",
            "attempt_count",
        ),
        Index("ix_agent_execution_lease_expiry", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    context_snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner_id: Mapped[str | None] = mapped_column(String(128))
    lease_acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_outcome: Mapped[str | None] = mapped_column(String(24))
    failure_classification: Mapped[str | None] = mapped_column(String(64))


class ControlledAgentExecutionState(Base):
    __tablename__ = "controlled_agent_execution_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_state_execution_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_state_schema"),
        CheckConstraint(
            "status IN ('proposed', 'awaiting_approval', 'ready', 'running', 'succeeded', "
            "'failed', 'cancelled', 'denied')",
            name="ck_agent_state_status",
        ),
        Index("ix_agent_state_execution_time", "execution_id", "recorded_at", "state_id"),
    )

    state_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    safe_reason_code: Mapped[str | None] = mapped_column(String(64))


class ControlledAgentStateTransition(Base):
    """Append-only compare-and-set evidence for one validated lifecycle transition."""

    __tablename__ = "controlled_agent_state_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_transition_execution_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["state_id"],
            ["controlled_agent_execution_states.state_id"],
            name="fk_agent_transition_state",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_state_id"],
            ["controlled_agent_execution_states.state_id"],
            name="fk_agent_transition_previous_state",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("state_id", name="uq_agent_transition_state"),
        UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_agent_transition_execution_sequence",
        ),
        UniqueConstraint(
            "execution_id",
            "predecessor_token",
            name="uq_agent_transition_execution_predecessor",
        ),
        CheckConstraint(
            "schema_version = 'controlled-agent-v1'",
            name="ck_agent_transition_schema",
        ),
        CheckConstraint("sequence >= 0", name="ck_agent_transition_sequence"),
        Index("ix_agent_transition_execution_sequence", "execution_id", "sequence"),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    state_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    previous_state_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    predecessor_token: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentContextSnapshot(Base):
    __tablename__ = "controlled_agent_context_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_context_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_agent_context_execution"),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_context_schema"),
        Index("ix_agent_context_owner_execution", "user_id", "workspace_id", "execution_id"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentPlanSnapshot(Base):
    __tablename__ = "controlled_agent_plan_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_plan_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_agent_plan_execution"),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_plan_schema"),
        Index("ix_agent_plan_owner_execution", "user_id", "workspace_id", "execution_id"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentCapabilityGrant(Base):
    __tablename__ = "controlled_agent_capability_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_grant_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_agent_grant_execution"),
        UniqueConstraint(
            "grant_id", "execution_id", "user_id", "workspace_id", name="uq_agent_grant_scope"
        ),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_grant_schema"),
        CheckConstraint("expires_at > issued_at", name="ck_agent_grant_time_order"),
        CheckConstraint(
            "(approval_required = false AND approval_id IS NULL) OR "
            "(approval_required = true AND approval_id IS NOT NULL)",
            name="ck_agent_grant_approval_binding",
        ),
        Index("ix_agent_grant_owner_execution", "user_id", "workspace_id", "execution_id"),
        Index("ix_agent_grant_expiry", "expires_at"),
    )

    grant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column()


class ControlledAgentGrantRevocation(Base):
    __tablename__ = "controlled_agent_grant_revocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["grant_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_capability_grants.grant_id",
                "controlled_agent_capability_grants.execution_id",
                "controlled_agent_capability_grants.user_id",
                "controlled_agent_capability_grants.workspace_id",
            ],
            name="fk_agent_revocation_grant_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("grant_id", name="uq_agent_revocation_grant"),
        CheckConstraint(
            "schema_version = 'controlled-agent-v1'", name="ck_agent_revocation_schema"
        ),
        Index("ix_agent_revocation_owner_execution", "user_id", "workspace_id", "execution_id"),
    )

    revocation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ControlledAgentApproval(Base):
    __tablename__ = "controlled_agent_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["grant_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_capability_grants.grant_id",
                "controlled_agent_capability_grants.execution_id",
                "controlled_agent_capability_grants.user_id",
                "controlled_agent_capability_grants.workspace_id",
            ],
            name="fk_agent_approval_grant_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "approval_id",
            "execution_id",
            "user_id",
            "workspace_id",
            name="uq_agent_approval_scope",
        ),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_approval_schema"),
        CheckConstraint("decision IN ('approved', 'denied')", name="ck_agent_approval_decision"),
        CheckConstraint("expires_at > decided_at", name="ck_agent_approval_time_order"),
        Index("ix_agent_approval_owner_execution", "user_id", "workspace_id", "execution_id"),
        Index("ix_agent_approval_expiry", "expires_at"),
    )

    approval_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentPolicyDecision(Base):
    __tablename__ = "controlled_agent_policy_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_policy_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "decision_id",
            "execution_id",
            "user_id",
            "workspace_id",
            name="uq_agent_policy_scope",
        ),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_policy_schema"),
        CheckConstraint(
            "outcome IN ('allow', 'deny', 'approval_required')", name="ck_agent_policy_outcome"
        ),
        Index("ix_agent_policy_execution_time", "execution_id", "evaluated_at", "decision_id"),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grant_id: Mapped[uuid.UUID | None] = mapped_column()
    approval_id: Mapped[uuid.UUID | None] = mapped_column()
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class ControlledAgentApprovalConsumption(Base):
    __tablename__ = "controlled_agent_approval_consumptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["approval_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_approvals.approval_id",
                "controlled_agent_approvals.execution_id",
                "controlled_agent_approvals.user_id",
                "controlled_agent_approvals.workspace_id",
            ],
            name="fk_agent_consumption_approval_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["policy_decision_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_policy_decisions.decision_id",
                "controlled_agent_policy_decisions.execution_id",
                "controlled_agent_policy_decisions.user_id",
                "controlled_agent_policy_decisions.workspace_id",
            ],
            name="fk_agent_consumption_policy_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("approval_id", name="uq_agent_consumption_approval"),
        CheckConstraint(
            "schema_version = 'controlled-agent-v1'", name="ck_agent_consumption_schema"
        ),
        Index("ix_agent_consumption_owner_execution", "user_id", "workspace_id", "execution_id"),
    )

    consumption_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    policy_decision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentAuditEvent(Base):
    __tablename__ = "controlled_agent_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_audit_execution_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("schema_version = 'controlled-agent-v1'", name="ck_agent_audit_schema"),
        Index("ix_agent_audit_execution_time", "execution_id", "recorded_at", "event_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)


class ControlledAgentRequestIdentity(Base):
    """Append-only database identity for one scoped logical execution request."""

    __tablename__ = "controlled_agent_request_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_request_execution_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            "idempotency_key",
            name="uq_agent_request_idempotency_scope",
        ),
        CheckConstraint(
            "action = 'generate_grounded_draft'", name="ck_agent_request_closed_action"
        ),
        Index("ix_agent_request_execution", "execution_id"),
    )

    request_identity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvases.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    client_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentReversibleWriteProposal(Base):
    """Immutable review-only proposal; this table does not represent an applied effect."""

    __tablename__ = "controlled_agent_reversible_write_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_reversible_proposal_execution_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["canvas_id"],
            ["canvases.id"],
            name="fk_agent_reversible_proposal_canvas",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_agent_reversible_proposal_execution"),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            "idempotency_key",
            name="uq_agent_reversible_proposal_idempotency",
        ),
        CheckConstraint(
            "action IN ('note.create', 'note.update')",
            name="ck_agent_reversible_proposal_action",
        ),
        CheckConstraint("expires_at > created_at", name="ck_agent_reversible_proposal_time_order"),
        Index(
            "ix_agent_reversible_proposal_scope",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
        Index(
            "ux_agent_reversible_proposal_effect_scope",
            "proposal_id",
            "execution_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            unique=True,
        ),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentReversibleWriteEffect(Base):
    """Immutable authoritative result for one accepted reversible note effect."""

    __tablename__ = "controlled_agent_reversible_write_effects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_reversible_effect_execution_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proposal_id", "execution_id", "user_id", "workspace_id", "canvas_id", "action"],
            [
                "controlled_agent_reversible_write_proposals.proposal_id",
                "controlled_agent_reversible_write_proposals.execution_id",
                "controlled_agent_reversible_write_proposals.user_id",
                "controlled_agent_reversible_write_proposals.workspace_id",
                "controlled_agent_reversible_write_proposals.canvas_id",
                "controlled_agent_reversible_write_proposals.action",
            ],
            name="fk_agent_reversible_effect_proposal",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["approval_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_approvals.approval_id",
                "controlled_agent_approvals.execution_id",
                "controlled_agent_approvals.user_id",
                "controlled_agent_approvals.workspace_id",
            ],
            name="fk_agent_reversible_effect_approval_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["canvas_id"],
            ["canvases.id"],
            name="fk_agent_reversible_effect_canvas",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_agent_reversible_effect_execution"),
        UniqueConstraint("proposal_id", name="uq_agent_reversible_effect_proposal"),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_agent_reversible_effect_idempotency",
        ),
        CheckConstraint(
            "action IN ('note.create', 'note.update')", name="ck_agent_reversible_effect_action"
        ),
        CheckConstraint("outcome = 'succeeded'", name="ck_agent_reversible_effect_outcome"),
        CheckConstraint(
            "(action = 'note.create' AND resource_id IS NULL AND expected_revision IS NULL "
            "AND before_digest IS NULL) OR "
            "(action = 'note.update' AND resource_id IS NOT NULL AND expected_revision IS NOT NULL "
            "AND resulting_resource_id = resource_id AND before_digest IS NOT NULL)",
            name="ck_agent_reversible_effect_resource_shape",
        ),
        Index("ix_agent_reversible_effect_proposal", "proposal_id"),
        Index(
            "ux_agent_reversible_effect_rollback_scope",
            "effect_id",
            "execution_id",
            "proposal_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            "resulting_resource_id",
            unique=True,
        ),
        Index(
            "ix_agent_reversible_effect_scope", "user_id", "workspace_id", "canvas_id", "created_at"
        ),
    )

    effect_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    resulting_resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resulting_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    before_digest: Mapped[str | None] = mapped_column(String(64))
    after_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentReversibleWriteRollbackEvidence(Base):
    """Immutable exact pre-update note state bound to one authoritative effect result."""

    __tablename__ = "controlled_agent_reversible_write_rollback_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "effect_id",
                "execution_id",
                "proposal_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "action",
                "note_id",
            ],
            [
                "controlled_agent_reversible_write_effects.effect_id",
                "controlled_agent_reversible_write_effects.execution_id",
                "controlled_agent_reversible_write_effects.proposal_id",
                "controlled_agent_reversible_write_effects.user_id",
                "controlled_agent_reversible_write_effects.workspace_id",
                "controlled_agent_reversible_write_effects.canvas_id",
                "controlled_agent_reversible_write_effects.action",
                "controlled_agent_reversible_write_effects.resulting_resource_id",
            ],
            name="fk_agent_rollback_evidence_effect_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["note_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_agent_rollback_evidence_note_canvas",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("effect_id", name="uq_agent_rollback_evidence_effect"),
        CheckConstraint("action = 'note.update'", name="ck_agent_rollback_evidence_action"),
        CheckConstraint(
            "post_effect_revision = pre_effect_revision + 1",
            name="ck_agent_rollback_evidence_revision_order",
        ),
        CheckConstraint(
            "json_type(before_state) = 'object'",
            name="ck_agent_rollback_evidence_before_state_object",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "json_typeof(before_state) = 'object'",
            name="ck_agent_rollback_evidence_before_state_object",
        ).ddl_if(dialect="postgresql"),
        Index("ix_agent_rollback_evidence_note", "note_id", "post_effect_revision"),
        Index(
            "ix_agent_rollback_evidence_scope",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
    )

    evidence_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    effect_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    pre_effect_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    post_effect_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    before_state: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    before_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    after_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentReversibleWriteRollbackApproval(Base):
    """Immutable, scoped approval contract for one exact reversible note rollback."""

    __tablename__ = "controlled_agent_reversible_write_rollback_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "proposal_id",
                "execution_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
            ],
            [
                "controlled_agent_reversible_write_proposals.proposal_id",
                "controlled_agent_reversible_write_proposals.execution_id",
                "controlled_agent_reversible_write_proposals.user_id",
                "controlled_agent_reversible_write_proposals.workspace_id",
                "controlled_agent_reversible_write_proposals.canvas_id",
                "controlled_agent_reversible_write_proposals.action",
            ],
            name="fk_agent_rollback_approval_proposal_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "effect_id",
                "execution_id",
                "proposal_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
                "note_id",
            ],
            [
                "controlled_agent_reversible_write_effects.effect_id",
                "controlled_agent_reversible_write_effects.execution_id",
                "controlled_agent_reversible_write_effects.proposal_id",
                "controlled_agent_reversible_write_effects.user_id",
                "controlled_agent_reversible_write_effects.workspace_id",
                "controlled_agent_reversible_write_effects.canvas_id",
                "controlled_agent_reversible_write_effects.action",
                "controlled_agent_reversible_write_effects.resulting_resource_id",
            ],
            name="fk_agent_rollback_approval_effect_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["grant_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_capability_grants.grant_id",
                "controlled_agent_capability_grants.execution_id",
                "controlled_agent_capability_grants.user_id",
                "controlled_agent_capability_grants.workspace_id",
            ],
            name="fk_agent_rollback_approval_grant_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "execution_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            "scoped_idempotency_key",
            name="uq_agent_rollback_approval_execution_scope_idempotency",
        ),
        CheckConstraint(
            "forward_action IN ('note.create', 'note.update')",
            name="ck_agent_rollback_approval_forward_action",
        ),
        CheckConstraint(
            "rollback_action IN ('note.create.rollback', 'note.update.rollback')",
            name="ck_agent_rollback_approval_action",
        ),
        CheckConstraint(
            "rollback_target_kind IN ('authoritative_absence', 'exact_prior_state')",
            name="ck_agent_rollback_approval_target_kind",
        ),
        CheckConstraint(
            "(forward_action = 'note.create' "
            "AND rollback_action = 'note.create.rollback' "
            "AND rollback_target_kind = 'authoritative_absence' "
            "AND rollback_evidence_id IS NULL) OR "
            "(forward_action = 'note.update' "
            "AND rollback_action = 'note.update.rollback' "
            "AND rollback_target_kind = 'exact_prior_state' "
            "AND rollback_evidence_id IS NOT NULL)",
            name="ck_agent_rollback_approval_action_shape",
        ),
        CheckConstraint(
            "(forward_action = 'note.create' "
            "AND rollback_action = 'note.create.rollback' "
            "AND expected_current_revision = 0) OR "
            "(forward_action = 'note.update' "
            "AND rollback_action = 'note.update.rollback' "
            "AND expected_current_revision > 0)",
            name="ck_agent_rollback_approval_expected_revision_action",
        ),
        CheckConstraint(
            "length(scoped_idempotency_key) > 0",
            name="ck_agent_rollback_approval_idempotency_nonempty",
        ),
        CheckConstraint("expires_at > created_at", name="ck_agent_rollback_approval_time_order"),
        CheckConstraint(
            "length(original_plan_digest) = 64 AND original_plan_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_approval_original_plan_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "original_plan_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_approval_original_plan_digest",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(effect_after_state_digest) = 64 "
            "AND effect_after_state_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_approval_effect_after_state_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "effect_after_state_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_approval_effect_after_state_digest",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(rollback_target_digest) = 64 AND rollback_target_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_approval_target_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "rollback_target_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_approval_target_digest",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(approval_digest) = 64 AND approval_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_approval_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "approval_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_approval_digest",
        ).ddl_if(dialect="postgresql"),
        Index("ix_agent_rollback_approval_effect", "effect_id"),
        Index(
            "ix_agent_rollback_approval_scope",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
        Index("ix_agent_rollback_approval_note", "note_id"),
        Index("ix_agent_rollback_approval_expiry", "expires_at"),
        Index("ix_agent_rollback_approval_evidence", "rollback_evidence_id"),
        Index(
            "ix_agent_rollback_approval_idempotency",
            "user_id",
            "workspace_id",
            "canvas_id",
            "scoped_idempotency_key",
        ),
        Index("ix_agent_rollback_approval_grant", "grant_id"),
    )

    rollback_approval_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    effect_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    forward_action: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_action: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "controlled_agent_reversible_write_rollback_evidence.evidence_id",
            ondelete="RESTRICT",
        )
    )
    original_plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_after_state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    rollback_target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scoped_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlledAgentReversibleWriteRollbackResult(Base):
    """Immutable authoritative result for one successfully applied note rollback."""

    __tablename__ = "controlled_agent_reversible_write_rollback_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["rollback_approval_id"],
            ["controlled_agent_reversible_write_rollback_approvals.rollback_approval_id"],
            name="fk_agent_rollback_result_approval",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "proposal_id",
                "execution_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
            ],
            [
                "controlled_agent_reversible_write_proposals.proposal_id",
                "controlled_agent_reversible_write_proposals.execution_id",
                "controlled_agent_reversible_write_proposals.user_id",
                "controlled_agent_reversible_write_proposals.workspace_id",
                "controlled_agent_reversible_write_proposals.canvas_id",
                "controlled_agent_reversible_write_proposals.action",
            ],
            name="fk_agent_rollback_result_proposal_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "effect_id",
                "execution_id",
                "proposal_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
                "note_id",
            ],
            [
                "controlled_agent_reversible_write_effects.effect_id",
                "controlled_agent_reversible_write_effects.execution_id",
                "controlled_agent_reversible_write_effects.proposal_id",
                "controlled_agent_reversible_write_effects.user_id",
                "controlled_agent_reversible_write_effects.workspace_id",
                "controlled_agent_reversible_write_effects.canvas_id",
                "controlled_agent_reversible_write_effects.action",
                "controlled_agent_reversible_write_effects.resulting_resource_id",
            ],
            name="fk_agent_rollback_result_effect_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("rollback_approval_id", name="uq_agent_rollback_result_approval"),
        UniqueConstraint("effect_id", name="uq_agent_rollback_result_effect"),
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "scoped_idempotency_key",
            name="uq_agent_rollback_result_idempotency",
        ),
        CheckConstraint(
            "forward_action IN ('note.create', 'note.update')",
            name="ck_agent_rollback_result_forward_action",
        ),
        CheckConstraint(
            "rollback_action IN ('note.create.rollback', 'note.update.rollback')",
            name="ck_agent_rollback_result_action",
        ),
        CheckConstraint(
            "rollback_target_kind IN ('authoritative_absence', 'exact_prior_state')",
            name="ck_agent_rollback_result_target_kind",
        ),
        CheckConstraint(
            "(forward_action = 'note.create' "
            "AND rollback_action = 'note.create.rollback' "
            "AND rollback_target_kind = 'authoritative_absence' "
            "AND resulting_revision IS NULL) OR "
            "(forward_action = 'note.update' "
            "AND rollback_action = 'note.update.rollback' "
            "AND rollback_target_kind = 'exact_prior_state' "
            "AND resulting_revision IS NOT NULL AND resulting_revision > 0)",
            name="ck_agent_rollback_result_action_shape",
        ),
        CheckConstraint(
            "(forward_action = 'note.create' "
            "AND rollback_action = 'note.create.rollback' "
            "AND expected_pre_rollback_revision = 0) OR "
            "(forward_action = 'note.update' "
            "AND rollback_action = 'note.update.rollback' "
            "AND expected_pre_rollback_revision > 0)",
            name="ck_agent_rollback_result_expected_revision_action",
        ),
        CheckConstraint(
            "length(scoped_idempotency_key) > 0",
            name="ck_agent_rollback_result_idempotency_nonempty",
        ),
        CheckConstraint(
            "length(rollback_approval_digest) = 64 "
            "AND rollback_approval_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_result_approval_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "rollback_approval_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_result_approval_digest",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(pre_rollback_state_digest) = 64 "
            "AND pre_rollback_state_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_result_pre_rollback_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "pre_rollback_state_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_result_pre_rollback_digest",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "length(post_rollback_target_digest) = 64 "
            "AND post_rollback_target_digest NOT GLOB '*[^0-9a-f]*'",
            name="ck_agent_rollback_result_post_rollback_digest",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "post_rollback_target_digest ~ '^[0-9a-f]{64}$'",
            name="ck_agent_rollback_result_post_rollback_digest",
        ).ddl_if(dialect="postgresql"),
        Index("ix_agent_rollback_result_approval", "rollback_approval_id"),
        Index("ix_agent_rollback_result_effect", "effect_id"),
        Index(
            "ix_agent_rollback_result_idempotency",
            "user_id",
            "workspace_id",
            "canvas_id",
            "scoped_idempotency_key",
        ),
        Index(
            "ix_agent_rollback_result_scope",
            "user_id",
            "workspace_id",
            "canvas_id",
            "created_at",
        ),
        Index("ix_agent_rollback_result_note", "note_id"),
    )

    rollback_result_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    rollback_approval_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    canvas_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    effect_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    forward_action: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_action: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_approval_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scoped_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_pre_rollback_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_revision: Mapped[int | None] = mapped_column(Integer)
    pre_rollback_state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    post_rollback_target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


CONTROLLED_AGENT_IMMUTABLE_MODELS = (
    ControlledAgentExecutionState,
    ControlledAgentStateTransition,
    ControlledAgentContextSnapshot,
    ControlledAgentPlanSnapshot,
    ControlledAgentCapabilityGrant,
    ControlledAgentGrantRevocation,
    ControlledAgentApproval,
    ControlledAgentPolicyDecision,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentRequestIdentity,
    ControlledAgentReversibleWriteProposal,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteRollbackEvidence,
    ControlledAgentReversibleWriteRollbackApproval,
    ControlledAgentReversibleWriteRollbackResult,
)

KNOWLEDGE_GRAPH_IMMUTABLE_MODELS = (
    CanonicalGraphEntity,
    CanonicalCanvasObjectBinding,
    CanonicalGraphRelationship,
    CanonicalRelationshipProvenance,
    CanonicalRelationshipHistory,
)

DOMAIN_EVENT_IMMUTABLE_MODELS = (
    DomainEventRecord,
    DomainEventProvenance,
    DomainEventDeliveryAttempt,
    DomainActivityEntry,
)

GRAPH_RETRIEVAL_IMMUTABLE_MODELS = (
    GraphRetrievalRun,
    GraphRetrievalDecision,
    GraphRetrievalCitation,
    TraceEvidenceBundle,
)

CONTROLLED_WORKFLOW_IMMUTABLE_MODELS = (
    ControlledWorkflowDefinition,
    ControlledWorkflowVersion,
    ControlledWorkflowVersionState,
    ControlledWorkflowStep,
    ControlledWorkflowDependency,
    ControlledWorkflowPlanSnapshot,
    ControlledWorkflowExecutionTransition,
    ControlledWorkflowStepTransition,
    ControlledWorkflowStepAttempt,
    ControlledWorkflowEvidenceLink,
)

BOUNDED_AGENT_STUDIO_IMMUTABLE_MODELS = (
    BoundedAgentIdentity,
    BoundedAgentLifecycleState,
    BoundedAgentVersion,
    BoundedAgentVersionState,
    BoundedAgentWorkflowBinding,
    BoundedAgentCapabilityRequirement,
    BoundedAgentValidationReport,
    BoundedAgentActivationRequest,
    BoundedAgentActivationDecision,
    BoundedAgentInvocation,
    BoundedAgentProposal,
    BoundedAgentProposalDecision,
    BoundedAgentEvaluation,
    BoundedCommunicationProfile,
    BoundedCommunicationProfileVersion,
    BoundedCommunicationRevision,
    BoundedCommunicationRevisionDecision,
)

COLLABORATION_IMMUTABLE_MODELS = (
    WorkspaceMembership,
    WorkspaceMembershipTransition,
    WorkspaceInvitation,
    WorkspaceInvitationTransition,
    WorkspaceInvitationSecretVersion,
    WorkspaceInvitationDeliveryAttempt,
    CollaborationRequestIdentity,
    CollaborationAuditEvent,
    CollaborationApprovalAuthorityAssignment,
    CollaborationApprovalAuthorityTransition,
    CollaborationReviewerEligibilityEvidence,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
    CollaborationResourceShare,
    CollaborationResourceShareTransition,
    CollaborationOwnershipTransfer,
    CollaborationOwnershipTransferTransition,
    CollaborationAuthoritySnapshot,
    CollaborationRevocationFence,
    CollaborationCommentThread,
    CollaborationCommentThreadTransition,
    CollaborationComment,
    CollaborationCommentRevision,
    CollaborationCommentTransition,
)

INDEXER_IMMUTABLE_MODELS = (
    PipelineManifest,
    IngestionRequest,
    IngestionRequestTransition,
    NormalizedArtifact,
    IndexCompatibilityProjection,
    IndexRevision,
    IndexRevisionChunk,
    VectorMaterialization,
    IndexPublication,
    IndexerAuditEvent,
    IndexerFailure,
)


def _reject_controlled_agent_mutation(_mapper: Any, _connection: Any, target: object) -> None:
    raise ValueError(f"{type(target).__name__} records are append-only")


def _reject_execution_authority_mutation(_mapper: Any, _connection: Any, target: object) -> None:
    state = sa_inspect(target)
    if state is None:
        raise ValueError("ControlledAgentExecution state is unavailable")
    immutable_fields = (
        "id",
        "user_id",
        "workspace_id",
        "schema_version",
        "role",
        "context_snapshot_id",
        "context_digest",
        "plan_id",
        "plan_digest",
        "grant_id",
        "created_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("ControlledAgentExecution authority fields are immutable")


def _reject_outbox_identity_mutation(_mapper: Any, _connection: Any, target: object) -> None:
    state = sa_inspect(target)
    if state is None:
        raise ValueError("DomainEventOutbox state is unavailable")
    immutable_fields = (
        "outbox_id",
        "event_id",
        "user_id",
        "workspace_id",
        "max_attempts",
        "created_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("DomainEventOutbox identity and scope fields are immutable")


def _reject_workflow_execution_identity_mutation(
    _mapper: Any, _connection: Any, target: object
) -> None:
    state = sa_inspect(target)
    if state is None:
        raise ValueError("ControlledWorkflowExecution state is unavailable")
    immutable_fields = (
        "execution_id",
        "definition_id",
        "version_id",
        "definition_owner_user_id",
        "user_id",
        "invoking_membership_id",
        "workspace_id",
        "canvas_id",
        "idempotency_key",
        "request_digest",
        "plan_id",
        "plan_digest",
        "input_digest",
        "normalized_input",
        "selected_object_ids",
        "graph_revision",
        "trace_id",
        "created_at",
        "deadline_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("ControlledWorkflowExecution identity and authority are immutable")
    snapshot_history = state.attrs.authority_snapshot_id.history
    if snapshot_history.has_changes() and any(
        value is not None for value in snapshot_history.deleted
    ):
        raise ValueError("ControlledWorkflowExecution authority snapshot is immutable")


def _reject_workflow_step_identity_mutation(_mapper: Any, _connection: Any, target: object) -> None:
    state = sa_inspect(target)
    if state is None:
        raise ValueError("ControlledWorkflowStepExecution state is unavailable")
    immutable_fields = (
        "step_execution_id",
        "workflow_execution_id",
        "step_definition_id",
        "user_id",
        "workspace_id",
        "max_attempts",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("ControlledWorkflowStepExecution identity and bounds are immutable")


event.listen(
    ControlledAgentExecution,
    "before_update",
    _reject_execution_authority_mutation,
)
event.listen(
    ControlledAgentExecution,
    "before_delete",
    _reject_controlled_agent_mutation,
)


for _immutable_model in CONTROLLED_AGENT_IMMUTABLE_MODELS:
    event.listen(_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _graph_immutable_model in KNOWLEDGE_GRAPH_IMMUTABLE_MODELS:
    event.listen(_graph_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_graph_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _domain_event_immutable_model in DOMAIN_EVENT_IMMUTABLE_MODELS:
    event.listen(_domain_event_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_domain_event_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _retrieval_immutable_model in GRAPH_RETRIEVAL_IMMUTABLE_MODELS:
    event.listen(_retrieval_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_retrieval_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _workflow_immutable_model in CONTROLLED_WORKFLOW_IMMUTABLE_MODELS:
    event.listen(_workflow_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_workflow_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _agent_studio_immutable_model in BOUNDED_AGENT_STUDIO_IMMUTABLE_MODELS:
    event.listen(_agent_studio_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_agent_studio_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _collaboration_immutable_model in COLLABORATION_IMMUTABLE_MODELS:
    event.listen(_collaboration_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_collaboration_immutable_model, "before_delete", _reject_controlled_agent_mutation)

for _indexer_immutable_model in INDEXER_IMMUTABLE_MODELS:
    event.listen(_indexer_immutable_model, "before_update", _reject_controlled_agent_mutation)
    event.listen(_indexer_immutable_model, "before_delete", _reject_controlled_agent_mutation)

event.listen(
    ControlledWorkflowExecution,
    "before_update",
    _reject_workflow_execution_identity_mutation,
)
event.listen(
    ControlledWorkflowExecution,
    "before_delete",
    _reject_controlled_agent_mutation,
)
event.listen(
    ControlledWorkflowStepExecution,
    "before_update",
    _reject_workflow_step_identity_mutation,
)
event.listen(
    ControlledWorkflowStepExecution,
    "before_delete",
    _reject_controlled_agent_mutation,
)

event.listen(DomainEventOutbox, "before_delete", _reject_controlled_agent_mutation)
event.listen(DomainEventOutbox, "before_update", _reject_outbox_identity_mutation)
