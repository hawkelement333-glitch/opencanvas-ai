from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    ControlledAgentAuditEvent,
    ControlledAgentExecution,
    ControlledAgentExecutionState,
    TraceEvent,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import (
    ExecutionStateRecord,
    ExecutionStatus,
    RevocationRecord,
)
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
from opencanvas_api.services.agents.reliability import (
    EXECUTION_LEASE_DURATION,
    ControlledExecutionReliability,
    ExecutionReliabilityDenied,
    RetryActionError,
    RetryFailureClassification,
    retry_delay,
)
from opencanvas_api.services.trace import RecordTraceEventInput, TraceService
from tests.agent_fixtures import NOW, AgentBundle, make_agent_bundle


async def _ready_bundle(database: Database) -> AgentBundle:
    bundle = make_agent_bundle()
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        await repository.append_bundle(
            execution=bundle.execution,
            context=bundle.context,
            plan=bundle.plan,
            grant=bundle.grant,
            approval=bundle.approval,
        )
        await repository.append_state(_state(bundle, ExecutionStatus.PROPOSED, 0))
        await repository.append_state(_state(bundle, ExecutionStatus.READY, 1))
        await session.commit()
    return bundle


def _state(
    bundle: AgentBundle,
    status: ExecutionStatus,
    second: int,
    *,
    reason: str | None = None,
) -> ExecutionStateRecord:
    return ExecutionStateRecord(
        state_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        status=status,
        recorded_at=NOW + timedelta(seconds=second),
        safe_reason_code=reason,
    )


async def _execution(database: Database, bundle: AgentBundle) -> ControlledAgentExecution:
    async with database.sessions() as session:
        row = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert row is not None
        return row


async def test_execution_reliability_defaults_are_deterministic(database: Database) -> None:
    bundle = await _ready_bundle(database)
    execution = await _execution(database, bundle)
    assert execution.deadline_at.replace(tzinfo=NOW.tzinfo) == (
        bundle.execution.created_at + timedelta(minutes=15)
    )
    assert (execution.max_attempts, execution.attempt_count, execution.lease_generation) == (
        3,
        0,
        0,
    )
    assert execution.next_retry_at is None
    assert execution.lease_owner_id is None
    assert execution.completed_at is None
    assert execution.terminal_outcome is None


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"max_attempts": 0}, "ck_agent_execution_max_attempts_positive"),
        ({"attempt_count": 4}, "ck_agent_execution_attempt_count_bounded"),
        (
            {"deadline_at": NOW - timedelta(seconds=1)},
            "ck_agent_execution_deadline_after_creation",
        ),
        (
            {"next_retry_at": NOW + timedelta(minutes=16)},
            "ck_agent_execution_retry_before_deadline",
        ),
        (
            {"lease_owner_id": "worker-only"},
            "ck_agent_execution_lease_shape",
        ),
        (
            {"completed_at": NOW + timedelta(seconds=2)},
            "ck_agent_execution_terminal_shape",
        ),
    ],
)
async def test_execution_reliability_constraints_reject_invalid_shapes(
    database: Database,
    values: dict[str, object],
    constraint: str,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        with pytest.raises(IntegrityError, match=constraint):
            await session.execute(
                update(ControlledAgentExecution)
                .where(ControlledAgentExecution.id == bundle.execution.execution_id)
                .values(**values)
            )


async def test_eligible_claim_is_atomic_and_records_audit_and_trace(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    claimed_at = NOW + timedelta(minutes=1)
    async with database.sessions() as session:
        lease = await ControlledExecutionReliability(session).claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=claimed_at,
        )
        await session.commit()
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id == lease.owner_id
        assert execution.lease_acquired_at is not None
        assert execution.lease_acquired_at.replace(tzinfo=NOW.tzinfo) == claimed_at
        assert execution.lease_expires_at is not None
        assert execution.lease_expires_at.replace(tzinfo=NOW.tzinfo) == (
            claimed_at + EXECUTION_LEASE_DURATION
        )
        assert (execution.attempt_count, execution.lease_generation) == (1, 1)
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.lease_claimed")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(TraceEvent.event_type == "execution.lease_claimed")
            )
            == 1
        )
        current = await ControlledAgentRepository(session).current_state(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
        )
        assert current is not None and current.status == ExecutionStatus.RUNNING.value


