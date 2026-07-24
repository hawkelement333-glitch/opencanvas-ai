"""Pure contracts for the first proposed reversible workspace-write boundary.

This module deliberately does not persist, authorize, route, or apply a workspace
change.  It only defines the frozen proposal that a later, separately reviewed
Terra checkpoint must reconstruct server-side before it can request approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from opencanvas_api.services.agents.contracts import (
    Capability,
    ContractModel,
    ResourceKind,
    ResourceScope,
    _require_aware_utc,
)


class ReversibleWriteAction(StrEnum):
    """The closed R3 action vocabulary approved for the initial effect scope."""

    NOTE_CREATE = "note.create"
    NOTE_UPDATE = "note.update"


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


__all__ = ["NotePreview", "ReversibleWriteAction", "ReversibleWriteProposal"]
