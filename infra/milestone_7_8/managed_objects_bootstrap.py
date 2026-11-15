"""Hash-bound external D-001 fixture bootstrap; injected into the retained image.

This does not exercise completed PostgreSQL acceptance. It reuses the shipped
Entra provisioning primitive and guarded Alembic runner for one isolated object
proof database, with a nonadministrator runtime principal. No image rebuild.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from opencanvas_api.core.config import Settings


DATABASE = "opencanvas_objects"
ROOT_CERT = "/etc/ssl/certs/ca-certificates.crt"


def bound_configuration(environment: dict[str, str]) -> dict[str, str]:
    """Reject cross-campaign targets and any password/TLS downgrade before I/O."""
    parsed = urlsplit(environment.get("OPENCANVAS_DATABASE_URL", ""))
    match = re.fullmatch(r"id-m78o-([a-f0-9]{10})-bootstrap", parsed.username or "")
    if match is None or parsed.scheme != "postgresql+asyncpg" or parsed.password is not None:
        raise RuntimeError("object bootstrap database identity is not bound")
    suffix = match[1]
    host = f"pg-m78o-{suffix}.postgres.database.azure.com"
    principal = f"id-m78o-{suffix}-probe"
    if (
        parsed.hostname != host
        or parsed.port != 5432
        or parsed.path != f"/{DATABASE}"
        or parsed.query
        or parsed.fragment
        or environment.get("OPENCANVAS_DATABASE_HOST") != host
        or environment.get("OPENCANVAS_DATABASE_NAME") != DATABASE
        or environment.get("OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL") != principal
    ):
        raise RuntimeError("object bootstrap target binding differs")
    for name in (
        "OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID",
        "OPENCANVAS_OBJECT_PROBE_BOOTSTRAP_PRINCIPAL_ID",
    ):
        if uuid.UUID(environment.get(name, "")).int == 0:
            raise RuntimeError("object bootstrap principal ID is invalid")
    if (
        environment.get("OPENCANVAS_DATABASE_AUTH_MODE") != "entra"
        or environment.get("OPENCANVAS_DATABASE_TLS_MODE") != "verify-full"
        or environment.get("PGSSLROOTCERT") != ROOT_CERT
        or environment.get("OPENCANVAS_DATABASE_ROLE") != "migration"
    ):
        raise RuntimeError("object bootstrap requires bound Entra verified TLS migration settings")
    if (
        environment["OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID"]
        == environment["OPENCANVAS_OBJECT_PROBE_BOOTSTRAP_PRINCIPAL_ID"]
    ):
        raise RuntimeError("object bootstrap and runtime principals must differ")
    return {
        "host": host,
        "administrator": parsed.username or "",
        "principal": principal,
        "principalId": environment["OPENCANVAS_OBJECT_PROBE_DB_PRINCIPAL_ID"],
        "administratorId": environment["OPENCANVAS_OBJECT_PROBE_BOOTSTRAP_PRINCIPAL_ID"],
    }


def require_private_host(host: str) -> None:
    addresses = {row[4][0] for row in socket.getaddrinfo(host, 5432, type=socket.SOCK_STREAM)}
    private_networks = tuple(
        ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    if not addresses or any(
        not any(ipaddress.ip_address(address) in network for network in private_networks)
        for address in addresses
    ):
        raise RuntimeError("object bootstrap database DNS is not private")
    if not Path(ROOT_CERT).is_file():
        raise RuntimeError("object bootstrap root certificate bundle is unavailable")


def fixture_grants(principal: str) -> tuple[str, ...]:
    """Union existing literal API/worker table grants for the single proof session.

    This fixture role is not a claim about deployed API/worker database identity
    isolation. Storage operations use their separate least-privilege identities.
    """
    from opencanvas_api.core.config import DatabaseRole
    from opencanvas_api.db.role_privileges import RUNTIME_TABLE_PRIVILEGES, quote_identifier

    quoted = quote_identifier(principal)
    statements = [
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        f"REVOKE ALL PRIVILEGES ON DATABASE {DATABASE} FROM {quoted}",
        f"GRANT CONNECT ON DATABASE {DATABASE} TO {quoted}",
        f"GRANT USAGE ON SCHEMA public TO {quoted}",
        f"REVOKE CREATE ON SCHEMA public FROM {quoted}",
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {quoted}",
    ]
    for operation in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        tables = sorted(
            RUNTIME_TABLE_PRIVILEGES[DatabaseRole.API][operation]
            | RUNTIME_TABLE_PRIVILEGES[DatabaseRole.WORKER][operation]
        )
        if tables:
            qualified = ", ".join(f"public.{quote_identifier(table)}" for table in tables)
            statements.append(f"GRANT {operation} ON TABLE {qualified} TO {quoted}")
    # These exact columns also form the union of RUNTIME_ROW_LOCK_COLUMNS in
    # the corrected source. Keep the external fixture compatible with the
    # retained image, whose grant generator predates that permission correction.
    for table, column in (
        ("malware_scan_requests", "scan_request_id"),
        ("object_deletion_requests", "deletion_request_id"),
        ("upload_sessions", "session_id"),
    ):
        statements.append(
            f"GRANT UPDATE ({quote_identifier(column)}) ON TABLE "
            f"public.{quote_identifier(table)} TO {quoted}"
        )
    statements.extend(
        [
            "CREATE SCHEMA IF NOT EXISTS m78_object_probe",
            "CREATE TABLE IF NOT EXISTS m78_object_probe.receipts ("
            "campaign uuid NOT NULL, phase text NOT NULL, attempt uuid NOT NULL, "
            "status text NOT NULL, source_sha256 text NOT NULL, result jsonb NOT NULL, "
            "recorded_at timestamptz NOT NULL DEFAULT now(), "
            "PRIMARY KEY (campaign, phase, attempt))",
            f"REVOKE ALL PRIVILEGES ON SCHEMA m78_object_probe FROM {quoted}",
            f"GRANT USAGE ON SCHEMA m78_object_probe TO {quoted}",
            f"REVOKE ALL PRIVILEGES ON m78_object_probe.receipts FROM {quoted}",
            f"GRANT SELECT, INSERT ON m78_object_probe.receipts TO {quoted}",
        ]
    )
    return tuple(statements)


async def provision_identity(settings: Settings, binding: dict[str, str]) -> None:
    from pydantic import SecretStr
    from scripts.bootstrap_postgres import PrincipalContract, _ensure_principal
    from scripts.m78_database_identity import list_mappings, require_mappings
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from opencanvas_api.core.config import DatabaseRole
    from opencanvas_api.db.session import Database

    scoped = settings.model_copy(
        update={
            "database_url": SecretStr(
                make_url(settings.database_url_value)
                .set(database="postgres")
                .render_as_string(hide_password=False)
            )
        }
    )
    database = Database.from_settings(scoped, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.begin() as connection:
            if tuple(
                (await connection.execute(text("SELECT current_user, current_database()"))).one()
            ) != (binding["administrator"], "postgres"):
                raise RuntimeError("object bootstrap identity database differs")
            require_mappings(
                await list_mappings(connection, [binding["administrator"]]),
                {binding["administrator"]: binding["administratorId"]},
                admins=frozenset({binding["administrator"]}),
            )
            await _ensure_principal(
                connection, PrincipalContract(binding["principal"], binding["principalId"])
            )
    finally:
        await database.dispose()


async def inspect_database(
    settings: Settings, binding: dict[str, str], *, finalize: bool
) -> str | None:
    from sqlalchemy import text

    from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION, DatabaseRole
    from opencanvas_api.db.session import Database

    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.begin() as connection:
            identity = tuple(
                (await connection.execute(text("SELECT current_user, current_database()"))).one()
            )
            if identity != (binding["administrator"], DATABASE):
                raise RuntimeError("object bootstrap application database differs")
            if (
                await connection.execute(
                    text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
                )
            ).scalar_one() is not True:
                raise RuntimeError("object bootstrap connection is not TLS")
            exists = (
                await connection.execute(text("SELECT to_regclass('public.alembic_version')"))
            ).scalar_one()
            revision = None
            if exists is not None:
                revisions = (
                    (
                        await connection.execute(
                            text("SELECT version_num FROM public.alembic_version")
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(revisions) > 1:
                    raise RuntimeError("object bootstrap schema has multiple migration heads")
                revision = revisions[0] if revisions else None
            if finalize:
                if revision != EXPECTED_DATABASE_REVISION:
                    raise RuntimeError("object bootstrap schema revision differs")
                for statement in fixture_grants(binding["principal"]):
                    await connection.execute(text(statement))
                flags = (
                    await connection.execute(
                        text(
                            "SELECT rolsuper, rolcreatedb, rolcreaterole, "
                            "rolreplication, rolbypassrls "
                            "FROM pg_roles WHERE rolname=:principal"
                        ),
                        {"principal": binding["principal"]},
                    )
                ).one()
                if any(flags):
                    raise RuntimeError("object bootstrap runtime principal is overprivileged")
                elevated = (
                    await connection.execute(
                        text(
                            "SELECT pg_has_role(:principal, 'azure_pg_admin', 'MEMBER'), "
                            "pg_has_role(:principal, :administrator, 'MEMBER')"
                        ),
                        {
                            "principal": binding["principal"],
                            "administrator": binding["administrator"],
                        },
                    )
                ).one()
                if any(elevated):
                    raise RuntimeError(
                        "object bootstrap runtime principal inherits privileged membership"
                    )
            else:
                await connection.execute(
                    text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                )
            return revision
    finally:
        await database.dispose()


def main() -> int:
    stage = "configuration"
    try:
        binding = bound_configuration(dict(os.environ))
        require_private_host(binding["host"])
        from scripts.migrate import run as migrate

        from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION, get_settings

        settings = get_settings()
        stage = "principal"
        asyncio.run(provision_identity(settings, binding))
        stage = "schema-inspection"
        current = asyncio.run(inspect_database(settings, binding, finalize=False))
        if current != EXPECTED_DATABASE_REVISION:
            stage = "existing-guarded-migrations"
            migrate(expected_current=current or "base", target=EXPECTED_DATABASE_REVISION)
        stage = "fixture-grants"
        revision = asyncio.run(inspect_database(settings, binding, finalize=True))
        print(
            "M78_OBJECT_BOOTSTRAP "
            + json.dumps(
                {
                    "version": "m78-object-bootstrap-v1",
                    "status": "accepted",
                    "alembicRevision": revision,
                    "runtimePrincipalPrivileged": False,
                    "databaseTlsMode": "verify-full",
                    "sourceSha256": os.environ.get("M78_EXECUTION_SHA256", ""),
                    "fixtureGrantSha256": hashlib.sha256(
                        "\n".join(fixture_grants(binding["principal"])).encode()
                    ).hexdigest(),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    except Exception as error:
        # Raw exception messages can contain connection strings; emit class/stage only.
        print(
            "M78_OBJECT_BOOTSTRAP "
            + json.dumps(
                {
                    "version": "m78-object-bootstrap-v1",
                    "status": "failed",
                    "stage": stage,
                    "errorType": type(error).__name__,
                }
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
