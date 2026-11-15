"""One hash-bound D-001 column-lock grant correction; no bootstrap or migration.

The retained application image remains bound to its original source. This
external deployment action applies the separately reviewed grant correction.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

LOCK_COLUMNS = (
    ("malware_scan_requests", "scan_request_id"),
    ("object_deletion_requests", "deletion_request_id"),
    ("upload_sessions", "session_id"),
)
RETAINED_ROLE_MODULE_SHA256 = "46f91b906ed5ce80cf9cbb561690bbf18e3dc9ea04c83390e2332e6739df61ae"


def require_reviewed_inventory() -> None:
    from opencanvas_api.core.config import DatabaseRole
    from opencanvas_api.db import role_privileges

    inventory = getattr(role_privileges, "RUNTIME_ROW_LOCK_COLUMNS", None)
    if inventory is None:
        if (
            hashlib.sha256(Path(role_privileges.__file__).read_bytes()).hexdigest()
            != RETAINED_ROLE_MODULE_SHA256
        ):
            raise RuntimeError("retained grant-generator source binding differs")
    elif inventory != {
        DatabaseRole.API: {"upload_sessions": "session_id"},
        DatabaseRole.WORKER: dict(LOCK_COLUMNS),
    }:
        raise RuntimeError("corrected column-lock inventory differs")
    for table, _ in LOCK_COLUMNS:
        for role in (DatabaseRole.API, DatabaseRole.WORKER):
            permissions = role_privileges.RUNTIME_TABLE_PRIVILEGES[role]
            if table not in permissions["SELECT"] or table in permissions["UPDATE"]:
                raise RuntimeError("column-lock correction table boundary differs")


def grant_statements(principal: str) -> tuple[str, ...]:
    from opencanvas_api.db.role_privileges import quote_identifier

    return tuple(
        f"GRANT UPDATE ({quote_identifier(column)}) ON TABLE "
        f"public.{quote_identifier(table)} TO {quote_identifier(principal)}"
        for table, column in LOCK_COLUMNS
    )


def require_guards(rows: list[dict[str, Any]]) -> None:
    expected = {
        (table, f"trg_{table}_{operation}_blocked", kind)
        for table, _ in LOCK_COLUMNS
        for operation, kind in (("update", 19), ("delete", 11))
    }
    observed = set()
    for row in rows:
        key = (row["table_name"], row["trigger_name"], row["trigger_type"])
        if (
            key not in expected
            or row["enabled"] not in {"O", "A"}
            or row["function_schema"] != "public"
            or row["function_name"] != "reject_controlled_agent_mutation"
        ):
            raise RuntimeError("immutable column-lock guard differs")
        observed.add(key)
    if observed != expected or len(rows) != 6:
        raise RuntimeError("immutable column-lock guard inventory incomplete")


async def run() -> dict[str, Any]:
    from pydantic import SecretStr
    from scripts.m78_database_identity import list_mappings, require_mappings
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from opencanvas_api.core.config import DatabaseRole, get_settings
    from opencanvas_api.db.session import Database

    require_reviewed_inventory()
    settings = get_settings()
    url = make_url(settings.database_url_value)
    match = re.fullmatch(r"id-m78o-([a-f0-9]{10})-bootstrap", url.username or "")
    if match is None:
        raise RuntimeError("column-lock administrator binding invalid")
    principal = f"id-m78o-{match[1]}-probe"
    if (
        url.drivername != "postgresql+asyncpg"
        or url.password is not None
        or url.host != f"pg-m78o-{match[1]}.postgres.database.azure.com"
        or url.port != 5432
        or url.database != "opencanvas_objects"
        or url.query
        or settings.database_role != DatabaseRole.MIGRATION
        or settings.database_auth_mode != "entra"
        or settings.database_tls_mode != "verify-full"
        or os.environ.get("PGSSLROOTCERT") != "/etc/ssl/certs/ca-certificates.crt"
        or os.environ.get("OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL") != principal
    ):
        raise RuntimeError("column-lock target or transport binding differs")
    administrator_id = str(uuid.UUID(os.environ["OPENCANVAS_OBJECT_PROBE_BOOTSTRAP_PRINCIPAL_ID"]))
    principal_id = str(uuid.UUID(os.environ["OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID"]))
    if administrator_id == principal_id:
        raise RuntimeError("column-lock principals are not distinct")
    identity_settings = settings.model_copy(
        update={
            "database_url": SecretStr(
                url.set(database="postgres").render_as_string(hide_password=False)
            )
        }
    )
    identity_database = Database.from_settings(
        identity_settings, expected_role=DatabaseRole.MIGRATION
    )
    try:
        async with identity_database.engine.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            require_mappings(
                await list_mappings(connection, [url.username, principal]),
                {url.username: administrator_id, principal: principal_id},
                admins=frozenset({url.username}),
            )
    finally:
        await identity_database.dispose()
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.begin() as connection:
            identity = (
                await connection.execute(text("SELECT current_user, current_database()"))
            ).one()
            if tuple(identity) != (url.username, "opencanvas_objects"):
                raise RuntimeError("column-lock connection identity differs")
            guards = (
                (
                    await connection.execute(
                        text(
                            "SELECT c.relname::text AS table_name, t.tgname::text AS trigger_name, "
                            "t.tgtype::integer AS trigger_type, t.tgenabled::text AS enabled, "
                            "pn.nspname::text AS function_schema, p.proname::text AS function_name "
                            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "JOIN pg_proc p ON p.oid=t.tgfoid "
                            "JOIN pg_namespace pn ON pn.oid=p.pronamespace "
                            "WHERE n.nspname='public' "
                            "AND c.relname::text=ANY(CAST(:tables AS text[])) "
                            "AND NOT t.tgisinternal AND t.tgname::text=ANY(CAST(:names AS text[]))"
                        ),
                        {
                            "tables": [table for table, _ in LOCK_COLUMNS],
                            "names": [
                                f"trg_{table}_{operation}_blocked"
                                for table, _ in LOCK_COLUMNS
                                for operation in ("update", "delete")
                            ],
                        },
                    )
                )
                .mappings()
                .all()
            )
            require_guards([dict(row) for row in guards])
            changed = 0
            for (table, column), statement in zip(
                LOCK_COLUMNS, grant_statements(principal), strict=True
            ):
                parameters = {"principal": principal, "table": f"public.{table}", "column": column}
                query = text(
                    "SELECT has_column_privilege(:principal,:table,:column,'UPDATE'), "
                    "has_table_privilege(:principal,:table,'UPDATE')"
                )
                column_allowed, table_allowed = (await connection.execute(query, parameters)).one()
                if table_allowed:
                    raise RuntimeError("column-lock principal has excessive table UPDATE")
                if not column_allowed:
                    await connection.execute(text(statement))
                    changed += 1
                if tuple((await connection.execute(query, parameters)).one()) != (True, False):
                    raise RuntimeError("column-lock grant readback differs")
        return {
            "classification": "targeted-column-lock-grant-correction",
            "status": "accepted",
            "guardCount": 6,
            "columnUpdateAllowedCount": 3,
            "tableUpdateAllowedCount": 0,
            "changedColumnCount": changed,
            "sourceSha256": os.environ["M78_EXECUTION_SHA256"],
            "grantSqlSha256": hashlib.sha256(
                "\n".join(grant_statements(principal)).encode()
            ).hexdigest(),
        }
    finally:
        await database.dispose()


def main() -> int:
    try:
        receipt = asyncio.run(run())
    except Exception as error:
        receipt = {
            "classification": "targeted-column-lock-grant-correction",
            "status": "failed",
            "errorType": type(error).__name__,
            "sourceSha256": os.environ.get("M78_EXECUTION_SHA256", ""),
        }
    print("M78_OBJECT_BOOTSTRAP " + json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
