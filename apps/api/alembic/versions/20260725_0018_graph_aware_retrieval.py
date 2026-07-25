"""Add graph-aware retrieval, citation, and evidence-bundle persistence.

Revision ID: 20260725_0018
Revises: 20260725_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260725_0018"
down_revision: str | None = "20260725_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "graph_retrieval_runs",
    "graph_retrieval_decisions",
    "graph_retrieval_citations",
    "trace_evidence_bundles",
)

REASONS = (
    "'selected_seed', 'direct_citation', 'supporting_relationship', "
    "'reference_relationship', 'derivation_relationship', "
    "'graph_related_candidate', 'exact_source_passage_match', "
    "'approved_deterministic_fallback', 'outside_selected_context', "
    "'unauthorized_scope', 'inactive_relationship', 'superseded_relationship', "
    "'invalid_relationship_direction', 'unsupported_relationship_kind', "
    "'historical_resource', 'removed_resource', 'missing_immutable_version', "
    "'missing_source_content', 'malformed_locator', 'duplicate_candidate', "
    "'candidate_limit_reached', 'traversal_limit_reached', "
    "'insufficient_relevance', 'unsupported_schema_version', "
    "'conflicting_provenance', 'unsafe_source', 'export_not_authorized'"
)


def _protect(table: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()}_blocked "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, "
                    "'retrieval evidence is append-only'); END"
                )
            )
        return
    function = f"reject_{table}_mutation"
    op.execute(
        sa.text(
            f"CREATE FUNCTION {function}() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'retrieval evidence is append-only'; END; "
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
    op.create_table(
        "graph_retrieval_runs",
        sa.Column("retrieval_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_digest", sa.String(64), nullable=False),
        sa.Column("selected_object_ids", sa.JSON(), nullable=False),
        sa.Column("seed_object_ids", sa.JSON(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("bounded", sa.Boolean(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "algorithm_version = 'graph-retrieval-v1'",
            name="ck_graph_retrieval_runs_algorithm",
        ),
        sa.CheckConstraint(
            "schema_version = 'graph-retrieval-result-v1'",
            name="ck_graph_retrieval_runs_schema",
        ),
        sa.CheckConstraint("mode IN ('selected_graph')", name="ck_graph_retrieval_runs_mode"),
        sa.CheckConstraint(
            "outcome IN ('supported', 'conflicting_evidence', "
            "'insufficient_evidence', 'bounded_result')",
            name="ck_graph_retrieval_runs_outcome",
        ),
        sa.CheckConstraint(
            "graph_revision >= 0 AND citation_count >= 0",
            name="ck_graph_retrieval_runs_counts",
        ),
        sa.CheckConstraint(
            "length(query_digest) = 64 AND length(request_digest) = 64",
            name="ck_graph_retrieval_runs_digests",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id", "workspace_id"],
            ["canvases.id", "canvases.workspace_id"],
            name="fk_graph_retrieval_runs_canvas_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("retrieval_id"),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "canvas_id",
            "idempotency_key",
            name="uq_graph_retrieval_runs_idempotency",
        ),
        sa.UniqueConstraint(
            "retrieval_id",
            "user_id",
            "workspace_id",
            name="uq_graph_retrieval_runs_scope",
        ),
    )
    op.create_index(
        "ix_graph_retrieval_runs_scope_time",
        "graph_retrieval_runs",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    op.create_index(
        "ix_graph_retrieval_runs_trace",
        "graph_retrieval_runs",
        ["trace_id"],
    )

    op.create_table(
        "graph_retrieval_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_id", sa.Uuid(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(48), nullable=False),
        sa.Column("distance", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("relationship_path", sa.JSON(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("distance >= 0", name="ck_graph_retrieval_decisions_distance"),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_graph_retrieval_decisions_rank"),
        sa.CheckConstraint(
            f"reason_code IN ({REASONS})",
            name="ck_graph_retrieval_decisions_reason",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_id", "user_id", "workspace_id"],
            [
                "graph_retrieval_runs.retrieval_id",
                "graph_retrieval_runs.user_id",
                "graph_retrieval_runs.workspace_id",
            ],
            name="fk_graph_retrieval_decisions_run_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_graph_retrieval_decisions_run_order",
        "graph_retrieval_decisions",
        ["retrieval_id", "included", "rank", "decision_id"],
    )

    op.create_table(
        "graph_retrieval_citations",
        sa.Column("citation_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_object_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_version", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_title", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("passage_identity", sa.String(96), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("excerpt_sha256", sa.String(64), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("relationship_path", sa.JSON(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("citation_schema_version", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_graph_retrieval_citations_ordinal"),
        sa.CheckConstraint(
            "canonical_version > 0 AND source_version > 0",
            name="ck_graph_retrieval_citations_versions",
        ),
        sa.CheckConstraint(
            "citation_schema_version = 'graph-citation-v1'",
            name="ck_graph_retrieval_citations_schema",
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(excerpt_sha256) = 64",
            name="ck_graph_retrieval_citations_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_id", "user_id", "workspace_id"],
            [
                "graph_retrieval_runs.retrieval_id",
                "graph_retrieval_runs.user_id",
                "graph_retrieval_runs.workspace_id",
            ],
            name="fk_graph_retrieval_citations_run_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("citation_id"),
        sa.UniqueConstraint(
            "retrieval_id",
            "ordinal",
            name="uq_graph_retrieval_citations_ordinal",
        ),
        sa.UniqueConstraint(
            "retrieval_id",
            "canonical_object_id",
            "passage_identity",
            name="uq_graph_retrieval_citations_passage",
        ),
    )
    op.create_index(
        "ix_graph_retrieval_citations_run_order",
        "graph_retrieval_citations",
        ["retrieval_id", "ordinal"],
    )
    op.create_index(
        "ix_graph_retrieval_citations_trace",
        "graph_retrieval_citations",
        ["trace_id"],
    )

    op.create_table(
        "trace_evidence_bundles",
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("artifact_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "schema_version = 'trace-evidence-bundle-v1'",
            name="ck_trace_evidence_bundles_schema",
        ),
        sa.CheckConstraint(
            "state IN ('completed', 'failed')",
            name="ck_trace_evidence_bundles_state",
        ),
        sa.CheckConstraint(
            "(state = 'completed' AND artifact_bytes IS NOT NULL "
            "AND artifact_sha256 IS NOT NULL AND byte_size > 0) OR "
            "(state = 'failed' AND artifact_bytes IS NULL "
            "AND artifact_sha256 IS NULL AND byte_size = 0)",
            name="ck_trace_evidence_bundles_artifact_shape",
        ),
        sa.CheckConstraint(
            "artifact_sha256 IS NULL OR length(artifact_sha256) = 64",
            name="ck_trace_evidence_bundles_hash",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_id", "user_id", "workspace_id"],
            [
                "graph_retrieval_runs.retrieval_id",
                "graph_retrieval_runs.user_id",
                "graph_retrieval_runs.workspace_id",
            ],
            name="fk_trace_evidence_bundles_run_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("bundle_id"),
        sa.UniqueConstraint(
            "retrieval_id",
            name="uq_trace_evidence_bundles_retrieval",
        ),
    )
    op.create_index(
        "ix_trace_evidence_bundles_scope",
        "trace_evidence_bundles",
        ["user_id", "workspace_id", "canvas_id", "created_at"],
    )
    for table in IMMUTABLE_TABLES:
        _protect(table)


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        _unprotect(table)
    op.drop_index("ix_trace_evidence_bundles_scope", table_name="trace_evidence_bundles")
    op.drop_table("trace_evidence_bundles")
    op.drop_index(
        "ix_graph_retrieval_citations_trace",
        table_name="graph_retrieval_citations",
    )
    op.drop_index(
        "ix_graph_retrieval_citations_run_order",
        table_name="graph_retrieval_citations",
    )
    op.drop_table("graph_retrieval_citations")
    op.drop_index(
        "ix_graph_retrieval_decisions_run_order",
        table_name="graph_retrieval_decisions",
    )
    op.drop_table("graph_retrieval_decisions")
    op.drop_index("ix_graph_retrieval_runs_trace", table_name="graph_retrieval_runs")
    op.drop_index(
        "ix_graph_retrieval_runs_scope_time",
        table_name="graph_retrieval_runs",
    )
    op.drop_table("graph_retrieval_runs")
