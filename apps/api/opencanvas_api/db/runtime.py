from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from opencanvas_api.core.config import AppMode, DatabaseRole, Settings

POSTGRESQL_MAJOR_VERSION = 17
MINIMUM_PGVECTOR_VERSION = (0, 7, 0)
MIGRATION_ADVISORY_LOCK_ID = 7_102_025_001


class DatabaseRuntimeError(RuntimeError):
    """Safe, closed runtime failure without connection or topology details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatabaseRuntimeReport:
    dialect: str
    schema_revision: str | None
    database_user: str | None


async def validate_database_runtime(
    engine: AsyncEngine,
    settings: Settings,
    *,
    expected_role: DatabaseRole,
) -> DatabaseRuntimeReport:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            if connection.dialect.name != "postgresql":
                return DatabaseRuntimeReport(
                    dialect=connection.dialect.name,
                    schema_revision=None,
                    database_user=None,
                )

            server_version = int(
                (await connection.execute(text("SHOW server_version_num"))).scalar_one()
            )
            isolation = str(
                (await connection.execute(text("SHOW transaction_isolation"))).scalar_one()
            ).lower()
            if isolation != "read committed":
                raise DatabaseRuntimeError("transaction_isolation_incompatible")

            vector_version = (
                await connection.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
            ).scalar_one_or_none()
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            validate_postgresql_capabilities(
                server_version=server_version,
                vector_version=None if vector_version is None else str(vector_version),
                schema_revision=None if revision is None else str(revision),
                expected_revision=settings.database_expected_revision,
            )

            lock_available = bool(
                (
                    await connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                    )
                ).scalar_one()
            )
            if not lock_available:
                raise DatabaseRuntimeError("database_migration_in_progress")
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            )

            role = (
                await connection.execute(
                    text(
                        """
                        SELECT r.rolname, r.rolsuper, r.rolcreatedb, r.rolcreaterole,
                               r.rolreplication, r.rolbypassrls,
                               has_schema_privilege(r.rolname, current_schema(), 'CREATE')
                        FROM pg_roles AS r
                        WHERE r.rolname = current_user
                        """
                    )
                )
            ).one()
            if settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}:
                settings.require_database_role(expected_role)
                if any(bool(value) for value in role[1:]):
                    raise DatabaseRuntimeError("database_role_is_overprivileged")

            return DatabaseRuntimeReport(
                dialect="postgresql",
                schema_revision=str(revision),
                database_user=str(role[0]),
            )
    except DatabaseRuntimeError:
        raise
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise DatabaseRuntimeError("database_unavailable") from exc


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    try:
        parsed = tuple(int(part) for part in parts[:3])
    except ValueError as exc:
        raise DatabaseRuntimeError("pgvector_capability_incompatible") from exc
    padded = (*parsed, 0, 0, 0)
    return padded[0], padded[1], padded[2]


def validate_postgresql_capabilities(
    *,
    server_version: int,
    vector_version: str | None,
    schema_revision: str | None,
    expected_revision: str,
) -> None:
    if server_version // 10_000 != POSTGRESQL_MAJOR_VERSION:
        raise DatabaseRuntimeError("postgresql_version_incompatible")
    if vector_version is None or _version_tuple(vector_version) < MINIMUM_PGVECTOR_VERSION:
        raise DatabaseRuntimeError("pgvector_capability_incompatible")
    if schema_revision != expected_revision:
        raise DatabaseRuntimeError("database_schema_incompatible")


__all__ = [
    "MIGRATION_ADVISORY_LOCK_ID",
    "MINIMUM_PGVECTOR_VERSION",
    "POSTGRESQL_MAJOR_VERSION",
    "DatabaseRuntimeError",
    "DatabaseRuntimeReport",
    "validate_database_runtime",
    "validate_postgresql_capabilities",
]
