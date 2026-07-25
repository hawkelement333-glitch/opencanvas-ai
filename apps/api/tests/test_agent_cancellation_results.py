from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    ControlledAgentAuditEvent,
    ControlledAgentExecutionState,
    ControlledAgentStateTransition,
    TraceEvent,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import (
    ExecutionStateRecord,
    ExecutionStatus,
    RevocationRecord,
)
from opencanvas_api.services.agents.execution import (
    AuthorityPreflightDenied,
    CancellationRequest,
    ControlledExecutionLifecycle,
    ExecutionAuthorityPreflight,
    ImmutableSelectedContextResolver,
    ResolvedSelectedContext,
    ResultAcceptanceRequest,
)
from opencanvas_api.services.agents.persistence import (
    AgentPersistenceNotFound,
    ControlledAgentRepository,
)
from opencanvas_api.services.agents.reliability import ControlledExecutionReliability
from tests.agent_fixtures import NOW, AgentBundle
from tests.test_agent_authority_preflight import request_for
from tests.test_agent_immutable_context import _seed_selected_context


@dataclass(frozen=True, slots=True)
class _RunningAttempt:
    state_id: uuid.UUID
    lease_owner_id: str
    lease_generation: int


async def _prepare_running(
    database: Database,
) -> tuple[AgentBundle, object, ResolvedSelectedContext, _RunningAttempt]:
    bundle, candidate, _, _, _ = await _seed_selected_context(database)
    async with database.sessions() as session:
        authorized = await ExecutionAuthorityPreflight(session).authorize(
            authenticated_user_id=bundle.execution.user_id,
            request=request_for(bundle, candidate.canvas_id),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        resolved = await ImmutableSelectedContextResolver(session).resolve(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
        )
        repository = ControlledAgentRepository(session)
        for second, status in (
            (1, ExecutionStatus.PROPOSED),
            (2, ExecutionStatus.READY),
        ):
            await repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=bundle.execution.execution_id,
                    user_id=bundle.execution.user_id,
                    workspace_id=bundle.execution.workspace_id,
                    status=status,
                    recorded_at=NOW + timedelta(seconds=second),
                )
            )
        lease = await ControlledExecutionReliability(session).claim(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            claimed_at=NOW + timedelta(seconds=3),
        )
        current = await repository.current_state(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
        )
        assert current is not None
        await session.commit()
    return (
        bundle,
        authorized,
        resolved,
        _RunningAttempt(
            state_id=current.state_id,
            lease_owner_id=lease.owner_id,
            lease_generation=lease.generation,
        ),
    )


def _result_request(
    bundle: AgentBundle,
    resolved: ResolvedSelectedContext,
    running: _RunningAttempt,
    *,
    delivery_id: uuid.UUID | None = None,
    running_state_id: uuid.UUID | None = None,
) -> ResultAcceptanceRequest:
    return ResultAcceptanceRequest(
        delivery_id=delivery_id or uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        running_state_id=running_state_id or running.state_id,
        context_snapshot_id=resolved.snapshot_id,
        context_digest=resolved.context_digest,
        resolution_digest=resolved.resolution_digest,
        result_digest="9" * 64,
        produced_at=NOW + timedelta(seconds=4),
        lease_owner_id=running.lease_owner_id,
        lease_generation=running.lease_generation,
    )


async def test_cancellation_before_start_is_authoritative_and_idempotent(
    database: Database,
) -> None:
    bundle, _, _, _, _ = await _seed_selected_context(database)
    cancellation = CancellationRequest(
        cancellation_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        requested_at=NOW,
    )
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        first = await lifecycle.cancel(
            authenticated_user_id=bundle.execution.user_id,
            request=cancellation,
            trace_id=uuid.uuid4(),
        )
        duplicate = await lifecycle.cancel(
            authenticated_user_id=bundle.execution.user_id,
            request=cancellation,
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert first.cancelled is True and first.duplicate is False
        assert duplicate.cancelled is True and duplicate.duplicate is True
        states = tuple(
            (
                await session.scalars(
                    select(ControlledAgentExecutionState)
                    .join(
                        ControlledAgentStateTransition,
                        ControlledAgentStateTransition.state_id
                        == ControlledAgentExecutionState.state_id,
                    )
                    .where(
                        ControlledAgentExecutionState.execution_id == bundle.execution.execution_id
                    )
                    .order_by(ControlledAgentStateTransition.sequence)
                )
            ).all()
        )
        assert [row.status for row in states] == ["proposed", "cancelled"]
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentAuditEvent)) == 1
        )


