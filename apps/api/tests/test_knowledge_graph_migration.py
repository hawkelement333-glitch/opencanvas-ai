from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def _config(database_path: Path) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_knowledge_graph_migration_cycle_and_sqlite_append_only_guards(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "knowledge-graph-migration.db"
    config = _config(database_path)
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert head == ("20260725_0018",)
        trigger_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND name LIKE 'trg_canonical_%_blocked'"
            )
        }
        assert {
            "trg_canonical_graph_entities_update_blocked",
            "trg_canonical_graph_entities_delete_blocked",
            "trg_canonical_canvas_object_bindings_update_blocked",
            "trg_canonical_canvas_object_bindings_delete_blocked",
            "trg_canonical_graph_relationships_update_blocked",
            "trg_canonical_graph_relationships_delete_blocked",
            "trg_canonical_relationship_provenance_update_blocked",
            "trg_canonical_relationship_provenance_delete_blocked",
            "trg_canonical_relationship_history_update_blocked",
            "trg_canonical_relationship_history_delete_blocked",
        }.issubset(trigger_names)

        connection.execute("PRAGMA foreign_keys=OFF")
        relationship_id = "1" * 32
        history_id = "2" * 32
        connection.execute(
            "INSERT INTO canonical_relationship_history "
            "(history_id, relationship_id, workspace_id, user_id, canvas_id, "
            "state, reason_code, actor_user_id, trace_id, graph_revision, "
            "previous_history_id, idempotency_key, request_digest) "
            "VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, ?, 1, NULL, ?, ?)",
            (
                history_id,
                relationship_id,
                "3" * 32,
                "4" * 32,
                "5" * 32,
                "4" * 32,
                "6" * 32,
                "migration-trigger-test",
                "a" * 64,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="knowledge-graph records are append-only"):
            connection.execute(
                "UPDATE canonical_relationship_history SET state = 'rejected' WHERE history_id = ?",
                (history_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="knowledge-graph records are append-only"):
            connection.execute(
                "DELETE FROM canonical_relationship_history WHERE history_id = ?",
                (history_id,),
            )

    command.downgrade(config, "20260724_0015")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260724_0015",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "canonical_graph_relationships" not in tables
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0018",
        )
