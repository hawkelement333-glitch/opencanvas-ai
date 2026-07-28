from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def _config(database_path: Path) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def test_0026_backfills_ready_output_and_preserves_legacy_rows_across_cycle(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "indexer-backfill.db"
    config = _config(database_path)
    workspace_id = uuid.uuid4().hex
    canvas_id = uuid.uuid4().hex
    document_id = uuid.uuid4().hex
    version_id = uuid.uuid4().hex
    chunk_id = uuid.uuid4().hex
    embedding_id = uuid.uuid4().hex
    system_user_id = "00000000000040008000000000000001"
    source_digest = "a" * 64
    timestamp = "2026-07-27 12:00:00+00:00"

    command.upgrade(config, "20260725_0025")
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO workspaces
                (id, name, owner_id, version, lifecycle_state, metadata,
                 settings_payload, created_at, updated_at)
            VALUES (?, 'Indexer backfill', ?, 1, 'active', '{}', '{}', ?, ?)
            """,
            (workspace_id, system_user_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO canvases
                (id, workspace_id, name, viewport_x, viewport_y, viewport_zoom,
                 revision, created_at, updated_at)
            VALUES (?, ?, 'Indexer backfill canvas', 0, 0, 1, 0, ?, ?)
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
            VALUES (?, ?, 'backfill.txt', 'txt', 'text/plain', 17, ?, 'ready',
                    'ready', 1, 1, 'Preserved passage.', 0, 1, 1, ?, ?)
            """,
            (document_id, canvas_id, source_digest, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO document_versions
                (id, document_id, version, file_name, file_type, media_type,
                 file_size_bytes, content_sha256, storage_key, extracted_text,
                 status, created_at, updated_at)
            VALUES (?, ?, 1, 'backfill.txt', 'txt', 'text/plain', 17, ?,
                    'backfill/source.txt', 'Preserved passage.', 'ready', ?, ?)
            """,
            (version_id, document_id, source_digest, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO document_chunks
                (id, document_id, document_version, chunk_index, content,
                 page_number, heading, char_start, char_end, created_at, updated_at)
            VALUES (?, ?, 1, 0, 'Preserved passage.', 1, NULL, 0, 18, ?, ?)
            """,
            (chunk_id, document_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO document_embeddings
                (id, document_id, chunk_id, provider, model, dimensions, embedding,
                 created_at, updated_at)
            VALUES (?, ?, ?, 'mock', 'deterministic-mock-v1', 1536, ?, ?, ?)
            """,
            (
                embedding_id,
                document_id,
                chunk_id,
                json.dumps([0.0] * 1536),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()

    command.upgrade(config, "20260726_0026")
    with sqlite3.connect(database_path) as connection:
        projection = connection.execute(
            """
            SELECT workspace_id, canvas_id, document_id, document_version_id,
                   document_version, source_sha256, chunk_count, provenance_state
            FROM index_compatibility_projections
            """
        ).fetchone()
        assert projection == (
            workspace_id,
            canvas_id,
            document_id,
            version_id,
            1,
            source_digest,
            1,
            "unverified_legacy",
        )
        head = connection.execute(
            """
            SELECT workspace_id, canvas_id, activation_kind, revision_id,
                   publication_id, compatibility_projection_id, generation
            FROM retrieval_heads WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()
        assert head is not None
        assert head[:5] == (
            workspace_id,
            canvas_id,
            "compatibility",
            None,
            None,
        )
        assert head[5] is not None
        assert head[6] == 1
        assert connection.execute(
            "SELECT content FROM document_chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone() == ("Preserved passage.",)
        assert connection.execute(
            "SELECT provider, model FROM document_embeddings WHERE id = ?",
            (embedding_id,),
        ).fetchone() == ("mock", "deterministic-mock-v1")
        triggers = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        }
        assert {
            "trg_pipeline_manifests_update_blocked",
            "trg_ingestion_requests_delete_blocked",
            "trg_index_revisions_update_blocked",
            "trg_index_publications_delete_blocked",
        } <= triggers
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                """
                UPDATE index_compatibility_projections
                SET provenance_state = 'unverified_legacy'
                WHERE document_id = ?
                """,
                (document_id,),
            )

    command.downgrade(config, "20260725_0025")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "index_compatibility_projections" not in tables
        assert "retrieval_heads" not in tables
        assert connection.execute(
            "SELECT status, chunk_count FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone() == ("ready", 1)
        assert connection.execute(
            "SELECT content FROM document_chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone() == ("Preserved passage.",)

    command.upgrade(config, "20260726_0026")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260726_0026",
        )
        assert connection.execute(
            """
            SELECT projection_id FROM index_compatibility_projections
            WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone() == (head[5],)
