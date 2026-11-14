from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from os import environ
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION
from opencanvas_api.db.principal_manifest import (
    MANIFEST_ENV,
    PrincipalManifest,
    PrincipalSlot,
)
from opencanvas_api.db.runtime import MIGRATION_ADVISORY_LOCK_ID
from scripts.m78_database_identity import (
    APPLICATION_DATABASE,
    IDENTITY_DATABASE,
    list_mappings,
    require_bound_connection,
    require_mappings,
)

Operation = Literal["bootstrap", "migrate"]
PREFIX = "M78_DATABASE_RECOVERY "
VERSION = "m7.8-database-recovery-observation-v1"
SLOTS = (PrincipalSlot.MIGRATION, PrincipalSlot.API, PrincipalSlot.WORKER, PrincipalSlot.EVIDENCE)


def retry_argument(arguments: list[str] | None) -> str | None:
    parser = argparse.ArgumentParser(description="Run the existing guarded database job")
    parser.add_argument("--retry-after-execution")
    value = parser.parse_args(arguments or []).retry_after_execution
    if value is not None and (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is None
    ):
        raise RuntimeError("database retry execution binding is invalid")
    return value if isinstance(value, str) else None


def _digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        domain.encode()
        + b"\0"
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


async def _rows(
    connection: AsyncConnection,
    query: str,
    parameters: dict[str, object],
) -> list[dict[str, object]]:
    result = await connection.execute(text(query), parameters)
    return [dict(row) for row in result.mappings()]


async def _observe(
    connection: AsyncConnection,
    manifest: PrincipalManifest,
    identity: AsyncConnection,
) -> dict[str, object]:
    parameters: dict[str, object] = {slot.value: manifest.principals[slot].name for slot in SLOTS}
    names = ":migration, :api, :worker, :evidence"
    current = (await connection.execute(text("SELECT current_user, current_database()"))).one()
    roles = await _rows(
        connection,
        (
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            f"FROM pg_catalog.pg_roles WHERE rolname IN ({names}) ORDER BY rolname"
        ),
        parameters,
    )
    mappings = await list_mappings(identity, [manifest.principals[slot].name for slot in SLOTS])
    memberships = await _rows(
        connection,
        (
            "SELECT member.rolname AS member, parent.rolname AS parent "
            "FROM pg_catalog.pg_auth_members a "
            "JOIN pg_catalog.pg_roles member ON member.oid=a.member "
            "JOIN pg_catalog.pg_roles parent ON parent.oid=a.roleid "
            f"WHERE member.rolname IN ({names}) ORDER BY member.rolname, parent.rolname"
        ),
        parameters,
    )
    relations = await _rows(
        connection,
        (
            "SELECT c.relname AS name, c.relkind::text AS kind, "
            "pg_get_userbyid(c.relowner) AS owner "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') "
            "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend d WHERE d.classid="
            "'pg_catalog.pg_class'::regclass AND d.objid=c.oid AND d.deptype='e') "
            "ORDER BY c.relname"
        ),
        {},
    )
    functions = await _rows(
        connection,
        (
            "SELECT p.oid::regprocedure::text AS name, pg_get_userbyid(p.proowner) AS owner "
            "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend d "
            "WHERE d.classid='pg_catalog.pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e') "
            "ORDER BY p.oid::regprocedure::text"
        ),
        {},
    )
    owner = (
        await connection.execute(
            text(
                "SELECT pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace "
                "WHERE nspname='public'"
            )
        )
    ).scalar_one()
    exists = (
        await connection.execute(text("SELECT to_regclass('public.alembic_version')"))
    ).scalar_one_or_none()
    revisions = (
        []
        if exists is None
        else list(
            (
                await connection.execute(
                    text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                )
            ).scalars()
        )
    )
    if exists is not None and len(revisions) != 1:
        raise RuntimeError("database retry revision history is inconsistent")
    activity = (
        await connection.execute(
            text(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() "
                "AND usename IN (:bootstrap, :migration)"
            ),
            {
                "bootstrap": manifest.principals[PrincipalSlot.BOOTSTRAP].name,
                "migration": parameters["migration"],
            },
        )
    ).scalar_one()
    locks = (
        await connection.execute(
            text(
                "SELECT count(*) FROM pg_catalog.pg_locks WHERE locktype='advisory' AND granted "
                "AND database=(SELECT oid FROM pg_catalog.pg_database "
                "WHERE datname=current_database()) "
                "AND objsubid=1 AND classid::bigint=:high AND objid::bigint=:low "
                "AND pid<>pg_backend_pid()"
            ),
            {
                "high": MIGRATION_ADVISORY_LOCK_ID >> 32,
                "low": MIGRATION_ADVISORY_LOCK_ID & 0xFFFFFFFF,
            },
        )
    ).scalar_one()
    return {
        "currentUser": current[0],
        "database": current[1],
        "roles": roles,
        "mappings": mappings,
        "memberships": memberships,
        "schemaOwner": owner,
        "relations": relations,
        "functions": functions,
        "revisions": revisions,
        "activeWriters": activity,
        "migrationLocks": locks,
    }


