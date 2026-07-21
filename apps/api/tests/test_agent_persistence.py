from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from opencanvas_api.db.models import (
    ControlledAgentApprovalConsumption,
    ControlledAgentCapabilityGrant,
    ControlledAgentContextSnapshot,
    ControlledAgentGrantRevocation,
    ControlledAgentPlanSnapshot,
    ControlledAgentPolicyDecision,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import (
    AuditAttribute,
    AuditEvent,
    Capability,
    ExecutionStateRecord,
    ExecutionStatus,
    PolicyOutcome,
    RevocationRecord,
)
from opencanvas_api.services.agents.persistence import (
    AgentContractIntegrityError,
    AgentPersistenceNotFound,
    ApprovalConsumptionAttempt,
    ControlledAgentRepository,
)
from tests.agent_fixtures import NOW, make_agent_bundle


async def _persist_bundle(database: Database, **kwargs: object):
    bundle = make_agent_bundle(**kwargs)  # type: ignore[arg-type]
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


def _attempt(bundle, **updates: object) -> ApprovalConsumptionAttempt:
    values = {
        "consumption_id": uuid.uuid4(),
        "decision_id": uuid.uuid4(),
        "user_id": bundle.execution.user_id,
        "workspace_id": bundle.execution.workspace_id,
        "execution_id": bundle.execution.execution_id,
        "approval_id": bundle.approval.approval_id,
        "capability": Capability.DOCUMENT_VERSION_READ,
        "resource": bundle.resource,
        "evaluated_at": NOW + timedelta(minutes=1),
    }
    values.update(updates)
    return ApprovalConsumptionAttempt(**values)  # type: ignore[arg-type]


async def test_immutable_snapshots_and_append_only_state_history(database: Database) -> None:
    bundle = await _persist_bundle(database)
    first = ExecutionStateRecord(
        state_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        status=ExecutionStatus.PROPOSED,
        recorded_at=NOW,
    )
    second = first.model_copy(
        update={
            "state_id": uuid.uuid4(),
            "status": ExecutionStatus.AWAITING_APPROVAL,
            "recorded_at": NOW + timedelta(seconds=1),
        }
    )
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        await repository.append_state(first)
        await repository.append_state(second)
        await session.commit()
        inspection = await repository.inspect_execution(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            limit=50,
            offset=0,
        )
        assert [row.status for row in inspection.states] == [
            ExecutionStatus.PROPOSED.value,
            ExecutionStatus.AWAITING_APPROVAL.value,
        ]
        inspection.plan.payload_digest = "f" * 64
        with pytest.raises(ValueError, match="append-only"):
            await session.commit()
        await session.rollback()


async def test_revocation_is_separate_and_blocks_approval_consumption(database: Database) -> None:
    bundle = await _persist_bundle(database)
    revocation = RevocationRecord(
        revocation_id=uuid.uuid4(),
        subject_kind="grant",
        subject_id=bundle.grant.grant_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        execution_id=bundle.execution.execution_id,
        revoked_at=NOW + timedelta(seconds=30),
        reason_code="owner_revoked",
    )
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        await repository.append_revocation(revocation)
        result = await repository.consume_approval(_attempt(bundle))
        await session.commit()
        assert (result.outcome, result.reason_code) == (PolicyOutcome.DENY, "grant_revoked")
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentGrantRevocation))
            == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentCapabilityGrant))
            == 1
        )


async def test_approval_is_consumed_exactly_once_and_replay_is_audited(database: Database) -> None:
    bundle = await _persist_bundle(database)
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        first = await repository.consume_approval(_attempt(bundle))
        second = await repository.consume_approval(_attempt(bundle))
        await session.commit()
        assert (first.outcome, first.reason_code) == (PolicyOutcome.ALLOW, "approval_valid")
        assert (second.outcome, second.reason_code) == (PolicyOutcome.DENY, "approval_replayed")
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentPolicyDecision))
            == 2
        )


