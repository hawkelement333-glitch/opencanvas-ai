from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from opencanvas_api.core.config import DatabaseRole
from opencanvas_api.db.role_privileges import (
    configure_vector_runtime_functions,
    require_runtime_function_privileges,
)
from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


@pytest.mark.asyncio
async def test_provider_vector_baseline_cannot_expand_to_other_routines_or_grants(
    database_url: str,
) -> None:
    engine = create_async_engine(database_url)
    api, worker, bootstrap = (name + "_" + uuid4().hex for name in ("api", "worker", "bootstrap"))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                # These synthetic roles and ACLs exist only inside this test transaction.
                await connection.execute(text("CREATE ROLE azuresu SUPERUSER"))
                for principal in (api, worker, bootstrap):
                    await connection.execute(text(f"CREATE ROLE {principal} LOGIN"))
                await connection.execute(text("SET ROLE azuresu"))
                await connection.execute(text("CREATE EXTENSION vector"))
                await connection.execute(text("RESET ROLE"))
                await connection.execute(text("CREATE FUNCTION public.outside_vector() RETURNS int "
                                              "LANGUAGE sql AS 'SELECT 1'"))
                await connection.execute(text("REVOKE EXECUTE ON FUNCTION public.outside_vector() "
                                              "FROM PUBLIC"))
                await connection.execute(text(f"SET ROLE {bootstrap}"))
                await configure_vector_runtime_functions(
                    connection, api_principal=api, worker_principal=worker, managed=True,
                )
                observed = await require_runtime_function_privileges(
                    connection, DatabaseRole.API, principal=api, managed=True,
                )
                assert observed["effectiveExecuteCount"] == 118
                assert observed["providerPublicVectorRoutineCount"] == 118
                assert observed["providerPublicVectorExtensionVersion"] == (
                    await connection.scalar(text("SELECT extversion FROM pg_extension "
                                                 "WHERE extname='vector'"))
                )
                assert observed["requiredVectorSignatures"] == [
                    "public.cosine_distance(public.vector, public.vector)",
                    "public.vector(public.vector, pg_catalog.int4, pg_catalog.bool)",
                ]
                assert len(str(observed["providerPublicVectorInventorySha256"])) == 64
                with pytest.raises(RuntimeError, match="exact matrix"):
                    await require_runtime_function_privileges(
                        connection, DatabaseRole.API, principal=api,
                    )
                await connection.execute(text("RESET ROLE"))
                await connection.execute(text("GRANT EXECUTE ON FUNCTION public.outside_vector() "
                                              "TO PUBLIC"))
                with pytest.raises(RuntimeError, match="exact matrix"):
                    await require_runtime_function_privileges(
                        connection, DatabaseRole.WORKER, principal=worker, managed=True,
                    )
                await connection.execute(text("REVOKE EXECUTE ON FUNCTION public.outside_vector() "
                                              "FROM PUBLIC"))
                await connection.execute(text("GRANT EXECUTE ON FUNCTION "
                                              "public.cosine_distance(vector, vector) "
                                              f"TO {worker} WITH GRANT OPTION"))
                with pytest.raises(RuntimeError, match="ownership or PUBLIC grants differ"):
                    await require_runtime_function_privileges(
                        connection, DatabaseRole.WORKER, principal=worker, managed=True,
                    )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
