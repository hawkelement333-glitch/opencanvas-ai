"""Add immutable bounded Agent Studio definitions and evidence.

Revision ID: 20260725_0020
Revises: 20260725_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0020"
down_revision: str | None = "20260725_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIOR_EVENT_TYPES = (
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
AGENT_EVENT_TYPES = (
    "agent.identity.created",
    "agent.version.created",
    "agent.version.validated",
    "agent.version.validation_failed",
    "agent.version.activated",
    "agent.activation.requested",
    "agent.activation.approved",
    "agent.activation.denied",
    "agent.invocation.started",
    "agent.proposal.created",
    "agent.proposal.accepted",
    "agent.proposal.rejected",
    "agent.evaluation.recorded",
    "agent.communication.revision_proposed",
    "agent.communication.revision_accepted",
    "agent.communication.revision_rejected",
    "agent.suspended",
    "agent.retired",
)
PRIOR_SUBJECT_KINDS = (
    "canonical_resource",
    "graph_relationship",
    "controlled_execution",
    "controlled_effect",
    "controlled_rollback",
    "evidence_bundle",
    "citation",
    "workflow_definition",
    "workflow_version",
    "workflow_execution",
    "workflow_step",
)
AGENT_SUBJECT_KINDS = (
    "agent_identity",
    "agent_version",
    "agent_activation",
    "agent_invocation",
    "agent_proposal",
    "agent_evaluation",
    "communication_revision",
)
IMMUTABLE_TABLES = (
    "bounded_agent_identities",
    "bounded_agent_lifecycle_states",
    "bounded_agent_versions",
    "bounded_agent_version_states",
    "bounded_agent_workflow_bindings",
    "bounded_agent_capability_requirements",
    "bounded_agent_validation_reports",
    "bounded_agent_activation_requests",
    "bounded_agent_activation_decisions",
    "bounded_agent_invocations",
    "bounded_agent_proposals",
    "bounded_agent_proposal_decisions",
    "bounded_agent_evaluations",
    "bounded_communication_profiles",
    "bounded_communication_profile_versions",
    "bounded_communication_revisions",
    "bounded_communication_revision_decisions",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_event_constraints(
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
                    "'bounded agent evidence is append-only'); END"
                )
            )
        return
    function = f"reject_{table}_mutation"
    op.execute(
        sa.text(
            f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'bounded agent evidence is append-only'; END; "
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
    _replace_event_constraints(
        PRIOR_EVENT_TYPES + AGENT_EVENT_TYPES,
        PRIOR_SUBJECT_KINDS + AGENT_SUBJECT_KINDS,
    )
    op.create_table(
        "bounded_agent_identities",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'bounded-agent-studio-v1'",
            name="ck_bounded_agent_schema",
        ),
        sa.CheckConstraint(
            "kind IN ('workflow_assistant', 'grounded_research_assistant', "
            "'document_analysis_assistant', 'controlled_operations_assistant', "
            "'communication_assistant', 'evaluation_assistant', 'agent_design_assistant')",
            name="ck_bounded_agent_kind",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_bounded_agent_request_digest",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_id"),
        sa.UniqueConstraint(
            "agent_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_scope",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_agent_create_idempotency",
        ),
    )
    op.create_index(
        "ix_bounded_agent_scope_time",
        "bounded_agent_identities",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index(
        "ix_bounded_agent_identities_trace_id",
        "bounded_agent_identities",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_lifecycle_states",
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('draft', 'proposed', 'validation_failed', 'validated', "
            "'awaiting_activation_approval', 'active', 'suspended', 'superseded', "
            "'retired', 'rejected')",
            name="ck_bounded_agent_state",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_bounded_agent_state_sequence"),
        sa.ForeignKeyConstraint(
            ["agent_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_identities.agent_id",
                "bounded_agent_identities.user_id",
                "bounded_agent_identities.workspace_id",
                "bounded_agent_identities.canvas_id",
            ],
            name="fk_bounded_agent_state_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("state_id"),
        sa.UniqueConstraint(
            "agent_id",
            "sequence",
            name="uq_bounded_agent_state_sequence",
        ),
    )
    op.create_index(
        "ix_bounded_agent_state_time",
        "bounded_agent_lifecycle_states",
        ["agent_id", "sequence"],
    )

    op.create_table(
        "bounded_agent_versions",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(2000), nullable=False),
        sa.Column("system_instruction", sa.Text(), nullable=False),
        sa.Column("prompt_template_version", sa.String(128), nullable=False),
        sa.Column("selected_context_policy", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("communication_policy", sa.JSON(), nullable=False),
        sa.Column("evaluation_policy", sa.String(48), nullable=False),
        sa.Column("risk_class", sa.String(32), nullable=False),
        sa.Column("normalized_definition", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'bounded-agent-definition-v1'",
            name="ck_bounded_agent_version_schema",
        ),
        sa.CheckConstraint("version_number > 0", name="ck_bounded_agent_version_number"),
        sa.CheckConstraint(
            "provider IN ('mock', 'openai')",
            name="ck_bounded_agent_version_provider",
        ),
        sa.CheckConstraint(
            "risk_class IN ('r0_observation', 'r1_draft', 'r2_transient_action', "
            "'r3_durable_write')",
            name="ck_bounded_agent_version_risk",
        ),
        sa.CheckConstraint(
            "selected_context_policy IN ('required_explicit', 'optional_explicit')",
            name="ck_bounded_agent_context_policy",
        ),
        sa.CheckConstraint(
            "evaluation_policy IN ('human_review', 'deterministic_evidence_review')",
            name="ck_bounded_agent_evaluation_policy",
        ),
        sa.CheckConstraint(
            "length(content_digest) = 64",
            name="ck_bounded_agent_version_digest",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_identities.agent_id",
                "bounded_agent_identities.user_id",
                "bounded_agent_identities.workspace_id",
                "bounded_agent_identities.canvas_id",
            ],
            name="fk_bounded_agent_version_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"],
            ["bounded_agent_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint(
            "agent_id",
            "version_number",
            name="uq_bounded_agent_version_number",
        ),
        sa.UniqueConstraint(
            "version_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_version_scope",
        ),
        sa.UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_bounded_agent_version_idempotency",
        ),
    )
    op.create_index(
        "ix_bounded_agent_version_time",
        "bounded_agent_versions",
        ["agent_id", "version_number"],
    )
    op.create_index(
        "ix_bounded_agent_versions_trace_id",
        "bounded_agent_versions",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_version_states",
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('draft', 'proposed', 'validation_failed', 'validated', "
            "'awaiting_activation_approval', 'approved', 'active', 'superseded', "
            "'rejected', 'retired')",
            name="ck_bounded_agent_version_state",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_bounded_agent_version_state_sequence"),
        sa.ForeignKeyConstraint(
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_version_state_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("state_id"),
        sa.UniqueConstraint(
            "version_id",
            "sequence",
            name="uq_bounded_agent_version_state_sequence",
        ),
    )
    op.create_index(
        "ix_bounded_agent_version_state_time",
        "bounded_agent_version_states",
        ["version_id", "sequence"],
    )

    op.create_table(
        "bounded_agent_workflow_bindings",
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("workflow_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0 AND ordinal < 16",
            name="ck_bounded_agent_workflow_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_workflow_agent_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_versions.version_id",
                "controlled_workflow_versions.user_id",
                "controlled_workflow_versions.workspace_id",
                "controlled_workflow_versions.canvas_id",
            ],
            name="fk_bounded_agent_workflow_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint(
            "agent_version_id",
            "workflow_version_id",
            name="uq_bounded_agent_workflow_binding",
        ),
    )
    op.create_index(
        "ix_bounded_agent_workflow_order",
        "bounded_agent_workflow_bindings",
        ["agent_version_id", "ordinal"],
    )

    op.create_table(
        "bounded_agent_capability_requirements",
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("resource_kind", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability IN ('workspace.metadata.read', 'canvas.snapshot.read', "
            "'context.selected.read', 'document.version.read', 'trace.scoped.read', "
            "'retrieval.selected.search', 'draft.note.create', 'draft.answer.create', "
            "'canvas.note.create', 'canvas.note.update', 'canvas.note.create.rollback', "
            "'canvas.note.update.rollback', 'knowledge_graph.relationship.write', "
            "'workflow.step.execute', 'evidence.bundle.create', 'execution.cancel')",
            name="ck_bounded_agent_capability",
        ),
        sa.CheckConstraint(
            "resource_kind IN ('workspace', 'canvas', 'node', 'document_version', "
            "'chunk', 'trace', 'canonical_relationship', 'canonical_object')",
            name="ck_bounded_agent_resource_kind",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_capability_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("requirement_id"),
        sa.UniqueConstraint(
            "agent_version_id",
            "capability",
            "resource_kind",
            name="uq_bounded_agent_capability_requirement",
        ),
    )
    op.create_index(
        "ix_bounded_agent_capability_version",
        "bounded_agent_capability_requirements",
        ["agent_version_id"],
    )

    op.create_table(
        "bounded_agent_validation_reports",
        sa.Column("validation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(48), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("registry_versions", sa.JSON(), nullable=False),
        sa.Column("validator_version", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('valid', 'invalid_schema', 'invalid_workflow', "
            "'invalid_capability', 'invalid_scope', 'invalid_provider', 'invalid_limits', "
            "'invalid_prompt_contract', 'invalid_communication_policy', "
            "'risk_exceeds_allowed_boundary', 'approval_required', 'unsupported_version')",
            name="ck_bounded_agent_validation_outcome",
        ),
        sa.CheckConstraint(
            "length(content_digest) = 64",
            name="ck_bounded_agent_validation_digest",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_validation_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("validation_id"),
        sa.UniqueConstraint(
            "agent_version_id",
            "content_digest",
            name="uq_bounded_agent_validation_digest",
        ),
        sa.UniqueConstraint(
            "validation_id",
            "agent_version_id",
            name="uq_bounded_agent_validation_version",
        ),
    )
    op.create_index(
        "ix_bounded_agent_validation_time",
        "bounded_agent_validation_reports",
        ["agent_version_id", "created_at"],
    )
    op.create_index(
        "ix_bounded_agent_validation_reports_trace_id",
        "bounded_agent_validation_reports",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_activation_requests",
        sa.Column("activation_request_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("validation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("authority_summary", sa.JSON(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_bounded_agent_activation_digest",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_bounded_agent_activation_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_activation_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validation_id", "agent_version_id"],
            [
                "bounded_agent_validation_reports.validation_id",
                "bounded_agent_validation_reports.agent_version_id",
            ],
            name="fk_bounded_agent_activation_validation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("activation_request_id"),
        sa.UniqueConstraint(
            "agent_version_id",
            "idempotency_key",
            name="uq_bounded_agent_activation_idempotency",
        ),
        sa.UniqueConstraint(
            "activation_request_id",
            "agent_version_id",
            name="uq_bounded_agent_activation_version",
        ),
    )
    op.create_index(
        "ix_bounded_agent_activation_time",
        "bounded_agent_activation_requests",
        ["agent_version_id", "created_at"],
    )
    op.create_index(
        "ix_bounded_agent_activation_requests_trace_id",
        "bounded_agent_activation_requests",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_activation_decisions",
        sa.Column("activation_decision_id", sa.Uuid(), nullable=False),
        sa.Column("activation_request_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'denied')",
            name="ck_bounded_agent_activation_decision",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_bounded_agent_decision_digest",
        ),
        sa.ForeignKeyConstraint(
            ["activation_request_id", "agent_version_id"],
            [
                "bounded_agent_activation_requests.activation_request_id",
                "bounded_agent_activation_requests.agent_version_id",
            ],
            name="fk_bounded_agent_activation_decision_request",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("activation_decision_id"),
        sa.UniqueConstraint(
            "activation_request_id",
            name="uq_bounded_agent_activation_decision",
        ),
    )
    op.create_index(
        "ix_bounded_agent_activation_decision_time",
        "bounded_agent_activation_decisions",
        ["agent_version_id", "decided_at"],
    )
    op.create_index(
        "ix_bounded_agent_activation_decisions_trace_id",
        "bounded_agent_activation_decisions",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_invocations",
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("selected_object_ids", sa.JSON(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_bounded_agent_invocation_digest",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_versions.version_id",
                "bounded_agent_versions.user_id",
                "bounded_agent_versions.workspace_id",
                "bounded_agent_versions.canvas_id",
            ],
            name="fk_bounded_agent_invocation_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id", "user_id", "workspace_id", "canvas_id"],
            [
                "controlled_workflow_executions.execution_id",
                "controlled_workflow_executions.user_id",
                "controlled_workflow_executions.workspace_id",
                "controlled_workflow_executions.canvas_id",
            ],
            name="fk_bounded_agent_invocation_workflow",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("invocation_id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_agent_invocation_idempotency",
        ),
        sa.UniqueConstraint(
            "invocation_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_invocation_scope",
        ),
    )
    op.create_index(
        "ix_bounded_agent_invocation_time",
        "bounded_agent_invocations",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "ix_bounded_agent_invocations_trace_id",
        "bounded_agent_invocations",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_proposals",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("source_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("source_kind", sa.String(48), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('agent_creation', 'agent_version_improvement', 'workflow_binding', "
            "'capability_requirement', 'provider_policy', 'communication_revision', "
            "'evaluation_recommendation')",
            name="ck_bounded_agent_proposal_kind",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_bounded_agent_proposal_request",
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64",
            name="ck_bounded_agent_proposal_payload",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["bounded_agent_identities.agent_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_invocation_id"],
            ["bounded_agent_invocations.invocation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_agent_proposal_idempotency",
        ),
        sa.UniqueConstraint(
            "proposal_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_agent_proposal_scope",
        ),
    )
    op.create_index(
        "ix_bounded_agent_proposal_time",
        "bounded_agent_proposals",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index(
        "ix_bounded_agent_proposals_trace_id",
        "bounded_agent_proposals",
        ["trace_id"],
    )

    op.create_table(
        "bounded_agent_proposal_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("resulting_agent_id", sa.Uuid(), nullable=True),
        sa.Column("resulting_version_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_bounded_agent_proposal_decision",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_proposals.proposal_id",
                "bounded_agent_proposals.user_id",
                "bounded_agent_proposals.workspace_id",
                "bounded_agent_proposals.canvas_id",
            ],
            name="fk_bounded_agent_proposal_decision_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint(
            "proposal_id",
            name="uq_bounded_agent_proposal_decision",
        ),
    )

    op.create_table(
        "bounded_agent_evaluations",
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(48), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(2000), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('meets_requirements', 'partially_meets_requirements', "
            "'fails_requirements', 'unsafe_result', 'insufficient_evidence', "
            "'bounded_result', 'evaluation_unavailable')",
            name="ck_bounded_agent_evaluation_outcome",
        ),
        sa.CheckConstraint(
            "length(evidence_digest) = 64",
            name="ck_bounded_agent_evaluation_digest",
        ),
        sa.ForeignKeyConstraint(
            ["invocation_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_invocations.invocation_id",
                "bounded_agent_invocations.user_id",
                "bounded_agent_invocations.workspace_id",
                "bounded_agent_invocations.canvas_id",
            ],
            name="fk_bounded_agent_evaluation_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evaluation_id"),
        sa.UniqueConstraint(
            "invocation_id",
            "idempotency_key",
            name="uq_bounded_agent_evaluation_idempotency",
        ),
    )
    op.create_index(
        "ix_bounded_agent_evaluation_time",
        "bounded_agent_evaluations",
        ["invocation_id", "created_at"],
    )
    op.create_index(
        "ix_bounded_agent_evaluations_trace_id",
        "bounded_agent_evaluations",
        ["trace_id"],
    )

    op.create_table(
        "bounded_communication_profiles",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_bounded_profile_request_digest",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canvas_id"], ["canvases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.UniqueConstraint(
            "profile_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_communication_profile_scope",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_communication_profile_idempotency",
        ),
    )
    op.create_index(
        "ix_bounded_communication_profile_time",
        "bounded_communication_profiles",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )

    op.create_table(
        "bounded_communication_profile_versions",
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("audience", sa.String(24), nullable=False),
        sa.Column("reading_level", sa.String(24), nullable=False),
        sa.Column("formality", sa.String(24), nullable=False),
        sa.Column("verbosity", sa.String(24), nullable=False),
        sa.Column("technical_depth", sa.String(24), nullable=False),
        sa.Column("orwell_rules", sa.Boolean(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "audience IN ('general', 'executive', 'technical', 'academic')",
            name="ck_bounded_profile_audience",
        ),
        sa.CheckConstraint(
            "reading_level IN ('plain', 'standard', 'advanced')",
            name="ck_bounded_profile_reading_level",
        ),
        sa.CheckConstraint(
            "formality IN ('conversational', 'neutral', 'formal')",
            name="ck_bounded_profile_formality",
        ),
        sa.CheckConstraint(
            "verbosity IN ('concise', 'balanced', 'detailed')",
            name="ck_bounded_profile_verbosity",
        ),
        sa.CheckConstraint(
            "technical_depth IN ('low', 'medium', 'high')",
            name="ck_bounded_profile_technical_depth",
        ),
        sa.CheckConstraint(
            "length(content_digest) = 64",
            name="ck_bounded_profile_digest",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_communication_profiles.profile_id",
                "bounded_communication_profiles.user_id",
                "bounded_communication_profiles.workspace_id",
                "bounded_communication_profiles.canvas_id",
            ],
            name="fk_bounded_profile_version_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("profile_version_id"),
        sa.UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_bounded_profile_version_number",
        ),
        sa.UniqueConstraint(
            "profile_id",
            "idempotency_key",
            name="uq_bounded_profile_version_idempotency",
        ),
        sa.UniqueConstraint(
            "profile_version_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            name="uq_bounded_profile_version_scope",
        ),
    )

    op.create_table(
        "bounded_communication_revisions",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("revised_text", sa.Text(), nullable=False),
        sa.Column("original_digest", sa.String(64), nullable=False),
        sa.Column("revised_digest", sa.String(64), nullable=False),
        sa.Column("protected_facts", sa.JSON(), nullable=False),
        sa.Column("protected_facts_digest", sa.String(64), nullable=False),
        sa.Column("preservation_status", sa.String(16), nullable=False),
        sa.Column("safe_failure_code", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "preservation_status IN ('preserved', 'rejected')",
            name="ck_bounded_communication_preservation",
        ),
        sa.CheckConstraint(
            "length(original_digest) = 64",
            name="ck_bounded_revision_original_digest",
        ),
        sa.CheckConstraint(
            "length(revised_digest) = 64",
            name="ck_bounded_revision_revised_digest",
        ),
        sa.CheckConstraint(
            "length(protected_facts_digest) = 64",
            name="ck_bounded_revision_facts_digest",
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id", "user_id", "workspace_id", "canvas_id"],
            [
                "bounded_communication_profile_versions.profile_version_id",
                "bounded_communication_profile_versions.user_id",
                "bounded_communication_profile_versions.workspace_id",
                "bounded_communication_profile_versions.canvas_id",
            ],
            name="fk_bounded_revision_profile_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_invocation_id"],
            ["bounded_agent_invocations.invocation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_bounded_communication_revision_idempotency",
        ),
    )
    op.create_index(
        "ix_bounded_communication_revision_time",
        "bounded_communication_revisions",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )

    op.create_table(
        "bounded_communication_revision_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_bounded_revision_decision",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["bounded_communication_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint(
            "revision_id",
            name="uq_bounded_communication_revision_decision",
        ),
    )

    for table in IMMUTABLE_TABLES:
        _protect(table)


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        _unprotect(table)
        op.drop_table(table)
    _replace_event_constraints(PRIOR_EVENT_TYPES, PRIOR_SUBJECT_KINDS)
