from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from contextlib import redirect_stdout
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION, DatabaseRole, Settings
from opencanvas_api.db.models import Base
from opencanvas_api.db.principal_manifest import (
    CAMPAIGN_ENV,
    CURRENT_PRINCIPAL_ID_ENV,
    GENERATION_ENV,
    MANIFEST_ENV,
    PrincipalManifest,
    PrincipalSlot,
    load_principal_manifest,
)
from opencanvas_api.db.session import Database
from scripts import bootstrap_postgres, migrate_and_grant
from scripts import m78_database_identity as identity_sql
from scripts import m78_database_prerequisites as prerequisites
from scripts import m78_database_recovery as recovery

CREATE_ROUTINE = "pg_catalog.pgaadauth_create_principal_with_oid"
CREATE_ARGUMENTS = (
    "rolename text",
    "objectid text",
    "objecttype text",
    "isadmin boolean",
    "ismfa boolean",
    "tenantid text DEFAULT NULL::text",
    "skipvalidation boolean DEFAULT false",
)


def create_signature(arguments: tuple[str, ...]) -> str:
    types = ",".join(argument.split()[1] for argument in arguments)
    return f"{CREATE_ROUTINE}({types})"


@pytest.fixture
def manifest(monkeypatch: pytest.MonkeyPatch) -> PrincipalManifest:
    value = {
        "version": "m7.8-principal-manifest-v1",
        "campaignId": "m78-recovery-fixture",
        "generationId": "g1-0123456789ab",
        "subscriptionCorrelation": "a" * 16,
        "principals": {
            slot.value: {
                "role": slot.value,
                "name": f"m78-{slot.value}",
                "objectId": str(uuid.UUID(int=index + 1)),
            }
            for index, slot in enumerate(PrincipalSlot)
        },
    }
    monkeypatch.setenv(MANIFEST_ENV, json.dumps(value))
    monkeypatch.setenv(CAMPAIGN_ENV, str(value["campaignId"]))
    monkeypatch.setenv(GENERATION_ENV, str(value["generationId"]))
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, str(uuid.UUID(int=1)))
    return load_principal_manifest()


def state(manifest: PrincipalManifest, *, head: bool = False, absent: int = 0) -> dict[str, Any]:
    selected = list(recovery.SLOTS)[absent:]
    roles = [
        {
            "rolname": manifest.principals[slot].name,
            **{
                key: False
                for key in (
                    "rolsuper",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                    "rolbypassrls",
                )
            },
        }
        for slot in selected
    ]
    mappings = [
        {
            "mapping": {
                "rolename": manifest.principals[slot].name,
                "principalType": "service",
                "objectId": manifest.principals[slot].object_id,
                "tenantId": str(uuid.UUID(int=99)),
                "isMfa": 0,
                "isAdmin": 0,
            }
        }
        for slot in selected
    ]
    bootstrap = manifest.principals[PrincipalSlot.BOOTSTRAP]
    mappings.append({
        "mapping": {
            "rolename": bootstrap.name,
            "principalType": "service",
            "objectId": bootstrap.object_id,
            "tenantId": str(uuid.UUID(int=99)),
            "isMfa": 0,
            "isAdmin": 1,
        }
    })
    migration = manifest.principals[PrincipalSlot.MIGRATION].name
    return {
        "currentUser": manifest.principals[PrincipalSlot.BOOTSTRAP].name,
        "database": "opencanvas",
        "roles": roles,
        "mappings": mappings,
        "memberships": [],
        "schemaOwner": migration,
        "relations": [
            {"name": name, "kind": "r", "owner": migration}
            for name in sorted(set(Base.metadata.tables) | {"alembic_version"})
        ]
        if head
        else [],
        "functions": [],
        "revisions": [EXPECTED_DATABASE_REVISION] if head else [],
        "activeWriters": 0,
        "migrationLocks": 0,
    }


