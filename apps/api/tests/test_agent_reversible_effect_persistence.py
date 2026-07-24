from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from opencanvas_api.db.models import (
    Canvas,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteProposal,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
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