async def test_cancellation_cross_user_and_workspace_scope_fail_closed(
    database: Database,
) -> None:
    bundle, _, _, _, _ = await _seed_selected_context(database)
    request = CancellationRequest(
        cancellation_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        requested_at=NOW,
    )
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        with pytest.raises(AuthorityPreflightDenied, match="user_scope_mismatch"):
            await lifecycle.cancel(
                authenticated_user_id=uuid.uuid4(),
                request=request,
                trace_id=uuid.uuid4(),
            )
        with pytest.raises(AgentPersistenceNotFound):
            await lifecycle.cancel(
                authenticated_user_id=bundle.execution.user_id,
                request=request.model_copy(update={"workspace_id": uuid.uuid4()}),
                trace_id=uuid.uuid4(),
            )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentAuditEvent)) == 0
        )


async def test_start_cancel_result_rejects_late_result_without_reopening(
    database: Database,
) -> None:
    bundle, authorized, resolved, running = await _prepare_running(database)
    cancellation = CancellationRequest(
        cancellation_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        requested_at=NOW + timedelta(seconds=4),
    )
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        cancelled = await lifecycle.cancel(
            authenticated_user_id=bundle.execution.user_id,
            request=cancellation,
            trace_id=uuid.uuid4(),
        )
        rejected = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=_result_request(bundle, resolved, running),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert cancelled.status is ExecutionStatus.CANCELLED
        assert rejected.accepted is False
        assert rejected.reason_code == "stale_execution_state"
        assert rejected.status is ExecutionStatus.CANCELLED


async def test_start_result_cancel_preserves_success(database: Database) -> None:
    bundle, authorized, resolved, running = await _prepare_running(database)
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        accepted = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=_result_request(bundle, resolved, running),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        cancellation = await lifecycle.cancel(
            authenticated_user_id=bundle.execution.user_id,
            request=CancellationRequest(
                cancellation_id=uuid.uuid4(),
                execution_id=bundle.execution.execution_id,
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                requested_at=NOW + timedelta(seconds=6),
            ),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert accepted.accepted is True
        assert cancellation.cancelled is False
        assert cancellation.status is ExecutionStatus.SUCCEEDED


async def test_duplicate_result_delivery_is_idempotent(database: Database) -> None:
    bundle, authorized, resolved, running = await _prepare_running(database)
    request = _result_request(bundle, resolved, running)
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        first = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=request,
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        duplicate = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=request,
            accepted_at=NOW + timedelta(seconds=6),
            trace_id=uuid.uuid4(),
        )
        with pytest.raises(AuthorityPreflightDenied, match="result_delivery_conflict"):
            await lifecycle.accept_result(
                authenticated_user_id=bundle.execution.user_id,
                authorized=authorized,
                resolved=resolved,
                request=request.model_copy(update={"result_digest": "8" * 64}),
                accepted_at=NOW + timedelta(seconds=7),
                trace_id=uuid.uuid4(),
            )
        await session.commit()
        assert first.accepted is True and first.duplicate is False
        assert duplicate.accepted is True and duplicate.duplicate is True
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.result_accepted")
            )
            == 1
        )


