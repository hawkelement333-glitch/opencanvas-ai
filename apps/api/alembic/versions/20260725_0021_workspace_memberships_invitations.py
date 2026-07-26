"""Add workspace memberships and secure invitation evidence.

Revision ID: 20260725_0021
Revises: 20260725_0020
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0021"
down_revision: str | None = "20260725_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_VERSION = "collaboration-policy-v1"
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
COLLABORATION_EVENT_TYPES = (
    "invitation.created",
    "invitation.accepted",
    "invitation.declined",
    "invitation.expired",
    "invitation.revoked",
    "membership.activated",
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
    "agent_identity",
    "agent_version",
    "agent_activation",
    "agent_invocation",
    "agent_proposal",
    "agent_evaluation",
    "communication_revision",
)
COLLABORATION_SUBJECT_KINDS = ("workspace_invitation", "workspace_membership")
IMMUTABLE_TABLES = (
    "collaboration_audit_events",
    "workspace_memberships",
    "workspace_membership_transitions",
    "workspace_invitations",
    "workspace_invitation_transitions",
    "workspace_invitation_secret_versions",
    "workspace_invitation_delivery_attempts",
    "collaboration_request_identities",
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
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()"))


def upgrade() -> None:
    _replace_event_constraints(
        PRIOR_EVENT_TYPES + COLLABORATION_EVENT_TYPES,
        PRIOR_SUBJECT_KINDS + COLLABORATION_SUBJECT_KINDS,
    )
    op.create_table(
        "collaboration_audit_events",
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_kind", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("metadata_digest", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "subject_kind IN ('workspace_membership', 'workspace_invitation')",
            name="ck_collaboration_audit_subject_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed')",
            name="ck_collaboration_audit_outcome",
        ),
        sa.CheckConstraint(
            "length(metadata_digest) = 64",
            name="ck_collaboration_audit_metadata_digest",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("audit_event_id"),
    )
    op.create_index(
        "ix_collaboration_audit_workspace_time",
        "collaboration_audit_events",
        ["workspace_id", "recorded_at", "audit_event_id"],
    )
    op.create_index(
        "ix_collaboration_audit_trace",
        "collaboration_audit_events",
        ["trace_id"],
    )

    op.create_table(
        "workspace_memberships",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_invitation_id", sa.Uuid(), nullable=True),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"collaboration_policy_version = '{POLICY_VERSION}'",
            name="ck_workspace_memberships_policy",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.UniqueConstraint(
            "membership_id",
            "user_id",
            "workspace_id",
            name="uq_workspace_memberships_scope",
        ),
        sa.UniqueConstraint(
            "accepted_invitation_id",
            name="uq_workspace_memberships_accepted_invitation",
        ),
    )
    op.create_index(
        "ix_workspace_memberships_user_workspace",
        "workspace_memberships",
        ["user_id", "workspace_id", "created_at"],
    )
    op.create_index(
        "ix_workspace_memberships_workspace_time",
        "workspace_memberships",
        ["workspace_id", "created_at", "membership_id"],
    )

    op.create_table(
        "workspace_invitations",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email_normalized", sa.String(320), nullable=False),
        sa.Column("recipient_digest", sa.String(64), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=True),
        sa.Column("intended_role", sa.String(24), nullable=False),
        sa.Column("inviter_user_id", sa.Uuid(), nullable=False),
        sa.Column("inviter_membership_id", sa.Uuid(), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "intended_role IN ('administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_workspace_invitations_role",
        ),
        sa.CheckConstraint(
            f"collaboration_policy_version = '{POLICY_VERSION}'",
            name="ck_workspace_invitations_policy",
        ),
        sa.CheckConstraint(
            "length(recipient_digest) = 64 AND length(request_digest) = 64",
            name="ck_workspace_invitations_digests",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_workspace_invitations_expiry_order",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["inviter_membership_id", "inviter_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_workspace_invitation_inviter_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("invitation_id"),
        sa.UniqueConstraint(
            "invitation_id",
            "workspace_id",
            name="uq_workspace_invitations_scope",
        ),
    )
    op.create_index(
        "ix_workspace_invitations_workspace_recipient",
        "workspace_invitations",
        ["workspace_id", "recipient_digest", "created_at"],
    )
    op.create_index(
        "ix_workspace_invitations_workspace_expiry",
        "workspace_invitations",
        ["workspace_id", "expires_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_workspace_membership_accepted_invitation_scope",
            "workspace_memberships",
            "workspace_invitations",
            ["accepted_invitation_id", "workspace_id"],
            ["invitation_id", "workspace_id"],
            ondelete="RESTRICT",
        )
    else:
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_workspace_membership_invitation_scope "
                "BEFORE INSERT ON workspace_memberships "
                "WHEN NEW.accepted_invitation_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM workspace_invitations i "
                "WHERE i.invitation_id = NEW.accepted_invitation_id "
                "AND i.workspace_id = NEW.workspace_id) "
                "BEGIN SELECT RAISE(ABORT, 'membership invitation scope mismatch'); END"
            )
        )

    op.create_table(
        "workspace_membership_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(16), nullable=True),
        sa.Column("current_state", sa.String(16), nullable=False),
        sa.Column("previous_role", sa.String(24), nullable=True),
        sa.Column("current_role", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_state IN ('active', 'suspended', 'removed')",
            name="ck_workspace_membership_transition_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('active', 'suspended', 'removed')",
            name="ck_workspace_membership_transition_previous_state",
        ),
        sa.CheckConstraint(
            "current_role IN ('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_workspace_membership_transition_role",
        ),
        sa.CheckConstraint(
            "previous_role IS NULL OR previous_role IN "
            "('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_workspace_membership_transition_previous_role",
        ),
        sa.CheckConstraint(
            f"collaboration_policy_version = '{POLICY_VERSION}'",
            name="ck_workspace_membership_transition_policy",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_workspace_membership_transition_sequence",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_workspace_membership_transition_generation",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_workspace_membership_transition_scope",
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
            "membership_id",
            "sequence",
            name="uq_workspace_membership_transition_sequence",
        ),
    )
    op.create_index(
        "ix_workspace_membership_transition_current",
        "workspace_membership_transitions",
        ["membership_id", "sequence"],
    )
    op.create_index(
        "ix_workspace_membership_transition_workspace",
        "workspace_membership_transitions",
        ["workspace_id", "recorded_at"],
    )

    op.create_table(
        "workspace_invitation_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(16), nullable=True),
        sa.Column("current_state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("result_membership_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_state IN ('pending', 'accepted', 'declined', 'expired', 'revoked')",
            name="ck_workspace_invitation_transition_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('pending', 'accepted', 'declined', 'expired', 'revoked')",
            name="ck_workspace_invitation_transition_previous_state",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_workspace_invitation_transition_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "workspace_id"],
            ["workspace_invitations.invitation_id", "workspace_invitations.workspace_id"],
            name="fk_workspace_invitation_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_membership_id"],
            ["workspace_memberships.membership_id"],
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
            "invitation_id",
            "sequence",
            name="uq_workspace_invitation_transition_sequence",
        ),
        sa.UniqueConstraint(
            "invitation_id",
            "current_state",
            name="uq_workspace_invitation_terminal_once",
        ),
    )
    op.create_index(
        "ix_workspace_invitation_transition_current",
        "workspace_invitation_transitions",
        ["invitation_id", "sequence"],
    )

    op.create_table(
        "workspace_invitation_secret_versions",
        sa.Column("secret_version_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_workspace_invitation_secret_sequence",
        ),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_workspace_invitation_secret_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "workspace_id"],
            ["workspace_invitations.invitation_id", "workspace_invitations.workspace_id"],
            name="fk_workspace_invitation_secret_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("secret_version_id"),
        sa.UniqueConstraint(
            "invitation_id",
            "sequence",
            name="uq_workspace_invitation_secret_sequence",
        ),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitation_secret_hash"),
    )
    op.create_index(
        "ix_workspace_invitation_secret_current",
        "workspace_invitation_secret_versions",
        ["invitation_id", "sequence"],
    )

    op.create_table(
        "workspace_invitation_delivery_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("secret_sequence", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('development_token', 'smtp')",
            name="ck_workspace_invitation_delivery_channel",
        ),
        sa.CheckConstraint(
            "outcome IN ('delivered', 'failed')",
            name="ck_workspace_invitation_delivery_outcome",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_workspace_invitation_delivery_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "workspace_id"],
            ["workspace_invitations.invitation_id", "workspace_invitations.workspace_id"],
            name="fk_workspace_invitation_delivery_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "invitation_id",
            "sequence",
            name="uq_workspace_invitation_delivery_sequence",
        ),
    )
    op.create_index(
        "ix_workspace_invitation_delivery_recent",
        "workspace_invitation_delivery_attempts",
        ["invitation_id", "recorded_at"],
    )

    op.create_table(
        "collaboration_request_identities",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("result_kind", sa.String(32), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('invitation.create', 'invitation.resend', "
            "'invitation.accept', 'invitation.decline', 'invitation.revoke')",
            name="ck_collaboration_request_operation",
        ),
        sa.CheckConstraint(
            "result_kind IN ('workspace_invitation', 'workspace_membership')",
            name="ck_collaboration_request_result_kind",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_collaboration_request_digest",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("request_id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "workspace_id",
            "operation",
            "idempotency_key",
            name="uq_collaboration_request_scope",
        ),
    )
    op.create_index(
        "ix_collaboration_request_created",
        "collaboration_request_identities",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "workspace_authority_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("last_trace_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_workspace_authority_generation",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    _install_lifecycle_guards()
    for table in IMMUTABLE_TABLES:
        _protect(table)
    _backfill_owner_memberships()


def _install_lifecycle_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
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
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT ("
                "(NEW.previous_state = 'active' AND NEW.current_state IN ('suspended','removed')) "
                "OR (NEW.previous_state = 'suspended' "
                "AND NEW.current_state IN ('active','removed'))) "
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
                "SELECT CASE WHEN NEW.current_role = 'owner' AND "
                "NEW.current_state IN ('active','suspended') AND NOT EXISTS ("
                "SELECT 1 FROM workspaces w WHERE w.id = NEW.workspace_id "
                "AND w.owner_id = NEW.user_id) "
                "THEN RAISE(ABORT, 'owner membership mismatch') END; "
                "SELECT CASE WHEN NEW.current_role = 'owner' AND "
                "NEW.current_state IN ('active','suspended') AND EXISTS ("
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
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_workspace_invitation_transition_valid "
                "BEFORE INSERT ON workspace_invitation_transitions BEGIN "
                "SELECT CASE WHEN NEW.sequence = 0 AND "
                "(NEW.previous_state IS NOT NULL OR NEW.current_state <> 'pending') "
                "THEN RAISE(ABORT, 'invalid initial invitation transition') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
                "SELECT 1 FROM workspace_invitation_transitions p "
                "WHERE p.invitation_id = NEW.invitation_id "
                "AND p.sequence = NEW.sequence - 1 "
                "AND p.current_state = NEW.previous_state "
                "AND p.current_state = 'pending') "
                "THEN RAISE(ABORT, 'invalid invitation lifecycle transition') END; "
                "SELECT CASE WHEN NEW.current_state = 'accepted' "
                "AND NEW.result_membership_id IS NULL "
                "THEN RAISE(ABORT, 'accepted invitation requires membership') END; "
                "SELECT CASE WHEN NEW.current_state <> 'accepted' "
                "AND NEW.result_membership_id IS NOT NULL "
                "THEN RAISE(ABORT, 'non-accepted invitation cannot bind membership') END; END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_workspace_invitation_secret_sequence "
                "BEFORE INSERT ON workspace_invitation_secret_versions BEGIN "
                "SELECT CASE WHEN NEW.sequence <> COALESCE(("
                "SELECT MAX(sequence) + 1 FROM workspace_invitation_secret_versions "
                "WHERE invitation_id = NEW.invitation_id), 0) "
                "THEN RAISE(ABORT, 'invalid invitation secret sequence') END; END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_workspace_invitation_delivery_sequence "
                "BEFORE INSERT ON workspace_invitation_delivery_attempts BEGIN "
                "SELECT CASE WHEN NEW.sequence <> COALESCE(("
                "SELECT MAX(sequence) + 1 FROM workspace_invitation_delivery_attempts "
                "WHERE invitation_id = NEW.invitation_id), 0) "
                "THEN RAISE(ABORT, 'invalid invitation delivery sequence') END; END"
            )
        )
        return
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_workspace_membership_transition() RETURNS trigger AS $$ "
            "DECLARE prior workspace_membership_transitions%ROWTYPE; "
            "BEGIN "
            "IF NEW.sequence = 0 THEN "
            "IF NEW.previous_state IS NOT NULL OR NEW.previous_role IS NOT NULL "
            "THEN RAISE EXCEPTION 'invalid initial membership transition'; END IF; "
            "ELSE SELECT * INTO prior FROM workspace_membership_transitions "
            "WHERE membership_id = NEW.membership_id AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state IS DISTINCT FROM "
            "NEW.previous_state OR prior.current_role IS DISTINCT FROM NEW.previous_role "
            "THEN RAISE EXCEPTION 'invalid membership transition sequence'; END IF; "
            "IF NOT ((NEW.previous_state = 'active' AND "
            "NEW.current_state IN ('suspended','removed')) OR "
            "(NEW.previous_state = 'suspended' AND "
            "NEW.current_state IN ('active','removed'))) "
            "THEN RAISE EXCEPTION 'invalid membership lifecycle transition'; END IF; "
            "END IF; "
            "IF NEW.current_state IN ('active','suspended') AND EXISTS ("
            "SELECT 1 FROM workspace_memberships m "
            "JOIN workspace_membership_transitions t ON t.membership_id = m.membership_id "
            "WHERE m.user_id = NEW.user_id AND m.workspace_id = NEW.workspace_id "
            "AND m.membership_id <> NEW.membership_id "
            "AND t.sequence = (SELECT MAX(x.sequence) "
            "FROM workspace_membership_transitions x "
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
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_workspace_invitation_transition() RETURNS trigger AS $$ "
            "DECLARE prior workspace_invitation_transitions%ROWTYPE; "
            "BEGIN IF NEW.sequence = 0 THEN "
            "IF NEW.previous_state IS NOT NULL OR NEW.current_state <> 'pending' "
            "THEN RAISE EXCEPTION 'invalid initial invitation transition'; END IF; "
            "ELSE SELECT * INTO prior FROM workspace_invitation_transitions "
            "WHERE invitation_id = NEW.invitation_id AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state <> 'pending' "
            "OR prior.current_state IS DISTINCT FROM NEW.previous_state "
            "THEN RAISE EXCEPTION 'invalid invitation lifecycle transition'; END IF; "
            "END IF; "
            "IF NEW.current_state = 'accepted' AND NEW.result_membership_id IS NULL "
            "THEN RAISE EXCEPTION 'accepted invitation requires membership'; END IF; "
            "IF NEW.current_state <> 'accepted' AND NEW.result_membership_id IS NOT NULL "
            "THEN RAISE EXCEPTION 'non-accepted invitation cannot bind membership'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_workspace_invitation_transition_valid "
            "BEFORE INSERT ON workspace_invitation_transitions FOR EACH ROW "
            "EXECUTE FUNCTION validate_workspace_invitation_transition()"
        )
    )
    for table, function, trigger in (
        (
            "workspace_invitation_secret_versions",
            "validate_workspace_invitation_secret_sequence",
            "trg_workspace_invitation_secret_sequence",
        ),
        (
            "workspace_invitation_delivery_attempts",
            "validate_workspace_invitation_delivery_sequence",
            "trg_workspace_invitation_delivery_sequence",
        ),
    ):
        op.execute(
            sa.text(
                f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
                "DECLARE expected_sequence integer; "
                "BEGIN SELECT COALESCE(MAX(sequence) + 1, 0) INTO expected_sequence "
                f"FROM {table} WHERE invitation_id = NEW.invitation_id; "
                "IF NEW.sequence <> expected_sequence "
                "THEN RAISE EXCEPTION 'invalid invitation evidence sequence'; END IF; "
                "RETURN NEW; END; $$ LANGUAGE plpgsql"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER {trigger} BEFORE INSERT ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {function}()"
            )
        )


def _backfill_owner_memberships() -> None:
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, owner_id FROM workspaces ORDER BY id")).all()
    now = datetime.now(UTC)
    for workspace_id, owner_id in rows:
        workspace_uuid = _uuid(workspace_id)
        owner_uuid = _uuid(owner_id)
        membership_id = uuid.uuid5(workspace_uuid, "owner-membership")
        trace_id = uuid.uuid5(workspace_uuid, "owner-membership-backfill-trace")
        audit_id = uuid.uuid5(workspace_uuid, "owner-membership-backfill-audit")
        metadata_digest = hashlib.sha256(
            b'{"reasonCode":"workspace_owner_backfill","role":"owner","state":"active"}'
        ).hexdigest()
        membership_value = _db_uuid(membership_id)
        trace_value = _db_uuid(trace_id)
        audit_value = _db_uuid(audit_id)
        workspace_value = _db_uuid(workspace_uuid)
        owner_value = _db_uuid(owner_uuid)
        bind.execute(
            sa.text(
                "INSERT INTO trace_events "
                "(event_id, trace_id, parent_trace_id, occurred_at, event_type, actor_id, "
                "actor_type, user_id, workspace_id, object_id, object_type, operation, status, "
                "metadata, error) "
                "VALUES (:event_id, :trace_id, NULL, :occurred_at, "
                "'collaboration.membership.backfill', :actor_id, 'system', :user_id, "
                ":workspace_id, :object_id, 'workspace_membership', "
                "'backfill_owner_membership', 'succeeded', :metadata, NULL)"
            ),
            {
                "event_id": _db_uuid(uuid.uuid5(trace_id, "event")),
                "trace_id": trace_value,
                "occurred_at": now,
                "actor_id": str(owner_uuid),
                "user_id": owner_value,
                "workspace_id": workspace_value,
                "object_id": membership_value,
                "metadata": '{"policyVersion":"collaboration-policy-v1"}',
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO collaboration_audit_events "
                "(audit_event_id, workspace_id, actor_user_id, subject_kind, subject_id, "
                "action, outcome, reason_code, metadata_digest, trace_id, recorded_at) "
                "VALUES (:audit_id, :workspace_id, :owner_id, 'workspace_membership', "
                ":membership_id, 'membership.bootstrap_owner', 'succeeded', "
                "'workspace_owner_backfill', :metadata_digest, :trace_id, :recorded_at)"
            ),
            {
                "audit_id": audit_value,
                "workspace_id": workspace_value,
                "owner_id": owner_value,
                "membership_id": membership_value,
                "metadata_digest": metadata_digest,
                "trace_id": trace_value,
                "recorded_at": now,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO workspace_memberships "
                "(membership_id, user_id, workspace_id, created_by_user_id, "
                "accepted_invitation_id, collaboration_policy_version, creation_trace_id, "
                "creation_audit_event_id, created_at) "
                "VALUES (:membership_id, :owner_id, :workspace_id, :owner_id, NULL, "
                ":policy, :trace_id, :audit_id, :created_at)"
            ),
            {
                "membership_id": membership_value,
                "owner_id": owner_value,
                "workspace_id": workspace_value,
                "policy": POLICY_VERSION,
                "trace_id": trace_value,
                "audit_id": audit_value,
                "created_at": now,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO workspace_membership_transitions "
                "(transition_id, membership_id, user_id, workspace_id, sequence, "
                "previous_state, current_state, previous_role, current_role, reason_code, "
                "collaboration_policy_version, authority_generation, actor_user_id, trace_id, "
                "audit_event_id, recorded_at) "
                "VALUES (:transition_id, :membership_id, :owner_id, :workspace_id, 0, NULL, "
                "'active', NULL, 'owner', 'workspace_owner_backfill', :policy, 1, :owner_id, "
                ":trace_id, :audit_id, :recorded_at)"
            ),
            {
                "transition_id": _db_uuid(uuid.uuid5(membership_id, "transition:0")),
                "membership_id": membership_value,
                "owner_id": owner_value,
                "workspace_id": workspace_value,
                "policy": POLICY_VERSION,
                "trace_id": trace_value,
                "audit_id": audit_value,
                "recorded_at": now,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO workspace_authority_versions "
                "(workspace_id, authority_generation, last_trace_id, updated_at) "
                "VALUES (:workspace_id, 1, :trace_id, :updated_at)"
            ),
            {
                "workspace_id": workspace_value,
                "trace_id": trace_value,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM trace_events "
            "WHERE event_type = 'collaboration.membership.backfill' "
            "AND operation = 'backfill_owner_membership'"
        )
    )
    for table in reversed(IMMUTABLE_TABLES):
        _unprotect(table)
    if op.get_bind().dialect.name == "postgresql":
        for table, function, trigger in (
            (
                "workspace_invitation_delivery_attempts",
                "validate_workspace_invitation_delivery_sequence",
                "trg_workspace_invitation_delivery_sequence",
            ),
            (
                "workspace_invitation_secret_versions",
                "validate_workspace_invitation_secret_sequence",
                "trg_workspace_invitation_secret_sequence",
            ),
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_workspace_membership_transition_valid "
                "ON workspace_membership_transitions"
            )
        )
        op.execute(sa.text("DROP FUNCTION IF EXISTS validate_workspace_membership_transition()"))
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_workspace_invitation_transition_valid "
                "ON workspace_invitation_transitions"
            )
        )
        op.execute(sa.text("DROP FUNCTION IF EXISTS validate_workspace_invitation_transition()"))
    op.drop_table("workspace_authority_versions")
    op.drop_index(
        "ix_collaboration_request_created",
        table_name="collaboration_request_identities",
    )
    op.drop_table("collaboration_request_identities")
    op.drop_index(
        "ix_workspace_invitation_delivery_recent",
        table_name="workspace_invitation_delivery_attempts",
    )
    op.drop_table("workspace_invitation_delivery_attempts")
    op.drop_index(
        "ix_workspace_invitation_secret_current",
        table_name="workspace_invitation_secret_versions",
    )
    op.drop_table("workspace_invitation_secret_versions")
    op.drop_index(
        "ix_workspace_invitation_transition_current",
        table_name="workspace_invitation_transitions",
    )
    op.drop_table("workspace_invitation_transitions")
    op.drop_index(
        "ix_workspace_membership_transition_workspace",
        table_name="workspace_membership_transitions",
    )
    op.drop_index(
        "ix_workspace_membership_transition_current",
        table_name="workspace_membership_transitions",
    )
    op.drop_table("workspace_membership_transitions")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "fk_workspace_membership_accepted_invitation_scope",
            "workspace_memberships",
            type_="foreignkey",
        )
    op.drop_index(
        "ix_workspace_invitations_workspace_expiry",
        table_name="workspace_invitations",
    )
    op.drop_index(
        "ix_workspace_invitations_workspace_recipient",
        table_name="workspace_invitations",
    )
    op.drop_table("workspace_invitations")
    op.drop_index(
        "ix_workspace_memberships_workspace_time",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_user_workspace",
        table_name="workspace_memberships",
    )
    op.drop_table("workspace_memberships")
    op.drop_index(
        "ix_collaboration_audit_trace",
        table_name="collaboration_audit_events",
    )
    op.drop_index(
        "ix_collaboration_audit_workspace_time",
        table_name="collaboration_audit_events",
    )
    op.drop_table("collaboration_audit_events")
    _replace_event_constraints(PRIOR_EVENT_TYPES, PRIOR_SUBJECT_KINDS)


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _db_uuid(value: uuid.UUID) -> uuid.UUID | str:
    return value.hex if op.get_bind().dialect.name == "sqlite" else value
