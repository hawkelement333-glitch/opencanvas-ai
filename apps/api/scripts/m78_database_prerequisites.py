from __future__ import annotations

import asyncio
import json
import re
from os import environ
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.session import Database
from scripts.m78_database_identity import (
    APPLICATION_DATABASE,
    CREATE_SIGNATURE,
    IDENTITY_DATABASE,
    LIST_SIGNATURE,
    failure_diagnostic,
    function_executable,
    identity_connection,
    list_mappings,
    require_bound_connection,
    require_mappings,
    sqlstate,
)

Operation = Literal["bootstrap", "migrate"]
PREFIX = "M78_DATABASE_PREREQUISITES "
VERSION = "m7.8-database-prerequisites-v1"
TOKEN_ENV = "M78_DATABASE_PREREQUISITE_TOKEN"
APPLICATION_SLOTS = (
    PrincipalSlot.MIGRATION, PrincipalSlot.API, PrincipalSlot.WORKER, PrincipalSlot.EVIDENCE,
)


async def vector_observation(
    connection: AsyncConnection, *, managed: bool, provisioning: bool,
) -> dict[str, object]:
    # Bind the read to the version the server would actually install. No DDL here.
    result = await connection.execute(
        text(
            "SELECT v.version, v.trusted, v.superuser, v.schema, "
            "v.requires, n.nspname AS installed_schema, "
            "current_setting('azure.extensions', true) AS allowlist, "
            "pg_catalog.has_database_privilege(current_user, current_database(), 'CREATE') "
            "AS database_create, "
            "pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create, "
            "r.rolsuper, COALESCE((SELECT pg_has_role(a.oid, 'MEMBER') "
            "FROM pg_catalog.pg_roles a WHERE a.rolname = 'azure_pg_admin'), false) AS azure_admin "
            "FROM pg_catalog.pg_available_extensions a "
            "JOIN pg_catalog.pg_available_extension_versions v ON v.name = a.name "
            "LEFT JOIN pg_catalog.pg_extension e ON e.extname = a.name "
            "LEFT JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace "
            "JOIN pg_catalog.pg_roles r ON r.rolname = current_user "
            "WHERE a.name = 'vector' AND v.version = COALESCE(e.extversion, a.default_version)"
        )
    )
    row = result.mappings().one_or_none()
    if (
        row is None
        or not isinstance(row["version"], str)
        or re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.]+)?", row["version"]) is None
        or type(row["trusted"]) is not bool
        or type(row["superuser"]) is not bool
        or row["schema"] not in {None, "public"}
        or row["installed_schema"] not in {None, "public"}
        or row["requires"] not in (None, [])
    ):
        raise RuntimeError("vector packaging or installed schema is unverified")
    if managed:
        allowlist = row["allowlist"]
        if not isinstance(allowlist, str) or "vector" not in {
            part.strip().casefold() for part in allowlist.split(",")
        }:
            raise RuntimeError("managed vector extension is not allowlisted")
    installed = row["installed_schema"] == "public"
    can_install = (
        provisioning
        and row["database_create"] is True
        and row["schema_create"] is True
        and (
            (managed and row["azure_admin"] is True)
            or (not managed and row["rolsuper"] is True)
            or row["trusted"] is True
            or row["superuser"] is False
        )
    )
    if not installed and not can_install:
        raise RuntimeError("vector installation requires the bound provisioning authority")
    return {
        "version": row["version"],
        "trusted": row["trusted"],
        "superuserRequired": row["superuser"],
        "installed": installed,
        "installerAllowed": can_install,
    }


async def require_installed_vector(connection: AsyncConnection) -> None:
    exists = (
        await connection.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_extension e "
                "JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace "
                "WHERE e.extname='vector' AND n.nspname='public')"
            )
        )
    ).scalar_one()
    if exists is not True:
        raise RuntimeError("public vector extension is missing; run the bound bootstrap first")


async def _diagnose(operation: Operation) -> dict[str, object]:
    provisioning = operation == "bootstrap"
    role = DatabaseRole.PROVISIONING if provisioning else DatabaseRole.MIGRATION
    slot = PrincipalSlot.BOOTSTRAP if provisioning else PrincipalSlot.MIGRATION
    settings = get_settings()
    settings.require_database_role(role)
    manifest = load_principal_manifest()
    async with asyncio.timeout(40):
        listing_read = False
        create_execute: bool | None = None
        # Check both the catalog ACL and a real invocation under READ ONLY. PostgreSQL
        # may reject the operation inside the routine even when its ACL allows EXECUTE.
        async with identity_connection(
            settings, role=role, manifest=manifest, slot=slot,
        ) as connection:
            listing_execute = await function_executable(connection, LIST_SIGNATURE)
            if provisioning:
                create_execute = await function_executable(connection, CREATE_SIGNATURE)
                if not listing_execute or not create_execute:
                    raise RuntimeError("bootstrap identity function permission is unavailable")
            if listing_execute:
                expected = {
                    manifest.principals[s].name: manifest.principals[s].object_id
                    for s in ([slot] if provisioning else APPLICATION_SLOTS)
                }
                try:
                    # A known listing denial cannot leave the outer transaction aborted.
                    async with connection.begin_nested():
                        rows = await list_mappings(connection, list(expected))
                except DBAPIError as exc:
                    if provisioning or sqlstate(exc) not in {"42501", "42883"}:
                        raise
                else:
                    require_mappings(
                        rows, expected,
                        admins=frozenset(expected) if provisioning else frozenset(),
                    )
                    listing_read = True
        database = Database.from_settings(settings, expected_role=role)
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await require_bound_connection(connection, manifest, slot, APPLICATION_DATABASE)
                vector = await vector_observation(
                    connection,
                    managed=settings.database_auth_mode == "entra",
                    provisioning=provisioning,
                )
        finally:
            await database.dispose()
    return {
        "version": VERSION,
        "operation": operation,
        "status": "read-only-prerequisites-passed",
        "campaignId": manifest.campaign_id,
        "generationId": manifest.generation_id,
        "identityDatabase": IDENTITY_DATABASE,
        "applicationDatabase": APPLICATION_DATABASE,
        "identityMatches": True,
        "applicationBindingMatches": True,
        "listingRead": listing_read,
        "createExecute": create_execute,
        "vector": vector,
    }


def diagnose(operation: Operation) -> int:
    try:
        token = environ.get(TOKEN_ENV, "")
        if re.fullmatch(r"[0-9a-f]{32}", token) is None:
            raise RuntimeError("database prerequisite observation binding is invalid")
        marker = asyncio.run(_diagnose(operation))
    except Exception as exc:
        failure_diagnostic("M78_DATABASE_PREREQUISITES_DIAGNOSTIC ", operation, exc)
        return 1
    print(PREFIX + token + " " + json.dumps(marker, sort_keys=True, separators=(",", ":")))
    return 0
