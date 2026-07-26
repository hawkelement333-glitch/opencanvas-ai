"""Add collaboration roles and permission authority.

Revision ID: 20260725_0022
Revises: 20260725_0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0022"
down_revision: str | None = "20260725_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_VERSION = "collaboration-policy-v1"
NEW_EVENT_TYPES = (
    "membership.role_changed",
    "membership.suspended",
    "membership.restored",
    "membership.removed",
    "approval_authority.assigned",
    "approval_authority.replaced",
    "approval_authority.revoked",
)
NEW_SUBJECT_KIND = "approval_authority_assignment"
BASE_EVENT_TYPES = (
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
    "invitation.created",
    "invitation.accepted",
    "invitation.declined",
    "invitation.expired",
    "invitation.revoked",
    "membership.activated",
)
BASE_SUBJECT_KINDS = (
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
    "agent_identity",
    "agent_version",
    "agent_activation",
    "agent_invocation",
    "agent_proposal",
    "agent_evaluation",
    "communication_revision",
    "workspace_invitation",
    "workspace_membership",
)
BASE_REQUEST_OPERATIONS = (
    "invitation.create",
    "invitation.resend",
    "invitation.accept",
    "invitation.decline",
    "invitation.revoke",
)
NEW_REQUEST_OPERATIONS = (
    "membership.role.change",
    "membership.suspend",
    "membership.restore",
    "membership.remove",
    "approval_authority.assign",
    "approval_authority.replace",
    "approval_authority.revoke",
)
CAPABILITIES = (
    "workspace.metadata.read",
    "canvas.snapshot.read",
    "context.selected.read",
    "document.version.read",
    "trace.scoped.read",
    "retrieval.selected.search",
    "draft.note.create",
    "draft.answer.create",
    "canvas.note.create",
    "canvas.note.update",
    "canvas.note.create.rollback",
    "canvas.note.update.rollback",
    "knowledge_graph.relationship.write",
    "workflow.step.execute",
    "evidence.bundle.create",
    "execution.cancel",
)
RESOURCE_KINDS = (
    "workspace",
    "canvas",
    "node",
    "document_version",
    "chunk",
    "trace",
    "canonical_relationship",
    "canonical_object",
)
NEW_IMMUTABLE_TABLES = (
    "collaboration_approval_authority_assignments",
    "collaboration_approval_authority_transitions",
    "collaboration_reviewer_eligibility_evidence",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _protect(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    "'collaboration evidence is append-only'); END"
                )
            )
        return
    function = f"reject_{table}_mutation"
    op.execute(
        sa.text(
            f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'collaboration evidence is append-only'; END; "
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
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"))
        return
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()"))


def _protect_domain_events() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_domain_events_{operation.lower()}_blocked "
                f"BEFORE {operation} ON domain_events BEGIN SELECT RAISE(ABORT, "
                "'domain event evidence is append-only'); END"
            )
        )


def _replace_checks(
    *,
    event_types: tuple[str, ...],
    subject_kinds: tuple[str, ...],
    request_operations: tuple[str, ...],
    request_result_kinds: tuple[str, ...],
    audit_subject_kinds: tuple[str, ...],
) -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        for table in (
            "domain_events",
            "collaboration_request_identities",
            "collaboration_audit_events",
        ):
            for operation in ("update", "delete"):
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"))
    with op.batch_alter_table("domain_events", recreate="always" if sqlite else "auto") as batch:
        batch.drop_constraint("ck_domain_events_type", type_="check")
        batch.drop_constraint("ck_domain_events_subject_kind", type_="check")
        batch.create_check_constraint(
            "ck_domain_events_type", f"event_type IN ({_in(event_types)})"
        )
        batch.create_check_constraint(
            "ck_domain_events_subject_kind",
            f"subject_kind IN ({_in(subject_kinds)})",
        )
    with op.batch_alter_table(
        "collaboration_request_identities", recreate="always" if sqlite else "auto"
    ) as batch:
        batch.drop_constraint("ck_collaboration_request_operation", type_="check")
        batch.drop_constraint("ck_collaboration_request_result_kind", type_="check")
        batch.create_check_constraint(
            "ck_collaboration_request_operation",
            f"operation IN ({_in(request_operations)})",
        )
        batch.create_check_constraint(
            "ck_collaboration_request_result_kind",
            f"result_kind IN ({_in(request_result_kinds)})",
        )
    with op.batch_alter_table(
        "collaboration_audit_events", recreate="always" if sqlite else "auto"
    ) as batch:
        batch.drop_constraint("ck_collaboration_audit_subject_kind", type_="check")
        batch.create_check_constraint(
            "ck_collaboration_audit_subject_kind",
            f"subject_kind IN ({_in(audit_subject_kinds)})",
        )
    if sqlite:
        _protect_domain_events()
        _protect("collaboration_request_identities")
        _protect("collaboration_audit_events")


def upgrade() -> None:
    _replace_checks(
        event_types=BASE_EVENT_TYPES + NEW_EVENT_TYPES,
        subject_kinds=(*BASE_SUBJECT_KINDS, NEW_SUBJECT_KIND),
        request_operations=BASE_REQUEST_OPERATIONS + NEW_REQUEST_OPERATIONS,
        request_result_kinds=(
            "workspace_invitation",
            "workspace_membership",
            "approval_authority_assignment",
        ),
        audit_subject_kinds=(
            "workspace_membership",
            "workspace_invitation",
            "approval_authority_assignment",
        ),
    )
    op.create_table(
        "collaboration_approval_authority_assignments",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer_membership_id", sa.Uuid(), nullable=False),
        sa.Column("issuer_user_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("maximum_risk_class", sa.String(32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conflict_policy", sa.String(32), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("supersedes_assignment_id", sa.Uuid(), nullable=True),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"capability IN ({_in(CAPABILITIES)})",
            name="ck_collaboration_approval_assignment_capability",
        ),
        sa.CheckConstraint(
            f"resource_kind IN ({_in(RESOURCE_KINDS)})",
            name="ck_collaboration_approval_assignment_resource_kind",
        ),
        sa.CheckConstraint(
            "maximum_risk_class IN ('r0_observation', 'r1_draft', "
            "'r2_transient_action', 'r3_durable_write')",
            name="ck_collaboration_approval_assignment_risk",
        ),
        sa.CheckConstraint(
            "conflict_policy = 'deny_self_review'",
            name="ck_collaboration_approval_assignment_conflict",
        ),
        sa.CheckConstraint(
            f"collaboration_policy_version = '{POLICY_VERSION}'",
            name="ck_collaboration_approval_assignment_policy",
        ),
        sa.CheckConstraint(
            "expires_at > valid_from",
            name="ck_collaboration_approval_assignment_time_order",
        ),
        sa.CheckConstraint(
            "length(scope_digest) = 64",
            name="ck_collaboration_approval_assignment_digest",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "reviewer_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_approval_assignment_reviewer_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issuer_membership_id", "issuer_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_approval_assignment_issuer_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_assignment_id"],
            ["collaboration_approval_authority_assignments.assignment_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("assignment_id"),
        sa.UniqueConstraint(
            "assignment_id",
            "membership_id",
            "reviewer_user_id",
            "workspace_id",
            name="uq_collaboration_approval_assignment_scope",
        ),
    )
    op.create_index(
        "ix_collaboration_approval_assignment_reviewer",
        "collaboration_approval_authority_assignments",
        ["workspace_id", "membership_id", "valid_from"],
    )
    op.create_index(
        "ix_collaboration_approval_assignment_scope",
        "collaboration_approval_authority_assignments",
        ["workspace_id", "capability", "resource_kind", "resource_id"],
    )
    op.create_table(
        "collaboration_approval_authority_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(16), nullable=True),
        sa.Column("current_state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_state IN ('active', 'revoked', 'superseded')",
            name="ck_collaboration_approval_transition_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('active', 'revoked', 'superseded')",
            name="ck_collaboration_approval_transition_previous_state",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_approval_transition_generation",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "membership_id", "reviewer_user_id", "workspace_id"],
            [
                "collaboration_approval_authority_assignments.assignment_id",
                "collaboration_approval_authority_assignments.membership_id",
                "collaboration_approval_authority_assignments.reviewer_user_id",
                "collaboration_approval_authority_assignments.workspace_id",
            ],
            name="fk_collaboration_approval_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint(
            "assignment_id",
            "sequence",
            name="uq_collaboration_approval_transition_sequence",
        ),
    )
    op.create_index(
        "ix_collaboration_approval_transition_current",
        "collaboration_approval_authority_transitions",
        ["assignment_id", "sequence"],
    )
    op.create_table(
        "collaboration_reviewer_eligibility_evidence",
        sa.Column("eligibility_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("deciding_user_id", sa.Uuid(), nullable=False),
        sa.Column("deciding_membership_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("decision_session_id", sa.Uuid(), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"collaboration_policy_version = '{POLICY_VERSION}'",
            name="ck_collaboration_reviewer_evidence_policy",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_reviewer_evidence_generation",
        ),
        sa.CheckConstraint(
            "length(scope_digest) = 64",
            name="ck_collaboration_reviewer_evidence_digest",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id", "execution_id", "requester_user_id", "workspace_id"],
            [
                "controlled_agent_approvals.approval_id",
                "controlled_agent_approvals.execution_id",
                "controlled_agent_approvals.user_id",
                "controlled_agent_approvals.workspace_id",
            ],
            name="fk_collaboration_reviewer_evidence_approval_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "deciding_membership_id", "deciding_user_id", "workspace_id"],
            [
                "collaboration_approval_authority_assignments.assignment_id",
                "collaboration_approval_authority_assignments.membership_id",
                "collaboration_approval_authority_assignments.reviewer_user_id",
                "collaboration_approval_authority_assignments.workspace_id",
            ],
            name="fk_collaboration_reviewer_evidence_assignment_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("eligibility_id"),
        sa.UniqueConstraint("approval_id", name="uq_collaboration_reviewer_evidence_approval"),
    )
    op.create_index(
        "ix_collaboration_reviewer_evidence_reviewer",
        "collaboration_reviewer_eligibility_evidence",
        ["workspace_id", "deciding_membership_id", "recorded_at"],
    )
    _replace_membership_guard(allow_role_changes=True)
    _install_approval_transition_guard()
    for table in NEW_IMMUTABLE_TABLES:
        _protect(table)


def _replace_membership_guard(*, allow_role_changes: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_workspace_membership_transition_valid"))
        if allow_role_changes:
            allowed = (
                "(NEW.previous_state = 'active' AND NEW.current_state = 'active' "
                "AND NEW.previous_role <> NEW.current_role "
                "AND NEW.previous_role <> 'owner' AND NEW.current_role <> 'owner') OR "
                "(NEW.previous_state = 'active' AND NEW.current_state = 'suspended' "
                "AND NEW.previous_role = NEW.current_role AND NEW.current_role <> 'owner') OR "
                "(NEW.previous_state = 'suspended' AND NEW.current_state = 'active' "
                "AND NEW.previous_role = NEW.current_role AND NEW.current_role <> 'owner') OR "
                "(NEW.previous_state IN ('active','suspended') "
                "AND NEW.current_state = 'removed' "
                "AND NEW.previous_role = NEW.current_role AND NEW.current_role <> 'owner')"
            )
        else:
            allowed = (
                "(NEW.previous_state = 'active' "
                "AND NEW.current_state IN ('suspended','removed') "
                "AND NEW.previous_role = NEW.current_role) OR "
                "(NEW.previous_state = 'suspended' "
                "AND NEW.current_state IN ('active','removed') "
                "AND NEW.previous_role = NEW.current_role)"
            )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_workspace_membership_transition_valid "
                "BEFORE INSERT ON workspace_membership_transitions BEGIN "
                "SELECT CASE WHEN NEW.sequence = 0 AND "
                "(NEW.previous_state IS NOT NULL OR NEW.previous_role IS NOT NULL) "
                "THEN RAISE(ABORT, 'invalid initial membership transition') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
                "SELECT 1 FROM workspace_membership_transitions p "
                "WHERE p.membership_id = NEW.membership_id "
                "AND p.sequence = NEW.sequence - 1 "
                "AND p.current_state = NEW.previous_state "
                "AND p.current_role = NEW.previous_role) "
                "THEN RAISE(ABORT, 'invalid membership transition sequence') END; "
                f"SELECT CASE WHEN NEW.sequence > 0 AND NOT ({allowed}) "
                "THEN RAISE(ABORT, 'invalid membership lifecycle transition') END; "
                "SELECT CASE WHEN NEW.current_state IN ('active','suspended') AND EXISTS ("
                "SELECT 1 FROM workspace_memberships m "
                "JOIN workspace_membership_transitions t ON t.membership_id = m.membership_id "
                "WHERE m.user_id = NEW.user_id AND m.workspace_id = NEW.workspace_id "
                "AND m.membership_id <> NEW.membership_id "
                "AND t.sequence = (SELECT MAX(x.sequence) "
                "FROM workspace_membership_transitions x "
                "WHERE x.membership_id = m.membership_id) "
                "AND t.current_state IN ('active','suspended')) "
                "THEN RAISE(ABORT, 'duplicate active membership') END; "
                "SELECT CASE WHEN NEW.current_role = 'owner' "
                "AND NEW.current_state IN ('active','suspended') AND NOT EXISTS ("
                "SELECT 1 FROM workspaces w WHERE w.id = NEW.workspace_id "
                "AND w.owner_id = NEW.user_id) "
                "THEN RAISE(ABORT, 'owner membership mismatch') END; "
                "SELECT CASE WHEN NEW.current_role = 'owner' "
                "AND NEW.current_state IN ('active','suspended') AND EXISTS ("
                "SELECT 1 FROM workspace_memberships m "
                "JOIN workspace_membership_transitions t ON t.membership_id = m.membership_id "
                "WHERE m.workspace_id = NEW.workspace_id "
                "AND m.membership_id <> NEW.membership_id "
                "AND t.sequence = (SELECT MAX(x.sequence) "
                "FROM workspace_membership_transitions x "
                "WHERE x.membership_id = m.membership_id) "
                "AND t.current_role = 'owner' "
                "AND t.current_state IN ('active','suspended')) "
                "THEN RAISE(ABORT, 'multiple workspace owners') END; END"
            )
        )
        return
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_workspace_membership_transition_valid "
            "ON workspace_membership_transitions"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_workspace_membership_transition()"))
    if allow_role_changes:
        allowed = (
            "(NEW.previous_state = 'active' AND NEW.current_state = 'active' "
            "AND NEW.previous_role <> NEW.current_role "
            "AND NEW.previous_role <> 'owner' AND NEW.current_role <> 'owner') OR "
            "(NEW.previous_state = 'active' AND NEW.current_state = 'suspended' "
            "AND NEW.previous_role = NEW.current_role AND NEW.current_role <> 'owner') OR "
            "(NEW.previous_state = 'suspended' AND NEW.current_state = 'active' "
            "AND NEW.previous_role = NEW.current_role AND NEW.current_role <> 'owner') OR "
            "(NEW.previous_state IN ('active','suspended') AND NEW.current_state = 'removed' "
            "AND NEW.previous_role = NEW.current_role AND NEW.current_role <> 'owner')"
        )
    else:
        allowed = (
            "(NEW.previous_state = 'active' AND NEW.current_state IN ('suspended','removed') "
            "AND NEW.previous_role = NEW.current_role) OR "
            "(NEW.previous_state = 'suspended' AND NEW.current_state IN ('active','removed') "
            "AND NEW.previous_role = NEW.current_role)"
        )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_workspace_membership_transition() RETURNS trigger AS $$ "
            "DECLARE prior workspace_membership_transitions%ROWTYPE; BEGIN "
            "IF NEW.sequence = 0 THEN "
            "IF NEW.previous_state IS NOT NULL OR NEW.previous_role IS NOT NULL "
            "THEN RAISE EXCEPTION 'invalid initial membership transition'; END IF; "
            "ELSE SELECT * INTO prior FROM workspace_membership_transitions "
            "WHERE membership_id = NEW.membership_id AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state IS DISTINCT FROM "
            "NEW.previous_state OR prior.current_role IS DISTINCT FROM NEW.previous_role "
            "THEN RAISE EXCEPTION 'invalid membership transition sequence'; END IF; "
            f"IF NOT ({allowed}) "
            "THEN RAISE EXCEPTION 'invalid membership lifecycle transition'; END IF; END IF; "
            "IF NEW.current_state IN ('active','suspended') AND EXISTS ("
            "SELECT 1 FROM workspace_memberships m "
            "JOIN workspace_membership_transitions t ON t.membership_id = m.membership_id "
            "WHERE m.user_id = NEW.user_id AND m.workspace_id = NEW.workspace_id "
            "AND m.membership_id <> NEW.membership_id "
            "AND t.sequence = (SELECT MAX(x.sequence) FROM workspace_membership_transitions x "
            "WHERE x.membership_id = m.membership_id) "
            "AND t.current_state IN ('active','suspended')) "
            "THEN RAISE EXCEPTION 'duplicate active membership'; END IF; "
            "IF NEW.current_role = 'owner' AND NEW.current_state IN ('active','suspended') "
            "AND NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.id = NEW.workspace_id "
            "AND w.owner_id = NEW.user_id) "
            "THEN RAISE EXCEPTION 'owner membership mismatch'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_workspace_membership_transition_valid "
            "BEFORE INSERT ON workspace_membership_transitions FOR EACH ROW "
            "EXECUTE FUNCTION validate_workspace_membership_transition()"
        )
    )


def _install_approval_transition_guard() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_collaboration_approval_transition_valid "
                "BEFORE INSERT ON collaboration_approval_authority_transitions BEGIN "
                "SELECT CASE WHEN NEW.sequence = 0 AND "
                "(NEW.previous_state IS NOT NULL OR NEW.current_state <> 'active') "
                "THEN RAISE(ABORT, 'invalid initial approval authority transition') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
                "SELECT 1 FROM collaboration_approval_authority_transitions p "
                "WHERE p.assignment_id = NEW.assignment_id "
                "AND p.sequence = NEW.sequence - 1 "
                "AND p.current_state = NEW.previous_state "
                "AND p.current_state = 'active') "
                "THEN RAISE(ABORT, 'invalid approval authority transition') END; "
                "SELECT CASE WHEN NEW.sequence > 0 "
                "AND NEW.current_state NOT IN ('revoked','superseded') "
                "THEN RAISE(ABORT, 'invalid approval authority lifecycle') END; END"
            )
        )
        return
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_approval_transition() "
            "RETURNS trigger AS $$ "
            "DECLARE prior collaboration_approval_authority_transitions%ROWTYPE; BEGIN "
            "IF NEW.sequence = 0 THEN "
            "IF NEW.previous_state IS NOT NULL OR NEW.current_state <> 'active' "
            "THEN RAISE EXCEPTION 'invalid initial approval authority transition'; END IF; "
            "ELSE SELECT * INTO prior FROM collaboration_approval_authority_transitions "
            "WHERE assignment_id = NEW.assignment_id AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state <> 'active' "
            "OR prior.current_state IS DISTINCT FROM NEW.previous_state "
            "OR NEW.current_state NOT IN ('revoked','superseded') "
            "THEN RAISE EXCEPTION 'invalid approval authority transition'; END IF; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_approval_transition_valid "
            "BEFORE INSERT ON collaboration_approval_authority_transitions FOR EACH ROW "
            "EXECUTE FUNCTION validate_collaboration_approval_transition()"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in NEW_IMMUTABLE_TABLES:
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError("Downgrade refused: Milestone 6.2 append-only evidence exists.")
    if bind.dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_collaboration_approval_transition_valid"))
    else:
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_collaboration_approval_transition_valid "
                "ON collaboration_approval_authority_transitions"
            )
        )
        op.execute(sa.text("DROP FUNCTION IF EXISTS validate_collaboration_approval_transition()"))
    for table in reversed(NEW_IMMUTABLE_TABLES):
        _unprotect(table)
    op.drop_index(
        "ix_collaboration_reviewer_evidence_reviewer",
        table_name="collaboration_reviewer_eligibility_evidence",
    )
    op.drop_table("collaboration_reviewer_eligibility_evidence")
    op.drop_index(
        "ix_collaboration_approval_transition_current",
        table_name="collaboration_approval_authority_transitions",
    )
    op.drop_table("collaboration_approval_authority_transitions")
    op.drop_index(
        "ix_collaboration_approval_assignment_scope",
        table_name="collaboration_approval_authority_assignments",
    )
    op.drop_index(
        "ix_collaboration_approval_assignment_reviewer",
        table_name="collaboration_approval_authority_assignments",
    )
    op.drop_table("collaboration_approval_authority_assignments")
    _replace_membership_guard(allow_role_changes=False)
    _replace_checks(
        event_types=BASE_EVENT_TYPES,
        subject_kinds=BASE_SUBJECT_KINDS,
        request_operations=BASE_REQUEST_OPERATIONS,
        request_result_kinds=("workspace_invitation", "workspace_membership"),
        audit_subject_kinds=("workspace_membership", "workspace_invitation"),
    )
