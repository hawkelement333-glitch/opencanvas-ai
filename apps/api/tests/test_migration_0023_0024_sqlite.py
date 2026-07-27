from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

SYSTEM_USER_ID = "00000000000040008000000000000001"
RESOURCE_WORKSPACE_ID = "10000000000040008000000000000023"
RESOURCE_CANVAS_ID = "20000000000040008000000000000023"
RESOURCE_OBJECT_ID = "30000000000040008000000000000023"
RESOURCE_WORKFLOW_ID = "40000000000040008000000000000023"
RESOURCE_AGENT_ID = "50000000000040008000000000000023"
RESOURCE_WORKFLOW_TRACE_ID = "60000000000040008000000000000023"
RESOURCE_AGENT_TRACE_ID = "70000000000040008000000000000023"
ZERO_UUID = "0" * 32


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


def _config(database_path: Path) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def _install_sqlite_append_only_guard(
    connection: Connection,
    migration: ModuleType,
    table: str,
) -> None:
    original_op = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        migration._protect(table)
    finally:
        migration.op = original_op


def test_sqlite_all_thirteen_append_only_helpers_allow_insert_and_block_mutation() -> None:
    migrations = (MIGRATION_0023, MIGRATION_0024)
    tables = tuple(table for migration in migrations for table in migration.NEW_TABLES)
    assert len(tables) == len(set(tables)) == 13

    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            for migration in migrations:
                for table in migration.NEW_TABLES:
                    connection.exec_driver_sql(
                        f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)'
                    )
                    _install_sqlite_append_only_guard(connection, migration, table)
                    connection.exec_driver_sql(
                        f'INSERT INTO "{table}" (id, marker) VALUES (1, ?)',
                        ("original",),
                    )
            connection.commit()

            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            expected_triggers = {
                f"trg_{table}_{operation}_blocked"
                for table in tables
                for operation in ("update", "delete")
            }
            assert triggers == expected_triggers

            for table in tables:
                before = connection.exec_driver_sql(
                    f'SELECT id, marker FROM "{table}" WHERE id = 1'
                ).one()
                for statement in (
                    f'UPDATE "{table}" SET marker = marker WHERE id = 1',
                    f'DELETE FROM "{table}" WHERE id = 1',
                ):
                    with pytest.raises(
                        IntegrityError,
                        match=f"{table} records are append-only",
                    ):
                        connection.exec_driver_sql(statement)
                    connection.rollback()
                    assert (
                        connection.exec_driver_sql(
                            f'SELECT id, marker FROM "{table}" WHERE id = 1'
                        ).one()
                        == before
                    )
                    assert (
                        connection.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar_one()
                        == 1
                    )
    finally:
        engine.dispose()


def _seed_registry_rows(
    database_path: Path,
    registries: dict[str, tuple[str, ...]],
) -> str:
    workspace_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO workspaces (id, name, owner_id) VALUES (?, 'Registry workspace', ?)",
            (workspace_id, SYSTEM_USER_ID),
        )
        event_types = registries["ck_domain_events_type"]
        subject_kinds = registries["ck_domain_events_subject_kind"]
        for sequence, event_type in enumerate(event_types, start=1):
            connection.execute(
                """INSERT INTO domain_events
                   (event_id, user_id, workspace_id, canvas_id, scope_id, sequence,
                    event_type, registry_version, schema_version, subject_kind, subject_id,
                    actor_user_id, source_identity, occurred_at, payload, payload_digest,
                    request_digest, trace_id)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, 'mobius-domain-events-v1',
                           'domain-event-v1', ?, ?, ?, ?, CURRENT_TIMESTAMP, '{}', ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    SYSTEM_USER_ID,
                    workspace_id,
                    uuid.uuid4().hex,
                    sequence,
                    event_type,
                    subject_kinds[(sequence - 1) % len(subject_kinds)],
                    uuid.uuid4().hex,
                    SYSTEM_USER_ID,
                    f"registry-seed-{sequence}",
                    "a" * 64,
                    "b" * 64,
                    uuid.uuid4().hex,
                ),
            )
        result_kinds = registries["ck_collaboration_request_result_kind"]
        for ordinal, operation in enumerate(registries["ck_collaboration_request_operation"]):
            connection.execute(
                """INSERT INTO collaboration_request_identities
                   (request_id, actor_user_id, workspace_id, operation, idempotency_key,
                    request_digest, result_kind, result_id, trace_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    uuid.uuid4().hex,
                    SYSTEM_USER_ID,
                    workspace_id,
                    operation,
                    f"registry-request-{ordinal}",
                    "c" * 64,
                    result_kinds[ordinal % len(result_kinds)],
                    uuid.uuid4().hex,
                    uuid.uuid4().hex,
                ),
            )
        for ordinal, subject_kind in enumerate(registries["ck_collaboration_audit_subject_kind"]):
            connection.execute(
                """INSERT INTO collaboration_audit_events
                   (audit_event_id, workspace_id, actor_user_id, subject_kind, subject_id,
                    action, outcome, reason_code, metadata_digest, trace_id, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'succeeded', 'registry_seed', ?, ?,
                           CURRENT_TIMESTAMP)""",
                (
                    uuid.uuid4().hex,
                    workspace_id,
                    SYSTEM_USER_ID,
                    subject_kind,
                    uuid.uuid4().hex,
                    f"registry.seed.{ordinal}",
                    "d" * 64,
                    uuid.uuid4().hex,
                ),
            )
        connection.commit()
    return workspace_id


