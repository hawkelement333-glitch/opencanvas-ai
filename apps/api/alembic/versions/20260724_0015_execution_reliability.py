"""Add bounded controlled-agent execution reliability state.

Revision ID: 20260724_0015
Revises: 20260724_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0015"
down_revision: str | None = "20260724_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_executions"
POSTGRES_FUNCTION = "reject_agent_execution_authority_mutation"

IMMUTABLE_COLUMNS = (
    "id",
    "user_id",
    "workspace_id",
    "schema_version",
    "role",
    "context_snapshot_id",
    "context_digest",
    "plan_id",
    "plan_digest",
    "grant_id",
    "created_at",
)


def _replace_append_only_update_guard() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text(f"DROP TRIGGER trg_{TABLE}_update_blocked"))
        return
    op.execute(sa.text(f"DROP TRIGGER trg_{TABLE}_mutation_blocked ON {TABLE}"))
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{TABLE}_delete_blocked BEFORE DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION reject_controlled_agent_mutation()"
        )
    )


def _create_authority_update_guard() -> None:
    if op.get_bind().dialect.name == "sqlite":
        unchanged = " AND ".join(f"OLD.{column} IS NEW.{column}" for column in IMMUTABLE_COLUMNS)
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_delete_blocked"))
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{TABLE}_delete_blocked BEFORE DELETE ON {TABLE} "
                "BEGIN SELECT RAISE(ABORT, 'controlled-agent records are append-only'); END"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{TABLE}_authority_update_blocked "
                f"BEFORE UPDATE ON {TABLE} WHEN NOT ({unchanged}) "
                "BEGIN SELECT RAISE(ABORT, "
                "'controlled-agent execution authority is immutable'); END"
            )
        )
        return
    changed = " OR ".join(
        f"OLD.{column} IS DISTINCT FROM NEW.{column}" for column in IMMUTABLE_COLUMNS
    )
    op.execute(
        sa.text(
            f"CREATE FUNCTION {POSTGRES_FUNCTION}() RETURNS trigger AS $$ "
            f"BEGIN IF {changed} THEN "
            "RAISE EXCEPTION 'controlled-agent execution authority is immutable'; "
            "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{TABLE}_authority_update_blocked BEFORE UPDATE ON {TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {POSTGRES_FUNCTION}()"
        )
    )


def _restore_append_only_update_guard() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_authority_update_blocked"))
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{TABLE}_update_blocked BEFORE UPDATE ON {TABLE} "
                "BEGIN SELECT RAISE(ABORT, 'controlled-agent records are append-only'); END"
            )
        )
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_delete_blocked"))
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{TABLE}_delete_blocked BEFORE DELETE ON {TABLE} "
                "BEGIN SELECT RAISE(ABORT, 'controlled-agent records are append-only'); END"
            )
        )
        return
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_authority_update_blocked ON {TABLE}"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS {POSTGRES_FUNCTION}()"))
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_delete_blocked ON {TABLE}"))
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{TABLE}_mutation_blocked BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION reject_controlled_agent_mutation()"
        )
    )


def upgrade() -> None:
    _replace_append_only_update_guard()
    op.add_column(TABLE, sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        TABLE,
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(TABLE, sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("lease_owner_id", sa.String(length=128), nullable=True))
    op.add_column(TABLE, sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(TABLE, sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("terminal_outcome", sa.String(length=24), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("failure_classification", sa.String(length=64), nullable=True),
    )

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                f"UPDATE {TABLE} SET deadline_at = datetime(created_at, '+15 minutes') "
                "WHERE deadline_at IS NULL"
            )
        )
    else:
        op.execute(
            sa.text(
                f"UPDATE {TABLE} SET deadline_at = created_at + INTERVAL '15 minutes' "
                "WHERE deadline_at IS NULL"
            )
        )

    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.alter_column(
            "deadline_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_deadline_after_creation",
            "deadline_at > created_at",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_max_attempts_positive",
            "max_attempts > 0",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_attempt_count_bounded",
            "attempt_count >= 0 AND attempt_count <= max_attempts",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_retry_before_deadline",
            "next_retry_at IS NULL OR next_retry_at <= deadline_at",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_lease_shape",
            "(lease_owner_id IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner_id IS NOT NULL AND length(lease_owner_id) > 0 "
            "AND lease_acquired_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > lease_acquired_at "
            "AND lease_expires_at <= deadline_at)",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_lease_generation_nonnegative",
            "lease_generation >= 0",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_terminal_shape",
            "(completed_at IS NULL AND terminal_outcome IS NULL "
            "AND failure_classification IS NULL) OR "
            "(completed_at IS NOT NULL AND terminal_outcome IS NOT NULL "
            "AND terminal_outcome IN ('succeeded', 'failed', 'cancelled', 'denied') "
            "AND lease_owner_id IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL AND next_retry_at IS NULL)",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_terminal_classification",
            "terminal_outcome IS NULL OR "
            "(terminal_outcome = 'succeeded' AND failure_classification IS NULL) OR "
            "(terminal_outcome IN ('failed', 'cancelled', 'denied') "
            "AND failure_classification IS NOT NULL "
            "AND length(failure_classification) > 0)",
        )
        batch_op.create_check_constraint(
            "ck_agent_execution_completion_after_creation",
            "completed_at IS NULL OR completed_at >= created_at",
        )

    op.create_index(
        "ix_agent_execution_claimable",
        TABLE,
        ["deadline_at", "next_retry_at", "attempt_count"],
    )
    op.create_index("ix_agent_execution_lease_expiry", TABLE, ["lease_expires_at"])
    _create_authority_update_guard()


def downgrade() -> None:
    op.drop_index("ix_agent_execution_lease_expiry", table_name=TABLE)
    op.drop_index("ix_agent_execution_claimable", table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_constraint(
            "ck_agent_execution_completion_after_creation",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_agent_execution_terminal_classification",
            type_="check",
        )
        batch_op.drop_constraint("ck_agent_execution_terminal_shape", type_="check")
        batch_op.drop_constraint(
            "ck_agent_execution_lease_generation_nonnegative",
            type_="check",
        )
        batch_op.drop_constraint("ck_agent_execution_lease_shape", type_="check")
        batch_op.drop_constraint(
            "ck_agent_execution_retry_before_deadline",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_agent_execution_attempt_count_bounded",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_agent_execution_max_attempts_positive",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_agent_execution_deadline_after_creation",
            type_="check",
        )
        batch_op.drop_column("failure_classification")
        batch_op.drop_column("terminal_outcome")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("lease_generation")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_acquired_at")
        batch_op.drop_column("lease_owner_id")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("deadline_at")
    _restore_append_only_update_guard()