class Result:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def mappings(self) -> Result:
        return self

    def __iter__(self) -> Iterator[Any]:
        return iter(self.values)

    def scalars(self) -> list[Any]:
        return self.values

    def one(self) -> Any:
        assert len(self.values) == 1
        return self.values[0]

    def scalar_one(self) -> Any:
        return self.one()

    def scalar_one_or_none(self) -> Any:
        return self.one() if self.values else None

    def one_or_none(self) -> Any:
        return self.scalar_one_or_none()


class Connection:
    def __init__(self, observed: dict[str, Any]) -> None:
        self.observed = observed
        self.queries: list[str] = []
        self.mutations: list[str] = []
        self.output: io.StringIO | None = None
        self.database = observed["database"]

    async def execute(self, statement: object, parameters: object = None) -> Result:
        sql = str(statement)
        self.queries.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            return Result([])
        if not sql.startswith("SELECT"):
            if self.output is not None:
                assert recovery.PREFIX in self.output.getvalue()
            self.mutations.append(sql)
            return Result([])
        if sql == "SELECT current_user":
            return Result([self.observed["currentUser"]])
        if sql == "SELECT current_user, current_database()":
            return Result([(self.observed["currentUser"], self.database)])
        if "pg_catalog.has_function_privilege" in sql:
            assert self.database == "postgres"
            assert isinstance(parameters, dict)
            # pg_proc records all argument types, including both defaulted
            # arguments. Only the exact signature resolves for ACL inspection.
            available = {
                "pg_catalog.pgaadauth_list_principals(boolean)",
                create_signature(CREATE_ARGUMENTS),
            }
            signature_exists = parameters.get("signature") in available
            return Result([signature_exists and self.observed.get("functionExecute", True)])
        if "pg_available_extension_versions" in sql:
            assert self.database == "opencanvas"
            return Result([{
                "version": "0.8.2", "trusted": False, "superuser": True, "schema": None,
                "requires": None, "installed_schema": "public", "allowlist": None,
                "database_create": True, "schema_create": True, "rolsuper": True,
                "azure_admin": False,
            }])
        if "e.extname='vector'" in sql and "SELECT EXISTS" in sql:
            assert self.database == "opencanvas"
            return Result([True])
        if "WHERE rolname = :principal" in sql:
            assert isinstance(parameters, dict)
            rows = [r for r in self.observed["roles"] if r["rolname"] == parameters["principal"]]
            return Result(
                [
                    tuple(
                        r[k]
                        for k in (
                            "rolsuper",
                            "rolcreatedb",
                            "rolcreaterole",
                            "rolreplication",
                            "rolbypassrls",
                        )
                    )
                    for r in rows
                ]
            )
        if "FROM pg_catalog.pg_roles WHERE" in sql:
            return Result(self.observed["roles"])
        if "pgaadauth_list_principals" in sql:
            assert self.database == "postgres"
            assert parameters is None and "p.rolename" not in sql and "p.rolname" not in sql
            if error := self.observed.get("listingError"):
                raise error
            return Result(self.observed["mappings"])
        for fragment, key in (
            ("FROM pg_catalog.pg_auth_members", "memberships"),
            ("FROM pg_catalog.pg_class c", "relations"),
            ("FROM pg_catalog.pg_proc p", "functions"),
        ):
            if fragment in sql:
                return Result(self.observed[key])
        for fragment, key in (
            ("pg_namespace WHERE nspname='public'", "schemaOwner"),
            ("FROM pg_catalog.pg_stat_activity", "activeWriters"),
            ("FROM pg_catalog.pg_locks", "migrationLocks"),
        ):
            if fragment in sql:
                return Result([self.observed[key]])
        if "to_regclass" in sql:
            return Result(["alembic_version"] if self.observed["revisions"] else [])
        if "version_num" in sql:
            return Result(self.observed["revisions"])
        if any(
            fragment in sql
            for fragment in (
                "SELECT tablename",
                "SELECT sequencename",
                "SELECT p.oid::regprocedure",
            )
        ):
            return Result([])
        raise AssertionError(f"unexpected SQL shape: {sql[:40]}")

    def begin_nested(self) -> Connection:
        return self

    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def separate_identity(connection: Connection) -> Connection:
    identity = Connection(connection.observed)
    identity.database = "postgres"
    return identity


