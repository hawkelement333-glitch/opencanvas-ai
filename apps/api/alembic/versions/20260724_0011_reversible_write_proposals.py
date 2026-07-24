"""Persist review-only reversible-write proposals.

Revision ID: 20260724_0011
Revises: 20260724_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0011"
down_revision: str | None = "20260724_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_reversible_write_proposals"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('note.create', 'note.update')",
            name="ck_agent_reversible_proposal_action",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_agent_reversible_proposal_time_order"
        ),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_reversible_proposal_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint("execution_id", name="uq_agent_reversible_proposal_execution"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            "idempotency_key",
            name="uq_agent_reversible_proposal_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_reversible_proposal_scope",
        TABLE,
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_reversible_proposal_scope", table_name=TABLE)
    op.drop_table(TABLE)
