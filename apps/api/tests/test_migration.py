from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from opencanvas_api.core.config import get_settings


def test_initial_migration_upgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "canvases",
        "nodes",
        "edges",
        "ai_requests",
        "ai_responses",
        "documents",
        "document_files",
        "canvas_document_nodes",
        "document_chunks",
        "document_embeddings",
        "document_processing_jobs",
        "citations",
        "ai_response_sources",
        "ai_execution_nodes",
        "ai_execution_chunks",
        "ai_execution_citations",
        "ai_execution_sources",
        "trace_events",
        "workspaces",
        "canonical_objects",
        "canonical_documents",
        "canonical_chunks",
        "canonical_notes",
        "canonical_executions",
        "canonical_relationships",
    } <= tables

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        response_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(ai_responses)")
        }
        response_foreign_keys = list(connection.execute("PRAGMA foreign_key_list(ai_responses)"))
        assert response_columns["node_id"][3] == 0
        node_foreign_key = next(row for row in response_foreign_keys if row[3] == "node_id")
        assert node_foreign_key[6] == "SET NULL"

        canvas_id = uuid.uuid4().hex
        node_id = uuid.uuid4().hex
        request_id = uuid.uuid4().hex
        response_id = uuid.uuid4().hex
        workspace_id = uuid.uuid4().hex
        system_user_id = "00000000000040008000000000000001"
        connection.execute(
            "INSERT INTO workspaces (id, name, owner_id) VALUES (?, ?, ?)",
            (workspace_id, "Audit workspace", system_user_id),
        )
        connection.execute(
            "INSERT INTO canvases (id, workspace_id, name) VALUES (?, ?, ?)",
            (canvas_id, workspace_id, "Audit"),
        )
        connection.execute(
            """INSERT INTO nodes
               (id, canvas_id, type, title, text, position_x, position_y)
               VALUES (?, ?, 'ai_response', 'Answer', 'grounded', 0, 0)""",
            (node_id, canvas_id),
        )
        connection.execute(
            """INSERT INTO ai_requests
               (id, trace_id, user_id, workspace_id, canvas_id, instruction,
                selected_node_ids, context_snapshot, provider, model,
                provider_configuration_version, execution_mode, status)
               VALUES (?, ?, ?, ?, ?, 'Question', '[]', '[]', 'mock', 'mock',
                       'test-v1', 'current_context', 'completed')""",
            (request_id, request_id, system_user_id, workspace_id, canvas_id),
        )
        connection.execute(
            """INSERT INTO ai_responses (id, request_id, node_id, content)
               VALUES (?, ?, ?, 'Preserved answer')""",
            (response_id, request_id, node_id),
        )
        connection.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        preserved = connection.execute(
            "SELECT node_id, content FROM ai_responses WHERE id = ?", (response_id,)
        ).fetchone()
        assert preserved == (None, "Preserved answer")


def test_migration_uses_configured_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "configured-migration.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("OPENCANVAS_DATABASE_URL", database_url)
    get_settings.cache_clear()

    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))

    try:
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("20260721_0006",)


def test_phase_two_migration_downgrades_and_reupgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    command.downgrade(config, "20260716_0001")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        response_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(ai_responses)")
        }
        response_foreign_keys = list(connection.execute("PRAGMA foreign_key_list(ai_responses)"))
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert revision == ("20260716_0001",)
    assert response_columns["node_id"][3] == 1
    node_foreign_key = next(row for row in response_foreign_keys if row[3] == "node_id")
    assert node_foreign_key[6] == "CASCADE"
    assert "ai_execution_citations" not in tables
    assert "ai_execution_sources" not in tables

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("20260721_0006",)


def test_trace_foundation_migration_downgrades_and_reupgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    command.downgrade(config, "20260717_0002")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert revision == ("20260717_0002",)
    assert "trace_events" not in tables

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(trace_events)")}
    assert revision == ("20260721_0006",)
    assert {
        "ix_trace_events_trace_time",
        "ix_trace_events_workspace_time",
        "ix_trace_events_object_time",
        "ix_trace_events_type_time",
    } <= indexes


def test_canonical_migration_backfills_canvases_and_reverses_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "canonical-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260717_0003")
    retained_canvas_id = uuid.uuid4().hex
    removed_canvas_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO canvases (id, name) VALUES (?, ?)",
            (
                (retained_canvas_id, "Retained canvas"),
                (removed_canvas_id, "Removed canvas"),
            ),
        )

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        workspaces = connection.execute(
            """SELECT id, name, version, lifecycle_state, metadata, legacy_canvas_id
               FROM workspaces ORDER BY name"""
        ).fetchall()
        connection.execute("DELETE FROM canvases WHERE id = ?", (removed_canvas_id,))
        removed_workspace = connection.execute(
            "SELECT id, legacy_canvas_id FROM workspaces WHERE id = ?",
            (removed_canvas_id,),
        ).fetchone()
    assert revision == ("20260721_0006",)
    assert workspaces == [
        (removed_canvas_id, "Removed canvas", 1, "active", "{}", removed_canvas_id),
        (retained_canvas_id, "Retained canvas", 1, "active", "{}", retained_canvas_id),
    ]
    assert removed_workspace == (removed_canvas_id, None)

    command.downgrade(config, "20260717_0003")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        canvases = connection.execute("SELECT id, name FROM canvases").fetchall()
    assert revision == ("20260717_0003",)
    assert (
        not {
            "workspaces",
            "canonical_objects",
            "canonical_documents",
            "canonical_chunks",
            "canonical_notes",
            "canonical_executions",
            "canonical_relationships",
        }
        & tables
    )
    assert canvases == [(retained_canvas_id, "Retained canvas")]

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        workspaces = connection.execute(
            "SELECT id, legacy_canvas_id, lifecycle_state FROM workspaces"
        ).fetchall()
    assert revision == ("20260721_0006",)
    assert workspaces == [(retained_canvas_id, retained_canvas_id, "active")]
