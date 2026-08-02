from __future__ import annotations

import asyncio
import os
import re
import sys

from sqlalchemy import text

from opencanvas_api.core.config import (
    EXPECTED_DATABASE_REVISION,
    DatabaseRole,
    get_settings,
)
from opencanvas_api.db.session import Database
from scripts.migrate import run as run_migration

_SAFE_PRINCIPAL = re.compile(r"^id-mobius77-(?:api|worker)$")


async def _current_revision() -> str:
    settings = get_settings()
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


async def _grant_runtime_roles() -> None:
    principals = (
        os.getenv("OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL", ""),
        os.getenv("OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL", ""),
    )
    if any(_SAFE_PRINCIPAL.fullmatch(principal) is None for principal in principals):
        raise RuntimeError("database runtime principal contract is invalid")
    settings = get_settings()
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.begin() as connection:
            current_user = str((await connection.execute(text("SELECT current_user"))).scalar_one())
            for principal in principals:
                existing = (
                    await connection.execute(
                        text(
                            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                            "rolbypassrls FROM pg_roles WHERE rolname = :principal"
                        ),
                        {"principal": principal},
                    )
                ).one_or_none()
                if existing is None:
                    await connection.execute(
                        text("SELECT * FROM pgaadauth_create_principal(:principal, false, false)"),
                        {"principal": principal},
                    )
                elif any(bool(value) for value in existing):
                    raise RuntimeError("database runtime principal is overprivileged")

            preparer = connection.dialect.identifier_preparer
            quoted_admin = preparer.quote(current_user)
            quoted_principals = [preparer.quote(principal) for principal in principals]
            await connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            for quoted in quoted_principals:
                await connection.execute(text(f"REVOKE ALL ON DATABASE opencanvas FROM {quoted}"))
                await connection.execute(text(f"GRANT CONNECT ON DATABASE opencanvas TO {quoted}"))
                await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted}"))
                await connection.execute(
                    text(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                        f"IN SCHEMA public TO {quoted}"
                    )
                )
                await connection.execute(
                    text(
                        f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {quoted}"
                    )
                )
                await connection.execute(
                    text(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {quoted}")
                )
                await connection.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted}"
                    )
                )
                await connection.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
                        f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {quoted}"
                    )
                )
                await connection.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES FOR ROLE {quoted_admin} IN SCHEMA public "
                        f"GRANT EXECUTE ON FUNCTIONS TO {quoted}"
                    )
                )
    finally:
        await database.dispose()


def main() -> int:
    try:
        revision = asyncio.run(_current_revision())
        if revision == "base":
            run_migration(expected_current="base", target=EXPECTED_DATABASE_REVISION)
        elif revision != EXPECTED_DATABASE_REVISION:
            raise RuntimeError("database migration state is inconsistent")
        asyncio.run(_grant_runtime_roles())
        if asyncio.run(_current_revision()) != EXPECTED_DATABASE_REVISION:
            raise RuntimeError("database migration verification failed")
        return 0
    except Exception:
        print("PostgreSQL bootstrap failed safely.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
