"""Add immutable controlled workflow definitions and bounded execution evidence.

Revision ID: 20260725_0019
Revises: 20260725_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0019"
down_revision: str | None = "20260725_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "controlled_workflow_definitions",
    "controlled_workflow_versions",
    "controlled_workflow_version_states",
    "controlled_workflow_steps",
    "controlled_workflow_dependencies",
    "controlled_workflow_plan_snapshots",
    "controlled_workflow_execution_transitions",
    "controlled_workflow_step_transitions",
    "controlled_workflow_step_attempts",
    "controlled_workflow_evidence_links",
)

ORIGINAL_EVENT_TYPES = (
    "graph.relationship.created",
    "graph.relationship.superseded",
    "graph.relationship.deactivated",
    "canonical.resource.created",
    "canonical.resource.updated",
    "canonical.resource.historical",
    "controlled.execution.started",
    "controlled.execution.completed",
    "controlled.execution.failed",
    "controlled.execution.canceled",
    "controlled.effect.committed",
    "controlled.rollback.committed",
    "evidence.bundle.requested",
    "evidence.bundle.generation_started",
    "evidence.bundle.completed",
    "evidence.bundle.failed",
    "evidence.bundle.accessed",
    "evidence.bundle.export_denied",
    "citation.rendering.completed",
    "citation.rendering.failed",
)
WORKFLOW_EVENT_TYPES = (
    "workflow.definition.created",
    "workflow.version.created",
    "workflow.version.validated",
    "workflow.version.activated",
    "workflow.version.disabled",
    "workflow.execution.requested",
    "workflow.execution.planned",
    "workflow.execution.started",
    "workflow.execution.awaiting_approval",
    "workflow.execution.completed",
    "workflow.execution.failed",
    "workflow.execution.canceled",
    "workflow.compensation.started",
    "workflow.compensation.completed",
    "workflow.compensation.failed",
    "workflow.step.started",
    "workflow.step.completed",
    "workflow.step.failed",
    "workflow.step.retry_scheduled",
    "workflow.step.awaiting_approval",
    "workflow.approval.requested",
    "workflow.approval.accepted",
    "workflow.approval.denied",
)
ORIGINAL_SUBJECT_KINDS = (
    "canonical_resource",
    "graph_relationship",
    "controlled_execution",
    "controlled_effect",
    "controlled_rollback",
    "evidence_bundle",
    "citation",
)
WORKFLOW_SUBJECT_KINDS = (
    "workflow_definition",
    "workflow_version",
    "workflow_execution",
    "workflow_step",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_domain_event_constraints(
    event_types: tuple[str, ...],
    subject_kinds: tuple[str, ...],
) -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_domain_events_update_blocked"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_domain_events_delete_blocked"))
    with op.batch_alter_table(
        "domain_events",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_constraint("ck_domain_events_type", type_="check")
        batch.drop_constraint("ck_domain_events_subject_kind", type_="check")
        batch.create_check_constraint(
            "ck_domain_events_type",
            f"event_type IN ({_in(event_types)})",
        )
        batch.create_check_constraint(
            "ck_domain_events_subject_kind",
            f"subject_kind IN ({_in(subject_kinds)})",
        )
    if sqlite:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_domain_events_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON domain_events BEGIN SELECT RAISE(ABORT, "
                    "'domain event evidence is append-only'); END"
                )
            )


def _protect(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    "'workflow evidence is append-only'); END"
                )
            )
        return
    function = f"reject_{table}_mutation"
    op.execute(
        sa.text(
            f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'workflow evidence is append-only'; END; "
            "$$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{table}_mutation_blocked BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    )


def _unprotect(table: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()"))


def upgrade() -> None:
    _replace_domain_event_constraints(
        ORIGINAL_EVENT_TYPES + WORKFLOW_EVENT_TYPES,
        ORIGINAL_SUBJECT_KINDS + WORKFLOW_SUBJECT_KINDS,
    )
    op.create_table(
        "controlled_workflow_definitions",
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'controlled-workflow-v1'",
            name="ck_workflow_definition_schema",
        ),
        sa.CheckConstraint(
            "kind IN ('grounded_answer', 'evidence_package', 'approved_reversible_note')",
            name="ck_workflow_definition_kind",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("definition_id"),
        sa.UniqueConstraint(
            "definition_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_definition_scope",
        ),
    )
    op.create_index(
        "ix_workflow_definition_scope_time",
        "controlled_workflow_definitions",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index(
        "ix_controlled_workflow_definitions_trace_id",
        "controlled_workflow_definitions",
        ["trace_id"],
    )

    op.create_table(
        "controlled_workflow_versions",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("input_schema_version", sa.String(40), nullable=False),
        sa.Column("output_schema_version", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("normalized_definition", sa.JSON(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries_per_step", sa.Integer(), nullable=False),
        sa.Column("compensation_policy", sa.String(32), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'controlled-workflow-v1'",
            name="ck_workflow_version_schema",
        ),
        sa.CheckConstraint("version_number > 0", name="ck_workflow_version_number"),
        sa.CheckConstraint(
            "max_steps > 0 AND max_steps <= 32",
            name="ck_workflow_version_steps",
        ),
        sa.CheckConstraint(
            "max_duration_seconds > 0 AND max_duration_seconds <= 900",
            name="ck_workflow_version_duration",
        ),
        sa.CheckConstraint(
            "max_retries_per_step >= 0 AND max_retries_per_step <= 3",
            name="ck_workflow_version_retries",
        ),
        sa.CheckConstraint(
            "compensation_policy IN ('none', 'predefined_saga')",
            name="ck_workflow_version_compensation",
        ),
        sa.CheckConstraint("length(content_digest) = 64", name="ck_workflow_version_digest"),
        sa.ForeignKeyConstraint(
            ["definition_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_definitions.definition_id",
                "controlled_workflow_definitions.user_id",
                "controlled_workflow_definitions.workspace_id",
                "controlled_workflow_definitions.canvas_id",
            ],
            name="fk_workflow_version_definition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"],
            ["controlled_workflow_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint(
            "definition_id",
            "version_number",
            name="uq_workflow_version_number",
        ),
        sa.UniqueConstraint(
            "version_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_version_scope",
        ),
        sa.UniqueConstraint(
            "definition_id",
            "idempotency_key",
            name="uq_workflow_version_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_version_definition_time",
        "controlled_workflow_versions",
        ["definition_id", "created_at"],
    )
    op.create_index(
        "ix_controlled_workflow_versions_trace_id",
        "controlled_workflow_versions",
        ["trace_id"],
    )

    op.create_table(
        "controlled_workflow_version_states",
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('draft', 'validated', 'active', 'superseded', 'disabled', 'retired')",
            name="ck_workflow_version_state",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_workflow_version_state_sequence"),
        sa.ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_workflow_version_state_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("state_id"),
        sa.UniqueConstraint(
            "version_id",
            "sequence",
            name="uq_workflow_version_state_sequence",
        ),
    )
    op.create_index(
        "ix_workflow_version_state_time",
        "controlled_workflow_version_states",
        ["version_id", "sequence"],
    )

    op.create_table(
        "controlled_workflow_steps",
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(40), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("risk_class", sa.String(32), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("step_digest", sa.String(64), nullable=False),
        sa.Column("compensation_step_key", sa.String(64), nullable=True),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 32", name="ck_workflow_step_ordinal"),
        sa.CheckConstraint(
            "step_type IN ('validate_input', 'capture_context', 'graph_retrieval', "
            "'evaluate_evidence', 'grounded_model', 'render_citations', "
            "'evidence_bundle', 'human_approval', 'controlled_effect', "
            "'compensation', 'record_output')",
            name="ck_workflow_step_type",
        ),
        sa.CheckConstraint(
            "risk_class IN ('r0_observation', 'r1_draft', 'r2_transient_action', "
            "'r3_durable_write')",
            name="ck_workflow_step_risk",
        ),
        sa.CheckConstraint(
            "max_attempts > 0 AND max_attempts <= 4",
            name="ck_workflow_step_attempts",
        ),
        sa.CheckConstraint("length(step_digest) = 64", name="ck_workflow_step_digest"),
        sa.ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_workflow_step_version_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("step_id"),
        sa.UniqueConstraint("version_id", "step_id", name="uq_workflow_step_version_id"),
        sa.UniqueConstraint("version_id", "step_key", name="uq_workflow_step_key"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_workflow_step_ordinal"),
    )
    op.create_index(
        "ix_workflow_step_version_order",
        "controlled_workflow_steps",
        ["version_id", "ordinal"],
    )

    op.create_table(
        "controlled_workflow_dependencies",
        sa.Column("dependency_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_step_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("step_id <> depends_on_step_id", name="ck_workflow_dependency_self"),
        sa.ForeignKeyConstraint(
            ["version_id", "step_id"],
            ["controlled_workflow_steps.version_id", "controlled_workflow_steps.step_id"],
            name="fk_workflow_dependency_step",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "depends_on_step_id"],
            ["controlled_workflow_steps.version_id", "controlled_workflow_steps.step_id"],
            name="fk_workflow_dependency_predecessor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("dependency_id"),
        sa.UniqueConstraint(
            "version_id",
            "step_id",
            "depends_on_step_id",
            name="uq_workflow_dependency_edge",
        ),
    )
    op.create_index(
        "ix_workflow_dependency_step",
        "controlled_workflow_dependencies",
        ["version_id", "step_id"],
    )

    op.create_table(
        "controlled_workflow_executions",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("normalized_input", sa.JSON(), nullable=False),
        sa.Column("selected_object_ids", sa.JSON(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("output_digest", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('requested', 'planned', 'awaiting_approval', 'ready', 'running', "
            "'cancel_requested', 'canceling', 'compensating', 'completed', 'failed', "
            "'canceled', 'compensated', 'compensation_failed')",
            name="ck_workflow_execution_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('supported', 'conflicting_evidence', "
            "'insufficient_evidence', 'bounded_result', 'effect_committed', "
            "'compensated', 'canceled', 'failed')",
            name="ck_workflow_execution_outcome",
        ),
        sa.CheckConstraint(
            "deadline_at > created_at",
            name="ck_workflow_execution_deadline",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_workflow_execution_request_digest",
        ),
        sa.CheckConstraint(
            "length(plan_digest) = 64",
            name="ck_workflow_execution_plan_digest",
        ),
        sa.CheckConstraint(
            "length(input_digest) = 64",
            name="ck_workflow_execution_input_digest",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_workflow_execution_version_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("execution_id"),
        sa.UniqueConstraint(
            "execution_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_workflow_execution_scope",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "user_id",
            "workspace_id",
            name="uq_workflow_execution_owner_scope",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_workflow_execution_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_execution_scope_time",
        "controlled_workflow_executions",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_execution_status",
        "controlled_workflow_executions",
        ["status", "deadline_at"],
    )
    op.create_index(
        "ix_controlled_workflow_executions_trace_id",
        "controlled_workflow_executions",
        ["trace_id"],
    )

    op.create_table(
        "controlled_workflow_plan_snapshots",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'controlled-workflow-plan-v1'",
            name="ck_workflow_plan_schema",
        ),
        sa.CheckConstraint("length(plan_digest) = 64", name="ck_workflow_plan_digest"),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
            ],
            name="fk_workflow_plan_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint("execution_id", name="uq_workflow_plan_execution"),
    )

    op.create_table(
        "controlled_workflow_execution_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_workflow_execution_transition_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id", "workspace_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
            ],
            name="fk_workflow_execution_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_workflow_execution_transition_sequence",
        ),
    )
    op.create_index(
        "ix_workflow_execution_transition_time",
        "controlled_workflow_execution_transitions",
        ["execution_id", "sequence"],
    )

    op.create_table(
        "controlled_workflow_step_executions",
        sa.Column("step_execution_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("step_definition_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("controlled_execution_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner_id", sa.String(128), nullable=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("retrieval_id", sa.Uuid(), nullable=True),
        sa.Column("bundle_id", sa.Uuid(), nullable=True),
        sa.Column("effect_id", sa.Uuid(), nullable=True),
        sa.Column("rollback_result_id", sa.Uuid(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("output_digest", sa.String(64), nullable=True),
        sa.Column("safe_failure_class", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'blocked', 'awaiting_approval', 'ready', 'claimed', "
            "'running', 'succeeded', 'retry_waiting', 'failed', 'canceled', "
            "'compensating', 'compensated', 'compensation_failed', 'skipped')",
            name="ck_workflow_step_execution_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_workflow_step_execution_attempts",
        ),
        sa.CheckConstraint(
            "(lease_owner_id IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_workflow_step_execution_lease",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_workflow_step_execution_generation",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id", "user_id", "workspace_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
            ],
            name="fk_workflow_step_execution_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["step_definition_id"],
            ["controlled_workflow_steps.step_id"],
            name="fk_workflow_step_execution_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["controlled_execution_id"],
            ["controlled_agent_executions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_id"],
            ["graph_retrieval_runs.retrieval_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["trace_evidence_bundles.bundle_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["effect_id"],
            ["controlled_agent_reversible_write_effects.effect_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_result_id"],
            ["controlled_agent_reversible_write_rollback_results.rollback_result_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("step_execution_id"),
        sa.UniqueConstraint(
            "workflow_execution_id",
            "step_definition_id",
            name="uq_workflow_step_execution",
        ),
    )
    op.create_index(
        "ix_workflow_step_execution_ready",
        "controlled_workflow_step_executions",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_workflow_step_execution_run",
        "controlled_workflow_step_executions",
        ["workflow_execution_id", "step_definition_id"],
    )

    op.create_table(
        "controlled_workflow_step_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("step_execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_workflow_step_transition_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["step_execution_id"],
            ["controlled_workflow_step_executions.step_execution_id"],
            name="fk_workflow_step_transition_execution",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint(
            "step_execution_id",
            "sequence",
            name="uq_workflow_step_transition_sequence",
        ),
    )
    op.create_index(
        "ix_workflow_step_transition_time",
        "controlled_workflow_step_transitions",
        ["step_execution_id", "sequence"],
    )

    op.create_table(
        "controlled_workflow_step_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("step_execution_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("output_digest", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("failure_class", sa.String(64), nullable=True),
        sa.Column("provider_id", sa.String(64), nullable=True),
        sa.Column("model_id", sa.String(160), nullable=True),
        sa.Column("provider_configuration_version", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(128), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_workflow_step_attempt_number",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'retry_scheduled', 'failed', 'canceled')",
            name="ck_workflow_step_attempt_outcome",
        ),
        sa.CheckConstraint(
            "length(input_digest) = 64",
            name="ck_workflow_step_attempt_input_digest",
        ),
        sa.CheckConstraint(
            "output_digest IS NULL OR length(output_digest) = 64",
            name="ck_workflow_step_attempt_output_digest",
        ),
        sa.ForeignKeyConstraint(
            ["step_execution_id"],
            ["controlled_workflow_step_executions.step_execution_id"],
            name="fk_workflow_step_attempt_execution",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "step_execution_id",
            "attempt_number",
            name="uq_workflow_step_attempt_number",
        ),
    )
    op.create_index(
        "ix_workflow_step_attempt_time",
        "controlled_workflow_step_attempts",
        ["step_execution_id", "attempt_number"],
    )

    op.create_table(
        "controlled_workflow_evidence_links",
        sa.Column("evidence_link_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("step_execution_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_kind", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_kind IN ('retrieval', 'citation', 'evidence_bundle', "
            "'controlled_effect', 'controlled_rollback', 'approval', 'model_output')",
            name="ck_workflow_evidence_kind",
        ),
        sa.CheckConstraint(
            "length(evidence_digest) = 64",
            name="ck_workflow_evidence_digest",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"],
            ["controlled_workflow_executions.execution_id"],
            name="fk_workflow_evidence_execution",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["step_execution_id"],
            ["controlled_workflow_step_executions.step_execution_id"],
            name="fk_workflow_evidence_step",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_link_id"),
        sa.UniqueConstraint(
            "workflow_execution_id",
            "step_execution_id",
            "evidence_kind",
            "evidence_id",
            name="uq_workflow_evidence_link",
        ),
    )
    op.create_index(
        "ix_workflow_evidence_execution",
        "controlled_workflow_evidence_links",
        ["workflow_execution_id", "step_execution_id"],
    )

    for table in IMMUTABLE_TABLES:
        _protect(table)


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        _unprotect(table)
    op.drop_index(
        "ix_workflow_evidence_execution",
        table_name="controlled_workflow_evidence_links",
    )
    op.drop_table("controlled_workflow_evidence_links")
    op.drop_index(
        "ix_workflow_step_attempt_time",
        table_name="controlled_workflow_step_attempts",
    )
    op.drop_table("controlled_workflow_step_attempts")
    op.drop_index(
        "ix_workflow_step_transition_time",
        table_name="controlled_workflow_step_transitions",
    )
    op.drop_table("controlled_workflow_step_transitions")
    op.drop_index(
        "ix_workflow_step_execution_run",
        table_name="controlled_workflow_step_executions",
    )
    op.drop_index(
        "ix_workflow_step_execution_ready",
        table_name="controlled_workflow_step_executions",
    )
    op.drop_table("controlled_workflow_step_executions")
    op.drop_index(
        "ix_workflow_execution_transition_time",
        table_name="controlled_workflow_execution_transitions",
    )
    op.drop_table("controlled_workflow_execution_transitions")
    op.drop_table("controlled_workflow_plan_snapshots")
    op.drop_index(
        "ix_controlled_workflow_executions_trace_id",
        table_name="controlled_workflow_executions",
    )
    op.drop_index(
        "ix_workflow_execution_status",
        table_name="controlled_workflow_executions",
    )
    op.drop_index(
        "ix_workflow_execution_scope_time",
        table_name="controlled_workflow_executions",
    )
    op.drop_table("controlled_workflow_executions")
    op.drop_index(
        "ix_workflow_dependency_step",
        table_name="controlled_workflow_dependencies",
    )
    op.drop_table("controlled_workflow_dependencies")
    op.drop_index(
        "ix_workflow_step_version_order",
        table_name="controlled_workflow_steps",
    )
    op.drop_table("controlled_workflow_steps")
    op.drop_index(
        "ix_workflow_version_state_time",
        table_name="controlled_workflow_version_states",
    )
    op.drop_table("controlled_workflow_version_states")
    op.drop_index(
        "ix_controlled_workflow_versions_trace_id",
        table_name="controlled_workflow_versions",
    )
    op.drop_index(
        "ix_workflow_version_definition_time",
        table_name="controlled_workflow_versions",
    )
    op.drop_table("controlled_workflow_versions")
    op.drop_index(
        "ix_controlled_workflow_definitions_trace_id",
        table_name="controlled_workflow_definitions",
    )
    op.drop_index(
        "ix_workflow_definition_scope_time",
        table_name="controlled_workflow_definitions",
    )
    op.drop_table("controlled_workflow_definitions")
    _replace_domain_event_constraints(ORIGINAL_EVENT_TYPES, ORIGINAL_SUBJECT_KINDS)
