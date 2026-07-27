from __future__ import annotations

from collections.abc import Callable

from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection

from opencanvas_api.db.runtime import MIGRATION_ADVISORY_LOCK_ID


def _release_postgresql_migration_lock(connection: Connection) -> None:
    try:
        released = bool(
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            ).scalar_one()
        )
        if not released:
            raise RuntimeError("database migration lock ownership was lost")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def run_guarded_postgresql_migration(
    connection: Connection,
    *,
    expected_current: str | None,
    expected_target: str | None,
    migrate: Callable[[], None],
) -> None:
    locked = bool(
        connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
        ).scalar_one()
    )
    if not locked:
        connection.rollback()
        raise RuntimeError("another database migration is already active")
    try:
        current = MigrationContext.configure(connection).get_current_revision()
        normalized_expected = None if expected_current == "base" else expected_current
        if expected_current is not None and current != normalized_expected:
            raise RuntimeError("database revision does not match the expected deployment state")

        migrate()

        current = MigrationContext.configure(connection).get_current_revision()
        if expected_target is not None and current != expected_target:
            raise RuntimeError("database migration did not reach the expected release revision")
    except Exception as migration_error:
        try:
            connection.rollback()
        except Exception:
            migration_error.add_note("PostgreSQL migration transaction cleanup also failed safely.")
            raise migration_error from None
        try:
            _release_postgresql_migration_lock(connection)
        except Exception:
            migration_error.add_note(
                "PostgreSQL migration advisory-lock cleanup also failed safely."
            )
        raise
    else:
        _release_postgresql_migration_lock(connection)


__all__ = ["run_guarded_postgresql_migration"]
