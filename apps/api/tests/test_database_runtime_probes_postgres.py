from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager

import asyncpg
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION, DatabaseRole, Settings
from opencanvas_api.db.runtime import (
    MIGRATION_ADVISORY_LOCK_ID,
    DatabaseRuntimeError,
    validate_database_runtime,
)
from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def runtime_probe_database_url() -> Iterator[str]:
    with contextmanager(disposable_postgres_database)(upgrade_to=None) as url:

        async def initialize() -> None:
            connection = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql", 1))
            try:
                await connection.execute("CREATE EXTENSION vector")
                await connection.execute("CREATE TABLE public.alembic_version (version_num text)")
                await connection.execute(
                    "INSERT INTO public.alembic_version VALUES ($1)", EXPECTED_DATABASE_REVISION
                )
            finally:
                await connection.close()

        asyncio.run(initialize())
        yield url


class _PausedProbeEngine:
    """Pause after a real PostgreSQL lock result without replacing database behavior."""

    def __init__(self, engine, after_lock: Callable[[], Awaitable[object]]) -> None:
        self.engine = engine
        self.after_lock = after_lock

    @asynccontextmanager
    async def connect(self):
        async with self.engine.connect() as connection:
            after_lock = self.after_lock

            class Connection:
                dialect = connection.dialect

                async def execute(self, statement, *args):
                    result = await connection.execute(statement, *args)
                    if "pg_try_advisory" in str(statement):
                        await after_lock()
                    return result

            yield Connection()


async def _assert_exclusive_available(url: str) -> None:
    verifier = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql", 1))
    try:
        assert await verifier.fetchval(
            "SELECT pg_try_advisory_lock($1)", MIGRATION_ADVISORY_LOCK_ID
        )
        assert await verifier.fetchval("SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_LOCK_ID)
    finally:
        await verifier.close()


async def test_eight_concurrent_runtime_probes_share_lock_and_release(
    runtime_probe_database_url: str,
) -> None:
    engine = create_async_engine(runtime_probe_database_url, pool_size=8, max_overflow=0)
    barrier = asyncio.Barrier(8)
    probes = _PausedProbeEngine(engine, barrier.wait)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    validate_database_runtime(probes, Settings(), expected_role=DatabaseRole.API)
                    for _ in range(8)
                ),
                return_exceptions=True,
            ),
            timeout=10,
        )
        assert all(not isinstance(result, BaseException) for result in results), results
        # Keep the pool alive: disposing it would conceal leaked session locks.
        await _assert_exclusive_available(runtime_probe_database_url)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("transaction_lock", [False, True])
async def test_exclusive_migration_rejects_runtime_probe(
    runtime_probe_database_url: str,
    transaction_lock: bool,
) -> None:
    engine = create_async_engine(runtime_probe_database_url)
    owner = await asyncpg.connect(
        runtime_probe_database_url.replace("postgresql+asyncpg", "postgresql", 1)
    )
    try:
        await owner.execute("BEGIN")
        function = "pg_try_advisory_xact_lock" if transaction_lock else "pg_try_advisory_lock"
        assert await owner.fetchval(f"SELECT {function}($1)", MIGRATION_ADVISORY_LOCK_ID)
        with pytest.raises(DatabaseRuntimeError, match=r"^database_migration_in_progress$"):
            await validate_database_runtime(engine, Settings(), expected_role=DatabaseRole.API)
        await owner.execute("ROLLBACK")
        if not transaction_lock:
            assert await owner.fetchval("SELECT pg_advisory_unlock($1)", MIGRATION_ADVISORY_LOCK_ID)
        await validate_database_runtime(engine, Settings(), expected_role=DatabaseRole.API)
        await _assert_exclusive_available(runtime_probe_database_url)
    finally:
        await owner.close()
        await engine.dispose()


@pytest.mark.parametrize("cancel", [False, True])
async def test_runtime_probe_failure_or_cancellation_releases_transaction_lock(
    runtime_probe_database_url: str,
    cancel: bool,
) -> None:
    engine = create_async_engine(runtime_probe_database_url, pool_size=1, max_overflow=0)
    acquired = asyncio.Event()

    async def interrupt() -> None:
        acquired.set()
        if cancel:
            await asyncio.Event().wait()
        raise SQLAlchemyError("private database diagnostic")

    task = asyncio.create_task(
        validate_database_runtime(
            _PausedProbeEngine(engine, interrupt), Settings(), expected_role=DatabaseRole.API
        )
    )
    try:
        await asyncio.wait_for(acquired.wait(), timeout=10)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(DatabaseRuntimeError, match=r"^database_unavailable$"):
                await task
        await _assert_exclusive_available(runtime_probe_database_url)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
