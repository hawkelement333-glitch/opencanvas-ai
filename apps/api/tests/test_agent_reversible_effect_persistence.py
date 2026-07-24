from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteProposal,
    ControlledAgentReversibleWriteRollbackApproval,
    ControlledAgentReversibleWriteRollbackEvidence,
    ControlledAgentReversibleWriteRollbackResult,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
from opencanvas_api.services.agents.reversible_write_effects import (
    _note_digest,
    verify_completed_effect_state,
)
from tests.agent_fixtures import NOW, AgentBundle, make_agent_bundle


@dataclass(frozen=True, slots=True)
class EffectContext:
    bundle: AgentBundle
    canvas_id: uuid.UUID
    proposal_id: uuid.UUID
    action: str


async def _seed_effect_context(
    database: Database,
    *,
    bundle: AgentBundle | None = None,
    canvas_id: uuid.UUID | None = None,
    action: str = "note.create",
) -> EffectContext:
    bundle = bundle or make_agent_bundle()
    canvas_id = canvas_id or uuid.uuid4()
    proposal_id = uuid.uuid4()
    async with database.sessions() as session:
        await ControlledAgentRepository(session).append_bundle(
            execution=bundle.execution,
            context=bundle.context,
            plan=bundle.plan,
            grant=bundle.grant,
            approval=bundle.approval,
        )
        if canvas_id != (await session.scalar(select(Canvas.id).where(Canvas.id == canvas_id))):
            session.add(
                Canvas(
                    id=canvas_id,
                    workspace_id=bundle.execution.workspace_id,
                    name="Effect persistence canvas",
                )
            )
        session.add(
            ControlledAgentReversibleWriteProposal(
                proposal_id=proposal_id,
                execution_id=bundle.execution.execution_id,
                user_id=bundle.execution.user_id,
                workspace_id=bundle.execution.workspace_id,
                canvas_id=canvas_id,
                action=action,
                idempotency_key=f"proposal-{proposal_id}",
                payload_digest="a" * 64,
                payload={"title": "Bounded", "text": "Preview"},
                trace_id=uuid.uuid4(),
                created_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )
        )
        await session.commit()
    return EffectContext(bundle=bundle, canvas_id=canvas_id, proposal_id=proposal_id, action=action)


def _effect(context: EffectContext, **updates: object) -> ControlledAgentReversibleWriteEffect:
    values: dict[str, object] = {
        "effect_id": uuid.uuid4(),
        "execution_id": context.bundle.execution.execution_id,
        "proposal_id": context.proposal_id,
        "approval_id": context.bundle.approval.approval_id,
        "user_id": context.bundle.execution.user_id,
        "workspace_id": context.bundle.execution.workspace_id,
        "canvas_id": context.canvas_id,
        "idempotency_key": f"effect-{uuid.uuid4()}",
        "plan_digest": context.bundle.execution.plan_digest,
        "action": context.action,
        "destination_id": context.canvas_id,
        "resource_id": None,
        "expected_revision": None,
        "resulting_resource_id": uuid.uuid4(),
        "resulting_revision": 1,
        "before_digest": None,
        "after_digest": "b" * 64,
        "outcome": "succeeded",
        "trace_id": uuid.uuid4(),
        "created_at": NOW,
    }
    values.update(updates)
    return ControlledAgentReversibleWriteEffect(**values)


async def _persist(database: Database, effect: ControlledAgentReversibleWriteEffect) -> None:
    async with database.sessions() as session:
        session.add(effect)
        await session.commit()


async def _seed_update_effect(
    database: Database,
) -> tuple[EffectContext, ControlledAgentReversibleWriteEffect, uuid.UUID]:
    context = await _seed_effect_context(database, action="note.update")
    note_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            CanvasNode(
                id=note_id,
                canvas_id=context.canvas_id,
                type="note",
                title="Before title",
                text="Before text",
                position_x=0.0,
                position_y=0.0,
                revision=5,
            )
        )
        await session.commit()
    effect = _effect(
        context,
        resource_id=note_id,
        expected_revision=4,
        resulting_resource_id=note_id,
        resulting_revision=5,
        before_digest="a" * 64,
    )
    await _persist(database, effect)
    return context, effect, note_id


