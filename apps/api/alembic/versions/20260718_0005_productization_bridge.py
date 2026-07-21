"""Add productization identity, ownership, jobs, versions, usage, and operations data.

Revision ID: 20260718_0005
Revises: 20260717_0004
Create Date: 2026-07-18
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0005"
down_revision: str | None = "20260717_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def _replace_check(table: str, name: str, expression: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, expression)
        return
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def _create_check(table: str, name: str, expression: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.create_check_constraint(name, expression)
        return
    op.create_check_constraint(name, table, expression)


def _drop_check(table: str, name: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(name, type_="check")
        return
    op.drop_constraint(name, table, type_="check")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settings_payload", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(email) <= 320", name="ck_users_email_length"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"], unique=True)
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String()),
        sa.column("email_normalized", sa.String()),
        sa.column("password_hash", sa.Text()),
        sa.column("display_name", sa.String()),
        sa.column("email_verified", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("settings_payload", sa.JSON()),
    )
    op.bulk_insert(
        users,
        [
            {
                "id": SYSTEM_USER_ID,
                "email": "migration-principal@mobius.invalid",
                "email_normalized": "migration-principal@mobius.invalid",
                "password_hash": "login-disabled",
                "display_name": "Migrated local data",
                "email_verified": True,
                "is_active": True,
                "settings_payload": {"migrationPrincipal": True},
            }
        ],
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_user_expires", "user_sessions", ["user_id", "expires_at"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_token_hash", "password_reset_tokens", ["token_hash"], unique=True
    )

    op.add_column(
        "workspaces", sa.Column("settings_payload", sa.JSON(), server_default="{}", nullable=False)
    )
    op.add_column("workspaces", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    workspace = sa.table("workspaces", sa.column("owner_id", sa.Uuid()))
    op.execute(sa.update(workspace).values(owner_id=SYSTEM_USER_ID))
    with op.batch_alter_table("workspaces", recreate="always") as batch:
        batch.alter_column("owner_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_workspaces_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )

    op.add_column("canvases", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE canvases SET workspace_id = "
            "(SELECT workspaces.id FROM workspaces WHERE workspaces.legacy_canvas_id = canvases.id)"
        )
    )
    with op.batch_alter_table("canvases", recreate="always") as batch:
        batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_canvases_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_canvases_workspace_id", "canvases", ["workspace_id"])

    op.add_column("trace_events", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_index("ix_trace_events_user_id", "trace_events", ["user_id"])

    for column in (
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("provider_configuration_version", sa.String(length=64), nullable=True),
        sa.Column("execution_mode", sa.String(length=32), nullable=True),
        sa.Column("parent_request_id", sa.Uuid(), nullable=True),
        sa.Column("rerun_type", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("safe_error_category", sa.String(length=64), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
    ):
        op.add_column("ai_requests", column)
    ai_requests = sa.table(
        "ai_requests",
        sa.column("id", sa.Uuid()),
        sa.column("trace_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("provider_configuration_version", sa.String()),
        sa.column("execution_mode", sa.String()),
    )
    op.execute(
        sa.update(ai_requests).values(
            user_id=SYSTEM_USER_ID,
            provider_configuration_version="legacy-v1",
            execution_mode="current_context",
        )
    )
    op.execute(sa.update(ai_requests).values(trace_id=ai_requests.c.id))
    op.execute(
        sa.text(
            "UPDATE ai_requests SET workspace_id = "
            "(SELECT canvases.workspace_id FROM canvases WHERE canvases.id = ai_requests.canvas_id)"
        )
    )
    with op.batch_alter_table("ai_requests", recreate="always") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("trace_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column(
            "provider_configuration_version", existing_type=sa.String(length=64), nullable=False
        )
        batch.alter_column("execution_mode", existing_type=sa.String(length=32), nullable=False)
        batch.create_foreign_key(
            "fk_ai_requests_user_id_users", "users", ["user_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ai_requests_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_ai_requests_parent_request_id_ai_requests",
            "ai_requests",
            ["parent_request_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_ai_requests_user_id", "ai_requests", ["user_id"])
    op.create_index("ix_ai_requests_trace_id", "ai_requests", ["trace_id"])
    op.create_index("ix_ai_requests_workspace_id", "ai_requests", ["workspace_id"])
    op.create_index("ix_ai_requests_parent_request_id", "ai_requests", ["parent_request_id"])

    for column in (
        sa.Column("safe_error_category", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("documents", column)
    _replace_check(
        "documents",
        "ck_documents_status",
        "status IN ('uploaded', 'queued', 'processing', 'ready', 'failed', "
        "'retryable_failure', 'permanent_failure', 'deleting', 'deleted')",
    )
    _replace_check(
        "documents",
        "ck_documents_processing_stage",
        "processing_stage IN ('uploading', 'queued', 'processing', 'extracting', 'chunking', "
        "'embedding', 'indexing', 'ready', 'retrying', 'failed', 'deleting', 'deleted')",
    )
    _create_check("documents", "ck_documents_version_count_positive", "version_count > 0")
    op.create_index("ix_documents_canvas_hash", "documents", ["canvas_id", "content_sha256"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="uploaded", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("version > 0", name="ck_document_versions_number_positive"),
        sa.CheckConstraint("file_size_bytes >= 0", name="ck_document_versions_size_nonnegative"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_versions_number"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index(
        "ix_document_versions_hash", "document_versions", ["document_id", "content_sha256"]
    )
    op.execute(
        sa.text(
            "INSERT INTO document_versions (id, document_id, version, file_name, file_type, "
            "media_type, file_size_bytes, content_sha256, storage_key, extracted_text, status, "
            "created_at, updated_at) "
            "SELECT document_files.id, documents.id, 1, documents.file_name, documents.file_type, "
            "documents.media_type, documents.file_size_bytes, documents.content_sha256, "
            "document_files.storage_key, documents.extracted_text, documents.status, "
            "documents.created_at, documents.updated_at FROM documents "
            "JOIN document_files ON document_files.document_id = documents.id"
        )
    )
    with op.batch_alter_table("document_files", recreate="always") as batch:
        batch.alter_column(
            "storage_key", existing_type=sa.String(length=255), type_=sa.String(length=512)
        )
    op.add_column(
        "document_chunks",
        sa.Column("document_version", sa.Integer(), server_default="1", nullable=False),
    )

    for column in (
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("safe_error_category", sa.String(length=64), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("document_processing_jobs", column)
    jobs = sa.table(
        "document_processing_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("idempotency_key", sa.String()),
    )
    connection = op.get_bind()
    for job_id in connection.execute(sa.select(jobs.c.id)).scalars():
        connection.execute(
            sa.update(jobs)
            .where(jobs.c.id == job_id)
            .values(user_id=SYSTEM_USER_ID, idempotency_key=f"migration:{job_id}")
        )
    op.execute(
        sa.text(
            "UPDATE document_processing_jobs SET workspace_id = "
            "(SELECT canvases.workspace_id FROM documents JOIN canvases "
            "ON canvases.id = documents.canvas_id "
            "WHERE documents.id = document_processing_jobs.document_id)"
        )
    )
    _replace_check(
        "document_processing_jobs",
        "ck_document_processing_jobs_status",
        "status IN ('queued', 'uploading', 'processing', 'extracting', 'chunking', "
        "'embedding', 'indexing', 'ready', 'retrying', 'retryable_failure', "
        "'permanent_failure', 'cancelled', 'failed')",
    )
    with op.batch_alter_table("document_processing_jobs", recreate="always") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("idempotency_key", existing_type=sa.String(length=160), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=24), type_=sa.String(length=32))
        batch.create_foreign_key(
            "fk_document_jobs_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_document_jobs_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_document_jobs_idempotency_key", ["idempotency_key"])
    op.create_index("ix_document_jobs_user_id", "document_processing_jobs", ["user_id"])
    op.create_index("ix_document_jobs_workspace_id", "document_processing_jobs", ["workspace_id"])
    op.create_index(
        "ix_document_jobs_claim",
        "document_processing_jobs",
        ["status", "available_at", "created_at"],
    )

    op.add_column(
        "citations", sa.Column("document_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "ai_execution_chunks",
        sa.Column("document_version_snapshot", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "ai_execution_citations",
        sa.Column("document_version_snapshot", sa.Integer(), server_default="1", nullable=False),
    )

    op.create_table(
        "ai_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("ai_response_id", sa.Uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), server_default="[]", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "evidence_status IN ('supported', 'inference', 'conflict', 'unsupported', "
            "'insufficient_evidence', 'excluded_from_context')",
            name="ck_ai_claims_evidence_status",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["ai_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_response_id"], ["ai_responses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_claims_request_id", "ai_claims", ["request_id"])
    op.create_index("ix_ai_claims_response_id", "ai_claims", ["ai_response_id"])
    op.create_index(
        "ix_ai_claims_request_ordinal", "ai_claims", ["request_id", "ordinal"], unique=True
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("storage_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("metadata_payload", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_records_user_time", "usage_records", ["user_id", "created_at"])
    op.create_index(
        "ix_usage_records_workspace_time", "usage_records", ["workspace_id", "created_at"]
    )

    op.create_table(
        "application_errors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("safe_message", sa.String(length=500), nullable=False),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_application_errors_correlation", "application_errors", ["correlation_id"])

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="ready", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_table(
        "data_export_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="requested", nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_export_requests_user_id", "data_export_requests", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_data_export_requests_user_id", table_name="data_export_requests")
    op.drop_table("data_export_requests")
    op.drop_table("worker_heartbeats")
    op.drop_index("ix_application_errors_correlation", table_name="application_errors")
    op.drop_table("application_errors")
    op.drop_index("ix_usage_records_workspace_time", table_name="usage_records")
    op.drop_index("ix_usage_records_user_time", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_ai_claims_request_ordinal", table_name="ai_claims")
    op.drop_index("ix_ai_claims_response_id", table_name="ai_claims")
    op.drop_index("ix_ai_claims_request_id", table_name="ai_claims")
    op.drop_table("ai_claims")
    op.drop_column("ai_execution_citations", "document_version_snapshot")
    op.drop_column("ai_execution_chunks", "document_version_snapshot")
    op.drop_column("citations", "document_version")
    op.drop_index("ix_document_jobs_claim", table_name="document_processing_jobs")
    op.drop_index("ix_document_jobs_workspace_id", table_name="document_processing_jobs")
    op.drop_index("ix_document_jobs_user_id", table_name="document_processing_jobs")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("document_processing_jobs", recreate="always") as batch:
            batch.drop_constraint("uq_document_jobs_idempotency_key", type_="unique")
            batch.drop_constraint("fk_document_jobs_user_id_users", type_="foreignkey")
            batch.drop_constraint("fk_document_jobs_workspace_id_workspaces", type_="foreignkey")
            batch.drop_constraint("ck_document_processing_jobs_status", type_="check")
            batch.create_check_constraint(
                "ck_document_processing_jobs_status",
                "status IN ('uploading', 'extracting', 'chunking', 'embedding', 'ready', 'failed')",
            )
            batch.alter_column(
                "status", existing_type=sa.String(length=32), type_=sa.String(length=24)
            )
            for name in (
                "heartbeat_at",
                "locked_by",
                "available_at",
                "retryable",
                "safe_error_category",
                "idempotency_key",
                "workspace_id",
                "user_id",
            ):
                batch.drop_column(name)
    else:
        op.drop_constraint(
            "uq_document_jobs_idempotency_key", "document_processing_jobs", type_="unique"
        )
        op.drop_constraint(
            "fk_document_jobs_user_id_users", "document_processing_jobs", type_="foreignkey"
        )
        op.drop_constraint(
            "fk_document_jobs_workspace_id_workspaces",
            "document_processing_jobs",
            type_="foreignkey",
        )
        _replace_check(
            "document_processing_jobs",
            "ck_document_processing_jobs_status",
            "status IN ('uploading', 'extracting', 'chunking', 'embedding', 'ready', 'failed')",
        )
        op.alter_column(
            "document_processing_jobs",
            "status",
            existing_type=sa.String(length=32),
            type_=sa.String(length=24),
        )
        for name in (
            "heartbeat_at",
            "locked_by",
            "available_at",
            "retryable",
            "safe_error_category",
            "idempotency_key",
            "workspace_id",
            "user_id",
        ):
            op.drop_column("document_processing_jobs", name)
    op.drop_column("document_chunks", "document_version")
    op.drop_index("ix_document_versions_hash", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_canvas_hash", table_name="documents")
    _replace_check(
        "documents",
        "ck_documents_status",
        "status IN ('processing', 'ready', 'failed')",
    )
    _replace_check(
        "documents",
        "ck_documents_processing_stage",
        (
            "processing_stage IN ('uploading', 'extracting', 'chunking', "
            "'embedding', 'ready', 'failed')"
        ),
    )
    _drop_check("documents", "ck_documents_version_count_positive")
    for name in (
        "deleted_at",
        "current_version",
        "version_count",
        "retry_count",
        "safe_error_category",
    ):
        op.drop_column("documents", name)
    op.drop_index("ix_ai_requests_parent_request_id", table_name="ai_requests")
    op.drop_index("ix_ai_requests_trace_id", table_name="ai_requests")
    op.drop_index("ix_ai_requests_workspace_id", table_name="ai_requests")
    op.drop_index("ix_ai_requests_user_id", table_name="ai_requests")
    ai_request_columns = (
        "estimated_cost_usd",
        "safe_error_category",
        "latency_ms",
        "completed_at",
        "started_at",
        "rerun_type",
        "parent_request_id",
        "execution_mode",
        "provider_configuration_version",
        "workspace_id",
        "user_id",
        "trace_id",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ai_requests", recreate="always") as batch:
            batch.drop_constraint("fk_ai_requests_user_id_users", type_="foreignkey")
            batch.drop_constraint("fk_ai_requests_workspace_id_workspaces", type_="foreignkey")
            batch.drop_constraint(
                "fk_ai_requests_parent_request_id_ai_requests", type_="foreignkey"
            )
            for name in ai_request_columns:
                batch.drop_column(name)
    else:
        op.drop_constraint("fk_ai_requests_user_id_users", "ai_requests", type_="foreignkey")
        op.drop_constraint(
            "fk_ai_requests_workspace_id_workspaces", "ai_requests", type_="foreignkey"
        )
        op.drop_constraint(
            "fk_ai_requests_parent_request_id_ai_requests", "ai_requests", type_="foreignkey"
        )
        for name in ai_request_columns:
            op.drop_column("ai_requests", name)
    op.drop_index("ix_trace_events_user_id", table_name="trace_events")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("trace_events", recreate="always") as batch:
            batch.drop_column("user_id")
    else:
        op.drop_column("trace_events", "user_id")
    op.drop_index("ix_canvases_workspace_id", table_name="canvases")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("canvases", recreate="always") as batch:
            batch.drop_constraint("fk_canvases_workspace_id_workspaces", type_="foreignkey")
            batch.drop_column("workspace_id")
        with op.batch_alter_table("workspaces", recreate="always") as batch:
            batch.drop_constraint("fk_workspaces_owner_id_users", type_="foreignkey")
            batch.alter_column("owner_id", existing_type=sa.Uuid(), nullable=True)
    else:
        op.drop_constraint("fk_canvases_workspace_id_workspaces", "canvases", type_="foreignkey")
        op.drop_column("canvases", "workspace_id")
        op.drop_constraint("fk_workspaces_owner_id_users", "workspaces", type_="foreignkey")
        op.alter_column("workspaces", "owner_id", existing_type=sa.Uuid(), nullable=True)
    op.drop_column("workspaces", "deleted_at")
    op.drop_column("workspaces", "settings_payload")
    op.drop_table("password_reset_tokens")
    op.drop_table("user_sessions")
    op.drop_index("ix_users_email_normalized", table_name="users")
    op.drop_table("users")
