from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, make_url

from opencanvas_api.db.models import WorkspaceMembershipTransition
from tests.postgres_support import (
    disposable_postgres_database,
    validate_postgres_test_url,
)

pytestmark = pytest.mark.postgres

APP_TEST_URL_ENV = "MOBIUS_APP_TEST_DATABASE_URL"
COLLABORATION_ROLES = (
    "owner",
    "administrator",
    "editor",
    "approver",
    "member",
    "viewer",
)
CURRENT_ROLE_CONSTRAINT = (
    "\"current_role\" IN ('owner', 'administrator', 'editor', 'approver', 'member', 'viewer')"
)
SEEDED_OWNER_ID = uuid.UUID("02100000-0000-4000-8000-000000000001")
SEEDED_WORKSPACE_ID = uuid.UUID("02100000-0000-4000-8000-000000000002")
SECOND_OWNER_ID = uuid.UUID("02100000-0000-4000-8000-000000000003")
SECOND_WORKSPACE_ID = uuid.UUID("02100000-0000-4000-8000-000000000004")
SEEDED_SCOPES = (
    (SEEDED_OWNER_ID, SEEDED_WORKSPACE_ID),
    (SECOND_OWNER_ID, SECOND_WORKSPACE_ID),
)
MIGRATION_0021_TABLES = (
    "collaboration_audit_events",
    "collaboration_request_identities",
    "workspace_authority_versions",
    "workspace_invitation_delivery_attempts",
    "workspace_invitation_secret_versions",
    "workspace_invitation_transitions",
    "workspace_invitations",
    "workspace_membership_transitions",
    "workspace_memberships",
)


@pytest.fixture
def postgres_migration_database_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to=None)


def _config(database_url: str) -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _asyncpg_dsn(database_url: str) -> str:
    return make_url(database_url).set(drivername="postgresql").render_as_string(False)


