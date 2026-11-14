from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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

# Startup needs to check the deployed Alembic revision. Keep this inventory
# separate from the application SELECT set used to derive INSERT permissions.
SCHEMA_REVISION_READ_TABLES: Final = frozenset({"alembic_version"})

RUNTIME_TABLE_PRIVILEGES: Final[Mapping[DatabaseRole, Mapping[TableOperation, frozenset[str]]]] = {
    DatabaseRole.API: {
        "SELECT": API_SELECT_TABLES | SCHEMA_REVISION_READ_TABLES,
        "INSERT": API_INSERT_TABLES,
        "UPDATE": API_UPDATE_TABLES,
        "DELETE": API_DELETE_TABLES,
    },
    DatabaseRole.WORKER: {
        "SELECT": WORKER_SELECT_TABLES | SCHEMA_REVISION_READ_TABLES,
        "INSERT": WORKER_INSERT_TABLES,
        "UPDATE": WORKER_UPDATE_TABLES,
        "DELETE": WORKER_DELETE_TABLES,
    },
}

RUNTIME_SEQUENCE_PRIVILEGES: Final[Mapping[DatabaseRole, frozenset[str]]] = {
    DatabaseRole.API: frozenset(),
    DatabaseRole.WORKER: frozenset(),
}
_VECTOR_TYPEMOD: Final = "public.vector(public.vector, pg_catalog.int4, pg_catalog.bool)"
_VECTOR_COSINE: Final = "public.cosine_distance(public.vector, public.vector)"
_AZURE_VECTOR_ROUTINE_COUNT: Final = 118
RUNTIME_FUNCTION_PRIVILEGES: Final[Mapping[DatabaseRole, frozenset[str]]] = {
    DatabaseRole.API: frozenset({_VECTOR_TYPEMOD, _VECTOR_COSINE}),
    DatabaseRole.WORKER: frozenset({_VECTOR_TYPEMOD}),
}

_PUBLIC_ROUTINES: Final = """
    SELECT p.oid,
           pg_catalog.format('%I.%I(%s)', n.nspname, p.proname,
                             pg_catalog.pg_get_function_identity_arguments(p.oid)) AS routine,
           pg_catalog.pg_get_userbyid(p.proowner) AS owner,
           EXISTS (
               SELECT 1 FROM pg_catalog.pg_depend AS d
               JOIN pg_catalog.pg_extension AS e ON e.oid = d.refobjid
               WHERE d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
                 AND d.objid = p.oid AND d.objsubid = 0
                 AND d.refclassid = 'pg_catalog.pg_extension'::pg_catalog.regclass
                 AND d.deptype = 'e' AND e.extname = 'vector' AND e.extnamespace = n.oid
           ) AS is_vector
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
"""


async def application_routines(connection: AsyncConnection, *, owner: str) -> tuple[str, ...]:
    routines = (await connection.execute(text(_PUBLIC_ROUTINES + " ORDER BY routine"))).all()
    application = [row for row in routines if not row.is_vector]
    if any(row.owner != owner for row in application):
        raise RuntimeError("migration principal does not own the application routines")
    return tuple(str(row.routine) for row in application)


async def _runtime_function_oids(connection: AsyncConnection, role: DatabaseRole) -> set[int]:
    expected: set[int] = set()
    for routine in sorted(RUNTIME_FUNCTION_PRIVILEGES[role]):
        oid = (
            await connection.execute(
                text(
                    "SELECT oid FROM (" + _PUBLIC_ROUTINES + ") AS routines "
                    "WHERE is_vector AND oid = pg_catalog.to_regprocedure(:routine)"
                ),
                {"routine": routine},
            )
        ).scalar_one_or_none()
        if oid is None:
            raise RuntimeError("required vector routine is missing or is not an extension member")
        expected.add(int(oid))
    return expected