def _seed_resource_rows(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """INSERT INTO workspaces (id, name, owner_id)
               VALUES (?, 'Resource backfill workspace', ?)""",
            (RESOURCE_WORKSPACE_ID, SYSTEM_USER_ID),
        )
        connection.execute(
            """INSERT INTO canvases (id, workspace_id, name)
               VALUES (?, ?, 'Resource backfill canvas')""",
            (RESOURCE_CANVAS_ID, RESOURCE_WORKSPACE_ID),
        )
        connection.execute(
            """INSERT INTO canonical_objects
               (id, workspace_id, object_type, lifecycle_state)
               VALUES (?, ?, 'note', 'active')""",
            (RESOURCE_OBJECT_ID, RESOURCE_WORKSPACE_ID),
        )
        connection.execute(
            """INSERT INTO controlled_workflow_definitions
               (definition_id, user_id, workspace_id, canvas_id, schema_version, kind,
                name, description, created_by_user_id, trace_id, created_at)
               VALUES (?, ?, ?, ?, 'controlled-workflow-v1', 'grounded_answer',
                       'Resource backfill workflow', '', ?, ?, CURRENT_TIMESTAMP)""",
            (
                RESOURCE_WORKFLOW_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKFLOW_TRACE_ID,
            ),
        )
        connection.execute(
            """INSERT INTO bounded_agent_identities
               (agent_id, user_id, workspace_id, canvas_id, schema_version, kind,
                display_name, description, idempotency_key, request_digest,
                created_by_user_id, trace_id, created_at)
               VALUES (?, ?, ?, ?, 'bounded-agent-studio-v1', 'workflow_assistant',
                       'Resource backfill agent', 'Bounded', 'resource-backfill-agent',
                       ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                RESOURCE_AGENT_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
                "a" * 64,
                SYSTEM_USER_ID,
                RESOURCE_AGENT_TRACE_ID,
            ),
        )
        connection.commit()


def _assert_resource_sources(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM canvases WHERE id = ? AND workspace_id = ?",
            (RESOURCE_CANVAS_ID, RESOURCE_WORKSPACE_ID),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM canonical_objects WHERE id = ? AND workspace_id = ?",
            (RESOURCE_OBJECT_ID, RESOURCE_WORKSPACE_ID),
        ).fetchone() == (1,)
        assert connection.execute(
            """SELECT count(*) FROM controlled_workflow_definitions
               WHERE definition_id = ? AND user_id = ?
                 AND workspace_id = ? AND canvas_id = ?""",
            (
                RESOURCE_WORKFLOW_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
            ),
        ).fetchone() == (1,)
        assert connection.execute(
            """SELECT count(*) FROM bounded_agent_identities
               WHERE agent_id = ? AND user_id = ?
                 AND workspace_id = ? AND canvas_id = ?""",
            (
                RESOURCE_AGENT_ID,
                SYSTEM_USER_ID,
                RESOURCE_WORKSPACE_ID,
                RESOURCE_CANVAS_ID,
            ),
        ).fetchone() == (1,)


def _assert_resource_backfill(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        rows = connection.execute(
            """SELECT resource_kind, resource_id, workspace_id, canvas_id,
                      canonical_object_id, workflow_definition_id, agent_id,
                      target_user_id, creator_user_id, creation_trace_id
               FROM collaboration_resources
               WHERE workspace_id = ?
               ORDER BY resource_kind""",
            (RESOURCE_WORKSPACE_ID,),
        ).fetchall()
        actual = {row[0]: row[1:] for row in rows}
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
        assert ZERO_UUID not in {
            value for values in actual.values() for value in values if value is not None
        }

        transitions = connection.execute(
            """SELECT resource_id, resource_kind, workspace_id, sequence,
                      previous_owner_kind, current_owner_kind,
                      current_owner_membership_id, current_owner_user_id,
                      visibility_policy, authority_generation, actor_user_id,
                      actor_membership_id, reason_code, trace_id
               FROM collaboration_resource_ownership_transitions
               WHERE workspace_id = ?
               ORDER BY resource_kind""",
            (RESOURCE_WORKSPACE_ID,),
        ).fetchall()
        assert len(transitions) == 4
        expected_traces = {
            "agent": RESOURCE_AGENT_TRACE_ID,
            "canonical_object": RESOURCE_OBJECT_ID,
            "canvas": RESOURCE_CANVAS_ID,
            "workflow": RESOURCE_WORKFLOW_TRACE_ID,
        }
        for transition in transitions:
            kind = transition[1]
            assert transition == (
                actual[kind][0],
                kind,
                RESOURCE_WORKSPACE_ID,
                0,
                None,
                "workspace",
                None,
                None,
                "private",
                1,
                SYSTEM_USER_ID,
                None,
                "resource_owner_backfill",
                expected_traces[kind],
            )

        unknown_canvas_id = uuid.uuid4().hex
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                """INSERT INTO collaboration_resources
                   (resource_id, workspace_id, resource_kind, canvas_id,
                    canonical_object_id, workflow_definition_id, agent_id,
                    target_user_id, creator_user_id, creation_trace_id, created_at)
                   VALUES (?, ?, 'canvas', ?, NULL, NULL, NULL, NULL,
                           ?, ?, CURRENT_TIMESTAMP)""",
                (
                    unknown_canvas_id,
                    RESOURCE_WORKSPACE_ID,
                    unknown_canvas_id,
                    SYSTEM_USER_ID,
                    uuid.uuid4().hex,
                ),
            )


def _assert_registry_constraints(
    database_path: Path,
    migration: ModuleType,
    expected: dict[str, tuple[str, ...]],
) -> None:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        inspector = inspect(engine)
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
            checks = {
                item["name"]: item["sqltext"] for item in inspector.get_check_constraints(table)
            }
            assert constraint in checks
            assert (
                migration._parse_check_values(
                    checks[constraint],
                    column=migration._CLOSED_CHECK_COLUMNS[constraint],
                )
                == expected[constraint]
            )
    finally:
        engine.dispose()


def _assert_seeded_rows(
    database_path: Path,
    registries: dict[str, tuple[str, ...]],
) -> None:
    with sqlite3.connect(database_path) as connection:
        assert {
            row[0] for row in connection.execute("SELECT event_type FROM domain_events")
        } == set(registries["ck_domain_events_type"])
        assert {
            row[0] for row in connection.execute("SELECT subject_kind FROM domain_events")
        } == set(registries["ck_domain_events_subject_kind"])
        assert {
            row[0]
            for row in connection.execute("SELECT operation FROM collaboration_request_identities")
        } == set(registries["ck_collaboration_request_operation"])
        assert {
            row[0]
            for row in connection.execute(
                "SELECT result_kind FROM collaboration_request_identities"
            )
        } == set(registries["ck_collaboration_request_result_kind"])
        assert {
            row[0]
            for row in connection.execute("SELECT subject_kind FROM collaboration_audit_events")
        } == set(registries["ck_collaboration_audit_subject_kind"])


def _assert_invalid_event_rejected(database_path: Path, workspace_id: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="ck_domain_events_type"):
            connection.execute(
                """INSERT INTO domain_events
                   (event_id, user_id, workspace_id, canvas_id, scope_id, sequence,
                    event_type, registry_version, schema_version, subject_kind, subject_id,
                    actor_user_id, source_identity, occurred_at, payload, payload_digest,
                    request_digest, trace_id)
                   VALUES (?, ?, ?, NULL, ?, 1000, 'unapproved.event',
                           'mobius-domain-events-v1', 'domain-event-v1',
                           'canonical_resource', ?, ?, 'invalid-registry-seed',
                           CURRENT_TIMESTAMP, '{}', ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    SYSTEM_USER_ID,
                    workspace_id,
                    uuid.uuid4().hex,
                    uuid.uuid4().hex,
                    SYSTEM_USER_ID,
                    "e" * 64,
                    "f" * 64,
                    uuid.uuid4().hex,
                ),
            )


