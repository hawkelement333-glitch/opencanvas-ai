"""Add immutable reversible effect-result persistence.

Revision ID: 20260724_0012
Revises: 20260724_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0012"
down_revision: str | None = "20260724_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_reversible_write_effects"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("plan_digest", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=True),
        sa.Column("resulting_resource_id", sa.Uuid(), nullable=False),
        sa.Column("resulting_revision", sa.Integer(), nullable=False),
        sa.Column("before_digest", sa.String(length=64), nullable=True),
        sa.Column("after_digest", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('note.create', 'note.update')", name="ck_agent_reversible_effect_action"
        ),
        sa.CheckConstraint("outcome = 'succeeded'", name="ck_agent_reversible_effect_outcome"),
        sa.ForeignKeyConstraint(
            ["canvas_id"],
            ["canvases.id"],
            name="fk_agent_reversible_effect_canvas",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["controlled_agent_reversible_write_proposals.proposal_id"],
            name="fk_agent_reversible_effect_proposal",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_agent_reversible_effect_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("effect_id"),
        sa.UniqueConstraint("execution_id", name="uq_agent_reversible_effect_execution"),
        sa.UniqueConstraint("proposal_id", name="uq_agent_reversible_effect_proposal"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_agent_reversible_effect_idempotency",
        ),
    )
    op.create_index("ix_agent_reversible_effect_proposal", TABLE, ["proposal_id"])
    op.create_index(
        "ix_agent_reversible_effect_scope",
        TABLE,
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{TABLE}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {TABLE} BEGIN SELECT RAISE(ABORT, "
                    "'controlled-agent records are append-only'); END"
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
