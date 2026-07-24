from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select, text, update

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    CanvasNode,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentCapabilityGrant,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteRollbackApproval,
    ControlledAgentReversibleWriteRollbackEvidence,
    ControlledAgentReversibleWriteRollbackResult,
    TraceEvent,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import (
    Capability,
    CapabilityGrant,
    ResourceKind,
    ResourceScope,
    RevocationRecord,
    contract_digest,
)
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
from opencanvas_api.services.agents.reversible_write_effects import ReversibleWriteEffectService
from opencanvas_api.services.agents.reversible_write_rollback_approvals import (
    ReversibleWriteRollbackApprovalService,
    RollbackApprovalError,
)
from opencanvas_api.services.agents.reversible_writes import (
    ROLLBACK_APPROVAL_TTL,
    RollbackApprovalDigestInput,
    authoritative_absence_digest,
    rollback_approval_digest,
)
from tests.test_auth_authorization import _csrf, _enable_real_auth, _sign_up
from tests.test_canvas_api import _create_canvas, _create_node


async def _approved_proposal(
    client: httpx.AsyncClient,
    api_prefix: str,
    *,
    action: str = "note.create",
    node: dict[str, Any] | None = None,
    canvas: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
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
    prepared = await client.post(
        f"{route}/reversible-proposals", json=payload, headers=headers
    )
    assert prepared.status_code == 201, prepared.text
    proposal = prepared.json()
    proposal["_idempotencyKey"] = payload["idempotencyKey"]
    approved = await client.post(
        f"{route}/{proposal['executionId']}/reversible-proposal/approve",
        json={"planDigest": proposal["planDigest"]},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    return canvas, proposal, route


async def _effect(
    client: httpx.AsyncClient,
    route: str,
    proposal: dict[str, Any],
    *,
    key: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        f"{route}/{proposal['executionId']}/reversible-effect",
        json={"idempotencyKey": key or proposal["_idempotencyKey"]},
        headers=headers,
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


async def _prepared_rollback_effect(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    *,
    action: str = "note.create",
    capability: Capability | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, httpx.Response, uuid.UUID]:
    canvas = await _create_canvas(client, api_prefix, f"Rollback {action} validation")
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
    if capability is not None:
        await _install_rollback_grant(
            database, effect_id=effect_id, capability=capability
        )
    return canvas, proposal, route, applied, effect_id


async def _rollback_issue_error(
    database: Database,
    *,
    canvas: dict[str, Any],
    effect_id: uuid.UUID,
    expected_approvals: int = 0,
    expected_results: int = 0,
) -> RollbackApprovalError:
    async with database.sessions() as session:
        with pytest.raises(RollbackApprovalError) as caught:
            await ReversibleWriteRollbackApprovalService(session).issue(
                authenticated_user_id=SYSTEM_USER_ID,
                workspace_id=uuid.UUID(canvas["workspaceId"]),
                canvas_id=uuid.UUID(canvas["id"]),
                effect_id=effect_id,
                idempotency_key=f"rollback-denied-{uuid.uuid4().hex}",
            )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == expected_approvals
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackResult)
            )
            == expected_results
        )
    return caught.value


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


