"""Add document ingestion, retrieval, and grounded-source persistence.

Revision ID: 20260717_0002
Revises: 20260716_0001
Create Date: 2026-07-17
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260717_0002"
down_revision: str | None = "20260716_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _replace_phase_one_checks(*, upgrade: bool) -> None:
    node_expression = (
        "type IN ('note', 'ai_response', 'document')"
        if upgrade
        else "type IN ('note', 'ai_response')"
    )
    edge_expression = (
        "kind IN ('default', 'generated_from', 'cites')"
        if upgrade
        else "kind IN ('default', 'generated_from')"
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("nodes", recreate="always") as batch:
            batch.drop_constraint("ck_nodes_type", type_="check")
            batch.create_check_constraint("ck_nodes_type", node_expression)
        with op.batch_alter_table("edges", recreate="always") as batch:
            batch.drop_constraint("ck_edges_kind", type_="check")
            batch.create_check_constraint("ck_edges_kind", edge_expression)
        return

    op.drop_constraint("ck_nodes_type", "nodes", type_="check")
    op.create_check_constraint("ck_nodes_type", "nodes", node_expression)
    op.drop_constraint("ck_edges_kind", "edges", type_="check")
    op.create_check_constraint("ck_edges_kind", "edges", edge_expression)


def _replace_ai_response_node_fk(*, upgrade: bool) -> None:
    """Keep response outcomes when their generated canvas node is deleted."""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        naming_convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
        existing_name = (
            "fk_ai_responses_node_preserve" if not upgrade else "fk_ai_responses_node_id_nodes"
        )
        replacement_name = (
            "fk_ai_responses_node_preserve" if upgrade else "fk_ai_responses_node_id_nodes"
        )
        with op.batch_alter_table(
            "ai_responses", recreate="always", naming_convention=naming_convention
        ) as batch:
            batch.drop_constraint(existing_name, type_="foreignkey")
            batch.alter_column(
                "node_id", existing_type=sa.Uuid(), nullable=upgrade, existing_nullable=not upgrade
            )
            batch.create_foreign_key(
                replacement_name,
                "nodes",
                ["node_id"],
                ["id"],
                ondelete="SET NULL" if upgrade else "CASCADE",
            )
        return

    existing_name = "fk_ai_responses_node_preserve" if not upgrade else "ai_responses_node_id_fkey"
    replacement_name = "fk_ai_responses_node_preserve" if upgrade else "ai_responses_node_id_fkey"
    op.drop_constraint(existing_name, "ai_responses", type_="foreignkey")
    op.alter_column(
        "ai_responses",
        "node_id",
        existing_type=sa.Uuid(),
        nullable=upgrade,
        existing_nullable=not upgrade,
    )
    op.create_foreign_key(
        replacement_name,
        "ai_responses",
        "nodes",
        ["node_id"],
        ["id"],
        ondelete="SET NULL" if upgrade else "CASCADE",
    )


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    _replace_phase_one_checks(upgrade=True)
    _replace_ai_response_node_fk(upgrade=True)
    op.add_column(
        "ai_requests",
        sa.Column("model_configuration", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "ai_requests",
        sa.Column("retrieval_configuration", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "ai_requests",
        sa.Column(
            "prompt_version", sa.String(length=64), server_default="canvas-v1", nullable=False
        ),
    )
    op.add_column(
        "ai_responses",
        sa.Column("grounded", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "ai_responses",
        sa.Column("insufficient_evidence", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("ai_responses", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_responses", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_responses", sa.Column("total_tokens", sa.Integer(), nullable=True))

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="processing", nullable=False),
        sa.Column(
            "processing_stage", sa.String(length=24), server_default="uploading", nullable=False
        ),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'failed')", name="ck_documents_status"
        ),
        sa.CheckConstraint(
            "processing_stage IN "
            "('uploading', 'extracting', 'chunking', 'embedding', 'ready', 'failed')",
            name="ck_documents_processing_stage",
        ),
        sa.CheckConstraint("file_size_bytes >= 0", name="ck_documents_file_size_nonnegative"),
        sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_documents_page_count"),
        sa.CheckConstraint("chunk_count >= 0", name="ck_documents_chunk_count_nonnegative"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "canvas_id", name="uq_documents_id_canvas"),
    )
    op.create_index("ix_documents_canvas_id", "documents", ["canvas_id"])
    op.create_index("ix_documents_canvas_status", "documents", ["canvas_id", "status"])

    op.create_table(
        "document_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("byte_size >= 0", name="ck_document_files_byte_size_nonnegative"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
        sa.UniqueConstraint("storage_key"),
    )

    op.create_table(
        "canvas_document_nodes",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["node_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_canvas_document_nodes_node_same_canvas",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "canvas_id"],
            ["documents.id", "documents.canvas_id"],
            name="fk_canvas_document_nodes_document_same_canvas",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("node_id"),
    )
    op.create_index("ix_canvas_document_nodes_canvas_id", "canvas_document_nodes", ["canvas_id"])
    op.create_index(
        "ix_canvas_document_nodes_document_id", "canvas_document_nodes", ["document_id"]
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonnegative"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0", name="ck_document_chunks_page_number"
        ),
        sa.CheckConstraint("char_start >= 0", name="ck_document_chunks_char_start_nonnegative"),
        sa.CheckConstraint("char_end > char_start", name="ck_document_chunks_char_range"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "document_id", name="uq_document_chunks_id_document"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_index"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    embedding_type: sa.types.TypeEngine[object]
    embedding_type = Vector(1536) if is_postgresql else sa.JSON()
    op.create_table(
        "document_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("dimensions", sa.Integer(), server_default="1536", nullable=False),
        sa.Column("embedding", embedding_type, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("dimensions = 1536", name="ck_document_embeddings_dimensions"),
        sa.ForeignKeyConstraint(
            ["chunk_id", "document_id"],
            ["document_chunks.id", "document_chunks.document_id"],
            name="fk_document_embeddings_chunk_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id"),
    )
    op.create_index("ix_document_embeddings_document_id", "document_embeddings", ["document_id"])
    if is_postgresql:
        op.create_index(
            "ix_document_embeddings_embedding_hnsw",
            "document_embeddings",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    op.create_table(
        "document_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="uploading", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("attempt > 0", name="ck_document_processing_jobs_attempt_positive"),
        sa.CheckConstraint(
            "status IN ('uploading', 'extracting', 'chunking', 'embedding', 'ready', 'failed')",
            name="ck_document_processing_jobs_status",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "attempt", name="uq_document_processing_jobs_attempt"),
    )
    op.create_index(
        "ix_document_processing_jobs_document_id",
        "document_processing_jobs",
        ["document_id"],
    )

    op.create_table(
        "citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ai_response_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("identifier", sa.String(length=48), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ordinal > 0", name="ck_citations_ordinal_positive"),
        sa.ForeignKeyConstraint(["ai_response_id"], ["ai_responses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["chunk_id", "document_id"],
            ["document_chunks.id", "document_chunks.document_id"],
            name="fk_citations_chunk_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ai_response_id", "identifier", name="uq_citations_response_identifier"
        ),
    )
    op.create_index("ix_citations_ai_response_id", "citations", ["ai_response_id"])
    op.create_index("ix_citations_document_id", "citations", ["document_id"])
    op.create_index("ix_citations_chunk_id", "citations", ["chunk_id"])

    op.create_table(
        "ai_response_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ai_response_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_node_id", sa.Uuid(), nullable=True),
        sa.Column("max_relevance_score", sa.Float(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "max_relevance_score >= -1 AND max_relevance_score <= 1",
            name="ck_ai_response_sources_score",
        ),
        sa.ForeignKeyConstraint(["ai_response_id"], ["ai_responses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_node_id"], ["nodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ai_response_id", "document_id", name="uq_ai_response_sources_response_document"
        ),
    )
    op.create_index(
        "ix_ai_response_sources_ai_response_id", "ai_response_sources", ["ai_response_id"]
    )
    op.create_index("ix_ai_response_sources_document_id", "ai_response_sources", ["document_id"])
    op.create_index(
        "ix_ai_response_sources_document_node_id", "ai_response_sources", ["document_node_id"]
    )

    op.create_table(
        "ai_execution_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("selected_order", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(length=24), nullable=False),
        sa.Column("node_revision", sa.Integer(), nullable=False),
        sa.Column("title_snapshot", sa.String(length=160), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("selected_order >= 0", name="ck_ai_execution_nodes_order_nonnegative"),
        sa.CheckConstraint("node_revision >= 0", name="ck_ai_execution_nodes_revision_nonnegative"),
        sa.ForeignKeyConstraint(["request_id"], ["ai_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "selected_order", name="uq_ai_execution_nodes_order"),
    )
    op.create_index("ix_ai_execution_nodes_request_id", "ai_execution_nodes", ["request_id"])
    op.create_index("ix_ai_execution_nodes_node_id", "ai_execution_nodes", ["node_id"])
    op.create_index("ix_ai_execution_nodes_document_id", "ai_execution_nodes", ["document_id"])

    op.create_table(
        "ai_execution_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("included_in_context", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=120), nullable=True),
        sa.Column("source_id_snapshot", sa.String(length=48), nullable=False),
        sa.Column("document_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column("page_number_snapshot", sa.Integer(), nullable=True),
        sa.Column("heading_snapshot", sa.String(length=500), nullable=True),
        sa.Column("char_start_snapshot", sa.Integer(), nullable=False),
        sa.Column("char_end_snapshot", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("rank > 0", name="ck_ai_execution_chunks_rank_positive"),
        sa.CheckConstraint("score >= -1 AND score <= 1", name="ck_ai_execution_chunks_score"),
        sa.CheckConstraint(
            "page_number_snapshot IS NULL OR page_number_snapshot > 0",
            name="ck_ai_execution_chunks_page_number",
        ),
        sa.CheckConstraint(
            "char_start_snapshot >= 0", name="ck_ai_execution_chunks_char_start_nonnegative"
        ),
        sa.CheckConstraint(
            "char_end_snapshot > char_start_snapshot",
            name="ck_ai_execution_chunks_char_range",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["ai_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "rank", name="uq_ai_execution_chunks_rank"),
    )
    op.create_index("ix_ai_execution_chunks_request_id", "ai_execution_chunks", ["request_id"])
    op.create_index("ix_ai_execution_chunks_chunk_id", "ai_execution_chunks", ["chunk_id"])
    op.create_index("ix_ai_execution_chunks_document_id", "ai_execution_chunks", ["document_id"])

    op.create_table(
        "ai_execution_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("ai_response_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_id_snapshot", sa.String(length=48), nullable=False),
        sa.Column("claim_snapshot", sa.Text(), nullable=False),
        sa.Column("excerpt_snapshot", sa.Text(), nullable=False),
        sa.Column("document_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("chunk_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("document_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("page_number_snapshot", sa.Integer(), nullable=True),
        sa.Column("heading_snapshot", sa.String(length=500), nullable=True),
        sa.Column("char_start_snapshot", sa.Integer(), nullable=False),
        sa.Column("char_end_snapshot", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ordinal > 0", name="ck_ai_execution_citations_ordinal_positive"),
        sa.CheckConstraint(
            "page_number_snapshot IS NULL OR page_number_snapshot > 0",
            name="ck_ai_execution_citations_page_number",
        ),
        sa.CheckConstraint(
            "char_start_snapshot >= 0",
            name="ck_ai_execution_citations_char_start_nonnegative",
        ),
        sa.CheckConstraint(
            "char_end_snapshot > char_start_snapshot",
            name="ck_ai_execution_citations_char_range",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["ai_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "ordinal", name="uq_ai_execution_citations_ordinal"),
    )
    op.create_index(
        "ix_ai_execution_citations_request_id", "ai_execution_citations", ["request_id"]
    )

    op.create_table(
        "ai_execution_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("response_node_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("document_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("document_node_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("document_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("max_relevance_score", sa.Float(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "max_relevance_score >= -1 AND max_relevance_score <= 1",
            name="ck_ai_execution_sources_score",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["ai_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "document_id_snapshot",
            "document_node_id_snapshot",
            name="uq_ai_execution_sources_relation",
        ),
    )
    op.create_index("ix_ai_execution_sources_request_id", "ai_execution_sources", ["request_id"])


def downgrade() -> None:
    is_postgresql = op.get_bind().dialect.name == "postgresql"
    op.drop_index("ix_ai_execution_sources_request_id", table_name="ai_execution_sources")
    op.drop_table("ai_execution_sources")
    op.drop_index("ix_ai_execution_citations_request_id", table_name="ai_execution_citations")
    op.drop_table("ai_execution_citations")
    op.drop_index("ix_ai_execution_chunks_document_id", table_name="ai_execution_chunks")
    op.drop_index("ix_ai_execution_chunks_chunk_id", table_name="ai_execution_chunks")
    op.drop_index("ix_ai_execution_chunks_request_id", table_name="ai_execution_chunks")
    op.drop_table("ai_execution_chunks")
    op.drop_index("ix_ai_execution_nodes_document_id", table_name="ai_execution_nodes")
    op.drop_index("ix_ai_execution_nodes_node_id", table_name="ai_execution_nodes")
    op.drop_index("ix_ai_execution_nodes_request_id", table_name="ai_execution_nodes")
    op.drop_table("ai_execution_nodes")
    op.drop_index("ix_ai_response_sources_document_node_id", table_name="ai_response_sources")
    op.drop_index("ix_ai_response_sources_document_id", table_name="ai_response_sources")
    op.drop_index("ix_ai_response_sources_ai_response_id", table_name="ai_response_sources")
    op.drop_table("ai_response_sources")
    op.drop_index("ix_citations_chunk_id", table_name="citations")
    op.drop_index("ix_citations_document_id", table_name="citations")
    op.drop_index("ix_citations_ai_response_id", table_name="citations")
    op.drop_table("citations")
    op.drop_index("ix_document_processing_jobs_document_id", table_name="document_processing_jobs")
    op.drop_table("document_processing_jobs")
    if is_postgresql:
        op.drop_index("ix_document_embeddings_embedding_hnsw", table_name="document_embeddings")
    op.drop_index("ix_document_embeddings_document_id", table_name="document_embeddings")
    op.drop_table("document_embeddings")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_canvas_document_nodes_document_id", table_name="canvas_document_nodes")
    op.drop_index("ix_canvas_document_nodes_canvas_id", table_name="canvas_document_nodes")
    op.drop_table("canvas_document_nodes")
    op.drop_table("document_files")
    op.drop_index("ix_documents_canvas_status", table_name="documents")
    op.drop_index("ix_documents_canvas_id", table_name="documents")
    op.drop_table("documents")
    _replace_ai_response_node_fk(upgrade=False)
    op.drop_column("ai_responses", "total_tokens")
    op.drop_column("ai_responses", "output_tokens")
    op.drop_column("ai_responses", "input_tokens")
    op.drop_column("ai_responses", "insufficient_evidence")
    op.drop_column("ai_responses", "grounded")
    op.drop_column("ai_requests", "prompt_version")
    op.drop_column("ai_requests", "retrieval_configuration")
    op.drop_column("ai_requests", "model_configuration")
    _replace_phase_one_checks(upgrade=False)
