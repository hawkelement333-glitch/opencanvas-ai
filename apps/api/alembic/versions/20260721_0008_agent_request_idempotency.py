"""Add append-only controlled-agent request idempotency.

Revision ID: 20260721_0008
Revises: 20260721_0007
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_0008"
down_revision: str | None = "20260721_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_request_identities"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("request_identity_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action = 'generate_grounded_draft'", name="ck_agent_request_closed_action"
        ),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_request_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("request_identity_id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            "idempotency_key",
            name="uq_agent_request_idempotency_scope",
        ),
    )
    op.create_index("ix_agent_request_execution", TABLE, ["execution_id"])
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{TABLE}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {TABLE} "
                    "BEGIN SELECT RAISE(ABORT, 'controlled-agent records are append-only'); END"
                )
            )
    else:
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{TABLE}_mutation_blocked BEFORE UPDATE OR DELETE ON {TABLE} "
                "FOR EACH ROW EXECUTE FUNCTION reject_controlled_agent_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_table(TABLE)
