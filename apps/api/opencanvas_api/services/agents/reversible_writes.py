"""Pure contracts for the first proposed reversible workspace-write boundary.

This module deliberately does not persist, authorize, route, or apply a workspace
change.  It only defines the frozen proposal that a later, separately reviewed
Terra checkpoint must reconstruct server-side before it can request approval.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from opencanvas_api.services.agents.contracts import (
    Capability,
    ContractModel,
    ResourceKind,
    ResourceScope,
    _require_aware_utc,
    canonical_json,
)

ROLLBACK_TARGET_DIGEST_DOMAIN = "controlled-agent.rollback-target.v1"
ROLLBACK_APPROVAL_DIGEST_DOMAIN = "controlled-agent.rollback-approval.v1"
ROLLBACK_APPROVAL_TTL = timedelta(minutes=15)


class ReversibleWriteAction(StrEnum):
    """The closed R3 action vocabulary approved for the initial effect scope."""

    NOTE_CREATE = "note.create"
    NOTE_UPDATE = "note.update"


class ReversibleWriteRollbackAction(StrEnum):
    """The closed inverse action vocabulary; it grants no generic undo authority."""

    NOTE_CREATE_ROLLBACK = "note.create.rollback"
    NOTE_UPDATE_ROLLBACK = "note.update.rollback"


class RollbackTargetAbsence(ContractModel):
    """The one server-owned target representation for a completed create rollback."""

    resource: Literal["canvas.note"] = "canvas.note"
    state: Literal["authoritative_absence"] = "authoritative_absence"


class RollbackApprovalDigestInput(ContractModel):
    """The full immutable authority payload for a rollback approval digest."""

    schema_version: Literal["controlled-agent-v1"] = "controlled-agent-v1"
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    note_id: uuid.UUID
    proposal_id: uuid.UUID
    effect_id: uuid.UUID
    forward_action: ReversibleWriteAction
    rollback_action: ReversibleWriteRollbackAction
    original_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_current_revision: int = Field(ge=0)
    effect_after_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_target_kind: Literal["authoritative_absence", "exact_prior_state"]
    rollback_target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_evidence_id: uuid.UUID | None = None
    grant_id: uuid.UUID
    scoped_idempotency_key: str = Field(min_length=1, max_length=128)
    expires_at: datetime

    _expires_at_is_utc = field_validator("expires_at")(_require_aware_utc)

    @model_validator(mode="after")
    def binds_only_one_closed_rollback_target(self) -> RollbackApprovalDigestInput:
        if self.forward_action is ReversibleWriteAction.NOTE_CREATE:
            if (
                self.rollback_action is not ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK
                or self.rollback_target_kind != "authoritative_absence"
                or self.rollback_evidence_id is not None
                or self.rollback_target_digest != authoritative_absence_digest()
                or self.expected_current_revision != 0
            ):
                raise ValueError("note.create rollback must use the canonical absence target")
        elif self.forward_action is ReversibleWriteAction.NOTE_UPDATE:
            if (
                self.rollback_action is not ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK
                or self.rollback_target_kind != "exact_prior_state"
                or self.rollback_evidence_id is None
                or self.expected_current_revision <= 0
            ):
                raise ValueError("note.update rollback must bind immutable prior-state evidence")
        else:
            raise ValueError("rollback action is unsupported")
        return self


def _domain_digest(domain: str, contract: ContractModel) -> str:
    return hashlib.sha256(f"{domain}\n{canonical_json(contract)}".encode()).hexdigest()


def authoritative_absence_digest() -> str:
    """Return the sole canonical target digest for note absence after create rollback."""

    return _domain_digest(ROLLBACK_TARGET_DIGEST_DOMAIN, RollbackTargetAbsence())


def rollback_approval_digest(input: RollbackApprovalDigestInput) -> str:
    """Hash exactly one server-derived rollback-approval authority payload."""

    return _domain_digest(ROLLBACK_APPROVAL_DIGEST_DOMAIN, input)


ROLLBACK_CAPABILITY_BY_ACTION = {
    ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK: Capability.CANVAS_NOTE_CREATE_ROLLBACK,
    ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK: Capability.CANVAS_NOTE_UPDATE_ROLLBACK,
}


def rollback_capability_for(action: ReversibleWriteRollbackAction) -> Capability:
    """Return the sole least-privilege capability for one closed rollback action."""

    return ROLLBACK_CAPABILITY_BY_ACTION[action]


class NotePreview(ContractModel):
    """Bounded, display-safe proposal content; it is not a persisted note."""

    title: str = Field(min_length=1, max_length=160)
    text: str = Field(max_length=20_000)


class ReversibleWriteProposal(ContractModel):
    """A server-owned, immutable plan for one future note effect.

    ``canvas`` identifies the one owned canvas that is both the destination and
    the scope boundary.  An update must bind one existing note node and exact
    revision.  A create binds the canvas revision and has no existing node.
    """

    contract_kind: str = "reversible_write_proposal"
    schema_version: str = "controlled-agent-v1"
    proposal_id: uuid.UUID
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas: ResourceScope
    action: ReversibleWriteAction
    capability: Capability
    destination: ResourceScope
    resource: ResourceScope | None = None
    preview: NotePreview
    created_at: datetime
    expires_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

    _proposal_times_are_utc = field_validator("created_at", "expires_at")(_require_aware_utc)

    @model_validator(mode="after")
    def binds_only_one_allowed_note_change(self) -> ReversibleWriteProposal:
        if self.expires_at <= self.created_at:
            raise ValueError("proposal expiry must follow creation")
        if self.canvas.kind is not ResourceKind.CANVAS:
            raise ValueError("proposal canvas must be a canvas resource")
        if self.destination != self.canvas:
            raise ValueError("proposal destination must equal its bound canvas")
        if self.action is ReversibleWriteAction.NOTE_CREATE:
            if self.capability is not Capability.CANVAS_NOTE_CREATE:
                raise ValueError("note.create requires canvas.note.create")
            if self.resource is not None:
                raise ValueError("note.create cannot bind an existing note resource")
        else:
            if self.capability is not Capability.CANVAS_NOTE_UPDATE:
                raise ValueError("note.update requires canvas.note.update")
            if self.resource is None or self.resource.kind is not ResourceKind.NODE:
                raise ValueError("note.update requires one bound note node")
            if self.resource.version is None:
                raise ValueError("note.update requires an exact note revision")
        return self


__all__ = [
    "ROLLBACK_APPROVAL_DIGEST_DOMAIN",
    "ROLLBACK_APPROVAL_TTL",
    "ROLLBACK_TARGET_DIGEST_DOMAIN",
    "NotePreview",
    "ReversibleWriteAction",
    "ReversibleWriteProposal",
    "ReversibleWriteRollbackAction",
    "RollbackApprovalDigestInput",
    "RollbackTargetAbsence",
    "authoritative_absence_digest",
    "rollback_approval_digest",
    "rollback_capability_for",
]
