from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def _config(database_path: Path) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_milestone_6_2_migration_cycles_and_replaces_role_guard(tmp_path: Path) -> None:
    database_path = tmp_path / "collaboration-6-2.db"
    config = _config(database_path)
    command.upgrade(config, "20260725_0021")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        owner_id = uuid.uuid4().hex
        member_id = uuid.uuid4().hex
        workspace_id = uuid.uuid4().hex
        membership_id = uuid.uuid4().hex
        owner_membership_id = uuid.uuid4().hex
        audit_id = uuid.uuid4().hex
        connection.executemany(
            """INSERT INTO users
               (id, email, email_normalized, password_hash, display_name, email_verified)
               VALUES (?, ?, ?, 'test-only', ?, 1)""",
            (
                (owner_id, "owner-6-2@example.test", "owner-6-2@example.test", "Owner"),
                (member_id, "member-6-2@example.test", "member-6-2@example.test", "Member"),
            ),
        )
        connection.execute(
            "INSERT INTO workspaces (id, owner_id, name) VALUES (?, ?, '6.2 workspace')",
            (workspace_id, owner_id),
        )
        connection.execute(
            """INSERT INTO collaboration_audit_events
               (audit_event_id, workspace_id, actor_user_id, subject_kind, subject_id,
                action, outcome, reason_code, metadata_digest, trace_id, recorded_at)
               VALUES (?, ?, ?, 'workspace_membership', ?, 'membership.seed',
                       'succeeded', 'test_seed', ?, ?, CURRENT_TIMESTAMP)""",
            (audit_id, workspace_id, owner_id, membership_id, "0" * 64, uuid.uuid4().hex),
        )
        for identity, user, role in (
            (owner_membership_id, owner_id, "owner"),
            (membership_id, member_id, "editor"),
        ):
            connection.execute(
                """INSERT INTO workspace_memberships
                   (membership_id, user_id, workspace_id, created_by_user_id,
                    collaboration_policy_version, creation_trace_id,
                    creation_audit_event_id, created_at)
                   VALUES (?, ?, ?, ?, 'collaboration-policy-v1', ?, ?,
                           CURRENT_TIMESTAMP)""",
                (
                    identity,
                    user,
                    workspace_id,
                    owner_id,
                    uuid.uuid4().hex,
                    audit_id,
                ),
            )
            connection.execute(
                """INSERT INTO workspace_membership_transitions
                   (transition_id, membership_id, user_id, workspace_id, sequence,
                    current_state, current_role, reason_code, collaboration_policy_version,
                    authority_generation, actor_user_id, trace_id, audit_event_id, recorded_at)
                   VALUES (?, ?, ?, ?, 0, 'active', ?, 'test_seed',
                           'collaboration-policy-v1', 1, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    uuid.uuid4().hex,
                    identity,
                    user,
                    workspace_id,
                    role,
                    owner_id,
                    uuid.uuid4().hex,
                    audit_id,
                ),
            )
        connection.execute(
            """INSERT INTO workspace_authority_versions
               (workspace_id, authority_generation, last_trace_id, updated_at)
               VALUES (?, 1, ?, CURRENT_TIMESTAMP)""",
            (workspace_id, uuid.uuid4().hex),
        )
        connection.commit()

    command.upgrade(config, "20260725_0022")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0022",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "collaboration_approval_authority_assignments",
            "collaboration_approval_authority_transitions",
            "collaboration_reviewer_eligibility_evidence",
        } <= tables
        connection.execute(
            """INSERT INTO workspace_membership_transitions
               (transition_id, membership_id, user_id, workspace_id, sequence,
                previous_state, current_state, previous_role, current_role, reason_code,
                collaboration_policy_version, authority_generation, actor_user_id,
                trace_id, audit_event_id, recorded_at)
               VALUES (?, ?, ?, ?, 1, 'active', 'active', 'editor', 'member',
                       'role_changed', 'collaboration-policy-v1', 2, ?, ?, ?,
                       CURRENT_TIMESTAMP)""",
            (
                uuid.uuid4().hex,
                membership_id,
                member_id,
                workspace_id,
                owner_id,
                uuid.uuid4().hex,
                audit_id,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="invalid membership"):
            connection.execute(
                """INSERT INTO workspace_membership_transitions
                   (transition_id, membership_id, user_id, workspace_id, sequence,
                    previous_state, current_state, previous_role, current_role, reason_code,
                    collaboration_policy_version, authority_generation, actor_user_id,
                    trace_id, audit_event_id, recorded_at)
                   VALUES (?, ?, ?, ?, 1, 'active', 'active', 'owner', 'administrator',
                           'invalid_owner_change', 'collaboration-policy-v1', 2, ?, ?, ?,
                           CURRENT_TIMESTAMP)""",
                (
                    uuid.uuid4().hex,
                    owner_membership_id,
                    owner_id,
                    workspace_id,
                    owner_id,
                    uuid.uuid4().hex,
                    audit_id,
                ),
            )
        connection.rollback()

    command.downgrade(config, "20260725_0021")
    command.upgrade(config, "20260725_0022")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260725_0022",
        )


def test_milestone_6_2_is_sole_head_and_postgresql_ddl_compiles() -> None:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["20260726_0027"]

    buffer = io.StringIO()
    offline = Config(api_directory / "alembic.ini", output_buffer=buffer)
    offline.set_main_option("script_location", str(api_directory / "alembic"))
    offline.set_main_option("sqlalchemy.url", "postgresql+asyncpg://unused/unused")
    command.upgrade(offline, "20260725_0021:20260725_0022", sql=True)
    ddl = buffer.getvalue()
    assert "CREATE TABLE collaboration_approval_authority_assignments" in ddl
    assert "CREATE TABLE collaboration_reviewer_eligibility_evidence" in ddl
    assert "validate_workspace_membership_transition" in ddl
    assert "validate_collaboration_approval_transition" in ddl
