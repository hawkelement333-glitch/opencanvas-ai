from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres
REVISION = "20260716_0001"


@pytest.fixture
def postgres_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _config(database_url: str) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _connect(database_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))


async def _restrict_extension_commands(database_url: str, *, installed: bool) -> None:
    connection = await _connect(database_url)
    try:
        if installed:
            await connection.execute("CREATE EXTENSION vector")
        await connection.execute("""
            CREATE FUNCTION public.test_deny_extension_commands() RETURNS event_trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'synthetic managed extension permission gate'
                    USING ERRCODE = 'insufficient_privilege';
            END;
            $$;
            CREATE EVENT TRIGGER test_deny_extension_commands ON ddl_command_start
                WHEN TAG IN ('CREATE EXTENSION')
                EXECUTE FUNCTION public.test_deny_extension_commands();
        """)
        # Reproduce the production error: Azure checks permission before the
        # redundant CREATE can become an IF NOT EXISTS no-op.
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
            await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        assert denied.value.sqlstate == "42501"
    finally:
        await connection.close()


async def _assert_state(database_url: str, *, installed: bool, migrated: bool) -> None:
    connection = await _connect(database_url)
    try:
        assert await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'vector')"
        ) is installed
        if migrated:
            assert await connection.fetchval("TABLE public.alembic_version") == REVISION
            assert await connection.fetchval("SELECT to_regclass('public.canvases')") is not None
    finally:
        await connection.close()


async def _assert_denied_upgrade_does_not_change_schema(database_url: str) -> None:
    revision = ScriptDirectory.from_config(_config(database_url)).get_revision(REVISION)
    assert revision is not None
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            def upgrade(sync_connection: Connection) -> None:
                with Operations.context(MigrationContext.configure(connection=sync_connection)):
                    revision.module.upgrade()

            with pytest.raises(DBAPIError) as denied:
                await connection.run_sync(upgrade)
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
            await connection.rollback()
    finally:
        await engine.dispose()
    await _assert_state(database_url, installed=False, migrated=False)
    raw = await _connect(database_url)
    try:
        assert await raw.fetchval("SELECT to_regclass('public.canvases')") is None
        assert await raw.fetchval("SELECT to_regclass('public.alembic_version')") is None
    finally:
        await raw.close()


@pytest.mark.parametrize("case", ["present-restricted", "fresh-installer", "fresh-restricted"])
def test_initial_postgres_migration_installs_vector_only_when_absent(
    postgres_database_url: str, case: str,
) -> None:
    installed = case == "present-restricted"
    if case != "fresh-installer":
        asyncio.run(_restrict_extension_commands(postgres_database_url, installed=installed))
    asyncio.run(_assert_state(postgres_database_url, installed=installed, migrated=False))
    config = _config(postgres_database_url)
    if case == "fresh-restricted":
        asyncio.run(_assert_denied_upgrade_does_not_change_schema(postgres_database_url))
        return
    command.upgrade(config, REVISION)
    asyncio.run(_assert_state(postgres_database_url, installed=True, migrated=True))
