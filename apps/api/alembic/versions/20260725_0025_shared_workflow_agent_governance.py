"""Separate definition ownership from shared invocation authority.

Revision ID: 20260725_0025
Revises: 20260725_0024
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0025"
down_revision: str | None = "20260725_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_VERSION = "collaboration-policy-v1"


def upgrade() -> None:
    _add_parent_scope_keys()
    _add_invocation_columns()
    if not op.get_context().as_sql:
        _backfill_invocation_authority()
    _add_invocation_constraints()
    _restore_sqlite_guards()


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table(
        "bounded_agent_invocations",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_index("ix_bounded_agent_invocation_invoker_authority")
        batch.drop_constraint("fk_bounded_agent_invocation_authority_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_bounded_agent_invocation_membership", type_="foreignkey")
        batch.drop_constraint("fk_bounded_agent_invocation_workflow", type_="foreignkey")
        batch.drop_constraint("fk_bounded_agent_invocation_scope", type_="foreignkey")
        batch.create_foreign_key(
            "fk_bounded_agent_invocation_scope",
            "bounded_agent_versions",
            ["agent_version_id", "user_id", "workspace_id", "canvas_id"],
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_bounded_agent_invocation_workflow",
            "controlled_workflow_executions",
            ["workflow_execution_id", "user_id", "workspace_id", "canvas_id"],
            ["execution_id", "user_id", "workspace_id", "canvas_id"],
            ondelete="RESTRICT",
        )
        batch.drop_column("authority_snapshot_id")
        batch.drop_column("invoking_membership_id")
        batch.drop_column("definition_owner_user_id")
    with op.batch_alter_table(
        "controlled_workflow_executions",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_index("ix_workflow_execution_invoker_authority")
        batch.drop_constraint("fk_workflow_execution_authority_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_workflow_execution_invoking_membership", type_="foreignkey")
        batch.drop_constraint("fk_workflow_execution_version_scope", type_="foreignkey")
        batch.drop_constraint("uq_workflow_execution_invocation_scope", type_="unique")
        batch.create_foreign_key(
            "fk_workflow_execution_version_scope",
            "controlled_workflow_versions",
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            ["version_id", "user_id", "workspace_id", "canvas_id"],
            ondelete="RESTRICT",
        )
        batch.drop_column("authority_snapshot_id")
        batch.drop_column("invoking_membership_id")
        batch.drop_column("definition_owner_user_id")
    with op.batch_alter_table(
        "collaboration_authority_snapshots",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_constraint("uq_collaboration_snapshot_invoker_scope", type_="unique")
    with op.batch_alter_table(
        "bounded_agent_versions",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_constraint("uq_bounded_agent_version_parent_owner_scope", type_="unique")
    with op.batch_alter_table(
        "controlled_workflow_versions",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_constraint("uq_workflow_version_parent_owner_scope", type_="unique")
    _restore_sqlite_guards()


def _add_parent_scope_keys() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table(
        "controlled_workflow_versions",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.create_unique_constraint(
            "uq_workflow_version_parent_owner_scope",
            ["version_id", "definition_id", "user_id", "workspace_id", "canvas_id"],
        )
    with op.batch_alter_table(
        "bounded_agent_versions",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.create_unique_constraint(
            "uq_bounded_agent_version_parent_owner_scope",
            ["version_id", "agent_id", "user_id", "workspace_id", "canvas_id"],
        )
    with op.batch_alter_table(
        "collaboration_authority_snapshots",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.create_unique_constraint(
            "uq_collaboration_snapshot_invoker_scope",
            ["snapshot_id", "user_id", "membership_id", "workspace_id"],
        )


def _add_invocation_columns() -> None:
    op.add_column(
        "controlled_workflow_executions",
        sa.Column("definition_owner_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "controlled_workflow_executions",
        sa.Column("invoking_membership_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "controlled_workflow_executions",
        sa.Column("authority_snapshot_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "bounded_agent_invocations",
        sa.Column("definition_owner_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "bounded_agent_invocations",
        sa.Column("invoking_membership_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "bounded_agent_invocations",
        sa.Column("authority_snapshot_id", sa.Uuid(), nullable=True),
    )


def _backfill_invocation_authority() -> None:
    bind = op.get_bind()
    executions = bind.execute(
        sa.text(
            "SELECT execution_id, definition_id, version_id, user_id, workspace_id, "
            "canvas_id, trace_id, created_at FROM controlled_workflow_executions "
            "ORDER BY created_at, execution_id"
        )
    ).mappings()
    execution_memberships: dict[uuid.UUID, uuid.UUID] = {}
    for row in executions:
        execution_id = _uuid(row["execution_id"])
        user_id = _uuid(row["user_id"])
        workspace_id = _uuid(row["workspace_id"])
        membership = _historical_membership(
            bind,
            user_id=user_id,
            workspace_id=workspace_id,
            occurred_at=row["created_at"],
            subject=f"workflow execution {execution_id}",
        )
        snapshot_id = _authority_snapshot(
            bind,
            subject_id=execution_id,
            subject_kind="workflow",
            resource_id=_uuid(row["definition_id"]),
            permission="workflow.invoke",
            user_id=user_id,
            membership_id=membership["membership_id"],
            role=membership["role"],
            authority_generation=membership["authority_generation"],
            workspace_id=workspace_id,
            workflow_execution_id=execution_id,
            trace_id=_uuid(row["trace_id"]),
            occurred_at=row["created_at"],
        )
        bind.execute(
            sa.text(
                "UPDATE controlled_workflow_executions SET "
                "definition_owner_user_id = user_id, "
                "invoking_membership_id = :membership_id, "
                "authority_snapshot_id = :snapshot_id "
                "WHERE execution_id = :execution_id"
            ),
            {
                "membership_id": _db_uuid(membership["membership_id"]),
                "snapshot_id": _db_uuid(snapshot_id),
                "execution_id": _db_uuid(execution_id),
            },
        )
        execution_memberships[execution_id] = membership["membership_id"]

    invocations = bind.execute(
        sa.text(
            "SELECT invocation_id, agent_id, workflow_execution_id, user_id, workspace_id, "
            "trace_id, created_at FROM bounded_agent_invocations "
            "ORDER BY created_at, invocation_id"
        )
    ).mappings()
    for row in invocations:
        invocation_id = _uuid(row["invocation_id"])
        execution_id = _uuid(row["workflow_execution_id"])
        user_id = _uuid(row["user_id"])
        workspace_id = _uuid(row["workspace_id"])
        membership = _historical_membership(
            bind,
            user_id=user_id,
            workspace_id=workspace_id,
            occurred_at=row["created_at"],
            subject=f"agent invocation {invocation_id}",
        )
        if execution_memberships.get(execution_id) != membership["membership_id"]:
            raise RuntimeError(
                f"Milestone 6.5 backfill failed closed: agent invocation {invocation_id} "
                "does not share the exact invoking membership of its workflow execution"
            )
        snapshot_id = _authority_snapshot(
            bind,
            subject_id=invocation_id,
            subject_kind="agent",
            resource_id=_uuid(row["agent_id"]),
            permission="agent.invoke",
            user_id=user_id,
            membership_id=membership["membership_id"],
            role=membership["role"],
            authority_generation=membership["authority_generation"],
            workspace_id=workspace_id,
            workflow_execution_id=execution_id,
            trace_id=_uuid(row["trace_id"]),
            occurred_at=row["created_at"],
        )
        bind.execute(
            sa.text(
                "UPDATE bounded_agent_invocations SET "
                "definition_owner_user_id = user_id, "
                "invoking_membership_id = :membership_id, "
                "authority_snapshot_id = :snapshot_id "
                "WHERE invocation_id = :invocation_id"
            ),
            {
                "membership_id": _db_uuid(membership["membership_id"]),
                "snapshot_id": _db_uuid(snapshot_id),
                "invocation_id": _db_uuid(invocation_id),
            },
        )


def _historical_membership(
    bind: sa.engine.Connection,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    occurred_at: object,
    subject: str,
) -> dict[str, object]:
    rows = bind.execute(
        sa.text(
            "SELECT m.membership_id, t.current_role, t.authority_generation "
            "FROM workspace_memberships m "
            "JOIN workspace_membership_transitions t ON t.membership_id = m.membership_id "
            "WHERE m.user_id = :user_id AND m.workspace_id = :workspace_id "
            "AND m.created_at <= :occurred_at AND t.recorded_at <= :occurred_at "
            "AND t.sequence = (SELECT MAX(x.sequence) "
            "FROM workspace_membership_transitions x "
            "WHERE x.membership_id = m.membership_id AND x.recorded_at <= :occurred_at) "
            "AND t.current_state = 'active' ORDER BY m.membership_id"
        ),
        {
            "user_id": _db_uuid(user_id),
            "workspace_id": _db_uuid(workspace_id),
            "occurred_at": occurred_at,
        },
    ).all()
    if len(rows) != 1:
        raise RuntimeError(
            f"Milestone 6.5 backfill failed closed: {subject} has {len(rows)} "
            "exact active historical memberships; expected exactly 1"
        )
    return {
        "membership_id": _uuid(rows[0][0]),
        "role": str(rows[0][1]),
        "authority_generation": int(rows[0][2]),
    }


def _authority_snapshot(
    bind: sa.engine.Connection,
    *,
    subject_id: uuid.UUID,
    subject_kind: str,
    resource_id: uuid.UUID,
    permission: str,
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    role: object,
    authority_generation: object,
    workspace_id: uuid.UUID,
    workflow_execution_id: uuid.UUID,
    trace_id: uuid.UUID,
    occurred_at: object,
) -> uuid.UUID:
    ownership = bind.execute(
        sa.text(
            "SELECT transition_id FROM collaboration_resource_ownership_transitions "
            "WHERE resource_id = :resource_id AND workspace_id = :workspace_id "
            "AND resource_kind = :resource_kind AND recorded_at <= :occurred_at "
            "ORDER BY sequence DESC LIMIT 1"
        ),
        {
            "resource_id": _db_uuid(resource_id),
            "workspace_id": _db_uuid(workspace_id),
            "resource_kind": subject_kind,
            "occurred_at": occurred_at,
        },
    ).all()
    if len(ownership) != 1:
        raise RuntimeError(
            f"Milestone 6.5 backfill failed closed: {subject_kind} {resource_id} "
            "has no exact historical ownership evidence"
        )
    ownership_id = _uuid(ownership[0][0])
    snapshot_id = uuid.uuid5(subject_id, f"milestone-6.5:{permission}:authority")
    existing = bind.execute(
        sa.text(
            "SELECT snapshot_id FROM collaboration_authority_snapshots "
            "WHERE snapshot_id = :snapshot_id"
        ),
        {"snapshot_id": _db_uuid(snapshot_id)},
    ).first()
    if existing is not None:
        return snapshot_id
    scope = {
        "userId": str(user_id),
        "membershipId": str(membership_id),
        "workspaceId": str(workspace_id),
        "role": str(role),
        "permission": permission,
        "boundary": "claim",
        "resourceKind": subject_kind,
        "resourceId": str(resource_id),
        "shareId": None,
        "ownershipTransitionId": str(ownership_id),
        "authorityGeneration": int(authority_generation),
        "controlledExecutionId": None,
        "workflowExecutionId": str(workflow_execution_id),
    }
    scope_digest = hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    bind.execute(
        sa.text(
            "INSERT INTO collaboration_authority_snapshots "
            "(snapshot_id, user_id, membership_id, workspace_id, role, permission, boundary, "
            "resource_id, resource_kind, share_id, ownership_transition_id, "
            "authority_generation, controlled_execution_id, workflow_execution_id, "
            "request_identity_id, collaboration_policy_version, scope_digest, trace_id, "
            "captured_at) VALUES "
            "(:snapshot_id, :user_id, :membership_id, :workspace_id, :role, :permission, "
            "'claim', :resource_id, :resource_kind, NULL, :ownership_transition_id, "
            ":authority_generation, NULL, :workflow_execution_id, NULL, :policy, "
            ":scope_digest, :trace_id, :captured_at)"
        ),
        {
            "snapshot_id": _db_uuid(snapshot_id),
            "user_id": _db_uuid(user_id),
            "membership_id": _db_uuid(membership_id),
            "workspace_id": _db_uuid(workspace_id),
            "role": str(role),
            "permission": permission,
            "resource_id": _db_uuid(resource_id),
            "resource_kind": subject_kind,
            "ownership_transition_id": _db_uuid(ownership_id),
            "authority_generation": int(authority_generation),
            "workflow_execution_id": _db_uuid(workflow_execution_id),
            "policy": POLICY_VERSION,
            "scope_digest": scope_digest,
            "trace_id": _db_uuid(trace_id),
            "captured_at": occurred_at,
        },
    )
    return snapshot_id


def _add_invocation_constraints() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    with op.batch_alter_table(
        "controlled_workflow_executions",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.alter_column("definition_owner_user_id", nullable=False)
        batch.alter_column("invoking_membership_id", nullable=False)
        batch.drop_constraint("fk_workflow_execution_version_scope", type_="foreignkey")
        batch.create_foreign_key(
            "fk_workflow_execution_version_scope",
            "controlled_workflow_versions",
            [
                "version_id",
                "definition_id",
                "definition_owner_user_id",
                "workspace_id",
                "canvas_id",
            ],
            ["version_id", "definition_id", "user_id", "workspace_id", "canvas_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_workflow_execution_invoking_membership",
            "workspace_memberships",
            ["invoking_membership_id", "user_id", "workspace_id"],
            ["membership_id", "user_id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_workflow_execution_authority_snapshot",
            "collaboration_authority_snapshots",
            ["authority_snapshot_id", "user_id", "invoking_membership_id", "workspace_id"],
            ["snapshot_id", "user_id", "membership_id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_workflow_execution_invocation_scope",
            [
                "execution_id",
                "version_id",
                "user_id",
                "invoking_membership_id",
                "workspace_id",
                "canvas_id",
            ],
        )
        batch.create_index(
            "ix_workflow_execution_invoker_authority",
            ["workspace_id", "user_id", "invoking_membership_id", "authority_snapshot_id"],
        )
    with op.batch_alter_table(
        "bounded_agent_invocations",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.alter_column("definition_owner_user_id", nullable=False)
        batch.alter_column("invoking_membership_id", nullable=False)
        batch.alter_column("authority_snapshot_id", nullable=False)
        batch.drop_constraint("fk_bounded_agent_invocation_scope", type_="foreignkey")
        batch.drop_constraint("fk_bounded_agent_invocation_workflow", type_="foreignkey")
        batch.create_foreign_key(
            "fk_bounded_agent_invocation_scope",
            "bounded_agent_versions",
            [
                "agent_version_id",
                "agent_id",
                "definition_owner_user_id",
                "workspace_id",
                "canvas_id",
            ],
            ["version_id", "agent_id", "user_id", "workspace_id", "canvas_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_bounded_agent_invocation_membership",
            "workspace_memberships",
            ["invoking_membership_id", "user_id", "workspace_id"],
            ["membership_id", "user_id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_bounded_agent_invocation_authority_snapshot",
            "collaboration_authority_snapshots",
            ["authority_snapshot_id", "user_id", "invoking_membership_id", "workspace_id"],
            ["snapshot_id", "user_id", "membership_id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_bounded_agent_invocation_workflow",
            "controlled_workflow_executions",
            [
                "workflow_execution_id",
                "workflow_version_id",
                "user_id",
                "invoking_membership_id",
                "workspace_id",
                "canvas_id",
            ],
            [
                "execution_id",
                "version_id",
                "user_id",
                "invoking_membership_id",
                "workspace_id",
                "canvas_id",
            ],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_bounded_agent_invocation_invoker_authority",
            ["workspace_id", "user_id", "invoking_membership_id", "authority_snapshot_id"],
        )


def _restore_sqlite_guards() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table, message in (
        ("controlled_workflow_versions", "workflow evidence is append-only"),
        ("bounded_agent_versions", "agent studio evidence is append-only"),
        ("collaboration_authority_snapshots", "collaboration evidence is append-only"),
        ("bounded_agent_invocations", "agent studio evidence is append-only"),
    ):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER IF NOT EXISTS trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    f"'{message}'); END"
                )
            )


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _db_uuid(value: uuid.UUID) -> object:
    return value.hex if op.get_bind().dialect.name == "sqlite" else value
