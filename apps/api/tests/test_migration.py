from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from opencanvas_api.core.config import get_settings


def _load_migration_validator() -> ModuleType:
    repository_root = Path(__file__).resolve().parents[3]
    validator_path = repository_root / "scripts" / "validate_migrations.py"
    spec = importlib.util.spec_from_file_location("validate_migrations", validator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the migration validator.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_standalone_migration_validator_tracks_current_head() -> None:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1

    validator = _load_migration_validator()
    assert heads[0] == validator.EXPECTED_HEAD
    assert scripts.get_revision(heads[0]).down_revision == validator.PREVIOUS_REVISION


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
        "controlled_agent_executions",
        "controlled_agent_execution_states",
        "controlled_agent_state_transitions",
        "controlled_agent_context_snapshots",
        "controlled_agent_plan_snapshots",
        "controlled_agent_capability_grants",
        "controlled_agent_grant_revocations",
        "controlled_agent_approvals",
        "controlled_agent_policy_decisions",
        "controlled_agent_approval_consumptions",
        "controlled_agent_audit_events",
        "controlled_agent_request_identities",
        "controlled_agent_reversible_write_proposals",
        "controlled_agent_reversible_write_effects",
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
    assert revision == ("20260725_0025",)


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
    assert revision == ("20260725_0025",)


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
    assert revision == ("20260725_0025",)
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

    # Exercise the historical canonical boundary before 6.3 intentionally
    # adds RESTRICT-scoped collaboration resource identities for canvases.
    command.upgrade(config, "20260725_0022")
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
    assert revision == ("20260725_0022",)
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
    assert revision == ("20260725_0025",)
    assert workspaces == [(retained_canvas_id, retained_canvas_id, "active")]


def test_controlled_agent_migration_is_append_only_and_reversible_sqlite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "controlled-agent-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    execution_id = uuid.uuid4().hex
    context_id = uuid.uuid4().hex
    plan_id = uuid.uuid4().hex
    grant_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        user_id = "00000000000040008000000000000001"
        workspace_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO workspaces (id, name, owner_id) VALUES (?, ?, ?)",
            (workspace_id, "Controlled-agent audit", user_id),
        )
        connection.execute(
            """INSERT INTO controlled_agent_executions
               (id, user_id, workspace_id, schema_version, role, context_snapshot_id,
                context_digest, plan_id, plan_digest, grant_id, created_at, deadline_at)
               VALUES (?, ?, ?, 'controlled-agent-v1', 'evidence_verifier', ?, ?, ?, ?, ?, ?, ?)""",
            (
                execution_id,
                user_id,
                workspace_id,
                context_id,
                "a" * 64,
                plan_id,
                "b" * 64,
                grant_id,
                "2026-07-21 18:00:00.000000",
                "2026-07-21 18:15:00.000000",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="authority is immutable"):
            connection.execute(
                "UPDATE controlled_agent_executions SET plan_digest = ? WHERE id = ?",
                ("c" * 64, execution_id),
            )

    command.downgrade(config, "20260721_0006")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert revision == ("20260721_0006",)
    assert not any(table.startswith("controlled_agent_") for table in tables)

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert revision == ("20260725_0025",)
    assert "controlled_agent_approval_consumptions" in tables


def test_reversible_effect_migration_upgrades_downgrades_and_reupgrades_sqlite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "reversible-effect-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260724_0011")
    command.upgrade(config, "20260724_0012")
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0025"]

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(controlled_agent_reversible_write_effects)"
            )
        }
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'controlled_agent_reversible_write_effects'"
            )
        }
        effect_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'controlled_agent_reversible_write_effects'"
        ).fetchone()
    assert revision == ("20260724_0012",)
    assert "controlled_agent_reversible_write_effects" in tables
    assert {
        "ix_agent_reversible_effect_proposal",
        "ix_agent_reversible_effect_scope",
        "sqlite_autoindex_controlled_agent_reversible_write_effects_2",
        "sqlite_autoindex_controlled_agent_reversible_write_effects_3",
        "sqlite_autoindex_controlled_agent_reversible_write_effects_4",
    } <= indexes
    assert triggers == {
        "trg_controlled_agent_reversible_write_effects_update_blocked",
        "trg_controlled_agent_reversible_write_effects_delete_blocked",
    }
    assert effect_sql is not None
    assert "ck_agent_reversible_effect_resource_shape" in effect_sql[0]
    assert "fk_agent_reversible_effect_approval_scope" in effect_sql[0]
    assert "fk_agent_reversible_effect_proposal" in effect_sql[0]

    effect_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO controlled_agent_reversible_write_effects
               (effect_id, execution_id, proposal_id, approval_id, user_id, workspace_id,
                canvas_id, idempotency_key, plan_digest, action, destination_id,
                resulting_resource_id, resulting_revision, after_digest, outcome, trace_id,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'note.create', ?, ?, 1, ?, 'succeeded', ?, ?)""",
            (
                effect_id,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                "migration-trigger-effect",
                "a" * 64,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                "b" * 64,
                uuid.uuid4().hex,
                "2026-07-24T12:00:00+00:00",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE controlled_agent_reversible_write_effects SET after_digest = ? "
                "WHERE effect_id = ?",
                ("c" * 64, effect_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM controlled_agent_reversible_write_effects WHERE effect_id = ?",
                (effect_id,),
            )

    command.downgrade(config, "20260724_0011")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'controlled_agent_reversible_write_effects'"
            )
        }
    assert revision == ("20260724_0011",)
    assert "controlled_agent_reversible_write_effects" not in tables
    assert not triggers

    command.upgrade(config, "20260724_0012")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("20260724_0012",)


def test_rollback_evidence_migration_upgrades_downgrades_and_reupgrades_sqlite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rollback-evidence-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260724_0012")
    command.upgrade(config, "20260724_0013")
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0025"]

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        evidence_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(controlled_agent_reversible_write_rollback_evidence)"
            )
        }
        effect_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(controlled_agent_reversible_write_effects)"
            )
        }
        evidence_triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'controlled_agent_reversible_write_rollback_evidence'"
            )
        }
        evidence_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'controlled_agent_reversible_write_rollback_evidence'"
        ).fetchone()

        valid_values = (
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            4,
            5,
            '{"title":"Before"}',
            "a" * 64,
            "b" * 64,
            "2026-07-24T12:00:00+00:00",
        )
        invalid_values = valid_values[:10] + valid_values[11:]
        with pytest.raises(sqlite3.IntegrityError, match="before_state_object"):
            connection.execute(
                """INSERT INTO controlled_agent_reversible_write_rollback_evidence
                   (evidence_id, effect_id, execution_id, proposal_id, user_id, workspace_id,
                    canvas_id, action, note_id, pre_effect_revision, post_effect_revision,
                    before_state, before_digest, after_digest, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'note.update', ?, ?, ?, 'null', ?, ?, ?)""",
                invalid_values,
            )
        connection.execute(
            """INSERT INTO controlled_agent_reversible_write_rollback_evidence
               (evidence_id, effect_id, execution_id, proposal_id, user_id, workspace_id,
                canvas_id, action, note_id, pre_effect_revision, post_effect_revision,
                before_state, before_digest, after_digest, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'note.update', ?, ?, ?, ?, ?, ?, ?)""",
            valid_values,
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE controlled_agent_reversible_write_rollback_evidence SET before_digest = ? "
                "WHERE evidence_id = ?",
                ("c" * 64, valid_values[0]),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM controlled_agent_reversible_write_rollback_evidence "
                "WHERE evidence_id = ?",
                (valid_values[0],),
            )

    assert revision == ("20260724_0013",)
    assert "controlled_agent_reversible_write_rollback_evidence" in tables
    assert {
        "ix_agent_rollback_evidence_note",
        "ix_agent_rollback_evidence_scope",
        "sqlite_autoindex_controlled_agent_reversible_write_rollback_evidence_2",
    } <= evidence_indexes
    assert "ux_agent_reversible_effect_rollback_scope" in effect_indexes
    assert evidence_triggers == {
        "trg_controlled_agent_reversible_write_rollback_evidence_delete_blocked",
        "trg_controlled_agent_reversible_write_rollback_evidence_update_blocked",
    }
    assert evidence_sql is not None
    assert "ck_agent_rollback_evidence_before_state_object" in evidence_sql[0]
    assert "json_type(before_state) = 'object'" in evidence_sql[0]
    assert "fk_agent_rollback_evidence_effect_scope" in evidence_sql[0]
    assert "fk_agent_rollback_evidence_note_canvas" in evidence_sql[0]

    command.downgrade(config, "20260724_0012")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        evidence_triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'controlled_agent_reversible_write_rollback_evidence'"
            )
        }
        effect_triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'controlled_agent_reversible_write_effects'"
            )
        }
        effect_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(controlled_agent_reversible_write_effects)"
            )
        }
    assert revision == ("20260724_0012",)
    assert "controlled_agent_reversible_write_rollback_evidence" not in tables
    assert not evidence_triggers
    assert "ux_agent_reversible_effect_rollback_scope" not in effect_indexes
    assert effect_triggers == {
        "trg_controlled_agent_reversible_write_effects_delete_blocked",
        "trg_controlled_agent_reversible_write_effects_update_blocked",
    }

    command.upgrade(config, "20260724_0013")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("20260724_0013",)
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0025"]


def test_rollback_authority_migration_upgrades_downgrades_and_reupgrades_sqlite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rollback-authority-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260724_0013")
    command.upgrade(config, "20260724_0014")

    approval_table = "controlled_agent_reversible_write_rollback_approvals"
    result_table = "controlled_agent_reversible_write_rollback_results"
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        approval_indexes = {
            row[1] for row in connection.execute(f"PRAGMA index_list({approval_table})")
        }
        result_indexes = {
            row[1] for row in connection.execute(f"PRAGMA index_list({result_table})")
        }
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN (?, ?)",
                (approval_table, result_table),
            )
        }
        approval_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (approval_table,)
        ).fetchone()
        result_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (result_table,)
        ).fetchone()
        approval_id = uuid.uuid4().hex
        effect_id = uuid.uuid4().hex
        values = (
            approval_id,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            effect_id,
            "a" * 64,
            0,
            "b" * 64,
            "c" * 64,
            uuid.uuid4().hex,
            "migration-approval",
            "d" * 64,
            "2026-07-24T12:05:00+00:00",
            "2026-07-24T12:00:00+00:00",
        )
        connection.execute(
            f"""INSERT INTO {approval_table}
               (rollback_approval_id, execution_id, user_id, workspace_id, canvas_id, note_id,
                proposal_id, effect_id, forward_action, rollback_action, original_plan_digest,
                expected_current_revision, effect_after_state_digest, rollback_target_kind,
                rollback_target_digest, grant_id, scoped_idempotency_key, approval_digest,
                expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'note.create', 'note.create.rollback', ?, ?, ?,
                       'authoritative_absence', ?, ?, ?, ?, ?, ?)""",
            values,
        )
        result_id = uuid.uuid4().hex
        connection.execute(
            f"""INSERT INTO {result_table}
               (rollback_result_id, rollback_approval_id, execution_id, user_id, workspace_id,
                canvas_id, note_id, proposal_id, effect_id, forward_action, rollback_action,
                rollback_target_kind, rollback_approval_digest, scoped_idempotency_key,
                expected_pre_rollback_revision, resulting_revision, pre_rollback_state_digest,
                post_rollback_target_digest, trace_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'note.create', 'note.create.rollback',
                       'authoritative_absence', ?, ?, ?, NULL, ?, ?, ?, ?)""",
            (
                result_id,
                approval_id,
                *values[1:8],
                "d" * 64,
                "migration-result",
                0,
                "b" * 64,
                "c" * 64,
                uuid.uuid4().hex,
                "2026-07-24T12:01:00+00:00",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                f"UPDATE {approval_table} SET approval_digest = ? WHERE rollback_approval_id = ?",
                ("e" * 64, approval_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                f"DELETE FROM {result_table} WHERE rollback_result_id = ?", (result_id,)
            )

    assert revision == ("20260724_0014",)
    assert {approval_table, result_table} <= tables
    assert {
        "ix_agent_rollback_approval_effect",
        "ix_agent_rollback_approval_scope",
        "ix_agent_rollback_approval_note",
        "ix_agent_rollback_approval_expiry",
        "ix_agent_rollback_approval_evidence",
        "ix_agent_rollback_approval_idempotency",
        "ix_agent_rollback_approval_grant",
    } <= approval_indexes
    assert {
        "ix_agent_rollback_result_approval",
        "ix_agent_rollback_result_effect",
        "ix_agent_rollback_result_idempotency",
        "ix_agent_rollback_result_scope",
        "ix_agent_rollback_result_note",
        "ix_controlled_agent_reversible_write_rollback_results_trace_id",
    } <= result_indexes
    assert triggers == {
        f"trg_{approval_table}_update_blocked",
        f"trg_{approval_table}_delete_blocked",
        f"trg_{result_table}_update_blocked",
        f"trg_{result_table}_delete_blocked",
    }
    assert approval_sql is not None and result_sql is not None
    assert "uq_agent_rollback_approval_execution_scope_idempotency" in approval_sql[0]
    assert "ck_agent_rollback_approval_action_shape" in approval_sql[0]
    assert "fk_agent_rollback_approval_effect_scope" in approval_sql[0]
    assert "ck_agent_rollback_result_action_shape" in result_sql[0]
    assert "fk_agent_rollback_result_effect_scope" in result_sql[0]

    command.downgrade(config, "20260724_0013")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN (?, ?)",
                (approval_table, result_table),
            )
        }
    assert revision == ("20260724_0013",)
    assert approval_table not in tables and result_table not in tables
    assert "controlled_agent_reversible_write_rollback_evidence" in tables
    assert not triggers

    command.upgrade(config, "20260724_0014")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("20260724_0014",)
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0025"]


def test_execution_reliability_migration_backfills_and_cycles_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "execution-reliability-migration-cycle.db"
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260724_0014")
    execution_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO controlled_agent_executions
               (id, user_id, workspace_id, schema_version, role, context_snapshot_id,
                context_digest, plan_id, plan_digest, grant_id, created_at)
               VALUES (?, ?, ?, 'controlled-agent-v1', 'evidence_verifier', ?, ?, ?, ?, ?, ?)""",
            (
                execution_id,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                "a" * 64,
                uuid.uuid4().hex,
                "b" * 64,
                uuid.uuid4().hex,
                "2026-07-24 12:00:00.000000",
            ),
        )

    command.upgrade(config, "20260724_0015")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(controlled_agent_executions)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(controlled_agent_executions)")
        }
        table_sql = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type = 'table' AND name = 'controlled_agent_executions'"""
        ).fetchone()
        reliability = connection.execute(
            """SELECT deadline_at, max_attempts, attempt_count, lease_generation
               FROM controlled_agent_executions WHERE id = ?""",
            (execution_id,),
        ).fetchone()
    assert revision == ("20260724_0015",)
    assert columns["deadline_at"][3] == 1
    assert {
        "ix_agent_execution_claimable",
        "ix_agent_execution_lease_expiry",
    } <= indexes
    assert table_sql is not None
    assert "ck_agent_execution_attempt_count_bounded" in table_sql[0]
    assert "ck_agent_execution_lease_shape" in table_sql[0]
    assert "ck_agent_execution_terminal_shape" in table_sql[0]
    assert reliability == ("2026-07-24 12:15:00", 3, 0, 0)

    command.downgrade(config, "20260724_0014")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        column_names = {
            row[1] for row in connection.execute("PRAGMA table_info(controlled_agent_executions)")
        }
    assert revision == ("20260724_0014",)
    assert "deadline_at" not in column_names
    assert "lease_owner_id" not in column_names

    command.upgrade(config, "20260724_0015")
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("20260724_0015",)
    assert ScriptDirectory.from_config(config).get_heads() == ["20260725_0025"]
