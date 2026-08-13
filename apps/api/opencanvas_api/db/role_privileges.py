from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Literal

from opencanvas_api.core.config import DatabaseRole

TableOperation = Literal["SELECT", "INSERT", "UPDATE", "DELETE"]

# This inventory is intentionally literal. A migration that adds a table must make a
# reviewed decision here; metadata discovery or default grants must never widen a
# runtime role automatically. application_errors and index_compatibility_projections
# are migration-only tables and are deliberately absent.
API_SELECT_TABLES: Final = frozenset(
    {
        "ai_claims",
        "ai_execution_chunks",
        "ai_execution_citations",
        "ai_execution_nodes",
        "ai_execution_sources",
        "ai_requests",
        "ai_response_sources",
        "ai_responses",
        "bounded_agent_activation_decisions",
        "bounded_agent_activation_requests",
        "bounded_agent_capability_requirements",
        "bounded_agent_evaluations",
        "bounded_agent_identities",
        "bounded_agent_invocations",
        "bounded_agent_lifecycle_states",
        "bounded_agent_proposal_decisions",
        "bounded_agent_proposals",
        "bounded_agent_validation_reports",
        "bounded_agent_version_states",
        "bounded_agent_versions",
        "bounded_agent_workflow_bindings",
        "bounded_communication_profile_versions",
        "bounded_communication_profiles",
        "bounded_communication_revision_decisions",
        "bounded_communication_revisions",
        "canonical_canvas_object_bindings",
        "canonical_chunks",
        "canonical_documents",
        "canonical_executions",
        "canonical_graph_entities",
        "canonical_graph_relationships",
        "canonical_notes",
        "canonical_objects",
        "canonical_relationship_history",
        "canonical_relationship_provenance",
        "canonical_relationships",
        "canvas_document_nodes",
        "canvases",
        "citations",
        "collaboration_approval_authority_assignments",
        "collaboration_approval_authority_transitions",
        "collaboration_audit_events",
        "collaboration_authority_snapshots",
        "collaboration_comment_revisions",
        "collaboration_comment_thread_transitions",
        "collaboration_comment_threads",
        "collaboration_comment_transitions",
        "collaboration_comments",
        "collaboration_ownership_transfer_transitions",
        "collaboration_ownership_transfers",
        "collaboration_request_identities",
        "collaboration_resource_ownership_transitions",
        "collaboration_resource_share_transitions",
        "collaboration_resource_shares",
        "collaboration_resources",
        "collaboration_reviewer_eligibility_evidence",
        "collaboration_revocation_fences",
        "controlled_agent_approval_consumptions",
        "controlled_agent_approvals",
        "controlled_agent_audit_events",
        "controlled_agent_capability_grants",
        "controlled_agent_context_snapshots",
        "controlled_agent_execution_states",
        "controlled_agent_executions",
        "controlled_agent_grant_revocations",
        "controlled_agent_plan_snapshots",
        "controlled_agent_policy_decisions",
        "controlled_agent_request_identities",
        "controlled_agent_reversible_write_effects",
        "controlled_agent_reversible_write_proposals",
        "controlled_agent_reversible_write_rollback_approvals",
        "controlled_agent_reversible_write_rollback_evidence",
        "controlled_agent_reversible_write_rollback_results",
        "controlled_agent_state_transitions",
        "controlled_workflow_definitions",
        "controlled_workflow_dependencies",
        "controlled_workflow_evidence_links",
        "controlled_workflow_execution_transitions",
        "controlled_workflow_executions",
        "controlled_workflow_plan_snapshots",
        "controlled_workflow_step_attempts",
        "controlled_workflow_step_executions",
        "controlled_workflow_step_transitions",
        "controlled_workflow_steps",
        "controlled_workflow_version_states",
        "controlled_workflow_versions",
        "data_export_requests",
        "document_chunks",
        "document_embeddings",
        "document_files",
        "document_processing_jobs",
        "document_versions",
        "documents",
        "domain_activity_entries",
        "domain_event_delivery_attempts",
        "domain_event_outbox",
        "domain_event_provenance",
        "domain_events",
        "durable_job_attempts",
        "durable_job_audit_events",
        "durable_job_dead_letters",
        "durable_job_outcomes",
        "durable_job_replay_requests",
        "durable_job_requests",
        "durable_queue_deliveries",
        "durable_retry_decisions",
        "edges",
        "graph_retrieval_citations",
        "graph_retrieval_decisions",
        "graph_retrieval_runs",
        "index_publications",
        "index_revision_chunks",
        "index_revisions",
        "indexer_audit_events",
        "indexer_failures",
        "ingestion_request_transitions",
        "ingestion_requests",
        "legacy_creation_request_identities",
        "malware_scan_requests",
        "malware_scan_results",
        "nodes",
        "normalized_artifacts",
        "object_deletion_requests",
        "object_ingestion_audit_events",
        "object_promotions",
        "password_reset_tokens",
        "pipeline_manifests",
        "retrieval_heads",
        "storage_object_lifecycle_transitions",
        "storage_object_versions",
        "storage_objects",
        "trace_events",
        "trace_evidence_bundles",
        "upload_session_transitions",
        "upload_sessions",
        "usage_records",
        "user_sessions",
        "users",
        "vector_materializations",
        "worker_heartbeats",
        "workspace_authority_versions",
        "workspace_event_sequences",
        "workspace_graph_states",
        "workspace_invitation_delivery_attempts",
        "workspace_invitation_secret_versions",
        "workspace_invitation_transitions",
        "workspace_invitations",
        "workspace_membership_transitions",
        "workspace_memberships",
        "workspaces",
    }
)

