from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres

APPEND_ONLY_TABLES = {
    "controlled_agent_executions": "id",
    "controlled_agent_execution_states": "state_id",
    "controlled_agent_context_snapshots": "snapshot_id",
    "controlled_agent_plan_snapshots": "plan_id",
    "controlled_agent_capability_grants": "grant_id",
    "controlled_agent_grant_revocations": "revocation_id",
    "controlled_agent_approvals": "approval_id",
    "controlled_agent_policy_decisions": "decision_id",
    "controlled_agent_approval_consumptions": "consumption_id",
    "controlled_agent_audit_events": "event_id",
}


@pytest.fixture(scope="session")
def postgres_agent_database_url() -> Iterator[str]:
    yield from disposable_postgres_database()


@pytest.mark.asyncio
async def test_postgres_enforces_all_controlled_agent_append_only_boundaries(
    postgres_agent_database_url: str,
) -> None:
    connection = await asyncpg.connect(
        postgres_agent_database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    try:
        identities = await _seed_all_tables(connection)
        triggers = await connection.fetch(
            """SELECT c.relname AS table_name, t.tgname AS trigger_name
               FROM pg_trigger t
               JOIN pg_class c ON c.oid = t.tgrelid
               WHERE NOT t.tgisinternal AND c.relname = ANY($1::text[])""",
            list(APPEND_ONLY_TABLES),
        )
        assert {row["table_name"] for row in triggers} == set(APPEND_ONLY_TABLES)
        assert len(triggers) == len(APPEND_ONLY_TABLES)

        for table, primary_key in APPEND_ONLY_TABLES.items():
            identifier = identities[table]
            await _assert_append_only_rejection(
                connection,
                f"UPDATE {table} SET schema_version = schema_version WHERE {primary_key} = $1",
                identifier,
            )
            await _assert_append_only_rejection(
                connection,
                f"DELETE FROM {table} WHERE {primary_key} = $1",
                identifier,
            )

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO controlled_agent_execution_states
                       (state_id, execution_id, user_id, workspace_id, schema_version,
                        status, recorded_at)
                       VALUES ($1, $2, $3, $4, 'controlled-agent-v1', 'proposed', $5)""",
                    uuid.uuid4(),
                    identities["controlled_agent_executions"],
                    uuid.uuid4(),
                    identities["workspace_id"],
                    datetime.now(UTC),
                )

        with pytest.raises(asyncpg.UniqueViolationError):
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO controlled_agent_approval_consumptions
                       (consumption_id, approval_id, policy_decision_id, execution_id,
                        user_id, workspace_id, schema_version, consumed_at)
                       VALUES ($1, $2, $3, $4, $5, $6, 'controlled-agent-v1', $7)""",
                    uuid.uuid4(),
                    identities["controlled_agent_approvals"],
                    identities["controlled_agent_policy_decisions"],
                    identities["controlled_agent_executions"],
                    identities["user_id"],
                    identities["workspace_id"],
                    datetime.now(UTC),
                )

        for table, primary_key in APPEND_ONLY_TABLES.items():
            assert (
                await connection.fetchval(
                    f"SELECT count(*) FROM {table} WHERE {primary_key} = $1",
                    identities[table],
                )
                == 1
            )
        assert (
            await connection.fetchval(
                "SELECT plan_digest FROM controlled_agent_executions WHERE id = $1",
                identities["controlled_agent_executions"],
            )
            == "b" * 64
        )
        assert (
            await connection.fetchval(
                "SELECT payload_digest FROM controlled_agent_plan_snapshots WHERE plan_id = $1",
                identities["controlled_agent_plan_snapshots"],
            )
            == "b" * 64
        )
    finally:
        await connection.close()


async def _assert_append_only_rejection(
    connection: asyncpg.Connection, statement: str, identifier: uuid.UUID
) -> None:
    with pytest.raises(asyncpg.RaiseError, match="controlled-agent records are append-only"):
        async with connection.transaction():
            await connection.execute(statement, identifier)


