from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.db.runtime import (
    MIGRATION_ADVISORY_LOCK_ID,
    DatabaseRuntimeError,
    validate_database_runtime,
)


@pytest.mark.parametrize("lock_available", [True, False])
async def test_runtime_probe_uses_shared_transaction_lock_and_preserves_rejection(
    lock_available: bool,
) -> None:
    settings = Settings()
    connection = AsyncMock()
    connection.dialect = SimpleNamespace(name="postgresql")

    def execute(statement, *_args):
        sql = str(statement)
        if sql == "SHOW server_version_num":
            return Mock(scalar_one=Mock(return_value=170_005))
        if sql == "SHOW transaction_isolation":
            return Mock(scalar_one=Mock(return_value="read committed"))
        if "pg_extension" in sql:
            return Mock(scalar_one_or_none=Mock(return_value="0.8.1"))
        if "alembic_version" in sql:
            return Mock(scalar_one_or_none=Mock(return_value=settings.database_expected_revision))
        if "pg_try_advisory" in sql:
            return Mock(scalar_one=Mock(return_value=lock_available))
        if "pg_roles" in sql:
            return Mock(one=Mock(return_value=("api", False, False, False, False, False, False)))
        return Mock()

    connection.execute.side_effect = execute
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = Mock()
    engine.connect.return_value = context

    if lock_available:
        report = await validate_database_runtime(engine, settings, expected_role=DatabaseRole.API)
        assert report.database_user == "api"
        assert report.schema_revision == settings.database_expected_revision
    else:
        with pytest.raises(DatabaseRuntimeError, match=r"^database_migration_in_progress$"):
            await validate_database_runtime(engine, settings, expected_role=DatabaseRole.API)

    lock_call = connection.execute.call_args_list[5]
    assert str(lock_call.args[0]) == (
        "SELECT pg_catalog.pg_try_advisory_xact_lock_shared(:lock_id)"
    )
    assert lock_call.args[1] == {"lock_id": MIGRATION_ADVISORY_LOCK_ID}
    assert connection.execute.call_count == (7 if lock_available else 6)
    context.__aexit__.assert_awaited_once()


async def test_runtime_probe_database_failure_remains_sanitized() -> None:
    connection = AsyncMock()
    connection.execute.side_effect = SQLAlchemyError("private-host secret")
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = Mock()
    engine.connect.return_value = context

    with pytest.raises(DatabaseRuntimeError, match=r"^database_unavailable$"):
        await validate_database_runtime(engine, Settings(), expected_role=DatabaseRole.API)
    context.__aexit__.assert_awaited_once()
