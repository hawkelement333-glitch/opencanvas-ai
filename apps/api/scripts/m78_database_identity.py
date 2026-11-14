from __future__ import annotations

import json
import re
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.db.principal_manifest import PrincipalManifest, PrincipalSlot
from opencanvas_api.db.session import Database

APPLICATION_DATABASE = "opencanvas"
IDENTITY_DATABASE = "postgres"
LIST_SIGNATURE = "pg_catalog.pgaadauth_list_principals(boolean)"
CREATE_SIGNATURE = (
    "pg_catalog.pgaadauth_create_principal_with_oid(text,text,text,boolean,boolean,text,boolean)"
)


@asynccontextmanager
async def identity_connection(
    settings: Settings,
    *,
    role: DatabaseRole,
    manifest: PrincipalManifest,
    slot: PrincipalSlot,
    read_only: bool = True,
) -> AsyncIterator[AsyncConnection]:
    url = make_url(settings.database_url_value)
    if url.database != APPLICATION_DATABASE or url.username != manifest.principals[slot].name:
        raise RuntimeError("identity database source URL differs from bound application URL")
    scoped = settings.model_copy(
        update={
            "database_url": SecretStr(
                url.set(database=IDENTITY_DATABASE).render_as_string(hide_password=False)
            )
        }
    )
    database = Database.from_settings(scoped, expected_role=role)
    try:
        async with database.engine.begin() as connection:
            if read_only:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
            await require_bound_connection(connection, manifest, slot, IDENTITY_DATABASE)
            yield connection
    finally:
        await database.dispose()


async def require_bound_connection(
    connection: AsyncConnection,
    manifest: PrincipalManifest,
    slot: PrincipalSlot,
    database_name: str,
) -> None:
    current_user, current_database = (
        await connection.execute(text("SELECT current_user, current_database()"))
    ).one()
    if not isinstance(current_user, str) or current_database != database_name:
        raise RuntimeError("database target binding differs")
    manifest.require_current(slot, current_name=current_user)


async def function_executable(connection: AsyncConnection, signature: str) -> bool:
    return (
        await connection.execute(
            text(
                "SELECT COALESCE(pg_catalog.has_function_privilege("
                "current_user, pg_catalog.to_regprocedure(:signature), 'EXECUTE'), false)"
            ),
            {"signature": signature},
        )
    ).scalar_one() is True


async def list_mappings(
    connection: AsyncConnection, names: list[str]
) -> list[dict[str, object]]:
    # Always invoke the provider's read API, including an empty result on a fresh server.
    rows = await connection.execute(
        text(
            "SELECT to_jsonb(p) AS mapping FROM pg_catalog.pgaadauth_list_principals(false) AS p "
            "WHERE p.rolename::text = ANY(CAST(:names AS text[])) ORDER BY p.rolename"
        ),
        {"names": names},
    )
    return [dict(row) for row in rows.mappings()]


def require_mappings(
    rows: list[dict[str, object]],
    expected: Mapping[str, str],
    *,
    admins: frozenset[str] = frozenset(),
) -> None:
    observed: set[str] = set()
    tenants: set[uuid.UUID] = set()
    for item in rows:
        raw = item.get("mapping")
        if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
            raise RuntimeError("database Entra mapping is unverified")
        mapping = {key.casefold(): value for key, value in raw.items()}
        name = mapping.get("rolename")
        try:
            tenant = uuid.UUID(str(mapping.get("tenantid")))
            valid = (
                len(mapping) == len(raw)
                and isinstance(name, str)
                and name in expected
                and name not in observed
                and mapping.get("principaltype") == "service"
                and uuid.UUID(str(mapping.get("objectid"))) == uuid.UUID(expected[name])
                and type(mapping.get("isadmin")) is int
                and mapping["isadmin"] == int(name in admins)
                and type(mapping.get("ismfa")) is int
                and mapping["ismfa"] == 0
                and tenant.int != 0
            )
        except (ValueError, KeyError):
            valid = False
        if not valid or not isinstance(name, str):
            raise RuntimeError("database Entra mapping differs")
        tenants.add(tenant)
        observed.add(name)
    if observed != set(expected) or len(tenants) > 1:
        raise RuntimeError("database Entra mapping is missing or tenant bindings differ")


def sqlstate(error: BaseException) -> str | None:
    pending = [error]
    seen: set[int] = set()
    while pending and len(seen) < 8:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        value = getattr(current, "sqlstate", None)
        if isinstance(value, str) and re.fullmatch(r"[0-9A-Z]{5}", value):
            return value
        for attribute in ("orig", "__cause__"):
            child = getattr(current, attribute, None)
            if isinstance(child, BaseException):
                pending.append(child)
    return None


def failure_diagnostic(prefix: str, stage: str, error: Exception) -> None:
    # Never render the exception, driver arguments, SQL, or principal values.
    allowed = {
        "TimeoutError", "ConnectionError", "OSError", "OperationalError", "InterfaceError",
        "ProgrammingError", "DataError", "IntegrityError", "DBAPIError", "InvalidRequestError",
        "ClientAuthenticationError", "CredentialUnavailableError", "ValidationError",
        "RuntimeError", "ValueError", "TypeError",
    }
    category = next(
        (kind.__name__ for kind in type(error).__mro__ if kind.__name__ in allowed),
        "Exception",
    )
    print(
        prefix + json.dumps(
            {"stage": stage, "errorClass": category, "sqlstate": sqlstate(error)},
            separators=(",", ":"),
            sort_keys=True,
        ),
        file=sys.stderr,
    )
