from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config


def _config(database_path: Path) -> Config:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(api_root / "alembic.ini")
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_0027_backfills_legacy_as_unscanned_and_preserves_source_across_cycle(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "secure-object-backfill.db"
    config = _config(database_path)
    workspace_id = uuid.uuid4().hex
    canvas_id = uuid.uuid4().hex
    document_id = uuid.uuid4().hex
    version_id = uuid.uuid4().hex
    system_user_id = "00000000000040008000000000000001"
    source_digest = "a" * 64
    timestamp = "2026-07-28 12:00:00+00:00"

    command.upgrade(config, "20260726_0026")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO workspaces
                (id, name, owner_id, version, lifecycle_state, metadata,
                 settings_payload, created_at, updated_at)
            VALUES (?, 'Secure object backfill', ?, 1, 'active', '{}', '{}', ?, ?)
            """,
            (workspace_id, system_user_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO canvases
                (id, workspace_id, name, viewport_x, viewport_y, viewport_zoom,
                 revision, created_at, updated_at)
            VALUES (?, ?, 'Secure object canvas', 0, 0, 1, 0, ?, ?)
            """,
            (canvas_id, workspace_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO documents
                (id, canvas_id, file_name, file_type, media_type, file_size_bytes,
                 content_sha256, status, processing_stage, page_count, chunk_count,
                 extracted_text, retry_count, version_count, current_version,
                 created_at, updated_at)
            VALUES (?, ?, 'legacy.txt', 'txt', 'text/plain', 17, ?, 'ready',
                    'ready', 1, 1, 'Legacy passage.', 0, 1, 1, ?, ?)
            """,
            (document_id, canvas_id, source_digest, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO document_versions
                (id, document_id, version, file_name, file_type, media_type,
                 file_size_bytes, content_sha256, storage_key, extracted_text,
                 status, created_at, updated_at)
            VALUES (?, ?, 1, 'legacy.txt', 'txt', 'text/plain', 17, ?,
                    'legacy/source.txt', 'Legacy passage.', 'ready', ?, ?)
            """,
            (version_id, document_id, source_digest, timestamp, timestamp),
        )
        connection.commit()

    command.upgrade(config, "20260726_0027")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260726_0027",
        )
        version = connection.execute(
            """
            SELECT security_class, physical_key, provider_name, provider_version_id,
                   byte_size, content_sha256
            FROM storage_object_versions
            """
        ).fetchone()
        assert version == (
            "quarantine",
            "legacy/source.txt",
            "legacy",
            "legacy",
            17,
            source_digest,
        )
        assert connection.execute(
            """
            SELECT current_state, reason_code
            FROM storage_object_lifecycle_transitions
            """
        ).fetchone() == ("legacy_unscanned", "migration_backfill")
        assert connection.execute("SELECT COUNT(*) FROM malware_scan_results").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM object_promotions").fetchone() == (0,)
        try:
            connection.execute(
                "UPDATE storage_object_versions SET content_sha256 = ?",
                ("b" * 64,),
            )
        except sqlite3.IntegrityError as exc:
            assert "append-only" in str(exc)
        else:  # pragma: no cover - proves the migration trigger is mandatory
            raise AssertionError("storage object version mutation was not blocked")

    command.downgrade(config, "20260726_0026")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT storage_key, content_sha256 FROM document_versions"
        ).fetchone() == ("legacy/source.txt", source_digest)

    command.upgrade(config, "20260726_0027")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260726_0027",
        )
        assert connection.execute(
            "SELECT current_state FROM storage_object_lifecycle_transitions"
        ).fetchone() == ("legacy_unscanned",)