def _evidence(
    context: EffectContext,
    effect: ControlledAgentReversibleWriteEffect,
    note_id: uuid.UUID,
    **updates: object,
) -> ControlledAgentReversibleWriteRollbackEvidence:
    values: dict[str, object] = {
        "evidence_id": uuid.uuid4(),
        "effect_id": effect.effect_id,
        "execution_id": effect.execution_id,
        "proposal_id": effect.proposal_id,
        "user_id": context.bundle.execution.user_id,
        "workspace_id": context.bundle.execution.workspace_id,
        "canvas_id": context.canvas_id,
        "action": "note.update",
        "note_id": note_id,
        "pre_effect_revision": 4,
        "post_effect_revision": 5,
        "before_state": {"title": "Before title", "text": "Before text"},
        "before_digest": "a" * 64,
        "after_digest": "b" * 64,
        "created_at": NOW,
    }
    values.update(updates)
    return ControlledAgentReversibleWriteRollbackEvidence(**values)


async def _persist_evidence(
    database: Database, evidence: ControlledAgentReversibleWriteRollbackEvidence
) -> None:
    async with database.sessions() as session:
        session.add(evidence)
        await session.commit()


async def test_effect_persists_with_bound_proposal_approval_and_create_shape(
    database: Database,
) -> None:
    context = await _seed_effect_context(database)
    effect = _effect(context)

    await _persist(database, effect)

    async with database.sessions() as session:
        persisted = await session.scalar(
            select(ControlledAgentReversibleWriteEffect).where(
                ControlledAgentReversibleWriteEffect.effect_id == effect.effect_id
            )
        )
    assert persisted is not None
    assert persisted.proposal_id == context.proposal_id
    assert persisted.approval_id == context.bundle.approval.approval_id
    assert persisted.resource_id is None
    assert persisted.expected_revision is None


async def test_create_effect_state_verification_uses_only_legacy_note_digest(
    database: Database,
) -> None:
    context = await _seed_effect_context(database)
    note = CanvasNode(
        id=uuid.uuid4(),
        canvas_id=context.canvas_id,
        type="note",
        title="Created title",
        text="Created text",
        position_x=0.0,
        position_y=0.0,
        revision=1,
    )
    effect = _effect(
        context,
        resulting_resource_id=note.id,
        resulting_revision=note.revision,
        after_digest=_note_digest(note),
    )

    assert verify_completed_effect_state(effect, note)
    note.title = "Changed"
    assert not verify_completed_effect_state(effect, note)
    note.title = "Created title"
    note.revision = 2
    assert not verify_completed_effect_state(effect, note)
    assert not verify_completed_effect_state(_effect(context, resulting_resource_id=note.id), note)


async def test_effect_persists_with_update_resource_revision_and_evidence(
    database: Database,
) -> None:
    context = await _seed_effect_context(database, action="note.update")
    resource_id = uuid.uuid4()
    effect = _effect(
        context,
        action="note.update",
        resource_id=resource_id,
        expected_revision=4,
        resulting_resource_id=resource_id,
        resulting_revision=5,
        before_digest="c" * 64,
    )

    await _persist(database, effect)

    assert effect.resource_id == resource_id
    assert effect.expected_revision == 4
    assert effect.before_digest == "c" * 64


@pytest.mark.parametrize("field", ["plan_digest", "idempotency_key", "resulting_resource_id"])
async def test_effect_requires_persisted_fields(database: Database, field: str) -> None:
    context = await _seed_effect_context(database)
    effect = _effect(context)
    setattr(effect, field, None)

    with pytest.raises(IntegrityError):
        await _persist(database, effect)


@pytest.mark.parametrize("action", ["note.delete", "canvas.write", ""])
async def test_effect_rejects_unknown_actions(database: Database, action: str) -> None:
    context = await _seed_effect_context(database)

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(context, action=action))


@pytest.mark.parametrize("outcome", ["failed", "pending", ""])
async def test_effect_rejects_nonterminal_outcomes(database: Database, outcome: str) -> None:
    context = await _seed_effect_context(database)

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(context, outcome=outcome))