@pytest.mark.asyncio
@pytest.mark.parametrize("name_field", ["rolname", "rolename", "roleName"])
async def test_list_mappings_accepts_named_provider_columns(
    manifest: PrincipalManifest, name_field: str,
) -> None:
    observed = state(manifest)
    mappings = observed["mappings"]
    for entry in mappings:
        mapping = entry["mapping"]
        mapping[name_field] = mapping.pop("rolename")
    mappings.extend([
        {"mapping": {**mappings[0]["mapping"], name_field: "unrelated-group",
                     "principalType": "group"}},
        {"mapping": {**mappings[0]["mapping"], name_field: "unrelated-user",
                     "principalType": "user"}},
    ])
    mappings.reverse()
    identity = cast(AsyncConnection, separate_identity(Connection(observed)))
    principals = [manifest.principals[slot] for slot in recovery.SLOTS]
    requested = {principal.name: principal.object_id for principal in principals}
    rows = await identity_sql.list_mappings(identity, list(requested))
    assert [row["mapping"] for row in rows] == [
        entry["mapping"] for name in sorted(requested) for entry in mappings
        if entry["mapping"][name_field] == name
    ]
    identity_sql.require_mappings(rows, requested)
    assert await identity_sql.list_mappings(identity, ["no-such-valid-principal"]) == []
    with pytest.raises(RuntimeError, match="database Entra mapping differs"):
        identity_sql.require_mappings(rows, dict.fromkeys(requested, "unverified"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["name", "alias", "case", "object", "tenant", "flags", "duplicate"],
)
async def test_malformed_listing_cannot_look_like_an_empty_recovery_scope(
    manifest: PrincipalManifest, defect: str,
) -> None:
    observed = state(manifest, absent=4)
    row = observed["mappings"][0]["mapping"]
    if defect == "name":
        row["unrecognizedName"] = row.pop("rolename")
    elif defect == "alias":
        row["rolname"] = row["rolename"]
    elif defect == "case":
        row["roleName"] = row["rolename"]
    elif defect == "object":
        row.pop("objectId")
    elif defect == "tenant":
        row["tenantId"] = "unverified"
    elif defect == "flags":
        row["isAdmin"] = True
    else:
        observed["mappings"].append(observed["mappings"][0])
    identity = cast(AsyncConnection, separate_identity(Connection(observed)))
    with pytest.raises(RuntimeError, match="database Entra mapping"):
        await identity_sql.list_mappings(identity, [])


@pytest.mark.asyncio
async def test_exact_create_identity_preserves_five_argument_bootstrap_call(
    manifest: PrincipalManifest,
) -> None:
    observed = state(manifest)
    missing_role = observed["roles"].pop(0)
    missing_mapping = observed["mappings"].pop(0)
    principal = manifest.principals[PrincipalSlot.MIGRATION]
    contract = bootstrap_postgres.PrincipalContract(principal.name, principal.object_id)
    calls = []

    class FreshIdentity(Connection):
        async def execute(self, statement: object, parameters: object = None) -> Result:
            sql = str(statement)
            if sql.startswith(f"SELECT * FROM {CREATE_ROUTINE}("):
                assert self.database == "postgres"
                assert sql == (
                    f"SELECT * FROM {CREATE_ROUTINE}(CAST(:principal AS text), "
                    "CAST(:object_id AS text), 'service'::text, false, false)"
                )
                assert parameters == {"principal": principal.name, "object_id": principal.object_id}
                defaults = tuple(
                    argument.split(" DEFAULT ")[1] for argument in CREATE_ARGUMENTS[5:]
                )
                calls.append(defaults)
                self.observed["roles"].append(missing_role)
                self.observed["mappings"].append(missing_mapping)
                return Result([True])
            return await super().execute(statement, parameters)

    fixture = FreshIdentity(observed)
    fixture.database = "postgres"
    connection = cast(AsyncConnection, fixture)
    assert not await identity_sql.function_executable(
        connection, create_signature(CREATE_ARGUMENTS[:5])
    )
    assert await identity_sql.function_executable(connection, identity_sql.CREATE_SIGNATURE)
    await bootstrap_postgres._ensure_principal(connection, contract)
    assert calls == [("NULL::text", "false")]


def use_database(
    monkeypatch: pytest.MonkeyPatch,
    connection: Connection,
    *,
    role: DatabaseRole,
) -> list[str]:
    events: list[str] = []

    async def dispose() -> None:
        events.append("disposed")

    identity = separate_identity(connection)
    username = connection.observed["currentUser"]

    def from_settings(settings: Settings, *, expected_role: DatabaseRole) -> SimpleNamespace:
        assert expected_role is role
        url = make_url(settings.database_url_value)
        assert url.username == username and url.host == "fixture.invalid"
        assert url.database in {"postgres", "opencanvas"}
        selected = connection if url.database == "opencanvas" else identity
        return SimpleNamespace(
            engine=SimpleNamespace(begin=lambda: selected, connect=lambda: selected),
            dispose=dispose,
        )

    async def configure_vector(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(bootstrap_postgres, "configure_vector_runtime_functions", configure_vector)
    monkeypatch.setattr(Database, "from_settings", from_settings)
    settings = Settings(
        database_role=role,
        database_url=SecretStr(f"postgresql+asyncpg://{username}@fixture.invalid/opencanvas"),
    )
    monkeypatch.setattr(bootstrap_postgres, "get_settings", lambda: settings)
    monkeypatch.setattr(migrate_and_grant, "get_settings", lambda: settings)
    monkeypatch.setattr(prerequisites, "get_settings", lambda: settings)
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "absent,expected", [(4, "bootstrap-empty"), (2, "bootstrap-partial"), (0, "bootstrap-existing")]
)
async def test_real_query_handoff_accepts_only_bound_bootstrap_states(
    manifest: PrincipalManifest,
    absent: int,
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = Connection(state(manifest, absent=absent))
    marker = await recovery.require_safe_retry(
        cast(AsyncConnection, connection),
        identity=cast(AsyncConnection, separate_identity(connection)),
        operation="bootstrap",
        previous_execution="previous-execution",
        manifest=manifest,
    )
    assert marker["state"] == expected and marker["principalCount"] == 4 - absent
    assert len(str(marker["snapshotSha256"])) == 64
    assert connection.queries and all(q.startswith("SELECT") for q in connection.queries)
    assert not connection.mutations
    printed = capsys.readouterr().out
    assert json.loads(printed.removeprefix(recovery.PREFIX)) == marker
    assert all(
        binding.object_id not in printed and binding.name not in printed
        for binding in manifest.principals.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "mapping",
        "missing-mapping",
        "duplicate-mapping",
        "admin",
        "role-flags",
        "membership",
        "intermediate",
        "multiple-heads",
        "partial-schema",
        "writer",
        "lock",
        "target",
        "owner",
    ],
)
async def test_unsafe_observed_partial_state_cannot_emit_retry_marker_or_mutate(
    manifest: PrincipalManifest,
    bad: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest)
    if bad == "mapping":
        observed["mappings"][0]["mapping"]["objectId"] = str(uuid.UUID(int=555))
    elif bad == "missing-mapping":
        observed["mappings"].pop(0)
    elif bad == "duplicate-mapping":
        observed["mappings"].append(observed["mappings"][0])
    elif bad == "admin":
        observed["mappings"][0]["mapping"]["isAdmin"] = 1
    elif bad == "role-flags":
        observed["roles"][0]["rolcreaterole"] = True
    elif bad == "membership":
        observed["memberships"] = [{"member": "m78-api", "parent": "m78-migration"}]
    elif bad == "intermediate":
        observed["revisions"] = ["20260726_0028"]
    elif bad == "multiple-heads":
        observed["revisions"] = [EXPECTED_DATABASE_REVISION] * 2
    elif bad == "partial-schema":
        observed["relations"] = [{"name": "canvases", "kind": "r", "owner": "m78-migration"}]
    elif bad == "writer":
        observed["activeWriters"] = 1
    elif bad == "lock":
        observed["migrationLocks"] = 1
    elif bad == "target":
        observed["database"] = "another-database"
    elif bad == "owner":
        observed["schemaOwner"] = "unrelated-owner"
    connection = Connection(observed)
    with pytest.raises(RuntimeError):
        await recovery.require_safe_retry(
            cast(AsyncConnection, connection),
            identity=cast(AsyncConnection, separate_identity(connection)),
            operation="bootstrap",
            previous_execution="previous",
            manifest=manifest,
        )
    assert not connection.mutations and recovery.PREFIX not in capsys.readouterr().out


def test_normal_bootstrap_retry_inspects_before_actual_privilege_statements(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
) -> None:
    connection = Connection(state(manifest))
    events = use_database(monkeypatch, connection, role=DatabaseRole.PROVISIONING)
    output = io.StringIO()
    connection.output = output
    with redirect_stdout(output):
        assert bootstrap_postgres.main(["--retry-after-execution=previous"]) == 0
    assert connection.mutations and all(
        q.startswith(("GRANT", "REVOKE", "ALTER")) for q in connection.mutations
    )
    assert events == ["disposed", "disposed"]
    assert recovery.PREFIX in output.getvalue()


def test_normal_bootstrap_retry_unsafe_state_never_reaches_existing_writes(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest)
    observed["mappings"][0]["mapping"]["objectId"] = str(uuid.UUID(int=777))
    connection = Connection(observed)
    events = use_database(monkeypatch, connection, role=DatabaseRole.PROVISIONING)
    assert bootstrap_postgres.main(["--retry-after-execution=previous"]) == 1
    assert not connection.mutations and events == ["disposed", "disposed"]
    captured = capsys.readouterr()
    assert recovery.PREFIX not in captured.out and "777" not in captured.err


def test_idempotent_bootstrap_rejects_mapped_name_with_different_object(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest)
    observed["mappings"][0]["mapping"]["objectId"] = str(uuid.UUID(int=777))
    connection = Connection(observed)
    use_database(monkeypatch, connection, role=DatabaseRole.PROVISIONING)
    assert bootstrap_postgres.main() == 1
    assert not connection.mutations
    captured = capsys.readouterr()
    assert '"stage":"principal-provisioning"' in captured.err
    assert "777" not in captured.err


@pytest.mark.parametrize("operation", ["bootstrap", "migrate"])
def test_read_only_prerequisites_require_actual_identity_listing(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    operation: prerequisites.Operation,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest)
    role = DatabaseRole.PROVISIONING
    main = bootstrap_postgres.main
    if operation == "migrate":
        principal = manifest.principals[PrincipalSlot.MIGRATION]
        observed["currentUser"] = principal.name
        monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, principal.object_id)
        role = DatabaseRole.MIGRATION
        main = migrate_and_grant.main
    connection = Connection(observed)
    use_database(monkeypatch, connection, role=role)
    token = "a" * 32
    monkeypatch.setenv(prerequisites.TOKEN_ENV, token)
    assert main(["--diagnose-prerequisites"]) == 0
    assert not connection.mutations
    assert "SET TRANSACTION READ ONLY" in connection.queries
    assert not any("pgaadauth" in sql for sql in connection.queries)
    payload = json.loads(capsys.readouterr().out.removeprefix(prerequisites.PREFIX + token + " "))
    assert payload["identityDatabase"] == "postgres"
    assert payload["applicationDatabase"] == "opencanvas"
    assert payload["listingRead"] is True and payload["operation"] == operation
    assert payload["createExecute"] is (True if operation == "bootstrap" else None)