async def test_rollback_approval_replay_fails_closed_after_note_state_changes(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    note_id = uuid.UUID(applied.json()["noteId"])
    await _install_rollback_grant(
        database, effect_id=effect_id, capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK
    )
    key = f"rollback-authority-change-{uuid.uuid4().hex}"

    async with database.sessions() as session:
        first = await ReversibleWriteRollbackApprovalService(session).issue(
            authenticated_user_id=SYSTEM_USER_ID,
            workspace_id=uuid.UUID(canvas["workspaceId"]),
            canvas_id=uuid.UUID(canvas["id"]),
            effect_id=effect_id,
            idempotency_key=key,
        )
        await session.commit()

    changed = await client.patch(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{note_id}",
        json={"revision": applied.json()["revision"], "text": "Authoritative concurrent edit"},
    )
    assert changed.status_code == 200, changed.text
    changed_note = changed.json()

    async with database.sessions() as session:
        original = await session.get(
            ControlledAgentReversibleWriteRollbackApproval,
            first.approval.rollback_approval_id,
        )
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        assert effect is not None
        grant = await session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id
            )
        )
        assert original is not None and grant is not None
        original_identity = (
            original.rollback_approval_id,
            original.approval_digest,
            original.expires_at,
        )
        effect_state = (
            effect.effect_id,
            effect.after_digest,
            effect.resulting_revision,
        )
        grant_state = (grant.grant_id, grant.payload_digest, grant.expires_at)

    async with database.sessions() as session:
        with pytest.raises(RollbackApprovalError) as caught:
            await ReversibleWriteRollbackApprovalService(session).issue(
                authenticated_user_id=SYSTEM_USER_ID,
                workspace_id=uuid.UUID(canvas["workspaceId"]),
                canvas_id=uuid.UUID(canvas["id"]),
                effect_id=effect_id,
                idempotency_key=key,
            )
        assert caught.value.code == "revision_conflict"
        assert caught.value.message == "Rollback is not eligible."
        assert "sql" not in caught.value.message.lower()
        assert "traceback" not in caught.value.message.lower()

    async with database.sessions() as session:
        original = await session.get(
            ControlledAgentReversibleWriteRollbackApproval,
            first.approval.rollback_approval_id,
        )
        note = await session.get(CanvasNode, note_id)
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        assert effect is not None
        grant = await session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id
            )
        )
        assert original is not None
        assert note is not None
        assert grant is not None
        assert (
            original.rollback_approval_id,
            original.approval_digest,
            original.expires_at,
        ) == original_identity
        assert (note.revision, note.title, note.text) == (
            changed_note["revision"],
            changed_note["title"],
            changed_note["text"],
        )
        assert (effect.effect_id, effect.after_digest, effect.resulting_revision) == effect_state
        assert (grant.grant_id, grant.payload_digest, grant.expires_at) == grant_state
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackResult)
            )
            == 0
        )


async def test_rollback_approval_expired_replay_fails_closed_without_replacement(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    await _install_rollback_grant(
        database, effect_id=effect_id, capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK
    )
    key = f"rollback-expired-replay-{uuid.uuid4().hex}"

    async with database.sessions() as session:
        first = await ReversibleWriteRollbackApprovalService(session).issue(
            authenticated_user_id=SYSTEM_USER_ID,
            workspace_id=uuid.UUID(canvas["workspaceId"]),
            canvas_id=uuid.UUID(canvas["id"]),
            effect_id=effect_id,
            idempotency_key=key,
        )
        await session.commit()

    async with database.sessions() as session:
        original = await session.get(
            ControlledAgentReversibleWriteRollbackApproval,
            first.approval.rollback_approval_id,
        )
        note = await session.get(CanvasNode, uuid.UUID(applied.json()["noteId"]))
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        assert effect is not None
        evidence = await session.scalar(
            select(ControlledAgentReversibleWriteRollbackEvidence).where(
                ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect_id
            )
        )
        grant = await session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id
            )
        )
        assert original is not None and note is not None and grant is not None
        original_expiration = (
            original.expires_at.replace(tzinfo=UTC)
            if original.expires_at.tzinfo is None
            else original.expires_at
        )
        original_identity = (
            original.rollback_approval_id,
            original.approval_digest,
            original.expires_at,
        )
        note_state = (note.revision, note.title, note.text)
        effect_state = (effect.effect_id, effect.after_digest, effect.resulting_revision)
        evidence_id = evidence.evidence_id if evidence is not None else None
        grant_state = (grant.grant_id, grant.payload_digest, grant.expires_at)

    async with database.sessions() as session:
        with pytest.raises(RollbackApprovalError) as caught:
            await ReversibleWriteRollbackApprovalService(
                session, now=original_expiration + timedelta(seconds=1)
            ).issue(
                authenticated_user_id=SYSTEM_USER_ID,
                workspace_id=uuid.UUID(canvas["workspaceId"]),
                canvas_id=uuid.UUID(canvas["id"]),
                effect_id=effect_id,
                idempotency_key=key,
            )
        assert caught.value.code == "approval_expired"
        assert caught.value.message == "Rollback approval has expired."
        assert "sql" not in caught.value.message.lower()
        assert "traceback" not in caught.value.message.lower()

    async with database.sessions() as session:
        original = await session.get(
            ControlledAgentReversibleWriteRollbackApproval,
            first.approval.rollback_approval_id,
        )
        note = await session.get(CanvasNode, uuid.UUID(applied.json()["noteId"]))
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        assert effect is not None
        evidence = await session.scalar(
            select(ControlledAgentReversibleWriteRollbackEvidence).where(
                ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect_id
            )
        )
        grant = await session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id
            )
        )
        assert original is not None and note is not None and grant is not None
        assert (
            original.rollback_approval_id,
            original.approval_digest,
            original.expires_at,
        ) == original_identity
        assert (note.revision, note.title, note.text) == note_state
        assert (effect.effect_id, effect.after_digest, effect.resulting_revision) == effect_state
        assert (evidence.evidence_id if evidence is not None else None) == evidence_id
        assert (grant.grant_id, grant.payload_digest, grant.expires_at) == grant_state
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackResult)
            )
            == 0
        )


