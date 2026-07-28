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

INDEXER_APPEND_ONLY_TABLES = {
    "pipeline_manifests",
    "ingestion_requests",
    "ingestion_request_transitions",
    "normalized_artifacts",
    "index_compatibility_projections",
    "index_revisions",
    "index_revision_chunks",
    "vector_materializations",
    "index_publications",
    "indexer_audit_events",
    "indexer_failures",
}


@pytest.fixture
def postgres_indexer_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _config(database_url: str) -> Config:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(api_root / "alembic.ini")
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _asyncpg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def test_postgresql_0026_cycle_and_append_only_trigger_catalog(
    postgres_indexer_database_url: str,
) -> None:
    config = _config(postgres_indexer_database_url)
    command.upgrade(config, "head")
    asyncio.run(_assert_upgraded(postgres_indexer_database_url))

    command.downgrade(config, "20260725_0025")
    asyncio.run(_assert_downgraded(postgres_indexer_database_url))

    command.upgrade(config, "20260726_0026")
    asyncio.run(_assert_reupgraded(postgres_indexer_database_url))


async def _assert_upgraded(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "20260726_0026"
        )
        assert int(await connection.fetchval("SHOW server_version_num")) // 10_000 == 17
        assert await connection.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )
        triggers = await connection.fetch(
            """SELECT c.relname AS table_name, t.tgname AS trigger_name
               FROM pg_trigger t
               JOIN pg_class c ON c.oid = t.tgrelid
               WHERE NOT t.tgisinternal
                 AND c.relname = ANY($1::text[])""",
            sorted(INDEXER_APPEND_ONLY_TABLES),
        )
        assert {(str(row["table_name"]), str(row["trigger_name"])) for row in triggers} == {
            (table, f"trg_{table}_{operation}_blocked")
            for table in INDEXER_APPEND_ONLY_TABLES
            for operation in ("update", "delete")
        }
        event_type_constraint = await connection.fetchval(
            """SELECT pg_get_constraintdef(oid)
                   FROM pg_constraint
                   WHERE conname = 'ck_domain_events_type'"""
        )
        assert str(event_type_constraint).count("ingestion.requested") == 1
    finally:
        await connection.close()


async def _assert_downgraded(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "20260725_0025"
        )
        assert not await connection.fetchval(
            """SELECT EXISTS (
                   SELECT 1 FROM information_schema.tables
                   WHERE table_schema = current_schema()
                     AND table_name = 'index_revisions'
               )"""
        )
    finally:
        await connection.close()


async def _assert_reupgraded(database_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(database_url))
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "20260726_0026"
        )
    finally:
        await connection.close()
