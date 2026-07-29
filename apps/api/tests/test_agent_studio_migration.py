from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

AGENT_STUDIO_TABLES = {
    "bounded_agent_identities",
    "bounded_agent_lifecycle_states",
    "bounded_agent_versions",
    "bounded_agent_version_states",
    "bounded_agent_workflow_bindings",
    "bounded_agent_capability_requirements",
    "bounded_agent_validation_reports",
    "bounded_agent_activation_requests",
    "bounded_agent_activation_decisions",
    "bounded_agent_invocations",
    "bounded_agent_proposals",
    "bounded_agent_proposal_decisions",
    "bounded_agent_evaluations",
    "bounded_communication_profiles",
    "bounded_communication_profile_versions",
    "bounded_communication_revisions",
    "bounded_communication_revision_decisions",
}


def _config(database_path: Path) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_agent_studio_migration_cycle_scope_and_append_only(tmp_path: Path) -> None:
    database_path = tmp_path / "agent-studio.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0020")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0020",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= AGENT_STUDIO_TABLES
        profile_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('bounded_communication_profiles')")
        }
        assert {"user_id", "workspace_id", "canvas_id"} <= profile_columns
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND name LIKE 'trg_bounded_%'"
            )
        }
        assert {
            f"trg_{table}_{operation}_blocked"
            for table in (
                "bounded_agent_identities",
                "bounded_agent_versions",
                "bounded_agent_validation_reports",
                "bounded_agent_activation_decisions",
                "bounded_agent_evaluations",
            )
            for operation in ("update", "delete")
        } <= triggers

        user_id = uuid.uuid4().hex
        workspace_id = uuid.uuid4().hex
        canvas_id = uuid.uuid4().hex
        agent_id = uuid.uuid4().hex
        connection.execute(
            """INSERT INTO users
               (id, email, email_normalized, password_hash, display_name, email_verified)
               VALUES (?, 'agent@example.invalid', 'agent@example.invalid',
                       'test-only', 'Agent migration', 1)""",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO workspaces (id, owner_id, name) VALUES (?, ?, 'Agent migration')",
            (workspace_id, user_id),
        )
        connection.execute(
            "INSERT INTO canvases (id, workspace_id, name) VALUES (?, ?, 'Agent migration')",
            (canvas_id, workspace_id),
        )
        connection.execute(
            """INSERT INTO bounded_agent_identities
               (agent_id, user_id, workspace_id, canvas_id, schema_version, kind,
                display_name, description, idempotency_key, request_digest,
                created_by_user_id, trace_id, created_at)
               VALUES (?, ?, ?, ?, 'bounded-agent-studio-v1', 'workflow_assistant',
                       'Immutable', 'Bounded', 'migration-key', ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                agent_id,
                user_id,
                workspace_id,
                canvas_id,
                "a" * 64,
                user_id,
                uuid.uuid4().hex,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE bounded_agent_identities SET display_name = 'Changed' WHERE agent_id = ?",
                (agent_id,),
            )

    command.downgrade(config, "20260725_0019")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0019",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert not (AGENT_STUDIO_TABLES & tables)

    command.upgrade(config, "20260725_0020")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0020",
        )


def test_agent_studio_is_sole_head_and_postgresql_ddl_compiles() -> None:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["20260726_0028"]

    buffer = io.StringIO()
    offline = Config(api_directory / "alembic.ini", output_buffer=buffer)
    offline.set_main_option("script_location", str(api_directory / "alembic"))
    offline.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(offline, "20260725_0019:20260725_0020", sql=True)
    ddl = buffer.getvalue()
    assert "CREATE TABLE bounded_agent_identities" in ddl
    assert "CREATE TABLE bounded_agent_activation_decisions" in ddl
    assert "CREATE TABLE bounded_communication_profiles" in ddl
    assert "CREATE TRIGGER trg_bounded_agent_versions_mutation_blocked" in ddl
