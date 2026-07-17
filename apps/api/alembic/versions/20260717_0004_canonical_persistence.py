"""Add canonical workspace, object, subtype, and relationship persistence.

Revision ID: 20260717_0004
Revises: 20260717_0003
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0004"
down_revision: str | None = "20260717_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            server_default="created",
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("legacy_canvas_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("version >= 1", name="ck_workspaces_version_positive"),
        sa.CheckConstraint(
            "lifecycle_state IN ('created', 'active', 'archived', 'deleted')",
            name="ck_workspaces_lifecycle_state",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_canvas_id"],
            ["canvases.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legacy_canvas_id"),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_index("ix_workspaces_lifecycle_state", "workspaces", ["lifecycle_state"])

    op.execute(
        sa.text(
            """
            INSERT INTO workspaces (
                id,
                name,
                description,
                owner_id,
                version,
                lifecycle_state,
                metadata,
                legacy_canvas_id,
                created_at,
                updated_at
            )
            SELECT
                id,
                name,
                NULL,
                NULL,
                1,
                'active',
                '{}',
                id,
                created_at,
                updated_at
            FROM canvases
            """
        )
    )

    op.create_table(
        "canonical_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("object_type", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            server_default="created",
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "object_type IN ('document', 'chunk', 'note', 'execution', 'relationship')",
            name="ck_canonical_objects_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_canonical_objects_version_positive"),
        sa.CheckConstraint(
            "lifecycle_state IN ('created', 'active', 'archived', 'deleted')",
            name="ck_canonical_objects_lifecycle_state",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_canonical_objects_id_workspace"),
    )
    op.create_index("ix_canonical_objects_workspace_id", "canonical_objects", ["workspace_id"])
    op.create_index(
        "ix_canonical_objects_workspace_type_state",
        "canonical_objects",
        ["workspace_id", "object_type", "lifecycle_state"],
    )

    op.create_table(
        "canonical_documents",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            server_default="created",
            nullable=False,
        ),
        sa.Column("source_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("legacy_document_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "processing_status IN ('created', 'processing', 'ready', 'failed')",
            name="ck_canonical_documents_processing_status",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_document_id"],
            ["documents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["canonical_objects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("object_id"),
        sa.UniqueConstraint("legacy_document_id"),
    )
    op.create_index(
        "ix_canonical_documents_processing_status",
        "canonical_documents",
        ["processing_status"],
    )

    op.create_table(
        "canonical_chunks",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("document_object_id", sa.Uuid(), nullable=False),
        sa.Column("ordered_position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_location", sa.JSON(), server_default="{}", nullable=False),
        sa.CheckConstraint(
            "ordered_position >= 0",
            name="ck_canonical_chunks_position_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_object_id"],
            ["canonical_documents.object_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["canonical_objects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("object_id"),
        sa.UniqueConstraint(
            "document_object_id",
            "ordered_position",
            name="uq_canonical_chunks_document_position",
        ),
    )
    op.create_index(
        "ix_canonical_chunks_document_object_id",
        "canonical_chunks",
        ["document_object_id"],
    )

    op.create_table(
        "canonical_notes",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["canonical_objects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("object_id"),
    )

    op.create_table(
        "canonical_executions",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("execution_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("inputs_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("outputs_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_canonical_executions_status",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_canonical_executions_time_order",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["canonical_objects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("object_id"),
    )
    op.create_index("ix_canonical_executions_status", "canonical_executions", ["status"])
    op.create_index("ix_canonical_executions_trace_id", "canonical_executions", ["trace_id"])

    op.create_table(
        "canonical_relationships",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_object_id", sa.Uuid(), nullable=False),
        sa.Column("target_object_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "relationship_type IN "
            "('contains', 'part_of', 'references', 'derived_from', 'related_to')",
            name="ck_canonical_relationships_type",
        ),
        sa.CheckConstraint(
            "source_object_id <> target_object_id",
            name="ck_canonical_relationships_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_canonical_relationships_object_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_canonical_relationships_source_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_canonical_relationships_target_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("object_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_object_id",
            "target_object_id",
            "relationship_type",
            name="uq_canonical_relationships_direction_type",
        ),
    )
    op.create_index(
        "ix_canonical_relationships_workspace_type",
        "canonical_relationships",
        ["workspace_id", "relationship_type"],
    )
    op.create_index(
        "ix_canonical_relationships_workspace_target",
        "canonical_relationships",
        ["workspace_id", "target_object_id"],
    )
    op.create_index(
        "ix_canonical_relationships_trace_id",
        "canonical_relationships",
        ["trace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_relationships_trace_id", table_name="canonical_relationships")
    op.drop_index(
        "ix_canonical_relationships_workspace_target",
        table_name="canonical_relationships",
    )
    op.drop_index(
        "ix_canonical_relationships_workspace_type",
        table_name="canonical_relationships",
    )
    op.drop_table("canonical_relationships")
    op.drop_index("ix_canonical_executions_trace_id", table_name="canonical_executions")
    op.drop_index("ix_canonical_executions_status", table_name="canonical_executions")
    op.drop_table("canonical_executions")
    op.drop_table("canonical_notes")
    op.drop_index(
        "ix_canonical_chunks_document_object_id",
        table_name="canonical_chunks",
    )
    op.drop_table("canonical_chunks")
    op.drop_index(
        "ix_canonical_documents_processing_status",
        table_name="canonical_documents",
    )
    op.drop_table("canonical_documents")
    op.drop_index(
        "ix_canonical_objects_workspace_type_state",
        table_name="canonical_objects",
    )
    op.drop_index("ix_canonical_objects_workspace_id", table_name="canonical_objects")
    op.drop_table("canonical_objects")
    op.drop_index("ix_workspaces_lifecycle_state", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_table("workspaces")