@pytest.mark.parametrize("scope_field", ["user", "workspace", "canvas"])
async def test_rollback_approval_rejects_cross_scope_issuance(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    scope_field: str,
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    await _install_rollback_grant(
        database, effect_id=effect_id, capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK
    )
    request_scope = {
        "authenticated_user_id": SYSTEM_USER_ID,
        "workspace_id": uuid.UUID(canvas["workspaceId"]),
        "canvas_id": uuid.UUID(canvas["id"]),
    }
    request_scope[
        {
            "user": "authenticated_user_id",
            "workspace": "workspace_id",
            "canvas": "canvas_id",
        }[scope_field]
    ] = uuid.uuid4()

    async with database.sessions() as session:
        with pytest.raises(RollbackApprovalError) as caught:
            await ReversibleWriteRollbackApprovalService(session).issue(
                **request_scope,
                effect_id=effect_id,
                idempotency_key=f"rollback-cross-scope-{uuid.uuid4().hex}",
            )
        assert caught.value.code == "scope_mismatch"
        assert caught.value.message == "Rollback is not eligible."
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackResult)
            )
            == 0
        )


@pytest.mark.parametrize("grant_scope_field", ["execution_id", "user_id", "workspace_id"])
async def test_rollback_approval_rejects_wrong_grant_scope(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    grant_scope_field: str,
) -> None:
    canvas, proposal, route = await _approved_proposal(client, api_prefix)
    applied = await _effect(client, route, proposal)
    assert applied.status_code == 200, applied.text
    effect_id = uuid.UUID(applied.json()["effectId"])
    await _install_rollback_grant(
        database, effect_id=effect_id, capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK
    )
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
            update={grant_scope_field: uuid.uuid4()}
        )
        await session.execute(
            update(ControlledAgentCapabilityGrant)
            .where(ControlledAgentCapabilityGrant.grant_id == row.grant_id)
            .values(
                payload=grant.model_dump(mode="json"),
                payload_digest=contract_digest(grant),
            )
        )
        await session.commit()

    async with database.sessions() as session:
        with pytest.raises(RollbackApprovalError) as caught:
            await ReversibleWriteRollbackApprovalService(session).issue(
                authenticated_user_id=SYSTEM_USER_ID,
                workspace_id=uuid.UUID(canvas["workspaceId"]),
                canvas_id=uuid.UUID(canvas["id"]),
                effect_id=effect_id,
                idempotency_key=f"rollback-wrong-grant-{uuid.uuid4().hex}",
            )
        assert caught.value.code == "grant_scope_mismatch"
        assert caught.value.message == "Rollback is not eligible."
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == 0
        )


