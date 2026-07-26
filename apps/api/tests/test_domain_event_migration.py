from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def _config(database_path: Path) -> Config:
    api_directory = Path(__file__).parents[1]
    config = Config(str(api_directory / "alembic.ini"))
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_living_state_migration_cycle_and_append_only_guards(tmp_path: Path) -> None:
    database_path = tmp_path / "living-state.db"
    config = _config(database_path)
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0025",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "workspace_event_sequences",
            "domain_events",
            "domain_event_provenance",
            "domain_event_outbox",
            "domain_event_delivery_attempts",
            "domain_activity_entries",
        } <= tables
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND name LIKE 'trg_domain_%_blocked'"
            )
        }
        assert {
            "trg_domain_events_update_blocked",
            "trg_domain_events_delete_blocked",
            "trg_domain_event_provenance_update_blocked",
            "trg_domain_event_provenance_delete_blocked",
            "trg_domain_event_delivery_attempts_update_blocked",
            "trg_domain_event_delivery_attempts_delete_blocked",
            "trg_domain_activity_entries_update_blocked",
            "trg_domain_activity_entries_delete_blocked",
            "trg_domain_event_outbox_identity_update_blocked",
            "trg_domain_event_outbox_delete_blocked",
        } <= triggers

        connection.execute("PRAGMA foreign_keys=OFF")
        event_id = "1" * 32
        user_id = "2" * 32
        workspace_id = "3" * 32
        connection.execute(
            "INSERT INTO domain_events "
            "(event_id, user_id, workspace_id, canvas_id, scope_id, sequence, "
            "event_type, registry_version, schema_version, subject_kind, subject_id, "
            "actor_user_id, source_identity, occurred_at, payload, payload_digest, "
            "request_digest, trace_id) VALUES "
            "(?, ?, ?, NULL, ?, 1, 'canonical.resource.created', "
            "'mobius-domain-events-v1', 'domain-event-v1', 'canonical_resource', "
            "?, ?, 'migration-test', '2026-07-25 00:00:00', '{}', ?, ?, ?)",
            (
                event_id,
                user_id,
                workspace_id,
                workspace_id,
                "4" * 32,
                user_id,
                "a" * 64,
                "b" * 64,
                "5" * 32,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="domain event evidence is append-only"):
            connection.execute(
                "UPDATE domain_events SET event_type = 'canonical.resource.updated' "
                "WHERE event_id = ?",
                (event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="domain event evidence is append-only"):
            connection.execute("DELETE FROM domain_events WHERE event_id = ?", (event_id,))
        outbox_id = "6" * 32
        connection.execute(
            "INSERT INTO domain_event_outbox "
            "(outbox_id, event_id, user_id, workspace_id, delivery_state, eligible_at, "
            "attempt_count, max_attempts, lease_generation) VALUES "
            "(?, ?, ?, ?, 'pending', '2026-07-25 00:00:00', 0, 3, 0)",
            (outbox_id, event_id, user_id, workspace_id),
        )
        connection.execute(
            "UPDATE domain_event_outbox SET failure_classification = 'consumer_retryable' "
            "WHERE outbox_id = ?",
            (outbox_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="outbox identity is immutable"):
            connection.execute(
                "UPDATE domain_event_outbox SET max_attempts = 4 WHERE outbox_id = ?",
                (outbox_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="outbox history is retained"):
            connection.execute(
                "DELETE FROM domain_event_outbox WHERE outbox_id = ?",
                (outbox_id,),
            )

    command.downgrade(config, "20260725_0016")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0016",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "domain_events" not in tables
        assert "canonical_graph_relationships" in tables

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0025",
        )


def test_living_state_postgresql_ddl_compiles_offline() -> None:
    buffer = io.StringIO()
    api_directory = Path(__file__).parents[1]
    config = Config(str(api_directory / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(config, "20260725_0016:20260725_0017", sql=True)
    ddl = buffer.getvalue()
    assert "CREATE TABLE domain_events" in ddl
    assert "CREATE TABLE domain_event_outbox" in ddl
    assert "reject_domain_events_mutation" in ddl
    assert "reject_domain_event_outbox_identity_mutation" in ddl
