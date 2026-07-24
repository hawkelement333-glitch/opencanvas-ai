from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    CanvasNode,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentCapabilityGrant,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteRollbackApproval,
    ControlledAgentReversibleWriteRollbackEvidence,
    TraceEvent,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import (
    Capability,
    CapabilityGrant,
    ResourceKind,
    ResourceScope,
    contract_digest,
)
from opencanvas_api.services.agents.reversible_write_effects import ReversibleWriteEffectService
from opencanvas_api.services.agents.reversible_write_rollback_approvals import (
    ReversibleWriteRollbackApprovalService,
)
from opencanvas_api.services.agents.reversible_writes import (
    ROLLBACK_APPROVAL_TTL,
    RollbackApprovalDigestInput,
    authoritative_absence_digest,
    rollback_approval_digest,
)
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
        evidence = await session.scalar(select(ControlledAgentReversibleWriteRollbackEvidence))
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
    assert evidence is not None
    assert evidence.effect_id == effect.effect_id
    assert (evidence.user_id, evidence.workspace_id, evidence.canvas_id, evidence.note_id) == (
        effect.user_id,
        effect.workspace_id,
        effect.canvas_id,
        updated.id,
    )
    assert evidence.before_state == {"text": "Before text", "title": "Before"}
    assert (evidence.pre_effect_revision, evidence.post_effect_revision) == (0, 1)
    assert evidence.before_digest == _state_digest(evidence.before_state)
    assert evidence.after_digest == _state_digest(
        {"text": "Applied text", "title": "Applied title"}
    )
    assert effect.before_digest == evidence.before_digest
    assert effect.after_digest == evidence.after_digest


async def test_exact_duplicate_update_returns_one_effect_and_one_rollback_evidence(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Rollback duplicate canvas")
    node = await _create_node(client, api_prefix, canvas["id"], title="Before", text="Before text")
    _, proposal, route = await _approved_proposal(
        client, api_prefix, action="note.update", node=node, canvas=canvas
    )
    applied = await _effect(client, route, proposal)
    duplicate = await _effect(client, route, proposal)
    assert applied.status_code == duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    async with database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackEvidence)
            )
            == 1
        )
        persisted = await session.get(CanvasNode, uuid.UUID(node["id"]))
    assert persisted is not None and (persisted.title, persisted.text, persisted.revision) == (
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
    canvas = await _create_canvas(client, api_prefix, "Rollback failure canvas")
    node = await _create_node(client, api_prefix, canvas["id"], title="Before", text="Before text")
    _, proposal, _ = await _approved_proposal(
        client, api_prefix, action="note.update", node=node, canvas=canvas
    )

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
        persisted = await session.get(CanvasNode, uuid.UUID(node["id"]))
        assert persisted is not None and (persisted.title, persisted.text, persisted.revision) == (
            "Before",
            "Before text",
            0,
        )
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
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackEvidence)
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
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackEvidence)
            )
            == 0
        )


async def _install_rollback_grant(
    database: Database, *, effect_id: uuid.UUID, capability: Capability
) -> None:
    """Install a test-only rollback grant without changing the forward-effect contract."""

    async with database.sessions() as session:
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        assert effect is not None
        row = await session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id
            )
        )
        assert row is not None
        grant = CapabilityGrant.model_validate(row.payload).model_copy(
            update={
                "capabilities": (capability,),
                "resources": (
                    ResourceScope(
                        kind=ResourceKind.NODE,
                        resource_id=effect.resulting_resource_id,
                        version=effect.resulting_revision,
                    ),
                ),
                "issued_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
            }
        )
        await session.execute(
            update(ControlledAgentCapabilityGrant)
            .where(ControlledAgentCapabilityGrant.grant_id == row.grant_id)
            .values(
                payload=grant.model_dump(mode="json"),
                payload_digest=contract_digest(grant),
                issued_at=grant.issued_at,
                expires_at=grant.expires_at,
            )
        )
        await session.commit()


