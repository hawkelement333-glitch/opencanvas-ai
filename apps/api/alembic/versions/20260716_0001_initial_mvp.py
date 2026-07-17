"""Create the OpenCanvas first-MVP persistence model.

Revision ID: 20260716_0001
Revises:
Create Date: 2026-07-16
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0001"
down_revision: str | None = None
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


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "canvases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("viewport_x", sa.Float(), server_default="0", nullable=False),
        sa.Column("viewport_y", sa.Float(), server_default="0", nullable=False),
        sa.Column("viewport_zoom", sa.Float(), server_default="1", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("revision >= 0", name="ck_canvases_revision_nonnegative"),
        sa.CheckConstraint("viewport_zoom > 0", name="ck_canvases_viewport_zoom_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("position_x", sa.Float(), nullable=False),
        sa.Column("position_y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), server_default="300", nullable=False),
        sa.Column("height", sa.Float(), server_default="220", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("type IN ('note', 'ai_response')", name="ck_nodes_type"),
        sa.CheckConstraint("width >= 220 AND width <= 1600", name="ck_nodes_width"),
        sa.CheckConstraint("height >= 140 AND height <= 1200", name="ck_nodes_height"),
        sa.CheckConstraint("revision >= 0", name="ck_nodes_revision_nonnegative"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "canvas_id", name="uq_nodes_id_canvas"),
    )
    op.create_index("ix_nodes_canvas_id", "nodes", ["canvas_id"])
    op.create_table(
        "edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("source_node_id", sa.Uuid(), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), server_default="default", nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("source_node_id <> target_node_id", name="ck_edges_not_self"),
        sa.CheckConstraint("kind IN ('default', 'generated_from')", name="ck_edges_kind"),
        sa.CheckConstraint("revision >= 0", name="ck_edges_revision_nonnegative"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_node_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_edges_source_same_canvas",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_edges_target_same_canvas",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canvas_id", "source_node_id", "target_node_id", "kind", name="uq_edges_direction_kind"
        ),
    )
    op.create_index("ix_edges_canvas_id", "edges", ["canvas_id"])
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("selected_node_ids", sa.JSON(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')", name="ck_ai_requests_status"
        ),
        sa.CheckConstraint("provider IN ('mock', 'openai')", name="ck_ai_requests_provider"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_requests_canvas_id", "ai_requests", ["canvas_id"])
    op.create_table(
        "ai_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider_response_id", sa.String(length=200), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["ai_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id"),
        sa.UniqueConstraint("request_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_responses")
    op.drop_index("ix_ai_requests_canvas_id", table_name="ai_requests")
    op.drop_table("ai_requests")
    op.drop_index("ix_edges_canvas_id", table_name="edges")
    op.drop_table("edges")
    op.drop_index("ix_nodes_canvas_id", table_name="nodes")
    op.drop_table("nodes")
    op.drop_table("canvases")
