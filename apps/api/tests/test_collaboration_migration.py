from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

COLLABORATION_TABLES = {
    "workspace_memberships",
    "workspace_membership_transitions",
    "workspace_invitations",
    "workspace_invitation_transitions",
    "workspace_invitation_secret_versions",
    "workspace_invitation_delivery_attempts",
    "collaboration_request_identities",
    "workspace_authority_versions",
    "collaboration_audit_events",
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


def test_collaboration_migration_backfills_owner_and_cycles(tmp_path: Path) -> None:
    database_path = tmp_path / "collaboration.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0020")
    user_id = uuid.uuid4().hex
    workspace_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """INSERT INTO users
               (id, email, email_normalized, password_hash, display_name, email_verified)
               VALUES (?, 'owner@example.test', 'owner@example.test',
                       'test-only', 'Owner', 1)""",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO workspaces (id, owner_id, name) VALUES (?, ?, 'Owned workspace')",
            (workspace_id, user_id),
        )
        connection.commit()

    command.upgrade(config, "20260725_0021")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0021",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= COLLABORATION_TABLES
        membership = connection.execute(
            """SELECT m.user_id, m.workspace_id, t.current_state, t.current_role,
                      t.authority_generation
               FROM workspace_memberships m
               JOIN workspace_membership_transitions t
                 ON t.membership_id = m.membership_id
               WHERE m.workspace_id = ?""",
            (workspace_id,),
        ).fetchone()
        assert membership == (user_id, workspace_id, "active", "owner", 1)
        assert connection.execute(
            "SELECT authority_generation FROM workspace_authority_versions WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_audit_events WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trace_events "
            "WHERE workspace_id = ? AND operation = 'backfill_owner_membership'",
            (workspace_id,),
        ).fetchone() == (1,)
        invitation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('workspace_invitations')")
        }
        secret_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('workspace_invitation_secret_versions')"
            )
        }
        assert not {"token", "secret", "raw_token"} & invitation_columns
        assert "token_hash" in secret_columns
        assert "raw_token" not in secret_columns

        membership_id = connection.execute(
            "SELECT membership_id FROM workspace_memberships WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE workspace_memberships SET created_by_user_id = ? WHERE membership_id = ?",
                (uuid.uuid4().hex, membership_id),
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match=r"duplicate active membership|multiple workspace owners",
        ):
            second_membership = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO workspace_memberships
                   (membership_id, user_id, workspace_id, created_by_user_id,
                    collaboration_policy_version, creation_trace_id,
                    creation_audit_event_id, created_at)
                   VALUES (?, ?, ?, ?, 'collaboration-policy-v1', ?, ?,
                           CURRENT_TIMESTAMP)""",
                (
                    second_membership,
                    user_id,
                    workspace_id,
                    user_id,
                    uuid.uuid4().hex,
                    connection.execute(
                        "SELECT audit_event_id FROM collaboration_audit_events "
                        "WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()[0],
                ),
            )
            connection.execute(
                """INSERT INTO workspace_membership_transitions
                   (transition_id, membership_id, user_id, workspace_id, sequence,
                    current_state, current_role, reason_code, collaboration_policy_version,
                    authority_generation, actor_user_id, trace_id, audit_event_id, recorded_at)
                   VALUES (?, ?, ?, ?, 0, 'active', 'owner', 'invalid_second_owner',
                           'collaboration-policy-v1', 1, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    uuid.uuid4().hex,
                    second_membership,
                    user_id,
                    workspace_id,
                    user_id,
                    uuid.uuid4().hex,
                    connection.execute(
                        "SELECT audit_event_id FROM collaboration_audit_events "
                        "WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()[0],
                ),
            )

    command.downgrade(config, "20260725_0020")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0020",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert not (tables & COLLABORATION_TABLES)
        assert connection.execute(
            "SELECT COUNT(*) FROM trace_events WHERE operation = 'backfill_owner_membership'"
        ).fetchone() == (0,)

    command.upgrade(config, "20260725_0021")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0021",
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone() == (1,)


def test_collaboration_migration_is_sole_head_and_postgresql_ddl_compiles() -> None:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0022"]

    buffer = io.StringIO()
    offline = Config(api_directory / "alembic.ini", output_buffer=buffer)
    offline.set_main_option("script_location", str(api_directory / "alembic"))
    offline.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(offline, "20260725_0020:20260725_0021", sql=True)
    ddl = buffer.getvalue()
    assert "CREATE TABLE workspace_memberships" in ddl
    assert "CREATE TABLE workspace_invitations" in ddl
    assert "fk_workspace_membership_accepted_invitation_scope" in ddl
    assert "trg_workspace_membership_transition_valid" in ddl
    assert "trg_workspace_invitation_secret_sequence" in ddl
    assert "trg_workspace_invitation_delivery_sequence" in ddl
    assert "CREATE TABLE collaboration_audit_events" in ddl