@pytest.mark.parametrize(
    ("action", "capability", "target_kind"),
    [
        ("note.create", Capability.CANVAS_NOTE_CREATE_ROLLBACK, "authoritative_absence"),
        ("note.update", Capability.CANVAS_NOTE_UPDATE_ROLLBACK, "exact_prior_state"),
    ],
)
async def test_rollback_review_derives_eligible_authority_from_persisted_effect(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    action: str,
    capability: Capability,
    target_kind: str,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Rollback review canvas")
    node = None
    if action == "note.update":
        node = await _create_node(
            client, api_prefix, canvas["id"], title="Before", text="Before text"
        )
    _, proposal, route = await _approved_proposal(
        client, api_prefix, action=action, node=node, canvas=canvas
    )
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    await _install_rollback_grant(database, effect_id=effect_id, capability=capability)

    review = await client.get(
        f"{route}/canvases/{canvas['id']}/reversible-effects/{effect_id}/rollback-review"
    )
    assert review.status_code == 200, review.text
    body = review.json()
    assert body == {
        "effectId": str(effect_id),
        "forwardAction": action,
        "noteId": applied.json()["noteId"],
        "effectRevision": applied.json()["revision"],
        "currentRevision": applied.json()["revision"],
        "rollbackAction": f"{action}.rollback",
        "rollbackTargetKind": target_kind,
        "requiredCapability": capability.value,
        "eligible": True,
        "approvalRequired": True,
        "denialReason": None,
        "conflict": False,
    }
    assert "beforeState" not in body and "grant" not in body and "digest" not in body


async def test_rollback_review_rejects_forward_capability_without_mutation(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    before = applied.json().copy()

    review = await client.get(
        f"{route}/canvases/{canvas['id']}/reversible-effects/{effect_id}/rollback-review"
    )
    assert review.status_code == 200, review.text
    assert review.json()["eligible"] is False
    assert review.json()["denialReason"] == "capability_missing"
    async with database.sessions() as session:
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        node = await session.get(CanvasNode, uuid.UUID(before["noteId"]))
    assert effect is not None and node is not None and node.revision == before["revision"]


@pytest.mark.parametrize(
    ("action", "capability"),
    [
        ("note.create", Capability.CANVAS_NOTE_CREATE_ROLLBACK),
        ("note.update", Capability.CANVAS_NOTE_UPDATE_ROLLBACK),
    ],
)
async def test_successful_rollback_approval_issuance(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    action: str,
    capability: Capability,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Rollback approval canvas")
    node = None
    if action == "note.update":
        node = await _create_node(
            client, api_prefix, canvas["id"], title="Before", text="Before text"
        )
    _, proposal, route = await _approved_proposal(
        client, api_prefix, action=action, node=node, canvas=canvas
    )
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    await _install_rollback_grant(database, effect_id=effect_id, capability=capability)
    key = f"rollback-approval-{uuid.uuid4().hex}"
    async with database.sessions() as session:
        issued = await ReversibleWriteRollbackApprovalService(session).issue(
            authenticated_user_id=SYSTEM_USER_ID,
            workspace_id=uuid.UUID(canvas["workspaceId"]),
            canvas_id=uuid.UUID(canvas["id"]),
            effect_id=effect_id,
            idempotency_key=key,
        )
        await session.commit()
    async with database.sessions() as session:
        approval = await session.get(
            ControlledAgentReversibleWriteRollbackApproval, issued.approval.rollback_approval_id
        )
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        grant = (
            await session.scalar(
                select(ControlledAgentCapabilityGrant).where(
                    ControlledAgentCapabilityGrant.execution_id == effect.execution_id
                )
            )
            if effect
            else None
        )
        evidence = await session.scalar(
            select(ControlledAgentReversibleWriteRollbackEvidence).where(
                ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect_id
            )
        )
    assert approval is not None and effect is not None and grant is not None
    assert approval.grant_id == grant.grant_id
    assert approval.expires_at - approval.created_at == ROLLBACK_APPROVAL_TTL
    if action == "note.create":
        assert approval.expected_current_revision == 0
        assert approval.rollback_target_kind == "authoritative_absence"
        assert approval.rollback_target_digest == authoritative_absence_digest()
        assert approval.rollback_evidence_id is None
    else:
        assert approval.expected_current_revision > 0
        assert approval.rollback_target_kind == "exact_prior_state"
        assert evidence is not None and approval.rollback_evidence_id == evidence.evidence_id
        assert approval.rollback_target_digest == evidence.before_digest
    digest = rollback_approval_digest(
        RollbackApprovalDigestInput(
            execution_id=approval.execution_id,
            user_id=approval.user_id,
            workspace_id=approval.workspace_id,
            canvas_id=approval.canvas_id,
            note_id=approval.note_id,
            proposal_id=approval.proposal_id,
            effect_id=approval.effect_id,
            forward_action=approval.forward_action,
            rollback_action=approval.rollback_action,
            original_plan_digest=approval.original_plan_digest,
            expected_current_revision=approval.expected_current_revision,
            effect_after_state_digest=approval.effect_after_state_digest,
            rollback_target_kind=approval.rollback_target_kind,
            rollback_target_digest=approval.rollback_target_digest,
            rollback_evidence_id=approval.rollback_evidence_id,
            grant_id=approval.grant_id,
            scoped_idempotency_key=approval.scoped_idempotency_key,
            expires_at=approval.expires_at.replace(tzinfo=UTC)
            if approval.expires_at.tzinfo is None
            else approval.expires_at,
        )
    )
    assert approval.approval_digest == digest


async def test_rollback_approval_exact_duplicate_returns_one_row(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    effect_id = uuid.UUID(applied.json()["effectId"])
    await _install_rollback_grant(
        database, effect_id=effect_id, capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK
    )
    key = f"rollback-duplicate-{uuid.uuid4().hex}"
    async with database.sessions() as session:
        service = ReversibleWriteRollbackApprovalService(session)
        first = await service.issue(
            authenticated_user_id=SYSTEM_USER_ID,
            workspace_id=uuid.UUID(canvas["workspaceId"]),
            canvas_id=uuid.UUID(canvas["id"]),
            effect_id=effect_id,
            idempotency_key=key,
        )
        await session.commit()
    async with database.sessions() as session:
        duplicate = await ReversibleWriteRollbackApprovalService(session).issue(
            authenticated_user_id=SYSTEM_USER_ID,
            workspace_id=uuid.UUID(canvas["workspaceId"]),
            canvas_id=uuid.UUID(canvas["id"]),
            effect_id=effect_id,
            idempotency_key=key,
        )
        assert duplicate.duplicate is True
        assert duplicate.approval.rollback_approval_id == first.approval.rollback_approval_id
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == 1
        )


def _state_digest(state: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