@pytest.mark.security
async def test_rollback_approval_api_enforces_authentication_csrf_and_scope(
    app: FastAPI, database: Database, api_prefix: str
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as owner:
        owner_session = await _sign_up(
            owner,
            api_prefix,
            email="rollback-owner@example.test",
            display_name="Rollback Owner",
        )
        headers = _csrf(owner_session)
        workspace = cast(
            dict[str, Any], (await owner.get(f"{api_prefix}/workspaces")).json()[0]
        )
        canvas_response = await owner.post(
            f"{api_prefix}/canvases",
            json={"name": "Rollback API canvas", "workspaceId": workspace["id"]},
            headers=headers,
        )
        assert canvas_response.status_code == 201, canvas_response.text
        canvas = cast(dict[str, Any], canvas_response.json())
        _, proposal, route = await _approved_proposal(
            owner, api_prefix, canvas=canvas, headers=headers
        )
        applied = await _effect(owner, route, proposal, headers=headers)
        assert applied.status_code == 200, applied.text
        effect_id = uuid.UUID(applied.json()["effectId"])
        await _install_rollback_grant(
            database,
            effect_id=effect_id,
            capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK,
        )
        endpoint = (
            f"{route}/canvases/{canvas['id']}/reversible-effects/"
            f"{effect_id}/rollback-approval"
        )

        missing = await owner.post(endpoint, json={"idempotencyKey": "missing-csrf-key"})
        invalid = await owner.post(
            endpoint,
            json={"idempotencyKey": "invalid-csrf-key"},
            headers={"X-CSRF-Token": "invalid"},
        )
        assert missing.status_code == invalid.status_code == 403
        assert missing.json()["code"] == invalid.json()["code"] == "csrf_validation_failed"

        valid = await owner.post(
            endpoint,
            json={"idempotencyKey": "valid-csrf-key"},
            headers=headers,
        )
        assert valid.status_code == 200, valid.text
        assert valid.json()["effectId"] == str(effect_id)

        inaccessible_canvas = await owner.post(
            endpoint.replace(str(canvas["id"]), str(uuid.uuid4())),
            json={"idempotencyKey": "wrong-canvas-key"},
            headers=headers,
        )
        inaccessible_workspace = await owner.post(
            endpoint.replace(str(workspace["id"]), str(uuid.uuid4())),
            json={"idempotencyKey": "wrong-workspace-key"},
            headers=headers,
        )
        for inaccessible in (inaccessible_canvas, inaccessible_workspace):
            assert inaccessible.status_code == 409
            assert inaccessible.json() == {
                "code": "scope_mismatch",
                "detail": "Rollback is not eligible.",
            }

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as anonymous:
            unauthenticated = await anonymous.post(
                endpoint,
                json={"idempotencyKey": "unauthenticated-key"},
                headers=headers,
            )
        assert unauthenticated.status_code == 401
        for response in (
            missing,
            invalid,
            inaccessible_canvas,
            inaccessible_workspace,
            unauthenticated,
        ):
            serialized = response.text.lower()
            assert "traceback" not in serialized
            assert "sql" not in serialized
            assert "database" not in serialized


@pytest.mark.parametrize("changed_field", ["revision", "title", "text", "state_digest"])
async def test_rollback_approval_revalidates_current_note_state(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    changed_field: str,
) -> None:
    canvas, _, _, applied, effect_id = await _prepared_rollback_effect(
        client,
        database,
        api_prefix,
        capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK,
    )
    note_id = uuid.UUID(applied.json()["noteId"])
    if changed_field == "state_digest":
        async with database.sessions() as session:
            await session.execute(
                update(CanvasNode)
                .where(CanvasNode.id == note_id)
                .values(text="Digest-only test mutation")
            )
            await session.commit()
        expected_code = "state_conflict"
    else:
        payload: dict[str, object] = {"revision": applied.json()["revision"]}
        if changed_field == "revision":
            payload["text"] = "Revision changed"
        elif changed_field == "title":
            payload["title"] = "Title changed"
        else:
            payload["text"] = "Text changed"
        changed = await client.patch(
            f"{api_prefix}/canvases/{canvas['id']}/nodes/{note_id}",
            json=payload,
        )
        assert changed.status_code == 200, changed.text
        expected_code = "revision_conflict"

    error = await _rollback_issue_error(database, canvas=canvas, effect_id=effect_id)
    assert error.code == expected_code
    assert error.message == "Rollback is not eligible."


@pytest.mark.parametrize(
    ("evidence_change", "expected_code"),
    [
        ("missing", "rollback_evidence_missing"),
        ("before_state", "rollback_evidence_invalid"),
        ("before_digest", "rollback_evidence_invalid"),
        ("after_digest", "rollback_evidence_invalid"),
    ],
)
async def test_rollback_approval_rejects_invalid_update_evidence(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    evidence_change: str,
    expected_code: str,
) -> None:
    canvas, _, _, _, effect_id = await _prepared_rollback_effect(
        client,
        database,
        api_prefix,
        action="note.update",
        capability=Capability.CANVAS_NOTE_UPDATE_ROLLBACK,
    )
    async with database.sessions() as session:
        if evidence_change == "missing":
            await session.execute(
                delete(ControlledAgentReversibleWriteRollbackEvidence).where(
                    ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect_id
                )
            )
        else:
            values: dict[str, object]
            if evidence_change == "before_state":
                values = {"before_state": {"title": "Incomplete"}}
            elif evidence_change == "before_digest":
                values = {"before_digest": "f" * 64}
            else:
                values = {"after_digest": "f" * 64}
            await session.execute(
                update(ControlledAgentReversibleWriteRollbackEvidence)
                .where(ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect_id)
                .values(**values)
            )
        await session.commit()

    error = await _rollback_issue_error(database, canvas=canvas, effect_id=effect_id)
    assert error.code == expected_code
    assert error.message == "Rollback is not eligible."


@pytest.mark.parametrize(
    ("action", "capability"),
    [
        ("note.create", Capability.CANVAS_NOTE_CREATE),
        ("note.create", Capability.CANVAS_NOTE_UPDATE_ROLLBACK),
        ("note.update", Capability.CANVAS_NOTE_UPDATE),
        ("note.update", Capability.CANVAS_NOTE_CREATE_ROLLBACK),
    ],
)
async def test_rollback_approval_rejects_wrong_capability(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    action: str,
    capability: Capability,
) -> None:
    canvas, _, _, _, effect_id = await _prepared_rollback_effect(
        client, database, api_prefix, action=action, capability=capability
    )
    error = await _rollback_issue_error(database, canvas=canvas, effect_id=effect_id)
    assert error.code == "capability_missing"


@pytest.mark.parametrize("grant_state", ["expired", "revoked"])
async def test_rollback_approval_rejects_inactive_grant(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    grant_state: str,
) -> None:
    canvas, _, _, _, effect_id = await _prepared_rollback_effect(
        client,
        database,
        api_prefix,
        capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK,
    )
    async with database.sessions() as session:
        effect = await session.get(ControlledAgentReversibleWriteEffect, effect_id)
        assert effect is not None
        grant = await session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id
            )
        )
        assert grant is not None
        if grant_state == "expired":
            expired_at = datetime.now(UTC) - timedelta(minutes=1)
            issued_at = expired_at - timedelta(hours=1)
            await session.execute(
                update(ControlledAgentCapabilityGrant)
                .where(ControlledAgentCapabilityGrant.grant_id == grant.grant_id)
                .values(issued_at=issued_at, expires_at=expired_at)
            )
        else:
            await ControlledAgentRepository(session).append_revocation(
                RevocationRecord(
                    revocation_id=uuid.uuid4(),
                    subject_kind="grant",
                    subject_id=grant.grant_id,
                    user_id=grant.user_id,
                    workspace_id=grant.workspace_id,
                    execution_id=grant.execution_id,
                    revoked_at=datetime.now(UTC),
                    reason_code="rollback_test_revoked",
                )
            )
        await session.commit()

    error = await _rollback_issue_error(database, canvas=canvas, effect_id=effect_id)
    assert error.code == f"grant_{grant_state}"


