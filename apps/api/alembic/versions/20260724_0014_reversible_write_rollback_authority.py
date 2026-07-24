"""Add immutable reversible-write rollback authority persistence.

Revision ID: 20260724_0014
Revises: 20260724_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_0014"
down_revision: str | None = "20260724_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVAL_TABLE = "controlled_agent_reversible_write_rollback_approvals"
RESULT_TABLE = "controlled_agent_reversible_write_rollback_results"
PROPOSAL_TABLE = "controlled_agent_reversible_write_proposals"
EFFECT_TABLE = "controlled_agent_reversible_write_effects"
EVIDENCE_TABLE = "controlled_agent_reversible_write_rollback_evidence"
GRANT_TABLE = "controlled_agent_capability_grants"
APPROVAL_POSTGRES_FUNCTION = "reject_agent_rollback_approval_mutation"
RESULT_POSTGRES_FUNCTION = "reject_agent_rollback_result_mutation"


def _sha256_check(column: str, dialect: str) -> str:
    if dialect == "sqlite":
        return f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'"
    return f"{column} ~ '^[0-9a-f]{{64}}$'"


def _create_immutable_protection(table: str, postgres_function: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    "'controlled-agent records are append-only'); END"
                )
            )
        return
    op.execute(
        sa.text(
            f"CREATE FUNCTION {postgres_function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'controlled-agent records are append-only'; END; "
            "$$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{table}_mutation_blocked BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {postgres_function}()"
        )
    )


def _drop_immutable_protection(table: str, postgres_function: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {postgres_function}()"))


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        APPROVAL_TABLE,
        sa.Column("rollback_approval_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("forward_action", sa.String(length=32), nullable=False),
        sa.Column("rollback_action", sa.String(length=32), nullable=False),
        sa.Column("rollback_evidence_id", sa.Uuid(), nullable=True),
        sa.Column("original_plan_digest", sa.String(length=64), nullable=False),
        sa.Column("expected_current_revision", sa.Integer(), nullable=False),
        sa.Column("effect_after_state_digest", sa.String(length=64), nullable=False),
        sa.Column("rollback_target_kind", sa.String(length=32), nullable=False),
        sa.Column("rollback_target_digest", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("scoped_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("approval_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "forward_action IN ('note.create', 'note.update')",
            name="ck_agent_rollback_approval_forward_action",
        ),
        sa.CheckConstraint(
            "rollback_action IN ('note.create.rollback', 'note.update.rollback')",
            name="ck_agent_rollback_approval_action",
        ),
        sa.CheckConstraint(
            "rollback_target_kind IN ('authoritative_absence', 'exact_prior_state')",
            name="ck_agent_rollback_approval_target_kind",
        ),
        sa.CheckConstraint(
            "(forward_action = 'note.create' "
            "AND rollback_action = 'note.create.rollback' "
            "AND rollback_target_kind = 'authoritative_absence' "
            "AND rollback_evidence_id IS NULL) OR "
            "(forward_action = 'note.update' "
            "AND rollback_action = 'note.update.rollback' "
            "AND rollback_target_kind = 'exact_prior_state' "
            "AND rollback_evidence_id IS NOT NULL)",
            name="ck_agent_rollback_approval_action_shape",
        ),
        sa.CheckConstraint(
            "expected_current_revision > 0",
            name="ck_agent_rollback_approval_expected_revision_positive",
        ),
        sa.CheckConstraint(
            "length(scoped_idempotency_key) > 0",
            name="ck_agent_rollback_approval_idempotency_nonempty",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_agent_rollback_approval_time_order"),
        sa.CheckConstraint(
            _sha256_check("original_plan_digest", dialect),
            name="ck_agent_rollback_approval_original_plan_digest",
        ),
        sa.CheckConstraint(
            _sha256_check("effect_after_state_digest", dialect),
            name="ck_agent_rollback_approval_effect_after_state_digest",
        ),
        sa.CheckConstraint(
            _sha256_check("rollback_target_digest", dialect),
            name="ck_agent_rollback_approval_target_digest",
        ),
        sa.CheckConstraint(
            _sha256_check("approval_digest", dialect),
            name="ck_agent_rollback_approval_digest",
        ),
        sa.ForeignKeyConstraint(
            [
                "proposal_id",
                "execution_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
            ],
            [
                f"{PROPOSAL_TABLE}.proposal_id",
                f"{PROPOSAL_TABLE}.execution_id",
                f"{PROPOSAL_TABLE}.user_id",
                f"{PROPOSAL_TABLE}.workspace_id",
                f"{PROPOSAL_TABLE}.canvas_id",
                f"{PROPOSAL_TABLE}.action",
            ],
            name="fk_agent_rollback_approval_proposal_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "effect_id",
                "execution_id",
                "proposal_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
                "note_id",
            ],
            [
                f"{EFFECT_TABLE}.effect_id",
                f"{EFFECT_TABLE}.execution_id",
                f"{EFFECT_TABLE}.proposal_id",
                f"{EFFECT_TABLE}.user_id",
                f"{EFFECT_TABLE}.workspace_id",
                f"{EFFECT_TABLE}.canvas_id",
                f"{EFFECT_TABLE}.action",
                f"{EFFECT_TABLE}.resulting_resource_id",
            ],
            name="fk_agent_rollback_approval_effect_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["note_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_agent_rollback_approval_note_canvas",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["grant_id", "execution_id", "user_id", "workspace_id"],
            [
                f"{GRANT_TABLE}.grant_id",
                f"{GRANT_TABLE}.execution_id",
                f"{GRANT_TABLE}.user_id",
                f"{GRANT_TABLE}.workspace_id",
            ],
            name="fk_agent_rollback_approval_grant_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_evidence_id"],
            [f"{EVIDENCE_TABLE}.evidence_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rollback_approval_id"),
    )
    op.create_index("ix_agent_rollback_approval_effect", APPROVAL_TABLE, ["effect_id"])
    op.create_index(
        "ix_agent_rollback_approval_scope",
        APPROVAL_TABLE,
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index("ix_agent_rollback_approval_note", APPROVAL_TABLE, ["note_id"])
    op.create_index("ix_agent_rollback_approval_expiry", APPROVAL_TABLE, ["expires_at"])
    op.create_index("ix_agent_rollback_approval_evidence", APPROVAL_TABLE, ["rollback_evidence_id"])
    op.create_index(
        "ix_agent_rollback_approval_idempotency",
        APPROVAL_TABLE,
        ["user_id", "workspace_id", "canvas_id", "scoped_idempotency_key"],
    )
    op.create_index("ix_agent_rollback_approval_grant", APPROVAL_TABLE, ["grant_id"])
    _create_immutable_protection(APPROVAL_TABLE, APPROVAL_POSTGRES_FUNCTION)

    op.create_table(
        RESULT_TABLE,
        sa.Column("rollback_result_id", sa.Uuid(), nullable=False),
        sa.Column("rollback_approval_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("forward_action", sa.String(length=32), nullable=False),
        sa.Column("rollback_action", sa.String(length=32), nullable=False),
        sa.Column("rollback_target_kind", sa.String(length=32), nullable=False),
        sa.Column("rollback_approval_digest", sa.String(length=64), nullable=False),
        sa.Column("scoped_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("expected_pre_rollback_revision", sa.Integer(), nullable=False),
        sa.Column("resulting_revision", sa.Integer(), nullable=True),
        sa.Column("pre_rollback_state_digest", sa.String(length=64), nullable=False),
        sa.Column("post_rollback_target_digest", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "forward_action IN ('note.create', 'note.update')",
            name="ck_agent_rollback_result_forward_action",
        ),
        sa.CheckConstraint(
            "rollback_action IN ('note.create.rollback', 'note.update.rollback')",
            name="ck_agent_rollback_result_action",
        ),
        sa.CheckConstraint(
            "rollback_target_kind IN ('authoritative_absence', 'exact_prior_state')",
            name="ck_agent_rollback_result_target_kind",
        ),
        sa.CheckConstraint(
            "(forward_action = 'note.create' "
            "AND rollback_action = 'note.create.rollback' "
            "AND rollback_target_kind = 'authoritative_absence' "
            "AND resulting_revision IS NULL) OR "
            "(forward_action = 'note.update' "
            "AND rollback_action = 'note.update.rollback' "
            "AND rollback_target_kind = 'exact_prior_state' "
            "AND resulting_revision IS NOT NULL AND resulting_revision > 0)",
            name="ck_agent_rollback_result_action_shape",
        ),
        sa.CheckConstraint(
            "expected_pre_rollback_revision > 0",
            name="ck_agent_rollback_result_expected_revision_positive",
        ),
        sa.CheckConstraint(
            "length(scoped_idempotency_key) > 0",
            name="ck_agent_rollback_result_idempotency_nonempty",
        ),
        sa.CheckConstraint(
            _sha256_check("rollback_approval_digest", dialect),
            name="ck_agent_rollback_result_approval_digest",
        ),
        sa.CheckConstraint(
            _sha256_check("pre_rollback_state_digest", dialect),
            name="ck_agent_rollback_result_pre_rollback_digest",
        ),
        sa.CheckConstraint(
            _sha256_check("post_rollback_target_digest", dialect),
            name="ck_agent_rollback_result_post_rollback_digest",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_approval_id"],
            [f"{APPROVAL_TABLE}.rollback_approval_id"],
            name="fk_agent_rollback_result_approval",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "proposal_id",
                "execution_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
            ],
            [
                f"{PROPOSAL_TABLE}.proposal_id",
                f"{PROPOSAL_TABLE}.execution_id",
                f"{PROPOSAL_TABLE}.user_id",
                f"{PROPOSAL_TABLE}.workspace_id",
                f"{PROPOSAL_TABLE}.canvas_id",
                f"{PROPOSAL_TABLE}.action",
            ],
            name="fk_agent_rollback_result_proposal_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "effect_id",
                "execution_id",
                "proposal_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "forward_action",
                "note_id",
            ],
            [
                f"{EFFECT_TABLE}.effect_id",
                f"{EFFECT_TABLE}.execution_id",
                f"{EFFECT_TABLE}.proposal_id",
                f"{EFFECT_TABLE}.user_id",
                f"{EFFECT_TABLE}.workspace_id",
                f"{EFFECT_TABLE}.canvas_id",
                f"{EFFECT_TABLE}.action",
                f"{EFFECT_TABLE}.resulting_resource_id",
            ],
            name="fk_agent_rollback_result_effect_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["note_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_agent_rollback_result_note_canvas",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rollback_result_id"),
        sa.UniqueConstraint("rollback_approval_id", name="uq_agent_rollback_result_approval"),
        sa.UniqueConstraint("effect_id", name="uq_agent_rollback_result_effect"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "scoped_idempotency_key",
            name="uq_agent_rollback_result_idempotency",
        ),
    )
    op.create_index("ix_agent_rollback_result_approval", RESULT_TABLE, ["rollback_approval_id"])
    op.create_index("ix_agent_rollback_result_effect", RESULT_TABLE, ["effect_id"])
    op.create_index(
        "ix_agent_rollback_result_idempotency",
        RESULT_TABLE,
        ["user_id", "workspace_id", "canvas_id", "scoped_idempotency_key"],
    )
    op.create_index(
        "ix_agent_rollback_result_scope",
        RESULT_TABLE,
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index("ix_agent_rollback_result_note", RESULT_TABLE, ["note_id"])
    op.create_index(
        "ix_controlled_agent_reversible_write_rollback_results_trace_id",
        RESULT_TABLE,
        ["trace_id"],
    )
    _create_immutable_protection(RESULT_TABLE, RESULT_POSTGRES_FUNCTION)


def downgrade() -> None:
    _drop_immutable_protection(RESULT_TABLE, RESULT_POSTGRES_FUNCTION)
    op.drop_table(RESULT_TABLE)
    _drop_immutable_protection(APPROVAL_TABLE, APPROVAL_POSTGRES_FUNCTION)
    op.drop_table(APPROVAL_TABLE)
