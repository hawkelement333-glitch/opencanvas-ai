from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from opencanvas_api.db.migrations import run_guarded_postgresql_migration
from scripts import migrate as migration_script


def _connection(*, lock_available: bool = True) -> Mock:
    connection = Mock()
    connection.dialect = SimpleNamespace(name="postgresql")
    lock_result = Mock()
    lock_result.scalar_one.return_value = lock_available
    unlock_result = Mock()
    unlock_result.scalar_one.return_value = True
    connection.execute.side_effect = [lock_result, unlock_result]
    return connection


def _migration_context(*revisions: str | None) -> Mock:
    contexts = []
    for revision in revisions:
        context = Mock()
        context.get_current_revision.return_value = revision
        contexts.append(context)
    return Mock(side_effect=contexts)


def test_guarded_migration_locks_verifies_heads_and_releases() -> None:
    connection = _connection()
    migrate = Mock()
    with patch(
        "opencanvas_api.db.migrations.MigrationContext.configure",
        _migration_context("20260725_0024", "20260725_0025"),
    ):
        run_guarded_postgresql_migration(
            connection,
            expected_current="20260725_0024",
            expected_target="20260725_0025",
            migrate=migrate,
        )

    migrate.assert_called_once_with()
    assert connection.execute.call_count == 2
    assert "pg_try_advisory_lock" in str(connection.execute.call_args_list[0].args[0])
    assert "pg_advisory_unlock" in str(connection.execute.call_args_list[1].args[0])


def test_competing_migration_fails_without_running() -> None:
    connection = _connection(lock_available=False)
    migrate = Mock()

    with pytest.raises(RuntimeError, match="already active"):
        run_guarded_postgresql_migration(
            connection,
            expected_current="20260725_0024",
            expected_target="20260725_0025",
            migrate=migrate,
        )

    migrate.assert_not_called()
    assert connection.execute.call_count == 1


@pytest.mark.parametrize(
    ("revisions", "migration_error", "message"),
    [
        (("20260725_0023",), None, "expected deployment state"),
        (("20260725_0024", "20260725_0024"), None, "expected release revision"),
        (("20260725_0024",), RuntimeError("bounded failure"), "bounded failure"),
    ],
)
def test_guarded_migration_releases_lock_on_rejection_or_failure(
    revisions: tuple[str, ...],
    migration_error: RuntimeError | None,
    message: str,
) -> None:
    connection = _connection()
    migrate = Mock(side_effect=migration_error)
    with (
        patch(
            "opencanvas_api.db.migrations.MigrationContext.configure",
            _migration_context(*revisions),
        ),
        pytest.raises(RuntimeError, match=message),
    ):
        run_guarded_postgresql_migration(
            connection,
            expected_current="20260725_0024",
            expected_target="20260725_0025",
            migrate=migrate,
        )

    assert "pg_advisory_unlock" in str(connection.execute.call_args_list[-1].args[0])


def test_migration_command_suppresses_raw_connection_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        migration_script,
        "run",
        Mock(side_effect=RuntimeError("postgresql://user:secret@private-host/database")),
    )
    monkeypatch.setattr("sys.argv", ["migrate"])

    result = migration_script.main()

    captured = capsys.readouterr()
    assert result == 1
    assert "Migration failed safely." in captured.err
    assert "secret" not in captured.err
    assert "private-host" not in captured.err