@pytest.mark.parametrize("status", ["42501", "42883", "08006", "timeout", "acl-denied"])
def test_only_bound_listing_permission_failure_allows_migration_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    status: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    principal = manifest.principals[PrincipalSlot.MIGRATION]
    observed = state(manifest)
    observed["currentUser"] = principal.name
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, principal.object_id)
    token = "a" * 32
    monkeypatch.setenv(prerequisites.TOKEN_ENV, token)
    if status == "acl-denied":
        observed["functionExecute"] = False
    elif status == "timeout":
        observed["listingError"] = TimeoutError("sensitive")
    else:
        class DriverError(Exception):
            sqlstate = status

        observed["listingError"] = DBAPIError(None, None, DriverError("sensitive"))
    connection = Connection(observed)
    use_database(monkeypatch, connection, role=DatabaseRole.MIGRATION)
    denied = status in {"42501", "42883", "acl-denied"}
    assert migrate_and_grant.main(["--diagnose-prerequisites"]) == (0 if denied else 1)
    captured = capsys.readouterr()
    assert "sensitive" not in captured.err and not connection.mutations
    if denied:
        payload = json.loads(captured.out.removeprefix(prerequisites.PREFIX + token + " "))
        assert payload["listingRead"] is False
    else:
        assert prerequisites.PREFIX not in captured.out


