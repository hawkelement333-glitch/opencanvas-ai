from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.api.dependencies import get_ai_provider
from opencanvas_api.db.models import AIRequest, AIResponse, CanvasNode, Edge
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
    assert requests[0].error == "Provider unavailable."
    assert response_count == 0
    assert node_count == 1
    assert edge_count == 0
