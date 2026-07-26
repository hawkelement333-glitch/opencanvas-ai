"""Add bounded comments and collaboration activity contracts.

Revision ID: 20260725_0024
Revises: 20260725_0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260725_0024"
down_revision: str | None = "20260725_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_EVENT_TYPES = (
    "comment.created",
    "comment.reply.created",
    "comment.revised",
    "comment.tombstoned",
    "comment.thread.resolved",
    "comment.thread.reopened",
)
NEW_SUBJECT_KINDS = ("comment_thread", "comment")
NEW_REQUEST_OPERATIONS = (
    "comment.create",
    "comment.reply",
    "comment.revise",
    "comment.tombstone",
    "comment.thread.resolve",
    "comment.thread.reopen",
)
NEW_REQUEST_RESULT_KINDS = (
    "comment_thread",
    "comment",
    "comment_revision",
    "comment_transition",
    "comment_thread_transition",
)
NEW_AUDIT_SUBJECTS = (
    "comment_thread",
    "comment",
    "comment_revision",
    "comment_transition",
)
NEW_TABLES = (
    "collaboration_comment_threads",
    "collaboration_comment_thread_transitions",
    "collaboration_comments",
    "collaboration_comment_revisions",
    "collaboration_comment_transitions",
)


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _existing_check_values(table: str, constraint: str) -> tuple[str, ...]:
    if context.is_offline_mode():
        from opencanvas_api.db.models import (
            CollaborationAuditEvent,
            CollaborationRequestIdentity,
            DomainEventRecord,
        )

        tables = {
            "domain_events": DomainEventRecord.__table__,
            "collaboration_request_identities": CollaborationRequestIdentity.__table__,
            "collaboration_audit_events": CollaborationAuditEvent.__table__,
        }
        check = next(
            item
            for item in tables[table].constraints
            if isinstance(item, sa.CheckConstraint) and item.name == constraint
        )
        text = str(check.sqltext)
    else:
        checks = sa.inspect(op.get_bind()).get_check_constraints(table)
        text = next(item["sqltext"] for item in checks if item.get("name") == constraint)
    start = text.index("(") + 1
    end = text.rindex(")")
    return tuple(value.strip().strip("'").strip('"') for value in text[start:end].split(","))


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
            "FOR EACH ROW EXECUTE FUNCTION reject_controlled_agent_security_mutation()"
        )
    )


def _unprotect(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"))
        return
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_mutation_blocked ON {table}"))


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
            "EXECUTE FUNCTION reject_controlled_agent_security_mutation()"
        )
    )


def _replace_closed_checks(*, add: bool) -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    event_types = list(_existing_check_values("domain_events", "ck_domain_events_type"))
    subject_kinds = list(_existing_check_values("domain_events", "ck_domain_events_subject_kind"))
    request_operations = list(
        _existing_check_values(
            "collaboration_request_identities",
            "ck_collaboration_request_operation",
        )
    )
    result_kinds = list(
        _existing_check_values(
            "collaboration_request_identities",
            "ck_collaboration_request_result_kind",
        )
    )
    audit_subjects = list(
        _existing_check_values(
            "collaboration_audit_events",
            "ck_collaboration_audit_subject_kind",
        )
    )
    groups: tuple[tuple[list[str], Sequence[str]], ...] = (
        (event_types, NEW_EVENT_TYPES),
        (subject_kinds, NEW_SUBJECT_KINDS),
        (request_operations, NEW_REQUEST_OPERATIONS),
        (result_kinds, NEW_REQUEST_RESULT_KINDS),
        (audit_subjects, NEW_AUDIT_SUBJECTS),
    )
    for values, delta in groups:
        if add:
            values.extend(value for value in delta if value not in values)
        else:
            values[:] = [value for value in values if value not in delta]
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
            "ck_domain_events_type",
            f"event_type IN ({_in(event_types)})",
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


def upgrade() -> None:
    _replace_closed_checks(add=True)
    _create_thread_tables()
    _create_comment_tables()
    _install_guards()
    for table in NEW_TABLES:
        _protect(table)


def _create_thread_tables() -> None:
    op.create_table(
        "collaboration_comment_threads",
        sa.Column("thread_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=True),
        sa.Column("resource_sequence", sa.Integer(), nullable=False),
        sa.Column("creator_membership_id", sa.Uuid(), nullable=False),
        sa.Column("creator_user_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("creation_request_id", sa.Uuid(), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_id", "workspace_id", "resource_kind"],
            [
                "collaboration_resources.resource_id",
                "collaboration_resources.workspace_id",
                "collaboration_resources.resource_kind",
            ],
            name="fk_collaboration_comment_thread_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creator_membership_id", "creator_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_thread_creator_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id"],
            ["canvases.id"],
            name="fk_collaboration_comment_thread_canvas",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_comment_thread_audit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "workspace_id",
            "resource_id",
            "resource_kind",
            name="uq_collaboration_comment_thread_scope",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "resource_id",
            "resource_kind",
            "resource_sequence",
            name="uq_collaboration_comment_thread_resource_sequence",
        ),
        sa.CheckConstraint(
            "resource_kind IN ('canvas', 'canonical_object', 'workflow', 'agent')",
            name="ck_collaboration_comment_thread_resource_kind",
        ),
        sa.CheckConstraint(
            "resource_sequence > 0",
            name="ck_collaboration_comment_thread_sequence",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_thread_generation",
        ),
        sa.CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_comment_thread_policy",
        ),
    )
    op.create_index(
        "ix_collaboration_comment_thread_resource",
        "collaboration_comment_threads",
        ["workspace_id", "resource_kind", "resource_id", "resource_sequence"],
    )
    op.create_index(
        "ix_collaboration_comment_thread_creator",
        "collaboration_comment_threads",
        ["workspace_id", "creator_membership_id", "created_at"],
    )
    op.create_table(
        "collaboration_comment_thread_transitions",
        sa.Column("transition_id", sa.Uuid(), primary_key=True),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(16), nullable=True),
        sa.Column("current_state", sa.String(16), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comment_threads.thread_id",
                "collaboration_comment_threads.workspace_id",
                "collaboration_comment_threads.resource_id",
                "collaboration_comment_threads.resource_kind",
            ],
            name="fk_collaboration_comment_thread_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "actor_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_thread_transition_actor_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_comment_thread_transition_audit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "sequence",
            name="uq_collaboration_comment_thread_transition_sequence",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('open', 'resolved', 'reopened')",
            name="ck_collaboration_comment_thread_transition_previous",
        ),
        sa.CheckConstraint(
            "current_state IN ('open', 'resolved', 'reopened')",
            name="ck_collaboration_comment_thread_transition_state",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_collaboration_comment_thread_transition_sequence",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_thread_transition_generation",
        ),
    )
    op.create_index(
        "ix_collaboration_comment_thread_transition_current",
        "collaboration_comment_thread_transitions",
        ["workspace_id", "thread_id", "sequence"],
    )
    op.create_index(
        "ix_collaboration_comment_thread_transition_state",
        "collaboration_comment_thread_transitions",
        ["workspace_id", "current_state", "recorded_at"],
    )


def _create_comment_tables() -> None:
    op.create_table(
        "collaboration_comments",
        sa.Column("comment_id", sa.Uuid(), primary_key=True),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("parent_comment_id", sa.Uuid(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("thread_sequence", sa.Integer(), nullable=False),
        sa.Column("author_membership_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("collaboration_policy_version", sa.String(40), nullable=False),
        sa.Column("creation_request_id", sa.Uuid(), nullable=False),
        sa.Column("creation_trace_id", sa.Uuid(), nullable=False),
        sa.Column("creation_audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comment_threads.thread_id",
                "collaboration_comment_threads.workspace_id",
                "collaboration_comment_threads.resource_id",
                "collaboration_comment_threads.resource_kind",
            ],
            name="fk_collaboration_comment_thread_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "parent_comment_id",
                "thread_id",
                "workspace_id",
                "resource_id",
                "resource_kind",
            ],
            [
                "collaboration_comments.comment_id",
                "collaboration_comments.thread_id",
                "collaboration_comments.workspace_id",
                "collaboration_comments.resource_id",
                "collaboration_comments.resource_kind",
            ],
            name="fk_collaboration_comment_parent_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_membership_id", "author_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_author_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creation_audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_comment_audit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "comment_id",
            "thread_id",
            "workspace_id",
            "resource_id",
            "resource_kind",
            name="uq_collaboration_comment_scope",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "thread_sequence",
            name="uq_collaboration_comment_thread_sequence",
        ),
        sa.CheckConstraint("depth BETWEEN 0 AND 4", name="ck_collaboration_comment_depth"),
        sa.CheckConstraint(
            "(depth = 0 AND parent_comment_id IS NULL) OR "
            "(depth > 0 AND parent_comment_id IS NOT NULL)",
            name="ck_collaboration_comment_parent_shape",
        ),
        sa.CheckConstraint(
            "parent_comment_id IS NULL OR parent_comment_id <> comment_id",
            name="ck_collaboration_comment_not_self_parent",
        ),
        sa.CheckConstraint(
            "thread_sequence > 0",
            name="ck_collaboration_comment_thread_sequence",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_generation",
        ),
        sa.CheckConstraint(
            "collaboration_policy_version = 'collaboration-policy-v1'",
            name="ck_collaboration_comment_policy",
        ),
    )
    op.create_index(
        "ix_collaboration_comment_thread_order",
        "collaboration_comments",
        ["workspace_id", "thread_id", "thread_sequence", "comment_id"],
    )
    op.create_index(
        "ix_collaboration_comment_author",
        "collaboration_comments",
        ["workspace_id", "author_membership_id", "created_at"],
    )
    op.create_index(
        "ix_collaboration_comment_parent",
        "collaboration_comments",
        ["workspace_id", "parent_comment_id", "thread_sequence"],
    )
    op.create_table(
        "collaboration_comment_revisions",
        sa.Column("revision_id", sa.Uuid(), primary_key=True),
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=True),
        sa.Column("revision_kind", sa.String(16), nullable=False),
        sa.Column("author_membership_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["comment_id", "thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comments.comment_id",
                "collaboration_comments.thread_id",
                "collaboration_comments.workspace_id",
                "collaboration_comments.resource_id",
                "collaboration_comments.resource_kind",
            ],
            name="fk_collaboration_comment_revision_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id", "comment_id", "workspace_id"],
            [
                "collaboration_comment_revisions.revision_id",
                "collaboration_comment_revisions.comment_id",
                "collaboration_comment_revisions.workspace_id",
            ],
            name="fk_collaboration_comment_revision_previous",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_membership_id", "author_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_revision_author_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_comment_revision_audit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "comment_id",
            "workspace_id",
            name="uq_collaboration_comment_revision_scope",
        ),
        sa.UniqueConstraint(
            "comment_id",
            "sequence",
            name="uq_collaboration_comment_revision_sequence",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_collaboration_comment_revision_sequence",
        ),
        sa.CheckConstraint(
            "revision_kind IN ('created', 'edited')",
            name="ck_collaboration_comment_revision_kind",
        ),
        sa.CheckConstraint(
            "(sequence = 1 AND revision_kind = 'created' AND "
            "previous_revision_id IS NULL) OR "
            "(sequence > 1 AND revision_kind = 'edited' AND "
            "previous_revision_id IS NOT NULL)",
            name="ck_collaboration_comment_revision_previous_shape",
        ),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 5000",
            name="ck_collaboration_comment_revision_content_length",
        ),
        sa.CheckConstraint(
            "length(content_digest) = 64",
            name="ck_collaboration_comment_revision_digest",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_revision_generation",
        ),
    )
    op.create_index(
        "ix_collaboration_comment_revision_history",
        "collaboration_comment_revisions",
        ["workspace_id", "comment_id", "sequence"],
    )
    op.create_index(
        "ix_collaboration_comment_revision_author",
        "collaboration_comment_revisions",
        ["workspace_id", "author_membership_id", "created_at"],
    )
    op.create_table(
        "collaboration_comment_transitions",
        sa.Column("transition_id", sa.Uuid(), primary_key=True),
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("current_state", sa.String(32), nullable=False),
        sa.Column("visible_revision_id", sa.Uuid(), nullable=True),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["comment_id", "thread_id", "workspace_id", "resource_id", "resource_kind"],
            [
                "collaboration_comments.comment_id",
                "collaboration_comments.thread_id",
                "collaboration_comments.workspace_id",
                "collaboration_comments.resource_id",
                "collaboration_comments.resource_kind",
            ],
            name="fk_collaboration_comment_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visible_revision_id", "comment_id", "workspace_id"],
            [
                "collaboration_comment_revisions.revision_id",
                "collaboration_comment_revisions.comment_id",
                "collaboration_comment_revisions.workspace_id",
            ],
            name="fk_collaboration_comment_transition_visible_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id", "actor_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_collaboration_comment_transition_actor_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["collaboration_audit_events.audit_event_id"],
            name="fk_collaboration_comment_transition_audit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "comment_id",
            "sequence",
            name="uq_collaboration_comment_transition_sequence",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('active', 'edited', 'hidden_by_moderation', 'removed_by_author')",
            name="ck_collaboration_comment_transition_previous",
        ),
        sa.CheckConstraint(
            "current_state IN ('active', 'edited', 'hidden_by_moderation', 'removed_by_author')",
            name="ck_collaboration_comment_transition_state",
        ),
        sa.CheckConstraint(
            "(current_state IN ('active', 'edited') AND visible_revision_id IS NOT NULL) "
            "OR (current_state IN ('hidden_by_moderation', 'removed_by_author') "
            "AND visible_revision_id IS NULL)",
            name="ck_collaboration_comment_transition_visibility",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_collaboration_comment_transition_sequence",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_collaboration_comment_transition_generation",
        ),
    )
    op.create_index(
        "ix_collaboration_comment_transition_current",
        "collaboration_comment_transitions",
        ["workspace_id", "comment_id", "sequence"],
    )
    op.create_index(
        "ix_collaboration_comment_transition_state",
        "collaboration_comment_transitions",
        ["workspace_id", "current_state", "recorded_at"],
    )


def _install_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _install_sqlite_guards()
    else:
        _install_postgresql_guards()


def _install_sqlite_guards() -> None:
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_thread_scope_valid "
            "BEFORE INSERT ON collaboration_comment_threads BEGIN "
            "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM collaboration_resources r "
            "WHERE r.resource_id = NEW.resource_id AND r.workspace_id = NEW.workspace_id "
            "AND r.resource_kind = NEW.resource_kind AND r.canvas_id IS NEW.canvas_id) "
            "THEN RAISE(ABORT, 'invalid comment thread resource scope') END; END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_insert_valid "
            "BEFORE INSERT ON collaboration_comments BEGIN "
            "SELECT CASE WHEN (SELECT current_state FROM "
            "collaboration_comment_thread_transitions t WHERE t.thread_id = NEW.thread_id "
            "ORDER BY t.sequence DESC LIMIT 1) = 'resolved' "
            "THEN RAISE(ABORT, 'resolved comment thread rejects replies') END; "
            "SELECT CASE WHEN NEW.parent_comment_id IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM collaboration_comments p WHERE p.comment_id = NEW.parent_comment_id "
            "AND NEW.depth = p.depth + 1) "
            "THEN RAISE(ABORT, 'invalid comment reply depth') END; "
            "SELECT CASE WHEN NEW.parent_comment_id IS NOT NULL AND EXISTS ("
            "SELECT 1 FROM collaboration_comment_transitions s "
            "WHERE s.comment_id = NEW.parent_comment_id "
            "AND s.sequence = (SELECT MAX(x.sequence) FROM collaboration_comment_transitions x "
            "WHERE x.comment_id = NEW.parent_comment_id) "
            "AND s.current_state IN ('hidden_by_moderation','removed_by_author')) "
            "THEN RAISE(ABORT, 'tombstoned comment rejects replies') END; "
            "SELECT CASE WHEN (SELECT COUNT(*) FROM collaboration_comments c "
            "WHERE c.thread_id = NEW.thread_id) >= 500 "
            "THEN RAISE(ABORT, 'comment thread limit exceeded') END; END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_revision_valid "
            "BEFORE INSERT ON collaboration_comment_revisions BEGIN "
            "SELECT CASE WHEN NEW.sequence = 1 AND "
            "(NEW.previous_revision_id IS NOT NULL OR NEW.revision_kind <> 'created') "
            "THEN RAISE(ABORT, 'invalid initial comment revision') END; "
            "SELECT CASE WHEN NEW.sequence > 1 AND NOT EXISTS ("
            "SELECT 1 FROM collaboration_comment_revisions p "
            "WHERE p.comment_id = NEW.comment_id AND p.sequence = NEW.sequence - 1 "
            "AND p.revision_id = NEW.previous_revision_id) "
            "THEN RAISE(ABORT, 'invalid comment revision sequence') END; END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_transition_valid "
            "BEFORE INSERT ON collaboration_comment_transitions BEGIN "
            "SELECT CASE WHEN NEW.sequence = 0 AND "
            "(NEW.previous_state IS NOT NULL OR NEW.current_state <> 'active') "
            "THEN RAISE(ABORT, 'invalid initial comment transition') END; "
            "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
            "SELECT 1 FROM collaboration_comment_transitions p "
            "WHERE p.comment_id = NEW.comment_id AND p.sequence = NEW.sequence - 1 "
            "AND p.current_state = NEW.previous_state) "
            "THEN RAISE(ABORT, 'invalid comment transition sequence') END; "
            "SELECT CASE WHEN NEW.sequence > 0 AND NEW.previous_state "
            "IN ('hidden_by_moderation','removed_by_author') "
            "THEN RAISE(ABORT, 'comment tombstone is terminal') END; "
            "SELECT CASE WHEN NEW.current_state = 'edited' AND NOT EXISTS ("
            "SELECT 1 FROM collaboration_comment_revisions r "
            "WHERE r.revision_id = NEW.visible_revision_id AND r.comment_id = NEW.comment_id "
            "AND r.sequence = (SELECT MAX(x.sequence) FROM collaboration_comment_revisions x "
            "WHERE x.comment_id = NEW.comment_id)) "
            "THEN RAISE(ABORT, 'edited comment must expose latest revision') END; END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_thread_transition_valid "
            "BEFORE INSERT ON collaboration_comment_thread_transitions BEGIN "
            "SELECT CASE WHEN NEW.sequence = 0 AND "
            "(NEW.previous_state IS NOT NULL OR NEW.current_state <> 'open') "
            "THEN RAISE(ABORT, 'invalid initial comment thread') END; "
            "SELECT CASE WHEN NEW.sequence > 0 AND NOT EXISTS ("
            "SELECT 1 FROM collaboration_comment_thread_transitions p "
            "WHERE p.thread_id = NEW.thread_id AND p.sequence = NEW.sequence - 1 "
            "AND p.current_state = NEW.previous_state) "
            "THEN RAISE(ABORT, 'invalid comment thread sequence') END; "
            "SELECT CASE WHEN NEW.sequence > 0 AND NOT ("
            "(NEW.previous_state IN ('open','reopened') AND NEW.current_state = 'resolved') "
            "OR (NEW.previous_state = 'resolved' AND NEW.current_state = 'reopened')) "
            "THEN RAISE(ABORT, 'invalid comment thread lifecycle') END; END"
        )
    )


def _install_postgresql_guards() -> None:
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_comment_thread_scope() "
            "RETURNS trigger AS $$ BEGIN IF NOT EXISTS (SELECT 1 FROM "
            "collaboration_resources r WHERE r.resource_id = NEW.resource_id "
            "AND r.workspace_id = NEW.workspace_id AND r.resource_kind = NEW.resource_kind "
            "AND r.canvas_id IS NOT DISTINCT FROM NEW.canvas_id) THEN "
            "RAISE EXCEPTION 'invalid comment thread resource scope'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_thread_scope_valid "
            "BEFORE INSERT ON collaboration_comment_threads FOR EACH ROW "
            "EXECUTE FUNCTION validate_collaboration_comment_thread_scope()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_comment_insert() "
            "RETURNS trigger AS $$ DECLARE parent_depth integer; parent_state text; "
            "thread_state text; comment_count integer; BEGIN "
            "SELECT current_state INTO thread_state FROM "
            "collaboration_comment_thread_transitions WHERE thread_id = NEW.thread_id "
            "ORDER BY sequence DESC LIMIT 1; "
            "IF thread_state = 'resolved' THEN "
            "RAISE EXCEPTION 'resolved comment thread rejects replies'; END IF; "
            "IF NEW.parent_comment_id IS NOT NULL THEN "
            "SELECT depth INTO parent_depth FROM collaboration_comments "
            "WHERE comment_id = NEW.parent_comment_id; "
            "SELECT current_state INTO parent_state FROM collaboration_comment_transitions "
            "WHERE comment_id = NEW.parent_comment_id ORDER BY sequence DESC LIMIT 1; "
            "IF parent_depth IS NULL OR NEW.depth <> parent_depth + 1 THEN "
            "RAISE EXCEPTION 'invalid comment reply depth'; END IF; "
            "IF parent_state IN ('hidden_by_moderation','removed_by_author') THEN "
            "RAISE EXCEPTION 'tombstoned comment rejects replies'; END IF; END IF; "
            "SELECT COUNT(*) INTO comment_count FROM collaboration_comments "
            "WHERE thread_id = NEW.thread_id; IF comment_count >= 500 THEN "
            "RAISE EXCEPTION 'comment thread limit exceeded'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_insert_valid "
            "BEFORE INSERT ON collaboration_comments FOR EACH ROW "
            "EXECUTE FUNCTION validate_collaboration_comment_insert()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_comment_revision() "
            "RETURNS trigger AS $$ DECLARE prior_id uuid; BEGIN "
            "IF NEW.sequence = 1 THEN IF NEW.previous_revision_id IS NOT NULL "
            "OR NEW.revision_kind <> 'created' THEN "
            "RAISE EXCEPTION 'invalid initial comment revision'; END IF; ELSE "
            "SELECT revision_id INTO prior_id FROM collaboration_comment_revisions "
            "WHERE comment_id = NEW.comment_id AND sequence = NEW.sequence - 1; "
            "IF prior_id IS NULL OR prior_id <> NEW.previous_revision_id THEN "
            "RAISE EXCEPTION 'invalid comment revision sequence'; END IF; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_revision_valid "
            "BEFORE INSERT ON collaboration_comment_revisions FOR EACH ROW "
            "EXECUTE FUNCTION validate_collaboration_comment_revision()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_comment_transition() "
            "RETURNS trigger AS $$ DECLARE prior_state text; latest_revision uuid; BEGIN "
            "IF NEW.sequence = 0 THEN IF NEW.previous_state IS NOT NULL "
            "OR NEW.current_state <> 'active' THEN "
            "RAISE EXCEPTION 'invalid initial comment transition'; END IF; ELSE "
            "SELECT current_state INTO prior_state FROM collaboration_comment_transitions "
            "WHERE comment_id = NEW.comment_id AND sequence = NEW.sequence - 1; "
            "IF prior_state IS NULL OR prior_state <> NEW.previous_state THEN "
            "RAISE EXCEPTION 'invalid comment transition sequence'; END IF; "
            "IF prior_state IN ('hidden_by_moderation','removed_by_author') THEN "
            "RAISE EXCEPTION 'comment tombstone is terminal'; END IF; END IF; "
            "IF NEW.current_state = 'edited' THEN SELECT revision_id INTO latest_revision "
            "FROM collaboration_comment_revisions WHERE comment_id = NEW.comment_id "
            "ORDER BY sequence DESC LIMIT 1; IF latest_revision IS NULL "
            "OR latest_revision <> NEW.visible_revision_id THEN "
            "RAISE EXCEPTION 'edited comment must expose latest revision'; END IF; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_transition_valid "
            "BEFORE INSERT ON collaboration_comment_transitions FOR EACH ROW "
            "EXECUTE FUNCTION validate_collaboration_comment_transition()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION validate_collaboration_comment_thread_transition() "
            "RETURNS trigger AS $$ DECLARE prior_state text; BEGIN "
            "IF NEW.sequence = 0 THEN IF NEW.previous_state IS NOT NULL "
            "OR NEW.current_state <> 'open' THEN "
            "RAISE EXCEPTION 'invalid initial comment thread'; END IF; ELSE "
            "SELECT current_state INTO prior_state FROM "
            "collaboration_comment_thread_transitions WHERE thread_id = NEW.thread_id "
            "AND sequence = NEW.sequence - 1; IF prior_state IS NULL "
            "OR prior_state <> NEW.previous_state OR NOT ("
            "(prior_state IN ('open','reopened') AND NEW.current_state = 'resolved') "
            "OR (prior_state = 'resolved' AND NEW.current_state = 'reopened')) THEN "
            "RAISE EXCEPTION 'invalid comment thread lifecycle'; END IF; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_collaboration_comment_thread_transition_valid "
            "BEFORE INSERT ON collaboration_comment_thread_transitions FOR EACH ROW "
            "EXECUTE FUNCTION validate_collaboration_comment_thread_transition()"
        )
    )


def _drop_guards() -> None:
    names = (
        ("collaboration_comment_threads", "collaboration_comment_thread_scope_valid"),
        ("collaboration_comments", "collaboration_comment_insert_valid"),
        ("collaboration_comment_revisions", "collaboration_comment_revision_valid"),
        ("collaboration_comment_transitions", "collaboration_comment_transition_valid"),
        (
            "collaboration_comment_thread_transitions",
            "collaboration_comment_thread_transition_valid",
        ),
    )
    for table, trigger in names:
        if op.get_bind().dialect.name == "sqlite":
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{trigger}"))
        else:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{trigger} ON {table}"))
    if op.get_bind().dialect.name != "sqlite":
        for function in (
            "validate_collaboration_comment_thread_scope",
            "validate_collaboration_comment_insert",
            "validate_collaboration_comment_revision",
            "validate_collaboration_comment_transition",
            "validate_collaboration_comment_thread_transition",
        ):
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))


def downgrade() -> None:
    bind = op.get_bind()
    for table in NEW_TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("Downgrade refused: Milestone 6.4 append-only evidence exists.")
    _drop_guards()
    for table in NEW_TABLES:
        _unprotect(table)
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    _replace_closed_checks(add=False)
