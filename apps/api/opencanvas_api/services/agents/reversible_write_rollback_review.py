"""Read-only, server-authoritative eligibility review for reversible note effects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    ControlledAgentCapabilityGrant,
    ControlledAgentGrantRevocation,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteProposal,
    ControlledAgentReversibleWriteRollbackEvidence,
    ControlledAgentReversibleWriteRollbackResult,
    Workspace,
)
from opencanvas_api.services.agents.contracts import Capability, CapabilityGrant, ResourceKind
from opencanvas_api.services.agents.persistence import (
    AgentContractIntegrityError,
    ControlledAgentRepository,
)
from opencanvas_api.services.agents.reversible_write_effects import (
    _note_state_digest,
    verify_completed_effect_state,
)
from opencanvas_api.services.agents.reversible_writes import (
    ReversibleWriteAction,
    ReversibleWriteRollbackAction,
    rollback_capability_for,
)


@dataclass(frozen=True)
class RollbackEligibilityReview:
    effect_id: uuid.UUID
    forward_action: str | None = None
    note_id: uuid.UUID | None = None
    effect_revision: int | None = None
    current_revision: int | None = None
    rollback_action: str | None = None
    rollback_target_kind: str | None = None
    required_capability: str | None = None
    eligible: bool = False
    approval_required: bool = True
    denial_reason: str | None = None
    conflict: bool = False


class ReversibleWriteRollbackReviewService:
    """Derive rollback eligibility solely from immutable records and live note state."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self.session = session
        self.now = now or datetime.now(UTC)

    async def review(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        effect_id: uuid.UUID,
    ) -> RollbackEligibilityReview:
        def deny(
            reason: str,
            review: RollbackEligibilityReview | None = None,
            *,
            conflict: bool = False,
        ) -> RollbackEligibilityReview:
            return replace(
                review or RollbackEligibilityReview(effect_id=effect_id),
                denial_reason=reason,
                conflict=conflict,
            )

        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.owner_id == authenticated_user_id,
            )
        )
        if canvas is None:
            return deny("scope_mismatch")

        effect = await self.session.get(ControlledAgentReversibleWriteEffect, effect_id)
        if effect is None:
            return deny("effect_not_found")
        if (
            effect.user_id != authenticated_user_id
            or effect.workspace_id != workspace_id
            or effect.canvas_id != canvas.id
        ):
            return deny("scope_mismatch")
        base = RollbackEligibilityReview(
            effect_id=effect_id,
            forward_action=effect.action,
            note_id=effect.resulting_resource_id,
            effect_revision=effect.resulting_revision,
        )
        if effect.outcome != "succeeded":
            return deny("effect_not_successful", base)
        if effect.action == ReversibleWriteAction.NOTE_CREATE.value:
            rollback_action = ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK
            target_kind = "authoritative_absence"
        elif effect.action == ReversibleWriteAction.NOTE_UPDATE.value:
            rollback_action = ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK
            target_kind = "exact_prior_state"
        else:
            return deny("unsupported_action", base)
        capability = rollback_capability_for(rollback_action)
        derived = replace(
            base,
            rollback_action=rollback_action.value,
            rollback_target_kind=target_kind,
            required_capability=capability.value,
        )

        proposal = await self.session.get(
            ControlledAgentReversibleWriteProposal, effect.proposal_id
        )
        if proposal is None or (
            proposal.execution_id != effect.execution_id
            or proposal.user_id != effect.user_id
            or proposal.workspace_id != effect.workspace_id
            or proposal.canvas_id != effect.canvas_id
            or proposal.action != effect.action
        ):
            return deny("proposal_mismatch", derived)
        if proposal.payload_digest != effect.plan_digest:
            return deny("plan_mismatch", derived)

        note = await self.session.scalar(
            select(CanvasNode).where(
                CanvasNode.id == effect.resulting_resource_id,
                CanvasNode.canvas_id == canvas.id,
                CanvasNode.type == "note",
            )
        )
        if note is None:
            return deny("note_missing", derived)
        current = replace(derived, current_revision=note.revision)
        if note.revision != effect.resulting_revision:
            return deny("revision_conflict", current, conflict=True)

        evidence: ControlledAgentReversibleWriteRollbackEvidence | None = None
        if effect.action == ReversibleWriteAction.NOTE_UPDATE.value:
            evidence = await self.session.scalar(
                select(ControlledAgentReversibleWriteRollbackEvidence).where(
                    ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect.effect_id
                )
            )
            if evidence is None:
                return deny("rollback_evidence_missing", current)
            if (
                evidence.execution_id != effect.execution_id
                or evidence.proposal_id != effect.proposal_id
                or evidence.user_id != effect.user_id
                or evidence.workspace_id != effect.workspace_id
                or evidence.canvas_id != effect.canvas_id
                or evidence.note_id != note.id
                or evidence.action != effect.action
                or evidence.post_effect_revision != effect.resulting_revision
                or evidence.after_digest != effect.after_digest
            ):
                return deny("rollback_evidence_invalid", current)
            before_state = evidence.before_state
            title = before_state.get("title") if isinstance(before_state, dict) else None
            text = before_state.get("text") if isinstance(before_state, dict) else None
            if (
                not isinstance(before_state, dict)
                or set(before_state) != {"title", "text"}
                or not isinstance(title, str)
                or not isinstance(text, str)
                or _note_state_digest({"title": title, "text": text}) != evidence.before_digest
            ):
                return deny("rollback_evidence_invalid", current)
        if not verify_completed_effect_state(effect, note, evidence):
            return deny("state_conflict", current, conflict=True)

        result = await self.session.scalar(
            select(ControlledAgentReversibleWriteRollbackResult.rollback_result_id).where(
                ControlledAgentReversibleWriteRollbackResult.effect_id == effect.effect_id
            )
        )
        if result is not None:
            return deny("already_rolled_back", current)
        grant_reason = await self._grant_reason(effect, note, capability)
        if grant_reason is not None:
            return deny(grant_reason, current)
        return replace(current, eligible=True)

    async def _grant_reason(
        self,
        effect: ControlledAgentReversibleWriteEffect,
        note: CanvasNode,
        capability: Capability,
    ) -> str | None:
        row = await self.session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == effect.execution_id,
                ControlledAgentCapabilityGrant.user_id == effect.user_id,
                ControlledAgentCapabilityGrant.workspace_id == effect.workspace_id,
            )
        )
        if row is None:
            return "capability_missing"
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if self.now >= expires_at:
            return "grant_expired"
        revoked = await self.session.scalar(
            select(ControlledAgentGrantRevocation.revocation_id).where(
                ControlledAgentGrantRevocation.grant_id == row.grant_id,
                ControlledAgentGrantRevocation.execution_id == effect.execution_id,
                ControlledAgentGrantRevocation.user_id == effect.user_id,
                ControlledAgentGrantRevocation.workspace_id == effect.workspace_id,
            )
        )
        if revoked is not None:
            return "grant_revoked"
        try:
            grant = ControlledAgentRepository._load_contract(
                CapabilityGrant, row.payload, row.payload_digest
            )
        except AgentContractIntegrityError:
            return "grant_scope_mismatch"
        if (
            grant.grant_id != row.grant_id
            or grant.execution_id != effect.execution_id
            or grant.user_id != effect.user_id
            or grant.workspace_id != effect.workspace_id
        ):
            return "grant_scope_mismatch"
        if capability not in grant.capabilities:
            return "capability_missing"
        if not any(
            scope.kind is ResourceKind.NODE
            and scope.resource_id == note.id
            and scope.version == effect.resulting_revision
            for scope in grant.resources
        ):
            return "grant_scope_mismatch"
        return None


__all__ = ["ReversibleWriteRollbackReviewService", "RollbackEligibilityReview"]