async def _connect(database_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(_asyncpg_dsn(database_url))


def _app_database_url(database_url: str) -> str:
    raw_url = os.getenv(APP_TEST_URL_ENV)
    if raw_url is None:
        pytest.fail(
            f"PostgreSQL session-role validation NOT RUN: set {APP_TEST_URL_ENV}",
            pytrace=False,
        )
    try:
        app_url = validate_postgres_test_url(raw_url, ci=os.getenv("CI") == "true")
    except ValueError as exc:
        pytest.fail(str(exc).replace("OPENCANVAS_POSTGRES_TEST_URL", APP_TEST_URL_ENV))
    database_name = make_url(database_url).database
    assert database_name is not None
    return app_url.set(database=database_name).render_as_string(hide_password=False)


async def _seed_0020_workspaces(database_url: str) -> None:
    connection = await _connect(database_url)
    try:
        for ordinal, (owner_id, workspace_id) in enumerate(SEEDED_SCOPES, start=1):
            email = f"owner-0021-{ordinal}@example.test"
            await connection.execute(
                """INSERT INTO users
                   (id, email, email_normalized, password_hash, display_name, email_verified)
                   VALUES ($1, $2, $2, 'test-only', $3, TRUE)""",
                owner_id,
                email,
                f"Migration 0021 Owner {ordinal}",
            )
            await connection.execute(
                """INSERT INTO workspaces (id, owner_id, name)
                   VALUES ($1, $2, $3)""",
                workspace_id,
                owner_id,
                f"Migration 0021 workspace {ordinal}",
            )
    finally:
        await connection.close()


async def _constraint_row(connection: asyncpg.Connection) -> asyncpg.Record:
    rows = await connection.fetch(
        """SELECT c.oid,
                  c.conkey,
                  a.attnum AS current_role_attnum,
                  pg_get_constraintdef(c.oid, TRUE) AS definition,
                  pg_get_expr(c.conbin, c.conrelid, TRUE) AS expression
           FROM pg_constraint c
           JOIN pg_class t ON t.oid = c.conrelid
           JOIN pg_namespace n ON n.oid = t.relnamespace
           JOIN pg_attribute a
             ON a.attrelid = t.oid AND a.attname = 'current_role'
           WHERE n.nspname = 'public'
             AND t.relname = 'workspace_membership_transitions'
             AND c.conname = 'ck_workspace_membership_transition_role'
             AND c.contype = 'c'"""
    )
    assert len(rows) == 1
    return rows[0]


def _assert_orm_parity() -> None:
    transition_table = WorkspaceMembershipTransition.__table__
    current_role_column = transition_table.c.current_role
    constraints = [
        constraint
        for constraint in transition_table.constraints
        if constraint.name == "ck_workspace_membership_transition_role"
    ]
    assert len(constraints) == 1
    constraint = constraints[0]
    assert isinstance(constraint, CheckConstraint)
    assert str(constraint.sqltext) == CURRENT_ROLE_CONSTRAINT
    assert current_role_column.nullable is False
    assert current_role_column.type.length == 24
    assert tuple(re.findall(r"'([^']+)'", str(constraint.sqltext))) == COLLABORATION_ROLES


async def _assert_database_constraint(connection: asyncpg.Connection) -> None:
    constraint = await _constraint_row(connection)
    assert list(constraint["conkey"]) == [constraint["current_role_attnum"]]
    expression = constraint["expression"]
    assert '"current_role"' in expression
    assert "::name" not in expression.lower()
    assert (
        re.search(
            r"\bcurrent_role\b",
            expression.replace('"current_role"', ""),
            flags=re.IGNORECASE,
        )
        is None
    )
    assert tuple(re.findall(r"'([^']+)'", constraint["definition"])) == COLLABORATION_ROLES


async def _assert_seeded_owner_backfills(connection: asyncpg.Connection) -> datetime:
    expected_digest = hashlib.sha256(
        b'{"reasonCode":"workspace_owner_backfill","role":"owner","state":"active"}'
    ).hexdigest()
    timestamps: set[datetime] = set()

    for owner_id, workspace_id in SEEDED_SCOPES:
        membership_id = uuid.uuid5(workspace_id, "owner-membership")
        trace_id = uuid.uuid5(workspace_id, "owner-membership-backfill-trace")
        audit_id = uuid.uuid5(workspace_id, "owner-membership-backfill-audit")
        transition_id = uuid.uuid5(membership_id, "transition:0")
        event_id = uuid.uuid5(trace_id, "event")

        trace = await connection.fetchrow(
            """SELECT event_id, trace_id, parent_trace_id, occurred_at, event_type,
                      actor_id, actor_type, user_id, workspace_id, object_id,
                      object_type, operation, status, metadata, error
               FROM trace_events
               WHERE operation = 'backfill_owner_membership'
                 AND workspace_id = $1""",
            workspace_id,
        )
        assert trace is not None
        assert tuple(trace) == (
            event_id,
            trace_id,
            None,
            trace["occurred_at"],
            "collaboration.membership.backfill",
            str(owner_id),
            "system",
            owner_id,
            workspace_id,
            membership_id,
            "workspace_membership",
            "backfill_owner_membership",
            "succeeded",
            '{"policyVersion":"collaboration-policy-v1"}',
            None,
        )

        audit = await connection.fetchrow(
            """SELECT audit_event_id, workspace_id, actor_user_id, subject_kind,
                      subject_id, action, outcome, reason_code, metadata_digest,
                      trace_id, recorded_at
               FROM collaboration_audit_events
               WHERE workspace_id = $1
                 AND action = 'membership.bootstrap_owner'""",
            workspace_id,
        )
        assert audit is not None
        assert tuple(audit) == (
            audit_id,
            workspace_id,
            owner_id,
            "workspace_membership",
            membership_id,
            "membership.bootstrap_owner",
            "succeeded",
            "workspace_owner_backfill",
            expected_digest,
            trace_id,
            audit["recorded_at"],
        )

        membership = await connection.fetchrow(
            """SELECT membership_id, user_id, workspace_id, created_by_user_id,
                      accepted_invitation_id, collaboration_policy_version,
                      creation_trace_id, creation_audit_event_id, created_at
               FROM workspace_memberships
               WHERE workspace_id = $1""",
            workspace_id,
        )
        assert membership is not None
        assert tuple(membership) == (
            membership_id,
            owner_id,
            workspace_id,
            owner_id,
            None,
            "collaboration-policy-v1",
            trace_id,
            audit_id,
            membership["created_at"],
        )

        transition = await connection.fetchrow(
            """SELECT transition_id, membership_id, user_id, workspace_id, sequence,
                      previous_state, current_state, previous_role, "current_role",
                      reason_code, collaboration_policy_version, authority_generation,
                      actor_user_id, trace_id, audit_event_id, recorded_at
               FROM workspace_membership_transitions
               WHERE workspace_id = $1""",
            workspace_id,
        )
        assert transition is not None
        assert tuple(transition) == (
            transition_id,
            membership_id,
            owner_id,
            workspace_id,
            0,
            None,
            "active",
            None,
            "owner",
            "workspace_owner_backfill",
            "collaboration-policy-v1",
            1,
            owner_id,
            trace_id,
            audit_id,
            transition["recorded_at"],
        )

        authority = await connection.fetchrow(
            """SELECT workspace_id, authority_generation, last_trace_id, updated_at
               FROM workspace_authority_versions
               WHERE workspace_id = $1""",
            workspace_id,
        )
        assert authority is not None
        assert tuple(authority) == (
            workspace_id,
            1,
            trace_id,
            authority["updated_at"],
        )
        timestamps.update(
            {
                trace["occurred_at"],
                audit["recorded_at"],
                membership["created_at"],
                transition["recorded_at"],
                authority["updated_at"],
            }
        )

    expected_count = len(SEEDED_SCOPES)
    assert await connection.fetchval("SELECT count(*) FROM workspace_memberships") == expected_count
    assert (
        await connection.fetchval("SELECT count(*) FROM workspace_membership_transitions")
        == expected_count
    )
    assert (
        await connection.fetchval("SELECT count(*) FROM collaboration_audit_events")
        == expected_count
    )
    assert (
        await connection.fetchval("SELECT count(*) FROM workspace_authority_versions")
        == expected_count
    )
    assert (
        await connection.fetchval(
            """SELECT count(*) FROM trace_events
               WHERE operation = 'backfill_owner_membership'"""
        )
        == expected_count
    )
    assert (
        await connection.fetchval(
            """SELECT count(*) FROM (
                   SELECT membership_id
                   FROM workspace_membership_transitions
                   GROUP BY membership_id
                   HAVING count(*) <> 1
               ) AS invalid_transition_counts"""
        )
        == 0
    )
    assert len(timestamps) == 1
    session_role = await connection.fetchval("SELECT CURRENT_ROLE::text")
    assert session_role not in COLLABORATION_ROLES
    return timestamps.pop()


async def _seed_transition_scope(
    connection: asyncpg.Connection,
    *,
    role: str | None,
) -> dict[str, uuid.UUID]:
    owner_id = uuid.uuid4()
    user_id = owner_id if role == "owner" else uuid.uuid4()
    workspace_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    audit_event_id = uuid.uuid4()
    email_scope = uuid.uuid4().hex
    users = [
        (
            owner_id,
            f"owner-{email_scope}@example.test",
            f"owner-{email_scope}@example.test",
            "Owner",
        )
    ]
    if user_id != owner_id:
        users.append(
            (
                user_id,
                f"member-{email_scope}@example.test",
                f"member-{email_scope}@example.test",
                "Member",
            )
        )
    await connection.executemany(
        """INSERT INTO users
           (id, email, email_normalized, password_hash, display_name, email_verified)
           VALUES ($1, $2, $3, 'test-only', $4, TRUE)""",
        users,
    )
    await connection.execute(
        """INSERT INTO workspaces (id, owner_id, name)
           VALUES ($1, $2, 'Role constraint workspace')""",
        workspace_id,
        owner_id,
    )
    await connection.execute(
        """INSERT INTO collaboration_audit_events
           (audit_event_id, workspace_id, actor_user_id, subject_kind, subject_id,
            action, outcome, reason_code, metadata_digest, trace_id, recorded_at)
           VALUES ($1, $2, $3, 'workspace_membership', $4, 'membership.seed',
                   'succeeded', 'current_role_constraint_test', $5, $6,
                   CURRENT_TIMESTAMP)""",
        audit_event_id,
        workspace_id,
        owner_id,
        membership_id,
        "0" * 64,
        uuid.uuid4(),
    )
    await connection.execute(
        """INSERT INTO workspace_memberships
           (membership_id, user_id, workspace_id, created_by_user_id,
            collaboration_policy_version, creation_trace_id,
            creation_audit_event_id, created_at)
           VALUES ($1, $2, $3, $4, 'collaboration-policy-v1', $5, $6,
                   CURRENT_TIMESTAMP)""",
        membership_id,
        user_id,
        workspace_id,
        owner_id,
        uuid.uuid4(),
        audit_event_id,
    )
    return {
        "owner_id": owner_id,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "membership_id": membership_id,
        "audit_event_id": audit_event_id,
    }


async def _insert_initial_transition(
    connection: asyncpg.Connection,
    *,
    scope: dict[str, uuid.UUID],
    role: str | None,
) -> tuple[object, ...]:
    await connection.execute(
        """INSERT INTO workspace_membership_transitions
           (transition_id, membership_id, user_id, workspace_id, sequence,
            previous_state, current_state, previous_role, "current_role", reason_code,
            collaboration_policy_version, authority_generation, actor_user_id,
            trace_id, audit_event_id, recorded_at)
           VALUES ($1, $2, $3, $4, 0, NULL, 'active', NULL, $5,
                   'current_role_constraint_test', 'collaboration-policy-v1',
                   1, $6, $7, $8, CURRENT_TIMESTAMP)""",
        uuid.uuid4(),
        scope["membership_id"],
        scope["user_id"],
        scope["workspace_id"],
        role,
        scope["owner_id"],
        uuid.uuid4(),
        scope["audit_event_id"],
    )
    row = await connection.fetchrow(
        """SELECT sequence,
                  previous_state,
                  current_state,
                  previous_role,
                  "current_role",
                  authority_generation,
                  reason_code,
                  user_id,
                  workspace_id
           FROM workspace_membership_transitions
           WHERE membership_id = $1""",
        scope["membership_id"],
    )
    assert row is not None
    assert row["user_id"] == scope["user_id"]
    assert row["workspace_id"] == scope["workspace_id"]
    return tuple(row)[:7]


async def _tracked_counts(connection: asyncpg.Connection) -> tuple[int, ...]:
    counts: list[int] = []
    for table in (
        "users",
        "workspaces",
        "collaboration_audit_events",
        "workspace_memberships",
        "workspace_membership_transitions",
    ):
        counts.append(await connection.fetchval(f"SELECT count(*) FROM {table}"))
    return tuple(counts)


async def _grant_app_transition_access(
    connection: asyncpg.Connection,
    *,
    app_role: str,
) -> None:
    database_identifier = await connection.fetchval("SELECT quote_ident(current_database())")
    role_identifier = await connection.fetchval("SELECT quote_ident($1)", app_role)
    await connection.execute(
        f"GRANT CONNECT ON DATABASE {database_identifier} TO {role_identifier}"
    )
    await connection.execute(f"GRANT USAGE ON SCHEMA public TO {role_identifier}")
    await connection.execute(
        "GRANT SELECT ON TABLE users, workspaces, collaboration_audit_events, "
        "workspace_memberships, workspace_membership_transitions "
        f"TO {role_identifier}"
    )
    await connection.execute(
        f"GRANT INSERT ON TABLE workspace_membership_transitions TO {role_identifier}"
    )


async def _assert_least_privilege_role(
    connection: asyncpg.Connection,
    *,
    role: str,
    allow_createdb: bool,
) -> None:
    attributes = await connection.fetchrow(
        """SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls
           FROM pg_roles
           WHERE rolname = $1""",
        role,
    )
    assert attributes is not None
    assert attributes["rolsuper"] is False
    assert attributes["rolcreaterole"] is False
    assert attributes["rolreplication"] is False
    assert attributes["rolbypassrls"] is False
    if not allow_createdb:
        assert attributes["rolcreatedb"] is False


async def _exercise_0021(
    database_url: str,
    app_database_url: str,
) -> datetime:
    connection = await _connect(database_url)
    try:
        assert (
            await connection.fetchval("SELECT version_num FROM alembic_version") == "20260725_0021"
        )
        await _assert_database_constraint(connection)
        backfill_timestamp = await _assert_seeded_owner_backfills(connection)

        accepted_roles: set[str] = set()
        for role in COLLABORATION_ROLES:
            scope = await _seed_transition_scope(connection, role=role)
            transition = await _insert_initial_transition(
                connection,
                scope=scope,
                role=role,
            )
            stored_role = transition[4]
            assert isinstance(stored_role, str)
            accepted_roles.add(stored_role)
        assert accepted_roles == set(COLLABORATION_ROLES)

        for invalid_role in ("", "OWNER", "unknown", None):
            before = await _tracked_counts(connection)
            transaction = connection.transaction()
            await transaction.start()
            try:
                scope = await _seed_transition_scope(connection, role=invalid_role)
                with pytest.raises((asyncpg.CheckViolationError, asyncpg.NotNullViolationError)):
                    await _insert_initial_transition(
                        connection,
                        scope=scope,
                        role=invalid_role,
                    )
            finally:
                await transaction.rollback()
            assert await _tracked_counts(connection) == before

        migration_role = await connection.fetchval("SELECT CURRENT_ROLE::text")
        app_role = make_url(app_database_url).username
        assert app_role is not None
        assert migration_role != app_role
        assert migration_role not in COLLABORATION_ROLES
        assert app_role not in COLLABORATION_ROLES
        await _assert_least_privilege_role(
            connection,
            role=migration_role,
            allow_createdb=True,
        )
        await _assert_least_privilege_role(
            connection,
            role=app_role,
            allow_createdb=False,
        )
        await _grant_app_transition_access(connection, app_role=app_role)

        migration_scope = await _seed_transition_scope(connection, role="viewer")
        app_scope = await _seed_transition_scope(connection, role="viewer")
        migration_result = await _insert_initial_transition(
            connection,
            scope=migration_scope,
            role="viewer",
        )
        app_connection = await _connect(app_database_url)
        try:
            assert await app_connection.fetchval("SELECT CURRENT_ROLE::text") == app_role
            app_result = await _insert_initial_transition(
                app_connection,
                scope=app_scope,
                role="viewer",
            )
        finally:
            await app_connection.close()
        assert app_result == migration_result
        assert app_result == (
            0,
            None,
            "active",
            None,
            "viewer",
            1,
            "current_role_constraint_test",
        )
        return backfill_timestamp
    finally:
        await connection.close()


async def _assert_0020(database_url: str) -> None:
    connection = await _connect(database_url)
    try:
        assert (
            await connection.fetchval("SELECT version_num FROM alembic_version") == "20260725_0020"
        )
        assert (
            await connection.fetchval(
                "SELECT to_regclass('public.workspace_membership_transitions')"
            )
            is None
        )
        assert (
            await connection.fetchval(
                """SELECT count(*) FROM trace_events
                   WHERE operation = 'backfill_owner_membership'"""
            )
            == 0
        )
    finally:
        await connection.close()


async def _public_table_counts(database_url: str) -> dict[str, int]:
    connection = await _connect(database_url)
    try:
        tables = await connection.fetch(
            """SELECT tablename
               FROM pg_tables
               WHERE schemaname = 'public'
               ORDER BY tablename"""
        )
        counts: dict[str, int] = {}
        for row in tables:
            table = str(row["tablename"])
            identifier = table.replace('"', '""')
            counts[table] = await connection.fetchval(f'SELECT count(*) FROM "{identifier}"')
        return counts
    finally:
        await connection.close()


async def _assert_failed_0021_upgrade_is_atomic(
    database_url: str,
    *,
    before_counts: dict[str, int],
) -> None:
    connection = await _connect(database_url)
    try:
        assert (
            await connection.fetchval("SELECT version_num FROM alembic_version") == "20260725_0020"
        )
        for table in MIGRATION_0021_TABLES:
            assert await connection.fetchval(f"SELECT to_regclass('public.{table}')") is None
        assert (
            await connection.fetchval(
                """SELECT count(*) FROM trace_events
                   WHERE operation = 'backfill_owner_membership'"""
            )
            == 0
        )
    finally:
        await connection.close()
    assert await _public_table_counts(database_url) == before_counts


async def _assert_reupgraded_0021(database_url: str) -> datetime:
    connection = await _connect(database_url)
    try:
        assert (
            await connection.fetchval("SELECT version_num FROM alembic_version") == "20260725_0021"
        )
        await _assert_database_constraint(connection)
        return await _assert_seeded_owner_backfills(connection)
    finally:
        await connection.close()


def test_postgresql_migration_0021_current_role_constraint_and_cycle(
    postgres_migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_orm_parity()
    config = _config(postgres_migration_database_url)
    app_database_url = _app_database_url(postgres_migration_database_url)

    command.upgrade(config, "20260725_0020")
    asyncio.run(_seed_0020_workspaces(postgres_migration_database_url))

    before_failure = asyncio.run(_public_table_counts(postgres_migration_database_url))
    real_uuid5 = uuid.uuid5

    def fail_after_partial_backfill(namespace: uuid.UUID, name: str) -> uuid.UUID:
        if name == "transition:0":
            raise RuntimeError("injected owner backfill failure")
        return real_uuid5(namespace, name)

    with monkeypatch.context() as scoped:
        scoped.setattr(uuid, "uuid5", fail_after_partial_backfill)
        with pytest.raises(RuntimeError, match="injected owner backfill failure"):
            command.upgrade(config, "20260725_0021")
    asyncio.run(
        _assert_failed_0021_upgrade_is_atomic(
            postgres_migration_database_url,
            before_counts=before_failure,
        )
    )

    command.upgrade(config, "20260725_0021")
    first_timestamp = asyncio.run(_assert_reupgraded_0021(postgres_migration_database_url))

    command.downgrade(config, "20260725_0020")
    asyncio.run(_assert_0020(postgres_migration_database_url))

    command.upgrade(config, "20260725_0021")
    second_timestamp = asyncio.run(_assert_reupgraded_0021(postgres_migration_database_url))
    assert second_timestamp > first_timestamp
    assert (
        asyncio.run(_exercise_0021(postgres_migration_database_url, app_database_url))
        == second_timestamp
    )