API_INSERT_TABLES: Final = API_SELECT_TABLES - {"worker_heartbeats"}
API_UPDATE_TABLES: Final = frozenset(
    {
        "ai_requests",
        "ai_responses",
        "canonical_objects",
        "canvases",
        "controlled_agent_executions",
        "controlled_workflow_executions",
        "controlled_workflow_step_executions",
        "document_processing_jobs",
        "document_versions",
        "documents",
        "domain_event_outbox",
        "nodes",
        "users",
        "user_sessions",
        "workspace_authority_versions",
        "workspace_event_sequences",
        "workspaces",
    }
)
API_DELETE_TABLES: Final = frozenset(
    {
        "ai_response_sources",
        "canonical_objects",
        "canonical_relationships",
        "canvases",
        "citations",
        "document_chunks",
        "documents",
        "edges",
        "nodes",
    }
)

WORKER_SELECT_TABLES: Final = frozenset(
    {
        "bounded_agent_invocations",
        "canonical_graph_relationships",
        "canvas_document_nodes",
        "canvases",
        "collaboration_comment_threads",
        "collaboration_comments",
        "collaboration_ownership_transfers",
        "collaboration_resource_shares",
        "collaboration_resources",
        "controlled_agent_executions",
        "controlled_workflow_executions",
        "controlled_workflow_step_executions",
        "document_chunks",
        "document_embeddings",
        "document_files",
        "document_processing_jobs",
        "document_versions",
        "documents",
        "domain_activity_entries",
        "domain_event_delivery_attempts",
        "domain_event_outbox",
        "domain_event_provenance",
        "domain_events",
        "durable_job_attempts",
        "durable_job_audit_events",
        "durable_job_dead_letters",
        "durable_job_outcomes",
        "durable_job_replay_requests",
        "durable_job_requests",
        "durable_queue_deliveries",
        "durable_retry_decisions",
        "index_publications",
        "index_revisions",
        "ingestion_requests",
        "malware_scan_requests",
        "malware_scan_results",
        "nodes",
        "object_deletion_requests",
        "object_ingestion_audit_events",
        "object_promotions",
        "retrieval_heads",
        "storage_object_lifecycle_transitions",
        "storage_object_versions",
        "storage_objects",
        "trace_events",
        "upload_session_transitions",
        "upload_sessions",
        "worker_heartbeats",
        "workspace_authority_versions",
        "workspace_event_sequences",
        "workspace_invitation_transitions",
        "workspace_invitations",
        "workspace_membership_transitions",
        "workspace_memberships",
        "workspaces",
    }
)
WORKER_INSERT_TABLES: Final = frozenset(
    {
        "document_chunks",
        "document_embeddings",
        "domain_event_outbox",
        "domain_event_provenance",
        "domain_events",
        "durable_job_attempts",
        "durable_job_audit_events",
        "durable_job_dead_letters",
        "durable_job_outcomes",
        "durable_queue_deliveries",
        "durable_retry_decisions",
        "malware_scan_results",
        "object_ingestion_audit_events",
        "object_promotions",
        "storage_object_lifecycle_transitions",
        "trace_events",
        "worker_heartbeats",
        "workspace_event_sequences",
    }
)
WORKER_UPDATE_TABLES: Final = frozenset(
    {
        "document_processing_jobs",
        "document_versions",
        "documents",
        "domain_event_outbox",
        "worker_heartbeats",
        "workspace_event_sequences",
    }
)
WORKER_DELETE_TABLES: Final = frozenset({"document_chunks"})

