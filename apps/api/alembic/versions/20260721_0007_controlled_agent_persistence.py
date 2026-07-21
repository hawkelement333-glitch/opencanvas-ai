"""Add the append-only controlled-agent persistence boundary.

Revision ID: 20260721_0007
Revises: 20260721_0006
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0007"
down_revision: str | None = "20260721_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_CHECK = "schema_version = 'controlled-agent-v1'"
IMMUTABLE_TABLES = (
    "controlled_agent_executions",
    "controlled_agent_execution_states",
    "controlled_agent_context_snapshots",
    "controlled_agent_plan_snapshots",
    "controlled_agent_capability_grants",
    "controlled_agent_grant_revocations",
    "controlled_agent_approvals",
    "controlled_agent_policy_decisions",
    "controlled_agent_approval_consumptions",
    "controlled_agent_audit_events",
)


def _execution_scope_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["execution_id", "user_id", "workspace_id"],
        [
            "controlled_agent_executions.id",
            "controlled_agent_executions.user_id",
            "controlled_agent_executions.workspace_id",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "controlled_agent_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("context_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("context_digest", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_digest", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_execution_schema"),
        sa.CheckConstraint(
            "role IN ('universe_coordinator', 'galaxy_analyst', "
            "'solar_system_researcher', 'planet_specialist', 'evidence_verifier', "
            "'drafting_assistant', 'controlled_action_executor')",
            name="ck_agent_execution_role",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", "workspace_id", name="uq_agent_execution_scope"),
    )
    op.create_index(
        "ix_agent_execution_owner_created",
        "controlled_agent_executions",
        ["user_id", "workspace_id", "created_at"],
    )

    op.create_table(
        "controlled_agent_execution_states",
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("safe_reason_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_state_schema"),
        sa.CheckConstraint(
            "status IN ('proposed', 'awaiting_approval', 'ready', 'running', 'succeeded', "
            "'failed', 'cancelled', 'denied')",
            name="ck_agent_state_status",
        ),
        _execution_scope_fk("fk_agent_state_execution_scope"),
        sa.PrimaryKeyConstraint("state_id"),
    )
    op.create_index(
        "ix_agent_state_execution_time",
        "controlled_agent_execution_states",
        ["execution_id", "recorded_at", "state_id"],
    )

    for table, primary_key, time_column, constraint_prefix in (
        ("controlled_agent_context_snapshots", "snapshot_id", "captured_at", "context"),
        ("controlled_agent_plan_snapshots", "plan_id", "created_at", "plan"),
    ):
        op.create_table(
            table,
            sa.Column(primary_key, sa.Uuid(), nullable=False),
            sa.Column("execution_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("schema_version", sa.String(length=32), nullable=False),
            sa.Column("payload_digest", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column(time_column, sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(SCHEMA_CHECK, name=f"ck_agent_{constraint_prefix}_schema"),
            _execution_scope_fk(f"fk_agent_{constraint_prefix}_execution_scope"),
            sa.PrimaryKeyConstraint(primary_key),
            sa.UniqueConstraint("execution_id", name=f"uq_agent_{constraint_prefix}_execution"),
        )
        op.create_index(
            f"ix_agent_{constraint_prefix}_owner_execution",
            table,
            ["user_id", "workspace_id", "execution_id"],
        )

    op.create_table(
        "controlled_agent_capability_grants",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("context_digest", sa.String(length=64), nullable=False),
        sa.Column("plan_digest", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_grant_schema"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_agent_grant_time_order"),
        sa.CheckConstraint(
            "(approval_required = false AND approval_id IS NULL) OR "
            "(approval_required = true AND approval_id IS NOT NULL)",
            name="ck_agent_grant_approval_binding",
        ),
        _execution_scope_fk("fk_agent_grant_execution_scope"),
        sa.PrimaryKeyConstraint("grant_id"),
        sa.UniqueConstraint("execution_id", name="uq_agent_grant_execution"),
        sa.UniqueConstraint(
            "grant_id", "execution_id", "user_id", "workspace_id", name="uq_agent_grant_scope"
        ),
    )
    op.create_index(
        "ix_agent_grant_owner_execution",
        "controlled_agent_capability_grants",
        ["user_id", "workspace_id", "execution_id"],
    )
    op.create_index("ix_agent_grant_expiry", "controlled_agent_capability_grants", ["expires_at"])

    op.create_table(
        "controlled_agent_grant_revocations",
        sa.Column("revocation_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_revocation_schema"),
        sa.ForeignKeyConstraint(
            ["grant_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_capability_grants.grant_id",
                "controlled_agent_capability_grants.execution_id",
                "controlled_agent_capability_grants.user_id",
                "controlled_agent_capability_grants.workspace_id",
            ],
            name="fk_agent_revocation_grant_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("revocation_id"),
        sa.UniqueConstraint("grant_id", name="uq_agent_revocation_grant"),
    )
    op.create_index(
        "ix_agent_revocation_owner_execution",
        "controlled_agent_grant_revocations",
        ["user_id", "workspace_id", "execution_id"],
    )

    op.create_table(
        "controlled_agent_approvals",
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("context_digest", sa.String(length=64), nullable=False),
        sa.Column("plan_digest", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_approval_schema"),
        sa.CheckConstraint("decision IN ('approved', 'denied')", name="ck_agent_approval_decision"),
        sa.CheckConstraint("expires_at > decided_at", name="ck_agent_approval_time_order"),
        sa.ForeignKeyConstraint(
            ["grant_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_capability_grants.grant_id",
                "controlled_agent_capability_grants.execution_id",
                "controlled_agent_capability_grants.user_id",
                "controlled_agent_capability_grants.workspace_id",
            ],
            name="fk_agent_approval_grant_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
        sa.UniqueConstraint(
            "approval_id",
            "execution_id",
            "user_id",
            "workspace_id",
            name="uq_agent_approval_scope",
        ),
    )
    op.create_index(
        "ix_agent_approval_owner_execution",
        "controlled_agent_approvals",
        ["user_id", "workspace_id", "execution_id"],
    )
    op.create_index("ix_agent_approval_expiry", "controlled_agent_approvals", ["expires_at"])

    op.create_table(
        "controlled_agent_policy_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("context_digest", sa.String(length=64), nullable=False),
        sa.Column("plan_digest", sa.String(length=64), nullable=False),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_policy_schema"),
        sa.CheckConstraint(
            "outcome IN ('allow', 'deny', 'approval_required')", name="ck_agent_policy_outcome"
        ),
        _execution_scope_fk("fk_agent_policy_execution_scope"),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint(
            "decision_id",
            "execution_id",
            "user_id",
            "workspace_id",
            name="uq_agent_policy_scope",
        ),
    )
    op.create_index(
        "ix_agent_policy_execution_time",
        "controlled_agent_policy_decisions",
        ["execution_id", "evaluated_at", "decision_id"],
    )

    op.create_table(
        "controlled_agent_approval_consumptions",
        sa.Column("consumption_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_consumption_schema"),
        sa.ForeignKeyConstraint(
            ["approval_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_approvals.approval_id",
                "controlled_agent_approvals.execution_id",
                "controlled_agent_approvals.user_id",
                "controlled_agent_approvals.workspace_id",
            ],
            name="fk_agent_consumption_approval_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id", "execution_id", "user_id", "workspace_id"],
            [
                "controlled_agent_policy_decisions.decision_id",
                "controlled_agent_policy_decisions.execution_id",
                "controlled_agent_policy_decisions.user_id",
                "controlled_agent_policy_decisions.workspace_id",
            ],
            name="fk_agent_consumption_policy_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("consumption_id"),
        sa.UniqueConstraint("approval_id", name="uq_agent_consumption_approval"),
    )
    op.create_index(
        "ix_agent_consumption_owner_execution",
        "controlled_agent_approval_consumptions",
        ["user_id", "workspace_id", "execution_id"],
    )

    op.create_table(
        "controlled_agent_audit_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.CheckConstraint(SCHEMA_CHECK, name="ck_agent_audit_schema"),
        _execution_scope_fk("fk_agent_audit_execution_scope"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_agent_audit_execution_time",
        "controlled_agent_audit_events",
        ["execution_id", "recorded_at", "event_id"],
    )
    op.create_index(
        "ix_controlled_agent_audit_events_trace_id",
        "controlled_agent_audit_events",
        ["trace_id"],
    )
    _create_append_only_guards()


def _create_append_only_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for table in IMMUTABLE_TABLES:
            for operation in ("UPDATE", "DELETE"):
                trigger = f"trg_{table}_{operation.lower()}_blocked"
                op.execute(
                    sa.text(
                        f"CREATE TRIGGER {trigger} BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'controlled-agent records are append-only'); END"
                    )
                )
        return
    op.execute(
        sa.text(
            "CREATE FUNCTION reject_controlled_agent_mutation() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'controlled-agent records are append-only'; END; "
            "$$ LANGUAGE plpgsql"
        )
    )
    for table in IMMUTABLE_TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_mutation_blocked BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_controlled_agent_mutation()"
            )
        )


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        op.drop_table(table)
    if op.get_bind().dialect.name != "sqlite":
        op.execute(sa.text("DROP FUNCTION reject_controlled_agent_mutation()"))
