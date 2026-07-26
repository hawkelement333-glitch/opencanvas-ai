from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

WORKFLOW_TABLES = {
    "controlled_workflow_definitions",
    "controlled_workflow_versions",
    "controlled_workflow_version_states",
    "controlled_workflow_steps",
    "controlled_workflow_dependencies",
    "controlled_workflow_executions",
    "controlled_workflow_plan_snapshots",
    "controlled_workflow_execution_transitions",
    "controlled_workflow_step_executions",
    "controlled_workflow_step_transitions",
    "controlled_workflow_step_attempts",
    "controlled_workflow_evidence_links",
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


def test_workflow_migration_upgrade_downgrade_reupgrade_and_append_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "controlled-workflows.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0019")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0019",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= WORKFLOW_TABLES
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'ix_%workflow_%'"
            )
        }
        assert {
            "ix_workflow_execution_scope_time",
            "ix_workflow_step_execution_run",
            "ix_workflow_evidence_execution",
        } <= indexes
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND name LIKE 'trg_controlled_workflow_%'"
            )
        }
        assert {
            f"trg_{table}_{operation}_blocked"
            for table in (
                "controlled_workflow_definitions",
                "controlled_workflow_versions",
                "controlled_workflow_plan_snapshots",
                "controlled_workflow_step_attempts",
            )
            for operation in ("update", "delete")
        } <= triggers

        user_id = uuid.uuid4().hex
        workspace_id = uuid.uuid4().hex
        canvas_id = uuid.uuid4().hex
        definition_id = uuid.uuid4().hex
        connection.execute(
            """INSERT INTO users
               (id, email, email_normalized, password_hash, display_name, email_verified)
               VALUES (?, 'workflow@example.invalid', 'workflow@example.invalid',
                       'test-only', 'Workflow migration', 1)""",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO workspaces (id, owner_id, name) VALUES (?, ?, 'Workflow migration')",
            (workspace_id, user_id),
        )
        connection.execute(
            "INSERT INTO canvases (id, workspace_id, name) VALUES (?, ?, 'Workflow migration')",
            (canvas_id, workspace_id),
        )
        connection.execute(
            """INSERT INTO controlled_workflow_definitions
               (definition_id, user_id, workspace_id, canvas_id, schema_version, kind,
                name, description, created_by_user_id, trace_id, created_at)
               VALUES (?, ?, ?, ?, 'controlled-workflow-v1', 'grounded_answer',
                       'Immutable', '', ?, ?, CURRENT_TIMESTAMP)""",
            (
                definition_id,
                user_id,
                workspace_id,
                canvas_id,
                user_id,
                uuid.uuid4().hex,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE controlled_workflow_definitions SET name = 'Changed' "
                "WHERE definition_id = ?",
                (definition_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM controlled_workflow_definitions WHERE definition_id = ?",
                (definition_id,),
            )

    command.downgrade(config, "20260725_0018")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0018",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert not (WORKFLOW_TABLES & tables)

    command.upgrade(config, "20260725_0019")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0019",
        )


def test_workflow_migration_is_sole_head_and_postgresql_ddl_compiles() -> None:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0025"]

    buffer = io.StringIO()
    offline = Config(api_directory / "alembic.ini", output_buffer=buffer)
    offline.set_main_option("script_location", str(api_directory / "alembic"))
    offline.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(offline, "20260725_0018:20260725_0019", sql=True)
    ddl = buffer.getvalue()
    assert "CREATE TABLE controlled_workflow_definitions" in ddl
    assert "CREATE TABLE controlled_workflow_step_attempts" in ddl
    assert "CREATE TRIGGER trg_controlled_workflow_versions_mutation_blocked" in ddl
