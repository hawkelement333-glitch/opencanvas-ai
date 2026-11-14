from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.role_privileges import configure_vector_runtime_functions, quote_identifier
from opencanvas_api.db.session import Database
from scripts.m78_database_identity import (
    APPLICATION_DATABASE,
    failure_diagnostic,
    identity_connection,
    list_mappings,
    require_bound_connection,
    require_mappings,
)
from scripts.m78_database_prerequisites import (
    diagnose,
    require_installed_vector,
    vector_observation,
)
from scripts.m78_database_recovery import require_safe_retry, retry_argument


@dataclass(frozen=True, slots=True)
class PrincipalContract:
    name: str
    object_id: str


def _principal_contracts() -> tuple[PrincipalContract, ...]:
    manifest = load_principal_manifest()
    return tuple(
        PrincipalContract(manifest.principals[slot].name, manifest.principals[slot].object_id)
        for slot in (
            PrincipalSlot.MIGRATION,
            PrincipalSlot.API,
            PrincipalSlot.WORKER,
            PrincipalSlot.EVIDENCE,
        )
    )


async def _role_flags(
    connection: AsyncConnection, principal: str
) -> tuple[bool, bool, bool, bool, bool] | None:
    row = (
        await connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                "rolbypassrls FROM pg_roles WHERE rolname = :principal"
            ),
            {"principal": principal},
        )
    ).one_or_none()
    if row is None:
        return None
    return (bool(row[0]), bool(row[1]), bool(row[2]), bool(row[3]), bool(row[4]))


async def _ensure_principal(connection: AsyncConnection, contract: PrincipalContract) -> None:
    flags = await _role_flags(connection, contract.name)
    if flags is None:
        await connection.execute(
            text(
                "SELECT * FROM pg_catalog.pgaadauth_create_principal_with_oid("
                "CAST(:principal AS text), CAST(:object_id AS text), "
                "'service'::text, false, false)"
            ),
            {"principal": contract.name, "object_id": contract.object_id},
        )
        flags = await _role_flags(connection, contract.name)
    if flags is None or any(flags):
        raise RuntimeError("database principal is overprivileged")
    require_mappings(
        await list_mappings(connection, [contract.name]),
        {contract.name: contract.object_id},
    )