async def test_effect_rejects_unknown_proposal_or_canvas(database: Database) -> None:
    context = await _seed_effect_context(database)
    with pytest.raises(IntegrityError):
        await _persist(database, _effect(context, proposal_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await _persist(database, _effect(context, canvas_id=uuid.uuid4()))


@pytest.mark.parametrize("field", ["user_id", "workspace_id"])
async def test_effect_rejects_cross_owner_execution_scope(database: Database, field: str) -> None:
    context = await _seed_effect_context(database)

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(context, **{field: uuid.uuid4()}))


async def test_effect_rejects_cross_proposal_scope_and_cross_canvas_scope(
    database: Database,
) -> None:
    first = await _seed_effect_context(database)
    second = await _seed_effect_context(database, canvas_id=first.canvas_id)

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(first, proposal_id=second.proposal_id))

    other_canvas = await _seed_effect_context(database)
    with pytest.raises(IntegrityError):
        await _persist(database, _effect(first, canvas_id=other_canvas.canvas_id))


async def test_effect_rejects_cross_approval_scope(database: Database) -> None:
    first = await _seed_effect_context(database)
    second = await _seed_effect_context(database, canvas_id=first.canvas_id)

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(first, approval_id=second.bundle.approval.approval_id))


@pytest.mark.parametrize(
    "updates",
    [
        {"resource_id": uuid.uuid4()},
        {"expected_revision": 2},
        {"before_digest": "c" * 64},
    ],
)
async def test_create_effect_rejects_update_only_resource_fields(
    database: Database, updates: dict[str, object]
) -> None:
    context = await _seed_effect_context(database)

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(context, **updates))


@pytest.mark.parametrize(
    "updates",
    [
        {"resource_id": None},
        {"expected_revision": None},
        {"before_digest": None},
        {"resulting_resource_id": uuid.uuid4()},
    ],
)
async def test_update_effect_rejects_incomplete_or_mismatched_resource_shape(
    database: Database, updates: dict[str, object]
) -> None:
    context = await _seed_effect_context(database, action="note.update")
    resource_id = uuid.uuid4()
    effect = _effect(
        context,
        resource_id=resource_id,
        expected_revision=4,
        resulting_resource_id=resource_id,
        resulting_revision=5,
        before_digest="c" * 64,
    )
    for field, value in updates.items():
        setattr(effect, field, value)

    with pytest.raises(IntegrityError):
        await _persist(database, effect)


async def test_effect_idempotency_and_result_identities_are_unique_per_scope(
    database: Database,
) -> None:
    first = await _seed_effect_context(database)
    second = await _seed_effect_context(database, canvas_id=first.canvas_id)
    shared_key = "same-effect-key"
    await _persist(database, _effect(first, idempotency_key=shared_key))

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(second, idempotency_key=shared_key))

    third = await _seed_effect_context(database, canvas_id=first.canvas_id)
    await _persist(database, _effect(third, idempotency_key="different-effect-key"))

    with pytest.raises(IntegrityError):
        await _persist(database, _effect(third, execution_id=first.bundle.execution.execution_id))
    with pytest.raises(IntegrityError):
        await _persist(database, _effect(third, proposal_id=first.proposal_id))


async def test_rollback_evidence_persists_exact_canonical_prior_note_state(
    database: Database,
) -> None:
    context, effect, note_id = await _seed_update_effect(database)
    evidence = _evidence(context, effect, note_id)
    await _persist_evidence(database, evidence)
    assert evidence.before_state == {"title": "Before title", "text": "Before text"}
    assert evidence.pre_effect_revision == 4 and evidence.post_effect_revision == 5


@pytest.mark.parametrize(
    "updates",
    [
        {"before_digest": None},
        {"after_digest": None},
        {"post_effect_revision": 6},
        {"action": "note.create"},
        {"note_id": uuid.uuid4()},
        {"user_id": uuid.uuid4()},
        {"workspace_id": uuid.uuid4()},
        {"canvas_id": uuid.uuid4()},
    ],
)
async def test_rollback_evidence_rejects_invalid_required_scope_and_revision_bindings(
    database: Database, updates: dict[str, object]
) -> None:
    context, effect, note_id = await _seed_update_effect(database)
    evidence = _evidence(context, effect, note_id)
    for field, value in updates.items():
        setattr(evidence, field, value)
    with pytest.raises(IntegrityError):
        await _persist_evidence(database, evidence)


