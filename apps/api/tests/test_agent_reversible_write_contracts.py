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
    ROLLBACK_APPROVAL_DIGEST_DOMAIN,
    ROLLBACK_APPROVAL_TTL,
    ROLLBACK_TARGET_DIGEST_DOMAIN,
    NotePreview,
    ReversibleWriteAction,
    ReversibleWriteProposal,
    ReversibleWriteRollbackAction,
    RollbackApprovalDigestInput,
    RollbackTargetAbsence,
    authoritative_absence_digest,
    rollback_approval_digest,
    rollback_capability_for,
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


@pytest.mark.parametrize(
    ("action", "capability"),
    [
        (
            ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK,
            Capability.CANVAS_NOTE_CREATE_ROLLBACK,
        ),
        (
            ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK,
            Capability.CANVAS_NOTE_UPDATE_ROLLBACK,
        ),
    ],
)
def test_rollback_capabilities_are_closed_and_action_specific(
    action: ReversibleWriteRollbackAction, capability: Capability
) -> None:
    assert rollback_capability_for(action) is capability
    assert capability.value in {item.value for item in Capability}


def test_forward_and_cross_rollback_capabilities_cannot_substitute() -> None:
    assert (
        rollback_capability_for(ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK)
        is not Capability.CANVAS_NOTE_CREATE
    )
    assert (
        rollback_capability_for(ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK)
        is not Capability.CANVAS_NOTE_UPDATE
    )
    assert rollback_capability_for(
        ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK
    ) is not rollback_capability_for(ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK)


def test_unknown_rollback_capability_fails_closed() -> None:
    with pytest.raises(ValueError):
        Capability("canvas.note.rollback")


def _rollback_digest_input(**updates: object) -> RollbackApprovalDigestInput:
    values: dict[str, object] = {
        "execution_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "canvas_id": uuid.uuid4(),
        "note_id": uuid.uuid4(),
        "proposal_id": uuid.uuid4(),
        "effect_id": uuid.uuid4(),
        "forward_action": ReversibleWriteAction.NOTE_CREATE,
        "rollback_action": ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK,
        "original_plan_digest": "a" * 64,
        "expected_current_revision": 0,
        "effect_after_state_digest": "b" * 64,
        "rollback_target_kind": "authoritative_absence",
        "rollback_target_digest": authoritative_absence_digest(),
        "rollback_evidence_id": None,
        "grant_id": uuid.uuid4(),
        "scoped_idempotency_key": "rollback-approval-key",
        "expires_at": NOW + ROLLBACK_APPROVAL_TTL,
    }
    values.update(updates)
    return RollbackApprovalDigestInput(**values)


def test_authoritative_absence_digest_is_stable_domain_separated_and_not_note_state() -> None:
    digest = authoritative_absence_digest()
    assert digest == authoritative_absence_digest()
    assert len(digest) == 64 and digest == digest.lower()
    assert digest != _state_digest({"title": "", "text": ""})
    assert digest != _domain_digest_for_test(
        ROLLBACK_TARGET_DIGEST_DOMAIN,
        RollbackTargetAbsence(resource="canvas.note", state="authoritative_absence"),
        suffix="changed",
    )
    with pytest.raises(ValidationError, match="canonical absence"):
        _rollback_digest_input(rollback_target_digest="f" * 64)


def test_rollback_approval_digest_binds_all_authoritative_fields_and_uses_fixed_ttl() -> None:
    baseline = _rollback_digest_input()
    assert rollback_approval_digest(baseline) == rollback_approval_digest(
        RollbackApprovalDigestInput.model_validate(baseline.model_dump())
    )
    assert baseline.expires_at - NOW == ROLLBACK_APPROVAL_TTL == timedelta(minutes=15)
    for field, value in (
        ("effect_id", uuid.uuid4()),
        ("expected_current_revision", 1),
        ("rollback_evidence_id", uuid.uuid4()),
        ("scoped_idempotency_key", "different-key"),
    ):
        assert rollback_approval_digest(baseline) != rollback_approval_digest(
            baseline.model_copy(update={field: value})
        )
    assert ROLLBACK_APPROVAL_DIGEST_DOMAIN != ROLLBACK_TARGET_DIGEST_DOMAIN


def _state_digest(state: dict[str, str]) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _domain_digest_for_test(domain: str, contract: object, *, suffix: str) -> str:
    import hashlib

    return hashlib.sha256(f"{domain}{suffix}\n{contract}".encode()).hexdigest()