async def test_active_lease_blocks_duplicate_and_conflicting_claims(database: Database) -> None:
    bundle = await _ready_bundle(database)
    claimed_at = NOW + timedelta(minutes=1)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=claimed_at,
        )
        with pytest.raises(ExecutionReliabilityDenied, match="execution_not_claimable"):
            await service.claim(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                claimed_at=claimed_at + timedelta(seconds=1),
            )
        await session.commit()
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id == lease.owner_id
        assert execution.attempt_count == 1


async def test_expired_lease_does_not_block_ready_execution_claim(database: Database) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        await session.execute(
            update(ControlledAgentExecution)
            .where(ControlledAgentExecution.id == bundle.execution.execution_id)
            .values(
                lease_owner_id="expired-owner",
                lease_acquired_at=NOW + timedelta(seconds=2),
                lease_expires_at=NOW + timedelta(seconds=3),
                lease_generation=4,
                attempt_count=1,
            )
        )
        await session.commit()
    async with database.sessions() as session:
        lease = await ControlledExecutionReliability(session).claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(seconds=4),
        )
        await session.commit()
        assert lease.generation == 5
        assert lease.attempt_count == 2
        assert lease.owner_id != "expired-owner"


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ({"deadline_at": NOW + timedelta(seconds=2)}, "execution_deadline_expired"),
        ({"attempt_count": 3}, "execution_attempts_exhausted"),
        ({"next_retry_at": NOW + timedelta(minutes=2)}, "execution_retry_not_eligible"),
    ],
)
async def test_claim_fails_closed_for_deadline_attempt_and_retry_limits(
    database: Database,
    values: dict[str, object],
    reason: str,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        await session.execute(
            update(ControlledAgentExecution)
            .where(ControlledAgentExecution.id == bundle.execution.execution_id)
            .values(**values)
        )
        await session.commit()
    async with database.sessions() as session:
        with pytest.raises(ExecutionReliabilityDenied, match=reason):
            await ControlledExecutionReliability(session).claim(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                claimed_at=NOW + timedelta(minutes=1),
            )
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id is None
        assert execution.attempt_count == values.get("attempt_count", 0)


async def test_revoked_authority_blocks_claim_without_partial_state(database: Database) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        await ControlledAgentRepository(session).append_revocation(
            RevocationRecord(
                revocation_id=uuid.uuid4(),
                subject_kind="grant",
                subject_id=bundle.grant.grant_id,
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                revoked_at=NOW + timedelta(seconds=10),
                reason_code="owner_revoked",
            )
        )
        await session.commit()
    async with database.sessions() as session:
        with pytest.raises(ExecutionReliabilityDenied, match="grant_revoked"):
            await ControlledExecutionReliability(session).claim(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                claimed_at=NOW + timedelta(minutes=1),
            )
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id is None and execution.attempt_count == 0


@pytest.mark.parametrize(
    ("claimed_at", "updates", "reason"),
    [
        (NOW + timedelta(minutes=11), {}, "grant_inactive"),
        (NOW + timedelta(minutes=1), {"user_id": uuid.uuid4()}, "authority_not_found"),
        (NOW + timedelta(minutes=1), {"workspace_id": uuid.uuid4()}, "authority_not_found"),
    ],
)
async def test_expired_and_cross_scope_authority_fail_closed(
    database: Database,
    claimed_at: datetime,
    updates: dict[str, uuid.UUID],
    reason: str,
) -> None:
    bundle = await _ready_bundle(database)
    with pytest.raises(ExecutionReliabilityDenied, match=reason):
        async with database.sessions() as session:
            await ControlledExecutionReliability(session).claim(
                user_id=updates.get("user_id", bundle.execution.user_id),
                workspace_id=updates.get("workspace_id", bundle.execution.workspace_id),
                execution_id=bundle.execution.execution_id,
                claimed_at=claimed_at,
            )
    execution = await _execution(database, bundle)
    assert execution.lease_owner_id is None and execution.attempt_count == 0


async def test_terminal_execution_cannot_be_claimed(database: Database) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        await ControlledAgentRepository(session).append_state(
            _state(bundle, ExecutionStatus.CANCELLED, 2, reason="owner_cancelled")
        )
        await session.commit()
    async with database.sessions() as session:
        with pytest.raises(ExecutionReliabilityDenied, match="execution_not_claimable"):
            await ControlledExecutionReliability(session).claim(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                claimed_at=NOW + timedelta(minutes=1),
            )
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.completed_at is not None
        assert execution.terminal_outcome == ExecutionStatus.CANCELLED.value
        assert execution.failure_classification == "owner_cancelled"


async def test_current_owner_can_renew_and_release_without_erasing_attempt(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(minutes=1),
        )
        renewal = await service.renew(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            owner_id=lease.owner_id,
            generation=lease.generation,
            renewed_at=NOW + timedelta(minutes=1, seconds=30),
        )
        assert renewal.expires_at == NOW + timedelta(minutes=2, seconds=30)
        release = await service.release(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            owner_id=lease.owner_id,
            generation=lease.generation,
            released_at=NOW + timedelta(minutes=1, seconds=31),
        )
        await session.commit()
        assert release.attempt_count == 1
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id is None
        assert execution.attempt_count == 1
        assert execution.lease_generation == 1


async def test_renewal_is_capped_by_execution_deadline(database: Database) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        await session.execute(
            update(ControlledAgentExecution)
            .where(ControlledAgentExecution.id == bundle.execution.execution_id)
            .values(deadline_at=NOW + timedelta(minutes=2))
        )
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(seconds=30),
        )
        renewal = await service.renew(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            owner_id=lease.owner_id,
            generation=lease.generation,
            renewed_at=NOW + timedelta(minutes=1, seconds=29),
        )
        assert renewal.expires_at == NOW + timedelta(minutes=2)


