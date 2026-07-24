from __future__ import annotations

import httpx
from sqlalchemy import func, select

from opencanvas_api.db.models import CanvasNode, ControlledAgentApproval, ControlledAgentAuditEvent
from tests.test_canvas_api import _create_canvas, _create_node


async def test_reversible_proposal_is_server_owned_idempotent_and_review_only(
    client: httpx.AsyncClient, database, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Proposal canvas")
    route = f"{api_prefix}/workspaces/{canvas['workspaceId']}/agent-executions"
    payload = {
        "canvasId": canvas["id"],
        "action": "note.create",
        "title": "Proposed note",
        "text": "Preview only",
        "idempotencyKey": "reversible-proposal-001",
    }
    before = await _node_count(database)
    created = await client.post(f"{route}/reversible-proposals", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "note.create"
    assert body["duplicate"] is False
    assert await _node_count(database) == before

    duplicate = await client.post(f"{route}/reversible-proposals", json=payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["executionId"] == body["executionId"]
    assert duplicate.json()["duplicate"] is True
    conflict = await client.post(
        f"{route}/reversible-proposals", json={**payload, "title": "Changed preview"}
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"

    approved = await client.post(
        f"{route}/{body['executionId']}/reversible-proposal/approve",
        json={"planDigest": body["planDigest"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "ready"
    assert await _node_count(database) == before
    repeated = await client.post(
        f"{route}/{body['executionId']}/reversible-proposal/approve",
        json={"planDigest": body["planDigest"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    assert await _approval_and_audit_counts(database) == (1, 2)


async def test_reversible_proposal_rejects_digest_and_stale_note_revision(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Stale proposal canvas")
    node = await _create_node(client, api_prefix, canvas["id"], title="Note", text="Before")
    route = f"{api_prefix}/workspaces/{canvas['workspaceId']}/agent-executions"
    stale = await client.post(
        f"{route}/reversible-proposals",
        json={
            "canvasId": canvas["id"],
            "action": "note.update",
            "title": "After",
            "text": "After",
            "noteId": node["id"],
            "expectedRevision": node["revision"] + 1,
            "idempotencyKey": "reversible-stale-001",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_revision"

    created = await client.post(
        f"{route}/reversible-proposals",
        json={
            "canvasId": canvas["id"],
            "action": "note.update",
            "title": "After",
            "text": "After",
            "noteId": node["id"],
            "expectedRevision": node["revision"],
            "idempotencyKey": "reversible-update-001",
        },
    )
    assert created.status_code == 201, created.text
    mismatch = await client.post(
        f"{route}/{created.json()['executionId']}/reversible-proposal/approve",
        json={"planDigest": "f" * 64},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "proposal_digest_mismatch"


async def _node_count(database) -> int:
    async with database.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(CanvasNode)) or 0)


async def _approval_and_audit_counts(database) -> tuple[int, int]:
    async with database.sessions() as session:
        approvals = int(
            await session.scalar(select(func.count()).select_from(ControlledAgentApproval)) or 0
        )
        audit = int(
            await session.scalar(select(func.count()).select_from(ControlledAgentAuditEvent)) or 0
        )
        return approvals, audit
