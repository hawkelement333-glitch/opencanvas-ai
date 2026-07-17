"""Add the reusable persistent Trace Foundation.

Revision ID: 20260717_0003
Revises: 20260717_0002
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0003"
down_revision: str | None = "20260717_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_trace_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("object_id", sa.Uuid(), nullable=True),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'service')",
            name="ck_trace_events_actor_type",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name="ck_trace_events_status",
        ),
        sa.CheckConstraint(
            "parent_trace_id IS NULL OR parent_trace_id <> trace_id",
            name="ck_trace_events_not_own_parent",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_trace_events_trace_id", "trace_events", ["trace_id"])
    op.create_index("ix_trace_events_parent_trace_id", "trace_events", ["parent_trace_id"])
    op.create_index("ix_trace_events_occurred_at", "trace_events", ["occurred_at"])
    op.create_index("ix_trace_events_event_type", "trace_events", ["event_type"])
    op.create_index("ix_trace_events_workspace_id", "trace_events", ["workspace_id"])
    op.create_index("ix_trace_events_object_id", "trace_events", ["object_id"])
    op.create_index(
        "ix_trace_events_trace_time",
        "trace_events",
        ["trace_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_trace_events_workspace_time", "trace_events", ["workspace_id", "occurred_at"]
    )
    op.create_index("ix_trace_events_object_time", "trace_events", ["object_id", "occurred_at"])
    op.create_index("ix_trace_events_type_time", "trace_events", ["event_type", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_trace_events_type_time", table_name="trace_events")
    op.drop_index("ix_trace_events_object_time", table_name="trace_events")
    op.drop_index("ix_trace_events_workspace_time", table_name="trace_events")
    op.drop_index("ix_trace_events_trace_time", table_name="trace_events")
    op.drop_index("ix_trace_events_object_id", table_name="trace_events")
    op.drop_index("ix_trace_events_workspace_id", table_name="trace_events")
    op.drop_index("ix_trace_events_event_type", table_name="trace_events")
    op.drop_index("ix_trace_events_occurred_at", table_name="trace_events")
    op.drop_index("ix_trace_events_parent_trace_id", table_name="trace_events")
    op.drop_index("ix_trace_events_trace_id", table_name="trace_events")
    op.drop_table("trace_events")
