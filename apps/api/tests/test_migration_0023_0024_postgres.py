from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from opencanvas_api.db.models import Base
from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres

SYSTEM_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
RESOURCE_WORKSPACE_ID = uuid.UUID("10000000-0000-4000-8000-000000000023")
RESOURCE_CANVAS_ID = uuid.UUID("20000000-0000-4000-8000-000000000023")
RESOURCE_OBJECT_ID = uuid.UUID("30000000-0000-4000-8000-000000000023")
RESOURCE_WORKFLOW_ID = uuid.UUID("40000000-0000-4000-8000-000000000023")
RESOURCE_AGENT_ID = uuid.UUID("50000000-0000-4000-8000-000000000023")
RESOURCE_WORKFLOW_TRACE_ID = uuid.UUID("60000000-0000-4000-8000-000000000023")
RESOURCE_AGENT_TRACE_ID = uuid.UUID("70000000-0000-4000-8000-000000000023")
ZERO_UUID = uuid.UUID(int=0)
PROTECTED_TRIGGERS = {
    "collaboration_resources": "trg_collaboration_resources_mutation_blocked",
    "collaboration_resource_ownership_transitions": (
        "trg_collaboration_resource_ownership_transitions_mutation_blocked"
    ),
    "collaboration_resource_shares": "trg_collaboration_resource_shares_mutation_blocked",
    "collaboration_resource_share_transitions": (
        "trg_collaboration_resource_share_transitions_mutation_blocked"
    ),
    "collaboration_ownership_transfers": ("trg_collaboration_ownership_transfers_mutation_blocked"),
    "collaboration_ownership_transfer_transitions": (
        "trg_collaboration_ownership_transfer_transitions_mutation_blocked"
    ),
    "collaboration_authority_snapshots": ("trg_collaboration_authority_snapshots_mutation_blocked"),
    "collaboration_revocation_fences": ("trg_collaboration_revocation_fences_mutation_blocked"),
    "collaboration_comment_threads": "trg_collaboration_comment_threads_mutation_blocked",
    "collaboration_comment_thread_transitions": (
        "trg_collaboration_comment_thread_transitions_mutation_blocked"
    ),
    "collaboration_comments": "trg_collaboration_comments_mutation_blocked",
    "collaboration_comment_revisions": ("trg_collaboration_comment_revisions_mutation_blocked"),
    "collaboration_comment_transitions": ("trg_collaboration_comment_transitions_mutation_blocked"),
}
PROTECTED_0023_TABLES = frozenset(
    {
        "collaboration_authority_snapshots",
        "collaboration_ownership_transfer_transitions",
        "collaboration_ownership_transfers",
        "collaboration_resource_ownership_transitions",
        "collaboration_resource_share_transitions",
        "collaboration_resource_shares",
        "collaboration_resources",
        "collaboration_revocation_fences",
    }
)
TriggerCatalogIdentity = tuple[dict[str, tuple[int, int]], tuple[int, int]]


def _postgres_identifier(name: str) -> str:
    return name[:63]


