from __future__ import annotations

import importlib.util
import io
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REVISION = "20260725_0025"


def _config(database_path: Path) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260725_0025_shared_workflow_agent_governance.py"
    )
    spec = importlib.util.spec_from_file_location("milestone_6_5_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_governance_migration_cycles_and_compiles_postgresql(tmp_path: Path) -> None:
    database_path = tmp_path / "shared-governance.db"
    config = _config(database_path)
    command.upgrade(config, REVISION)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            REVISION,
        )
        workflow_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('controlled_workflow_executions')")
        }
        invocation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('bounded_agent_invocations')")
        }
        expected = {
            "definition_owner_user_id",
            "invoking_membership_id",
            "authority_snapshot_id",
        }
        assert expected <= workflow_columns
        assert expected <= invocation_columns
    command.downgrade(config, "20260725_0024")
    command.upgrade(config, REVISION)
    assert ScriptDirectory.from_config(config).get_heads() == [REVISION]

    api_directory = Path(__file__).resolve().parents[1]
    buffer = io.StringIO()
    offline = Config(api_directory / "alembic.ini", output_buffer=buffer)
    offline.set_main_option("script_location", str(api_directory / "alembic"))
    offline.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(offline, "20260725_0024:20260725_0025", sql=True)
    ddl = buffer.getvalue()
    assert "definition_owner_user_id" in ddl
    assert "fk_workflow_execution_invoking_membership" in ddl
    assert "fk_bounded_agent_invocation_authority_snapshot" in ddl


@pytest.mark.parametrize(
    ("states", "workspace_match", "expected_count"),
    [
        (("active",), True, 1),
        ((), True, 0),
        (("removed",), True, 0),
        (("active",), False, 0),
        (("active", "active"), True, 2),
    ],
)
def test_historical_membership_resolution_is_exact_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    states: tuple[str, ...],
    workspace_match: bool,
    expected_count: int,
) -> None:
    migration = _migration()
    engine = sa.create_engine("sqlite://")
    occurred_at = datetime.now(UTC)
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE workspace_memberships ("
                "membership_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                "workspace_id TEXT NOT NULL, created_at TIMESTAMP NOT NULL)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE workspace_membership_transitions ("
                "membership_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
                "current_state TEXT NOT NULL, current_role TEXT NOT NULL, "
                "authority_generation INTEGER NOT NULL, recorded_at TIMESTAMP NOT NULL)"
            )
        )
        for index, state in enumerate(states):
            membership_id = uuid.uuid4()
            candidate_workspace = workspace_id if workspace_match else uuid.uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO workspace_memberships VALUES "
                    "(:membership_id, :user_id, :workspace_id, :created_at)"
                ),
                {
                    "membership_id": membership_id.hex,
                    "user_id": user_id.hex,
                    "workspace_id": candidate_workspace.hex,
                    "created_at": occurred_at - timedelta(minutes=2 + index),
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO workspace_membership_transitions VALUES "
                    "(:membership_id, 0, :state, 'member', 1, :recorded_at)"
                ),
                {
                    "membership_id": membership_id.hex,
                    "state": state,
                    "recorded_at": occurred_at - timedelta(minutes=1),
                },
            )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        if expected_count == 1:
            resolved = migration._historical_membership(
                connection,
                user_id=user_id,
                workspace_id=workspace_id,
                occurred_at=occurred_at,
                subject="test execution",
            )
            assert resolved["role"] == "member"
        else:
            with pytest.raises(
                RuntimeError,
                match=rf"has {expected_count} exact active historical memberships",
            ):
                migration._historical_membership(
                    connection,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    occurred_at=occurred_at,
                    subject="test execution",
                )
