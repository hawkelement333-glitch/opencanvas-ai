"""Add secure object ingestion and immutable malware evidence.

Revision ID: 20260726_0027
Revises: 20260726_0026
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0027"
down_revision: str | None = "20260726_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = (
    "upload_sessions",
    "upload_session_transitions",
    "storage_objects",
    "storage_object_versions",
    "storage_object_lifecycle_transitions",
    "malware_scan_requests",
    "malware_scan_results",
    "object_promotions",
    "object_ingestion_audit_events",
    "object_deletion_requests",
)
_OBJECT_EVENT_TYPES = (
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
_OBJECT_SUBJECT_KINDS = (
    "upload_session",
    "storage_object_version",
    "malware_scan_request",
    "malware_scan_result",
    "object_promotion",
)
_DOMAIN_EVENT_TYPES_0026 = (
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
)
_DOMAIN_EVENT_SUBJECT_KINDS_0026 = (
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
)


def upgrade() -> None:
    _replace_domain_event_checks(add=True)
    _create_upload_and_object_tables()
    _create_scan_and_promotion_tables()
    if not op.get_context().as_sql:
        _backfill_legacy_objects()
    _create_append_only_guards()


def downgrade() -> None:
    _drop_append_only_guards()
    for table in (
        "object_deletion_requests",
        "object_ingestion_audit_events",
        "object_promotions",
        "malware_scan_results",
        "malware_scan_requests",
        "storage_object_lifecycle_transitions",
        "storage_object_versions",
        "upload_session_transitions",
        "upload_sessions",
        "storage_objects",
    ):
        op.drop_table(table)
    _replace_domain_event_checks(add=False)


def _replace_domain_event_checks(*, add: bool) -> None:
    event_types = (
        _DOMAIN_EVENT_TYPES_0026 + _OBJECT_EVENT_TYPES if add else _DOMAIN_EVENT_TYPES_0026
    )
    subject_kinds = (
        _DOMAIN_EVENT_SUBJECT_KINDS_0026 + _OBJECT_SUBJECT_KINDS
        if add
        else _DOMAIN_EVENT_SUBJECT_KINDS_0026
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


def _create_upload_and_object_tables() -> None:
    op.create_table(
        "storage_objects",
        sa.Column("object_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "creator_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_storage_objects_canvas_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("object_id", "workspace_id", name="uq_storage_objects_scope"),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            name="uq_storage_objects_document",
        ),
        sa.CheckConstraint(
            "classification IN ('private_source', 'restricted_source')",
            name="ck_storage_objects_classification",
        ),
    )
    op.create_index("ix_storage_objects_creator_user_id", "storage_objects", ["creator_user_id"])
    op.create_index("ix_storage_objects_workspace_id", "storage_objects", ["workspace_id"])
    op.create_index("ix_storage_objects_canvas_id", "storage_objects", ["canvas_id"])
    op.create_index(
        "ix_storage_objects_document_id",
        "storage_objects",
        ["document_id"],
    )

    op.create_table(
        "upload_sessions",
        sa.Column("session_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "object_id",
            sa.Uuid(),
            sa.ForeignKey("storage_objects.object_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("object_version_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("expected_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("media_type", sa.String(160), nullable=False),
        sa.Column("extension", sa.String(16), nullable=False),
        sa.Column("capability_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_upload_sessions_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_upload_sessions_canvas_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("session_id", "workspace_id", name="uq_upload_sessions_scope"),
        sa.UniqueConstraint("object_version_id", name="uq_upload_sessions_object_version_id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "idempotency_key",
            name="uq_upload_sessions_idempotency",
        ),
        sa.CheckConstraint("expected_size_bytes > 0", name="ck_upload_sessions_expected_size"),
        sa.CheckConstraint(
            "length(expected_sha256) = 64",
            name="ck_upload_sessions_expected_sha256",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_upload_sessions_request_digest",
        ),
        sa.CheckConstraint(
            "length(capability_digest) = 64",
            name="ck_upload_sessions_capability_digest",
        ),
        sa.CheckConstraint(
            "authority_generation >= 0",
            name="ck_upload_sessions_authority_generation",
        ),
    )
    for column in (
        "user_id",
        "workspace_id",
        "canvas_id",
        "document_id",
        "document_version_id",
        "object_id",
        "trace_id",
    ):
        op.create_index(f"ix_upload_sessions_{column}", "upload_sessions", [column])
    op.create_index(
        "ix_upload_sessions_scope_expiry",
        "upload_sessions",
        ["workspace_id", "canvas_id", "expires_at"],
    )

    op.create_table(
        "upload_session_transitions",
        sa.Column("transition_id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(24), nullable=True),
        sa.Column("current_state", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id", "workspace_id"],
            ["upload_sessions.session_id", "upload_sessions.workspace_id"],
            name="fk_upload_session_transitions_session",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_upload_session_transitions_sequence",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_upload_session_transitions_sequence"),
        sa.CheckConstraint(
            "current_state IN "
            "('requested', 'uploaded', 'completed', 'canceled', 'expired', 'error')",
            name="ck_upload_session_transitions_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('requested', 'uploaded', 'completed', 'canceled', 'expired', 'error')",
            name="ck_upload_session_transitions_previous_state",
        ),
    )
    for column in ("workspace_id", "actor_user_id", "trace_id"):
        op.create_index(
            f"ix_upload_session_transitions_{column}",
            "upload_session_transitions",
            [column],
        )
    op.create_index(
        "ix_upload_session_transitions_latest",
        "upload_session_transitions",
        ["session_id", "sequence"],
    )

    op.create_table(
        "storage_object_versions",
        sa.Column("object_version_id", sa.Uuid(), primary_key=True),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("security_class", sa.String(24), nullable=False),
        sa.Column("physical_key", sa.String(512), nullable=False),
        sa.Column("provider_name", sa.String(32), nullable=False),
        sa.Column("provider_version_id", sa.String(256), nullable=False),
        sa.Column("etag", sa.String(256), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id", "workspace_id"],
            ["storage_objects.object_id", "storage_objects.workspace_id"],
            name="fk_storage_object_versions_object",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "object_version_id",
            "workspace_id",
            name="uq_storage_object_versions_scope",
        ),
        sa.UniqueConstraint(
            "provider_name",
            "physical_key",
            "provider_version_id",
            name="uq_storage_object_versions_provider_identity",
        ),
        sa.CheckConstraint(
            "security_class IN ('quarantine', 'clean', 'rejected', 'retained')",
            name="ck_storage_object_versions_security_class",
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_storage_object_versions_byte_size"),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_storage_object_versions_sha256",
        ),
    )
    for column in ("object_id", "workspace_id", "document_version_id"):
        op.create_index(
            f"ix_storage_object_versions_{column}",
            "storage_object_versions",
            [column],
        )
    op.create_index(
        "ix_storage_object_versions_document",
        "storage_object_versions",
        ["workspace_id", "document_version_id", "created_at"],
    )

    op.create_table(
        "storage_object_lifecycle_transitions",
        sa.Column("transition_id", sa.Uuid(), primary_key=True),
        sa.Column("object_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(24), nullable=True),
        sa.Column("current_state", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("service_identity", sa.String(120), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_version_id", "workspace_id"],
            ["storage_object_versions.object_version_id", "storage_object_versions.workspace_id"],
            name="fk_storage_object_lifecycle_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "object_version_id",
            "sequence",
            name="uq_storage_object_lifecycle_sequence",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_storage_object_lifecycle_sequence"),
        sa.CheckConstraint(
            "current_state IN "
            "('quarantined', 'scan_pending', 'clean', 'rejected', 'retained', "
            "'deletion_requested', 'deleted', 'legacy_unscanned', 'canceled', 'error')",
            name="ck_storage_object_lifecycle_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('quarantined', 'scan_pending', 'clean', 'rejected', 'retained', "
            "'deletion_requested', 'deleted', 'legacy_unscanned', 'canceled', 'error')",
            name="ck_storage_object_lifecycle_previous_state",
        ),
    )
    for column in ("workspace_id", "actor_user_id", "trace_id"):
        op.create_index(
            f"ix_storage_object_lifecycle_transitions_{column}",
            "storage_object_lifecycle_transitions",
            [column],
        )
    op.create_index(
        "ix_storage_object_lifecycle_latest",
        "storage_object_lifecycle_transitions",
        ["object_version_id", "sequence"],
    )


def _create_scan_and_promotion_tables() -> None:
    op.create_table(
        "malware_scan_requests",
        sa.Column("scan_request_id", sa.Uuid(), primary_key=True),
        sa.Column("object_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scanner_identity", sa.String(120), nullable=False),
        sa.Column("scanner_version", sa.String(120), nullable=False),
        sa.Column("policy_version", sa.String(120), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_version_id", "workspace_id"],
            ["storage_object_versions.object_version_id", "storage_object_versions.workspace_id"],
            name="fk_malware_scan_requests_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "object_version_id",
            "policy_version",
            "request_digest",
            name="uq_malware_scan_requests_identity",
        ),
        sa.UniqueConstraint(
            "scan_request_id",
            "object_version_id",
            name="uq_malware_scan_requests_result_scope",
        ),
        sa.CheckConstraint("length(request_digest) = 64", name="ck_malware_scan_requests_digest"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_malware_scan_requests_timeout"),
    )
    for column in (
        "object_version_id",
        "workspace_id",
        "requested_by_user_id",
        "trace_id",
    ):
        op.create_index(
            f"ix_malware_scan_requests_{column}",
            "malware_scan_requests",
            [column],
        )
    op.create_index(
        "ix_malware_scan_requests_pending",
        "malware_scan_requests",
        ["workspace_id", "requested_at", "deadline_at"],
    )

    op.create_table(
        "malware_scan_results",
        sa.Column("scan_result_id", sa.Uuid(), primary_key=True),
        sa.Column("scan_request_id", sa.Uuid(), nullable=False),
        sa.Column("object_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("scanner_identity", sa.String(120), nullable=False),
        sa.Column("scanner_version", sa.String(120), nullable=False),
        sa.Column("engine_version", sa.String(120), nullable=False),
        sa.Column("signature_version", sa.String(120), nullable=False),
        sa.Column("policy_version", sa.String(120), nullable=False),
        sa.Column("provider_result_id", sa.String(256), nullable=False),
        sa.Column("provider_record_digest", sa.String(64), nullable=False),
        sa.Column("provider_version_id", sa.String(256), nullable=False),
        sa.Column("etag", sa.String(256), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=False),
        sa.Column("safe_reason_code", sa.String(64), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_request_id", "object_version_id"],
            ["malware_scan_requests.scan_request_id", "malware_scan_requests.object_version_id"],
            name="fk_malware_scan_results_request",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("scan_request_id", name="uq_malware_scan_results_request"),
        sa.UniqueConstraint(
            "scanner_identity",
            "provider_result_id",
            name="uq_malware_scan_results_provider",
        ),
        sa.CheckConstraint(
            "outcome IN ('clean', 'infected', 'suspicious', 'unsupported', 'error', 'timeout')",
            name="ck_malware_scan_results_outcome",
        ),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_malware_scan_results_sha256"),
        sa.CheckConstraint("length(result_digest) = 64", name="ck_malware_scan_results_digest"),
        sa.CheckConstraint(
            "length(provider_record_digest) = 64",
            name="ck_malware_scan_results_provider_digest",
        ),
    )
    for column in ("object_version_id", "workspace_id"):
        op.create_index(
            f"ix_malware_scan_results_{column}",
            "malware_scan_results",
            [column],
        )
    op.create_index(
        "ix_malware_scan_results_object",
        "malware_scan_results",
        ["workspace_id", "object_version_id", "scanned_at"],
    )

    op.create_table(
        "object_promotions",
        sa.Column("promotion_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scan_result_id",
            sa.Uuid(),
            sa.ForeignKey("malware_scan_results.scan_result_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_object_version_id", sa.Uuid(), nullable=False),
        sa.Column("target_object_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("target_sha256", sa.String(64), nullable=False),
        sa.Column("service_identity", sa.String(120), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_object_version_id", "workspace_id"],
            ["storage_object_versions.object_version_id", "storage_object_versions.workspace_id"],
            name="fk_object_promotions_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_object_version_id", "workspace_id"],
            ["storage_object_versions.object_version_id", "storage_object_versions.workspace_id"],
            name="fk_object_promotions_target",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("scan_result_id", name="uq_object_promotions_scan_result"),
        sa.UniqueConstraint(
            "source_object_version_id",
            "target_object_version_id",
            name="uq_object_promotions_pair",
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_object_promotions_source_sha256"),
        sa.CheckConstraint("length(target_sha256) = 64", name="ck_object_promotions_target_sha256"),
    )
    for column in (
        "source_object_version_id",
        "target_object_version_id",
        "workspace_id",
        "trace_id",
    ):
        op.create_index(
            f"ix_object_promotions_{column}",
            "object_promotions",
            [column],
        )

    op.create_table(
        "object_ingestion_audit_events",
        sa.Column("audit_event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "canvas_id",
            sa.Uuid(),
            sa.ForeignKey("canvases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("upload_session_id", sa.Uuid(), nullable=True),
        sa.Column("object_version_id", sa.Uuid(), nullable=True),
        sa.Column("scan_request_id", sa.Uuid(), nullable=True),
        sa.Column("scan_result_id", sa.Uuid(), nullable=True),
        sa.Column("promotion_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('allowed', 'denied', 'succeeded', 'failed')",
            name="ck_object_ingestion_audit_outcome",
        ),
    )
    for column in (
        "actor_user_id",
        "workspace_id",
        "canvas_id",
        "upload_session_id",
        "object_version_id",
        "scan_request_id",
        "scan_result_id",
        "promotion_id",
        "trace_id",
    ):
        op.create_index(
            f"ix_object_ingestion_audit_events_{column}",
            "object_ingestion_audit_events",
            [column],
        )
    op.create_index(
        "ix_object_ingestion_audit_scope",
        "object_ingestion_audit_events",
        ["workspace_id", "canvas_id", "recorded_at"],
    )

    op.create_table(
        "object_deletion_requests",
        sa.Column("deletion_request_id", sa.Uuid(), primary_key=True),
        sa.Column("object_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "requester_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_version_id", "workspace_id"],
            ["storage_object_versions.object_version_id", "storage_object_versions.workspace_id"],
            name="fk_object_deletion_requests_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "object_version_id",
            "idempotency_key",
            name="uq_object_deletion_requests_idempotency",
        ),
    )
    for column in (
        "object_version_id",
        "workspace_id",
        "requester_user_id",
        "trace_id",
    ):
        op.create_index(
            f"ix_object_deletion_requests_{column}",
            "object_deletion_requests",
            [column],
        )


def _backfill_legacy_objects() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                dv.id AS document_version_id,
                dv.document_id,
                d.canvas_id,
                c.workspace_id,
                w.owner_id AS creator_user_id,
                dv.storage_key,
                dv.file_size_bytes,
                dv.content_sha256,
                dv.media_type,
                dv.created_at
            FROM document_versions AS dv
            JOIN documents AS d ON d.id = dv.document_id
            JOIN canvases AS c ON c.id = d.canvas_id
            JOIN workspaces AS w ON w.id = c.workspace_id
            ORDER BY dv.document_id, dv.version
            """
        )
    ).mappings()
    seen_objects: set[uuid.UUID] = set()
    for row in rows:
        document_id = _uuid(row["document_id"])
        object_id = uuid.uuid5(uuid.NAMESPACE_URL, f"mobius:storage-object:{document_id}")
        object_version_id = uuid.uuid5(object_id, f"legacy:{_uuid(row['document_version_id'])}")
        workspace_id = _uuid(row["workspace_id"])
        created_at = row["created_at"] or datetime.now(UTC)
        if object_id not in seen_objects:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO storage_objects (
                        object_id, creator_user_id, workspace_id, canvas_id,
                        document_id, environment, classification, created_at
                    ) VALUES (
                        :object_id, :creator_user_id, :workspace_id, :canvas_id,
                        :document_id, 'legacy', 'private_source', :created_at
                    )
                    """
                ),
                {
                    "object_id": _db_uuid(object_id),
                    "creator_user_id": _db_uuid(_uuid(row["creator_user_id"])),
                    "workspace_id": _db_uuid(workspace_id),
                    "canvas_id": _db_uuid(_uuid(row["canvas_id"])),
                    "document_id": _db_uuid(document_id),
                    "created_at": created_at,
                },
            )
            seen_objects.add(object_id)
        bind.execute(
            sa.text(
                """
                INSERT INTO storage_object_versions (
                    object_version_id, object_id, workspace_id, document_version_id,
                    security_class, physical_key, provider_name, provider_version_id,
                    etag, byte_size, content_sha256, media_type, created_at
                ) VALUES (
                    :object_version_id, :object_id, :workspace_id, :document_version_id,
                    'quarantine', :physical_key, 'legacy', 'legacy', 'legacy',
                    :byte_size, :content_sha256, :media_type, :created_at
                )
                """
            ),
            {
                "object_version_id": _db_uuid(object_version_id),
                "object_id": _db_uuid(object_id),
                "workspace_id": _db_uuid(workspace_id),
                "document_version_id": _db_uuid(_uuid(row["document_version_id"])),
                "physical_key": row["storage_key"],
                "byte_size": row["file_size_bytes"],
                "content_sha256": row["content_sha256"],
                "media_type": row["media_type"],
                "created_at": created_at,
            },
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO storage_object_lifecycle_transitions (
                    transition_id, object_version_id, workspace_id, sequence,
                    previous_state, current_state, reason_code, actor_kind,
                    actor_user_id, service_identity, trace_id, recorded_at
                ) VALUES (
                    :transition_id, :object_version_id, :workspace_id, 0,
                    NULL, 'legacy_unscanned', 'migration_backfill', 'service',
                    NULL, 'migration-20260726-0027', :trace_id, :recorded_at
                )
                """
            ),
            {
                "transition_id": _db_uuid(uuid.uuid5(object_version_id, "legacy-transition")),
                "object_version_id": _db_uuid(object_version_id),
                "workspace_id": _db_uuid(workspace_id),
                "trace_id": _db_uuid(uuid.uuid5(object_version_id, "legacy-trace")),
                "recorded_at": created_at,
            },
        )


def _create_append_only_guards() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    for table in _IMMUTABLE_TABLES:
        for operation in ("UPDATE", "DELETE"):
            if sqlite:
                statement = (
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'object-ingestion evidence is append-only'); END"
                )
            else:
                statement = (
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} FOR EACH ROW "
                    "EXECUTE FUNCTION reject_controlled_agent_mutation()"
                )
            op.execute(sa.text(statement))


def _drop_append_only_guards() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    for table in _IMMUTABLE_TABLES:
        for operation in ("update", "delete"):
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"
                    if sqlite
                    else f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked ON {table}"
                )
            )


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _db_uuid(value: uuid.UUID) -> object:
    return value.hex if op.get_bind().dialect.name == "sqlite" else value


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)