async def test_rollback_evidence_rejects_json_null_before_state(database: Database) -> None:
    context, effect, note_id = await _seed_update_effect(database)
    evidence = _evidence(context, effect, note_id, before_state=None)
    with pytest.raises(IntegrityError, match="before_state_object"):
        await _persist_evidence(database, evidence)


async def test_rollback_evidence_is_one_per_effect_and_append_only(database: Database) -> None:
    context, effect, note_id = await _seed_update_effect(database)
    evidence = _evidence(context, effect, note_id)
    await _persist_evidence(database, evidence)
    evidence_id = evidence.evidence_id
    with pytest.raises(IntegrityError):
        await _persist_evidence(database, _evidence(context, effect, note_id))
    async with database.sessions() as session:
        persisted = await session.get(ControlledAgentReversibleWriteRollbackEvidence, evidence_id)
        assert persisted is not None
        persisted.before_state = {"title": "Changed", "text": "Changed"}
        with pytest.raises(ValueError, match="append-only"):
            await session.commit()
        await session.rollback()
    async with database.sessions() as session:
        persisted = await session.get(ControlledAgentReversibleWriteRollbackEvidence, evidence_id)
        assert persisted is not None
        await session.delete(persisted)
        with pytest.raises(ValueError, match="append-only"):
            await session.commit()


@dataclass(frozen=True, slots=True)
class RollbackAuthorityContext:
    context: EffectContext
    effect: ControlledAgentReversibleWriteEffect
    note_id: uuid.UUID
    evidence: ControlledAgentReversibleWriteRollbackEvidence | None


async def _seed_rollback_authority_context(
    database: Database,
    *,
    action: str,
    bundle: AgentBundle | None = None,
    canvas_id: uuid.UUID | None = None,
) -> RollbackAuthorityContext:
    context = await _seed_effect_context(
        database,
        bundle=bundle,
        canvas_id=canvas_id,
        action=action,
    )
    note_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            CanvasNode(
                id=note_id,
                canvas_id=context.canvas_id,
                type="note",
                title="Before title" if action == "note.update" else "Created title",
                text="Before text" if action == "note.update" else "Created text",
                position_x=0.0,
                position_y=0.0,
                revision=5 if action == "note.update" else 1,
            )
        )
        await session.commit()
    effect = _effect(
        context,
        action=action,
        resource_id=note_id if action == "note.update" else None,
        expected_revision=4 if action == "note.update" else None,
        resulting_resource_id=note_id,
        resulting_revision=5 if action == "note.update" else 1,
        before_digest="a" * 64 if action == "note.update" else None,
    )
    await _persist(database, effect)
    evidence = _evidence(context, effect, note_id) if action == "note.update" else None
    if evidence:
        await _persist_evidence(database, evidence)
    return RollbackAuthorityContext(context, effect, note_id, evidence)


def _rollback_approval(
    authority: RollbackAuthorityContext, **updates: object
) -> ControlledAgentReversibleWriteRollbackApproval:
    effect = authority.effect
    is_update = effect.action == "note.update"
    values: dict[str, object] = {
        "rollback_approval_id": uuid.uuid4(),
        "execution_id": effect.execution_id,
        "user_id": effect.user_id,
        "workspace_id": effect.workspace_id,
        "canvas_id": effect.canvas_id,
        "note_id": authority.note_id,
        "proposal_id": effect.proposal_id,
        "effect_id": effect.effect_id,
        "forward_action": effect.action,
        "rollback_action": "note.update.rollback" if is_update else "note.create.rollback",
        "rollback_evidence_id": authority.evidence.evidence_id if authority.evidence else None,
        "original_plan_digest": effect.plan_digest,
        "expected_current_revision": effect.resulting_revision,
        "effect_after_state_digest": effect.after_digest,
        "rollback_target_kind": "exact_prior_state" if is_update else "authoritative_absence",
        "rollback_target_digest": "a" * 64 if is_update else "c" * 64,
        "grant_id": authority.context.bundle.grant.grant_id,
        "scoped_idempotency_key": f"rollback-approval-{uuid.uuid4()}",
        "approval_digest": "d" * 64,
        "expires_at": NOW + timedelta(minutes=5),
        "created_at": NOW,
    }
    values.update(updates)
    return ControlledAgentReversibleWriteRollbackApproval(**values)