async def test_terminal_transition_clears_lease_and_blocks_renewal_and_release(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(minutes=1),
        )
        await ControlledAgentRepository(session).append_state(
            _state(bundle, ExecutionStatus.SUCCEEDED, 62)
        )
        with pytest.raises(ExecutionReliabilityDenied, match="execution_not_running"):
            await service.renew(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                owner_id=lease.owner_id,
                generation=lease.generation,
                renewed_at=NOW + timedelta(minutes=1, seconds=3),
            )
        with pytest.raises(ExecutionReliabilityDenied, match="execution_not_running"):
            await service.release(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                owner_id=lease.owner_id,
                generation=lease.generation,
                released_at=NOW + timedelta(minutes=1, seconds=3),
            )
        await session.commit()
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id is None
        assert execution.terminal_outcome == ExecutionStatus.SUCCEEDED.value
        assert execution.attempt_count == 1


async def test_revoked_authority_blocks_renewal_without_changing_lease(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(minutes=1),
        )
        await ControlledAgentRepository(session).append_revocation(
            RevocationRecord(
                revocation_id=uuid.uuid4(),
                subject_kind="grant",
                subject_id=bundle.grant.grant_id,
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                revoked_at=NOW + timedelta(minutes=1, seconds=5),
                reason_code="owner_revoked",
            )
        )
        with pytest.raises(ExecutionReliabilityDenied, match="grant_revoked"):
            await service.renew(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                owner_id=lease.owner_id,
                generation=lease.generation,
                renewed_at=NOW + timedelta(minutes=1, seconds=10),
            )
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_expires_at is not None
        assert execution.lease_expires_at.replace(tzinfo=NOW.tzinfo) == lease.expires_at
        assert execution.attempt_count == 1


