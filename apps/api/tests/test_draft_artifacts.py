from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, func, select

from opencanvas_api.api.dependencies import get_current_principal
from opencanvas_api.db.models import (
    AIExecutionCitation,
    AIRequest,
    AIResponse,
    Canvas,
    CanvasNode,
    Citation,
    ControlledDraftArtifact,
    Edge,
    TraceEvent,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.grounded_draft import ControlledGroundedDraftService
from opencanvas_api.services.ai import MockAIProvider
from opencanvas_api.services.auth import Principal
from tests.agent_fixtures import NOW
from tests.test_agent_authority_preflight import request_for
from tests.test_agent_grounded_draft import _settings
from tests.test_agent_immutable_context import _seed_selected_context


async def generated(database):
    bundle, _, source, _, chunk = await _seed_selected_context(database)
    async with database.sessions() as session:
        result = await ControlledGroundedDraftService(
            session,
            provider=MockAIProvider(),
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        ).execute(
            authenticated_user_id=bundle.execution.user_id,
            request=request_for(
                bundle,
                source.canvas_id,
                instruction="What exact evidence was selected?",
                idempotency_key="explicit-artifact-save",
            ),
        )
    url = (
        f"/api/v1/workspaces/{bundle.execution.workspace_id}/agent-executions/"
        f"{result.execution_id}/artifact"
    )
    payload = {"canvasId": str(source.canvas_id), "position": {"x": 420, "y": 80}}
    return bundle, source, chunk, result, url, payload


async def original_evidence(database):
    async with database.sessions() as session:
        result = {}
        for model in (AIRequest, AIResponse, Citation, AIExecutionCitation, TraceEvent):
            rows = (await session.execute(select(model.__table__))).all()
            result[model.__tablename__] = sorted([tuple(map(str, row)) for row in rows])
        return result


async def test_explicit_save_edit_reload_duplicate_and_delete_preserve_original_evidence(
    client: httpx.AsyncClient,
    database: Database,
):
    _, source, _, draft, url, payload = await generated(database)
    before = await original_evidence(database)
    snapshot_url = f"/api/v1/canvases/{source.canvas_id}/snapshot"
    initial = (await client.get(snapshot_url)).json()
    assert len(initial["nodes"]) == 1  # Generation does not materialize a node.
    saved = await client.post(url, json=payload)
    assert saved.status_code == 200, saved.text
    node = saved.json()
    assert node["text"] == draft.text
    assert node["citations"] == []  # Original citations never ground editable content.
    provenance = node["draftProvenance"]
    assert provenance["originalText"] == draft.text
    assert provenance["traceId"] == str(draft.trace_id)
    assert provenance["edited"] is False and len(provenance["citations"]) == 1
    node_url = f"/api/v1/canvases/{source.canvas_id}/nodes/{node['id']}"
    edited = await client.patch(node_url, json={"revision": node["revision"], "text": "User claim"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["draftProvenance"]["edited"] is True
    duplicate = await client.post(url, json={**payload, "position": {"x": 999, "y": 999}})
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == node["id"]
    assert duplicate.json()["text"] == "User claim"
    assert duplicate.json()["position"] == payload["position"]
    snapshot = (await client.get(snapshot_url)).json()
    restored = next(item for item in snapshot["nodes"] if item["id"] == node["id"])
    assert restored["text"] == "User claim"
    assert restored["draftProvenance"] == edited.json()["draftProvenance"]
    assert len(snapshot["edges"]) == 1
    assert snapshot["edges"][0]["kind"] == "generated_from"
    assert await original_evidence(database) == before
    deleted = await client.delete(node_url, params={"revision": edited.json()["revision"]})
    assert deleted.status_code == 204
    rejected = await client.post(url, json=payload)
    assert rejected.status_code == 409 and rejected.json()["code"] == "draft_artifact_deleted"
    assert await original_evidence(database) == before
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(ControlledDraftArtifact.execution_id))) == 1


async def test_save_rejects_other_canvas_workspace_actor_and_uncompleted_execution(
    client: httpx.AsyncClient,
    database: Database,
    app: FastAPI,
):
    bundle, _, _, draft, url, payload = await generated(database)
    assert (
        await client.post(url, json={**payload, "canvasId": str(uuid.uuid4())})
    ).status_code == 404
    foreign = url.replace(str(bundle.execution.workspace_id), str(uuid.uuid4()))
    assert (await client.post(foreign, json=payload)).status_code == 404
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=uuid.uuid4(),
        email="other@example.test",
        display_name="Other",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    assert (await client.post(url, json=payload)).status_code == 404
    app.dependency_overrides.pop(get_current_principal)
    async with database.sessions() as session:
        request = await session.get(AIRequest, draft.execution_id)
        request.status = "pending"
        await session.commit()
    assert (await client.post(url, json=payload)).status_code == 409
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(ControlledDraftArtifact.execution_id))) == 0


async def test_identity_failure_rolls_back_node_edges_and_canvas_revision(
    client: httpx.AsyncClient,
    database: Database,
):
    _, source, _, _, url, payload = await generated(database)
    async with database.sessions() as session:
        revision = (await session.get(Canvas, source.canvas_id)).revision
    before = await original_evidence(database)

    def fail_identity(*args):
        raise RuntimeError("injected artifact identity write failure")

    event.listen(ControlledDraftArtifact, "before_insert", fail_identity)
    try:
        with pytest.raises(RuntimeError, match="injected artifact"):
            await client.post(url, json=payload)
    finally:
        event.remove(ControlledDraftArtifact, "before_insert", fail_identity)
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(CanvasNode.id))) == 1
        assert await session.scalar(select(func.count(Edge.id))) == 0
        assert await session.scalar(select(func.count(ControlledDraftArtifact.execution_id))) == 0
        assert (await session.get(Canvas, source.canvas_id)).revision == revision
    assert await original_evidence(database) == before
    assert (await client.post(url, json=payload)).status_code == 200


async def test_deleted_source_is_not_navigable_from_saved_provenance(
    client: httpx.AsyncClient,
    database: Database,
):
    _, source, chunk, _, url, payload = await generated(database)
    saved = (await client.post(url, json=payload)).json()
    before = await original_evidence(database)
    deleted = await client.delete(f"/api/v1/documents/{chunk.document_id}")
    assert deleted.status_code == 204, deleted.text
    snapshot = (await client.get(f"/api/v1/canvases/{source.canvas_id}/snapshot")).json()
    node = next(item for item in snapshot["nodes"] if item["id"] == saved["id"])
    assert node["draftProvenance"]["citations"] == []
    assert node["draftProvenance"]["originalText"] == saved["text"]
    after = await original_evidence(database)
    # Live navigable citations disappear with their source; immutable execution
    # citation snapshots and original generated response/Trace remain unchanged.
    assert after.pop("citations") == []
    before.pop("citations")
    assert before["ai_execution_citations"]
    assert after == before
