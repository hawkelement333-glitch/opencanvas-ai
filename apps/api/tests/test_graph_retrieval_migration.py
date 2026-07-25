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


def test_graph_retrieval_migration_cycle_and_append_only_guards(tmp_path: Path) -> None:
    database_path = tmp_path / "graph-retrieval.db"
    config = _config(database_path)
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0019",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "graph_retrieval_runs",
            "graph_retrieval_decisions",
            "graph_retrieval_citations",
            "trace_evidence_bundles",
        } <= tables
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'trg_graph_retrieval_%_blocked'"
            )
        }
        assert "trg_graph_retrieval_runs_update_blocked" in triggers
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO graph_retrieval_runs "
            "(retrieval_id,user_id,workspace_id,canvas_id,idempotency_key,"
            "request_digest,query_text,query_digest,selected_object_ids,"
            "seed_object_ids,graph_revision,algorithm_version,schema_version,"
            "mode,outcome,bounded,citation_count,trace_id) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "1" * 32,
                "2" * 32,
                "3" * 32,
                "4" * 32,
                "migration",
                "a" * 64,
                "query",
                "b" * 64,
                "[]",
                "[]",
                0,
                "graph-retrieval-v1",
                "graph-retrieval-result-v1",
                "selected_graph",
                "insufficient_evidence",
                0,
                0,
                "5" * 32,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE graph_retrieval_runs SET outcome='supported' WHERE retrieval_id=?",
                ("1" * 32,),
            )

    command.downgrade(config, "20260725_0017")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0017",
        )
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0019",
        )


def test_graph_retrieval_postgresql_ddl_compiles_offline() -> None:
    buffer = io.StringIO()
    api_directory = Path(__file__).parents[1]
    config = Config(str(api_directory / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(config, "20260725_0017:20260725_0018", sql=True)
    ddl = buffer.getvalue()
    assert "CREATE TABLE graph_retrieval_runs" in ddl
    assert "CREATE TABLE graph_retrieval_citations" in ddl
    assert "CREATE TABLE trace_evidence_bundles" in ddl
    assert "reject_graph_retrieval_runs_mutation" in ddl