@pytest.mark.parametrize(
    ("owner_delta", "generation_delta", "seconds", "reason"),
    [
        ("other", 0, 10, "lease_not_current"),
        ("", 1, 10, "lease_not_current"),
        ("", 0, 61, "lease_not_current"),
    ],
)
async def test_stale_unrelated_and_expired_leases_cannot_renew_or_release(
    database: Database,
    owner_delta: str,
    generation_delta: int,
    seconds: int,
    reason: str,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(minutes=1),
        )
        owner = owner_delta or lease.owner_id
        with pytest.raises(ExecutionReliabilityDenied, match=reason):
            await service.renew(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                owner_id=owner,
                generation=lease.generation + generation_delta,
                renewed_at=NOW + timedelta(minutes=1, seconds=seconds),
            )
        with pytest.raises(ExecutionReliabilityDenied, match=reason):
            await service.release(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                owner_id=owner,
                generation=lease.generation + generation_delta,
                released_at=NOW + timedelta(minutes=1, seconds=seconds),
            )


class _FailingTraceService(TraceService):
    async def record_event(self, input_data: RecordTraceEventInput) -> TraceEvent:
        raise RuntimeError("injected trace failure")


async def test_claim_trace_failure_rolls_back_lease_attempt_audit_and_transition(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(
            session,
            trace_service=_FailingTraceService(session),
        )
        with pytest.raises(RuntimeError, match="injected trace failure"):
            await service.claim(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                claimed_at=NOW + timedelta(minutes=1),
            )
        await session.commit()
    async with database.sessions() as session:
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id is None and execution.attempt_count == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.lease_claimed")
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(TraceEvent.event_type == "execution.lease_claimed")
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentExecutionState)
                .where(
                    ControlledAgentExecutionState.execution_id == bundle.execution.execution_id,
                    ControlledAgentExecutionState.status == ExecutionStatus.RUNNING.value,
                )
            )
            == 0
        )


async def _file_database(path: Path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="reliability@mobius.invalid",
                email_normalized="reliability@mobius.invalid",
                password_hash="test-only",
                display_name="Reliability test",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=SYSTEM_WORKSPACE_ID,
                owner_id=SYSTEM_USER_ID,
                name="Reliability workspace",
            )
        )
        await session.commit()
    return database


async def test_competing_sqlite_claims_produce_one_owner(tmp_path: Path) -> None:
    database = await _file_database(tmp_path / "claim-race.db")
    try:
        bundle = await _ready_bundle(database)

        async def claim() -> str:
            async with database.sessions() as session:
                try:
                    lease = await ControlledExecutionReliability(session).claim(
                        user_id=bundle.execution.user_id,
                        workspace_id=bundle.execution.workspace_id,
                        execution_id=bundle.execution.execution_id,
                        claimed_at=NOW + timedelta(minutes=1),
                    )
                    await session.commit()
                    return lease.owner_id
                except ExecutionReliabilityDenied as exc:
                    await session.rollback()
                    return exc.reason_code

        outcomes = await asyncio.gather(claim(), claim())
        denials = {"execution_not_claimable", "execution_claim_conflict"}
        owners = [value for value in outcomes if value not in denials]
        assert len(owners) == 1
        assert sum(value in denials for value in outcomes) == 1
        execution = await _execution(database, bundle)
        assert execution.lease_owner_id == owners[0]
        assert execution.attempt_count == 1
    finally:
        await database.dispose()


def test_retry_delay_is_deterministic_and_bounded() -> None:
    assert [retry_delay(attempt) for attempt in range(1, 7)] == [
        timedelta(seconds=5),
        timedelta(seconds=10),
        timedelta(seconds=20),
        timedelta(seconds=40),
        timedelta(minutes=1),
        timedelta(minutes=1),
    ]


