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
from opencanvas_api.db.role_privileges import runtime_privilege_statements
from opencanvas_api.db.session import Database
from scripts.migrate import run as run_migration

_SAFE_FAILURE_CODE = "observability-bootstrap-migration-or-runtime-privilege-reconciliation-failed"


def _principals() -> tuple[str, str, str]:
    manifest = load_principal_manifest()
    return (
        manifest.principals[PrincipalSlot.MIGRATION].name,
        manifest.principals[PrincipalSlot.API].name,
        manifest.principals[PrincipalSlot.WORKER].name,
    )


async def _current_revision() -> str:
    settings = get_settings()
    if settings.database_role is not DatabaseRole.MIGRATION:
        raise RuntimeError("database migration role contract is invalid")
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.connect() as connection:
            exists = (
                await connection.execute(text("SELECT to_regclass('public.alembic_version')"))
            ).scalar_one_or_none()
            if exists is None:
                return "base"
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            if not isinstance(revision, str):
                raise RuntimeError("database migration state is inconsistent")
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
            current_user = str((await connection.execute(text("SELECT current_user"))).scalar_one())
            manifest.require_current(PrincipalSlot.MIGRATION, current_name=current_user)
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
            unowned_functions = int(
                (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM pg_catalog.pg_proc AS p "
                            "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
                            "JOIN pg_catalog.pg_roles AS r ON r.oid = p.proowner "
                            "WHERE n.nspname = 'public' AND r.rolname <> :migration"
                        ),
                        {"migration": migration},
                    )
                ).scalar_one()
            )
            if unowned_functions:
                raise RuntimeError("migration principal does not own application functions")
            for statement in runtime_privilege_statements(
                api_principal=api,
                worker_principal=worker,
                migration_principal=migration,
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
    finally:
        await database.dispose()


def main() -> int:
    try:
        revision = asyncio.run(_current_revision())
        if revision == "base":
            result = run_migration(expected_current="base", target=EXPECTED_DATABASE_REVISION)
            if result != 0:
                raise RuntimeError("database migration failed")
        elif revision != EXPECTED_DATABASE_REVISION:
            raise RuntimeError("database migration state is inconsistent")
        asyncio.run(apply_runtime_privileges())
        if asyncio.run(_current_revision()) != EXPECTED_DATABASE_REVISION:
            raise RuntimeError("database migration verification failed")
        return 0
    except Exception:
        print(_SAFE_FAILURE_CODE, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
