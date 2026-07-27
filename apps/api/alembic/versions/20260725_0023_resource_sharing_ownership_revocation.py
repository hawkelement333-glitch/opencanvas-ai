"""Add typed resource sharing, ownership, and revocation fencing.

Revision ID: 20260725_0023
Revises: 20260725_0022
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260725_0023"
down_revision: str | None = "20260725_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_EVENT_TYPES = (
    "resource.share.created",
    "resource.share.changed",
    "resource.share.revoked",
    "resource.share.expired",
    "resource.visibility.changed",
    "resource.ownership_changed",
    "ownership_transfer.requested",
    "ownership_transfer.accepted",
    "ownership_transfer.rejected",
    "ownership_transfer.canceled",
    "revocation.bulk_completed",
)
NEW_SUBJECT_KINDS = (
    "resource_share_request",
    "collaboration_resource",
    "ownership_transfer",
    "authority_fence",
)
NEW_REQUEST_OPERATIONS = (
    "share.create",
    "share.revoke",
    "share.bulk_revoke",
    "resource.visibility.change",
    "ownership_transfer.request",
    "ownership_transfer.accept",
    "ownership_transfer.reject",
    "ownership_transfer.cancel",
)
NEW_REQUEST_RESULT_KINDS = (
    "resource_share",
    "collaboration_resource",
    "ownership_transfer",
    "authority_fence",
)
NEW_TABLES = (
    "collaboration_resources",
    "collaboration_resource_ownership_transitions",
    "collaboration_resource_shares",
    "collaboration_resource_share_transitions",
    "collaboration_ownership_transfers",
    "collaboration_ownership_transfer_transitions",
    "collaboration_authority_snapshots",
    "collaboration_revocation_fences",
)

_CLOSED_CHECK_COLUMNS = {
    "ck_domain_events_type": "event_type",
    "ck_domain_events_subject_kind": "subject_kind",
    "ck_collaboration_request_operation": "operation",
    "ck_collaboration_request_result_kind": "result_kind",
    "ck_collaboration_audit_subject_kind": "subject_kind",
}
_REGISTRIES_BEFORE = {
    "ck_domain_events_type": (
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
        "membership.role_changed",
        "membership.suspended",
        "membership.restored",
        "membership.removed",
        "approval_authority.assigned",
        "approval_authority.replaced",
        "approval_authority.revoked",
    ),
    "ck_domain_events_subject_kind": (
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
        "approval_authority_assignment",
    ),
    "ck_collaboration_request_operation": (
        "invitation.create",
        "invitation.resend",
        "invitation.accept",
        "invitation.decline",
        "invitation.revoke",
        "membership.role.change",
        "membership.suspend",
        "membership.restore",
        "membership.remove",
        "approval_authority.assign",
        "approval_authority.replace",
        "approval_authority.revoke",
    ),
    "ck_collaboration_request_result_kind": (
        "workspace_invitation",
        "workspace_membership",
        "approval_authority_assignment",
    ),
    "ck_collaboration_audit_subject_kind": (
        "workspace_membership",
        "workspace_invitation",
        "approval_authority_assignment",
    ),
}
_REGISTRIES_AFTER = {
    "ck_domain_events_type": _REGISTRIES_BEFORE["ck_domain_events_type"] + NEW_EVENT_TYPES,
    "ck_domain_events_subject_kind": (
        _REGISTRIES_BEFORE["ck_domain_events_subject_kind"] + NEW_SUBJECT_KINDS
    ),
    "ck_collaboration_request_operation": (
        _REGISTRIES_BEFORE["ck_collaboration_request_operation"] + NEW_REQUEST_OPERATIONS
    ),
    "ck_collaboration_request_result_kind": (
        _REGISTRIES_BEFORE["ck_collaboration_request_result_kind"] + NEW_REQUEST_RESULT_KINDS
    ),
    "ck_collaboration_audit_subject_kind": (
        _REGISTRIES_BEFORE["ck_collaboration_audit_subject_kind"] + NEW_SUBJECT_KINDS
    ),
}


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _protect(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN "
                    f"SELECT RAISE(ABORT, '{table} records are append-only'); END"
                )
            )
        return
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_{table}_mutation_blocked BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_controlled_agent_mutation()"
        )
    )


def _unprotect(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"))
        return
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))


def _matching_delimiter(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    quoted = False
    cursor = start
    while cursor < len(text):
        character = text[cursor]
        if character == "'":
            if quoted and cursor + 1 < len(text) and text[cursor + 1] == "'":
                cursor += 2
                continue
            quoted = not quoted
        elif not quoted:
            if character == opening:
                depth += 1
            elif character == closing:
                depth -= 1
                if depth == 0:
                    return cursor
                if depth < 0:
                    return -1
        cursor += 1
    return -1


def _strip_outer_parentheses(expression: str) -> str:
    text = expression.strip()
    while text.startswith("("):
        closing = _matching_delimiter(text, 0, "(", ")")
        if closing != len(text) - 1:
            break
        text = text[1:-1].strip()
    return text


def _strip_supported_casts(expression: str, *, array: bool) -> str:
    text = expression.strip()
    target = r"(?:text|character\s+varying)"
    if array:
        target += r"\s*\[\s*\]"
    while True:
        unwrapped = _strip_outer_parentheses(text)
        if unwrapped != text:
            text = unwrapped
            continue
        cast = re.fullmatch(
            rf"(?P<value>.+?)\s*::\s*{target}\s*",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if cast is None:
            return text
        text = cast.group("value").strip()


def _unsupported_check_expression() -> RuntimeError:
    return RuntimeError("unsupported check constraint expression")


def _parse_sql_literal_list(expression: str) -> tuple[str, ...]:
    values: list[str] = []
    cursor = 0
    while True:
        while cursor < len(expression) and expression[cursor].isspace():
            cursor += 1
        if cursor >= len(expression) or expression[cursor] != "'":
            raise _unsupported_check_expression()
        cursor += 1
        characters: list[str] = []
        while cursor < len(expression):
            character = expression[cursor]
            if character == "'":
                if cursor + 1 < len(expression) and expression[cursor + 1] == "'":
                    characters.append("'")
                    cursor += 2
                    continue
                cursor += 1
                break
            characters.append(character)
            cursor += 1
        else:
            raise _unsupported_check_expression()

        while cursor < len(expression) and expression[cursor].isspace():
            cursor += 1
        if expression[cursor : cursor + 2] == "::":
            cast = re.match(
                r"::\s*(?:text|character\s+varying)(?![A-Za-z0-9_])",
                expression[cursor:],
                flags=re.IGNORECASE,
            )
            if cast is None:
                raise _unsupported_check_expression()
            cursor += cast.end()
        values.append("".join(characters))

        while cursor < len(expression) and expression[cursor].isspace():
            cursor += 1
        if cursor == len(expression):
            break
        if expression[cursor] != ",":
            raise _unsupported_check_expression()
        cursor += 1
    if not values:
        raise _unsupported_check_expression()
    return tuple(values)


def _parse_check_values(expression: str, *, column: str) -> tuple[str, ...]:
    text = _strip_outer_parentheses(expression)
    operator = re.match(
        r"^(?P<left>.+?)\s*(?P<operator>IN\b|=\s*ANY\b)(?P<remainder>.*)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if (
        operator is None
        or re.fullmatch(
            re.escape(column),
            _strip_supported_casts(operator.group("left"), array=False),
            flags=re.IGNORECASE,
        )
        is None
    ):
        raise _unsupported_check_expression()
    remainder = operator.group("remainder").strip()
    if not remainder.startswith("("):
        raise _unsupported_check_expression()
    closing = _matching_delimiter(remainder, 0, "(", ")")
    if closing != len(remainder) - 1:
        raise _unsupported_check_expression()
    body = remainder[1:-1]
    if operator.group("operator").upper() == "IN":
        return _parse_sql_literal_list(body)

    array = _strip_supported_casts(body, array=True)
    prefix = re.match(r"^ARRAY\b", array, flags=re.IGNORECASE)
    if prefix is None:
        raise _unsupported_check_expression()
    array = array[prefix.end() :].lstrip()
    if not array.startswith("["):
        raise _unsupported_check_expression()
    array_end = _matching_delimiter(array, 0, "[", "]")
    if array_end != len(array) - 1:
        raise _unsupported_check_expression()
    return _parse_sql_literal_list(array[1:array_end])


def _registry_digest(values: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(sorted(values)).encode()).hexdigest()


def _require_expected_registry(
    values: tuple[str, ...],
    *,
    fingerprint: tuple[int, str],
    constraint: str,
) -> tuple[str, ...]:
    if len(values) != len(set(values)) or (len(values), _registry_digest(values)) != fingerprint:
        raise RuntimeError(f"unexpected closed registry for {constraint}")
    return values


def _existing_check_values(
    table: str,
    constraint: str,
    *,
    expected: tuple[str, ...],
) -> tuple[str, ...]:
    fingerprint = (len(expected), _registry_digest(expected))
    if context.is_offline_mode():
        return _require_expected_registry(
            expected,
            fingerprint=fingerprint,
            constraint=constraint,
        )
    inspector = sa.inspect(op.get_bind())
    checks = inspector.get_check_constraints(table)
    text = next(
        (item["sqltext"] for item in checks if item.get("name") == constraint),
        None,
    )
    column = _CLOSED_CHECK_COLUMNS.get(constraint)
    if not isinstance(text, str) or column is None:
        raise RuntimeError(f"missing closed check constraint {constraint}")
    values = _parse_check_values(text, column=column)
    return _require_expected_registry(
        values,
        fingerprint=fingerprint,
        constraint=constraint,
    )


def _replace_closed_checks(*, add: bool) -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    source = _REGISTRIES_BEFORE if add else _REGISTRIES_AFTER
    target = _REGISTRIES_AFTER if add else _REGISTRIES_BEFORE
    for table, constraint in (
        ("domain_events", "ck_domain_events_type"),
        ("domain_events", "ck_domain_events_subject_kind"),
        ("collaboration_request_identities", "ck_collaboration_request_operation"),
        ("collaboration_request_identities", "ck_collaboration_request_result_kind"),
        ("collaboration_audit_events", "ck_collaboration_audit_subject_kind"),
    ):
        _existing_check_values(table, constraint, expected=source[constraint])
    event_types = target["ck_domain_events_type"]
    subject_kinds = target["ck_domain_events_subject_kind"]
    request_operations = target["ck_collaboration_request_operation"]
    result_kinds = target["ck_collaboration_request_result_kind"]
    audit_subjects = target["ck_collaboration_audit_subject_kind"]
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
        "collaboration_request_identities",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_constraint("ck_collaboration_request_operation", type_="check")
        batch.drop_constraint("ck_collaboration_request_result_kind", type_="check")
        batch.create_check_constraint(
            "ck_collaboration_request_operation",
            f"operation IN ({_in(request_operations)})",
        )
        batch.create_check_constraint(
            "ck_collaboration_request_result_kind",
            f"result_kind IN ({_in(result_kinds)})",
        )
    with op.batch_alter_table(
        "collaboration_audit_events",
        recreate="always" if sqlite else "auto",
    ) as batch:
        batch.drop_constraint("ck_collaboration_audit_subject_kind", type_="check")
        batch.create_check_constraint(
            "ck_collaboration_audit_subject_kind",
            f"subject_kind IN ({_in(audit_subjects)})",
        )
    if sqlite:
        _protect_domain_events()
        _protect("collaboration_request_identities")
        _protect("collaboration_audit_events")


def _protect_domain_events() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_domain_events_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON domain_events BEGIN "
                    "SELECT RAISE(ABORT, 'domain event evidence is append-only'); END"
                )
            )
        return
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_domain_events_mutation_blocked "
            "BEFORE UPDATE OR DELETE ON domain_events FOR EACH ROW "
            "EXECUTE FUNCTION reject_controlled_agent_mutation()"
        )
    )


def upgrade() -> None:
    _replace_closed_checks(add=True)
    _create_resource_tables()
    _create_share_tables()
    _create_transfer_tables()
    _create_snapshot_fence_tables()
    _backfill_resources()
    _install_resource_registration_triggers()
    _install_lifecycle_guards()
    _replace_membership_guard(allow_ownership_transfer=True)
    for table in NEW_TABLES:
        _protect(table)


def _create_resource_tables() -> None:
    op.create_table(
        "collaboration_resources",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=True),
        sa.Column("canonical_object_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_definition_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("creator_user_id", sa.Uuid(), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "resource_kind IN ('canvas', 'canonical_object', 'workflow', 'agent')",
            name="ck_collaboration_resource_kind",
        ),
        sa.CheckConstraint(
            "(resource_kind = 'canvas' AND resource_id = canvas_id "
            "AND canonical_object_id IS NULL AND workflow_definition_id IS NULL "
            "AND agent_id IS NULL AND target_user_id IS NULL) OR "
            "(resource_kind = 'canonical_object' AND "
            "resource_id = canonical_object_id AND workflow_definition_id IS NULL "
            "AND agent_id IS NULL AND target_user_id IS NULL) OR "
            "(resource_kind = 'workflow' AND resource_id = workflow_definition_id "
            "AND canonical_object_id IS NULL AND agent_id IS NULL "
            "AND target_user_id IS NOT NULL AND canvas_id IS NOT NULL) OR "
            "(resource_kind = 'agent' AND resource_id = agent_id "
            "AND canonical_object_id IS NULL AND workflow_definition_id IS NULL "
            "AND target_user_id IS NOT NULL AND canvas_id IS NOT NULL)",
            name="ck_collaboration_resource_target_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_collaboration_resource_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_user_id"],
            ["users.id"],
            name="fk_collaboration_resource_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_collaboration_resource_canvas_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_object_id", "workspace_id"],
            ["canonical_objects.id", "canonical_objects.workspace_id"],
            name="fk_collaboration_resource_object_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workflow_definition_id",
                "target_user_id",
                "workspace_id",
                "canvas_id",
            ],
            [
                "controlled_workflow_definitions.definition_id",
                "controlled_workflow_definitions.user_id",
                "controlled_workflow_definitions.workspace_id",
                "controlled_workflow_definitions.canvas_id",
            ],
            name="fk_collaboration_resource_workflow_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "target_user_id", "workspace_id", "canvas_id"],
            [
                "bounded_agent_identities.agent_id",
                "bounded_agent_identities.user_id",
                "bounded_agent_identities.workspace_id",
                "bounded_agent_identities.canvas_id",
            ],
            name="fk_collaboration_resource_agent_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("resource_id", "workspace_id", "resource_kind"),
    )
    op.create_index(
        "ix_collaboration_resource_workspace_kind",
        "collaboration_resources",
        ["workspace_id", "resource_kind", "created_at"],
    )
    op.create_table(
        "collaboration_resource_ownership_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_owner_kind", sa.String(16), nullable=True),
        sa.Column("previous_owner_membership_id", sa.Uuid(), nullable=True),
        sa.Column("previous_owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("current_owner_kind", sa.String(16), nullable=False),
        sa.Column("current_owner_membership_id", sa.Uuid(), nullable=True),
        sa.Column("current_owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("visibility_policy", sa.String(24), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_collaboration_ownership_sequence"),
        sa.CheckConstraint(
            "current_owner_kind IN ('workspace', 'membership')",
            name="ck_collaboration_ownership_current_kind",
        ),
        sa.CheckConstraint(
            "previous_owner_kind IS NULL OR previous_owner_kind IN ('workspace', 'membership')",
            name="ck_collaboration_ownership_previous_kind",
        ),
        sa.CheckConstraint(
            "(current_owner_kind = 'workspace' AND "
            "current_owner_membership_id IS NULL AND current_owner_user_id IS NULL) "
            "OR (current_owner_kind = 'membership' AND "
            "current_owner_membership_id IS NOT NULL AND "
            "current_owner_user_id IS NOT NULL)",
            name="ck_collaboration_ownership_current_shape",
        ),
        sa.CheckConstraint(
            "(previous_owner_kind IS NULL AND previous_owner_membership_id IS NULL "
            "AND previous_owner_user_id IS NULL) OR "
            "(previous_owner_kind = 'workspace' AND "
            "previous_owner_membership_id IS NULL AND "
            "previous_owner_user_id IS NULL) OR "
            "(previous_owner_kind = 'membership' AND "
            "previous_owner_membership_id IS NOT NULL AND "
            "previous_owner_user_id IS NOT NULL)",
            name="ck_collaboration_ownership_previous_shape",
        ),
        sa.CheckConstraint(
            "visibility_policy IN ('private', 'inherit', 'workspace_visible')",
            name="ck_collaboration_ownership_visibility",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_ownership_generation",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_ownership_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "current_owner_membership_id",
                "current_owner_user_id",
                "workspace_id",
            ],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_ownership_current_member_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "previous_owner_membership_id",
                "previous_owner_user_id",
                "workspace_id",
            ],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_ownership_previous_member_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_collaboration_ownership_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["workspace_memberships.membership_id"],
            name="fk_collaboration_ownership_actor_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_ownership_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint(
            "resource_id",
            "workspace_id",
            "resource_kind",
            "sequence",
            name="uq_collaboration_ownership_sequence",
        ),
    )
    op.create_index(
        "ix_collaboration_ownership_current",
        "collaboration_resource_ownership_transitions",
        ["workspace_id", "resource_kind", "resource_id", "sequence"],
    )
    op.create_index(
        "ix_collaboration_ownership_member",
        "collaboration_resource_ownership_transitions",
        ["workspace_id", "current_owner_membership_id", "recorded_at"],
    )


def _create_share_tables() -> None:
    op.create_table(
        "collaboration_resource_shares",
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("audience_kind", sa.String(16), nullable=False),
        sa.Column("audience_key", sa.String(64), nullable=False),
        sa.Column("audience_membership_id", sa.Uuid(), nullable=True),
        sa.Column("audience_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("creation_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "audience_kind IN ('workspace', 'membership')",
            name="ck_collaboration_share_audience_kind",
        ),
        sa.CheckConstraint(
            "(audience_kind = 'workspace' AND audience_membership_id IS NULL "
            "AND audience_user_id IS NULL) OR "
            "(audience_kind = 'membership' AND "
            "audience_membership_id IS NOT NULL AND audience_user_id IS NOT NULL)",
            name="ck_collaboration_share_audience_shape",
        ),
        sa.CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_share_policy",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_collaboration_share_request_digest",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_share_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audience_membership_id", "audience_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_share_audience_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "created_by_membership_id",
                "created_by_user_id",
                "workspace_id",
            ],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_share_creator_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_share_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("share_id"),
        sa.UniqueConstraint("share_id", "workspace_id", name="uq_collaboration_share_scope"),
        sa.UniqueConstraint(
            "workspace_id",
            "resource_kind",
            "resource_id",
            "audience_key",
            name="uq_collaboration_share_audience",
        ),
    )
    op.create_index(
        "ix_collaboration_share_resource",
        "collaboration_resource_shares",
        ["workspace_id", "resource_kind", "resource_id", "created_at"],
    )
    op.create_index(
        "ix_collaboration_share_audience",
        "collaboration_resource_shares",
        ["workspace_id", "audience_membership_id", "created_at"],
    )
    op.create_index(
        "ix_collaboration_share_request",
        "collaboration_resource_shares",
        ["workspace_id", "creation_request_id"],
    )
    op.create_table(
        "collaboration_resource_share_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(16), nullable=True),
        sa.Column("current_state", sa.String(16), nullable=False),
        sa.Column("access_level", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_collaboration_share_transition_sequence"),
        sa.CheckConstraint(
            "current_state IN ('active', 'revoked')",
            name="ck_collaboration_share_transition_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('active', 'revoked')",
            name="ck_collaboration_share_transition_previous_state",
        ),
        sa.CheckConstraint(
            "access_level IN ('view', 'contribute', 'manage')",
            name="ck_collaboration_share_transition_access",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > recorded_at",
            name="ck_collaboration_share_transition_expiry",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_share_transition_generation",
        ),
        sa.ForeignKeyConstraint(
            ["share_id", "workspace_id"],
            [
                "collaboration_resource_shares.share_id",
                "collaboration_resource_shares.workspace_id",
            ],
            name="fk_collaboration_share_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_collaboration_share_transition_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["workspace_memberships.membership_id"],
            name="fk_collaboration_share_transition_actor_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_share_transition_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint(
            "share_id",
            "sequence",
            name="uq_collaboration_share_transition_sequence",
        ),
    )
    op.create_index(
        "ix_collaboration_share_transition_current",
        "collaboration_resource_share_transitions",
        ["share_id", "sequence"],
    )
    op.create_index(
        "ix_collaboration_share_transition_expiry",
        "collaboration_resource_share_transitions",
        ["workspace_id", "current_state", "expires_at"],
    )


def _create_transfer_tables() -> None:
    op.create_table(
        "collaboration_ownership_transfers",
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("transfer_kind", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("resource_kind", sa.String(32), nullable=True),
        sa.Column("requester_membership_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_membership_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("former_owner_role", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "transfer_kind IN ('workspace', 'resource')",
            name="ck_collaboration_transfer_kind",
        ),
        sa.CheckConstraint(
            "(transfer_kind = 'workspace' AND resource_id IS NULL "
            "AND resource_kind IS NULL) OR "
            "(transfer_kind = 'resource' AND resource_id IS NOT NULL "
            "AND resource_kind IS NOT NULL)",
            name="ck_collaboration_transfer_target_shape",
        ),
        sa.CheckConstraint(
            "requester_membership_id <> recipient_membership_id",
            name="ck_collaboration_transfer_distinct_memberships",
        ),
        sa.CheckConstraint(
            "former_owner_role IN ('administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_collaboration_transfer_former_owner_role",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_collaboration_transfer_expiry"),
        sa.CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_transfer_policy",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_collaboration_transfer_request_digest",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_collaboration_transfer_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_transfer_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_membership_id", "requester_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_transfer_requester_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_membership_id", "recipient_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_transfer_recipient_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_transfer_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transfer_id"),
        sa.UniqueConstraint("transfer_id", "workspace_id", name="uq_collaboration_transfer_scope"),
    )
    op.create_index(
        "ix_collaboration_transfer_workspace_time",
        "collaboration_ownership_transfers",
        ["workspace_id", "transfer_kind", "created_at"],
    )
    op.create_index(
        "ix_collaboration_transfer_recipient",
        "collaboration_ownership_transfers",
        ["workspace_id", "recipient_membership_id", "created_at"],
    )
    op.create_table(
        "collaboration_ownership_transfer_transitions",
        sa.Column("transition_id", sa.Uuid(), nullable=False),
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(16), nullable=True),
        sa.Column("current_state", sa.String(16), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_collaboration_transfer_transition_sequence",
        ),
        sa.CheckConstraint(
            "current_state IN ('pending', 'accepted', 'rejected', 'canceled', "
            "'expired', 'superseded')",
            name="ck_collaboration_transfer_transition_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('pending', 'accepted', 'rejected', 'canceled', 'expired', "
            "'superseded')",
            name="ck_collaboration_transfer_transition_previous_state",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_transfer_transition_generation",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id", "workspace_id"],
            [
                "collaboration_ownership_transfers.transfer_id",
                "collaboration_ownership_transfers.workspace_id",
            ],
            name="fk_collaboration_transfer_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_collaboration_transfer_transition_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["workspace_memberships.membership_id"],
            name="fk_collaboration_transfer_transition_actor_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_transfer_transition_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint(
            "transfer_id",
            "sequence",
            name="uq_collaboration_transfer_transition_sequence",
        ),
    )
    op.create_index(
        "ix_collaboration_transfer_transition_current",
        "collaboration_ownership_transfer_transitions",
        ["transfer_id", "sequence"],
    )
    op.create_index(
        "ix_collaboration_transfer_transition_workspace",
        "collaboration_ownership_transfer_transitions",
        ["workspace_id", "recorded_at"],
    )


def _create_snapshot_fence_tables() -> None:
    permissions = (
        "workspace.view",
        "workspace.settings.manage",
        "membership.view",
        "membership.manage",
        "invitation.create",
        "invitation.resend",
        "invitation.revoke",
        "role.assign",
        "ownership.transfer.request",
        "ownership.transfer.accept",
        "ownership.transfer.cancel",
        "canvas.view",
        "canvas.edit",
        "canvas.share",
        "resource.view",
        "resource.edit",
        "resource.share",
        "comment.create",
        "comment.edit_own",
        "comment.resolve",
        "comment.moderate",
        "workflow.view",
        "workflow.edit",
        "workflow.share",
        "workflow.invoke",
        "agent.view",
        "agent.edit",
        "agent.share",
        "agent.activate_request",
        "agent.invoke",
        "approval.review",
        "collaboration_activity.view",
        "trace.view",
        "source.export",
        "evidence_bundle.view",
        "evidence_bundle.export",
    )
    op.create_table(
        "collaboration_authority_snapshots",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("boundary", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("resource_kind", sa.String(32), nullable=True),
        sa.Column("share_id", sa.Uuid(), nullable=True),
        sa.Column("ownership_transition_id", sa.Uuid(), nullable=True),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("controlled_execution_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=True),
        sa.Column("request_identity_id", sa.Uuid(), nullable=True),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')",
            name="ck_collaboration_snapshot_role",
        ),
        sa.CheckConstraint(
            f"permission IN ({_in(permissions)})",
            name="ck_collaboration_snapshot_permission",
        ),
        sa.CheckConstraint(
            "boundary IN ('claim', 'service_call', 'tool_call', 'retry', "
            "'effect', 'compensation', 'export', 'publication', "
            "'share_decision', 'ownership_decision')",
            name="ck_collaboration_snapshot_boundary",
        ),
        sa.CheckConstraint(
            "(resource_id IS NULL AND resource_kind IS NULL) OR "
            "(resource_id IS NOT NULL AND resource_kind IS NOT NULL)",
            name="ck_collaboration_snapshot_resource_shape",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_snapshot_generation",
        ),
        sa.CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_snapshot_policy",
        ),
        sa.CheckConstraint(
            "length(scope_digest) = 64",
            name="ck_collaboration_snapshot_digest",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_snapshot_member_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_snapshot_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["share_id", "workspace_id"],
            [
                "collaboration_resource_shares.share_id",
                "collaboration_resource_shares.workspace_id",
            ],
            name="fk_collaboration_snapshot_share_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ownership_transition_id"],
            ["collaboration_resource_ownership_transitions.transition_id"],
            name="fk_collaboration_snapshot_ownership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["controlled_execution_id"],
            ["controlled_agent_executions.id"],
            name="fk_collaboration_snapshot_controlled_execution",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"],
            ["controlled_workflow_executions.execution_id"],
            name="fk_collaboration_snapshot_workflow_execution",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_identity_id"],
            ["collaboration_request_identities.request_id"],
            name="fk_collaboration_snapshot_request",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index(
        "ix_collaboration_snapshot_controlled_execution",
        "collaboration_authority_snapshots",
        ["controlled_execution_id", "captured_at"],
    )
    op.create_index(
        "ix_collaboration_snapshot_workflow_execution",
        "collaboration_authority_snapshots",
        ["workflow_execution_id", "captured_at"],
    )
    op.create_index(
        "ix_collaboration_snapshot_scope",
        "collaboration_authority_snapshots",
        ["workspace_id", "membership_id", "captured_at"],
    )
    op.create_table(
        "collaboration_revocation_fences",
        sa.Column("fence_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=True),
        sa.Column("membership_user_id", sa.Uuid(), nullable=True),
        sa.Column("share_id", sa.Uuid(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("resource_kind", sa.String(32), nullable=True),
        sa.Column("previous_authority_generation", sa.Integer(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_kind IN ('workspace', 'membership', 'share', "
            "'resource_ownership', 'resource_visibility', 'approval_authority')",
            name="ck_collaboration_fence_scope_kind",
        ),
        sa.CheckConstraint(
            "authority_generation = previous_authority_generation + 1",
            name="ck_collaboration_fence_monotonic",
        ),
        sa.CheckConstraint(
            "(resource_id IS NULL AND resource_kind IS NULL) OR "
            "(resource_id IS NOT NULL AND resource_kind IS NOT NULL)",
            name="ck_collaboration_fence_resource_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_collaboration_fence_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "membership_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_fence_member_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["share_id", "workspace_id"],
            [
                "collaboration_resource_shares.share_id",
                "collaboration_resource_shares.workspace_id",
            ],
            name="fk_collaboration_fence_share_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_fence_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_collaboration_fence_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["workspace_memberships.membership_id"],
            name="fk_collaboration_fence_actor_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_fence_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("fence_id"),
    )
    op.create_index(
        "ix_collaboration_fence_workspace_generation",
        "collaboration_revocation_fences",
        ["workspace_id", "authority_generation"],
    )
    op.create_index(
        "ix_collaboration_fence_share",
        "collaboration_revocation_fences",
        ["share_id", "recorded_at"],
    )
    op.create_index(
        "ix_collaboration_fence_membership",
        "collaboration_revocation_fences",
        ["membership_id", "recorded_at"],
    )


def _backfill_resources() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        statements = (
            (
                "canvas",
                "SELECT id, workspace_id, id, NULL, NULL, NULL, NULL, "
                "(SELECT owner_id FROM workspaces w WHERE w.id = c.workspace_id), "
                "id, created_at FROM canvases c",
                "c1",
            ),
            (
                "canonical_object",
                "SELECT id, workspace_id, NULL, id, NULL, NULL, NULL, "
                "(SELECT owner_id FROM workspaces w WHERE w.id = c.workspace_id), "
                "id, created_at FROM canonical_objects c",
                "c2",
            ),
            (
                "workflow",
                "SELECT definition_id, workspace_id, canvas_id, NULL, "
                "definition_id, NULL, user_id, created_by_user_id, trace_id, "
                "created_at FROM controlled_workflow_definitions",
                "c3",
            ),
            (
                "agent",
                "SELECT agent_id, workspace_id, canvas_id, NULL, NULL, agent_id, "
                "user_id, created_by_user_id, trace_id, created_at "
                "FROM bounded_agent_identities",
                "c4",
            ),
        )
    else:
        statements = (
            (
                "canvas",
                "SELECT id, workspace_id, id, NULL::uuid, NULL::uuid, "
                "NULL::uuid, NULL::uuid, "
                "(SELECT owner_id FROM workspaces w WHERE w.id = c.workspace_id), "
                "id, created_at FROM canvases c",
                "c1",
            ),
            (
                "canonical_object",
                "SELECT id, workspace_id, NULL::uuid, id, NULL::uuid, "
                "NULL::uuid, NULL::uuid, "
                "(SELECT owner_id FROM workspaces w WHERE w.id = c.workspace_id), "
                "id, created_at FROM canonical_objects c",
                "c2",
            ),
            (
                "workflow",
                "SELECT definition_id, workspace_id, canvas_id, NULL::uuid, "
                "definition_id, NULL::uuid, user_id, created_by_user_id, trace_id, "
                "created_at FROM controlled_workflow_definitions",
                "c3",
            ),
            (
                "agent",
                "SELECT agent_id, workspace_id, canvas_id, NULL::uuid, "
                "NULL::uuid, agent_id, user_id, created_by_user_id, trace_id, created_at "
                "FROM bounded_agent_identities",
                "c4",
            ),
        )
    columns = (
        "resource_id, workspace_id, canvas_id, canonical_object_id, "
        "workflow_definition_id, agent_id, target_user_id, creator_user_id, "
        "creation_trace_id, created_at"
    )
    for kind, source, prefix in statements:
        bind.execute(
            sa.text(
                "INSERT INTO collaboration_resources "
                f"({columns}, resource_kind) SELECT q.*, '{kind}' FROM ({source}) q"
            )
        )
        transition_id = (
            f"'{prefix}' || substr(CAST(resource_id AS TEXT), 3)"
            if dialect == "sqlite"
            else f"('{prefix}' || substring(resource_id::text from 3))::uuid"
        )
        bind.execute(
            sa.text(
                "INSERT INTO collaboration_resource_ownership_transitions "
                "(transition_id, resource_id, workspace_id, resource_kind, sequence, "
                "previous_owner_kind, previous_owner_membership_id, "
                "previous_owner_user_id, current_owner_kind, "
                "current_owner_membership_id, current_owner_user_id, "
                "visibility_policy, authority_generation, actor_user_id, "
                "actor_membership_id, reason_code, trace_id, audit_event_id, "
                "recorded_at) "
                f"SELECT {transition_id}, resource_id, workspace_id, resource_kind, "
                "0, NULL, NULL, NULL, 'workspace', NULL, NULL, 'private', "
                "COALESCE((SELECT authority_generation FROM workspace_authority_versions "
                "v WHERE v.workspace_id = r.workspace_id), 1), creator_user_id, "
                "NULL, 'resource_owner_backfill', creation_trace_id, NULL, created_at "
                "FROM collaboration_resources r "
                f"WHERE r.resource_kind = '{kind}'"
            )
        )


def _install_resource_registration_triggers() -> None:
    # New resources are atomically registered as private workspace-owned resources.
    # The deterministic backfill above covers all pre-existing rows.
    dialect = op.get_bind().dialect.name
    specs = (
        (
            "canvases",
            "canvas",
            "NEW.id",
            "NEW.workspace_id",
            "NEW.id",
            "NULL",
            "NULL",
            "NULL",
            "NULL",
            "(SELECT owner_id FROM workspaces WHERE id = NEW.workspace_id)",
            "NEW.id",
            "NEW.created_at",
            "d1",
        ),
        (
            "canonical_objects",
            "canonical_object",
            "NEW.id",
            "NEW.workspace_id",
            "NULL",
            "NEW.id",
            "NULL",
            "NULL",
            "NULL",
            "(SELECT owner_id FROM workspaces WHERE id = NEW.workspace_id)",
            "NEW.id",
            "NEW.created_at",
            "d2",
        ),
        (
            "controlled_workflow_definitions",
            "workflow",
            "NEW.definition_id",
            "NEW.workspace_id",
            "NEW.canvas_id",
            "NULL",
            "NEW.definition_id",
            "NULL",
            "NEW.user_id",
            "NEW.created_by_user_id",
            "NEW.trace_id",
            "NEW.created_at",
            "d3",
        ),
        (
            "bounded_agent_identities",
            "agent",
            "NEW.agent_id",
            "NEW.workspace_id",
            "NEW.canvas_id",
            "NULL",
            "NULL",
            "NEW.agent_id",
            "NEW.user_id",
            "NEW.created_by_user_id",
            "NEW.trace_id",
            "NEW.created_at",
            "d4",
        ),
    )
    for (
        table,
        kind,
        resource_id,
        workspace_id,
        canvas_id,
        canonical_id,
        workflow_id,
        agent_id,
        target_user_id,
        creator_user_id,
        trace_id,
        created_at,
        prefix,
    ) in specs:
        transition_id = (
            f"'{prefix}' || substr(CAST({resource_id} AS TEXT), 3)"
            if dialect == "sqlite"
            else f"('{prefix}' || substring(({resource_id})::text from 3))::uuid"
        )
        body = (
            "INSERT INTO collaboration_resources "
            "(resource_id, workspace_id, resource_kind, canvas_id, "
            "canonical_object_id, workflow_definition_id, agent_id, "
            "target_user_id, creator_user_id, creation_trace_id, created_at) "
            f"VALUES ({resource_id}, {workspace_id}, '{kind}', {canvas_id}, "
            f"{canonical_id}, {workflow_id}, {agent_id}, {target_user_id}, "
            f"{creator_user_id}, {trace_id}, {created_at}); "
            "INSERT INTO collaboration_resource_ownership_transitions "
            "(transition_id, resource_id, workspace_id, resource_kind, sequence, "
            "previous_owner_kind, previous_owner_membership_id, "
            "previous_owner_user_id, current_owner_kind, "
            "current_owner_membership_id, current_owner_user_id, "
            "visibility_policy, authority_generation, actor_user_id, "
            "actor_membership_id, reason_code, trace_id, audit_event_id, "
            "recorded_at) "
            f"VALUES ({transition_id}, {resource_id}, {workspace_id}, '{kind}', "
            "0, NULL, NULL, NULL, 'workspace', NULL, NULL, 'private', "
            f"COALESCE((SELECT authority_generation FROM workspace_authority_versions "
            f"WHERE workspace_id = {workspace_id}), 1), {creator_user_id}, NULL, "
            f"'resource_created', {trace_id}, NULL, {created_at});"
        )
        if dialect == "sqlite":
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_collaboration_resource "
                    f"AFTER INSERT ON {table} BEGIN {body} END"
                )
            )
        else:
            function = f"register_{table}_collaboration_resource"
            op.execute(
                sa.text(
                    f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
                    f"BEGIN {body} RETURN NEW; END; $$ LANGUAGE plpgsql"
                )
            )
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_collaboration_resource "
                    f"AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
                )
            )


def _install_lifecycle_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_collaboration_share_transition_valid "
                "BEFORE INSERT ON collaboration_resource_share_transitions BEGIN "
                "SELECT CASE WHEN NEW.sequence = 0 AND "
                "(NEW.previous_state IS NOT NULL OR NEW.current_state <> 'active') "
                "THEN RAISE(ABORT, 'invalid initial share transition') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
                "SELECT 1 FROM collaboration_resource_share_transitions p "
                "WHERE p.share_id = NEW.share_id AND p.sequence = NEW.sequence - 1 "
                "AND p.current_state = NEW.previous_state) "
                "THEN RAISE(ABORT, 'invalid share transition sequence') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT ("
                "(NEW.previous_state = 'active' AND NEW.current_state = 'revoked') "
                "OR (NEW.previous_state = 'revoked' AND NEW.current_state = 'active')) "
                "THEN RAISE(ABORT, 'invalid share lifecycle transition') END; END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_collaboration_ownership_transition_valid "
                "BEFORE INSERT ON collaboration_resource_ownership_transitions BEGIN "
                "SELECT CASE WHEN NEW.sequence = 0 AND "
                "(NEW.previous_owner_kind IS NOT NULL OR "
                "NEW.current_owner_kind <> 'workspace') "
                "THEN RAISE(ABORT, 'invalid initial resource ownership') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
                "SELECT 1 FROM collaboration_resource_ownership_transitions p "
                "WHERE p.resource_id = NEW.resource_id "
                "AND p.workspace_id = NEW.workspace_id "
                "AND p.resource_kind = NEW.resource_kind "
                "AND p.sequence = NEW.sequence - 1 "
                "AND p.current_owner_kind = NEW.previous_owner_kind "
                "AND p.current_owner_membership_id IS "
                "NEW.previous_owner_membership_id "
                "AND p.current_owner_user_id IS NEW.previous_owner_user_id) "
                "THEN RAISE(ABORT, 'invalid resource ownership sequence') END; END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_collaboration_transfer_transition_valid "
                "BEFORE INSERT ON collaboration_ownership_transfer_transitions BEGIN "
                "SELECT CASE WHEN NEW.sequence = 0 AND "
                "(NEW.previous_state IS NOT NULL OR NEW.current_state <> 'pending') "
                "THEN RAISE(ABORT, 'invalid initial ownership transfer') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
                "SELECT 1 FROM collaboration_ownership_transfer_transitions p "
                "WHERE p.transfer_id = NEW.transfer_id "
                "AND p.sequence = NEW.sequence - 1 "
                "AND p.current_state = NEW.previous_state) "
                "THEN RAISE(ABORT, 'invalid ownership transfer sequence') END; "
                "SELECT CASE WHEN NEW.sequence > 0 AND "
                "(NEW.previous_state <> 'pending' OR NEW.current_state = 'pending') "
                "THEN RAISE(ABORT, 'invalid ownership transfer lifecycle') END; "
                "SELECT CASE WHEN NEW.current_state = 'pending' AND EXISTS ("
                "SELECT 1 FROM collaboration_ownership_transfers x "
                "JOIN collaboration_ownership_transfer_transitions t "
                "ON t.transfer_id = x.transfer_id "
                "WHERE x.workspace_id = NEW.workspace_id "
                "AND x.transfer_id <> NEW.transfer_id "
                "AND x.transfer_kind = (SELECT transfer_kind "
                "FROM collaboration_ownership_transfers "
                "WHERE transfer_id = NEW.transfer_id) "
                "AND x.resource_id IS (SELECT resource_id "
                "FROM collaboration_ownership_transfers "
                "WHERE transfer_id = NEW.transfer_id) "
                "AND t.sequence = (SELECT MAX(z.sequence) "
                "FROM collaboration_ownership_transfer_transitions z "
                "WHERE z.transfer_id = x.transfer_id) "
                "AND t.current_state = 'pending') "
                "THEN RAISE(ABORT, 'duplicate pending ownership transfer') END; END"
            )
        )
        return
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_share_transition() "
            "RETURNS trigger AS $$ DECLARE prior "
            "collaboration_resource_share_transitions%ROWTYPE; BEGIN "
            "IF NEW.sequence = 0 THEN IF NEW.previous_state IS NOT NULL "
            "OR NEW.current_state <> 'active' THEN "
            "RAISE EXCEPTION 'invalid initial share transition'; END IF; "
            "ELSE SELECT * INTO prior FROM collaboration_resource_share_transitions "
            "WHERE share_id = NEW.share_id AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state <> NEW.previous_state "
            "OR NOT ((NEW.previous_state = 'active' AND NEW.current_state = 'revoked') "
            "OR (NEW.previous_state = 'revoked' AND NEW.current_state = 'active')) "
            "THEN RAISE EXCEPTION 'invalid share lifecycle transition'; END IF; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_share_transition_valid "
            "BEFORE INSERT ON collaboration_resource_share_transitions "
            "FOR EACH ROW EXECUTE FUNCTION validate_collaboration_share_transition()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_ownership_transition() "
            "RETURNS trigger AS $$ DECLARE prior "
            "collaboration_resource_ownership_transitions%ROWTYPE; BEGIN "
            "IF NEW.sequence = 0 THEN IF NEW.previous_owner_kind IS NOT NULL "
            "OR NEW.current_owner_kind <> 'workspace' THEN "
            "RAISE EXCEPTION 'invalid initial resource ownership'; END IF; "
            "ELSE SELECT * INTO prior FROM "
            "collaboration_resource_ownership_transitions WHERE "
            "resource_id = NEW.resource_id AND workspace_id = NEW.workspace_id "
            "AND resource_kind = NEW.resource_kind AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL "
            "OR prior.current_owner_kind IS DISTINCT FROM NEW.previous_owner_kind "
            "OR prior.current_owner_membership_id IS DISTINCT FROM "
            "NEW.previous_owner_membership_id "
            "OR prior.current_owner_user_id IS DISTINCT FROM "
            "NEW.previous_owner_user_id THEN "
            "RAISE EXCEPTION 'invalid resource ownership sequence'; END IF; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_ownership_transition_valid "
            "BEFORE INSERT ON collaboration_resource_ownership_transitions "
            "FOR EACH ROW EXECUTE FUNCTION "
            "validate_collaboration_ownership_transition()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_transfer_transition() "
            "RETURNS trigger AS $$ DECLARE prior "
            "collaboration_ownership_transfer_transitions%ROWTYPE; BEGIN "
            "IF NEW.sequence = 0 THEN IF NEW.previous_state IS NOT NULL "
            "OR NEW.current_state <> 'pending' THEN "
            "RAISE EXCEPTION 'invalid initial ownership transfer'; END IF; "
            "ELSE SELECT * INTO prior FROM "
            "collaboration_ownership_transfer_transitions "
            "WHERE transfer_id = NEW.transfer_id AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state <> NEW.previous_state "
            "OR NEW.previous_state <> 'pending' OR NEW.current_state = 'pending' "
            "THEN RAISE EXCEPTION 'invalid ownership transfer lifecycle'; END IF; END IF; "
            "IF NEW.current_state = 'pending' AND EXISTS ("
            "SELECT 1 FROM collaboration_ownership_transfers x "
            "JOIN collaboration_ownership_transfer_transitions t "
            "ON t.transfer_id = x.transfer_id "
            "WHERE x.workspace_id = NEW.workspace_id "
            "AND x.transfer_id <> NEW.transfer_id "
            "AND x.transfer_kind = (SELECT transfer_kind "
            "FROM collaboration_ownership_transfers "
            "WHERE transfer_id = NEW.transfer_id) "
            "AND x.resource_id IS NOT DISTINCT FROM (SELECT resource_id "
            "FROM collaboration_ownership_transfers "
            "WHERE transfer_id = NEW.transfer_id) "
            "AND t.sequence = (SELECT MAX(z.sequence) "
            "FROM collaboration_ownership_transfer_transitions z "
            "WHERE z.transfer_id = x.transfer_id) "
            "AND t.current_state = 'pending') THEN "
            "RAISE EXCEPTION 'duplicate pending ownership transfer'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_transfer_transition_valid "
            "BEFORE INSERT ON collaboration_ownership_transfer_transitions "
            "FOR EACH ROW EXECUTE FUNCTION validate_collaboration_transfer_transition()"
        )
    )


def _replace_membership_guard(*, allow_ownership_transfer: bool) -> None:
    dialect = op.get_bind().dialect.name
    normal = (
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
    transfer = (
        " OR (NEW.previous_state = 'active' AND NEW.current_state = 'active' "
        "AND NEW.previous_role <> NEW.current_role "
        "AND NEW.reason_code = 'workspace_ownership_transferred' "
        "AND (NEW.previous_role = 'owner' OR NEW.current_role = 'owner'))"
        if allow_ownership_transfer
        else ""
    )
    allowed = normal + transfer
    if dialect == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_workspace_membership_transition_valid"))
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
                "SELECT CASE WHEN NEW.current_state IN ('active','suspended') "
                "AND EXISTS (SELECT 1 FROM workspace_memberships m "
                "JOIN workspace_membership_transitions t "
                "ON t.membership_id = m.membership_id "
                "WHERE m.user_id = NEW.user_id "
                "AND m.workspace_id = NEW.workspace_id "
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
                "JOIN workspace_membership_transitions t "
                "ON t.membership_id = m.membership_id "
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
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_workspace_membership_transition() "
            "RETURNS trigger AS $$ DECLARE prior "
            "workspace_membership_transitions%ROWTYPE; BEGIN "
            "IF NEW.sequence = 0 THEN IF NEW.previous_state IS NOT NULL "
            "OR NEW.previous_role IS NOT NULL THEN "
            "RAISE EXCEPTION 'invalid initial membership transition'; END IF; "
            "ELSE SELECT * INTO prior FROM workspace_membership_transitions "
            "WHERE membership_id = NEW.membership_id "
            "AND sequence = NEW.sequence - 1; "
            "IF prior.transition_id IS NULL OR prior.current_state <> NEW.previous_state "
            "OR prior.current_role <> NEW.previous_role THEN "
            "RAISE EXCEPTION 'invalid membership transition sequence'; END IF; "
            f"IF NOT ({allowed}) THEN "
            "RAISE EXCEPTION 'invalid membership lifecycle transition'; END IF; END IF; "
            "IF NEW.current_state IN ('active','suspended') AND EXISTS ("
            "SELECT 1 FROM workspace_memberships m "
            "JOIN workspace_membership_transitions t "
            "ON t.membership_id = m.membership_id "
            "WHERE m.user_id = NEW.user_id "
            "AND m.workspace_id = NEW.workspace_id "
            "AND m.membership_id <> NEW.membership_id "
            "AND t.sequence = (SELECT MAX(x.sequence) "
            "FROM workspace_membership_transitions x "
            "WHERE x.membership_id = m.membership_id) "
            "AND t.current_state IN ('active','suspended')) THEN "
            "RAISE EXCEPTION 'duplicate active membership'; END IF; "
            "IF NEW.current_role = 'owner' "
            "AND NEW.current_state IN ('active','suspended') "
            "AND NOT EXISTS (SELECT 1 FROM workspaces w "
            "WHERE w.id = NEW.workspace_id AND w.owner_id = NEW.user_id) THEN "
            "RAISE EXCEPTION 'owner membership mismatch'; END IF; "
            "IF NEW.current_role = 'owner' "
            "AND NEW.current_state IN ('active','suspended') AND EXISTS ("
            "SELECT 1 FROM workspace_memberships m "
            "JOIN workspace_membership_transitions t "
            "ON t.membership_id = m.membership_id "
            "WHERE m.workspace_id = NEW.workspace_id "
            "AND m.membership_id <> NEW.membership_id "
            "AND t.sequence = (SELECT MAX(x.sequence) "
            "FROM workspace_membership_transitions x "
            "WHERE x.membership_id = m.membership_id) "
            "AND t.current_role = 'owner' "
            "AND t.current_state IN ('active','suspended')) THEN "
            "RAISE EXCEPTION 'multiple workspace owners'; END IF; "
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


def downgrade() -> None:
    bind = op.get_bind()
    evidence = (
        ("collaboration_resource_shares", ""),
        ("collaboration_ownership_transfers", ""),
        ("collaboration_authority_snapshots", ""),
        ("collaboration_revocation_fences", ""),
        ("collaboration_resource_ownership_transitions", " WHERE sequence > 0"),
    )
    for table, where in evidence:
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}{where}")).scalar_one()
        if count:
            raise RuntimeError("Downgrade refused: Milestone 6.3 append-only evidence exists.")
    _replace_membership_guard(allow_ownership_transfer=False)
    _drop_lifecycle_guards()
    _drop_resource_registration_triggers()
    for table in reversed(NEW_TABLES):
        _unprotect(table)
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    _replace_closed_checks(add=False)


def _drop_lifecycle_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for trigger in (
            "trg_collaboration_share_transition_valid",
            "trg_collaboration_ownership_transition_valid",
            "trg_collaboration_transfer_transition_valid",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
        return
    pairs = (
        (
            "trg_collaboration_share_transition_valid",
            "collaboration_resource_share_transitions",
            "validate_collaboration_share_transition",
        ),
        (
            "trg_collaboration_ownership_transition_valid",
            "collaboration_resource_ownership_transitions",
            "validate_collaboration_ownership_transition",
        ),
        (
            "trg_collaboration_transfer_transition_valid",
            "collaboration_ownership_transfer_transitions",
            "validate_collaboration_transfer_transition",
        ),
    )
    for trigger, table, function in pairs:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))


def _drop_resource_registration_triggers() -> None:
    tables = (
        "canvases",
        "canonical_objects",
        "controlled_workflow_definitions",
        "bounded_agent_identities",
    )
    for table in tables:
        if op.get_bind().dialect.name == "sqlite":
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_collaboration_resource"))
        else:
            op.execute(
                sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_collaboration_resource ON {table}")
            )
            op.execute(
                sa.text(f"DROP FUNCTION IF EXISTS register_{table}_collaboration_resource()")
            )