def _load_migration(filename: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION_0023 = _load_migration("20260725_0023_resource_sharing_ownership_revocation.py")
MIGRATION_0024 = _load_migration("20260725_0024_comments_collaboration_activity.py")


@pytest.fixture
def postgres_migration_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _config(database_url: str) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _asyncpg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _assert_model_catalog(connection: Connection) -> None:
    inspector = inspect(connection)
    expected_tables = set(Base.metadata.tables)
    actual_tables = set(inspector.get_table_names(schema="public"))
    assert actual_tables == expected_tables | {"alembic_version"}

    for table_name, table in Base.metadata.tables.items():
        expected_primary_key = [column.name for column in table.primary_key.columns]
        actual_primary_key = inspector.get_pk_constraint(table_name)["constrained_columns"]
        assert actual_primary_key == expected_primary_key

        expected_foreign_keys = {
            (
                tuple(element.parent.name for element in constraint.elements),
                constraint.referred_table.name,
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete,
            )
            for constraint in table.foreign_key_constraints
        }
        actual_foreign_keys = {
            (
                tuple(foreign_key["constrained_columns"]),
                str(foreign_key["referred_table"]),
                tuple(foreign_key["referred_columns"]),
                foreign_key.get("options", {}).get("ondelete"),
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        assert expected_foreign_keys <= actual_foreign_keys


async def _assert_clean_model_catalog(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_assert_model_catalog)
    finally:
        await engine.dispose()


async def _schema_catalog_identity(
    database_url: str,
) -> tuple[tuple[tuple[str, str, str], ...], tuple[tuple[str, str, str, str], ...]]:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        indexes = tuple(
            (
                str(row["tablename"]),
                str(row["indexname"]),
                str(row["indexdef"]),
            )
            for row in await connection.fetch(
                """SELECT tablename, indexname, indexdef
                   FROM pg_indexes
                   WHERE schemaname = 'public'
                   ORDER BY tablename, indexname"""
            )
        )
        constraints = tuple(
            (
                str(row["table_name"]),
                str(row["constraint_name"]),
                str(row["constraint_type"]),
                str(row["definition"]),
            )
            for row in await connection.fetch(
                """SELECT relation.relname AS table_name,
                          constraint_record.conname AS constraint_name,
                          constraint_record.contype::text AS constraint_type,
                          pg_get_constraintdef(constraint_record.oid, true) AS definition
                   FROM pg_constraint AS constraint_record
                   JOIN pg_class AS relation
                     ON relation.oid = constraint_record.conrelid
                   JOIN pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   WHERE namespace.nspname = 'public'
                   ORDER BY relation.relname, constraint_record.conname"""
            )
        )
        return indexes, constraints
    finally:
        await connection.close()


async def _seed_registry_rows(
    database_url: str,
    registries: dict[str, tuple[str, ...]],
) -> uuid.UUID:
    workspace_id = uuid.uuid4()
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await connection.execute(
            "INSERT INTO workspaces (id, name, owner_id) VALUES ($1, 'Registry workspace', $2)",
            workspace_id,
            SYSTEM_USER_ID,
        )
        event_types = registries["ck_domain_events_type"]
        subject_kinds = registries["ck_domain_events_subject_kind"]
        await connection.executemany(
            """INSERT INTO domain_events
               (event_id, user_id, workspace_id, canvas_id, scope_id, sequence,
                event_type, registry_version, schema_version, subject_kind, subject_id,
                actor_user_id, source_identity, occurred_at, payload, payload_digest,
                request_digest, trace_id)
               VALUES ($1, $2, $3, NULL, $4, $5, $6, 'mobius-domain-events-v1',
                       'domain-event-v1', $7, $8, $2, $9, CURRENT_TIMESTAMP,
                       '{}'::json, $10, $11, $12)""",
            [
                (
                    uuid.uuid4(),
                    SYSTEM_USER_ID,
                    workspace_id,
                    uuid.uuid4(),
                    sequence,
                    event_type,
                    subject_kinds[(sequence - 1) % len(subject_kinds)],
                    uuid.uuid4(),
                    f"registry-seed-{sequence}",
                    "a" * 64,
                    "b" * 64,
                    uuid.uuid4(),
                )
                for sequence, event_type in enumerate(event_types, start=1)
            ],
        )
        result_kinds = registries["ck_collaboration_request_result_kind"]
        await connection.executemany(
            """INSERT INTO collaboration_request_identities
               (request_id, actor_user_id, workspace_id, operation, idempotency_key,
                request_digest, result_kind, result_id, trace_id, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, CURRENT_TIMESTAMP)""",
            [
                (
                    uuid.uuid4(),
                    SYSTEM_USER_ID,
                    workspace_id,
                    operation,
                    f"registry-request-{ordinal}",
                    "c" * 64,
                    result_kinds[ordinal % len(result_kinds)],
                    uuid.uuid4(),
                    uuid.uuid4(),
                )
                for ordinal, operation in enumerate(
                    registries["ck_collaboration_request_operation"]
                )
            ],
        )
        await connection.executemany(
            """INSERT INTO collaboration_audit_events
               (audit_event_id, workspace_id, actor_user_id, subject_kind, subject_id,
                action, outcome, reason_code, metadata_digest, trace_id, recorded_at)
               VALUES ($1, $2, $3, $4, $5, $6, 'succeeded', 'registry_seed',
                       $7, $8, CURRENT_TIMESTAMP)""",
            [
                (
                    uuid.uuid4(),
                    workspace_id,
                    SYSTEM_USER_ID,
                    subject_kind,
                    uuid.uuid4(),
                    f"registry.seed.{ordinal}",
                    "d" * 64,
                    uuid.uuid4(),
                )
                for ordinal, subject_kind in enumerate(
                    registries["ck_collaboration_audit_subject_kind"]
                )
            ],
        )
    finally:
        await connection.close()
    return workspace_id


async def _seed_resource_rows(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await connection.execute(
            """INSERT INTO workspaces (id, name, owner_id)
               VALUES ($1, 'Resource backfill workspace', $2)""",
            RESOURCE_WORKSPACE_ID,
            SYSTEM_USER_ID,
        )
        await connection.execute(
            """INSERT INTO canvases (id, workspace_id, name)
               VALUES ($1, $2, 'Resource backfill canvas')""",
            RESOURCE_CANVAS_ID,
            RESOURCE_WORKSPACE_ID,
        )
        await connection.execute(
            """INSERT INTO canonical_objects
               (id, workspace_id, object_type, lifecycle_state)
               VALUES ($1, $2, 'note', 'active')""",
            RESOURCE_OBJECT_ID,
            RESOURCE_WORKSPACE_ID,
        )
        await connection.execute(
            """INSERT INTO controlled_workflow_definitions
               (definition_id, user_id, workspace_id, canvas_id, schema_version, kind,
                name, description, created_by_user_id, trace_id, created_at)
               VALUES ($1, $2, $3, $4, 'controlled-workflow-v1', 'grounded_answer',
                       'Resource backfill workflow', '', $2, $5, CURRENT_TIMESTAMP)""",
            RESOURCE_WORKFLOW_ID,
            SYSTEM_USER_ID,
            RESOURCE_WORKSPACE_ID,
            RESOURCE_CANVAS_ID,
            RESOURCE_WORKFLOW_TRACE_ID,
        )
        await connection.execute(
            """INSERT INTO bounded_agent_identities
               (agent_id, user_id, workspace_id, canvas_id, schema_version, kind,
                display_name, description, idempotency_key, request_digest,
                created_by_user_id, trace_id, created_at)
               VALUES ($1, $2, $3, $4, 'bounded-agent-studio-v1',
                       'workflow_assistant', 'Resource backfill agent', 'Bounded',
                       'resource-backfill-agent', $5, $2, $6, CURRENT_TIMESTAMP)""",
            RESOURCE_AGENT_ID,
            SYSTEM_USER_ID,
            RESOURCE_WORKSPACE_ID,
            RESOURCE_CANVAS_ID,
            "a" * 64,
            RESOURCE_AGENT_TRACE_ID,
        )
    finally:
        await connection.close()


async def _assert_resource_sources(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM canvases WHERE id = $1 AND workspace_id = $2",
                RESOURCE_CANVAS_ID,
                RESOURCE_WORKSPACE_ID,
            )
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM canonical_objects WHERE id = $1 AND workspace_id = $2",
                RESOURCE_OBJECT_ID,
                RESOURCE_WORKSPACE_ID,
            )
            == 1
        )
        assert (
            await connection.fetchval(
                """SELECT count(*) FROM controlled_workflow_definitions
               WHERE definition_id = $1 AND user_id = $2
                 AND workspace_id = $3 AND canvas_id = $4""",
                RESOURCE_WORKFLOW_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
            )
            == 1
        )
        assert (
            await connection.fetchval(
                """SELECT count(*) FROM bounded_agent_identities
               WHERE agent_id = $1 AND user_id = $2
                 AND workspace_id = $3 AND canvas_id = $4""",
                RESOURCE_AGENT_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
            )
            == 1
        )
    finally:
        await connection.close()


async def _assert_resource_backfill(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        rows = await connection.fetch(
            """SELECT resource_kind, resource_id, workspace_id, canvas_id,
                      canonical_object_id, workflow_definition_id, agent_id,
                      target_user_id, creator_user_id, creation_trace_id
               FROM collaboration_resources
               WHERE workspace_id = $1
               ORDER BY resource_kind""",
            RESOURCE_WORKSPACE_ID,
        )
        actual = {
            row["resource_kind"]: (
                row["resource_id"],
                row["workspace_id"],
                row["canvas_id"],
                row["canonical_object_id"],
                row["workflow_definition_id"],
                row["agent_id"],
                row["target_user_id"],
                row["creator_user_id"],
                row["creation_trace_id"],
            )
            for row in rows
        }
        assert actual == {
            "agent": (
                RESOURCE_AGENT_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
                None,
                None,
                RESOURCE_AGENT_ID,
                SYSTEM_USER_ID,
                SYSTEM_USER_ID,
                RESOURCE_AGENT_TRACE_ID,
            ),
            "canonical_object": (
                RESOURCE_OBJECT_ID,
                RESOURCE_WORKSPACE_ID,
                None,
                RESOURCE_OBJECT_ID,
                None,
                None,
                None,
                SYSTEM_USER_ID,
                RESOURCE_OBJECT_ID,
            ),
            "canvas": (
                RESOURCE_CANVAS_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
                None,
                None,
                None,
                None,
                SYSTEM_USER_ID,
                RESOURCE_CANVAS_ID,
            ),
            "workflow": (
                RESOURCE_WORKFLOW_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
                None,
                RESOURCE_WORKFLOW_ID,
                None,
                SYSTEM_USER_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKFLOW_TRACE_ID,
            ),
        }
        assert len(rows) == 4

        non_null_uuids = {
            value for values in actual.values() for value in values if isinstance(value, uuid.UUID)
        }
        assert ZERO_UUID not in non_null_uuids
        assert non_null_uuids <= {
            SYSTEM_USER_ID,
            RESOURCE_WORKSPACE_ID,
            RESOURCE_CANVAS_ID,
            RESOURCE_OBJECT_ID,
            RESOURCE_WORKFLOW_ID,
            RESOURCE_AGENT_ID,
            RESOURCE_WORKFLOW_TRACE_ID,
            RESOURCE_AGENT_TRACE_ID,
        }

        transitions = await connection.fetch(
            """SELECT resource_id, resource_kind, workspace_id, sequence,
                      previous_owner_kind, current_owner_kind,
                      current_owner_membership_id, current_owner_user_id,
                      visibility_policy, authority_generation, actor_user_id,
                      actor_membership_id, reason_code, trace_id
               FROM collaboration_resource_ownership_transitions
               WHERE workspace_id = $1
               ORDER BY resource_kind""",
            RESOURCE_WORKSPACE_ID,
        )
        assert len(transitions) == 4
        expected_traces = {
            "agent": RESOURCE_AGENT_TRACE_ID,
            "canonical_object": RESOURCE_OBJECT_ID,
            "canvas": RESOURCE_CANVAS_ID,
            "workflow": RESOURCE_WORKFLOW_TRACE_ID,
        }
        for transition in transitions:
            assert transition["resource_id"] == actual[transition["resource_kind"]][0]
            assert transition["workspace_id"] == RESOURCE_WORKSPACE_ID
            assert transition["sequence"] == 0
            assert transition["previous_owner_kind"] is None
            assert transition["current_owner_kind"] == "workspace"
            assert transition["current_owner_membership_id"] is None
            assert transition["current_owner_user_id"] is None
            assert transition["visibility_policy"] == "private"
            assert transition["authority_generation"] == 1
            assert transition["actor_user_id"] == SYSTEM_USER_ID
            assert transition["actor_membership_id"] is None
            assert transition["reason_code"] == "resource_owner_backfill"
            assert transition["trace_id"] == expected_traces[transition["resource_kind"]]

        uuid_columns = {
            row["column_name"]: row["udt_name"]
            for row in await connection.fetch(
                """SELECT column_name, udt_name
                   FROM information_schema.columns
                   WHERE table_schema = 'public'
                     AND table_name = 'collaboration_resources'
                     AND column_name = ANY($1::text[])""",
                [
                    "canvas_id",
                    "canonical_object_id",
                    "workflow_definition_id",
                    "agent_id",
                    "target_user_id",
                ],
            )
        }
        assert uuid_columns == {
            "canvas_id": "uuid",
            "canonical_object_id": "uuid",
            "workflow_definition_id": "uuid",
            "agent_id": "uuid",
            "target_user_id": "uuid",
        }

        unknown_canvas_id = uuid.uuid4()
        with pytest.raises(asyncpg.ForeignKeyViolationError) as raised:
            await connection.execute(
                """INSERT INTO collaboration_resources
                   (resource_id, workspace_id, resource_kind, canvas_id,
                    canonical_object_id, workflow_definition_id, agent_id,
                    target_user_id, creator_user_id, creation_trace_id, created_at)
                   VALUES ($1, $2, 'canvas', $1, NULL, NULL, NULL, NULL,
                           $3, $4, CURRENT_TIMESTAMP)""",
                unknown_canvas_id,
                RESOURCE_WORKSPACE_ID,
                SYSTEM_USER_ID,
                uuid.uuid4(),
            )
        assert raised.value.constraint_name == "fk_collaboration_resource_canvas_scope"
    finally:
        await connection.close()


async def _assert_registry_constraints(
    database_url: str,
    migration: ModuleType,
    expected: dict[str, tuple[str, ...]],
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            checks_by_table = await connection.run_sync(
                lambda sync_connection: {
                    table: {
                        item["name"]: item["sqltext"]
                        for item in inspect(sync_connection).get_check_constraints(table)
                    }
                    for table in (
                        "domain_events",
                        "collaboration_request_identities",
                        "collaboration_audit_events",
                    )
                }
            )
        for table, constraint in (
            ("domain_events", "ck_domain_events_type"),
            ("domain_events", "ck_domain_events_subject_kind"),
            (
                "collaboration_request_identities",
                "ck_collaboration_request_operation",
            ),
            (
                "collaboration_request_identities",
                "ck_collaboration_request_result_kind",
            ),
            (
                "collaboration_audit_events",
                "ck_collaboration_audit_subject_kind",
            ),
        ):
            expression = checks_by_table[table][constraint]
            assert "ANY" in expression
            assert (
                migration._parse_check_values(
                    expression,
                    column=migration._CLOSED_CHECK_COLUMNS[constraint],
                )
                == expected[constraint]
            )
    finally:
        await engine.dispose()


async def _assert_seeded_rows(
    database_url: str,
    registries: dict[str, tuple[str, ...]],
) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert {
            row["event_type"]
            for row in await connection.fetch("SELECT event_type FROM domain_events")
        } == {value for value in registries["ck_domain_events_type"]}
        assert {
            row["subject_kind"]
            for row in await connection.fetch("SELECT subject_kind FROM domain_events")
        } == {value for value in registries["ck_domain_events_subject_kind"]}
        assert {
            row["operation"]
            for row in await connection.fetch(
                "SELECT operation FROM collaboration_request_identities"
            )
        } == {value for value in registries["ck_collaboration_request_operation"]}
        assert {
            row["result_kind"]
            for row in await connection.fetch(
                "SELECT result_kind FROM collaboration_request_identities"
            )
        } == {value for value in registries["ck_collaboration_request_result_kind"]}
        assert {
            row["subject_kind"]
            for row in await connection.fetch("SELECT subject_kind FROM collaboration_audit_events")
        } == {value for value in registries["ck_collaboration_audit_subject_kind"]}
    finally:
        await connection.close()


async def _assert_invalid_event_rejected(
    database_url: str,
    workspace_id: uuid.UUID,
) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        with pytest.raises(asyncpg.CheckViolationError) as raised:
            await connection.execute(
                """INSERT INTO domain_events
                   (event_id, user_id, workspace_id, canvas_id, scope_id, sequence,
                    event_type, registry_version, schema_version, subject_kind, subject_id,
                    actor_user_id, source_identity, occurred_at, payload, payload_digest,
                    request_digest, trace_id)
                   VALUES ($1, $2, $3, NULL, $4, 1000, 'unapproved.event',
                           'mobius-domain-events-v1', 'domain-event-v1',
                           'canonical_resource', $5, $2, 'invalid-registry-seed',
                           CURRENT_TIMESTAMP, '{}'::json, $6, $7, $8)""",
                uuid.uuid4(),
                SYSTEM_USER_ID,
                workspace_id,
                uuid.uuid4(),
                uuid.uuid4(),
                "e" * 64,
                "f" * 64,
                uuid.uuid4(),
            )
        assert raised.value.constraint_name == "ck_domain_events_type"
    finally:
        await connection.close()


async def _assert_protected_trigger_catalog(
    database_url: str,
    expected_tables: frozenset[str] | None = None,
) -> TriggerCatalogIdentity:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        expected_tables = (
            frozenset(PROTECTED_TRIGGERS) if expected_tables is None else expected_tables
        )
        functions = await connection.fetch(
            """SELECT ns.nspname AS schema_name, p.oid::bigint AS function_oid,
                      p.pronargs, pg_get_function_identity_arguments(p.oid) AS arguments,
                      pg_get_function_result(p.oid) AS result_type,
                      language.lanname AS language, p.prosrc AS source
               FROM pg_proc p
               JOIN pg_namespace ns ON ns.oid = p.pronamespace
               JOIN pg_language language ON language.oid = p.prolang
               WHERE p.proname = 'reject_controlled_agent_mutation'"""
        )
        assert len(functions) == 1
        function = functions[0]
        assert function["schema_name"] == "public"
        assert function["pronargs"] == 0
        assert function["arguments"] == ""
        assert function["result_type"] == "trigger"
        assert function["language"] == "plpgsql"
        assert "RAISE EXCEPTION 'controlled-agent records are append-only';" in function["source"]
        function_oid = function["function_oid"]
        assert function_oid > 0
        assert (
            await connection.fetchval(
                "SELECT to_regprocedure('public.reject_controlled_agent_mutation()')::oid"
            )
            == function_oid
        )
        assert (
            await connection.fetchval(
                """SELECT count(*)
                   FROM pg_proc
                   WHERE proname = 'reject_controlled_agent_security_mutation'"""
            )
            == 0
        )
        assert (
            await connection.fetchval(
                "SELECT to_regprocedure('public.reject_controlled_agent_security_mutation()')"
            )
            is None
        )

        trigger_rows = await connection.fetch(
            """SELECT table_class.relname AS table_name, trigger.tgname AS trigger_name,
                      trigger.oid::bigint AS trigger_oid,
                      trigger.tgtype::integer AS trigger_type,
                      function.oid::bigint AS function_oid,
                      function.proname AS function_name,
                      pg_get_triggerdef(trigger.oid, true) AS definition
               FROM pg_trigger trigger
               JOIN pg_class table_class ON table_class.oid = trigger.tgrelid
               JOIN pg_namespace ns ON ns.oid = table_class.relnamespace
               JOIN pg_proc function ON function.oid = trigger.tgfoid
               WHERE ns.nspname = 'public'
                 AND NOT trigger.tgisinternal
                 AND table_class.relname = ANY($1::text[])
                 AND trigger.tgname = ANY($2::text[])""",
            list(expected_tables),
            [_postgres_identifier(PROTECTED_TRIGGERS[table]) for table in sorted(expected_tables)],
        )
        expected_server_triggers = {
            table: _postgres_identifier(PROTECTED_TRIGGERS[table]) for table in expected_tables
        }
        assert len(set(expected_server_triggers.values())) == len(expected_tables)
        actual_triggers = {row["table_name"]: row["trigger_name"] for row in trigger_rows}
        assert actual_triggers == expected_server_triggers, {
            "missing": set(expected_server_triggers.items()) - set(actual_triggers.items()),
            "unexpected": set(actual_triggers.items()) - set(expected_server_triggers.items()),
        }
        assert len(trigger_rows) == len(expected_tables)
        assert len({row["trigger_oid"] for row in trigger_rows}) == len(expected_tables)
        for row in trigger_rows:
            assert row["trigger_oid"] > 0
            assert row["trigger_type"] == 27  # row-level BEFORE UPDATE OR DELETE
            assert row["function_oid"] == function_oid
            assert row["function_name"] == "reject_controlled_agent_mutation"
            assert "EXECUTE FUNCTION reject_controlled_agent_mutation()" in row["definition"]

        domain_triggers = await connection.fetch(
            """SELECT trigger.oid::bigint AS trigger_oid,
                      trigger.tgtype::integer AS trigger_type,
                      function.oid::bigint AS function_oid,
                      function.proname AS function_name,
                      pg_get_triggerdef(trigger.oid, true) AS definition
               FROM pg_trigger trigger
               JOIN pg_class table_class ON table_class.oid = trigger.tgrelid
               JOIN pg_namespace ns ON ns.oid = table_class.relnamespace
               JOIN pg_proc function ON function.oid = trigger.tgfoid
               WHERE ns.nspname = 'public'
                 AND table_class.relname = 'domain_events'
                 AND trigger.tgname = 'trg_domain_events_mutation_blocked'
                 AND NOT trigger.tgisinternal"""
        )
        assert len(domain_triggers) == 1
        domain_trigger = domain_triggers[0]
        assert domain_trigger["trigger_oid"] > 0
        assert domain_trigger["trigger_type"] == 27
        assert domain_trigger["function_oid"] > 0
        assert domain_trigger["function_oid"] != function_oid
        assert domain_trigger["function_name"] == "reject_domain_events_mutation"
        assert "EXECUTE FUNCTION reject_domain_events_mutation()" in domain_trigger["definition"]
        assert (
            await connection.fetchval(
                "SELECT to_regprocedure('public.reject_domain_events_mutation()')::oid"
            )
            == domain_trigger["function_oid"]
        )
        return (
            {row["table_name"]: (row["trigger_oid"], row["function_oid"]) for row in trigger_rows},
            (domain_trigger["trigger_oid"], domain_trigger["function_oid"]),
        )
    finally:
        await connection.close()


def _invoke_domain_event_fallback(
    connection: Connection,
    migration: ModuleType,
) -> None:
    original_op = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        migration._protect_domain_events()
    finally:
        migration.op = original_op


async def _assert_domain_event_fallback_probe(
    database_url: str,
    migration: ModuleType,
    workspace_id: uuid.UUID,
) -> None:
    query = text(
        """SELECT trigger.oid::bigint AS trigger_oid,
                  trigger.tgtype::integer AS trigger_type,
                  function.oid::bigint AS function_oid,
                  function.proname AS function_name
           FROM pg_trigger trigger
           JOIN pg_class table_class ON table_class.oid = trigger.tgrelid
           JOIN pg_namespace ns ON ns.oid = table_class.relnamespace
           JOIN pg_proc function ON function.oid = trigger.tgfoid
           WHERE ns.nspname = 'public'
             AND table_class.relname = 'domain_events'
             AND trigger.tgname = 'trg_domain_events_mutation_blocked'
             AND NOT trigger.tgisinternal"""
    )
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                normal_rows = list((await connection.execute(query)).mappings())
                assert len(normal_rows) == 1
                normal = dict(normal_rows[0])
                assert normal["trigger_oid"] > 0
                assert normal["trigger_type"] == 27
                assert normal["function_oid"] > 0
                assert normal["function_name"] == "reject_domain_events_mutation"

                await connection.execute(
                    text("DROP TRIGGER trg_domain_events_mutation_blocked ON domain_events")
                )
                await connection.run_sync(
                    lambda sync_connection: _invoke_domain_event_fallback(
                        sync_connection,
                        migration,
                    )
                )
                fallback_rows = list((await connection.execute(query)).mappings())
                assert len(fallback_rows) == 1
                fallback = fallback_rows[0]
                assert fallback["trigger_oid"] > 0
                assert fallback["trigger_type"] == 27
                assert fallback["function_oid"] > 0
                assert fallback["function_oid"] != normal["function_oid"]
                assert fallback["function_name"] == "reject_controlled_agent_mutation"

                event = (
                    (
                        await connection.execute(
                            text(
                                """SELECT * FROM domain_events
                               WHERE workspace_id = :workspace_id
                               ORDER BY sequence
                               LIMIT 1"""
                            ),
                            {"workspace_id": workspace_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                event_before = dict(event)
                event_id = event_before["event_id"]
                count_before = (
                    await connection.execute(
                        text(
                            """SELECT count(*) FROM domain_events
                               WHERE workspace_id = :workspace_id"""
                        ),
                        {"workspace_id": workspace_id},
                    )
                ).scalar_one()
                for statement in (
                    "UPDATE domain_events SET workspace_id = workspace_id "
                    "WHERE event_id = :event_id",
                    "DELETE FROM domain_events WHERE event_id = :event_id",
                ):
                    with pytest.raises(
                        DBAPIError,
                        match="controlled-agent records are append-only",
                    ):
                        async with connection.begin_nested():
                            await connection.execute(
                                text(statement),
                                {"event_id": event_id},
                            )
                    preserved = (
                        (
                            await connection.execute(
                                text("SELECT * FROM domain_events WHERE event_id = :event_id"),
                                {"event_id": event_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert dict(preserved) == event_before
                    assert (
                        await connection.execute(
                            text(
                                """SELECT count(*) FROM domain_events
                                   WHERE workspace_id = :workspace_id"""
                            ),
                            {"workspace_id": workspace_id},
                        )
                    ).scalar_one() == count_before
            finally:
                await transaction.rollback()

        async with engine.connect() as connection:
            restored_rows = list((await connection.execute(query)).mappings())
            assert len(restored_rows) == 1
            restored = restored_rows[0]
            assert restored["trigger_oid"] == normal["trigger_oid"]
            assert restored["trigger_type"] == 27
            assert restored["function_oid"] == normal["function_oid"]
            assert restored["function_name"] == "reject_domain_events_mutation"
    finally:
        await engine.dispose()


async def _insert_audit_event(
    connection: asyncpg.Connection,
    *,
    workspace_id: uuid.UUID,
    subject_kind: str,
    subject_id: uuid.UUID,
    action: str,
) -> uuid.UUID:
    audit_event_id = uuid.uuid4()
    await connection.execute(
        """INSERT INTO collaboration_audit_events
           (audit_event_id, workspace_id, actor_user_id, subject_kind, subject_id,
            action, outcome, reason_code, metadata_digest, trace_id, recorded_at)
           VALUES ($1, $2, $3, $4, $5, $6, 'succeeded', 'trigger_protection_fixture',
                   $7, $8, CURRENT_TIMESTAMP)""",
        audit_event_id,
        workspace_id,
        SYSTEM_USER_ID,
        subject_kind,
        subject_id,
        action,
        "9" * 64,
        uuid.uuid4(),
    )
    return audit_event_id


async def _seed_protected_trigger_rows(
    database_url: str,
) -> dict[str, tuple[str, uuid.UUID]]:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        member_user_id = uuid.uuid4()
        owner_membership_id = uuid.uuid4()
        member_membership_id = uuid.uuid4()
        owner_membership_audit_id = await _insert_audit_event(
            connection,
            workspace_id=RESOURCE_WORKSPACE_ID,
            subject_kind="workspace_membership",
            subject_id=owner_membership_id,
            action="trigger.fixture.owner_membership",
        )
        await connection.execute(
            """INSERT INTO users
               (id, email, email_normalized, password_hash, display_name)
               VALUES ($1, $2, $2, 'login-disabled', 'Trigger fixture member')""",
            member_user_id,
            f"trigger-fixture-{member_user_id.hex}@mobius.invalid",
        )
        member_membership_audit_id = await _insert_audit_event(
            connection,
            workspace_id=RESOURCE_WORKSPACE_ID,
            subject_kind="workspace_membership",
            subject_id=member_membership_id,
            action="trigger.fixture.member_membership",
        )
        await connection.execute(
            """INSERT INTO workspace_memberships
               (membership_id, user_id, workspace_id, created_by_user_id,
                collaboration_policy_version, creation_trace_id,
                creation_audit_event_id, created_at)
               VALUES ($1, $2, $3, $2, 'collaboration-policy-v1', $4, $5,
                       CURRENT_TIMESTAMP)""",
            owner_membership_id,
            SYSTEM_USER_ID,
            RESOURCE_WORKSPACE_ID,
            uuid.uuid4(),
            owner_membership_audit_id,
        )
        await connection.execute(
            """INSERT INTO workspace_membership_transitions
               (transition_id, membership_id, user_id, workspace_id, sequence,
                previous_state, current_state, previous_role, "current_role",
                reason_code, collaboration_policy_version, authority_generation,
                actor_user_id, trace_id, audit_event_id, recorded_at)
               VALUES ($1, $2, $3, $4, 0, NULL, 'active', NULL, 'owner',
                       'trigger_fixture', 'collaboration-policy-v1', 1, $3, $5, $6,
                       CURRENT_TIMESTAMP)""",
            uuid.uuid4(),
            owner_membership_id,
            SYSTEM_USER_ID,
            RESOURCE_WORKSPACE_ID,
            uuid.uuid4(),
            owner_membership_audit_id,
        )
        await connection.execute(
            """INSERT INTO workspace_memberships
               (membership_id, user_id, workspace_id, created_by_user_id,
                collaboration_policy_version, creation_trace_id,
                creation_audit_event_id, created_at)
               VALUES ($1, $2, $3, $4, 'collaboration-policy-v1', $5, $6,
                       CURRENT_TIMESTAMP)""",
            member_membership_id,
            member_user_id,
            RESOURCE_WORKSPACE_ID,
            SYSTEM_USER_ID,
            uuid.uuid4(),
            member_membership_audit_id,
        )
        await connection.execute(
            """INSERT INTO workspace_membership_transitions
               (transition_id, membership_id, user_id, workspace_id, sequence,
                previous_state, current_state, previous_role, "current_role",
                reason_code, collaboration_policy_version, authority_generation,
                actor_user_id, trace_id, audit_event_id, recorded_at)
               VALUES ($1, $2, $3, $4, 0, NULL, 'active', NULL, 'member',
                       'trigger_fixture', 'collaboration-policy-v1', 1, $5, $6, $7,
                       CURRENT_TIMESTAMP)""",
            uuid.uuid4(),
            member_membership_id,
            member_user_id,
            RESOURCE_WORKSPACE_ID,
            SYSTEM_USER_ID,
            uuid.uuid4(),
            member_membership_audit_id,
        )

        resource_id = uuid.uuid4()
        await connection.execute(
            """INSERT INTO canonical_objects
               (id, workspace_id, object_type, lifecycle_state)
               VALUES ($1, $2, 'note', 'active')""",
            resource_id,
            RESOURCE_WORKSPACE_ID,
        )
        ownership_transition_id = await connection.fetchval(
            """SELECT transition_id
               FROM collaboration_resource_ownership_transitions
               WHERE resource_id = $1 AND workspace_id = $2
                 AND resource_kind = 'canonical_object' AND sequence = 0""",
            resource_id,
            RESOURCE_WORKSPACE_ID,
        )
        assert isinstance(ownership_transition_id, uuid.UUID)
        action_audit_id = await _insert_audit_event(
            connection,
            workspace_id=RESOURCE_WORKSPACE_ID,
            subject_kind="collaboration_resource",
            subject_id=resource_id,
            action="trigger.fixture.protected_rows",
        )

        share_id = uuid.uuid4()
        share_transition_id = uuid.uuid4()
        await connection.execute(
            """INSERT INTO collaboration_resource_shares
               (share_id, workspace_id, resource_id, resource_kind, audience_kind,
                audience_key, audience_membership_id, audience_user_id,
                created_by_membership_id, created_by_user_id,
                collaboration_policy_version, creation_request_id, request_digest,
                creation_trace_id, creation_audit_event_id, created_at)
               VALUES ($1, $2, $3, 'canonical_object', 'workspace', 'workspace',
                       NULL, NULL, $4, $5, 'collaboration-policy-v1', $6, $7, $8,
                       $9, CURRENT_TIMESTAMP)""",
            share_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            owner_membership_id,
            SYSTEM_USER_ID,
            uuid.uuid4(),
            "1" * 64,
            uuid.uuid4(),
            action_audit_id,
        )
        await connection.execute(
            """INSERT INTO collaboration_resource_share_transitions
               (transition_id, share_id, workspace_id, sequence, previous_state,
                current_state, access_level, expires_at, authority_generation,
                actor_user_id, actor_membership_id, reason_code, trace_id,
                audit_event_id, recorded_at)
               VALUES ($1, $2, $3, 0, NULL, 'active', 'view', NULL, 1, $4, $5,
                       'trigger_fixture', $6, $7, CURRENT_TIMESTAMP)""",
            share_transition_id,
            share_id,
            RESOURCE_WORKSPACE_ID,
            SYSTEM_USER_ID,
            owner_membership_id,
            uuid.uuid4(),
            action_audit_id,
        )

        transfer_id = uuid.uuid4()
        transfer_transition_id = uuid.uuid4()
        await connection.execute(
            """INSERT INTO collaboration_ownership_transfers
               (transfer_id, workspace_id, transfer_kind, resource_id, resource_kind,
                requester_membership_id, requester_user_id, recipient_membership_id,
                recipient_user_id, former_owner_role, expires_at,
                collaboration_policy_version, idempotency_key, request_digest,
                creation_trace_id, creation_audit_event_id, created_at)
               VALUES ($1, $2, 'resource', $3, 'canonical_object', $4, $5, $6, $7,
                       'administrator', CURRENT_TIMESTAMP + INTERVAL '1 hour',
                       'collaboration-policy-v1', $8, $9, $10, $11,
                       CURRENT_TIMESTAMP)""",
            transfer_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            owner_membership_id,
            SYSTEM_USER_ID,
            member_membership_id,
            member_user_id,
            f"trigger-transfer-{transfer_id}",
            "2" * 64,
            uuid.uuid4(),
            action_audit_id,
        )
        await connection.execute(
            """INSERT INTO collaboration_ownership_transfer_transitions
               (transition_id, transfer_id, workspace_id, sequence, previous_state,
                current_state, authority_generation, actor_user_id,
                actor_membership_id, reason_code, trace_id, audit_event_id, recorded_at)
               VALUES ($1, $2, $3, 0, NULL, 'pending', 1, $4, $5,
                       'trigger_fixture', $6, $7, CURRENT_TIMESTAMP)""",
            transfer_transition_id,
            transfer_id,
            RESOURCE_WORKSPACE_ID,
            SYSTEM_USER_ID,
            owner_membership_id,
            uuid.uuid4(),
            action_audit_id,
        )

        snapshot_id = uuid.uuid4()
        await connection.execute(
            """INSERT INTO collaboration_authority_snapshots
               (snapshot_id, user_id, membership_id, workspace_id, role, permission,
                boundary, resource_id, resource_kind, share_id,
                ownership_transition_id, authority_generation,
                collaboration_policy_version, scope_digest, trace_id, captured_at)
               VALUES ($1, $2, $3, $4, 'owner', 'resource.view', 'share_decision',
                       $5, 'canonical_object', $6, $7, 1,
                       'collaboration-policy-v1', $8, $9, CURRENT_TIMESTAMP)""",
            snapshot_id,
            SYSTEM_USER_ID,
            owner_membership_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            share_id,
            ownership_transition_id,
            "3" * 64,
            uuid.uuid4(),
        )

        fence_id = uuid.uuid4()
        await connection.execute(
            """INSERT INTO collaboration_revocation_fences
               (fence_id, workspace_id, scope_kind, membership_id, membership_user_id,
                share_id, resource_id, resource_kind, previous_authority_generation,
                authority_generation, reason_code, actor_user_id, actor_membership_id,
                trace_id, audit_event_id, recorded_at)
               VALUES ($1, $2, 'resource_visibility', NULL, NULL, $3, $4,
                       'canonical_object', 1, 2, 'trigger_fixture', $5, $6, $7, $8,
                       CURRENT_TIMESTAMP)""",
            fence_id,
            RESOURCE_WORKSPACE_ID,
            share_id,
            resource_id,
            SYSTEM_USER_ID,
            owner_membership_id,
            uuid.uuid4(),
            action_audit_id,
        )

        thread_id = uuid.uuid4()
        thread_transition_id = uuid.uuid4()
        comment_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        comment_transition_id = uuid.uuid4()
        await connection.execute(
            """INSERT INTO collaboration_comment_threads
               (thread_id, workspace_id, resource_id, resource_kind, canvas_id,
                resource_sequence, creator_membership_id, creator_user_id,
                authority_generation, collaboration_policy_version,
                creation_request_id, creation_trace_id, creation_audit_event_id,
                created_at)
               VALUES ($1, $2, $3, 'canonical_object', NULL, 1, $4, $5, 2,
                       'collaboration-policy-v1', $6, $7, $8, CURRENT_TIMESTAMP)""",
            thread_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            owner_membership_id,
            SYSTEM_USER_ID,
            uuid.uuid4(),
            uuid.uuid4(),
            action_audit_id,
        )
        await connection.execute(
            """INSERT INTO collaboration_comment_thread_transitions
               (transition_id, thread_id, workspace_id, resource_id, resource_kind,
                sequence, previous_state, current_state, authority_generation,
                actor_user_id, actor_membership_id, reason_code, request_id,
                trace_id, audit_event_id, recorded_at)
               VALUES ($1, $2, $3, $4, 'canonical_object', 0, NULL, 'open', 2,
                       $5, $6, 'trigger_fixture', $7, $8, $9, CURRENT_TIMESTAMP)""",
            thread_transition_id,
            thread_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            SYSTEM_USER_ID,
            owner_membership_id,
            uuid.uuid4(),
            uuid.uuid4(),
            action_audit_id,
        )
        await connection.execute(
            """INSERT INTO collaboration_comments
               (comment_id, thread_id, workspace_id, resource_id, resource_kind,
                parent_comment_id, depth, thread_sequence, author_membership_id,
                author_user_id, authority_generation, collaboration_policy_version,
                creation_request_id, creation_trace_id, creation_audit_event_id,
                created_at)
               VALUES ($1, $2, $3, $4, 'canonical_object', NULL, 0, 1, $5, $6, 2,
                       'collaboration-policy-v1', $7, $8, $9, CURRENT_TIMESTAMP)""",
            comment_id,
            thread_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            owner_membership_id,
            SYSTEM_USER_ID,
            uuid.uuid4(),
            uuid.uuid4(),
            action_audit_id,
        )
        await connection.execute(
            """INSERT INTO collaboration_comment_revisions
               (revision_id, comment_id, thread_id, workspace_id, resource_id,
                resource_kind, sequence, previous_revision_id, revision_kind,
                author_membership_id, author_user_id, content, content_digest,
                authority_generation, request_id, trace_id, audit_event_id, created_at)
               VALUES ($1, $2, $3, $4, $5, 'canonical_object', 1, NULL, 'created',
                       $6, $7, 'Trigger protection fixture', $8, 2, $9, $10, $11,
                       CURRENT_TIMESTAMP)""",
            revision_id,
            comment_id,
            thread_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            owner_membership_id,
            SYSTEM_USER_ID,
            "4" * 64,
            uuid.uuid4(),
            uuid.uuid4(),
            action_audit_id,
        )
        await connection.execute(
            """INSERT INTO collaboration_comment_transitions
               (transition_id, comment_id, thread_id, workspace_id, resource_id,
                resource_kind, sequence, previous_state, current_state,
                visible_revision_id, authority_generation, actor_user_id,
                actor_membership_id, reason_code, request_id, trace_id,
                audit_event_id, recorded_at)
               VALUES ($1, $2, $3, $4, $5, 'canonical_object', 0, NULL, 'active',
                       $6, 2, $7, $8, 'trigger_fixture', $9, $10, $11,
                       CURRENT_TIMESTAMP)""",
            comment_transition_id,
            comment_id,
            thread_id,
            RESOURCE_WORKSPACE_ID,
            resource_id,
            revision_id,
            SYSTEM_USER_ID,
            owner_membership_id,
            uuid.uuid4(),
            uuid.uuid4(),
            action_audit_id,
        )

        targets = {
            "collaboration_resources": ("resource_id", resource_id),
            "collaboration_resource_ownership_transitions": (
                "transition_id",
                ownership_transition_id,
            ),
            "collaboration_resource_shares": ("share_id", share_id),
            "collaboration_resource_share_transitions": (
                "transition_id",
                share_transition_id,
            ),
            "collaboration_ownership_transfers": ("transfer_id", transfer_id),
            "collaboration_ownership_transfer_transitions": (
                "transition_id",
                transfer_transition_id,
            ),
            "collaboration_authority_snapshots": ("snapshot_id", snapshot_id),
            "collaboration_revocation_fences": ("fence_id", fence_id),
            "collaboration_comment_threads": ("thread_id", thread_id),
            "collaboration_comment_thread_transitions": (
                "transition_id",
                thread_transition_id,
            ),
            "collaboration_comments": ("comment_id", comment_id),
            "collaboration_comment_revisions": ("revision_id", revision_id),
            "collaboration_comment_transitions": (
                "transition_id",
                comment_transition_id,
            ),
        }
        assert set(targets) == set(PROTECTED_TRIGGERS)
        for table, (primary_key, identifier) in targets.items():
            assert (
                await connection.fetchval(
                    f"SELECT count(*) FROM {table} WHERE {primary_key} = $1 AND workspace_id = $2",
                    identifier,
                    RESOURCE_WORKSPACE_ID,
                )
                == 1
            )
        return targets
    finally:
        await connection.close()


async def _assert_protected_mutation_rollback(
    database_url: str,
    targets: dict[str, tuple[str, uuid.UUID]],
) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        for table, (primary_key, identifier) in targets.items():
            before_record = await connection.fetchrow(
                f"SELECT * FROM {table} WHERE {primary_key} = $1",
                identifier,
            )
            assert before_record is not None
            before = dict(before_record)
            assert before["workspace_id"] == RESOURCE_WORKSPACE_ID
            count_before = await connection.fetchval(f"SELECT count(*) FROM {table}")

            with pytest.raises(
                asyncpg.RaiseError,
                match="controlled-agent records are append-only",
            ) as update_error:
                async with connection.transaction():
                    await connection.execute(
                        f"UPDATE {table} SET workspace_id = workspace_id WHERE {primary_key} = $1",
                        identifier,
                    )
            assert update_error.value.sqlstate == "P0001"
            assert not connection.is_in_transaction()
            assert (
                dict(
                    await connection.fetchrow(
                        f"SELECT * FROM {table} WHERE {primary_key} = $1",
                        identifier,
                    )
                )
                == before
            )
            assert await connection.fetchval(f"SELECT count(*) FROM {table}") == count_before

            with pytest.raises(
                asyncpg.RaiseError,
                match="controlled-agent records are append-only",
            ) as delete_error:
                async with connection.transaction():
                    await connection.execute(
                        f"DELETE FROM {table} WHERE {primary_key} = $1",
                        identifier,
                    )
            assert delete_error.value.sqlstate == "P0001"
            assert not connection.is_in_transaction()
            assert (
                dict(
                    await connection.fetchrow(
                        f"SELECT * FROM {table} WHERE {primary_key} = $1",
                        identifier,
                    )
                )
                == before
            )
            assert await connection.fetchval(f"SELECT count(*) FROM {table}") == count_before
    finally:
        await connection.close()


async def _assert_protected_targets_present(
    database_url: str,
    targets: dict[str, tuple[str, uuid.UUID]],
) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        for table, (primary_key, identifier) in targets.items():
            row = await connection.fetchrow(
                f"SELECT * FROM {table} WHERE {primary_key} = $1",
                identifier,
            )
            assert row is not None
            assert row["workspace_id"] == RESOURCE_WORKSPACE_ID
    finally:
        await connection.close()


async def _assert_domain_event_mutation_rollback(
    database_url: str,
    workspace_id: uuid.UUID,
) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        before_record = await connection.fetchrow(
            """SELECT * FROM domain_events
               WHERE workspace_id = $1
               ORDER BY sequence
               LIMIT 1""",
            workspace_id,
        )
        assert before_record is not None
        before = dict(before_record)
        event_id = before["event_id"]
        count_before = await connection.fetchval(
            "SELECT count(*) FROM domain_events WHERE workspace_id = $1",
            workspace_id,
        )

        with pytest.raises(
            asyncpg.RaiseError,
            match="domain event evidence is append-only",
        ) as update_error:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE domain_events SET workspace_id = workspace_id WHERE event_id = $1",
                    event_id,
                )
        assert update_error.value.sqlstate == "P0001"
        assert not connection.is_in_transaction()
        assert (
            dict(
                await connection.fetchrow(
                    "SELECT * FROM domain_events WHERE event_id = $1",
                    event_id,
                )
            )
            == before
        )

        with pytest.raises(
            asyncpg.RaiseError,
            match="domain event evidence is append-only",
        ) as delete_error:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM domain_events WHERE event_id = $1",
                    event_id,
                )
        assert delete_error.value.sqlstate == "P0001"
        assert not connection.is_in_transaction()
        assert (
            dict(
                await connection.fetchrow(
                    "SELECT * FROM domain_events WHERE event_id = $1",
                    event_id,
                )
            )
            == before
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM domain_events WHERE workspace_id = $1",
                workspace_id,
            )
            == count_before
        )
    finally:
        await connection.close()


async def _assert_post_restart_insert_allowed(
    database_url: str,
    targets: dict[str, tuple[str, uuid.UUID]],
) -> None:
    source_snapshot_id = targets["collaboration_authority_snapshots"][1]
    inserted_snapshot_id = uuid.uuid4()
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        await connection.execute(
            """INSERT INTO collaboration_authority_snapshots
               (snapshot_id, user_id, membership_id, workspace_id, role, permission,
                boundary, resource_id, resource_kind, share_id,
                ownership_transition_id, authority_generation,
                collaboration_policy_version, scope_digest, trace_id, captured_at)
               SELECT $1, user_id, membership_id, workspace_id, role, permission,
                      boundary, resource_id, resource_kind, share_id,
                      ownership_transition_id, authority_generation,
                      collaboration_policy_version, scope_digest, $2, CURRENT_TIMESTAMP
               FROM collaboration_authority_snapshots
               WHERE snapshot_id = $3""",
            inserted_snapshot_id,
            uuid.uuid4(),
            source_snapshot_id,
        )
        assert (
            await connection.fetchval(
                """SELECT count(*) FROM collaboration_authority_snapshots
                   WHERE snapshot_id = $1 AND workspace_id = $2""",
                inserted_snapshot_id,
                RESOURCE_WORKSPACE_ID,
            )
            == 1
        )
    finally:
        await connection.close()


def test_postgresql_0023_preserves_exact_predecessor_registries_and_cycles(
    postgres_migration_database_url: str,
) -> None:
    config = _config(postgres_migration_database_url)
    command.upgrade(config, "20260725_0022")
    workspace_id = asyncio.run(
        _seed_registry_rows(
            postgres_migration_database_url,
            MIGRATION_0023._REGISTRIES_BEFORE,
        )
    )

    command.upgrade(config, "20260725_0023")
    asyncio.run(
        _assert_protected_trigger_catalog(
            postgres_migration_database_url,
            PROTECTED_0023_TABLES,
        )
    )
    asyncio.run(
        _assert_seeded_rows(
            postgres_migration_database_url,
            MIGRATION_0023._REGISTRIES_BEFORE,
        )
    )
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0023,
            MIGRATION_0023._REGISTRIES_AFTER,
        )
    )
    asyncio.run(_assert_invalid_event_rejected(postgres_migration_database_url, workspace_id))

    command.downgrade(config, "20260725_0022")
    asyncio.run(
        _assert_protected_trigger_catalog(
            postgres_migration_database_url,
            frozenset(),
        )
    )
    asyncio.run(
        _assert_seeded_rows(
            postgres_migration_database_url,
            MIGRATION_0023._REGISTRIES_BEFORE,
        )
    )
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0023,
            MIGRATION_0023._REGISTRIES_BEFORE,
        )
    )

    command.upgrade(config, "20260725_0023")
    asyncio.run(
        _assert_protected_trigger_catalog(
            postgres_migration_database_url,
            PROTECTED_0023_TABLES,
        )
    )
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0023,
            MIGRATION_0023._REGISTRIES_AFTER,
        )
    )


def test_postgresql_0023_backfills_exact_uuid_and_null_matrix_and_cycles(
    postgres_migration_database_url: str,
) -> None:
    config = _config(postgres_migration_database_url)
    command.upgrade(config, "20260725_0022")
    asyncio.run(_seed_resource_rows(postgres_migration_database_url))

    command.upgrade(config, "20260725_0023")
    asyncio.run(_assert_resource_sources(postgres_migration_database_url))
    asyncio.run(_assert_resource_backfill(postgres_migration_database_url))

    command.downgrade(config, "20260725_0022")
    asyncio.run(_assert_resource_sources(postgres_migration_database_url))

    command.upgrade(config, "20260725_0023")
    asyncio.run(_assert_resource_sources(postgres_migration_database_url))
    asyncio.run(_assert_resource_backfill(postgres_migration_database_url))


def test_postgresql_0024_consumes_0023_registries_without_widening_and_cycles(
    postgres_migration_database_url: str,
) -> None:
    config = _config(postgres_migration_database_url)
    command.upgrade(config, "20260725_0023")
    asyncio.run(
        _assert_protected_trigger_catalog(
            postgres_migration_database_url,
            PROTECTED_0023_TABLES,
        )
    )
    workspace_id = asyncio.run(
        _seed_registry_rows(
            postgres_migration_database_url,
            MIGRATION_0024._REGISTRIES_BEFORE,
        )
    )

    command.upgrade(config, "20260725_0024")
    asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    asyncio.run(
        _assert_seeded_rows(
            postgres_migration_database_url,
            MIGRATION_0024._REGISTRIES_BEFORE,
        )
    )
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0024,
            MIGRATION_0024._REGISTRIES_AFTER,
        )
    )
    asyncio.run(_assert_invalid_event_rejected(postgres_migration_database_url, workspace_id))

    command.downgrade(config, "20260725_0023")
    asyncio.run(
        _assert_protected_trigger_catalog(
            postgres_migration_database_url,
            PROTECTED_0023_TABLES,
        )
    )
    asyncio.run(
        _assert_seeded_rows(
            postgres_migration_database_url,
            MIGRATION_0024._REGISTRIES_BEFORE,
        )
    )
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0024,
            MIGRATION_0024._REGISTRIES_BEFORE,
        )
    )

    command.upgrade(config, "20260725_0024")
    asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0024,
            MIGRATION_0024._REGISTRIES_AFTER,
        )
    )


