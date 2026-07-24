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
from tests.test_canvas_api import _create_canvas, _create_node


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


async def test_authenticated_grounded_draft_start_is_idempotent_and_conflict_safe(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Controlled draft")
    first = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Selected note",
        text="Untrusted evidence only.",
    )
    second = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Different note",
        text="Different untrusted evidence.",
    )
    payload = {
        "canvasId": canvas["id"],
        "instruction": "What evidence is available?",
        "selectedNodeIds": [first["id"]],
        "idempotencyKey": "terra-api-draft-001",
    }
    route = f"{api_prefix}/workspaces/{canvas['workspaceId']}/agent-executions/drafts"
    started = await client.post(route, json=payload)
    assert started.status_code == 201, started.text
    first_result = started.json()
    assert first_result["insufficientEvidence"] is True
    assert first_result["citations"] == []
    assert first_result["duplicate"] is False

    duplicate = await client.post(route, json=payload)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["executionId"] == first_result["executionId"]
    assert duplicate.json()["duplicate"] is True

    conflict = await client.post(
        route,
        json={**payload, "selectedNodeIds": [second["id"]]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


async def test_prepared_draft_exposes_server_id_for_authoritative_cancellation(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Prepared controlled draft")
    node = await _create_node(client, api_prefix, canvas["id"], title="Evidence", text="Evidence.")
    route = f"{api_prefix}/workspaces/{canvas['workspaceId']}/agent-executions"
    prepared = await client.post(
        f"{route}/drafts/prepare",
        json={
            "canvasId": canvas["id"], "instruction": "What is supported?",
            "selectedNodeIds": [node["id"]], "idempotencyKey": "terra-prepared-cancel-001",
        },
    )
    assert prepared.status_code == 201, prepared.text
    body = prepared.json()
    assert body["status"] == "ready"
    execution_id = body["executionId"]
    cancelled = await client.post(
        f"{route}/{execution_id}/cancel", json={"idempotencyKey": "terra-cancel-confirm-001"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancelled"] is True
    assert cancelled.json()["status"] == "cancelled"
    refused = await client.post(f"{route}/{execution_id}/run")
    assert refused.status_code == 409
    assert refused.json()["code"] == "execution_not_runnable"
