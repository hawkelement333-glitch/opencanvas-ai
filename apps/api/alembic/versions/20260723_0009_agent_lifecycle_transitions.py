"""Add append-only controlled-agent lifecycle transition guards.

Revision ID: 20260723_0009
Revises: 20260721_0008
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0009"
down_revision: str | None = "20260721_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_state_transitions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("previous_state_id", sa.Uuid(), nullable=True),
        sa.Column("predecessor_token", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'controlled-agent-v1'",
            name="ck_agent_transition_schema",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_agent_transition_sequence"),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_transition_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["state_id"],
            ["controlled_agent_execution_states.state_id"],
            name="fk_agent_transition_state",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_state_id"],
            ["controlled_agent_execution_states.state_id"],
            name="fk_agent_transition_previous_state",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint("state_id", name="uq_agent_transition_state"),
        sa.UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_agent_transition_execution_sequence",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "predecessor_token",
            name="uq_agent_transition_execution_predecessor",
        ),
    )
    op.create_index(
        "ix_agent_transition_execution_sequence",
        TABLE,
        ["execution_id", "sequence"],
    )
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
