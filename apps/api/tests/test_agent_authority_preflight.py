from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    Canvas,
    ControlledAgentApprovalConsumption,
    ControlledAgentPolicyDecision,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import (
    Capability,
    ResourceKind,
    ResourceScope,
)
from opencanvas_api.services.agents.execution import (
    AuthorityPreflightDenied,
    ControlledAction,
    ControlledExecutionRequest,
    ExecutionAuthorityPreflight,
)
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
from tests.agent_fixtures import NOW, AgentBundle, make_agent_bundle


async def setup_authority(database: Database) -> tuple[AgentBundle, uuid.UUID]:
    canvas_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            Canvas(
                id=canvas_id, workspace_id=make_agent_bundle().execution.workspace_id, name="Agent"
            )
        )
        await session.flush()
        bundle = make_agent_bundle(
            resource=ResourceScope(kind=ResourceKind.CANVAS, resource_id=canvas_id),
            capability=Capability.DRAFT_ANSWER_CREATE,
        )
        await ControlledAgentRepository(session).append_bundle(
            execution=bundle.execution,
            context=bundle.context,
            plan=bundle.plan,
            grant=bundle.grant,
            approval=bundle.approval,
        )
        await session.commit()
    return bundle, canvas_id


def request_for(
    bundle: AgentBundle, base_canvas_id: uuid.UUID, **updates: object
) -> ControlledExecutionRequest:
    values: dict[str, object] = {
        "user_id": bundle.execution.user_id,
        "workspace_id": bundle.execution.workspace_id,
        "canvas_id": base_canvas_id,
        "execution_id": bundle.execution.execution_id,
        "context_snapshot_id": bundle.context.snapshot_id,
        "expected_context_digest": bundle.execution.context_digest,
        "plan_id": bundle.plan.plan_id,
        "expected_plan_digest": bundle.execution.plan_digest,
        "action": ControlledAction.GENERATE_GROUNDED_DRAFT,
        "grant_id": bundle.grant.grant_id,
        "approval_id": bundle.approval.approval_id,
        "idempotency_key": "authority:request-1",
        "correlation_id": "authority-correlation",
    }
    values.update(updates)
    return ControlledExecutionRequest(**values)


async def test_valid_stored_authority_records_decision_and_consumes_once(
    database: Database,
) -> None:
    bundle, canvas_id = await setup_authority(database)
    async with database.sessions() as session:
        result = await ExecutionAuthorityPreflight(session).authorize(
            authenticated_user_id=bundle.execution.user_id,
            request=request_for(bundle, canvas_id),
            evaluated_at=NOW + timedelta(minutes=1),
        )
        await session.commit()
        assert result.grant_id == bundle.grant.grant_id
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentPolicyDecision))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 1
        )


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"canvas_id": uuid.uuid4()}, "canvas_scope_mismatch"),
        ({"grant_id": uuid.uuid4()}, "grant_scope_mismatch"),
        ({"approval_id": uuid.uuid4()}, "approval_missing"),
        ({"expected_context_digest": "f" * 64}, "context_hash_mismatch"),
        ({"expected_plan_digest": "f" * 64}, "plan_hash_mismatch"),
    ],
)
async def test_reference_and_scope_failures_do_not_consume(
    database: Database, updates: dict[str, object], reason: str
) -> None:
    bundle, canvas_id = await setup_authority(database)
    async with database.sessions() as session:
        with pytest.raises(AuthorityPreflightDenied, match=reason):
            await ExecutionAuthorityPreflight(session).authorize(
                authenticated_user_id=bundle.execution.user_id,
                request=request_for(bundle, canvas_id, **updates),
                evaluated_at=NOW + timedelta(minutes=1),
            )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )


async def test_replay_is_denied_and_audited_without_second_consumption(database: Database) -> None:
    bundle, canvas_id = await setup_authority(database)
    request = request_for(bundle, canvas_id)
    async with database.sessions() as session:
        service = ExecutionAuthorityPreflight(session)
        await service.authorize(
            authenticated_user_id=bundle.execution.user_id,
            request=request,
            evaluated_at=NOW + timedelta(minutes=1),
        )
        with pytest.raises(AuthorityPreflightDenied, match="approval_replayed"):
            await service.authorize(
                authenticated_user_id=bundle.execution.user_id,
                request=request,
                evaluated_at=NOW + timedelta(minutes=1, seconds=1),
            )
        await session.commit()
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


async def test_authenticated_identity_cannot_be_replaced_by_request(database: Database) -> None:
    bundle, canvas_id = await setup_authority(database)
    async with database.sessions() as session:
        with pytest.raises(AuthorityPreflightDenied, match="user_scope_mismatch"):
            await ExecutionAuthorityPreflight(session).authorize(
                authenticated_user_id=uuid.uuid4(),
                request=request_for(bundle, canvas_id),
                evaluated_at=NOW + timedelta(minutes=1),
            )


async def test_parallel_requests_cannot_consume_one_approval_twice(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'authority-concurrency.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="parallel@mobius.invalid",
                email_normalized="parallel@mobius.invalid",
                password_hash="test-only",
                display_name="Parallel test",
                email_verified=True,
            )
        )
        session.add(
            Workspace(id=SYSTEM_WORKSPACE_ID, owner_id=SYSTEM_USER_ID, name="Parallel test")
        )
        await session.commit()
    bundle, canvas_id = await setup_authority(database)
    request = request_for(bundle, canvas_id)

    async def attempt(offset: int) -> str:
        async with database.sessions() as session:
            try:
                await ExecutionAuthorityPreflight(session).authorize(
                    authenticated_user_id=bundle.execution.user_id,
                    request=request,
                    evaluated_at=NOW + timedelta(minutes=1, seconds=offset),
                )
                result = "allow"
            except AuthorityPreflightDenied as exc:
                result = exc.reason_code
            await session.commit()
            return result

    try:
        assert sorted(await asyncio.gather(attempt(0), attempt(1))) == [
            "allow",
            "approval_replayed",
        ]
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ControlledAgentApprovalConsumption)
                )
                == 1
            )
    finally:
        await database.dispose()
