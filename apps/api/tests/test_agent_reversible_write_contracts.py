from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from opencanvas_api.services.agents.contracts import (
    Capability,
    ResourceKind,
    ResourceScope,
    contract_digest,
)
from opencanvas_api.services.agents.reversible_writes import (
    NotePreview,
    ReversibleWriteAction,
    ReversibleWriteProposal,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
CANVAS = ResourceScope(kind=ResourceKind.CANVAS, resource_id=uuid.uuid4(), version=4)
NOTE = ResourceScope(kind=ResourceKind.NODE, resource_id=uuid.uuid4(), version=8)


def proposal(
    *, action: ReversibleWriteAction = ReversibleWriteAction.NOTE_CREATE
) -> ReversibleWriteProposal:
    return ReversibleWriteProposal(
        proposal_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        canvas=CANVAS,
        action=action,
        capability=(
            Capability.CANVAS_NOTE_CREATE
            if action is ReversibleWriteAction.NOTE_CREATE
            else Capability.CANVAS_NOTE_UPDATE
        ),
        destination=CANVAS,
        resource=NOTE if action is ReversibleWriteAction.NOTE_UPDATE else None,
        preview=NotePreview(title="Bounded title", text="Bounded preview"),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        idempotency_key="proposal_request_1",
    )


def test_proposal_digest_is_stable_and_binds_action_destination_resource_and_revision() -> None:
    baseline = proposal(action=ReversibleWriteAction.NOTE_UPDATE)
    equivalent = ReversibleWriteProposal.model_validate(baseline.model_dump())

    assert contract_digest(baseline) == contract_digest(equivalent)
    assert contract_digest(baseline) != contract_digest(
        baseline.model_copy(
            update={
                "action": ReversibleWriteAction.NOTE_CREATE,
                "resource": None,
                "capability": Capability.CANVAS_NOTE_CREATE,
            }
        )
    )
    assert contract_digest(baseline) != contract_digest(
        baseline.model_copy(update={"resource": NOTE.model_copy(update={"version": 9})})
    )


@pytest.mark.parametrize(
    "changes, message",
    [
        (
            {
                "destination": ResourceScope(
                    kind=ResourceKind.CANVAS, resource_id=uuid.uuid4(), version=4
                )
            },
            "destination",
        ),
        ({"capability": Capability.CANVAS_NOTE_UPDATE}, "note.create requires"),
        ({"resource": NOTE}, "note.create cannot"),
    ],
)
def test_create_proposal_rejects_altered_destination_or_capability(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ReversibleWriteProposal.model_validate(proposal().model_dump() | changes)


def test_update_requires_a_bound_note_and_exact_revision() -> None:
    update = proposal(action=ReversibleWriteAction.NOTE_UPDATE)

    with pytest.raises(ValidationError, match="bound note"):
        ReversibleWriteProposal.model_validate(update.model_dump() | {"resource": None})
    with pytest.raises(ValidationError, match="exact note revision"):
        ReversibleWriteProposal.model_validate(
            update.model_dump() | {"resource": NOTE.model_copy(update={"version": None})}
        )


def test_unknown_action_fails_closed() -> None:
    data = proposal().model_dump()
    data["action"] = "note.delete"

    with pytest.raises(ValidationError):
        ReversibleWriteProposal.model_validate(data)