def test_migration_diagnostic_binds_stage_and_sqlstate_without_error_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DriverError(Exception):
        sqlstate = "42501"

    async def current_revision() -> str:
        raise DBAPIError(None, None, DriverError("sensitive"))

    monkeypatch.setattr(migrate_and_grant, "_current_revision", current_revision)
    assert migrate_and_grant.main() == 1
    diagnostic = capsys.readouterr().err
    assert "sensitive" not in diagnostic
    assert '"stage":"database-revision"' in diagnostic
    assert '"sqlstate":"42501"' in diagnostic


@pytest.mark.parametrize("head", [False, True])
def test_normal_migration_retry_inspects_then_uses_existing_upgrade_or_grant_reconcile(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    head: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest, head=head)
    observed["currentUser"] = manifest.principals[PrincipalSlot.MIGRATION].name
    monkeypatch.setenv(
        CURRENT_PRINCIPAL_ID_ENV, manifest.principals[PrincipalSlot.MIGRATION].object_id
    )
    connection = Connection(observed)
    use_database(monkeypatch, connection, role=DatabaseRole.MIGRATION)
    events: list[str] = []

    def migrate(*, expected_current: str, target: str) -> int:
        assert expected_current == "base" and target == EXPECTED_DATABASE_REVISION
        events.append("upgrade")
        observed["revisions"] = [EXPECTED_DATABASE_REVISION]
        return 0

    async def grants() -> None:
        events.append("reconcile-grants")

    monkeypatch.setattr(migrate_and_grant, "run_migration", migrate)
    monkeypatch.setattr(migrate_and_grant, "apply_runtime_privileges", grants)
    assert migrate_and_grant.main(["--retry-after-execution=previous"]) == 0
    assert events == ([] if head else ["upgrade"]) + ["reconcile-grants"]
    marker = json.loads(capsys.readouterr().out.removeprefix(recovery.PREFIX))
    assert marker["state"] == ("migration-grants-reconcile" if head else "migration-empty")


