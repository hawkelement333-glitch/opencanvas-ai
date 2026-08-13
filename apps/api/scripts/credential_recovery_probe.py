from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.role_privileges import quote_identifier
from opencanvas_api.db.session import Database


async def apply(mode: str) -> None:
    settings = get_settings()
    settings.require_database_role(DatabaseRole.PROVISIONING)
    manifest = load_principal_manifest()
    api = manifest.principals[PrincipalSlot.API]
    database = Database.from_settings(settings, expected_role=DatabaseRole.PROVISIONING)
    try:
        async with database.engine.begin() as connection:
            current = str((await connection.execute(text("SELECT current_user"))).scalar_one())
            manifest.require_current(PrincipalSlot.BOOTSTRAP, current_name=current)
            quoted_api = quote_identifier(api.name)
            if mode == "revoke":
                await connection.execute(text(f"ALTER ROLE {quoted_api} NOLOGIN"))
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE usename = :principal AND pid <> pg_backend_pid()"
                    ),
                    {"principal": api.name},
                )
            else:
                await connection.execute(text(f"ALTER ROLE {quoted_api} LOGIN"))
            can_login = bool(
                (
                    await connection.execute(
                        text(
                            "SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = :principal"
                        ),
                        {"principal": api.name},
                    )
                ).scalar_one()
            )
            if can_login != (mode == "restore"):
                raise RuntimeError("credential recovery readback is inconsistent")
    finally:
        await database.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Campaign-only database-login recovery probe")
    parser.add_argument("mode", choices=("revoke", "restore"))
    args = parser.parse_args()
    try:
        asyncio.run(apply(args.mode))
        return 0
    except Exception:
        print("credential-recovery-probe-failed-safely", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
