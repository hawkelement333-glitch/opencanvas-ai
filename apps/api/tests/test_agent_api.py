from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
from fastapi import FastAPI

from opencanvas_api.api.dependencies import get_current_principal
from opencanvas_api.db.models import User
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import ExecutionStateRecord, ExecutionStatus
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
from opencanvas_api.services.auth import Principal
from tests.agent_fixtures import NOW, make_agent_bundle


async def _seed_inspection(database: Database):
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
        for index, status in enumerate(
            (ExecutionStatus.PROPOSED, ExecutionStatus.AWAITING_APPROVAL, ExecutionStatus.READY)
        ):
            await repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=bundle.execution.execution_id,
                    user_id=bundle.execution.user_id,
                    workspace_id=bundle.execution.workspace_id,
                    status=status,
                    recorded_at=NOW + timedelta(seconds=index),
                )
            )
        await session.commit()
    return bundle


async def test_inspection_endpoint_is_read_only_paginated_and_secret_safe(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    bundle = await _seed_inspection(database)
    path = (
        f"{api_prefix}/workspaces/{bundle.execution.workspace_id}"
        f"/agent-executions/{bundle.execution.execution_id}"
    )
    response = await client.get(path, params={"limit": 1, "offset": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["executionId"] == str(bundle.execution.execution_id)
    assert body["context"] == {
        "snapshotId": str(bundle.context.snapshot_id),
        "digest": bundle.execution.context_digest,
        "capturedAt": "2026-07-21T18:00:00Z",
    }
    assert [state["status"] for state in body["states"]] == ["awaiting_approval"]
    serialized = response.text.lower()
    assert all(
        prohibited not in serialized
        for prohibited in (
            "payload",
            "sessionid",
            "issuingservice",
            "authorization",
            "password",
            "api_key",
            "secret",
        )
    )
    assert (await client.post(path)).status_code == 405
    assert (await client.get(path, params={"limit": 101})).status_code == 422


async def test_inspection_endpoint_hides_cross_user_and_missing_records(
    app: FastAPI,
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    bundle = await _seed_inspection(database)
    other_user_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            User(
                id=other_user_id,
                email="inspector@example.test",
                email_normalized="inspector@example.test",
                password_hash="test-only",
                display_name="Other inspector",
                email_verified=True,
            )
        )
        await session.commit()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=other_user_id,
        email="inspector@example.test",
        display_name="Other inspector",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    owner_path = (
        f"{api_prefix}/workspaces/{bundle.execution.workspace_id}"
        f"/agent-executions/{bundle.execution.execution_id}"
    )
    missing_path = (
        f"{api_prefix}/workspaces/{bundle.execution.workspace_id}/agent-executions/{uuid.uuid4()}"
    )
    for response in (await client.get(owner_path), await client.get(missing_path)):
        assert response.status_code == 404
        assert response.json()["code"] == "agent_execution_not_found"
