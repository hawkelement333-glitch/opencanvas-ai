"""Add immutable reversible-write rollback evidence.

Revision ID: 20260724_0013
Revises: 20260724_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_0013"
down_revision: str | None = "20260724_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_reversible_write_rollback_evidence"
EFFECT_TABLE = "controlled_agent_reversible_write_effects"
POSTGRES_FUNCTION = "reject_agent_rollback_evidence_mutation"


def upgrade() -> None:
    before_state_object_check = (
        "json_type(before_state) = 'object'"
        if op.get_bind().dialect.name == "sqlite"
        else "json_typeof(before_state) = 'object'"
    )
    op.create_index(
        "ux_agent_reversible_effect_rollback_scope",
        EFFECT_TABLE,
        [
            "effect_id",
            "execution_id",
            "proposal_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            "action",
            "resulting_resource_id",
        ],
        unique=True,
    )
    op.create_table(
        TABLE,
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("pre_effect_revision", sa.Integer(), nullable=False),
        sa.Column("post_effect_revision", sa.Integer(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("before_digest", sa.String(length=64), nullable=False),
        sa.Column("after_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action = 'note.update'", name="ck_agent_rollback_evidence_action"),
        sa.CheckConstraint(
            "post_effect_revision = pre_effect_revision + 1",
            name="ck_agent_rollback_evidence_revision_order",
        ),
        sa.CheckConstraint(
            before_state_object_check,
            name="ck_agent_rollback_evidence_before_state_object",
        ),
        sa.ForeignKeyConstraint(
            [
                "effect_id",
                "execution_id",
                "proposal_id",
                "user_id",
                "workspace_id",
                "canvas_id",
                "action",
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
            name="fk_agent_rollback_evidence_effect_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["note_id", "canvas_id"],
            ["nodes.id", "nodes.canvas_id"],
            name="fk_agent_rollback_evidence_note_canvas",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_id"),
        sa.UniqueConstraint("effect_id", name="uq_agent_rollback_evidence_effect"),
    )
    op.create_index("ix_agent_rollback_evidence_note", TABLE, ["note_id", "post_effect_revision"])
    op.create_index(
        "ix_agent_rollback_evidence_scope",
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
                f"CREATE FUNCTION {POSTGRES_FUNCTION}() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'controlled-agent records are append-only'; END; "
                "$$ LANGUAGE plpgsql"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{TABLE}_mutation_blocked BEFORE UPDATE OR DELETE ON {TABLE} "
                f"FOR EACH ROW EXECUTE FUNCTION {POSTGRES_FUNCTION}()"
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_mutation_blocked ON {TABLE}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {POSTGRES_FUNCTION}()"))
    op.drop_table(TABLE)
    op.drop_index("ux_agent_reversible_effect_rollback_scope", table_name=EFFECT_TABLE)