def test_normal_head_retry_reads_internal_relation_kind_as_text(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest, head=True)
    observed["currentUser"] = manifest.principals[PrincipalSlot.MIGRATION].name
    monkeypatch.setenv(
        CURRENT_PRINCIPAL_ID_ENV, manifest.principals[PrincipalSlot.MIGRATION].object_id
    )

    class AsyncpgConnection(Connection):
        async def execute(self, statement: object, parameters: object = None) -> Result:
            result = await super().execute(statement, parameters)
            if "FROM pg_catalog.pg_class c" in str(statement):
                # PostgreSQL internal "char" is bytes in asyncpg; text is str.
                return Result(
                    [
                        {
                            **row,
                            "kind": row["kind"]
                            if "c.relkind::text AS kind" in str(statement)
                            else row["kind"].encode(),
                        }
                        for row in result.values
                    ]
                )
            return result

    connection = AsyncpgConnection(observed)
    use_database(monkeypatch, connection, role=DatabaseRole.MIGRATION)
    reconciled: list[bool] = []

    async def grants() -> None:
        reconciled.append(True)

    def no_upgrade(**_kwargs: object) -> int:
        raise AssertionError("head reconciliation must not repeat migrations")

    monkeypatch.setattr(migrate_and_grant, "run_migration", no_upgrade)
    monkeypatch.setattr(migrate_and_grant, "apply_runtime_privileges", grants)
    assert migrate_and_grant.main(["--retry-after-execution=previous"]) == 0
    assert reconciled == [True]
    marker = json.loads(capsys.readouterr().out.removeprefix(recovery.PREFIX))
    assert marker["state"] == "migration-grants-reconcile"
    assert marker["applicationRelationCount"] == len(Base.metadata.tables) + 1
    assert not connection.mutations