async def _seed_all_tables(connection: asyncpg.Connection) -> dict[str, uuid.UUID]:
    now = datetime.now(UTC)
    user_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    workspace_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    context_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    grant_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    identities = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "controlled_agent_executions": execution_id,
        "controlled_agent_execution_states": uuid.uuid4(),
        "controlled_agent_context_snapshots": context_id,
        "controlled_agent_plan_snapshots": plan_id,
        "controlled_agent_capability_grants": grant_id,
        "controlled_agent_grant_revocations": uuid.uuid4(),
        "controlled_agent_approvals": approval_id,
        "controlled_agent_policy_decisions": decision_id,
        "controlled_agent_approval_consumptions": uuid.uuid4(),
        "controlled_agent_audit_events": uuid.uuid4(),
    }
    await connection.execute(
        "INSERT INTO workspaces (id, name, owner_id) VALUES ($1, 'PostgreSQL trigger test', $2)",
        workspace_id,
        user_id,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_executions
           (id, user_id, workspace_id, schema_version, role, context_snapshot_id,
            context_digest, plan_id, plan_digest, grant_id, created_at)
           VALUES ($1, $2, $3, 'controlled-agent-v1', 'evidence_verifier',
                   $4, $5, $6, $7, $8, $9)""",
        execution_id,
        user_id,
        workspace_id,
        context_id,
        "a" * 64,
        plan_id,
        "b" * 64,
        grant_id,
        now,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_execution_states
           (state_id, execution_id, user_id, workspace_id, schema_version, status, recorded_at)
           VALUES ($1, $2, $3, $4, 'controlled-agent-v1', 'proposed', $5)""",
        identities["controlled_agent_execution_states"],
        execution_id,
        user_id,
        workspace_id,
        now,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_context_snapshots
           (snapshot_id, execution_id, user_id, workspace_id, schema_version,
            payload_digest, payload, captured_at)
           VALUES ($1, $2, $3, $4, 'controlled-agent-v1', $5, '{}'::json, $6)""",
        context_id,
        execution_id,
        user_id,
        workspace_id,
        "a" * 64,
        now,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_plan_snapshots
           (plan_id, execution_id, user_id, workspace_id, schema_version,
            payload_digest, payload, created_at)
           VALUES ($1, $2, $3, $4, 'controlled-agent-v1', $5, '{}'::json, $6)""",
        plan_id,
        execution_id,
        user_id,
        workspace_id,
        "b" * 64,
        now,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_capability_grants
           (grant_id, execution_id, user_id, workspace_id, schema_version, policy_version,
            role, context_digest, plan_digest, payload_digest, payload, issued_at, expires_at,
            approval_required, approval_id)
           VALUES ($1, $2, $3, $4, 'controlled-agent-v1', 'policy-v1', 'evidence_verifier',
                   $5, $6, $7, '{}'::json, $8, $9, true, $10)""",
        grant_id,
        execution_id,
        user_id,
        workspace_id,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        now,
        now + timedelta(minutes=10),
        approval_id,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_grant_revocations
           (revocation_id, grant_id, execution_id, user_id, workspace_id,
            schema_version, revoked_at, reason_code, payload)
           VALUES ($1, $2, $3, $4, $5, 'controlled-agent-v1', $6, 'test_revocation', '{}'::json)""",
        identities["controlled_agent_grant_revocations"],
        grant_id,
        execution_id,
        user_id,
        workspace_id,
        now,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_approvals
           (approval_id, grant_id, execution_id, user_id, workspace_id, schema_version,
            policy_version, decision, context_digest, plan_digest, payload_digest, payload,
            decided_at, expires_at)
           VALUES ($1, $2, $3, $4, $5, 'controlled-agent-v1', 'policy-v1', 'approved',
                   $6, $7, $8, '{}'::json, $9, $10)""",
        approval_id,
        grant_id,
        execution_id,
        user_id,
        workspace_id,
        "a" * 64,
        "b" * 64,
        "d" * 64,
        now,
        now + timedelta(minutes=5),
    )
    await connection.execute(
        """INSERT INTO controlled_agent_policy_decisions
           (decision_id, execution_id, user_id, workspace_id, schema_version, policy_version,
            outcome, reason_code, evaluated_at, grant_id, approval_id, context_digest, plan_digest)
           VALUES ($1, $2, $3, $4, 'controlled-agent-v1', 'policy-v1', 'allow',
                   'approval_valid', $5, $6, $7, $8, $9)""",
        decision_id,
        execution_id,
        user_id,
        workspace_id,
        now,
        grant_id,
        approval_id,
        "a" * 64,
        "b" * 64,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_approval_consumptions
           (consumption_id, approval_id, policy_decision_id, execution_id,
            user_id, workspace_id, schema_version, consumed_at)
           VALUES ($1, $2, $3, $4, $5, $6, 'controlled-agent-v1', $7)""",
        identities["controlled_agent_approval_consumptions"],
        approval_id,
        decision_id,
        execution_id,
        user_id,
        workspace_id,
        now,
    )
    await connection.execute(
        """INSERT INTO controlled_agent_audit_events
           (event_id, trace_id, execution_id, user_id, workspace_id, schema_version,
            event_type, recorded_at, attributes)
           VALUES ($1, $2, $3, $4, $5, 'controlled-agent-v1',
                   'postgres.trigger.test', $6, '[]'::json)""",
        identities["controlled_agent_audit_events"],
        uuid.uuid4(),
        execution_id,
        user_id,
        workspace_id,
        now,
    )
    return identities
