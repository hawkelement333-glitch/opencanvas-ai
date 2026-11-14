from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

from sqlalchemy import text

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.role_privileges import quote_identifier
from opencanvas_api.db.session import Database
from scripts.m78_database_identity import APPLICATION_DATABASE, require_bound_connection


async def apply(mode: str) -> dict[str, object]:
    settings = get_settings()
    settings.require_database_role(DatabaseRole.PROVISIONING)
    manifest = load_principal_manifest()
    api = manifest.principals[PrincipalSlot.API]
    database = Database.from_settings(settings, expected_role=DatabaseRole.PROVISIONING)
    terminated: int | None = None
    sessions: int | None = None
    try:
        async with database.engine.begin() as connection:
            await require_bound_connection(
                connection, manifest, PrincipalSlot.BOOTSTRAP, APPLICATION_DATABASE,
            )
            quoted_api = quote_identifier(api.name)
            disposition = "NOLOGIN" if mode == "revoke" else "LOGIN"
            await connection.execute(text(f"ALTER ROLE {quoted_api} {disposition}"))

        async with database.engine.begin() as observed:
            await require_bound_connection(
                observed, manifest, PrincipalSlot.BOOTSTRAP, APPLICATION_DATABASE,
            )
            can_login = (
                await observed.execute(
                    text("SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = :principal"),
                    {"principal": api.name},
                )
            ).scalar_one()
            if can_login is not (mode == "restore"):
                raise RuntimeError("credential recovery readback is inconsistent")
            if mode == "revoke":
                # NOLOGIN is committed before terminating sessions. The provider
                # wait is bounded per backend and the whole probe is also bounded.
                outcomes = (
                    await observed.execute(
                        text(
                            "SELECT pg_catalog.pg_terminate_backend(pid, 2000) "
                            "FROM pg_catalog.pg_stat_activity "
                            "WHERE usename = :principal AND pid <> pg_backend_pid()"
                        ),
                        {"principal": api.name},
                    )
                ).scalars().all()
                if any(stopped is not True for stopped in outcomes):
                    raise RuntimeError("credential recovery session termination is unproved")
                terminated = len(outcomes)

        if mode == "revoke":
            # A fresh statistics snapshot follows the termination transaction.
            async with database.engine.connect() as connection:
                await require_bound_connection(
                    connection, manifest, PrincipalSlot.BOOTSTRAP, APPLICATION_DATABASE,
                )
                sessions = (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                            "WHERE usename = :principal"
                        ),
                        {"principal": api.name},
                    )
                ).scalar_one()
                if type(sessions) is not int or sessions != 0:
                    raise RuntimeError("credential recovery retained active sessions")
    finally:
        await database.dispose()
    return {
        "version": "m7.8-credential-recovery-observation-v1", "status": "observed",
        "campaignId": manifest.campaign_id, "generationId": manifest.generation_id,
        "mode": mode, "loginEnabled": can_login, "activeSessions": sessions,
        "terminatedSessions": terminated,
    }


async def _observe(mode: str) -> dict[str, object]:
    async with asyncio.timeout(40):
        return await apply(mode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Campaign-only database-login recovery probe")
    parser.add_argument("mode", choices=("revoke", "restore"))
    args = parser.parse_args()
    try:
        token = os.environ.get("M78_EVIDENCE_TOKEN")
        if token is not None and re.fullmatch(r"[a-f0-9]{32}", token) is None:
            raise RuntimeError("credential evidence dispatch binding is malformed")
        result = asyncio.run(_observe(args.mode))
        if token is not None:
            encoded = json.dumps(result, separators=(",", ":"), sort_keys=True, allow_nan=False)
            print(f"M78_EVIDENCE {token} {encoded}", flush=True)
        return 0
    except Exception:
        print("credential-recovery-probe-failed-safely", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