def test_postgresql_all_13_protected_tables_bind_existing_function_and_rollback_mutations(
    postgres_migration_database_url: str,
) -> None:
    config = _config(postgres_migration_database_url)
    command.upgrade(config, "20260725_0022")
    asyncio.run(_seed_resource_rows(postgres_migration_database_url))
    command.upgrade(config, "20260725_0024")

    asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    event_workspace_id = asyncio.run(
        _seed_registry_rows(
            postgres_migration_database_url,
            MIGRATION_0024._REGISTRIES_AFTER,
        )
    )
    for migration in (MIGRATION_0023, MIGRATION_0024):
        asyncio.run(
            _assert_domain_event_fallback_probe(
                postgres_migration_database_url,
                migration,
                event_workspace_id,
            )
        )
    targets = asyncio.run(_seed_protected_trigger_rows(postgres_migration_database_url))
    asyncio.run(
        _assert_protected_mutation_rollback(
            postgres_migration_database_url,
            targets,
        )
    )
    asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))


def test_postgresql_trigger_identity_and_mutations_survive_same_database_restart(
    postgres_migration_database_url: str,
) -> None:
    if os.getenv("OPENCANVAS_RUN_POSTGRES_RESTART_TEST") != "1":
        pytest.skip("same-database PostgreSQL restart validation is opt-in")

    config = _config(postgres_migration_database_url)
    command.upgrade(config, "20260725_0022")
    asyncio.run(_seed_resource_rows(postgres_migration_database_url))
    command.upgrade(config, "20260725_0024")
    event_workspace_id = asyncio.run(
        _seed_registry_rows(
            postgres_migration_database_url,
            MIGRATION_0024._REGISTRIES_AFTER,
        )
    )
    targets = asyncio.run(_seed_protected_trigger_rows(postgres_migration_database_url))
    catalog_before = asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    asyncio.run(
        _assert_protected_mutation_rollback(
            postgres_migration_database_url,
            targets,
        )
    )
    asyncio.run(
        _assert_domain_event_mutation_rollback(
            postgres_migration_database_url,
            event_workspace_id,
        )
    )

    subprocess.run(
        [
            "wsl.exe",
            "-d",
            "Ubuntu-24.04",
            "-u",
            "root",
            "--",
            "systemctl",
            "restart",
            "postgresql",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    subprocess.run(
        [
            "wsl.exe",
            "-d",
            "Ubuntu-24.04",
            "-u",
            "root",
            "--",
            "systemctl",
            "is-active",
            "--quiet",
            "postgresql",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    catalog_after = asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    assert catalog_after == catalog_before
    asyncio.run(_assert_protected_targets_present(postgres_migration_database_url, targets))
    asyncio.run(_assert_post_restart_insert_allowed(postgres_migration_database_url, targets))
    asyncio.run(
        _assert_protected_mutation_rollback(
            postgres_migration_database_url,
            targets,
        )
    )
    asyncio.run(
        _assert_domain_event_mutation_rollback(
            postgres_migration_database_url,
            event_workspace_id,
        )
    )


async def _assert_clean_head(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "20260725_0025"
        )
        assert int(await connection.fetchval("SHOW server_version_num")) // 10_000 == 17
        assert (
            await connection.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            == "0.8.5"
        )
        tables = {
            row["tablename"]
            for row in await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        assert {
            "workspaces",
            "canonical_objects",
            "domain_events",
            "collaboration_request_identities",
            "collaboration_audit_events",
            "collaboration_resources",
            "collaboration_comment_threads",
            "bounded_agent_workflow_bindings",
        } <= tables
        triggers = {
            row["tgname"]
            for row in await connection.fetch(
                """SELECT tg.tgname
                   FROM pg_trigger tg
                   JOIN pg_class t ON t.oid = tg.tgrelid
                   WHERE NOT tg.tgisinternal AND t.relname IN (
                       'domain_events',
                       'collaboration_resources',
                       'collaboration_comments'
                   )"""
            )
        }
        assert {
            "trg_domain_events_mutation_blocked",
            "trg_collaboration_resources_mutation_blocked",
            "trg_collaboration_comments_mutation_blocked",
        } <= triggers
        assert await connection.fetchval(
            """SELECT count(*) >= 1
               FROM pg_constraint c
               JOIN pg_class t ON t.oid = c.conrelid
               WHERE c.contype = 'f'
                 AND t.relname IN ('canonical_objects', 'domain_events')
                 AND pg_get_constraintdef(c.oid) LIKE '%workspace%'"""
        )
        assert {
            row["column_name"]: row["udt_name"]
            for row in await connection.fetch(
                """SELECT column_name, udt_name
                   FROM information_schema.columns
                   WHERE table_schema = 'public'
                     AND table_name = 'collaboration_resources'
                     AND column_name = ANY($1::text[])""",
                [
                    "canvas_id",
                    "canonical_object_id",
                    "workflow_definition_id",
                    "agent_id",
                    "target_user_id",
                ],
            )
        } == {
            "canvas_id": "uuid",
            "canonical_object_id": "uuid",
            "workflow_definition_id": "uuid",
            "agent_id": "uuid",
            "target_user_id": "uuid",
        }
    finally:
        await connection.close()


def test_postgresql_clean_chain_reaches_0025_and_cycles_final_revision(
    postgres_migration_database_url: str,
) -> None:
    config = _config(postgres_migration_database_url)
    command.upgrade(config, "head")
    asyncio.run(_assert_clean_head(postgres_migration_database_url))
    asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    asyncio.run(_assert_clean_model_catalog(postgres_migration_database_url))
    head_catalog = asyncio.run(_schema_catalog_identity(postgres_migration_database_url))
    asyncio.run(
        _assert_registry_constraints(
            postgres_migration_database_url,
            MIGRATION_0024,
            MIGRATION_0024._REGISTRIES_AFTER,
        )
    )

    command.downgrade(config, "20260725_0024")
    command.upgrade(config, "head")
    asyncio.run(_assert_clean_head(postgres_migration_database_url))
    asyncio.run(_assert_protected_trigger_catalog(postgres_migration_database_url))
    asyncio.run(_assert_clean_model_catalog(postgres_migration_database_url))
    assert asyncio.run(_schema_catalog_identity(postgres_migration_database_url)) == head_catalog
