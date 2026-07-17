from __future__ import annotations

from typing import Any, cast

import httpx

JsonObject = dict[str, Any]


async def _create_canvas(
    client: httpx.AsyncClient, prefix: str, name: str = "Project Vox"
) -> JsonObject:
    response = await client.post(f"{prefix}/canvases", json={"name": name})
    assert response.status_code == 201
    canvas = cast(JsonObject, response.json())
    assert str(canvas["createdAt"]).endswith("Z")
    return canvas


async def _create_node(
    client: httpx.AsyncClient,
    prefix: str,
    canvas_id: str,
    *,
    title: str,
    text: str,
    x: float = 10,
) -> JsonObject:
    response = await client.post(
        f"{prefix}/canvases/{canvas_id}/nodes",
        json={
            "type": "note",
            "title": title,
            "text": text,
            "position": {"x": x, "y": 20},
            "width": 300,
            "height": 220,
        },
    )
    assert response.status_code == 201
    return cast(JsonObject, response.json())


async def test_create_edit_save_and_restore_canvas_state(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix)
    node = await _create_node(client, api_prefix, canvas["id"], title="Launch plan", text="Draft")

    updated_response = await client.patch(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{node['id']}",
        json={
            "revision": node["revision"],
            "title": "Launch plan v2",
            "text": "Ship the contextual canvas",
            "position": {"x": 155, "y": -25},
            "width": 520,
            "height": 310,
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["revision"] == 1

    restored_response = await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")
    assert restored_response.status_code == 200
    restored = restored_response.json()
    assert restored["nodes"] == [updated]
    assert restored["edges"] == []
    assert restored["canvas"]["revision"] == 2

    stale = await client.patch(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{node['id']}",
        json={"revision": 0, "text": "stale edit"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "revision_conflict"


async def test_create_and_delete_directional_edge(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix)
    source = await _create_node(client, api_prefix, canvas["id"], title="Source", text="A")
    target = await _create_node(client, api_prefix, canvas["id"], title="Target", text="B", x=400)

    edge_response = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/edges",
        json={
            "sourceNodeId": source["id"],
            "targetNodeId": target["id"],
            "kind": "default",
            "label": "supports",
        },
    )
    assert edge_response.status_code == 201
    edge = edge_response.json()
    assert edge["sourceNodeId"] == source["id"]
    assert edge["targetNodeId"] == target["id"]

    snapshot = (await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")).json()
    assert [item["id"] for item in snapshot["edges"]] == [edge["id"]]

    deleted = await client.delete(
        f"{api_prefix}/canvases/{canvas['id']}/edges/{edge['id']}",
        params={"revision": edge["revision"]},
    )
    assert deleted.status_code == 204
    restored = (await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")).json()
    assert restored["edges"] == []


async def test_duplicate_and_delete_node(client: httpx.AsyncClient, api_prefix: str) -> None:
    canvas = await _create_canvas(client, api_prefix)
    node = await _create_node(client, api_prefix, canvas["id"], title="Original", text="Body")

    duplicate_response = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{node['id']}/duplicate",
        json={"revision": node["revision"]},
    )
    assert duplicate_response.status_code == 201
    duplicate = duplicate_response.json()
    assert duplicate["title"] == "Copy of Original"
    assert duplicate["position"] == {"x": 50.0, "y": 60.0}

    deleted = await client.delete(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{duplicate['id']}",
        params={"revision": duplicate["revision"]},
    )
    assert deleted.status_code == 204


async def test_invalid_graph_requests_are_rejected(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    invalid_canvas = await client.post(f"{api_prefix}/canvases", json={"name": "  "})
    assert invalid_canvas.status_code == 422

    first_canvas = await _create_canvas(client, api_prefix, "First")
    second_canvas = await _create_canvas(client, api_prefix, "Second")
    first_node = await _create_node(
        client, api_prefix, first_canvas["id"], title="First", text="one"
    )
    second_node = await _create_node(
        client, api_prefix, second_canvas["id"], title="Second", text="two"
    )

    self_edge = await client.post(
        f"{api_prefix}/canvases/{first_canvas['id']}/edges",
        json={"sourceNodeId": first_node["id"], "targetNodeId": first_node["id"]},
    )
    assert self_edge.status_code == 422

    cross_canvas = await client.post(
        f"{api_prefix}/canvases/{first_canvas['id']}/edges",
        json={"sourceNodeId": first_node["id"], "targetNodeId": second_node["id"]},
    )
    assert cross_canvas.status_code == 400
    assert cross_canvas.json()["code"] == "invalid_node_reference"
