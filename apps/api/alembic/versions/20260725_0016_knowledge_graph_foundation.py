"""Add the scoped canonical knowledge-graph foundation.

Revision ID: 20260725_0016
Revises: 20260724_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260725_0016"
down_revision: str | None = "20260724_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "canonical_graph_entities",
    "canonical_canvas_object_bindings",
    "canonical_graph_relationships",
    "canonical_relationship_provenance",
    "canonical_relationship_history",
)

OLD_RELATIONSHIP_TYPES = "'contains', 'part_of', 'references', 'derived_from', 'related_to'"
GRAPH_RELATIONSHIP_TYPES = (
    OLD_RELATIONSHIP_TYPES + ", 'cites', 'supports', 'contradicts', 'produced_by', 'affected_by'"
)


def _create_immutable_protection(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    "'knowledge-graph records are append-only'); END"
                )
            )
        return
    function = f"reject_{table}_mutation"
    op.execute(
        sa.text(
            f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'knowledge-graph records are append-only'; END; "
            "$$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{table}_mutation_blocked BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    )


def _drop_immutable_protection(table: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        function = f"reject_{table}_mutation"
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))


def upgrade() -> None:
    with op.batch_alter_table("canvases") as batch_op:
        batch_op.create_unique_constraint(
            "uq_canvases_id_workspace",
            ["id", "workspace_id"],
        )
    with op.batch_alter_table("canonical_relationships") as batch_op:
        batch_op.create_unique_constraint(
            "uq_canonical_relationships_object_workspace",
            ["object_id", "workspace_id"],
        )
        batch_op.drop_constraint(
            "ck_canonical_relationships_type",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_canonical_relationships_type",
            f"relationship_type IN ({GRAPH_RELATIONSHIP_TYPES})",
        )

    op.create_table(
        "workspace_graph_states",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_workspace_graph_state_revision_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.create_table(
        "canonical_graph_entities",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entity_kind", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_kind IN ('document', 'note', 'execution')",
            name="ck_graph_entities_kind",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_graph_entities_object_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("object_id"),
        sa.UniqueConstraint(
            "object_id",
            "workspace_id",
            "user_id",
            name="uq_graph_entities_object_scope",
        ),
    )
    op.create_index(
        "ix_graph_entities_scope_kind",
        "canonical_graph_entities",
        ["user_id", "workspace_id", "entity_kind"],
    )
    op.create_index(
        "ix_canonical_graph_entities_trace_id",
        "canonical_graph_entities",
        ["trace_id"],
    )

    op.create_table(
        "canonical_canvas_object_bindings",
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_canvas_object_bindings_canvas_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["object_id", "workspace_id", "user_id"],
            [
                "canonical_graph_entities.object_id",
                "canonical_graph_entities.workspace_id",
                "canonical_graph_entities.user_id",
            ],
            name="fk_canvas_object_bindings_entity_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint(
            "object_id",
            "workspace_id",
            "user_id",
            "canvas_id",
            name="uq_canvas_object_bindings_entity_canvas",
        ),
    )
    op.create_index(
        "ix_canvas_object_bindings_scope",
        "canonical_canvas_object_bindings",
        ["user_id", "workspace_id", "canvas_id"],
    )
    op.create_index(
        "ix_canonical_canvas_object_bindings_trace_id",
        "canonical_canvas_object_bindings",
        ["trace_id"],
    )

    op.create_table(
        "canonical_graph_relationships",
        sa.Column("relationship_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("source_object_id", sa.Uuid(), nullable=False),
        sa.Column("target_object_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("canonical_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version = 'knowledge-graph-v1'",
            name="ck_graph_relationships_schema",
        ),
        sa.CheckConstraint(
            "graph_revision > 0",
            name="ck_graph_relationships_revision_positive",
        ),
        sa.CheckConstraint(
            "length(canonical_digest) = 64 AND length(request_digest) = 64",
            name="ck_graph_relationships_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id", "workspace_id"],
            ["canonical_relationships.object_id", "canonical_relationships.workspace_id"],
            name="fk_graph_relationships_canonical_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_object_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_canvas_object_bindings.object_id",
                "canonical_canvas_object_bindings.workspace_id",
                "canonical_canvas_object_bindings.user_id",
                "canonical_canvas_object_bindings.canvas_id",
            ],
            name="fk_graph_relationships_source_binding",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_object_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_canvas_object_bindings.object_id",
                "canonical_canvas_object_bindings.workspace_id",
                "canonical_canvas_object_bindings.user_id",
                "canonical_canvas_object_bindings.canvas_id",
            ],
            name="fk_graph_relationships_target_binding",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("relationship_id"),
        sa.UniqueConstraint("canonical_digest"),
        sa.UniqueConstraint(
            "relationship_id",
            "workspace_id",
            "user_id",
            "canvas_id",
            name="uq_graph_relationships_scope",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_graph_relationships_idempotency",
        ),
    )
    op.create_index(
        "ix_graph_relationships_source",
        "canonical_graph_relationships",
        ["user_id", "workspace_id", "canvas_id", "source_object_id"],
    )
    op.create_index(
        "ix_graph_relationships_target",
        "canonical_graph_relationships",
        ["user_id", "workspace_id", "canvas_id", "target_object_id"],
    )

    op.create_table(
        "canonical_relationship_provenance",
        sa.Column("provenance_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("origin_type", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("source_reference_id", sa.Uuid(), nullable=True),
        sa.Column("rule_id", sa.String(length=120), nullable=True),
        sa.Column("rule_version", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("provenance_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin_type IN ('user_created', 'imported_canonical', 'citation_derived', "
            "'controlled_agent_approved', 'deterministic_rule')",
            name="ck_relationship_provenance_origin",
        ),
        sa.CheckConstraint(
            "(origin_type = 'controlled_agent_approved' AND execution_id IS NOT NULL) OR "
            "(origin_type <> 'controlled_agent_approved' AND execution_id IS NULL)",
            name="ck_relationship_provenance_execution_shape",
        ),
        sa.CheckConstraint(
            "(origin_type IN ('imported_canonical', 'citation_derived') "
            "AND source_reference_id IS NOT NULL) OR "
            "(origin_type NOT IN ('imported_canonical', 'citation_derived') "
            "AND source_reference_id IS NULL)",
            name="ck_relationship_provenance_source_shape",
        ),
        sa.CheckConstraint(
            "(origin_type = 'deterministic_rule' AND rule_id IS NOT NULL "
            "AND rule_version IS NOT NULL) OR "
            "(origin_type <> 'deterministic_rule' AND rule_id IS NULL "
            "AND rule_version IS NULL)",
            name="ck_relationship_provenance_rule_shape",
        ),
        sa.CheckConstraint(
            "length(provenance_digest) = 64",
            name="ck_relationship_provenance_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_relationship_provenance_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_graph_relationships.relationship_id",
                "canonical_graph_relationships.workspace_id",
                "canonical_graph_relationships.user_id",
                "canonical_graph_relationships.canvas_id",
            ],
            name="fk_relationship_provenance_graph_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("provenance_id"),
        sa.UniqueConstraint(
            "relationship_id",
            name="uq_relationship_provenance_relationship",
        ),
    )
    op.create_index(
        "ix_relationship_provenance_trace",
        "canonical_relationship_provenance",
        ["trace_id"],
    )

    op.create_table(
        "canonical_relationship_history",
        sa.Column("history_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("previous_history_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('active', 'inactive', 'superseded', 'rejected')",
            name="ck_relationship_history_state",
        ),
        sa.CheckConstraint(
            "graph_revision > 0",
            name="ck_relationship_history_revision_positive",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_relationship_history_request_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_history_id", "relationship_id"],
            [
                "canonical_relationship_history.history_id",
                "canonical_relationship_history.relationship_id",
            ],
            name="fk_relationship_history_previous",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id", "workspace_id", "user_id", "canvas_id"],
            [
                "canonical_graph_relationships.relationship_id",
                "canonical_graph_relationships.workspace_id",
                "canonical_graph_relationships.user_id",
                "canonical_graph_relationships.canvas_id",
            ],
            name="fk_relationship_history_graph_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("history_id"),
        sa.UniqueConstraint(
            "history_id",
            "relationship_id",
            name="uq_relationship_history_identity",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_relationship_history_idempotency",
        ),
    )
    op.create_index(
        "ix_relationship_history_timeline",
        "canonical_relationship_history",
        ["relationship_id", "graph_revision", "history_id"],
    )

    for table in IMMUTABLE_TABLES:
        _create_immutable_protection(table)


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        _drop_immutable_protection(table)
    op.drop_table("canonical_relationship_history")
    op.drop_table("canonical_relationship_provenance")
    op.drop_table("canonical_graph_relationships")
    op.drop_table("canonical_canvas_object_bindings")
    op.drop_table("canonical_graph_entities")
    op.drop_table("workspace_graph_states")

    with op.batch_alter_table("canonical_relationships") as batch_op:
        batch_op.drop_constraint(
            "ck_canonical_relationships_type",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_canonical_relationships_type",
            f"relationship_type IN ({OLD_RELATIONSHIP_TYPES})",
        )
        batch_op.drop_constraint(
            "uq_canonical_relationships_object_workspace",
            type_="unique",
        )
    with op.batch_alter_table("canvases") as batch_op:
        batch_op.drop_constraint(
            "uq_canvases_id_workspace",
            type_="unique",
        )
