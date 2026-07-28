"""Add deterministic immutable Indexer revisions and publication.

Revision ID: 20260726_0026
Revises: 20260725_0025
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260726_0026"
down_revision: str | None = "20260725_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = (
    "pipeline_manifests",
    "ingestion_requests",
    "ingestion_request_transitions",
    "normalized_artifacts",
    "index_compatibility_projections",
    "index_revisions",
    "index_revision_chunks",
    "vector_materializations",
    "index_publications",
    "indexer_audit_events",
    "indexer_failures",
)
_INDEXER_EVENT_TYPES = (
    "ingestion.requested",
    "ingestion.queued",
    "ingestion.failed",
    "ingestion.canceled",
    "index.reindex.requested",
    "index.revision.created",
    "index.published",
    "index.superseded",
)
_INDEXER_SUBJECT_KINDS = (
    "ingestion_request",
    "index_revision",
    "index_publication",
)
_DOMAIN_EVENT_TYPES_0025 = (
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
)
_DOMAIN_EVENT_SUBJECT_KINDS_0025 = (
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
)


def upgrade() -> None:
    _replace_domain_event_checks(add=True)
    _create_manifest_and_request_tables()
    _create_artifact_and_revision_tables()
    _create_publication_and_evidence_tables()
    if not op.get_context().as_sql:
        _backfill_compatibility_projections()
    _create_append_only_guards()


def downgrade() -> None:
    _drop_append_only_guards()
    for table in (
        "retrieval_heads",
        "indexer_failures",
        "indexer_audit_events",
        "index_publications",
        "vector_materializations",
        "index_revision_chunks",
        "index_revisions",
        "index_compatibility_projections",
        "normalized_artifacts",
        "ingestion_request_transitions",
        "ingestion_requests",
        "pipeline_manifests",
    ):
        op.drop_table(table)
    _replace_domain_event_checks(add=False)


def _replace_domain_event_checks(*, add: bool) -> None:
    event_types = (
        _DOMAIN_EVENT_TYPES_0025 + _INDEXER_EVENT_TYPES if add else _DOMAIN_EVENT_TYPES_0025
    )
    subject_kinds = (
        _DOMAIN_EVENT_SUBJECT_KINDS_0025 + _INDEXER_SUBJECT_KINDS
        if add
        else _DOMAIN_EVENT_SUBJECT_KINDS_0025
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


def _create_manifest_and_request_tables() -> None:
    op.create_table(
        "pipeline_manifests",
        sa.Column("manifest_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("parser_name", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_build_digest", sa.String(64), nullable=False),
        sa.Column("normalizer_version", sa.String(64), nullable=False),
        sa.Column("metadata_version", sa.String(64), nullable=False),
        sa.Column("chunker_version", sa.String(64), nullable=False),
        sa.Column("embedding_provider", sa.String(32), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_configuration_version", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("indexer_version", sa.String(64), nullable=False),
        sa.Column("index_schema_version", sa.String(32), nullable=False),
        sa.Column("configuration_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("manifest_id", "workspace_id", name="uq_pipeline_manifest_scope"),
        sa.UniqueConstraint("workspace_id", "manifest_digest", name="uq_pipeline_manifest_digest"),
        sa.CheckConstraint("length(manifest_digest) = 64", name="ck_pipeline_manifest_digest"),
        sa.CheckConstraint("dimensions > 0", name="ck_pipeline_manifest_dimensions"),
    )
    op.create_index("ix_pipeline_manifests_workspace_id", "pipeline_manifests", ["workspace_id"])

    op.create_table(
        "ingestion_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "canvas_id",
            sa.Uuid(),
            sa.ForeignKey("canvases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("pipeline_manifest_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id", "user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_ingestion_request_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_manifest_id", "workspace_id"],
            ["pipeline_manifests.manifest_id", "pipeline_manifests.workspace_id"],
            name="fk_ingestion_request_manifest",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("request_id", "workspace_id", name="uq_ingestion_request_scope"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "idempotency_key",
            name="uq_ingestion_request_idempotency",
        ),
        sa.CheckConstraint("length(request_digest) = 64", name="ck_ingestion_request_digest"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_ingestion_request_source_digest"),
        sa.CheckConstraint(
            "operation IN ('index', 'reindex')",
            name="ck_ingestion_request_operation",
        ),
        sa.CheckConstraint("authority_generation >= 0", name="ck_ingestion_authority_generation"),
        sa.CheckConstraint("cancel_generation >= 0", name="ck_ingestion_cancel_generation"),
    )
    op.create_index("ix_ingestion_requests_user_id", "ingestion_requests", ["user_id"])
    op.create_index("ix_ingestion_requests_workspace_id", "ingestion_requests", ["workspace_id"])
    op.create_index("ix_ingestion_requests_canvas_id", "ingestion_requests", ["canvas_id"])
    op.create_index("ix_ingestion_requests_document_id", "ingestion_requests", ["document_id"])
    op.create_index("ix_ingestion_requests_trace_id", "ingestion_requests", ["trace_id"])
    op.create_index(
        "ix_ingestion_request_document",
        "ingestion_requests",
        ["workspace_id", "canvas_id", "document_id", "document_version", "created_at"],
    )

    op.create_table(
        "ingestion_request_transitions",
        sa.Column("transition_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(24), nullable=True),
        sa.Column("current_state", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_ingestion_transition_request",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "request_id", "sequence", name="uq_ingestion_request_transition_sequence"
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_ingestion_transition_sequence"),
        sa.CheckConstraint(
            "current_state IN "
            "('requested', 'queued', 'parsing', 'normalizing', 'chunking', 'indexing', "
            "'completed', 'published', 'failed', 'canceled', 'superseded')",
            name="ck_ingestion_transition_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('requested', 'queued', 'parsing', 'normalizing', 'chunking', 'indexing', "
            "'completed', 'published', 'failed', 'canceled', 'superseded')",
            name="ck_ingestion_transition_previous_state",
        ),
    )
    op.create_index(
        "ix_ingestion_request_transitions_request_id",
        "ingestion_request_transitions",
        ["request_id"],
    )
    op.create_index(
        "ix_ingestion_request_transitions_workspace_id",
        "ingestion_request_transitions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_ingestion_request_transitions_trace_id",
        "ingestion_request_transitions",
        ["trace_id"],
    )


def _create_artifact_and_revision_tables() -> None:
    op.create_table(
        "normalized_artifacts",
        sa.Column("artifact_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "pipeline_manifest_id",
            sa.Uuid(),
            sa.ForeignKey("pipeline_manifests.manifest_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("normalized_digest", sa.String(64), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("metadata_digest", sa.String(64), nullable=False),
        sa.Column("near_duplicate_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_normalized_artifact_request",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("request_id", name="uq_normalized_artifact_request"),
        sa.CheckConstraint("length(normalized_digest) = 64", name="ck_normalized_artifact_digest"),
        sa.CheckConstraint("length(metadata_digest) = 64", name="ck_normalized_metadata_digest"),
        sa.CheckConstraint(
            "length(near_duplicate_fingerprint) = 64",
            name="ck_normalized_near_duplicate_digest",
        ),
    )
    op.create_index(
        "ix_normalized_artifacts_workspace_id", "normalized_artifacts", ["workspace_id"]
    )
    op.create_index(
        "ix_normalized_artifact_scoped_digest",
        "normalized_artifacts",
        ["workspace_id", "normalized_digest", "pipeline_manifest_id"],
    )

    op.create_table(
        "index_compatibility_projections",
        sa.Column("projection_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("provenance_state", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "projection_id",
            "workspace_id",
            name="uq_index_compatibility_projection_scope",
        ),
        sa.UniqueConstraint(
            "document_id",
            "document_version",
            name="uq_index_compatibility_document_version",
        ),
        sa.CheckConstraint(
            "provenance_state = 'unverified_legacy'",
            name="ck_index_compatibility_provenance_state",
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64",
            name="ck_index_compatibility_source_digest",
        ),
        sa.CheckConstraint("chunk_count >= 0", name="ck_index_compatibility_chunk_count"),
    )
    op.create_index(
        "ix_index_compatibility_projections_workspace_id",
        "index_compatibility_projections",
        ["workspace_id"],
    )
    op.create_index(
        "ix_index_compatibility_projections_document_id",
        "index_compatibility_projections",
        ["document_id"],
    )

    op.create_table(
        "index_revisions",
        sa.Column("revision_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "canvas_id",
            sa.Uuid(),
            sa.ForeignKey("canvases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column(
            "pipeline_manifest_id",
            sa.Uuid(),
            sa.ForeignKey("pipeline_manifests.manifest_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("deduplication_kind", sa.String(24), nullable=False),
        sa.Column(
            "deduplicated_from_revision_id",
            sa.Uuid(),
            sa.ForeignKey("index_revisions.revision_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_digest", sa.String(64), nullable=False),
        sa.Column("metadata_digest", sa.String(64), nullable=False),
        sa.Column("chunk_manifest_digest", sa.String(64), nullable=False),
        sa.Column("vector_manifest_digest", sa.String(64), nullable=False),
        sa.Column("output_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_index_revision_request",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("revision_id", "workspace_id", name="uq_index_revision_scope"),
        sa.UniqueConstraint("request_id", name="uq_index_revision_request"),
        sa.CheckConstraint("revision_kind = 'native'", name="ck_index_revision_kind"),
        sa.CheckConstraint("status = 'completed'", name="ck_index_revision_status"),
        sa.CheckConstraint(
            "deduplication_kind IN ('none', 'exact_bytes', 'normalized_content')",
            name="ck_index_revision_deduplication_kind",
        ),
        sa.CheckConstraint(
            "(deduplication_kind = 'none' AND deduplicated_from_revision_id IS NULL) "
            "OR (deduplication_kind IN ('exact_bytes', 'normalized_content') "
            "AND deduplicated_from_revision_id IS NOT NULL)",
            name="ck_index_revision_deduplication_source",
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_index_revision_source_digest"),
        sa.CheckConstraint(
            "length(normalized_digest) = 64",
            name="ck_index_revision_normalized_digest",
        ),
        sa.CheckConstraint(
            "length(metadata_digest) = 64", name="ck_index_revision_metadata_digest"
        ),
        sa.CheckConstraint(
            "length(chunk_manifest_digest) = 64",
            name="ck_index_revision_chunk_digest",
        ),
        sa.CheckConstraint(
            "length(vector_manifest_digest) = 64",
            name="ck_index_revision_vector_digest",
        ),
        sa.CheckConstraint("length(output_digest) = 64", name="ck_index_revision_output_digest"),
    )
    op.create_index("ix_index_revisions_workspace_id", "index_revisions", ["workspace_id"])
    op.create_index("ix_index_revisions_trace_id", "index_revisions", ["trace_id"])
    op.create_index(
        "ix_index_revision_document",
        "index_revisions",
        ["workspace_id", "document_id", "document_version", "created_at"],
    )

    op.create_table(
        "index_revision_chunks",
        sa.Column("chunk_id", sa.Uuid(), primary_key=True),
        sa.Column("stable_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("heading", sa.String(500), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_index_chunk_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("chunk_id", "revision_id", name="uq_index_chunk_revision"),
        sa.UniqueConstraint("revision_id", "chunk_index", name="uq_index_chunk_order"),
        sa.UniqueConstraint(
            "revision_id",
            "stable_chunk_id",
            name="uq_index_chunk_stable_identity",
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_index_chunk_index"),
        sa.CheckConstraint("char_start >= 0", name="ck_index_chunk_start"),
        sa.CheckConstraint("char_end > char_start", name="ck_index_chunk_range"),
        sa.CheckConstraint("length(content_digest) = 64", name="ck_index_chunk_content_digest"),
    )
    op.create_index(
        "ix_index_revision_chunks_revision_id",
        "index_revision_chunks",
        ["revision_id"],
    )
    op.create_index(
        "ix_index_revision_chunks_stable_chunk_id",
        "index_revision_chunks",
        ["stable_chunk_id"],
    )
    op.create_index(
        "ix_index_revision_chunks_workspace_id",
        "index_revision_chunks",
        ["workspace_id"],
    )

    op.create_table(
        "vector_materializations",
        sa.Column("materialization_id", sa.Uuid(), primary_key=True),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reused_from_materialization_id",
            sa.Uuid(),
            sa.ForeignKey(
                "vector_materializations.materialization_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column(
            "embedding",
            Vector(1536).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_vector_materialization_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id", "revision_id"],
            ["index_revision_chunks.chunk_id", "index_revision_chunks.revision_id"],
            name="fk_vector_materialization_chunk",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("revision_id", "chunk_id", name="uq_vector_materialization_chunk"),
        sa.CheckConstraint("dimensions = 1536", name="ck_vector_materialization_dimensions"),
        sa.CheckConstraint(
            "length(artifact_digest) = 64",
            name="ck_vector_materialization_digest",
        ),
    )
    op.create_index(
        "ix_vector_materializations_revision_id",
        "vector_materializations",
        ["revision_id"],
    )
    op.create_index(
        "ix_vector_materializations_workspace_id",
        "vector_materializations",
        ["workspace_id"],
    )


def _create_publication_and_evidence_tables() -> None:
    op.create_table(
        "index_publications",
        sa.Column("publication_id", sa.Uuid(), primary_key=True),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("cancel_generation", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_index_publication_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "actor_user_id", "workspace_id"],
            [
                "workspace_memberships.membership_id",
                "workspace_memberships.user_id",
                "workspace_memberships.workspace_id",
            ],
            name="fk_index_publication_membership",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("publication_id", "workspace_id", name="uq_index_publication_scope"),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "generation",
            name="uq_index_publication_generation",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "revision_id",
            name="uq_index_publication_revision",
        ),
        sa.CheckConstraint("generation > 0", name="ck_index_publication_generation"),
        sa.CheckConstraint("authority_generation >= 0", name="ck_index_publication_authority"),
        sa.CheckConstraint("cancel_generation >= 0", name="ck_index_publication_cancel"),
    )
    op.create_index("ix_index_publications_workspace_id", "index_publications", ["workspace_id"])
    op.create_index("ix_index_publications_document_id", "index_publications", ["document_id"])
    op.create_index("ix_index_publications_trace_id", "index_publications", ["trace_id"])

    op.create_table(
        "retrieval_heads",
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("activation_kind", sa.String(24), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("publication_id", sa.Uuid(), nullable=True, unique=True),
        sa.Column("compatibility_projection_id", sa.Uuid(), nullable=True, unique=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "workspace_id"],
            ["index_revisions.revision_id", "index_revisions.workspace_id"],
            name="fk_retrieval_head_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["index_publications.publication_id", "index_publications.workspace_id"],
            name="fk_retrieval_head_publication",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["compatibility_projection_id", "workspace_id"],
            [
                "index_compatibility_projections.projection_id",
                "index_compatibility_projections.workspace_id",
            ],
            name="fk_retrieval_head_compatibility",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("generation > 0", name="ck_retrieval_head_generation"),
        sa.CheckConstraint(
            "(activation_kind = 'native' AND revision_id IS NOT NULL "
            "AND publication_id IS NOT NULL AND compatibility_projection_id IS NULL) "
            "OR (activation_kind = 'compatibility' AND revision_id IS NULL "
            "AND publication_id IS NULL AND compatibility_projection_id IS NOT NULL)",
            name="ck_retrieval_head_activation",
        ),
    )
    op.create_index("ix_retrieval_heads_workspace_id", "retrieval_heads", ["workspace_id"])

    op.create_table(
        "indexer_audit_events",
        sa.Column("audit_event_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("authority_generation", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_indexer_audit_request",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "outcome IN ('allowed', 'denied', 'succeeded', 'failed')",
            name="ck_indexer_audit_outcome",
        ),
    )
    op.create_index("ix_indexer_audit_events_request_id", "indexer_audit_events", ["request_id"])
    op.create_index(
        "ix_indexer_audit_events_workspace_id",
        "indexer_audit_events",
        ["workspace_id"],
    )
    op.create_index("ix_indexer_audit_events_trace_id", "indexer_audit_events", ["trace_id"])

    op.create_table(
        "indexer_failures",
        sa.Column("failure_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("safe_failure_code", sa.String(64), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id", "workspace_id"],
            ["ingestion_requests.request_id", "ingestion_requests.workspace_id"],
            name="fk_indexer_failure_request",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_indexer_failures_request_id", "indexer_failures", ["request_id"])
    op.create_index("ix_indexer_failures_workspace_id", "indexer_failures", ["workspace_id"])
    op.create_index("ix_indexer_failures_trace_id", "indexer_failures", ["trace_id"])


def _backfill_compatibility_projections() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT d.id, d.canvas_id, c.workspace_id, d.current_version, "
            "d.content_sha256, d.chunk_count, d.updated_at, v.id AS version_id "
            "FROM documents d JOIN canvases c ON c.id = d.canvas_id "
            "JOIN document_versions v ON v.document_id = d.id "
            "AND v.version = d.current_version "
            "WHERE d.status = 'ready' AND d.deleted_at IS NULL "
            "ORDER BY d.id"
        )
    ).mappings()
    for row in rows:
        document_id = _uuid(row["id"])
        projection_id = uuid.uuid5(
            document_id,
            f"milestone-7.2:compatibility:{int(row['current_version'])}",
        )
        values = {
            "projection_id": _db_uuid(projection_id),
            "workspace_id": _db_uuid(_uuid(row["workspace_id"])),
            "canvas_id": _db_uuid(_uuid(row["canvas_id"])),
            "document_id": _db_uuid(document_id),
            "version_id": _db_uuid(_uuid(row["version_id"])),
            "document_version": int(row["current_version"]),
            "source_sha256": str(row["content_sha256"]),
            "chunk_count": int(row["chunk_count"]),
            "created_at": row["updated_at"],
        }
        bind.execute(
            sa.text(
                "INSERT INTO index_compatibility_projections "
                "(projection_id, workspace_id, canvas_id, document_id, "
                "document_version_id, document_version, source_sha256, chunk_count, "
                "provenance_state, created_at) VALUES "
                "(:projection_id, :workspace_id, :canvas_id, :document_id, "
                ":version_id, :document_version, :source_sha256, :chunk_count, "
                "'unverified_legacy', :created_at)"
            ),
            values,
        )
        bind.execute(
            sa.text(
                "INSERT INTO retrieval_heads "
                "(document_id, workspace_id, canvas_id, activation_kind, revision_id, "
                "publication_id, compatibility_projection_id, generation, created_at, "
                "updated_at) VALUES "
                "(:document_id, :workspace_id, :canvas_id, 'compatibility', NULL, NULL, "
                ":projection_id, 1, :created_at, :created_at)"
            ),
            values,
        )


def _create_append_only_guards() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for table in _IMMUTABLE_TABLES:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    sa.text(
                        f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                        f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                        "'indexer evidence is append-only'); END"
                    )
                )
        return
    for table in _IMMUTABLE_TABLES:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} FOR EACH ROW "
                    "EXECUTE FUNCTION reject_controlled_agent_mutation()"
                )
            )


def _drop_append_only_guards() -> None:
    for table in _IMMUTABLE_TABLES:
        for operation in ("update", "delete"):
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked ON {table}"
                    if op.get_bind().dialect.name != "sqlite"
                    else f"DROP TRIGGER IF EXISTS trg_{table}_{operation}_blocked"
                )
            )


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _db_uuid(value: uuid.UUID) -> object:
    return value.hex if op.get_bind().dialect.name == "sqlite" else value


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)