@pytest.mark.parametrize("revision", ["base", EXPECTED_DATABASE_REVISION])
def test_grant_only_recovery_checks_bound_retry_and_never_migrates(
    monkeypatch: pytest.MonkeyPatch, revision: str,
) -> None:
    calls: list[str] = []

    async def current(*, retry_after_execution: str | None = None,
                      grants_only: bool = False) -> str:
        if retry_after_execution is None:
            calls.append("verify")
        else:
            assert grants_only and retry_after_execution == "failed-guarded-execution"
            calls.append("safe-catalog-inspection")
        return revision

    async def grants(*, grants_only: bool) -> None:
        assert grants_only
        calls.append("grants-only")

    def no_upgrade(**_kwargs: object) -> int:
        raise AssertionError("grant-only recovery must not invoke Alembic")

    monkeypatch.setattr(migrate_and_grant, "_current_revision", current)
    monkeypatch.setattr(migrate_and_grant, "apply_runtime_privileges", grants)
    monkeypatch.setattr(migrate_and_grant, "run_migration", no_upgrade)
    assert migrate_and_grant.main(["--reconcile-grants-only"]) == 1
    assert calls == []
    result = migrate_and_grant.main([
        "--reconcile-grants-only", "--retry-after-execution=failed-guarded-execution",
    ])
    assert result == int(revision == "base")
    assert calls == (["safe-catalog-inspection"] if revision == "base" else [
        "safe-catalog-inspection", "grants-only", "verify",
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["owner", "missing-table", "missing-principal"])
async def test_migration_retry_head_partial_state_rejects_unsafe_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    drift: str,
) -> None:
    observed = state(manifest, head=True)
    observed["currentUser"] = manifest.principals[PrincipalSlot.MIGRATION].name
    monkeypatch.setenv(
        CURRENT_PRINCIPAL_ID_ENV, manifest.principals[PrincipalSlot.MIGRATION].object_id
    )
    if drift == "owner":
        observed["relations"][0]["owner"] = "other"
    elif drift == "missing-table":
        observed["relations"].pop()
    else:
        observed["roles"].pop()
        observed["mappings"].pop(-2)
    connection = Connection(observed)
    with pytest.raises(RuntimeError):
        await recovery.require_safe_retry(
            cast(AsyncConnection, connection),
            identity=cast(AsyncConnection, separate_identity(connection)),
            operation="migrate",
            previous_execution="previous",
            manifest=manifest,
        )


def test_normal_legacy_script_entrypoints_do_not_parse_host_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provision(*, retry_after_execution: str | None = None) -> None:
        assert retry_after_execution is None

    monkeypatch.setattr(bootstrap_postgres, "provision_database_principals", provision)
    assert bootstrap_postgres.main() == 0


def test_retry_argument_rejects_invalid_execution() -> None:
    with pytest.raises(RuntimeError, match="execution"):
        recovery.retry_argument(["--retry-after-execution=bad' injection"])


@pytest.mark.asyncio
async def test_inspection_timeout_emits_no_passing_marker_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import asyncio

    connection = Connection(state(manifest))
    original_timeout = asyncio.timeout

    async def delayed(*_args: object) -> dict[str, object]:
        await asyncio.sleep(1)
        raise AssertionError("unreachable")

    monkeypatch.setattr(recovery, "_observe", delayed)
    monkeypatch.setattr(asyncio, "timeout", lambda _seconds: original_timeout(0.001))
    with pytest.raises(TimeoutError):
        await recovery.require_safe_retry(
            cast(AsyncConnection, connection),
            identity=cast(AsyncConnection, separate_identity(connection)),
            operation="bootstrap",
            previous_execution="previous",
            manifest=manifest,
        )
    assert not connection.mutations and recovery.PREFIX not in capsys.readouterr().out


