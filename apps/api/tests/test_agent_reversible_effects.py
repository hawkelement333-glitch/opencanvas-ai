from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    CanvasNode,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentReversibleWriteEffect,
    TraceEvent,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.reversible_write_effects import ReversibleWriteEffectService
from tests.test_canvas_api import _create_canvas, _create_node


async def _approved_proposal(
    client: httpx.AsyncClient,
    api_prefix: str,
    *,
    action: str = "note.create",
    node: dict[str, Any] | None = None,
    canvas: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    canvas = canvas or await _create_canvas(client, api_prefix, "Atomic effect canvas")
    route = f"{api_prefix}/workspaces/{canvas['workspaceId']}/agent-executions"
    payload: dict[str, Any] = {
        "canvasId": canvas["id"],
        "action": action,
        "title": "Applied title",
        "text": "Applied text",
        "idempotencyKey": f"effect-{uuid.uuid4().hex}",
    }
    if node is not None:
        payload.update(noteId=node["id"], expectedRevision=node["revision"])
    prepared = await client.post(f"{route}/reversible-proposals", json=payload)
    assert prepared.status_code == 201, prepared.text
    proposal = prepared.json()
    proposal["_idempotencyKey"] = payload["idempotencyKey"]
    approved = await client.post(
        f"{route}/{proposal['executionId']}/reversible-proposal/approve",
        json={"planDigest": proposal["planDigest"]},
    )
    assert approved.status_code == 200, approved.text
    return canvas, proposal, route


async def _effect(
    client: httpx.AsyncClient, route: str, proposal: dict[str, Any], *, key: str | None = None
) -> httpx.Response:
    return await client.post(
        f"{route}/{proposal['executionId']}/reversible-effect",
        json={"idempotencyKey": key or proposal["_idempotencyKey"]},
    )


async def test_approved_creation_is_atomic_idempotent_and_traced(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    body = applied.json()
    duplicate = await _effect(client, route, proposal)
    assert duplicate.status_code == 200
    assert duplicate.json() == {**body, "duplicate": True}

    async with database.sessions() as session:
        node = await session.get(CanvasNode, uuid.UUID(body["noteId"]))
        effects = int(
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteEffect)
            )
            or 0
        )
        consumptions = int(
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            or 0
        )
        audit = await session.scalar(
            select(ControlledAgentAuditEvent).where(
                ControlledAgentAuditEvent.trace_id == uuid.UUID(body["traceId"])
            )
        )
        trace = (
            await session.scalars(
                select(TraceEvent).where(TraceEvent.trace_id == uuid.UUID(body["traceId"]))
            )
        ).all()
    assert node is not None and (node.title, node.text, node.revision) == (
        "Applied title",
        "Applied text",
        0,
    )
    assert effects == 1
    assert consumptions == 1
    assert audit is not None
    assert {event.status for event in trace} == {"started", "succeeded"}
    assert canvas["id"]


async def test_approved_update_uses_exact_revision_and_preserves_before_after_evidence(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Atomic update canvas")
    node = await _create_node(client, api_prefix, canvas["id"], title="Before", text="Before text")
    _, proposal, route = await _approved_proposal(
        client, api_prefix, action="note.update", node=node, canvas=canvas
    )
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    async with database.sessions() as session:
        effect = await session.scalar(select(ControlledAgentReversibleWriteEffect))
        updated = await session.get(CanvasNode, uuid.UUID(applied.json()["noteId"]))
    assert (
        effect is not None
        and effect.before_digest is not None
        and effect.after_digest != effect.before_digest
    )
    assert updated is not None and (updated.title, updated.text, updated.revision) == (
        "Applied title",
        "Applied text",
        1,
    )


async def test_effect_rejects_conflicting_key_and_missing_execution_without_mutation(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    _, proposal, route = await _approved_proposal(client, api_prefix)
    bad = await _effect(client, route, proposal, key="different-effect-key")
    missing = await client.post(
        f"{route}/{uuid.uuid4()}/reversible-effect", json={"idempotencyKey": "missing-effect-key"}
    )
    assert bad.status_code == 409 and bad.json()["code"] == "idempotency_conflict"
    assert missing.status_code == 404 and missing.json()["code"] == "proposal_not_found"
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CanvasNode)) == 0
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )


async def test_failure_after_mutation_rolls_back_every_success_record(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, proposal, _ = await _approved_proposal(client, api_prefix)

    async def fail_after_mutation() -> None:
        raise RuntimeError("injected effect failure")

    async with database.sessions() as session:
        with pytest.raises(RuntimeError, match="injected effect failure"):
            await ReversibleWriteEffectService(session, after_mutation=fail_after_mutation).apply(
                authenticated_user_id=SYSTEM_USER_ID,
                workspace_id=uuid.UUID(canvas["workspaceId"]),
                execution_id=uuid.UUID(proposal["executionId"]),
                idempotency_key=str(proposal["_idempotencyKey"]),
            )
        await session.rollback()
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CanvasNode)) == 0
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteEffect)
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(TraceEvent)) == 0


async def test_stale_update_conflict_leaves_approval_and_note_unchanged(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Atomic stale canvas")
    node = await _create_node(client, api_prefix, canvas["id"], title="Before", text="Before text")
    _, proposal, route = await _approved_proposal(
        client, api_prefix, action="note.update", node=node, canvas=canvas
    )
    changed = await client.patch(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{node['id']}",
        json={"revision": node["revision"], "text": "Concurrent edit"},
    )
    assert changed.status_code == 200
    denied = await _effect(client, route, proposal)
    assert denied.status_code == 409
    async with database.sessions() as session:
        persisted = await session.get(CanvasNode, uuid.UUID(node["id"]))
        assert persisted is not None and persisted.text == "Concurrent edit"
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentApprovalConsumption)
            )
            == 0
        )