async def test_expired_approval_is_rejected_without_consumption(database: Database) -> None:
    bundle = await _persist_bundle(database, approval_expires_at=NOW + timedelta(seconds=30))
    async with database.sessions() as session:
        result = await ControlledAgentRepository(session).consume_approval(_attempt(bundle))
        await session.commit()
        assert (result.outcome, result.reason_code) == (PolicyOutcome.DENY, "approval_inactive")
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )


@pytest.mark.parametrize("scope_field", ["user_id", "workspace_id", "execution_id"])
async def test_consumption_rejects_wrong_actor_workspace_or_execution(
    database: Database, scope_field: str
) -> None:
    bundle = await _persist_bundle(database)
    async with database.sessions() as session:
        with pytest.raises(AgentPersistenceNotFound):
            await ControlledAgentRepository(session).consume_approval(
                _attempt(bundle, **{scope_field: uuid.uuid4()})
            )


@pytest.mark.parametrize(
    "record_kind",
    ["plan", "context"],
)
async def test_changed_plan_or_context_hash_is_detected(
    database: Database, record_kind: str
) -> None:
    bundle = await _persist_bundle(database)
    if record_kind == "plan":
        statement = (
            update(ControlledAgentPlanSnapshot)
            .where(ControlledAgentPlanSnapshot.plan_id == bundle.plan.plan_id)
            .values(payload_digest="f" * 64)
        )
    else:
        statement = (
            update(ControlledAgentContextSnapshot)
            .where(ControlledAgentContextSnapshot.snapshot_id == bundle.context.snapshot_id)
            .values(payload_digest="f" * 64)
        )
    async with database.sessions() as session:
        await session.execute(statement)
        await session.commit()
    async with database.sessions() as session:
        with pytest.raises(AgentContractIntegrityError, match="digest changed"):
            await ControlledAgentRepository(session).consume_approval(_attempt(bundle))


async def test_approval_binding_rejects_altered_hash_before_persistence(
    database: Database,
) -> None:
    bundle = make_agent_bundle()
    altered = bundle.approval.model_copy(update={"context_digest": "f" * 64})
    async with database.sessions() as session:
        with pytest.raises(AgentContractIntegrityError, match="Approval binding"):
            await ControlledAgentRepository(session).append_bundle(
                execution=bundle.execution,
                context=bundle.context,
                plan=bundle.plan,
                grant=bundle.grant,
                approval=altered,
            )


async def test_repository_reads_require_owner_workspace_and_execution(database: Database) -> None:
    bundle = await _persist_bundle(database)
    other_user_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            User(
                id=other_user_id,
                email="other@example.test",
                email_normalized="other@example.test",
                password_hash="test-only",
                display_name="Other",
                email_verified=True,
            )
        )
        session.add(Workspace(id=other_workspace_id, owner_id=other_user_id, name="Other"))
        await session.commit()
        repository = ControlledAgentRepository(session)
        for user_id, workspace_id, execution_id in (
            (other_user_id, bundle.execution.workspace_id, bundle.execution.execution_id),
            (bundle.execution.user_id, other_workspace_id, bundle.execution.execution_id),
            (bundle.execution.user_id, bundle.execution.workspace_id, uuid.uuid4()),
        ):
            with pytest.raises(AgentPersistenceNotFound):
                await repository.inspect_execution(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    execution_id=execution_id,
                    limit=50,
                    offset=0,
                )


async def test_audit_event_persists_only_bounded_attributes(database: Database) -> None:
    bundle = await _persist_bundle(database)
    event = AuditEvent(
        event_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        execution_id=bundle.execution.execution_id,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        event_type="approval.reviewed",
        recorded_at=NOW,
        attributes=(AuditAttribute(key="result", value="approved"),),
    )
    async with database.sessions() as session:
        repository = ControlledAgentRepository(session)
        await repository.append_audit_event(event)
        await session.commit()
        inspection = await repository.inspect_execution(
            user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            execution_id=bundle.execution.execution_id,
            limit=50,
            offset=0,
        )
        assert inspection.audit_events[0].attributes == [{"key": "result", "value": "approved"}]
