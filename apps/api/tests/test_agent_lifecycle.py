from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import ExecutionStateRecord, ExecutionStatus
from opencanvas_api.services.agents.persistence import (
    AgentPersistenceNotFound,
    AgentStateTransitionError,
    ControlledAgentRepository,
)
from tests.agent_fixtures import NOW, AgentBundle, make_agent_bundle


async def _persist_bundle(database: Database) -> AgentBundle:
    bundle = make_agent_bundle()
    async with database.sessions() as session:
        await ControlledAgentRepository(session).append_bundle(
            execution=bundle.execution,
            context=bundle.context,
            plan=bundle.plan,
            grant=bundle.grant,
            approval=bundle.approval,
        )
        await session.commit()
    return bundle


def _state(
    bundle: AgentBundle,
    status: ExecutionStatus,
    second: int,
) -> ExecutionStateRecord:
    return ExecutionStateRecord(
        state_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        status=status,
        recorded_at=NOW + timedelta(seconds=second),
    )


async def test_valid_lifecycle_is_append_only_and_terminal(database: Database) -> None:
    bundle = await _persist_bundle(database)
    statuses = (
        ExecutionStatus.PROPOSED,
        ExecutionStatus.AWAITING_APPROVAL,
        ExecutionStatus.READY,
        ExecutionStatus.RUNNING,
        ExecutionStatus.SUCCEEDED,
    )
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        for second, status in enumerate(statuses):
            await repository.append_state(_state(bundle, status, second))
        with pytest.raises(AgentStateTransitionError, match="execution_already_terminal"):
            await repository.append_state(_state(bundle, ExecutionStatus.RUNNING, 10))
        await session.commit()

        inspection = await repository.inspect_execution(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            limit=20,
            offset=0,
        )
        assert tuple(ExecutionStatus(row.status) for row in inspection.states) == statuses


async def test_execution_must_begin_proposed_and_rejects_skipped_terminal(
    database: Database,
) -> None:
    first = await _persist_bundle(database)
    second = await _persist_bundle(database)
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        with pytest.raises(AgentStateTransitionError, match="execution_must_begin_proposed"):
            await repository.append_state(_state(first, ExecutionStatus.READY, 0))

        await repository.append_state(_state(second, ExecutionStatus.PROPOSED, 0))
        with pytest.raises(
            AgentStateTransitionError,
            match="invalid_execution_transition:proposed:succeeded",
        ):
            await repository.append_state(_state(second, ExecutionStatus.SUCCEEDED, 1))


async def test_state_time_cannot_regress_and_scope_is_server_verified(
    database: Database,
) -> None:
    bundle = await _persist_bundle(database)
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        await repository.append_state(_state(bundle, ExecutionStatus.PROPOSED, 2))
        with pytest.raises(AgentStateTransitionError, match="execution_state_time_regressed"):
            await repository.append_state(_state(bundle, ExecutionStatus.AWAITING_APPROVAL, 1))

        wrong_scope = _state(bundle, ExecutionStatus.AWAITING_APPROVAL, 3).model_copy(
            update={"user_id": uuid.uuid4()}
        )
        with pytest.raises(AgentPersistenceNotFound):
            await repository.append_state(wrong_scope)


async def test_current_state_uses_validated_transition_order(database: Database) -> None:
    bundle = await _persist_bundle(database)
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        assert (
            await repository.current_state(
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                execution_id=bundle.execution.execution_id,
            )
            is None
        )
        await repository.append_state(_state(bundle, ExecutionStatus.PROPOSED, 0))
        ready = _state(bundle, ExecutionStatus.READY, 1)
        await repository.append_state(ready)
        current = await repository.current_state(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
        )
        assert current is not None
        assert current.state_id == ready.state_id
        assert current.status == ExecutionStatus.READY.value
