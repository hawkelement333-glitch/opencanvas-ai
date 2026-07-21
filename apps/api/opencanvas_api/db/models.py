from __future__ import annotations

import uuid
from datetime import datetime

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
    String,
    Text,
    UniqueConstraint,
    func,
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
    selected_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    node_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )


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
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
        CheckConstraint(
            "relationship_type IN "
            "('contains', 'part_of', 'references', 'derived_from', 'related_to')",
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
