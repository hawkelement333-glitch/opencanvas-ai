from __future__ import annotations

import io
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def _config(tmp_path: Path) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{(tmp_path / 'collaboration-6-4.db').as_posix()}",
    )
    return config


def test_milestone_6_4_is_the_only_direct_head(tmp_path: Path) -> None:
    scripts = ScriptDirectory.from_config(_config(tmp_path))
    assert scripts.get_heads() == ["20260726_0029"]
    assert scripts.get_revision("20260725_0024").down_revision == "20260725_0023"
    assert scripts.get_revision("20260725_0023").down_revision == "20260725_0022"


def test_milestone_6_4_schema_is_append_only_and_cycles(tmp_path: Path) -> None:
    config = _config(tmp_path)
    database_path = tmp_path / "collaboration-6-4.db"
    command.upgrade(config, "20260725_0024")
    expected_tables = {
        "collaboration_comment_threads",
        "collaboration_comment_thread_transitions",
        "collaboration_comments",
        "collaboration_comment_revisions",
        "collaboration_comment_transitions",
    }
    expected_guards = {
        "trg_collaboration_comment_thread_scope_valid",
        "trg_collaboration_comment_insert_valid",
        "trg_collaboration_comment_revision_valid",
        "trg_collaboration_comment_transition_valid",
        "trg_collaboration_comment_thread_transition_valid",
        "trg_collaboration_comments_update_blocked",
        "trg_collaboration_comments_delete_blocked",
        "trg_collaboration_comment_revisions_update_blocked",
        "trg_collaboration_comment_revisions_delete_blocked",
    }
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        triggers = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        }
        domain_event_ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'domain_events'"
        ).fetchone()[0]
    assert revision == ("20260725_0024",)
    assert expected_tables <= tables
    assert expected_guards <= triggers
    assert "comment.created" in domain_event_ddl
    assert "comment.thread.reopened" in domain_event_ddl

    command.downgrade(config, "20260725_0023")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0023",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert not expected_tables & tables
    command.upgrade(config, "20260725_0024")


def test_milestone_6_4_postgresql_ddl_compiles(tmp_path: Path) -> None:
    config = _config(tmp_path)
    output = io.StringIO()
    config.output_buffer = output
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(config, "20260725_0023:20260725_0024", sql=True)
    ddl = output.getvalue()
    assert "CREATE TABLE collaboration_comment_threads" in ddl
    assert "CREATE TABLE collaboration_comments" in ddl
    assert "CREATE TABLE collaboration_comment_revisions" in ddl
    assert "CREATE FUNCTION validate_collaboration_comment_insert()" in ddl
    assert "CREATE FUNCTION validate_collaboration_comment_revision()" in ddl
