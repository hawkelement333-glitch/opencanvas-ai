from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from opencanvas_api.core.config import (
    EXPECTED_DATABASE_REVISION,
    DatabaseRole,
    get_settings,
)
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.role_privileges import (
    application_routines,
    require_runtime_function_privileges,
    runtime_privilege_statements,
)
from opencanvas_api.db.session import Database
from scripts.m78_database_identity import (
    APPLICATION_DATABASE,
    failure_diagnostic,
    identity_connection,
    require_bound_connection,
)
from scripts.m78_database_prerequisites import diagnose, require_installed_vector
from scripts.m78_database_recovery import require_safe_retry, retry_argument
from scripts.migrate import run as run_migration

_SAFE_FAILURE_CODE = "observability-bootstrap-migration-or-runtime-privilege-reconciliation-failed"


def _principals() -> tuple[str, str, str]:
    manifest = load_principal_manifest()
    return (
        manifest.principals[PrincipalSlot.MIGRATION].name,
        manifest.principals[PrincipalSlot.API].name,
        manifest.principals[PrincipalSlot.WORKER].name,
    )


async def _current_revision(*, retry_after_execution: str | None = None) -> str:
    settings = get_settings()
    if settings.database_role is not DatabaseRole.MIGRATION:
        raise RuntimeError("database migration role contract is invalid")
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.connect() as connection:
            manifest = load_principal_manifest()
            await require_bound_connection(
                connection, manifest, PrincipalSlot.MIGRATION, APPLICATION_DATABASE,
            )
            retry_observation = None
            if retry_after_execution is not None:
                async with asyncio.timeout(40):
                    async with identity_connection(
                        settings, role=DatabaseRole.MIGRATION, manifest=manifest,
                        slot=PrincipalSlot.MIGRATION,
                    ) as identity:
                        retry_observation = await require_safe_retry(
                            connection, identity=identity, operation="migrate",
                            previous_execution=retry_after_execution, manifest=manifest,
                        )
            await require_installed_vector(connection)
            exists = (
                await connection.execute(text("SELECT to_regclass('public.alembic_version')"))
            ).scalar_one_or_none()
            if exists is None:
                if (
                    retry_observation is not None
                    and retry_observation["observedRevision"] != "base"
                ):
                    raise RuntimeError("database retry revision changed after inspection")
                return "base"
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            if not isinstance(revision, str):
                raise RuntimeError("database migration state is inconsistent")
            if retry_observation is not None and retry_observation["observedRevision"] != revision:
                raise RuntimeError("database retry revision changed after inspection")
            return revision
    finally:
        await database.dispose()


async def apply_runtime_privileges() -> None:
    settings = get_settings()
    settings.require_database_role(DatabaseRole.MIGRATION)
    if settings.database_role is not DatabaseRole.MIGRATION:
        raise RuntimeError("database migration role contract is invalid")
    migration, api, worker = _principals()
    manifest = load_principal_manifest()
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.begin() as connection:
            await require_bound_connection(
                connection, manifest, PrincipalSlot.MIGRATION, APPLICATION_DATABASE,
            )
            migration_flags = (
                await connection.execute(
                    text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                        "rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = :migration"
                    ),
                    {"migration": migration},
                )
            ).one_or_none()
            if migration_flags is None or any(bool(value) for value in migration_flags):
                raise RuntimeError("migration principal is overprivileged")
            unowned_relations = int(
                (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM pg_catalog.pg_class AS c "
                            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                            "JOIN pg_catalog.pg_roles AS r ON r.oid = c.relowner "
                            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S') "
                            "AND r.rolname <> :migration"
                        ),
                        {"migration": migration},
                    )
                ).scalar_one()
            )
            if unowned_relations:
                raise RuntimeError("migration principal does not own the application schema")
            routines = await application_routines(connection, owner=migration)
            for statement in runtime_privilege_statements(
                api_principal=api,
                worker_principal=worker,
                migration_principal=migration,
                application_routines=routines,
            ):
                await connection.execute(text(statement))
            role_rows = (
                await connection.execute(
                    text(
                        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                        "rolbypassrls, pg_has_role(rolname, :migration, 'MEMBER') "
                        "FROM pg_catalog.pg_roles WHERE rolname IN (:api, :worker) "
                        "ORDER BY rolname"
                    ),
                    {"migration": migration, "api": api, "worker": worker},
                )
            ).all()
            if len(role_rows) != 2 or any(
                any(bool(value) for value in row[1:]) for row in role_rows
            ):
                raise RuntimeError("database runtime principal is overprivileged")
            await require_runtime_function_privileges(connection, DatabaseRole.API, principal=api)
            await require_runtime_function_privileges(
                connection, DatabaseRole.WORKER, principal=worker,
            )
    finally:
        await database.dispose()


def main(arguments: list[str] | None = None) -> int:
    if arguments == ["--diagnose-prerequisites"]:
        return diagnose("migrate")
    stage = "configuration"
    try:
        retry = retry_argument(arguments)
        stage = "retry-inspection" if retry is not None else "database-revision"
        revision = asyncio.run(
            _current_revision() if retry is None
            else _current_revision(retry_after_execution=retry)
        )
        if revision == "base":
            stage = "migration-upgrade"
            result = run_migration(expected_current="base", target=EXPECTED_DATABASE_REVISION)
            if result != 0:
                raise RuntimeError("database migration failed")
        elif revision != EXPECTED_DATABASE_REVISION:
            raise RuntimeError("database migration state is inconsistent")
        stage = "runtime-grant-reconciliation"
        asyncio.run(apply_runtime_privileges())
        stage = "database-verification"
        if asyncio.run(_current_revision()) != EXPECTED_DATABASE_REVISION:
            raise RuntimeError("database migration verification failed")
        return 0
    except Exception as exc:
        failure_diagnostic("M78_MIGRATION_DIAGNOSTIC ", stage, exc)
        print(_SAFE_FAILURE_CODE, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
