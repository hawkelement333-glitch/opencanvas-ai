from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres

SYSTEM_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
CANVAS_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")
OBJECT_ID = uuid.UUID("30000000-0000-4000-8000-000000000001")


@pytest.fixture
def postgres_migration_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _config(database_url: str) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _connect(database_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))


async def _seed_0004(database_url: str) -> None:
    connection = await _connect(database_url)
    try:
        await connection.execute(
            "INSERT INTO canvases (id, name) VALUES ($1, 'Migration 0005 canvas')",
            CANVAS_ID,
        )
        await connection.execute(
            """INSERT INTO workspaces
               (id, name, owner_id, lifecycle_state, legacy_canvas_id)
               VALUES ($1, 'Migration 0005 workspace', NULL, 'active', $2)""",
            WORKSPACE_ID,
            CANVAS_ID,
        )
        await connection.execute(
            """INSERT INTO canonical_objects
               (id, workspace_id, object_type, lifecycle_state)
               VALUES ($1, $2, 'note', 'active')""",
            OBJECT_ID,
            WORKSPACE_ID,
        )
    finally:
        await connection.close()


async def _assert_0005(database_url: str) -> None:
    connection = await _connect(database_url)
    try:
        workspace = await connection.fetchrow(
            """SELECT id, owner_id, settings_payload, deleted_at
               FROM workspaces WHERE id = $1""",
            WORKSPACE_ID,
        )
        assert workspace is not None
        assert workspace["id"] == WORKSPACE_ID
        assert workspace["owner_id"] == SYSTEM_USER_ID
        assert json.loads(workspace["settings_payload"]) == {}
        assert workspace["deleted_at"] is None
        assert (
            await connection.fetchval(
                "SELECT workspace_id FROM canvases WHERE id = $1",
                CANVAS_ID,
            )
            == WORKSPACE_ID
        )
        assert (
            await connection.fetchval(
                "SELECT workspace_id FROM canonical_objects WHERE id = $1",
                OBJECT_ID,
            )
            == WORKSPACE_ID
        )

        constraints = {
            row["conname"]: (row["contype"], row["definition"])
            for row in await connection.fetch(
                """SELECT c.conname, c.contype::text AS contype,
                          pg_get_constraintdef(c.oid) AS definition
                   FROM pg_constraint c
                   JOIN pg_class t ON t.oid = c.conrelid
                   WHERE t.relname IN ('workspaces', 'canonical_objects', 'canvases')"""
            )
        }
        assert constraints["workspaces_pkey"][0] == "p"
        assert constraints["canonical_objects_workspace_id_fkey"] == (
            "f",
            "FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT",
        )
        assert constraints["fk_workspaces_owner_id_users"] == (
            "f",
            "FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE",
        )
        assert constraints["fk_canvases_workspace_id_workspaces"] == (
            "f",
            "FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE",
        )
        assert await connection.fetchval(
            """SELECT is_nullable = 'NO'
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = 'workspaces'
                 AND column_name = 'owner_id'"""
        )
        indexes = {
            row["indexname"]
            for row in await connection.fetch(
                """SELECT indexname FROM pg_indexes
                   WHERE schemaname = 'public' AND tablename = 'workspaces'"""
            )
        }
        assert {
            "workspaces_pkey",
            "workspaces_legacy_canvas_id_key",
            "ix_workspaces_owner_id",
            "ix_workspaces_lifecycle_state",
        } <= indexes
        assert await connection.fetchval("SELECT count(*) FROM workspaces") == 1
        assert await connection.fetchval("SELECT count(*) FROM canonical_objects") == 1
    finally:
        await connection.close()


async def _assert_0004(database_url: str) -> None:
    connection = await _connect(database_url)
    try:
        columns = {
            row["column_name"]: row["is_nullable"]
            for row in await connection.fetch(
                """SELECT column_name, is_nullable
                   FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'workspaces'"""
            )
        }
        assert columns["owner_id"] == "YES"
        assert "settings_payload" not in columns
        assert "deleted_at" not in columns
        assert (
            await connection.fetchval(
                "SELECT workspace_id FROM canonical_objects WHERE id = $1",
                OBJECT_ID,
            )
            == WORKSPACE_ID
        )
        assert await connection.fetchval(
            """SELECT EXISTS (
                   SELECT 1 FROM pg_constraint c
                   JOIN pg_class t ON t.oid = c.conrelid
                   WHERE t.relname = 'workspaces'
                     AND c.conname = 'workspaces_pkey'
                     AND c.contype = 'p'
               )"""
        )
        assert await connection.fetchval(
            """SELECT EXISTS (
                   SELECT 1 FROM pg_constraint c
                   JOIN pg_class t ON t.oid = c.conrelid
                   WHERE t.relname = 'canonical_objects'
                     AND c.conname = 'canonical_objects_workspace_id_fkey'
                     AND c.contype = 'f'
               )"""
        )
    finally:
        await connection.close()


def test_postgresql_migration_0005_preserves_seeded_workspace_dependencies(
    postgres_migration_database_url: str,
) -> None:
    config = _config(postgres_migration_database_url)

    command.upgrade(config, "20260717_0004")
    asyncio.run(_seed_0004(postgres_migration_database_url))

    command.upgrade(config, "20260718_0005")
    asyncio.run(_assert_0005(postgres_migration_database_url))

    command.downgrade(config, "20260717_0004")
    asyncio.run(_assert_0004(postgres_migration_database_url))

    command.upgrade(config, "20260718_0005")
    asyncio.run(_assert_0005(postgres_migration_database_url))