async def test_rollback_approval_rejects_missing_note(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, _, _, applied, effect_id = await _prepared_rollback_effect(
        client,
        database,
        api_prefix,
        capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK,
    )
    async with database.engine.connect() as connection:
        await connection.execute(text("PRAGMA foreign_keys=OFF"))
        await connection.commit()
        await connection.execute(
            delete(CanvasNode).where(CanvasNode.id == uuid.UUID(applied.json()["noteId"]))
        )
        await connection.commit()
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.commit()

    error = await _rollback_issue_error(database, canvas=canvas, effect_id=effect_id)
    assert error.code == "note_missing"


async def test_rollback_approval_rejects_existing_successful_result(
    client: httpx.AsyncClient, database: Database, api_prefix: str
) -> None:
    canvas, _, _, _, effect_id = await _prepared_rollback_effect(
        client,
        database,
        api_prefix,
        capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK,
    )
    async with database.sessions() as session:
        issued = await ReversibleWriteRollbackApprovalService(session).issue(
            authenticated_user_id=SYSTEM_USER_ID,
            workspace_id=uuid.UUID(canvas["workspaceId"]),
            canvas_id=uuid.UUID(canvas["id"]),
            effect_id=effect_id,
            idempotency_key=f"rollback-before-result-{uuid.uuid4().hex}",
        )
        approval = issued.approval
        result = ControlledAgentReversibleWriteRollbackResult(
            rollback_result_id=uuid.uuid4(),
            rollback_approval_id=approval.rollback_approval_id,
            execution_id=approval.execution_id,
            user_id=approval.user_id,
            workspace_id=approval.workspace_id,
            canvas_id=approval.canvas_id,
            note_id=approval.note_id,
            proposal_id=approval.proposal_id,
            effect_id=approval.effect_id,
            forward_action=approval.forward_action,
            rollback_action=approval.rollback_action,
            rollback_target_kind=approval.rollback_target_kind,
            rollback_approval_digest=approval.approval_digest,
            scoped_idempotency_key=f"rollback-result-{uuid.uuid4().hex}",
            expected_pre_rollback_revision=approval.expected_current_revision,
            resulting_revision=None,
            pre_rollback_state_digest=approval.effect_after_state_digest,
            post_rollback_target_digest=approval.rollback_target_digest,
            trace_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )
        session.add(result)
        await session.commit()

    error = await _rollback_issue_error(
        database,
        canvas=canvas,
        effect_id=effect_id,
        expected_approvals=1,
        expected_results=1,
    )
    assert error.code == "already_rolled_back"
    async with database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackApproval)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ControlledAgentReversibleWriteRollbackResult)
            )
            == 1
        )


