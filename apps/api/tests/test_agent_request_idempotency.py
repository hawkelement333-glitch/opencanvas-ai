from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentRequestIdentity,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.execution import (
    ExecutionRequestRegistry,
    IdempotencyConflict,
)
from tests.agent_fixtures import NOW
from tests.test_agent_authority_preflight import request_for, setup_authority


async def test_identical_retry_reuses_one_database_identity(database: Database) -> None:
    bundle, canvas_id = await setup_authority(database)
    request = request_for(bundle, canvas_id)
    async with database.sessions() as session:
        registry = ExecutionRequestRegistry(session)
        first = await registry.reserve(
            authenticated_user_id=bundle.execution.user_id, request=request, created_at=NOW
        )
        retry = await registry.reserve(
            authenticated_user_id=bundle.execution.user_id,
            request=request.model_copy(update={"correlation_id": "retry"}),
            created_at=NOW + timedelta(seconds=1),
        )
        await session.commit()
        assert first.created is True
        assert retry.created is False
        assert retry.request_identity_id == first.request_identity_id
        assert retry.execution_id == first.execution_id
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentRequestIdentity))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"expected_context_digest": "c" * 64},
        {"expected_plan_digest": "d" * 64},
        {"grant_id": uuid.uuid4()},
        {"approval_id": uuid.uuid4()},
    ],
)
async def test_conflicting_key_is_denied_and_audited_without_mutation(
    database: Database, updates: dict[str, object]
) -> None:
    bundle, canvas_id = await setup_authority(database)
    request = request_for(bundle, canvas_id)
    async with database.sessions() as session:
        registry = ExecutionRequestRegistry(session)
        first = await registry.reserve(
            authenticated_user_id=bundle.execution.user_id, request=request, created_at=NOW
        )
        with pytest.raises(IdempotencyConflict, match="idempotency_conflict"):
            await registry.reserve(
                authenticated_user_id=bundle.execution.user_id,
                request=request.model_copy(update=updates),
                created_at=NOW + timedelta(seconds=1),
            )
        await session.commit()
        stored = await session.get(ControlledAgentRequestIdentity, first.request_identity_id)
        assert stored is not None and stored.request_digest == first.request_digest
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentAuditEvent)) == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )


async def test_request_identity_is_append_only(database: Database) -> None:
    bundle, canvas_id = await setup_authority(database)
    async with database.sessions() as session:
        reserved = await ExecutionRequestRegistry(session).reserve(
            authenticated_user_id=bundle.execution.user_id,
            request=request_for(bundle, canvas_id),
            created_at=NOW,
        )
        await session.commit()
        stored = await session.get(ControlledAgentRequestIdentity, reserved.request_identity_id)
        assert stored is not None
        stored.request_digest = "f" * 64
        with pytest.raises(ValueError, match="append-only"):
            await session.commit()