def _validate(
    observation: dict[str, object],
    manifest: PrincipalManifest,
    operation: Operation,
) -> tuple[str, str, int, int]:
    slot = PrincipalSlot.BOOTSTRAP if operation == "bootstrap" else PrincipalSlot.MIGRATION
    current = observation["currentUser"]
    if not isinstance(current, str) or observation["database"] != APPLICATION_DATABASE:
        raise RuntimeError("database retry target binding differs")
    manifest.require_current(slot, current_name=current)
    if any(
        type(observation[key]) is not int or observation[key] != 0
        for key in ("activeWriters", "migrationLocks")
    ):
        raise RuntimeError("database retry has an active or unverified writer")
    roles = observation["roles"]
    mappings = observation["mappings"]
    if not isinstance(roles, list) or not isinstance(mappings, list):
        raise RuntimeError("database retry principal observation is malformed")
    expected = {manifest.principals[role].name: manifest.principals[role] for role in SLOTS}
    seen: set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            raise RuntimeError("database retry role observation is malformed")
        name = role.get("rolname")
        if (
            not isinstance(name, str)
            or name not in expected
            or name in seen
            or any(
                role.get(key) is not False
                for key in (
                    "rolsuper",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                    "rolbypassrls",
                )
            )
        ):
            raise RuntimeError("database retry principal is unexpected or overprivileged")
        seen.add(name)
    if any(not isinstance(item, dict) for item in mappings):
        raise RuntimeError("database retry Entra mapping is malformed")
    require_mappings(mappings, {name: expected[name].object_id for name in seen})
    memberships = observation["memberships"]
    if not isinstance(memberships, list):
        raise RuntimeError("database retry role memberships are unverified")
    allowed_memberships = {(manifest.principals[PrincipalSlot.EVIDENCE].name, "pg_monitor")}
    observed_memberships: set[tuple[str, str]] = set()
    for item in memberships:
        member = item.get("member") if isinstance(item, dict) else None
        parent = item.get("parent") if isinstance(item, dict) else None
        if not isinstance(member, str) or not isinstance(parent, str):
            raise RuntimeError("database retry role memberships are malformed")
        edge = (member, parent)
        if member not in seen or edge not in allowed_memberships or edge in observed_memberships:
            raise RuntimeError("database retry role has an unexpected inherited privilege")
        observed_memberships.add(edge)
    relations, functions = observation["relations"], observation["functions"]
    revisions = observation["revisions"]
    if not isinstance(relations, list) or not isinstance(functions, list):
        raise RuntimeError("database retry schema observation is malformed")
    if not isinstance(revisions, list) or revisions not in ([], [EXPECTED_DATABASE_REVISION]):
        raise RuntimeError("database retry revision is unsupported")
    revision = EXPECTED_DATABASE_REVISION if revisions else "base"
    migration = manifest.principals[PrincipalSlot.MIGRATION].name
    if revision == "base":
        if relations or functions:
            raise RuntimeError("database retry base revision has partial schema objects")
        if observation["schemaOwner"] not in {
            manifest.principals[PrincipalSlot.BOOTSTRAP].name,
            migration,
            "pg_database_owner",
        }:
            raise RuntimeError("database retry empty schema owner is unexpected")
    else:
        if operation == "bootstrap":
            raise RuntimeError("database bootstrap retry cannot alter a migrated schema")
        from opencanvas_api.db.models import Base

        tables = {
            item.get("name")
            for item in relations
            if isinstance(item, dict) and item.get("kind") in {"r", "p"}
        }
        if tables != set(Base.metadata.tables) | {"alembic_version"}:
            raise RuntimeError("database retry head schema inventory differs")
        if observation["schemaOwner"] != migration or any(
            not isinstance(item, dict) or item.get("owner") != migration
            for item in [*relations, *functions]
        ):
            raise RuntimeError("database retry schema ownership differs")
    if operation == "migrate" and seen != set(expected):
        raise RuntimeError("database migration retry principals are incomplete")
    state = (
        (
            "bootstrap-empty"
            if not seen
            else "bootstrap-existing"
            if len(seen) == 4
            else "bootstrap-partial"
        )
        if operation == "bootstrap"
        else ("migration-empty" if revision == "base" else "migration-grants-reconcile")
    )
    return state, revision, len(seen), len(relations)


async def require_safe_retry(
    connection: AsyncConnection,
    *,
    identity: AsyncConnection,
    operation: Operation,
    previous_execution: str,
    manifest: PrincipalManifest,
) -> dict[str, object]:
    """Observe real catalogs before a separately authorized same-job retry.

    This performs SELECTs only. It never repairs a role mapping or rewrites a
    revision. The existing migration runner still owns the mutation-time lock.
    """
    if retry_argument([f"--retry-after-execution={previous_execution}"]) != previous_execution:
        raise RuntimeError("database retry execution binding differs")
    slot = PrincipalSlot.BOOTSTRAP if operation == "bootstrap" else PrincipalSlot.MIGRATION
    async with asyncio.timeout(30):
        await require_bound_connection(identity, manifest, slot, IDENTITY_DATABASE)
        observation = await _observe(connection, manifest, identity)
    state, revision, count, relation_count = _validate(observation, manifest, operation)
    raw_manifest = json.loads(environ[MANIFEST_ENV])
    marker: dict[str, object] = {
        "version": VERSION,
        "operation": operation,
        "previousExecution": previous_execution,
        "campaignId": manifest.campaign_id,
        "generationId": manifest.generation_id,
        "manifestSha256": _digest("m7.8/database-recovery-manifest/v1", raw_manifest),
        "observedRevision": revision,
        "state": state,
        "principalCount": count,
        "applicationRelationCount": relation_count,
        "snapshotSha256": _digest("m7.8/database-recovery-snapshot/v1", observation),
        "status": "retry-preflight-passed",
    }
    print(PREFIX + json.dumps(marker, sort_keys=True, separators=(",", ":")), flush=True)
    return marker