@pytest.mark.parametrize(
    ("effect_change", "expected_code"),
    [("unsupported", "unsupported_action"), ("unsuccessful", "effect_not_successful")],
)
async def test_rollback_approval_fails_closed_for_invalid_effect_state(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
    effect_change: str,
    expected_code: str,
) -> None:
    canvas, _, _, _, effect_id = await _prepared_rollback_effect(
        client,
        database,
        api_prefix,
        capability=Capability.CANVAS_NOTE_CREATE_ROLLBACK,
    )
    async with database.engine.connect() as connection:
        await connection.execute(text("PRAGMA foreign_keys=OFF"))
        await connection.execute(text("PRAGMA ignore_check_constraints=ON"))
        await connection.commit()
        values = (
            {"action": "unsupported"}
            if effect_change == "unsupported"
            else {"outcome": "failed"}
        )
        await connection.execute(
            update(ControlledAgentReversibleWriteEffect)
            .where(ControlledAgentReversibleWriteEffect.effect_id == effect_id)
            .values(**values)
        )
        await connection.commit()
        await connection.execute(text("PRAGMA ignore_check_constraints=OFF"))
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.commit()

    error = await _rollback_issue_error(database, canvas=canvas, effect_id=effect_id)
    assert error.code == expected_code
    assert error.message == "Rollback is not eligible."


def _state_digest(state: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