RUNTIME_TABLE_PRIVILEGES: Final[Mapping[DatabaseRole, Mapping[TableOperation, frozenset[str]]]] = {
    DatabaseRole.API: {
        "SELECT": API_SELECT_TABLES,
        "INSERT": API_INSERT_TABLES,
        "UPDATE": API_UPDATE_TABLES,
        "DELETE": API_DELETE_TABLES,
    },
    DatabaseRole.WORKER: {
        "SELECT": WORKER_SELECT_TABLES,
        "INSERT": WORKER_INSERT_TABLES,
        "UPDATE": WORKER_UPDATE_TABLES,
        "DELETE": WORKER_DELETE_TABLES,
    },
}

RUNTIME_SEQUENCE_PRIVILEGES: Final[Mapping[DatabaseRole, frozenset[str]]] = {
    DatabaseRole.API: frozenset(),
    DatabaseRole.WORKER: frozenset(),
}
RUNTIME_FUNCTION_PRIVILEGES: Final[Mapping[DatabaseRole, frozenset[str]]] = {
    DatabaseRole.API: frozenset(),
    DatabaseRole.WORKER: frozenset(),
}


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_grant(operation: TableOperation, tables: Sequence[str], principal: str) -> str:
    qualified = ", ".join(f"public.{quote_identifier(table)}" for table in tables)
    return f"GRANT {operation} ON TABLE {qualified} TO {quote_identifier(principal)}"


def runtime_privilege_statements(
    *, api_principal: str, worker_principal: str, migration_principal: str
) -> tuple[str, ...]:
    principals = {
        DatabaseRole.API: api_principal,
        DatabaseRole.WORKER: worker_principal,
    }
    quoted_migration = quote_identifier(migration_principal)
    statements: list[str] = [
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC",
    ]
    for role, principal in principals.items():
        quoted = quote_identifier(principal)
        statements.extend(
            (
                f"REVOKE ALL PRIVILEGES ON DATABASE opencanvas FROM {quoted}",
                f"GRANT CONNECT ON DATABASE opencanvas TO {quoted}",
                f"REVOKE CREATE ON SCHEMA public FROM {quoted}",
                f"GRANT USAGE ON SCHEMA public TO {quoted}",
                f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {quoted}",
                f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {quoted}",
                f"REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM {quoted}",
                f"REVOKE {quoted_migration} FROM {quoted}",
            )
        )
        for object_kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            statements.append(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_migration} IN SCHEMA public "
                f"REVOKE ALL PRIVILEGES ON {object_kind} FROM {quoted}"
            )
        for operation in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            tables = sorted(RUNTIME_TABLE_PRIVILEGES[role][operation])
            if tables:
                statements.append(_table_grant(operation, tables, principal))
    for object_kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
        statements.append(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_migration} IN SCHEMA public "
            f"REVOKE ALL PRIVILEGES ON {object_kind} FROM PUBLIC"
        )
    return tuple(statements)


__all__ = [
    "API_DELETE_TABLES",
    "API_INSERT_TABLES",
    "API_SELECT_TABLES",
    "API_UPDATE_TABLES",
    "RUNTIME_FUNCTION_PRIVILEGES",
    "RUNTIME_SEQUENCE_PRIVILEGES",
    "RUNTIME_TABLE_PRIVILEGES",
    "WORKER_DELETE_TABLES",
    "WORKER_INSERT_TABLES",
    "WORKER_SELECT_TABLES",
    "WORKER_UPDATE_TABLES",
    "quote_identifier",
    "runtime_privilege_statements",
]
