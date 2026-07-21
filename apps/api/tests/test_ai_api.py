from __future__ import annotations

import uuid
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.api.dependencies import get_ai_provider
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    AIExecutionNode,
    AIRequest,
    AIResponse,
    CanvasNode,
    Edge,
    UsageRecord,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.ai import AIProviderError
from opencanvas_api.services.context import ContextBundle
from tests.test_canvas_api import _create_canvas, _create_node


async def test_full_create_save_refresh_query_workflow(
    client: httpx.AsyncClient, api_prefix: str, database: Database
) -> None:
    canvas = await _create_canvas(client, api_prefix)
    first = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Customer signal",
        text="Teams want a visual memory graph.",
    )
    second = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Technical bet",
        text="React Flow plus a server-owned context boundary.",
        x=420,
    )

    before_refresh = (await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")).json()
    assert {node["id"] for node in before_refresh["nodes"]} == {first["id"], second["id"]}

    query = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "Synthesize the product opportunity.",
            "selectedNodeIds": [second["id"], first["id"]],
        },
    )
    assert query.status_code == 201
    result = query.json()
    assert result["mock"] is True
    assert result["node"]["type"] == "ai_response"
    assert "Technical bet" in result["node"]["text"]
    assert "Customer signal" in result["node"]["text"]
    assert [edge["sourceNodeId"] for edge in result["edges"]] == [second["id"], first["id"]]
    assert all(edge["targetNodeId"] == result["node"]["id"] for edge in result["edges"])

    after_refresh = (await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")).json()
    assert len(after_refresh["nodes"]) == 3
    assert len(after_refresh["edges"]) == 2

    async with database.sessions() as session:
        request = await session.get(AIRequest, uuid.UUID(result["requestId"]))
        response = await session.get(AIResponse, uuid.UUID(result["responseId"]))
    assert request is not None and request.status == "completed"
    assert request.selected_node_ids == [second["id"], first["id"]]
    assert response is not None and str(response.node_id) == result["node"]["id"]


async def test_ai_request_validation_rejects_empty_duplicate_and_cross_canvas_ids(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    first_canvas = await _create_canvas(client, api_prefix, "First")
    second_canvas = await _create_canvas(client, api_prefix, "Second")
    first_node = await _create_node(client, api_prefix, first_canvas["id"], title="One", text="one")
    second_node = await _create_node(
        client, api_prefix, second_canvas["id"], title="Two", text="two"
    )

    empty = await client.post(
        f"{api_prefix}/canvases/{first_canvas['id']}/ai",
        json={"instruction": "Answer", "selectedNodeIds": []},
    )
    assert empty.status_code == 422

    duplicate = await client.post(
        f"{api_prefix}/canvases/{first_canvas['id']}/ai",
        json={
            "instruction": "Answer",
            "selectedNodeIds": [first_node["id"], first_node["id"]],
        },
    )
    assert duplicate.status_code == 422

    cross_canvas = await client.post(
        f"{api_prefix}/canvases/{first_canvas['id']}/ai",
        json={"instruction": "Answer", "selectedNodeIds": [second_node["id"]]},
    )
    assert cross_canvas.status_code == 400
    assert cross_canvas.json()["code"] == "invalid_selected_nodes"


class FailingProvider:
    name = "openai"
    model = "test-model"
    mock = False

    async def generate(self, instruction: str, context: ContextBundle) -> None:
        raise AIProviderError("Provider unavailable.")


async def test_openai_failure_persists_failed_request_without_partial_graph(
    client: httpx.AsyncClient,
    app: FastAPI,
    database: Database,
    api_prefix: str,
) -> None:
    app.dependency_overrides[get_ai_provider] = lambda: FailingProvider()
    canvas = await _create_canvas(client, api_prefix)
    node = await _create_node(client, api_prefix, canvas["id"], title="Context", text="safe")

    response = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={"instruction": "Answer", "selectedNodeIds": [node["id"]]},
    )

    assert response.status_code == 502
    assert response.json() == {
        "code": "ai_provider_error",
        "detail": "The AI provider could not complete the request. Try again.",
    }
    async with database.sessions() as session:
        requests = (await session.scalars(select(AIRequest))).all()
        response_count = await session.scalar(select(func.count()).select_from(AIResponse))
        node_count = await session.scalar(select(func.count()).select_from(CanvasNode))
        edge_count = await session.scalar(select(func.count()).select_from(Edge))
    assert len(requests) == 1
    assert requests[0].status == "failed"
    assert requests[0].error == "The configured AI provider could not complete the request."
    assert requests[0].safe_error_category == "provider_failure"
    assert response_count == 0
    assert node_count == 1
    assert edge_count == 0


async def test_original_and_current_context_reruns_are_linked_and_distinct(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Rerun comparison")
    node = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Decision",
        text="The original launch window is October.",
    )
    initial = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "Restate the selected launch window.",
            "selectedNodeIds": [node["id"]],
        },
    )
    assert initial.status_code == 201, initial.text
    original_request_id = initial.json()["requestId"]

    edited = await client.patch(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{node['id']}",
        json={
            "revision": node["revision"],
            "text": "The current launch window is December.",
        },
    )
    assert edited.status_code == 200, edited.text

    original_rerun = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai/{original_request_id}/rerun-original"
    )
    current_rerun = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai/{original_request_id}/rerun-current"
    )
    assert original_rerun.status_code == 201, original_rerun.text
    assert current_rerun.status_code == 201, current_rerun.text
    original_result = original_rerun.json()
    current_result = current_rerun.json()
    assert "original launch window is October" in original_result["node"]["text"]
    assert "current launch window is December" not in original_result["node"]["text"]
    assert "current launch window is December" in current_result["node"]["text"]
    assert original_result["parentRequestId"] == original_request_id
    assert original_result["rerunType"] == "original_context"
    assert current_result["parentRequestId"] == original_request_id
    assert current_result["rerunType"] == "current_context"
    original_trace = await client.get(f"{api_prefix}/traces/{original_result['traceId']}")
    assert original_trace.status_code == 200
    assert {event["parentTraceId"] for event in original_trace.json()} == {
        initial.json()["traceId"]
    }
    assert original_trace.json()[0]["metadata"]["rerunType"] == "original_context"

    other_canvas = await _create_canvas(client, api_prefix, "Unrelated canvas")
    denied = await client.post(
        f"{api_prefix}/canvases/{other_canvas['id']}/ai/{original_request_id}/rerun-original"
    )
    assert denied.status_code == 404
    assert denied.json()["code"] == "execution_not_found"

    async with database.sessions() as session:
        original_request = await session.get(AIRequest, uuid.UUID(original_result["requestId"]))
        current_request = await session.get(AIRequest, uuid.UUID(current_result["requestId"]))
        original_snapshot = await session.scalar(
            select(AIExecutionNode).where(
                AIExecutionNode.request_id == uuid.UUID(original_result["requestId"])
            )
        )
        current_snapshot = await session.scalar(
            select(AIExecutionNode).where(
                AIExecutionNode.request_id == uuid.UUID(current_result["requestId"])
            )
        )
    assert original_request is not None
    assert original_request.parent_request_id == uuid.UUID(original_request_id)
    assert original_request.execution_mode == "original_context"
    assert current_request is not None
    assert current_request.parent_request_id == uuid.UUID(original_request_id)
    assert current_request.execution_mode == "current_context"
    assert original_snapshot is not None
    assert original_snapshot.content_snapshot == "The original launch window is October."
    assert current_snapshot is not None
    assert current_snapshot.content_snapshot == "The current launch window is December."


@pytest.mark.security
async def test_workspace_monthly_token_budget_fails_before_provider_execution(
    client: httpx.AsyncClient,
    app: FastAPI,
    database: Database,
    api_prefix: str,
) -> None:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    app.dependency_overrides[get_settings] = lambda: current.model_copy(
        update={"monthly_token_budget_per_workspace": 1_000}
    )
    canvas = await _create_canvas(client, api_prefix, "Budgeted workspace")
    node = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Budget context",
        text="No provider call should be made.",
    )
    async with database.sessions() as session:
        session.add(
            UsageRecord(
                user_id=SYSTEM_USER_ID,
                workspace_id=uuid.UUID(canvas["workspaceId"]),
                operation="ai_execution",
                input_tokens=700,
                output_tokens=300,
            )
        )
        await session.commit()
    blocked = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={"instruction": "Answer", "selectedNodeIds": [node["id"]]},
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "workspace_token_budget_exhausted"
    async with database.sessions() as session:
        requests = list((await session.scalars(select(AIRequest))).all())
    assert requests == []