def test_normal_migration_retry_blocks_intermediate_revision_before_upgrade_or_grants(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = state(manifest)
    observed["currentUser"] = manifest.principals[PrincipalSlot.MIGRATION].name
    observed["revisions"] = ["20260726_0028"]
    monkeypatch.setenv(
        CURRENT_PRINCIPAL_ID_ENV, manifest.principals[PrincipalSlot.MIGRATION].object_id
    )
    connection = Connection(observed)
    use_database(monkeypatch, connection, role=DatabaseRole.MIGRATION)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unsafe recovery reached a mutation")

    monkeypatch.setattr(migrate_and_grant, "run_migration", forbidden)
    monkeypatch.setattr(migrate_and_grant, "apply_runtime_privileges", forbidden)
    assert migrate_and_grant.main(["--retry-after-execution=previous"]) == 1
    assert not connection.mutations and recovery.PREFIX not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_revision_change_after_retry_inspection_cannot_choose_a_different_mutation_path(
    monkeypatch: pytest.MonkeyPatch,
    manifest: PrincipalManifest,
) -> None:
    observed = state(manifest)
    observed["currentUser"] = manifest.principals[PrincipalSlot.MIGRATION].name
    monkeypatch.setenv(
        CURRENT_PRINCIPAL_ID_ENV,
        manifest.principals[PrincipalSlot.MIGRATION].object_id,
    )
    connection = Connection(observed)
    use_database(monkeypatch, connection, role=DatabaseRole.MIGRATION)
    real_inspection = recovery.require_safe_retry

    async def changed(*args: Any, **kwargs: Any) -> dict[str, object]:
        marker = await real_inspection(*args, **kwargs)
        observed["revisions"] = [EXPECTED_DATABASE_REVISION]
        return marker

    monkeypatch.setattr(migrate_and_grant, "require_safe_retry", changed)
    with pytest.raises(RuntimeError, match="changed after inspection"):
        await migrate_and_grant._current_revision(retry_after_execution="previous")
    assert not connection.mutations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "member,parent",
    [
        ("migration", "azure_pg_admin"),
        ("api", "pg_execute_server_program"),
        ("api", "unrelated-indirect-superuser-parent"),
        ("worker", "pg_monitor"),
        ("evidence", "pg_read_all_data"),
    ],
)
async def test_role_flags_cannot_hide_unapproved_inherited_privileges(
    manifest: PrincipalManifest,
    member: str,
    parent: str,
) -> None:
    observed = state(manifest)
    observed["memberships"] = [
        {
            "member": manifest.principals[PrincipalSlot(member)].name,
            "parent": parent,
        }
    ]
    connection = Connection(observed)
    with pytest.raises(RuntimeError, match="inherited privilege"):
        await recovery.require_safe_retry(
            cast(AsyncConnection, connection),
            identity=cast(AsyncConnection, separate_identity(connection)),
            operation="bootstrap",
            previous_execution="previous",
            manifest=manifest,
        )


@pytest.mark.asyncio
async def test_declared_evidence_monitor_membership_is_supported(
    manifest: PrincipalManifest,
) -> None:
    observed = state(manifest)
    observed["memberships"] = [
        {
            "member": manifest.principals[PrincipalSlot.EVIDENCE].name,
            "parent": "pg_monitor",
        }
    ]
    connection = Connection(observed)
    marker = await recovery.require_safe_retry(
        cast(AsyncConnection, connection),
        identity=cast(AsyncConnection, separate_identity(connection)),
        operation="bootstrap",
        previous_execution="previous",
        manifest=manifest,
    )
    assert marker["status"] == "retry-preflight-passed"
    activity = next(sql for sql in connection.queries if "pg_stat_activity" in sql)
    assert "usename IN (:bootstrap, :migration)" in activity
    assert "datname=current_database()" in activity
    assert "backend_type" not in activity and "state=" not in activity
