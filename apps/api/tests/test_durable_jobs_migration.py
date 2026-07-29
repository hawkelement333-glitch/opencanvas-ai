from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def _config(database_path: Path) -> Config:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(api_root / "alembic.ini")
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_0028_preserves_legacy_job_and_refuses_non_disposable_downgrade(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "durable-job-backfill.db"
    config = _config(database_path)
    system_user_id = "00000000000040008000000000000001"
    workspace_id = uuid.uuid4().hex
    canvas_id = uuid.uuid4().hex
    document_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    timestamp = "2026-07-28 12:00:00+00:00"

    command.upgrade(config, "20260726_0027")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO workspaces
                (id, name, owner_id, version, lifecycle_state, metadata,
                 settings_payload, created_at, updated_at)
            VALUES (?, 'Durable backfill', ?, 1, 'active', '{}', '{}', ?, ?)
            """,
            (workspace_id, system_user_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO canvases
                (id, workspace_id, name, viewport_x, viewport_y, viewport_zoom,
                 revision, created_at, updated_at)
            VALUES (?, ?, 'Durable canvas', 0, 0, 1, 0, ?, ?)
            """,
            (canvas_id, workspace_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO documents
                (id, canvas_id, file_name, file_type, media_type, file_size_bytes,
                 content_sha256, status, processing_stage, chunk_count, retry_count,
                 version_count, current_version, created_at, updated_at)
            VALUES (?, ?, 'legacy.txt', 'txt', 'text/plain', 17, ?, 'ready',
                    'ready', 1, 0, 1, 1, ?, ?)
            """,
            (document_id, canvas_id, "a" * 64, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO document_processing_jobs
                (id, user_id, workspace_id, document_id, attempt, status,
                 idempotency_key, retryable, available_at, started_at,
                 completed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 2, 'ready', ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                system_user_id,
                workspace_id,
                document_id,
                f"legacy:{job_id}",
                timestamp,
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()

    command.upgrade(config, "20260726_0028")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260726_0028",
        )
        assert connection.execute(
            """
            SELECT id, canvas_id, legacy_backfill, request_id, authority_generation,
                   status, attempt
            FROM document_processing_jobs
            """
        ).fetchone() == (job_id, canvas_id, 1, None, None, "ready", 2)
        assert connection.execute(
            """
            SELECT attempt_id, job_run_id, delivery_id, attempt_number,
                   lease_generation, outcome, started_at, completed_at
            FROM durable_job_attempts
            """
        ).fetchone() == (
            job_id,
            job_id,
            None,
            2,
            0,
            "legacy_ready",
            timestamp,
            timestamp,
        )
        assert connection.execute("SELECT COUNT(*) FROM durable_job_requests").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM durable_queue_deliveries").fetchone() == (
            0,
        )
        domain_event_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'domain_events'
            """
        ).fetchone()
        assert domain_event_sql is not None
        assert "job.completed" in domain_event_sql[0]
        assert "durable_job" in domain_event_sql[0]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE durable_job_attempts SET outcome = 'legacy_failed'")

    command.downgrade(config, "20260726_0027")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT id, status, attempt FROM document_processing_jobs"
        ).fetchone() == (job_id, "ready", 2)
        assert "durable_job_attempts" not in {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    command.upgrade(config, "20260726_0028")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE document_processing_jobs SET legacy_backfill = 0 WHERE id = ?",
            (job_id,),
        )
        connection.commit()
    with pytest.raises(RuntimeError, match="before new durable work exists"):
        command.downgrade(config, "20260726_0027")