async def test_expired_lease_recovery_fences_owner_and_records_retry(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    claimed_at = NOW + timedelta(minutes=1)
    recovered_at = claimed_at + EXECUTION_LEASE_DURATION
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=claimed_at,
        )
        recovery = await service.recover_expired_lease(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            expected_generation=lease.generation,
            recovered_at=recovered_at,
        )
        assert recovery.superseded_generation == lease.generation
        assert recovery.generation == lease.generation + 1
        assert recovery.next_retry_at == recovered_at + retry_delay(lease.attempt_count)
        with pytest.raises(ExecutionReliabilityDenied, match="execution_not_running"):
            await service.renew(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                owner_id=lease.owner_id,
                generation=lease.generation,
                renewed_at=recovered_at,
            )
        await session.commit()

    async with database.sessions() as session:
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id is None
        assert execution.attempt_count == 1
        assert execution.lease_generation == 2
        assert execution.next_retry_at is not None
        assert execution.next_retry_at.replace(tzinfo=NOW.tzinfo) == recovery.next_retry_at
        current = await ControlledAgentRepository(session).current_state(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
        )
        assert current is not None and current.status == ExecutionStatus.READY.value
        assert current.safe_reason_code == "lease_expired"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.lease_recovered")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(TraceEvent.event_type == "execution.lease_recovered")
            )
            == 1
        )


@pytest.mark.parametrize(
    ("seconds", "generation_delta", "reason"),
    [
        (30, 0, "execution_lease_active"),
        (60, 1, "execution_recovery_conflict"),
    ],
)
async def test_recovery_rejects_active_or_stale_lease_without_partial_state(
    database: Database,
    seconds: int,
    generation_delta: int,
    reason: str,
) -> None:
    bundle = await _ready_bundle(database)
    claimed_at = NOW + timedelta(minutes=1)
    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        lease = await service.claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=claimed_at,
        )
        with pytest.raises(ExecutionReliabilityDenied, match=reason):
            await service.recover_expired_lease(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                expected_generation=lease.generation + generation_delta,
                recovered_at=claimed_at + timedelta(seconds=seconds),
            )
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.lease_owner_id == lease.owner_id
        assert execution.lease_generation == lease.generation
        assert execution.next_retry_at is None


async def test_retryable_failure_rolls_back_action_and_schedules_retry(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    attempted_at = NOW + timedelta(minutes=1)
    async with database.sessions() as session:
        workspace = await session.get(Workspace, bundle.execution.workspace_id)
        assert workspace is not None
        owned_workspace: Workspace = workspace
        original_name = owned_workspace.name

        async def fail_after_mutation(_: object) -> None:
            owned_workspace.name = "must roll back"
            await session.flush()
            raise RetryActionError(RetryFailureClassification.PROVIDER_TIMEOUT)

        result = await ControlledExecutionReliability(session).execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=attempted_at,
            action=fail_after_mutation,
        )
        await session.commit()
        assert result.status is ExecutionStatus.READY
        assert result.failure_classification == "provider_timeout"
        assert result.next_retry_at == attempted_at + timedelta(seconds=5)

    async with database.sessions() as session:
        workspace = await session.get(Workspace, bundle.execution.workspace_id)
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert workspace is not None and workspace.name == original_name
        assert execution is not None
        assert execution.attempt_count == 1
        assert execution.lease_owner_id is None
        assert execution.lease_generation == 2
        assert execution.next_retry_at is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.retry_scheduled")
            )
            == 1
        )


