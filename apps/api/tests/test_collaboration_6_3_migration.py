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
        f"sqlite+aiosqlite:///{(tmp_path / 'collaboration-6-3.db').as_posix()}",
    )
    return config


def test_milestone_6_3_is_the_only_head_and_0024_is_absent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260725_0025"]
    assert scripts.get_revision("20260725_0023").down_revision == "20260725_0022"
    assert scripts.get_revision("20260725_0024").down_revision == "20260725_0023"


def test_milestone_6_3_schema_is_scoped_append_only_and_cycles(tmp_path: Path) -> None:
    config = _config(tmp_path)
    database_path = tmp_path / "collaboration-6-3.db"
    command.upgrade(config, "head")
    expected = {
        "collaboration_resources",
        "collaboration_resource_ownership_transitions",
        "collaboration_resource_shares",
        "collaboration_resource_share_transitions",
        "collaboration_ownership_transfers",
        "collaboration_ownership_transfer_transitions",
        "collaboration_authority_snapshots",
        "collaboration_revocation_fences",
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
    assert revision == ("20260725_0025",)
    assert expected <= tables
    assert {
        "trg_collaboration_resources_update_blocked",
        "trg_collaboration_resources_delete_blocked",
        "trg_collaboration_share_transition_valid",
        "trg_collaboration_ownership_transition_valid",
        "trg_collaboration_transfer_transition_valid",
        "trg_canvases_collaboration_resource",
        "trg_canonical_objects_collaboration_resource",
        "trg_controlled_workflow_definitions_collaboration_resource",
        "trg_bounded_agent_identities_collaboration_resource",
    } <= triggers

    command.downgrade(config, "20260725_0022")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0022",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert not expected & tables
    command.upgrade(config, "head")


def test_milestone_6_3_postgresql_ddl_compiles(tmp_path: Path) -> None:
    config = _config(tmp_path)
    output = io.StringIO()
    config.output_buffer = output
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(config, "20260725_0022:20260725_0023", sql=True)
    ddl = output.getvalue()
    assert "CREATE TABLE collaboration_resources" in ddl
    assert "CREATE TABLE collaboration_authority_snapshots" in ddl
    assert "CREATE TABLE collaboration_revocation_fences" in ddl
