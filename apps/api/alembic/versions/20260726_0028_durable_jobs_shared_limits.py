"""Add durable jobs, fenced workers, retries, dead letters, and replay evidence.

Revision ID: 20260726_0028
Revises: 20260726_0027
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0028"
down_revision: str | None = "20260726_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_TABLES = (
    "durable_job_requests",
    "durable_queue_deliveries",
    "durable_job_attempts",
    "durable_retry_decisions",
    "durable_job_outcomes",
    "durable_job_dead_letters",
    "durable_job_replay_requests",
    "durable_job_audit_events",
)
_JOB_EVENT_TYPES = (
    "job.created",
    "job.claimed",
    "job.retry_scheduled",
    "job.completed",
    "job.failed",
    "job.canceled",
    "job.dead_lettered",
    "job.replayed",
)
_JOB_SUBJECT_KINDS = ("durable_job",)
_DOMAIN_EVENT_TYPES_0027 = (
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
    "comment.created",
    "comment.reply.created",
    "comment.revised",
    "comment.tombstoned",
    "comment.thread.resolved",
    "comment.thread.reopened",
    "ingestion.requested",
    "ingestion.queued",
    "ingestion.failed",
    "ingestion.canceled",
    "index.reindex.requested",
    "index.revision.created",
    "index.published",
    "index.superseded",
    "upload.requested",
    "upload.completed",
    "object.quarantined",
    "scan.started",
    "scan.passed",
    "scan.rejected",
    "object.promoted",
    "object.failed",
    "object.deletion_requested",
)
_DOMAIN_EVENT_SUBJECT_KINDS_0027 = (
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
    "collaboration_resource",
    "resource_share",
    "ownership_transfer",
    "authority_fence",
    "comment_thread",
    "comment",
    "ingestion_request",
    "index_revision",
    "index_publication",
    "upload_session",
    "storage_object_version",
    "malware_scan_request",
    "malware_scan_result",
    "object_promotion",
)


def upgrade() -> None:
    _replace_domain_event_checks(add=True)
    _add_document_version_scope_key()
    _create_request_table()
    _extend_document_jobs()
    _create_delivery_and_attempt_tables()
    _create_retry_outcome_dead_letter_tables()
    _backfill_legacy_jobs()
    _create_append_only_guards()


def downgrade() -> None:
    _require_disposable_downgrade()
    _drop_append_only_guards()
    for table in reversed(_APPEND_ONLY_TABLES[1:]):
        op.drop_table(table)
    _restore_document_jobs()
    op.drop_table("durable_job_requests")
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("uq_document_versions_id_document", type_="unique")
    _replace_domain_event_checks(add=False)


def _replace_domain_event_checks(*, add: bool) -> None:
    event_types = _DOMAIN_EVENT_TYPES_0027 + _JOB_EVENT_TYPES if add else _DOMAIN_EVENT_TYPES_0027
    subject_kinds = (
        _DOMAIN_EVENT_SUBJECT_KINDS_0027 + _JOB_SUBJECT_KINDS
        if add
        else _DOMAIN_EVENT_SUBJECT_KINDS_0027
    )
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        for operation in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_domain_events_{operation}_blocked"))
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
                    f"BEFORE {operation} ON domain_events BEGIN "
                    "SELECT RAISE(ABORT, 'domain event evidence is append-only'); END"
                )
            )


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _add_document_version_scope_key() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.create_unique_constraint(
            "uq_document_versions_id_document",
            ["id", "document_id"],
        )


def _create_request_table() -> None:
    op.create_table(
        "durable_job_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("request_kind", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column(
            "cancellation_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_durable_job_request_membership_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_durable_job_request_canvas_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "canvas_id"],
            ["documents.id", "documents.canvas_id"],
            name="fk_durable_job_request_document_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "document_id"],
            ["document_versions.id", "document_versions.document_id"],
            name="fk_durable_job_request_version_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "idempotency_key",
            name="uq_durable_job_request_idempotency",
        ),
        sa.UniqueConstraint(
            "request_id",
            "user_id",
            "workspace_id",
            name="uq_durable_job_request_scope",
        ),
        sa.CheckConstraint(
            "request_kind IN ('document_processing', 'indexing', 'malware_scan')",
            name="ck_durable_job_request_kind",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_durable_job_request_digest",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_durable_job_request_authority_generation",
        ),
        sa.CheckConstraint(
            "cancellation_generation >= 0",
            name="ck_durable_job_request_cancellation_generation",
        ),
    )
    op.create_index(
        "ix_durable_job_request_scope_time",
        "durable_job_requests",
        ["workspace_id", "canvas_id", "created_at"],
    )
    op.create_index(
        "ix_durable_job_requests_trace_id",
        "durable_job_requests",
        ["trace_id"],
    )


def _extend_document_jobs() -> None:
    with op.batch_alter_table("document_processing_jobs") as batch:
        batch.drop_constraint("ck_document_processing_jobs_status", type_="check")
        batch.drop_index("ix_document_jobs_claim")
        batch.add_column(sa.Column("request_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("membership_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("canvas_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("document_version_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column(
                "job_kind",
                sa.String(32),
                nullable=False,
                server_default="document_processing",
            )
        )
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4")
        )
        batch.add_column(sa.Column("request_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("authority_generation", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "cancellation_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("source_version", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "priority_class",
                sa.String(24),
                nullable=False,
                server_default="normal",
            )
        )
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="50"))
        batch.add_column(
            sa.Column(
                "eligibility_class",
                sa.String(32),
                nullable=False,
                server_default="ordinary",
            )
        )
        batch.add_column(
            sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("deadline_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("result_id", sa.Uuid()))
        batch.add_column(sa.Column("publication_id", sa.Uuid()))
        batch.add_column(
            sa.Column("legacy_backfill", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_check_constraint(
            "ck_document_processing_jobs_status",
            "status IN ('queued', 'uploading', 'processing', 'extracting', 'chunking', "
            "'embedding', 'indexing', 'ready', 'retrying', 'retryable_failure', "
            "'permanent_failure', 'cancelled', 'failed', 'claimed', 'retry_waiting', "
            "'dead_lettered', 'succeeded')",
        )
        batch.create_check_constraint(
            "ck_document_jobs_kind",
            "job_kind IN ('document_processing', 'indexing', 'malware_scan')",
        )
        batch.create_check_constraint(
            "ck_document_jobs_priority_class",
            "priority_class IN ('interactive', 'normal', 'maintenance')",
        )
        batch.create_check_constraint(
            "ck_document_jobs_priority",
            "priority BETWEEN 0 AND 100",
        )
        batch.create_check_constraint(
            "ck_document_jobs_authority_generation",
            "authority_generation IS NULL OR authority_generation > 0",
        )
        batch.create_check_constraint(
            "ck_document_jobs_generations",
            "cancellation_generation >= 0 AND lease_generation >= 0",
        )
        batch.create_check_constraint(
            "ck_document_jobs_attempts_bounded",
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
        )
        batch.create_check_constraint(
            "ck_document_jobs_deadline",
            "deadline_at IS NULL OR deadline_at > created_at",
        )
        batch.create_check_constraint(
            "ck_document_jobs_lease_shape",
            "(locked_by IS NULL AND lease_expires_at IS NULL) OR "
            "(locked_by IS NOT NULL AND lease_expires_at IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_document_jobs_request_digest",
            "request_digest IS NULL OR length(request_digest) = 64",
        )
        batch.create_unique_constraint(
            "uq_document_processing_jobs_request",
            ["request_id"],
        )
        batch.create_unique_constraint(
            "uq_document_processing_jobs_scope",
            ["id", "user_id", "workspace_id"],
        )
        batch.create_foreign_key(
            "fk_document_jobs_request_scope",
            "durable_job_requests",
            ["request_id", "user_id", "workspace_id"],
            ["request_id", "user_id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_jobs_membership_scope",
            "workspace_memberships",
            ["membership_id", "user_id", "workspace_id"],
            ["membership_id", "user_id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_jobs_canvas_scope",
            "canvases",
            ["canvas_id", "workspace_id"],
            ["id", "workspace_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_jobs_document_scope",
            "documents",
            ["document_id", "canvas_id"],
            ["id", "canvas_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_document_jobs_version_scope",
            "document_versions",
            ["document_version_id", "document_id"],
            ["id", "document_id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_document_jobs_claim",
            [
                "status",
                "available_at",
                "priority_class",
                "priority",
                "created_at",
            ],
        )
        batch.create_index(
            "ix_document_jobs_fair_claim",
            ["workspace_id", "status", "available_at", "priority", "created_at"],
        )
        batch.create_index(
            "ix_document_jobs_lease_expiry",
            ["lease_expires_at", "lease_generation"],
        )
        batch.create_index(
            "ix_document_jobs_reconcile",
            ["status", "deadline_at", "lease_expires_at", "id"],
        )
        batch.create_index("ix_document_processing_jobs_request_id", ["request_id"])
        batch.create_index("ix_document_processing_jobs_canvas_id", ["canvas_id"])
        batch.create_index(
            "ix_document_processing_jobs_document_version_id",
            ["document_version_id"],
        )


def _create_delivery_and_attempt_tables() -> None:
    op.create_table(
        "durable_queue_deliveries",
        sa.Column("delivery_id", sa.Uuid(), primary_key=True),
        sa.Column("job_run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_sequence", sa.Integer(), nullable=False),
        sa.Column("delivery_kind", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id", "user_id", "workspace_id"],
            [
                "document_processing_jobs.id",
                "document_processing_jobs.user_id",
                "document_processing_jobs.workspace_id",
            ],
            name="fk_durable_queue_delivery_job_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_durable_queue_delivery_idempotency",
        ),
        sa.UniqueConstraint(
            "job_run_id",
            "delivery_sequence",
            name="uq_durable_queue_delivery_sequence",
        ),
        sa.CheckConstraint(
            "delivery_sequence > 0",
            name="ck_durable_queue_delivery_sequence",
        ),
        sa.CheckConstraint(
            "delivery_kind IN ('enqueue', 'retry', 'replay', 'recovery', 'reconcile')",
            name="ck_durable_queue_delivery_kind",
        ),
    )
    op.create_index(
        "ix_durable_queue_delivery_eligible",
        "durable_queue_deliveries",
        ["eligible_at", "job_run_id", "delivery_sequence"],
    )
    op.create_table(
        "durable_job_attempts",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("job_run_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(120)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("failure_classification", sa.String(64)),
        sa.Column("trace_id", sa.Uuid()),
        sa.Column("audit_event_id", sa.Uuid()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id", "user_id", "workspace_id"],
            [
                "document_processing_jobs.id",
                "document_processing_jobs.user_id",
                "document_processing_jobs.workspace_id",
            ],
            name="fk_durable_job_attempt_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["durable_queue_deliveries.delivery_id"],
            name="fk_durable_job_attempt_delivery",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "job_run_id",
            "attempt_number",
            name="uq_durable_job_attempt_number",
        ),
        sa.UniqueConstraint(
            "job_run_id",
            "lease_generation",
            name="uq_durable_job_attempt_generation",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_durable_job_attempt_number",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_durable_job_attempt_generation",
        ),
        sa.CheckConstraint(
            "outcome IN ('running', 'succeeded', 'retry_scheduled', "
            "'terminal_failure', 'canceled', 'deadline_expired', "
            "'authority_revoked', 'lease_lost', 'legacy_queued', "
            "'legacy_processing', 'legacy_ready', 'legacy_failed')",
            name="ck_durable_job_attempt_outcome",
        ),
    )
    op.create_index(
        "ix_durable_job_attempt_time",
        "durable_job_attempts",
        ["job_run_id", "attempt_number", "recorded_at"],
    )
    op.create_index("ix_durable_job_attempts_trace_id", "durable_job_attempts", ["trace_id"])
    op.create_index(
        "ix_durable_job_attempts_audit_event_id",
        "durable_job_attempts",
        ["audit_event_id"],
    )


def _create_retry_outcome_dead_letter_tables() -> None:
    _create_retry_table()
    _create_outcome_table()
    _create_dead_letter_table()
    _create_replay_table()
    _create_audit_table()


def _create_retry_table() -> None:
    op.create_table(
        "durable_retry_decisions",
        sa.Column("retry_decision_id", sa.Uuid(), primary_key=True),
        sa.Column("job_run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("failure_classification", sa.String(64), nullable=False),
        sa.Column("disposition", sa.String(24), nullable=False),
        sa.Column("delay_ms", sa.Integer(), nullable=False),
        sa.Column("jitter_digest", sa.String(64), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id", "user_id", "workspace_id"],
            [
                "document_processing_jobs.id",
                "document_processing_jobs.user_id",
                "document_processing_jobs.workspace_id",
            ],
            name="fk_durable_retry_decision_job_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "job_run_id",
            "attempt_number",
            name="uq_durable_retry_decision_attempt",
        ),
        sa.CheckConstraint(
            "failure_classification IN ('dependency_unavailable', "
            "'connection_interrupted', 'rate_limited', 'lease_interrupted', "
            "'provider_timeout', 'policy_rejected', 'malware', 'corrupt_input', "
            "'unsupported_format', 'canceled', 'authority_revoked', "
            "'source_superseded', 'deterministic_drift', 'deadline_exceeded', "
            "'attempts_exhausted', 'unknown_failure')",
            name="ck_durable_retry_decision_failure",
        ),
        sa.CheckConstraint(
            "disposition IN ('retry', 'terminal', 'dead_letter', 'canceled')",
            name="ck_durable_retry_decision_disposition",
        ),
        sa.CheckConstraint("delay_ms >= 0", name="ck_durable_retry_decision_delay"),
        sa.CheckConstraint(
            "length(jitter_digest) = 64",
            name="ck_durable_retry_decision_jitter_digest",
        ),
    )
    op.create_index(
        "ix_durable_retry_decision_eligible",
        "durable_retry_decisions",
        ["disposition", "eligible_at"],
    )


def _create_outcome_table() -> None:
    op.create_table(
        "durable_job_outcomes",
        sa.Column("outcome_id", sa.Uuid(), primary_key=True),
        sa.Column("job_run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("failure_classification", sa.String(64)),
        sa.Column("result_id", sa.Uuid()),
        sa.Column("publication_id", sa.Uuid()),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("domain_event_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id", "user_id", "workspace_id"],
            [
                "document_processing_jobs.id",
                "document_processing_jobs.user_id",
                "document_processing_jobs.workspace_id",
            ],
            name="fk_durable_job_outcome_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["durable_job_attempts.attempt_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_run_id", name="uq_durable_job_outcome_job"),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'canceled', 'deadline_expired', "
            "'authority_revoked', 'dead_lettered')",
            name="ck_durable_job_outcome",
        ),
    )
    op.create_index("ix_durable_job_outcome_trace", "durable_job_outcomes", ["trace_id"])


def _create_dead_letter_table() -> None:
    op.create_table(
        "durable_job_dead_letters",
        sa.Column("dead_letter_id", sa.Uuid(), primary_key=True),
        sa.Column("job_run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("failure_classification", sa.String(64), nullable=False),
        sa.Column("authority_generation", sa.Integer()),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id", "user_id", "workspace_id"],
            [
                "document_processing_jobs.id",
                "document_processing_jobs.user_id",
                "document_processing_jobs.workspace_id",
            ],
            name="fk_durable_job_dead_letter_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["durable_job_attempts.attempt_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_run_id", name="uq_durable_job_dead_letter_job"),
        sa.UniqueConstraint(
            "dead_letter_id",
            "job_run_id",
            name="uq_durable_job_dead_letter_scope",
        ),
        sa.CheckConstraint(
            "reason_code IN ('poison_job', 'attempts_exhausted', "
            "'deadline_exceeded', 'terminal_failure', 'authority_revoked', "
            "'source_superseded')",
            name="ck_durable_job_dead_letter_reason",
        ),
    )
    op.create_index(
        "ix_durable_job_dead_letter_scope",
        "durable_job_dead_letters",
        ["workspace_id", "created_at", "dead_letter_id"],
    )


def _create_replay_table() -> None:
    op.create_table(
        "durable_job_replay_requests",
        sa.Column("replay_request_id", sa.Uuid(), primary_key=True),
        sa.Column("dead_letter_id", sa.Uuid(), nullable=False),
        sa.Column("source_job_run_id", sa.Uuid(), nullable=False),
        sa.Column("new_job_run_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dead_letter_id", "source_job_run_id"],
            ["durable_job_dead_letters.dead_letter_id", "durable_job_dead_letters.job_run_id"],
            name="fk_durable_job_replay_dead_letter",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_job_run_id"],
            ["document_processing_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "new_job_run_id",
            name="uq_durable_job_replay_new_job",
        ),
        sa.CheckConstraint(
            "reason_code IN ('operator_retry', 'dependency_recovered', 'policy_corrected')",
            name="ck_durable_job_replay_reason",
        ),
        sa.CheckConstraint(
            "authority_generation > 0",
            name="ck_durable_job_replay_authority_generation",
        ),
    )
    op.create_index(
        "ix_durable_job_replay_scope",
        "durable_job_replay_requests",
        ["workspace_id", "created_at"],
    )


def _create_audit_table() -> None:
    op.create_table(
        "durable_job_audit_events",
        sa.Column("audit_event_id", sa.Uuid(), primary_key=True),
        sa.Column("job_run_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("metadata_digest", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id"],
            ["document_processing_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "action IN ('created', 'claimed', 'renewed', 'completed', 'failed', "
            "'retry_scheduled', 'canceled', 'dead_lettered', 'replayed', "
            "'stale_result_suppressed')",
            name="ck_durable_job_audit_action",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')",
            name="ck_durable_job_audit_outcome",
        ),
        sa.CheckConstraint(
            "length(metadata_digest) = 64",
            name="ck_durable_job_audit_digest",
        ),
    )
    op.create_index(
        "ix_durable_job_audit_scope",
        "durable_job_audit_events",
        ["workspace_id", "recorded_at", "audit_event_id"],
    )
    op.create_index(
        "ix_durable_job_audit_trace",
        "durable_job_audit_events",
        ["trace_id"],
    )


def _backfill_legacy_jobs() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE document_processing_jobs SET "
            "canvas_id = (SELECT documents.canvas_id FROM documents "
            "WHERE documents.id = document_processing_jobs.document_id), "
            "legacy_backfill = :legacy"
        ),
        {"legacy": True},
    )
    outcome = (
        "CASE "
        "WHEN status IN ('queued', 'retrying') THEN 'legacy_queued' "
        "WHEN status IN ('ready') THEN 'legacy_ready' "
        "WHEN status IN ('processing', 'extracting', 'chunking', 'embedding', 'indexing') "
        "THEN 'legacy_processing' "
        "ELSE 'legacy_failed' END"
    )
    bind.execute(
        sa.text(
            "INSERT INTO durable_job_attempts "
            "(attempt_id, job_run_id, delivery_id, user_id, workspace_id, "
            "attempt_number, lease_generation, worker_id, outcome, "
            "failure_classification, trace_id, audit_event_id, started_at, "
            "completed_at, recorded_at) "
            "SELECT id, id, NULL, user_id, workspace_id, attempt, 0, NULL, "
            f"{outcome}, safe_error_category, NULL, NULL, started_at, completed_at, "
            "COALESCE(completed_at, started_at, created_at) "
            "FROM document_processing_jobs"
        )
    )


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "CREATE OR REPLACE FUNCTION mobius_reject_durable_evidence_mutation() "
                "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                "RAISE EXCEPTION 'durable job evidence is append-only'; END; $$"
            )
        )
        for table in _APPEND_ONLY_TABLES:
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                    "EXECUTE FUNCTION mobius_reject_durable_evidence_mutation()"
                )
            )
        return
    for table in _APPEND_ONLY_TABLES:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'durable job evidence is append-only'); END"
                )
            )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in _APPEND_ONLY_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS mobius_reject_durable_evidence_mutation()"))
        return
    for table in _APPEND_ONLY_TABLES:
        for operation in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"))


def _require_disposable_downgrade() -> None:
    bind = op.get_bind()
    new_work = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM durable_job_requests) + "
            "(SELECT count(*) FROM durable_queue_deliveries) + "
            "(SELECT count(*) FROM durable_retry_decisions) + "
            "(SELECT count(*) FROM durable_job_outcomes) + "
            "(SELECT count(*) FROM durable_job_dead_letters) + "
            "(SELECT count(*) FROM durable_job_replay_requests) + "
            "(SELECT count(*) FROM durable_job_audit_events) + "
            "(SELECT count(*) FROM document_processing_jobs "
            "WHERE legacy_backfill = :legacy)"
        ),
        {"legacy": False},
    ).scalar_one()
    if int(new_work) != 0:
        raise RuntimeError(
            "Milestone 7.4 downgrade is allowed only before new durable work exists."
        )


def _restore_document_jobs() -> None:
    with op.batch_alter_table("document_processing_jobs") as batch:
        for name in (
            "ix_document_processing_jobs_document_version_id",
            "ix_document_processing_jobs_canvas_id",
            "ix_document_processing_jobs_request_id",
            "ix_document_jobs_reconcile",
            "ix_document_jobs_lease_expiry",
            "ix_document_jobs_fair_claim",
            "ix_document_jobs_claim",
        ):
            batch.drop_index(name)
        for name, constraint_type in (
            ("fk_document_jobs_version_scope", "foreignkey"),
            ("fk_document_jobs_document_scope", "foreignkey"),
            ("fk_document_jobs_canvas_scope", "foreignkey"),
            ("fk_document_jobs_membership_scope", "foreignkey"),
            ("fk_document_jobs_request_scope", "foreignkey"),
            ("uq_document_processing_jobs_scope", "unique"),
            ("uq_document_processing_jobs_request", "unique"),
            ("ck_document_jobs_request_digest", "check"),
            ("ck_document_jobs_lease_shape", "check"),
            ("ck_document_jobs_deadline", "check"),
            ("ck_document_jobs_attempts_bounded", "check"),
            ("ck_document_jobs_generations", "check"),
            ("ck_document_jobs_authority_generation", "check"),
            ("ck_document_jobs_priority", "check"),
            ("ck_document_jobs_priority_class", "check"),
            ("ck_document_jobs_kind", "check"),
            ("ck_document_processing_jobs_status", "check"),
        ):
            batch.drop_constraint(name, type_=constraint_type)
        for column in (
            "legacy_backfill",
            "publication_id",
            "result_id",
            "deadline_at",
            "lease_expires_at",
            "lease_generation",
            "eligibility_class",
            "priority",
            "priority_class",
            "source_version",
            "cancellation_generation",
            "authority_generation",
            "request_digest",
            "max_attempts",
            "attempt_count",
            "job_kind",
            "document_version_id",
            "canvas_id",
            "membership_id",
            "request_id",
        ):
            batch.drop_column(column)
        batch.create_check_constraint(
            "ck_document_processing_jobs_status",
            "status IN ('queued', 'uploading', 'processing', 'extracting', "
            "'chunking', 'embedding', 'indexing', 'ready', 'retrying', "
            "'retryable_failure', 'permanent_failure', 'cancelled', 'failed')",
        )
        batch.create_index(
            "ix_document_jobs_claim",
            ["status", "available_at", "created_at"],
        )