async def test_retry_succeeds_once_and_duplicate_delivery_does_not_rerun(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    calls = 0

    async def succeed(_: object) -> None:
        nonlocal calls
        calls += 1

    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        result = await service.execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=NOW + timedelta(minutes=1),
            action=succeed,
        )
        duplicate = await service.execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=NOW + timedelta(minutes=1, seconds=1),
            action=succeed,
        )
        await session.commit()
        assert result.status is ExecutionStatus.SUCCEEDED and not result.duplicate
        assert duplicate.status is ExecutionStatus.SUCCEEDED and duplicate.duplicate
        assert calls == 1
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.attempt_count == 1
        assert execution.terminal_outcome == ExecutionStatus.SUCCEEDED.value
        assert execution.lease_owner_id is None


async def test_bounded_retry_succeeds_on_next_eligible_attempt(database: Database) -> None:
    bundle = await _ready_bundle(database)
    calls = 0

    async def transient_then_success(_: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryActionError(RetryFailureClassification.PROVIDER_UNAVAILABLE)

    async with database.sessions() as session:
        service = ControlledExecutionReliability(session)
        first = await service.execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=NOW + timedelta(minutes=1),
            action=transient_then_success,
        )
        assert first.next_retry_at is not None
        with pytest.raises(ExecutionReliabilityDenied, match="execution_retry_not_eligible"):
            await service.execute_retry(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                attempted_at=first.next_retry_at - timedelta(microseconds=1),
                action=transient_then_success,
            )
        second = await service.execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=first.next_retry_at,
            action=transient_then_success,
        )
        await session.commit()
        assert second.status is ExecutionStatus.SUCCEEDED
        assert second.attempt_count == 2
        assert calls == 2


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (RetryFailureClassification.ACTION_CONFLICT, "action_conflict"),
        (RetryFailureClassification.UNSUPPORTED_ACTION, "unsupported_action"),
    ],
)
async def test_terminal_failure_classes_fail_closed_without_retry(
    database: Database,
    failure: RetryFailureClassification,
    expected: str,
) -> None:
    bundle = await _ready_bundle(database)

    async def fail(_: object) -> None:
        raise RetryActionError(failure)

    async with database.sessions() as session:
        result = await ControlledExecutionReliability(session).execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=NOW + timedelta(minutes=1),
            action=fail,
        )
        await session.commit()
        assert result.status is ExecutionStatus.FAILED
        assert result.failure_classification == expected
        assert result.next_retry_at is None


async def test_attempt_exhaustion_creates_one_terminal_failure_event(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        await session.execute(
            update(ControlledAgentExecution)
            .where(ControlledAgentExecution.id == bundle.execution.execution_id)
            .values(max_attempts=1)
        )

        async def fail(_: object) -> None:
            raise RetryActionError(RetryFailureClassification.PROVIDER_TIMEOUT)

        result = await ControlledExecutionReliability(session).execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=NOW + timedelta(minutes=1),
            action=fail,
        )
        await session.commit()
        assert result.status is ExecutionStatus.FAILED
        assert result.failure_classification == "execution_attempts_exhausted"
        assert result.attempt_count == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.retry_failed")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(TraceEvent.event_type == "execution.retry_failed")
            )
            == 1
        )


async def test_unknown_action_failure_is_terminal_and_safe(database: Database) -> None:
    bundle = await _ready_bundle(database)

    async def fail(_: object) -> None:
        raise RuntimeError("private provider and database detail")

    async with database.sessions() as session:
        result = await ControlledExecutionReliability(session).execute_retry(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            attempted_at=NOW + timedelta(minutes=1),
            action=fail,
        )
        await session.commit()
        assert result.failure_classification == "action_invalid"
        assert "private" not in result.failure_classification


