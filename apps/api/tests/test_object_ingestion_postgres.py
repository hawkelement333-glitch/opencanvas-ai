from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres

APPEND_ONLY_TABLES = {
    "malware_scan_requests",
    "malware_scan_results",
    "object_deletion_requests",
    "object_ingestion_audit_events",
    "object_promotions",
    "storage_object_lifecycle_transitions",
    "storage_object_versions",
    "storage_objects",
    "upload_session_transitions",
    "upload_sessions",
}


@pytest.fixture
def postgres_object_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _config(database_url: str) -> Config:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(api_root / "alembic.ini")
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _asyncpg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def test_postgresql_0027_cycle_and_append_only_catalog(
    postgres_object_database_url: str,
) -> None:
    config = _config(postgres_object_database_url)
    command.upgrade(config, "20260726_0027")
    asyncio.run(_assert_upgraded(postgres_object_database_url))
    command.downgrade(config, "20260726_0026")
    asyncio.run(_assert_downgraded(postgres_object_database_url))
    command.upgrade(config, "20260726_0027")
    asyncio.run(_assert_upgraded(postgres_object_database_url))


async def _assert_upgraded(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "20260726_0027"
        )
        assert int(await connection.fetchval("SHOW server_version_num")) // 10_000 == 17
        assert await connection.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )
        tables = {
            str(value)
            for value in await connection.fetch(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public' AND tablename = ANY($1::text[])
                """,
                sorted(APPEND_ONLY_TABLES),
            )
            for value in (value["tablename"],)
        }
        assert tables == APPEND_ONLY_TABLES
        triggers = await connection.fetch(
            """
            SELECT c.relname AS table_name, t.tgname AS trigger_name
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            WHERE NOT t.tgisinternal AND c.relname = ANY($1::text[])
            """,
            sorted(APPEND_ONLY_TABLES),
        )
        assert len(triggers) == len(APPEND_ONLY_TABLES) * 2
    finally:
        await connection.close()


async def _assert_downgraded(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "20260726_0026"
        )
        assert not await connection.fetchval(
            "SELECT to_regclass('public.upload_sessions') IS NOT NULL"
        )
    finally:
        await connection.close()
