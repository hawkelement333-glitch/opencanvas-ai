"""Add durable identities for legacy canvas, node, and edge creation.

Revision ID: 20260726_0029
Revises: 20260726_0028
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0029"
down_revision: str | None = "20260726_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legacy_creation_request_identities",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("result_kind", sa.String(length=16), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('canvas.create', 'node.create', 'node.duplicate', 'edge.create')",
            name="ck_legacy_creation_operation",
        ),
        sa.CheckConstraint(
            "result_kind IN ('canvas', 'node', 'edge')",
            name="ck_legacy_creation_result_kind",
        ),
        sa.CheckConstraint(
            "(operation = 'canvas.create' AND result_kind = 'canvas' AND canvas_id = result_id) "
            "OR (operation IN ('node.create', 'node.duplicate') "
            "AND result_kind = 'node' AND canvas_id IS NOT NULL) "
            "OR (operation = 'edge.create' AND result_kind = 'edge' AND canvas_id IS NOT NULL)",
            name="ck_legacy_creation_result_shape",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_legacy_creation_actor", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_legacy_creation_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("request_id", name="pk_legacy_creation_request_identities"),
        sa.UniqueConstraint(
            "actor_user_id",
            "operation",
            "idempotency_key",
            name="uq_legacy_creation_actor_operation_key",
        ),
    )
    op.create_index(
        "ix_legacy_creation_actor",
        "legacy_creation_request_identities",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_legacy_creation_canvas",
        "legacy_creation_request_identities",
        ["canvas_id"],
    )
    op.create_index(
        "ix_legacy_creation_workspace_created",
        "legacy_creation_request_identities",
        ["workspace_id", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION public.reject_legacy_creation_identity_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION 'legacy creation request identities are append-only';
            END;
            $$
            """
        )
        op.execute(
            "REVOKE ALL ON FUNCTION public.reject_legacy_creation_identity_mutation() FROM PUBLIC"
        )
        op.execute(
            """
            CREATE TRIGGER trg_legacy_creation_identity_append_only
            BEFORE UPDATE OR DELETE ON legacy_creation_request_identities
            FOR EACH ROW EXECUTE FUNCTION public.reject_legacy_creation_identity_mutation()
            """
        )
    else:
        op.execute(
            """
            CREATE TRIGGER trg_legacy_creation_identity_no_update
            BEFORE UPDATE ON legacy_creation_request_identities
            BEGIN
              SELECT RAISE(ABORT, 'legacy creation request identities are append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_legacy_creation_identity_no_delete
            BEFORE DELETE ON legacy_creation_request_identities
            BEGIN
              SELECT RAISE(ABORT, 'legacy creation request identities are append-only');
            END
            """
        )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM legacy_creation_request_identities"))
        .scalar_one()
    )
    if count:
        raise RuntimeError(
            "Milestone 7.8 downgrade is allowed only before durable creation identities exist."
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER trg_legacy_creation_identity_append_only "
            "ON legacy_creation_request_identities"
        )
        op.execute("DROP FUNCTION public.reject_legacy_creation_identity_mutation()")
    else:
        op.execute("DROP TRIGGER trg_legacy_creation_identity_no_update")
        op.execute("DROP TRIGGER trg_legacy_creation_identity_no_delete")
    op.drop_table("legacy_creation_request_identities")