async def test_retry_trace_failure_rolls_back_action_claim_and_terminal_state(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)
    async with database.sessions() as session:
        workspace = await session.get(Workspace, bundle.execution.workspace_id)
        assert workspace is not None
        owned_workspace: Workspace = workspace
        original_name = owned_workspace.name

        async def mutate(_: object) -> None:
            owned_workspace.name = "must roll back with trace"
            await session.flush()

        service = ControlledExecutionReliability(
            session,
            trace_service=_FailingTraceService(session),
        )
        with pytest.raises(RuntimeError, match="injected trace failure"):
            await service.execute_retry(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                attempted_at=NOW + timedelta(minutes=1),
                action=mutate,
            )
        await session.commit()

    async with database.sessions() as session:
        workspace = await session.get(Workspace, bundle.execution.workspace_id)
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert workspace is not None and workspace.name == original_name
        assert execution is not None
        assert execution.attempt_count == 0
        assert execution.completed_at is None
        assert execution.lease_owner_id is None
        current = await ControlledAgentRepository(session).current_state(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
        )
        assert current is not None and current.status == ExecutionStatus.READY.value


async def test_retry_schedule_trace_failure_rolls_back_claim_and_schedule(
    database: Database,
) -> None:
    bundle = await _ready_bundle(database)

    async def transient(_: object) -> None:
        raise RetryActionError(RetryFailureClassification.PROVIDER_TIMEOUT)

    async with database.sessions() as session:
        service = ControlledExecutionReliability(
            session,
            trace_service=_FailingTraceService(session),
        )
        with pytest.raises(RuntimeError, match="injected trace failure"):
            await service.execute_retry(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                attempted_at=NOW + timedelta(minutes=1),
                action=transient,
            )
        await session.commit()

    async with database.sessions() as session:
        execution = await session.get(ControlledAgentExecution, bundle.execution.execution_id)
        assert execution is not None
        assert execution.attempt_count == 0
        assert execution.lease_generation == 0
        assert execution.next_retry_at is None
        assert execution.lease_owner_id is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.retry_scheduled")
            )
            == 0
        )


async def test_recovery_trace_failure_restores_expired_owner(database: Database) -> None:
    bundle = await _ready_bundle(database)
    claimed_at = NOW + timedelta(minutes=1)
    async with database.sessions() as session:
        lease = await ControlledExecutionReliability(session).claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=claimed_at,
        )
        await session.commit()

    async with database.sessions() as session:
        service = ControlledExecutionReliability(
            session,
            trace_service=_FailingTraceService(session),
        )
        with pytest.raises(RuntimeError, match="injected trace failure"):
            await service.recover_expired_lease(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
                expected_generation=lease.generation,
                recovered_at=lease.expires_at,
            )
        await session.commit()

    execution = await _execution(database, bundle)
    assert execution.lease_owner_id == lease.owner_id
    assert execution.lease_generation == lease.generation
    assert execution.next_retry_at is None


async def test_competing_retry_deliveries_execute_action_once(tmp_path: Path) -> None:
    database = await _file_database(tmp_path / "retry-race.db")
    try:
        bundle = await _ready_bundle(database)
        calls = 0

        async def run_retry() -> str:
            nonlocal calls
            async with database.sessions() as session:

                async def action(_: object) -> None:
                    nonlocal calls
                    calls += 1
                    await asyncio.sleep(0.05)

                try:
                    result = await ControlledExecutionReliability(session).execute_retry(
                        user_id=bundle.execution.user_id,
                        workspace_id=bundle.execution.workspace_id,
                        execution_id=bundle.execution.execution_id,
                        attempted_at=NOW + timedelta(minutes=1),
                        action=action,
                    )
                    await session.commit()
                    return "duplicate" if result.duplicate else result.status.value
                except ExecutionReliabilityDenied as exc:
                    await session.rollback()
                    return exc.reason_code

        outcomes = await asyncio.gather(run_retry(), run_retry())
        assert "succeeded" in outcomes
        assert set(outcomes) <= {
            "succeeded",
            "duplicate",
            "execution_claim_conflict",
            "execution_not_claimable",
        }
        assert calls == 1
        execution = await _execution(database, bundle)
        assert execution.attempt_count == 1
        assert execution.terminal_outcome == ExecutionStatus.SUCCEEDED.value
    finally:
        await database.dispose()
