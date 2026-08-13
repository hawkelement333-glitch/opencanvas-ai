from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.api.routes import canvases as canvas_routes
from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    Edge,
    LegacyCreationRequestIdentity,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from tests.test_canvas_api import _create_canvas, _create_node


async def test_every_legacy_creation_path_replays_original_result(
    client: httpx.AsyncClient, api_prefix: str, database: Database
) -> None:
    canvas_key = "canvas-replay-0001"
    canvas_payload = {"idempotencyKey": canvas_key, "name": "Durable canvas"}
    first_canvas = await client.post(f"{api_prefix}/canvases", json=canvas_payload)
    replayed_canvas = await client.post(f"{api_prefix}/canvases", json=canvas_payload)
    assert first_canvas.status_code == replayed_canvas.status_code == 201
    assert first_canvas.json()["id"] == replayed_canvas.json()["id"]
    canvas = first_canvas.json()

    node_key = "node-replay-000001"
    node_payload = {
        "idempotencyKey": node_key,
        "type": "note",
        "title": "Durable node",
        "text": "body",
        "position": {"x": 10, "y": 20},
    }
    first_node = await client.post(f"{api_prefix}/canvases/{canvas['id']}/nodes", json=node_payload)
    replayed_node = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/nodes", json=node_payload
    )
    assert first_node.status_code == replayed_node.status_code == 201
    assert first_node.json()["id"] == replayed_node.json()["id"]
    node = first_node.json()

    duplicate_key = "duplicate-replay-01"
    duplicate_payload = {
        "idempotencyKey": duplicate_key,
        "revision": node["revision"],
    }
    duplicate_url = f"{api_prefix}/canvases/{canvas['id']}/nodes/{node['id']}/duplicate"
    first_duplicate = await client.post(duplicate_url, json=duplicate_payload)
    replayed_duplicate = await client.post(duplicate_url, json=duplicate_payload)
    assert first_duplicate.status_code == replayed_duplicate.status_code == 201
    assert first_duplicate.json()["id"] == replayed_duplicate.json()["id"]

    target = await _create_node(
        client, api_prefix, canvas["id"], title="Target", text="target", x=400
    )
    edge_key = "edge-replay-000001"
    edge_payload = {
        "idempotencyKey": edge_key,
        "sourceNodeId": node["id"],
        "targetNodeId": target["id"],
        "kind": "default",
        "label": "durable",
    }
    edge_url = f"{api_prefix}/canvases/{canvas['id']}/edges"
    first_edge = await client.post(edge_url, json=edge_payload)
    replayed_edge = await client.post(edge_url, json=edge_payload)
    assert first_edge.status_code == replayed_edge.status_code == 201
    assert first_edge.json()["id"] == replayed_edge.json()["id"]

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(Canvas.id))) == 1
        assert await session.scalar(select(func.count(CanvasNode.id))) == 3
        assert await session.scalar(select(func.count(Edge.id))) == 1
        assert (
            await session.scalar(select(func.count(LegacyCreationRequestIdentity.request_id))) == 5
        )


async def test_conflicting_payload_reuse_fails_without_leaking_result(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    key = "conflicting-canvas-01"
    first = await client.post(
        f"{api_prefix}/canvases", json={"idempotencyKey": key, "name": "Original"}
    )
    assert first.status_code == 201
    conflict = await client.post(
        f"{api_prefix}/canvases", json={"idempotencyKey": key, "name": "Different"}
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert first.json()["id"] not in conflict.text


async def test_concurrent_duplicate_requests_create_one_canvas(
    app: FastAPI, api_prefix: str, database: Database
) -> None:
    transport = httpx.ASGITransport(app=app)
    payload = {"idempotencyKey": "concurrent-canvas-01", "name": "One canvas"}
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as first_client,
        httpx.AsyncClient(transport=transport, base_url="http://test") as second_client,
    ):
        first, second = await asyncio.gather(
            first_client.post(f"{api_prefix}/canvases", json=payload),
            second_client.post(f"{api_prefix}/canvases", json=payload),
        )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(Canvas.id))) == 1


async def test_rollback_removes_claim_and_retry_succeeds(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = await _create_canvas(client, api_prefix)
    original_bump = canvas_routes._bump_canvas

    async def fail_after_claim(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("test rollback")

    monkeypatch.setattr(canvas_routes, "_bump_canvas", fail_after_claim)
    payload = {
        "idempotencyKey": "rollback-node-0001",
        "type": "note",
        "title": "Retry me",
        "text": "",
        "position": {"x": 1, "y": 2},
    }
    with pytest.raises(RuntimeError, match="test rollback"):
        await client.post(f"{api_prefix}/canvases/{canvas['id']}/nodes", json=payload)
    monkeypatch.setattr(canvas_routes, "_bump_canvas", original_bump)
    retried = await client.post(f"{api_prefix}/canvases/{canvas['id']}/nodes", json=payload)
    assert retried.status_code == 201
    async with database.sessions() as session:
        count = await session.scalar(
            select(func.count(LegacyCreationRequestIdentity.request_id)).where(
                LegacyCreationRequestIdentity.idempotency_key == "rollback-node-0001"
            )
        )
        assert count == 1


async def test_completed_replay_survives_client_replacement(app: FastAPI, api_prefix: str) -> None:
    payload = {"idempotencyKey": "process-independent-01", "name": "Persistent"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as first_client:
        first = await first_client.post(f"{api_prefix}/canvases", json=payload)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as replacement:
        replay = await replacement.post(f"{api_prefix}/canvases", json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]


async def test_workspace_authority_is_revalidated_before_replay(
    client: httpx.AsyncClient, api_prefix: str, database: Database
) -> None:
    key = "tenant-replay-000001"
    created = await client.post(
        f"{api_prefix}/canvases",
        json={"idempotencyKey": key, "name": "Authorized"},
    )
    assert created.status_code == 201
    other_user_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            User(
                id=other_user_id,
                email="other-tenant@example.test",
                email_normalized="other-tenant@example.test",
                password_hash="test-only",
                display_name="Other tenant",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=other_workspace_id,
                owner_id=other_user_id,
                name="Other workspace",
            )
        )
        await session.commit()
    forged = await client.post(
        f"{api_prefix}/canvases",
        json={
            "idempotencyKey": key,
            "name": "Authorized",
            "workspaceId": str(other_workspace_id),
        },
    )
    assert forged.status_code == 404
    assert created.json()["id"] not in forged.text