def _rollback_result(
    authority: RollbackAuthorityContext,
    approval: ControlledAgentReversibleWriteRollbackApproval,
    **updates: object,
) -> ControlledAgentReversibleWriteRollbackResult:
    effect = authority.effect
    is_update = effect.action == "note.update"
    values: dict[str, object] = {
        "rollback_result_id": uuid.uuid4(),
        "rollback_approval_id": approval.rollback_approval_id,
        "execution_id": effect.execution_id,
        "user_id": effect.user_id,
        "workspace_id": effect.workspace_id,
        "canvas_id": effect.canvas_id,
        "note_id": authority.note_id,
        "proposal_id": effect.proposal_id,
        "effect_id": effect.effect_id,
        "forward_action": effect.action,
        "rollback_action": approval.rollback_action,
        "rollback_target_kind": approval.rollback_target_kind,
        "rollback_approval_digest": approval.approval_digest,
        "scoped_idempotency_key": f"rollback-result-{uuid.uuid4()}",
        "expected_pre_rollback_revision": effect.resulting_revision,
        "resulting_revision": effect.resulting_revision + 1 if is_update else None,
        "pre_rollback_state_digest": effect.after_digest,
        "post_rollback_target_digest": approval.rollback_target_digest,
        "trace_id": uuid.uuid4(),
        "created_at": NOW,
    }
    values.update(updates)
    return ControlledAgentReversibleWriteRollbackResult(**values)


async def _persist_authority(database: Database, record: object) -> None:
    async with database.sessions() as session:
        session.add(record)
        await session.commit()


@pytest.mark.parametrize("action", ["note.create", "note.update"])
async def test_rollback_approval_persists_the_two_closed_authority_forms(
    database: Database, action: str
) -> None:
    authority = await _seed_rollback_authority_context(database, action=action)
    approval = _rollback_approval(authority)

    await _persist_authority(database, approval)

    assert approval.forward_action == action
    assert approval.rollback_evidence_id == (
        authority.evidence.evidence_id if authority.evidence else None
    )
    assert approval.expected_current_revision > 0


@pytest.mark.parametrize(
    "updates",
    [
        {"forward_action": "note.delete"},
        {"rollback_action": "note.delete.rollback"},
        {"rollback_target_kind": "arbitrary_state"},
        {"rollback_action": "note.update.rollback"},
        {"expected_current_revision": 0},
        {"expected_current_revision": -1},
        {"original_plan_digest": "bad"},
        {"effect_after_state_digest": "B" * 64},
        {"rollback_target_digest": "short"},
        {"scoped_idempotency_key": ""},
        {"approval_digest": ""},
        {"expires_at": NOW},
    ],
)
async def test_rollback_approval_rejects_invalid_closed_contract(
    database: Database, updates: dict[str, object]
) -> None:
    authority = await _seed_rollback_authority_context(database, action="note.create")
    with pytest.raises(IntegrityError):
        await _persist_authority(database, _rollback_approval(authority, **updates))


