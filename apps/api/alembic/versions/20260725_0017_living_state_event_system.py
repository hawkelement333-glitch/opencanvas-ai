"""Add the living-state domain event and transactional outbox foundation.

Revision ID: 20260725_0017
Revises: 20260725_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0017"
down_revision: str | None = "20260725_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "domain_events",
    "domain_event_provenance",
    "domain_event_delivery_attempts",
    "domain_activity_entries",
)

EVENT_TYPES = (
    "'graph.relationship.created', "
    "'graph.relationship.superseded', "
    "'graph.relationship.deactivated', "
    "'canonical.resource.created', "
    "'canonical.resource.updated', "
    "'canonical.resource.historical', "
    "'controlled.execution.started', "
    "'controlled.execution.completed', "
    "'controlled.execution.failed', "
    "'controlled.execution.canceled', "
    "'controlled.effect.committed', "
    "'controlled.rollback.committed', "
    "'evidence.bundle.requested', "
    "'evidence.bundle.generation_started', "
    "'evidence.bundle.completed', "
    "'evidence.bundle.failed', "
    "'evidence.bundle.accessed', "
    "'evidence.bundle.export_denied', "
    "'citation.rendering.completed', "
    "'citation.rendering.failed'"
)


def _create_immutable_protection(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    "'domain event evidence is append-only'); END"
                )
            )
        return
    function = f"reject_{table}_mutation"
    op.execute(
        sa.text(
            f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'domain event evidence is append-only'; END; "
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


def _create_outbox_identity_protection() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_domain_event_outbox_identity_update_blocked "
                "BEFORE UPDATE ON domain_event_outbox WHEN "
                "OLD.outbox_id IS NOT NEW.outbox_id OR "
                "OLD.event_id IS NOT NEW.event_id OR "
                "OLD.user_id IS NOT NEW.user_id OR "
                "OLD.workspace_id IS NOT NEW.workspace_id OR "
                "OLD.max_attempts IS NOT NEW.max_attempts OR "
                "OLD.created_at IS NOT NEW.created_at "
                "BEGIN SELECT RAISE(ABORT, 'domain event outbox identity is immutable'); END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_domain_event_outbox_delete_blocked "
                "BEFORE DELETE ON domain_event_outbox BEGIN SELECT RAISE(ABORT, "
                "'domain event outbox history is retained'); END"
            )
        )
        return
    op.execute(
        sa.text(
            "CREATE FUNCTION reject_domain_event_outbox_identity_mutation() "
            "RETURNS trigger AS $$ BEGIN "
            "IF TG_OP = 'DELETE' THEN "
            "RAISE EXCEPTION 'domain event outbox history is retained'; "
            "END IF; "
            "IF OLD.outbox_id IS DISTINCT FROM NEW.outbox_id "
            "OR OLD.event_id IS DISTINCT FROM NEW.event_id "
            "OR OLD.user_id IS DISTINCT FROM NEW.user_id "
            "OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id "
            "OR OLD.max_attempts IS DISTINCT FROM NEW.max_attempts "
            "OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN "
            "RAISE EXCEPTION 'domain event outbox identity is immutable'; "
            "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_domain_event_outbox_identity_blocked "
            "BEFORE UPDATE OR DELETE ON domain_event_outbox FOR EACH ROW "
            "EXECUTE FUNCTION reject_domain_event_outbox_identity_mutation()"
        )
    )


def _drop_outbox_identity_protection() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_domain_event_outbox_identity_blocked "
                "ON domain_event_outbox"
            )
        )
        op.execute(
            sa.text("DROP FUNCTION IF EXISTS reject_domain_event_outbox_identity_mutation()")
        )


def upgrade() -> None:
    op.create_table(
        "workspace_event_sequences",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name="ck_workspace_event_sequence_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.create_table(
        "domain_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=True),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("registry_version", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("related_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("source_identity", sa.String(length=128), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "registry_version = 'mobius-domain-events-v1'",
            name="ck_domain_events_registry_version",
        ),
        sa.CheckConstraint(
            "schema_version = 'domain-event-v1'",
            name="ck_domain_events_schema_version",
        ),
        sa.CheckConstraint(
            f"event_type IN ({EVENT_TYPES})",
            name="ck_domain_events_type",
        ),
        sa.CheckConstraint(
            "subject_kind IN ('canonical_resource', 'graph_relationship', "
            "'controlled_execution', 'controlled_effect', 'controlled_rollback', "
            "'evidence_bundle', 'citation')",
            name="ck_domain_events_subject_kind",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_domain_events_sequence_positive",
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64 AND length(request_digest) = 64",
            name="ck_domain_events_digest_length",
        ),
        sa.CheckConstraint(
            "graph_revision IS NULL OR graph_revision > 0",
            name="ck_domain_events_graph_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_domain_events_canvas_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_domain_events_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "event_id",
            "user_id",
            "workspace_id",
            name="uq_domain_events_scope",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "scope_id",
            "event_type",
            "source_identity",
            name="uq_domain_events_idempotency_scope",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "sequence",
            name="uq_domain_events_workspace_sequence",
        ),
    )
    op.create_index(
        "ix_domain_events_workspace_timeline",
        "domain_events",
        ["user_id", "workspace_id", "sequence", "event_id"],
    )
    op.create_index(
        "ix_domain_events_canvas_timeline",
        "domain_events",
        ["user_id", "workspace_id", "canvas_id", "sequence"],
    )
    op.create_index(
        "ix_domain_events_subject_timeline",
        "domain_events",
        ["user_id", "workspace_id", "subject_id", "sequence"],
    )
    op.create_index("ix_domain_events_trace", "domain_events", ["trace_id"])
    op.create_index("ix_domain_events_execution", "domain_events", ["execution_id"])

    op.create_table(
        "domain_event_provenance",
        sa.Column("provenance_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("origin_type", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("graph_relationship_id", sa.Uuid(), nullable=True),
        sa.Column("graph_history_id", sa.Uuid(), nullable=True),
        sa.Column("effect_id", sa.Uuid(), nullable=True),
        sa.Column("rollback_result_id", sa.Uuid(), nullable=True),
        sa.Column("provenance_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin_type IN ('authenticated_user', 'canonical_service', "
            "'controlled_execution', 'reserved_future_contract')",
            name="ck_domain_event_provenance_origin",
        ),
        sa.CheckConstraint(
            "length(provenance_digest) = 64",
            name="ck_domain_event_provenance_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "user_id", "workspace_id"],
            ["domain_events.event_id", "domain_events.user_id", "domain_events.workspace_id"],
            name="fk_domain_event_provenance_event_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_executions.id",
                "controlled_agent_executions.user_id",
                "controlled_agent_executions.workspace_id",
            ],
            name="fk_domain_event_provenance_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("provenance_id"),
        sa.UniqueConstraint(
            "event_id",
            name="uq_domain_event_provenance_event",
        ),
    )
    op.create_index(
        "ix_domain_event_provenance_trace",
        "domain_event_provenance",
        ["trace_id"],
    )

    op.create_table(
        "domain_event_outbox",
        sa.Column("outbox_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_state", sa.String(length=24), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("lease_owner_id", sa.String(length=128), nullable=True),
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_classification", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "delivery_state IN ('pending', 'delivering', 'retry_wait', "
            "'delivered', 'terminal_failure')",
            name="ck_domain_event_outbox_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts AND max_attempts > 0",
            name="ck_domain_event_outbox_attempts_bounded",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_domain_event_outbox_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "(delivery_state = 'delivering' AND lease_owner_id IS NOT NULL "
            "AND lease_acquired_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > lease_acquired_at) OR "
            "(delivery_state <> 'delivering' AND lease_owner_id IS NULL "
            "AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)",
            name="ck_domain_event_outbox_lease_shape",
        ),
        sa.CheckConstraint(
            "(delivery_state = 'delivered' AND completed_at IS NOT NULL "
            "AND terminal_at IS NULL) OR "
            "(delivery_state = 'terminal_failure' AND terminal_at IS NOT NULL) OR "
            "(delivery_state NOT IN ('delivered', 'terminal_failure') "
            "AND completed_at IS NULL AND terminal_at IS NULL)",
            name="ck_domain_event_outbox_terminal_shape",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "user_id", "workspace_id"],
            ["domain_events.event_id", "domain_events.user_id", "domain_events.workspace_id"],
            name="fk_domain_event_outbox_event_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("outbox_id"),
        sa.UniqueConstraint(
            "outbox_id",
            "event_id",
            name="uq_domain_event_outbox_identity",
        ),
        sa.UniqueConstraint(
            "event_id",
            name="uq_domain_event_outbox_event",
        ),
    )
    op.create_index(
        "ix_domain_event_outbox_claimable",
        "domain_event_outbox",
        ["delivery_state", "eligible_at", "lease_expires_at", "outbox_id"],
    )
    op.create_index(
        "ix_domain_event_outbox_scope",
        "domain_event_outbox",
        ["user_id", "workspace_id", "created_at"],
    )

    op.create_table(
        "domain_event_delivery_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("outbox_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("failure_classification", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('delivered', 'retry_scheduled', 'terminal_failure')",
            name="ck_domain_event_attempt_outcome",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_domain_event_attempt_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id", "event_id"],
            ["domain_event_outbox.outbox_id", "domain_event_outbox.event_id"],
            name="fk_domain_event_attempt_outbox",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "outbox_id",
            "lease_generation",
            name="uq_domain_event_attempt_generation",
        ),
    )
    op.create_index(
        "ix_domain_event_attempt_event",
        "domain_event_delivery_attempts",
        ["event_id", "recorded_at"],
    )

    op.create_table(
        "domain_activity_entries",
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("projection_version", sa.String(length=24), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "projection_version = 'activity-v1'",
            name="ck_domain_activity_projection_version",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "user_id", "workspace_id"],
            ["domain_events.event_id", "domain_events.user_id", "domain_events.workspace_id"],
            name="fk_domain_activity_event_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("activity_id"),
        sa.UniqueConstraint(
            "event_id",
            name="uq_domain_activity_event",
        ),
    )
    op.create_index(
        "ix_domain_activity_workspace_timeline",
        "domain_activity_entries",
        ["user_id", "workspace_id", "sequence", "activity_id"],
    )
    op.create_index(
        "ix_domain_activity_canvas_timeline",
        "domain_activity_entries",
        ["user_id", "workspace_id", "canvas_id", "sequence"],
    )
    op.create_index(
        "ix_domain_activity_subject_timeline",
        "domain_activity_entries",
        ["user_id", "workspace_id", "subject_id", "sequence"],
    )

    for table in IMMUTABLE_TABLES:
        _create_immutable_protection(table)
    _create_outbox_identity_protection()


def downgrade() -> None:
    _drop_outbox_identity_protection()
    for table in reversed(IMMUTABLE_TABLES):
        _drop_immutable_protection(table)

    op.drop_index(
        "ix_domain_activity_subject_timeline",
        table_name="domain_activity_entries",
    )
    op.drop_index(
        "ix_domain_activity_canvas_timeline",
        table_name="domain_activity_entries",
    )
    op.drop_index(
        "ix_domain_activity_workspace_timeline",
        table_name="domain_activity_entries",
    )
    op.drop_table("domain_activity_entries")
    op.drop_index(
        "ix_domain_event_attempt_event",
        table_name="domain_event_delivery_attempts",
    )
    op.drop_table("domain_event_delivery_attempts")
    op.drop_index(
        "ix_domain_event_outbox_scope",
        table_name="domain_event_outbox",
    )
    op.drop_index(
        "ix_domain_event_outbox_claimable",
        table_name="domain_event_outbox",
    )
    op.drop_table("domain_event_outbox")
    op.drop_index(
        "ix_domain_event_provenance_trace",
        table_name="domain_event_provenance",
    )
    op.drop_table("domain_event_provenance")
    op.drop_index("ix_domain_events_execution", table_name="domain_events")
    op.drop_index("ix_domain_events_trace", table_name="domain_events")
    op.drop_index(
        "ix_domain_events_subject_timeline",
        table_name="domain_events",
    )
    op.drop_index(
        "ix_domain_events_canvas_timeline",
        table_name="domain_events",
    )
    op.drop_index(
        "ix_domain_events_workspace_timeline",
        table_name="domain_events",
    )
    op.drop_table("domain_events")
    op.drop_table("workspace_event_sequences")
