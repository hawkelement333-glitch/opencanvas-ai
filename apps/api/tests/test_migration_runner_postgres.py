from __future__ import annotations

import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from opencanvas_api.db.migrations import run_guarded_postgresql_migration
from opencanvas_api.db.runtime import MIGRATION_ADVISORY_LOCK_ID
from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_runner_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _asyncpg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _runner_engine(database_url: str, application_name: str):
    return create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"application_name": application_name}},
    )


@pytest.mark.asyncio
async def test_postgresql_guard_excludes_competitor_and_releases_after_success(
    postgres_runner_database_url: str,
) -> None:
    application_name = f"opencanvas-migration-runner-{uuid.uuid4().hex}"
    owner = await asyncpg.connect(_asyncpg_url(postgres_runner_database_url))
    engine = _runner_engine(postgres_runner_database_url, application_name)
    try:
        assert await owner.fetchval("SELECT pg_try_advisory_lock($1)", MIGRATION_ADVISORY_LOCK_ID)
        async with engine.connect() as contender:
            with pytest.raises(RuntimeError, match="already active"):
                await contender.run_sync(
                    lambda connection: run_guarded_postgresql_migration(
                        connection,
                        expected_current=None,
                        expected_target=None,
                        migrate=lambda: None,
                    )
                )
            assert not contender.in_transaction()

        assert await owner.fetchval("SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_LOCK_ID)

        async with engine.connect() as successful:
            await successful.run_sync(
                lambda connection: run_guarded_postgresql_migration(
                    connection,
                    expected_current=None,
                    expected_target=None,
                    migrate=lambda: None,
                )
            )
            assert not successful.in_transaction()

        verifier = await asyncpg.connect(_asyncpg_url(postgres_runner_database_url))
        try:
            assert await verifier.fetchval(
                "SELECT pg_try_advisory_lock($1)", MIGRATION_ADVISORY_LOCK_ID
            )
            assert await verifier.fetchval(
                "SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_LOCK_ID
            )
        finally:
            await verifier.close()
    finally:
        await engine.dispose()
        assert (
            await owner.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name = $1",
                application_name,
            )
            == 0
        )
        await owner.close()


@pytest.mark.asyncio
async def test_postgresql_guard_rolls_back_before_unlock_and_preserves_failure(
    postgres_runner_database_url: str,
) -> None:
    application_name = f"opencanvas-migration-runner-{uuid.uuid4().hex}"
    engine = _runner_engine(postgres_runner_database_url, application_name)
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="division by zero") as raised:
                await connection.run_sync(
                    lambda sync_connection: run_guarded_postgresql_migration(
                        sync_connection,
                        expected_current=None,
                        expected_target=None,
                        migrate=lambda: sync_connection.execute(text("SELECT 1 / 0")),
                    )
                )
            assert "pg_advisory_unlock" not in str(raised.value)
            assert not connection.in_transaction()

        verifier = await asyncpg.connect(_asyncpg_url(postgres_runner_database_url))
        try:
            assert await verifier.fetchval(
                "SELECT pg_try_advisory_lock($1)", MIGRATION_ADVISORY_LOCK_ID
            )
            assert await verifier.fetchval(
                "SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_LOCK_ID
            )
        finally:
            await verifier.close()
    finally:
        await engine.dispose()

    verifier = await asyncpg.connect(_asyncpg_url(postgres_runner_database_url))
    try:
        assert (
            await verifier.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name = $1",
                application_name,
            )
            == 0
        )
    finally:
        await verifier.close()