async def test_rollback_approval_rejects_invalid_evidence_shape_and_scope(
    database: Database,
) -> None:
    created = await _seed_rollback_authority_context(database, action="note.create")
    updated = await _seed_rollback_authority_context(database, action="note.update")
    assert updated.evidence is not None

    with pytest.raises(IntegrityError):
        await _persist_authority(
            database,
            _rollback_approval(created, rollback_evidence_id=updated.evidence.evidence_id),
        )
    with pytest.raises(IntegrityError):
        await _persist_authority(
            database,
            _rollback_approval(updated, rollback_evidence_id=None),
        )
    with pytest.raises(IntegrityError):
        await _persist_authority(
            database,
            _rollback_approval(updated, proposal_id=created.effect.proposal_id),
        )
    with pytest.raises(IntegrityError):
        await _persist_authority(database, _rollback_approval(updated, note_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await _persist_authority(database, _rollback_approval(updated, grant_id=uuid.uuid4()))


@pytest.mark.parametrize("action", ["note.create", "note.update"])
async def test_rollback_result_persists_the_two_closed_success_forms(
    database: Database, action: str
) -> None:
    authority = await _seed_rollback_authority_context(database, action=action)
    approval = _rollback_approval(authority)
    await _persist_authority(database, approval)
    result = _rollback_result(authority, approval)

    await _persist_authority(database, result)

    assert result.rollback_approval_id == approval.rollback_approval_id
    if action == "note.create":
        assert result.resulting_revision is None
    else:
        assert result.resulting_revision is not None and result.resulting_revision > 0


@pytest.mark.parametrize(
    "updates",
    [
        {"forward_action": "note.delete"},
        {"rollback_action": "note.update.rollback"},
        {"rollback_target_kind": "arbitrary_state"},
        {"expected_pre_rollback_revision": 0},
        {"resulting_revision": 1},
        {"pre_rollback_state_digest": "bad"},
        {"post_rollback_target_digest": "BAD" * 22},
        {"scoped_idempotency_key": ""},
    ],
)
async def test_create_rollback_result_rejects_invalid_closed_contract(
    database: Database, updates: dict[str, object]
) -> None:
    authority = await _seed_rollback_authority_context(database, action="note.create")
    approval = _rollback_approval(authority)
    await _persist_authority(database, approval)
    with pytest.raises(IntegrityError):
        await _persist_authority(database, _rollback_result(authority, approval, **updates))


async def test_update_rollback_result_rejects_missing_resulting_revision(
    database: Database,
) -> None:
    authority = await _seed_rollback_authority_context(database, action="note.update")
    approval = _rollback_approval(authority)
    await _persist_authority(database, approval)
    with pytest.raises(IntegrityError):
        await _persist_authority(
            database, _rollback_result(authority, approval, resulting_revision=None)
        )


async def test_rollback_result_enforces_success_identity_uniqueness_and_append_only(
    database: Database,
) -> None:
    authority = await _seed_rollback_authority_context(database, action="note.update")
    approval = _rollback_approval(authority)
    await _persist_authority(database, approval)
    result = _rollback_result(authority, approval, scoped_idempotency_key="same-result-key")
    await _persist_authority(database, result)

    with pytest.raises(IntegrityError):
        await _persist_authority(database, _rollback_result(authority, approval))
    second_approval = _rollback_approval(authority)
    await _persist_authority(database, second_approval)
    with pytest.raises(IntegrityError):
        await _persist_authority(database, _rollback_result(authority, second_approval))
    other_authority = await _seed_rollback_authority_context(
        database,
        action="note.update",
        bundle=make_agent_bundle(
            user_id=authority.effect.user_id,
            workspace_id=authority.effect.workspace_id,
        ),
        canvas_id=authority.effect.canvas_id,
    )
    other_approval = _rollback_approval(other_authority)
    await _persist_authority(database, other_approval)
    with pytest.raises(IntegrityError):
        await _persist_authority(
            database,
            _rollback_result(
                other_authority,
                other_approval,
                scoped_idempotency_key="same-result-key",
            ),
        )

    async with database.sessions() as session:
        persisted = await session.get(
            ControlledAgentReversibleWriteRollbackResult, result.rollback_result_id
        )
        assert persisted is not None
        persisted.rollback_approval_digest = "e" * 64
        with pytest.raises(ValueError, match="append-only"):
            await session.commit()
        await session.rollback()
    async with database.sessions() as session:
        persisted = await session.get(
            ControlledAgentReversibleWriteRollbackResult, result.rollback_result_id
        )
        assert persisted is not None
        await session.delete(persisted)
        with pytest.raises(ValueError, match="append-only"):
            await session.commit()