async def _transfer_existing_ownership(
    connection: AsyncConnection, migration_principal: str
) -> None:
    quoted_migration = quote_identifier(migration_principal)
    table_names = (
        await connection.execute(
            text(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        )
    ).scalars()
    for table_name in table_names:
        await connection.execute(
            text(
                f"ALTER TABLE public.{quote_identifier(str(table_name))} "
                f"OWNER TO {quoted_migration}"
            )
        )
    sequence_names = (
        await connection.execute(
            text(
                "SELECT sequencename FROM pg_catalog.pg_sequences "
                "WHERE schemaname = 'public' ORDER BY sequencename"
            )
        )
    ).scalars()
    for sequence_name in sequence_names:
        await connection.execute(
            text(
                f"ALTER SEQUENCE public.{quote_identifier(str(sequence_name))} "
                f"OWNER TO {quoted_migration}"
            )
        )
    function_names = (
        await connection.execute(
            text(
                "SELECT p.oid::regprocedure::text "
                "FROM pg_catalog.pg_proc AS p "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND NOT EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_extension e "
                "ON d.refobjid=e.oid WHERE d.classid='pg_catalog.pg_proc'::regclass "
                "AND d.refclassid='pg_catalog.pg_extension'::regclass "
                "AND d.deptype='e' AND d.objid=p.oid AND e.extname='vector') "
                "ORDER BY p.oid::regprocedure::text"
            )
        )
    ).scalars()
    for function_name in function_names:
        await connection.execute(
            text(f"ALTER FUNCTION {function_name} OWNER TO {quoted_migration}")
        )


def _failure_diagnostic(stage: str, error: Exception) -> None:
    failure_diagnostic("M78_BOOTSTRAP_DIAGNOSTIC ", stage, error)


async def provision_database_principals(*, retry_after_execution: str | None = None) -> None:
    stage = "configuration"
    database: Database | None = None
    failure: Exception | None = None
    try:
        settings = get_settings()
        settings.require_database_role(DatabaseRole.PROVISIONING)
        if settings.database_role is not DatabaseRole.PROVISIONING:
            raise RuntimeError("database provisioning role contract is invalid")
        contracts = _principal_contracts()
        manifest = load_principal_manifest()
        migration, api, worker, evidence = contracts
        stage = "database-client"
        database = Database.from_settings(settings, expected_role=DatabaseRole.PROVISIONING)
        stage = "connection"
        async with database.engine.begin() as connection:
            stage = "bootstrap-identity"
            await require_bound_connection(
                connection, manifest, PrincipalSlot.BOOTSTRAP, APPLICATION_DATABASE,
            )
            stage = "vector-prerequisite"
            vector = await vector_observation(
                connection, managed=settings.database_auth_mode == "entra", provisioning=True,
            )
            stage = "identity-connection"
            async with identity_connection(
                settings, role=DatabaseRole.PROVISIONING, manifest=manifest,
                slot=PrincipalSlot.BOOTSTRAP, read_only=False,
            ) as identity:
                administrator = manifest.principals[PrincipalSlot.BOOTSTRAP]
                require_mappings(
                    await list_mappings(identity, [administrator.name]),
                    {administrator.name: administrator.object_id},
                    admins=frozenset({administrator.name}),
                )
                if retry_after_execution is not None:
                    stage = "retry-inspection"
                    await require_safe_retry(
                        connection, identity=identity, operation="bootstrap",
                        previous_execution=retry_after_execution, manifest=manifest,
                    )
                stage = "principal-provisioning"
                for contract in contracts:
                    await _ensure_principal(identity, contract)
                expected = {item.name: item.object_id for item in contracts}
                expected[administrator.name] = administrator.object_id
                require_mappings(
                    await list_mappings(identity, list(expected)),
                    expected,
                    admins=frozenset({administrator.name}),
                )

            # Principal mappings commit in postgres before app grants require their
            # roles. The guarded retry inspects that partial state if app DDL fails.
            stage = "vector-installation"
            if vector["installed"] is False:
                await connection.execute(
                    text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                )
            await require_installed_vector(connection)
            await configure_vector_runtime_functions(
                connection, api_principal=api.name, worker_principal=worker.name,
            )

            stage = "schema-privileges"
            quoted_migration = quote_identifier(migration.name)
            await connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            await connection.execute(
                text(f"REVOKE ALL PRIVILEGES ON DATABASE opencanvas FROM {quoted_migration}")
            )
            await connection.execute(
                text(f"GRANT CONNECT, CREATE ON DATABASE opencanvas TO {quoted_migration}")
            )
            await connection.execute(text(f"ALTER SCHEMA public OWNER TO {quoted_migration}"))
            await connection.execute(
                text(f"GRANT USAGE, CREATE ON SCHEMA public TO {quoted_migration}")
            )
            await _transfer_existing_ownership(connection, migration.name)

            stage = "runtime-privileges"
            for runtime in (api, worker):
                quoted_runtime = quote_identifier(runtime.name)
                await connection.execute(
                    text(f"REVOKE ALL PRIVILEGES ON DATABASE opencanvas FROM {quoted_runtime}")
                )
                await connection.execute(
                    text(f"GRANT CONNECT ON DATABASE opencanvas TO {quoted_runtime}")
                )
                await connection.execute(
                    text(f"REVOKE CREATE ON SCHEMA public FROM {quoted_runtime}")
                )
                await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_runtime}"))
                await connection.execute(text(f"REVOKE {quoted_migration} FROM {quoted_runtime}"))
            stage = "evidence-privileges"
            quoted_evidence = quote_identifier(evidence.name)
            await connection.execute(
                text(f"REVOKE ALL PRIVILEGES ON DATABASE opencanvas FROM {quoted_evidence}")
            )
            await connection.execute(
                text(f"GRANT CONNECT ON DATABASE opencanvas TO {quoted_evidence}")
            )
            await connection.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {quoted_evidence}"))
            await connection.execute(text(f"GRANT pg_monitor TO {quoted_evidence}"))
            await connection.execute(text(f"REVOKE {quoted_migration} FROM {quoted_evidence}"))
    except Exception as exc:
        failure = exc
        _failure_diagnostic(stage, exc)
        raise
    finally:
        if database is not None:
            try:
                await database.dispose()
            except Exception as exc:
                _failure_diagnostic("connection-dispose", exc)
                if failure is None:
                    raise

def main(arguments: list[str] | None = None) -> int:
    if arguments == ["--diagnose-prerequisites"]:
        return diagnose("bootstrap")
    try:
        retry = retry_argument(arguments)
        asyncio.run(provision_database_principals(retry_after_execution=retry))
        return 0
    except Exception:
        print("PostgreSQL principal bootstrap failed safely.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