async def test_revoked_or_expired_authority_rejects_publication(
    database: Database,
) -> None:
    revoked_bundle, revoked_authorized, revoked_resolved, revoked_running = await _prepare_running(
        database
    )
    async with database.sessions() as session:
        await ControlledAgentRepository(session).append_revocation(
            RevocationRecord(
                revocation_id=uuid.uuid4(),
                subject_kind="grant",
                subject_id=revoked_bundle.grant.grant_id,
                user_id=revoked_bundle.execution.user_id,
                workspace_id=revoked_bundle.execution.workspace_id,
                execution_id=revoked_bundle.execution.execution_id,
                revoked_at=NOW + timedelta(seconds=4),
                reason_code="owner_revoked",
            )
        )
        rejected = await ControlledExecutionLifecycle(session).accept_result(
            authenticated_user_id=revoked_bundle.execution.user_id,
            authorized=revoked_authorized,
            resolved=revoked_resolved,
            request=_result_request(revoked_bundle, revoked_resolved, revoked_running),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert rejected.accepted is False
        assert rejected.reason_code == "grant_revoked"
        assert rejected.status is ExecutionStatus.CANCELLED

    expired_bundle, expired_authorized, expired_resolved, expired_running = await _prepare_running(
        database
    )
    async with database.sessions() as session:
        expired = await ControlledExecutionLifecycle(session).accept_result(
            authenticated_user_id=expired_bundle.execution.user_id,
            authorized=expired_authorized,
            resolved=expired_resolved,
            request=_result_request(expired_bundle, expired_resolved, expired_running),
            accepted_at=NOW + timedelta(minutes=6),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert expired.accepted is False
        assert expired.reason_code == "approval_inactive"
        assert expired.status is ExecutionStatus.CANCELLED


async def test_superseded_and_stale_running_results_are_rejected(
    database: Database,
) -> None:
    bundle, authorized, resolved, running = await _prepare_running(database)
    replacement_id = uuid.uuid4()
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        await lifecycle.cancel(
            authenticated_user_id=bundle.execution.user_id,
            request=CancellationRequest(
                cancellation_id=uuid.uuid4(),
                execution_id=bundle.execution.execution_id,
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                requested_at=NOW + timedelta(seconds=4),
                reason_code="execution_superseded",
                replacement_execution_id=replacement_id,
            ),
            trace_id=uuid.uuid4(),
        )
        superseded = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=_result_request(bundle, resolved, running),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert superseded.accepted is False
        assert superseded.status is ExecutionStatus.CANCELLED

    stale_bundle, stale_authorized, stale_resolved, stale_running = await _prepare_running(database)
    async with database.sessions() as session:
        stale = await ControlledExecutionLifecycle(session).accept_result(
            authenticated_user_id=stale_bundle.execution.user_id,
            authorized=stale_authorized,
            resolved=stale_resolved,
            request=_result_request(
                stale_bundle,
                stale_resolved,
                stale_running,
                running_state_id=uuid.uuid4(),
            ),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert stale.accepted is False
        assert stale.reason_code == "stale_execution_state"
        current = await ControlledAgentRepository(session).current_state(
            user_id=stale_bundle.execution.user_id,
            workspace_id=stale_bundle.execution.workspace_id,
            execution_id=stale_bundle.execution.execution_id,
        )
        assert current is not None and current.status == ExecutionStatus.RUNNING.value


async def test_wrong_and_recovered_lease_generations_reject_stale_results(
    database: Database,
) -> None:
    wrong_bundle, wrong_authorized, wrong_resolved, wrong_running = await _prepare_running(database)
    async with database.sessions() as session:
        wrong = await ControlledExecutionLifecycle(session).accept_result(
            authenticated_user_id=wrong_bundle.execution.user_id,
            authorized=wrong_authorized,
            resolved=wrong_resolved,
            request=_result_request(
                wrong_bundle,
                wrong_resolved,
                wrong_running,
            ).model_copy(update={"lease_generation": wrong_running.lease_generation + 1}),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert not wrong.accepted
        assert wrong.reason_code == "stale_execution_lease"

    (
        recovered_bundle,
        recovered_authorized,
        recovered_resolved,
        recovered_running,
    ) = await _prepare_running(database)
    async with database.sessions() as session:
        await ControlledExecutionReliability(session).recover_expired_lease(
            user_id=recovered_bundle.execution.user_id,
            workspace_id=recovered_bundle.execution.workspace_id,
            execution_id=recovered_bundle.execution.execution_id,
            expected_generation=recovered_running.lease_generation,
            recovered_at=NOW + timedelta(minutes=1, seconds=3),
        )
        stale = await ControlledExecutionLifecycle(session).accept_result(
            authenticated_user_id=recovered_bundle.execution.user_id,
            authorized=recovered_authorized,
            resolved=recovered_resolved,
            request=_result_request(
                recovered_bundle,
                recovered_resolved,
                recovered_running,
            ),
            accepted_at=NOW + timedelta(minutes=1, seconds=4),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert not stale.accepted
        assert stale.reason_code == "stale_execution_state"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.result_accepted")
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(TraceEvent.event_type == "execution.result_accepted")
            )
            == 0
        )


async def test_deadline_terminated_worker_cannot_publish_result(database: Database) -> None:
    bundle, authorized, resolved, running = await _prepare_running(database)
    async with database.sessions() as session:
        result = await ControlledExecutionLifecycle(session).accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=_result_request(bundle, resolved, running),
            accepted_at=NOW + timedelta(minutes=15),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert not result.accepted
        assert result.status is ExecutionStatus.CANCELLED
        assert result.reason_code == "execution_deadline_exceeded"
        current = await ControlledAgentRepository(session).current_state(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
        )
        assert current is not None
        assert current.status == ExecutionStatus.CANCELLED.value
        assert current.safe_reason_code == "execution_deadline_exceeded"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.result_accepted")
            )
            == 0
        )


async def test_distinct_delivery_after_completion_cannot_reopen_success(
    database: Database,
) -> None:
    bundle, authorized, resolved, running = await _prepare_running(database)
    async with database.sessions() as session:
        lifecycle = ControlledExecutionLifecycle(session)
        first = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=_result_request(bundle, resolved, running),
            accepted_at=NOW + timedelta(seconds=5),
            trace_id=uuid.uuid4(),
        )
        second = await lifecycle.accept_result(
            authenticated_user_id=bundle.execution.user_id,
            authorized=authorized,
            resolved=resolved,
            request=_result_request(bundle, resolved, running),
            accepted_at=NOW + timedelta(seconds=6),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
        assert first.accepted
        assert not second.accepted
        assert second.status is ExecutionStatus.SUCCEEDED
        assert second.reason_code == "stale_execution_state"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ControlledAgentAuditEvent)
                .where(ControlledAgentAuditEvent.event_type == "execution.result_accepted")
            )
            == 1
        )