async def require_runtime_function_privileges(
    connection: AsyncConnection, role: DatabaseRole, *, principal: str,
    managed: bool = False,
) -> dict[str, object]:
    expected = await _runtime_function_oids(connection, role)
    rows = (
        await connection.execute(
            text(
                "SELECT oid, pg_catalog.has_function_privilege(CAST(:principal AS name), "
                "oid, 'EXECUTE'), pg_catalog.has_function_privilege(CAST(:principal AS name), "
                "oid, 'EXECUTE WITH GRANT OPTION') FROM (" + _PUBLIC_ROUTINES + ") AS routines"
            ),
            {"principal": principal},
        )
    ).all()
    observed = {int(oid) for oid, execute, _ in rows if execute}
    provider, extension_version = (
        await _azure_vector_routines(connection, principal) if managed else ({}, None)
    )
    if provider and not expected <= provider.keys():
        raise RuntimeError("required routines are absent from the Azure vector baseline")
    if observed != (set(provider) if provider else expected) or any(
        grant for _, _, grant in rows
    ):
        raise RuntimeError("runtime routine grants differ from the exact matrix")
    return {
        "functionObjectsChecked": len(rows),
        "effectiveExecuteCount": len(observed),
        "requiredVectorSignatures": sorted(RUNTIME_FUNCTION_PRIVILEGES[role]),
        "providerPublicVectorRoutineCount": len(provider),
        "providerPublicVectorExtensionVersion": extension_version,
        "providerPublicVectorInventorySha256": hashlib.sha256(
            b"m7.8/azure-public-vector-inventory/v1\0"
            + json.dumps({
                "extension": "vector",
                "schema": "public",
                "version": extension_version,
                "extensionOwner": "azuresu",
                "routineOwner": "azuresu",
                "publicGrantor": "azuresu",
                "publicExecute": True,
                "publicGrantOption": False,
                "routineSignatures": sorted(provider.values()),
            }, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest() if provider else None,
    }


async def _azure_vector_routines(
    connection: AsyncConnection, principal: str,
) -> tuple[dict[int, str], str | None]:
    """Allow only the observed provider-owned vector extension's public baseline."""
    rows = (await connection.execute(text("""
        SELECT q.oid, q.routine, e.extversion,
            q.owner='azuresu' AS provider_owner,
            e.extowner=a.oid AS provider_extension,
            EXISTS (SELECT 1 FROM pg_catalog.aclexplode(
                COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) x
                WHERE x.grantee=0 AND x.privilege_type='EXECUTE' AND x.grantor=a.oid
                  AND NOT x.is_grantable) AS provider_public,
            NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode(
                COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) x
                WHERE x.privilege_type='EXECUTE' AND (x.grantee=r.oid OR
                (x.grantee=0 AND (x.grantor IS DISTINCT FROM a.oid OR x.is_grantable))))
                AS no_direct_or_other_public,
            (a.rolsuper AND r.rolcanlogin AND NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
                OR r.rolreplication OR r.rolbypassrls)
                AND NOT pg_catalog.pg_has_role(r.oid,a.oid,'MEMBER') AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles admin WHERE admin.rolname='azure_pg_admin'
                AND pg_catalog.pg_has_role(r.oid,admin.oid,'MEMBER'))) AS restricted
        FROM (""" + _PUBLIC_ROUTINES + """) q
        JOIN pg_catalog.pg_proc p ON p.oid=q.oid
        CROSS JOIN pg_catalog.pg_roles r
        LEFT JOIN pg_catalog.pg_roles a ON a.rolname='azuresu'
        LEFT JOIN pg_catalog.pg_extension e ON e.extname='vector' AND e.extnamespace=(
            SELECT n.oid FROM pg_catalog.pg_namespace n WHERE n.nspname='public')
        WHERE q.is_vector AND r.rolname=:principal
        ORDER BY q.routine
    """), {"principal": principal})).all()
    if not any(row.provider_extension or row.provider_owner for row in rows):
        return {}, None
    if len(rows) != _AZURE_VECTOR_ROUTINE_COUNT or any(
        value is not True for row in rows for value in row[3:]
    ):
        raise RuntimeError("Azure provider vector ownership or PUBLIC grants differ")
    version = rows[0].extversion
    if not isinstance(version, str) or not version:
        raise RuntimeError("Azure provider vector extension version is unproved")
    return {int(row.oid): str(row.routine) for row in rows}, version


async def configure_vector_runtime_functions(
    connection: AsyncConnection, *, api_principal: str, worker_principal: str,
    managed: bool = False,
) -> None:
    provider, _ = await _azure_vector_routines(connection, api_principal) if managed else ({}, None)
    if provider:
        for role, principal in ((DatabaseRole.API, api_principal),
                                (DatabaseRole.WORKER, worker_principal)):
            await require_runtime_function_privileges(
                connection, role, principal=principal, managed=True,
            )
        return
    # For an installer-owned extension, control the exact runtime routine ACLs.
    for role in RUNTIME_FUNCTION_PRIVILEGES:
        await _runtime_function_oids(connection, role)
    routines = (
        await connection.execute(text(_PUBLIC_ROUTINES + " ORDER BY routine"))
    ).all()
    api = quote_identifier(api_principal)
    worker = quote_identifier(worker_principal)
    for row in routines:
        if row.is_vector:
            await connection.execute(
                text(f"REVOKE EXECUTE ON ROUTINE {row.routine} FROM PUBLIC, {api}, {worker}")
            )
    for role, principal in ((DatabaseRole.API, api), (DatabaseRole.WORKER, worker)):
        for routine in sorted(RUNTIME_FUNCTION_PRIVILEGES[role]):
            await connection.execute(text(f"GRANT EXECUTE ON ROUTINE {routine} TO {principal}"))


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_grant(operation: TableOperation, tables: Sequence[str], principal: str) -> str:
    qualified = ", ".join(f"public.{quote_identifier(table)}" for table in tables)
    return f"GRANT {operation} ON TABLE {qualified} TO {quote_identifier(principal)}"


def runtime_privilege_statements(
    *, api_principal: str, worker_principal: str, migration_principal: str,
    application_routines: Sequence[str],
) -> tuple[str, ...]:
    principals = {
        DatabaseRole.API: api_principal,
        DatabaseRole.WORKER: worker_principal,
    }
    quoted_migration = quote_identifier(migration_principal)
    statements: list[str] = [
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_migration} "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
    ]
    api = quote_identifier(api_principal)
    worker = quote_identifier(worker_principal)
    for routine in application_routines:
        statements.append(f"REVOKE EXECUTE ON ROUTINE {routine} FROM PUBLIC, {api}, {worker}")
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
            )
        )
        # Role membership is revoked by the privileged bootstrap, not by this
        # unprivileged schema owner. The caller rejects inherited migration
        # membership before committing these object grants.
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