def test_sqlite_0023_preserves_exact_predecessor_registries_and_cycles(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration-0023.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0022")
    workspace_id = _seed_registry_rows(database_path, MIGRATION_0023._REGISTRIES_BEFORE)

    command.upgrade(config, "20260725_0023")
    _assert_seeded_rows(database_path, MIGRATION_0023._REGISTRIES_BEFORE)
    _assert_registry_constraints(
        database_path,
        MIGRATION_0023,
        MIGRATION_0023._REGISTRIES_AFTER,
    )
    _assert_invalid_event_rejected(database_path, workspace_id)

    command.downgrade(config, "20260725_0022")
    _assert_seeded_rows(database_path, MIGRATION_0023._REGISTRIES_BEFORE)
    _assert_registry_constraints(
        database_path,
        MIGRATION_0023,
        MIGRATION_0023._REGISTRIES_BEFORE,
    )

    command.upgrade(config, "20260725_0023")
    _assert_seeded_rows(database_path, MIGRATION_0023._REGISTRIES_BEFORE)
    _assert_registry_constraints(
        database_path,
        MIGRATION_0023,
        MIGRATION_0023._REGISTRIES_AFTER,
    )


def test_sqlite_0023_backfills_equivalent_uuid_and_null_matrix_and_cycles(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration-0023-resource-backfill.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0022")
    _seed_resource_rows(database_path)

    command.upgrade(config, "20260725_0023")
    _assert_resource_sources(database_path)
    _assert_resource_backfill(database_path)

    command.downgrade(config, "20260725_0022")
    _assert_resource_sources(database_path)

    command.upgrade(config, "20260725_0023")
    _assert_resource_sources(database_path)
    _assert_resource_backfill(database_path)


def test_sqlite_0024_consumes_0023_registries_without_widening_and_cycles(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration-0024.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0023")
    workspace_id = _seed_registry_rows(database_path, MIGRATION_0024._REGISTRIES_BEFORE)

    command.upgrade(config, "20260725_0024")
    _assert_seeded_rows(database_path, MIGRATION_0024._REGISTRIES_BEFORE)
    _assert_registry_constraints(
        database_path,
        MIGRATION_0024,
        MIGRATION_0024._REGISTRIES_AFTER,
    )
    _assert_invalid_event_rejected(database_path, workspace_id)

    command.downgrade(config, "20260725_0023")
    _assert_seeded_rows(database_path, MIGRATION_0024._REGISTRIES_BEFORE)
    _assert_registry_constraints(
        database_path,
        MIGRATION_0024,
        MIGRATION_0024._REGISTRIES_BEFORE,
    )

    command.upgrade(config, "20260725_0024")
    _assert_seeded_rows(database_path, MIGRATION_0024._REGISTRIES_BEFORE)
    _assert_registry_constraints(
        database_path,
        MIGRATION_0024,
        MIGRATION_0024._REGISTRIES_AFTER,
    )
