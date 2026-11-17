"""Add append-only explicit controlled-draft artifact identities.

Revision ID: 20261116_0030
Revises: 20260726_0029
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261116_0030"
down_revision: str | None = "20260726_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "controlled_draft_artifacts",
        sa.Column("execution_id", sa.Uuid(), primary_key=True),
        sa.Column("response_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_controlled_draft_artifacts_canvas_id", "controlled_draft_artifacts", ["canvas_id"]
    )
    # Source/node identifiers intentionally have no deletion cascade. They preserve
    # the single-save identity after a mutable artifact is removed.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION public.reject_draft_artifact_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'controlled draft artifact identities are append-only';
            END; $$
        """)
        op.execute("REVOKE ALL ON FUNCTION public.reject_draft_artifact_mutation() FROM PUBLIC")
        op.execute("""
            CREATE TRIGGER trg_draft_artifact_append_only
            BEFORE UPDATE OR DELETE ON controlled_draft_artifacts
            FOR EACH ROW EXECUTE FUNCTION public.reject_draft_artifact_mutation()
        """)
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""
                CREATE TRIGGER trg_draft_artifact_no_{action.lower()}
                BEFORE {action} ON controlled_draft_artifacts
                BEGIN
                  SELECT RAISE(ABORT, 'controlled draft artifact identities are append-only');
                END
            """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM controlled_draft_artifacts"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot remove existing controlled draft artifact identities.")
    op.drop_table("controlled_draft_artifacts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION public.reject_draft_artifact_mutation()")
